"""
run_all.py — Direct connector runner for development and manual testing.

For production use, trigger a refresh via the API server:
    POST http://127.0.0.1:8000/api/refresh/start

This script is useful for:
  - Running a single institution outside the API lifecycle
  - Debugging connector issues without the full orchestrator
  - Forcing a refresh regardless of cadence

Usage:
    python run_all.py                        # Run all connectors (respects cadence)
    python run_all.py --force                # Ignore cadence, force all
    python run_all.py --institutions chase   # Run a specific institution
"""

import logging
import sys
import threading
from datetime import datetime
from backend.ipc import request_credentials
from backend.result_writer import persist_connector_result
from extractors import CONNECTOR_REGISTRY, get_connector
from config.logging_config import setup_logging

from dotenv import load_dotenv

load_dotenv()
setup_logging()

log = logging.getLogger("sentry")



def run_extractors(
    institutions: list[str] | None = None,
    force: bool = False,
    credentials: dict | None = None,
    dev_mode: bool = False,
) -> dict:
    """Run connectors sequentially. Each connector opens one tab, closes it,
    then the next connector runs. Chrome is never shared concurrently.
    """
    results = {}
    targets = institutions or list(CONNECTOR_REGISTRY.keys())
    _persist_thread: threading.Thread | None = None

    for inst_id in targets:
        if inst_id not in CONNECTOR_REGISTRY:
            log.warning("No connector registered for: %s", inst_id)
            continue

        print(f"\n  ── {inst_id.upper()} {'─' * (44 - len(inst_id))}")
        try:
            connector = get_connector(inst_id)
            # Feed credentials from broker if present
            inst_creds = credentials.get(inst_id) if credentials else None
            result = connector.run(
                force=force, credentials=inst_creds, dev_mode=dev_mode
            )
            results[inst_id] = result

            status_icon = {"success": "✅", "skipped": "⏭️", "error": "❌"}.get(
                result.status, "?"
            )
            print(f"  {status_icon}  Status: {result.status}")

            if result.files:
                print(f"  📄  {len(result.files)} file(s):")
                for f in result.files:
                    print(f"       • {f.name}")
            if result.balances:
                print(f"  💰  {len(result.balances)} balance(s):")
                for last4, info in result.balances.items():
                    print(
                        f"       • [{last4}] {info.get('name', '?')}: "
                        f"{info.get('balance', '?')}"
                    )
            if result.loan_details:
                print(f"  🏦  {len(result.loan_details)} loan detail(s)")
            if result.error:
                print(f"  ⚠   {result.error}")

            # Persist results to SQLite in a background thread so the next
            # connector can start immediately.  Barrier-join on the previous
            # thread first to avoid concurrent SQLite writers.
            if result.status == "success":
                if _persist_thread is not None:
                    _persist_thread.join()
                _persist_thread = threading.Thread(
                    target=_persist_results,
                    args=(inst_id, result),
                    daemon=True,
                )
                _persist_thread.start()

        except Exception as e:
            log.error("%s connector raised: %s", inst_id, e)
            print(f"  ❌  {inst_id} failed: {e}")

    # Ensure the last background write finishes before we return
    if _persist_thread is not None:
        _persist_thread.join()

    return results


def _persist_results(institution_id: str, result) -> None:
    """Persist connector results to SQLite using the shared result writer."""
    summary = persist_connector_result(institution_id, result)
    bal_count = summary["balances_recorded"]
    txn_count = summary["txn_inserted"]
    log.info(
        "Persisted %s: %d balances, %d new txns", institution_id, bal_count, txn_count
    )
    if bal_count:
        print(f"  \U0001f4be  Saved {bal_count} balance(s) to DB")
    if txn_count:
        print(f"  \U0001f4be  Saved {txn_count} new transaction(s) to DB")


def _requires_final_browser_cleanup_in_dev(targets: list[str]) -> bool:
    """Return True when any target refuses dev-mode browser preservation."""
    for inst_id in targets:
        try:
            connector = get_connector(inst_id)
            if not connector._preserve_browser_session_in_dev_mode():
                return True
        except Exception as e:
            log.debug("Could not inspect dev cleanup policy for %s: %s", inst_id, e)
    return False


def main():
    force = "--force" in sys.argv
    dev_mode = "--dev" in sys.argv

    # Parse --institutions chase,nfcu
    institutions = None
    for arg in sys.argv[1:]:
        if arg.startswith("--institutions"):
            parts = arg.split("=", 1)
            if len(parts) == 2:
                institutions = [i.strip() for i in parts[1].split(",")]
            elif sys.argv.index(arg) + 1 < len(sys.argv):
                institutions = [
                    i.strip() for i in sys.argv[sys.argv.index(arg) + 1].split(",")
                ]

    print(f"\n  🏰  Sentry Finance Pipeline — {datetime.now():%Y-%m-%d %H:%M}")
    flags = []
    if force:
        flags.append("⚡ Force")
    if dev_mode:
        flags.append("🛠️ Dev Mode")
    if institutions:
        flags.append(f"🎯 {', '.join(institutions)}")
    print(f"  {' | '.join(flags) if flags else '📋 Normal cadence'}\n")

    # Troubleshooting / manual mode setting:
    # Always close leftover Chrome tabs before starting a new run
    # to guarantee a clean slate and avoid zombie processes blocking the CDP port.
    from extractors.chrome_cdp import close_chrome

    if not dev_mode:
        log.info("Cleaning up leftover browser sessions before new run...")
        close_chrome()
    else:
        log.info("Dev mode active: Skipping browser cleanup to preserve sessions...")

    targets = institutions or list(CONNECTOR_REGISTRY.keys())
    force_final_cleanup = dev_mode and _requires_final_browser_cleanup_in_dev(targets)

    # Fetch creds via broker for UAC + Headless flow
    log.info("Requesting credentials for: %s", targets)
    credentials = request_credentials(targets)
    if not credentials:
        log.warning("No credentials received from broker, continuing without them")

    try:
        results = run_extractors(
            institutions=institutions,
            force=force,
            credentials=credentials,
            dev_mode=dev_mode,
        )

        # Summary
        success = sum(1 for r in results.values() if r.status == "success")
        skipped = sum(1 for r in results.values() if r.status == "skipped")
        errors = sum(1 for r in results.values() if r.status == "error")
        print(f"\n  {'─' * 50}")
        print(f"  ✅ {success} succeeded  ⏭️ {skipped} skipped  ❌ {errors} errors")

    finally:
        # Clear credentials from memory immediately after use
        if credentials:
            from backend.ipc import clear_credentials
            clear_credentials(credentials)
            credentials = None

        # Mirror the thorough cleanup from the start of the script.
        # Runs even on crashes — double coverage with the startup cleanup.
        if not dev_mode or force_final_cleanup:
            log.info("Final cleanup: closing browser after pipeline run...")
            close_chrome()
            print("  🧹  Browser closed")
        else:
            log.info("Dev mode: browser left open for debugging")

    print(f"  🏰  Done — {datetime.now():%H:%M:%S}\n")


if __name__ == "__main__":
    main()
