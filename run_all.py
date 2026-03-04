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
from datetime import datetime
from backend.ipc import request_credentials

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sentry")


# ── Institution registry ─────────────────────────────────────────────────────
# Add new connectors here as they are built.
# Connectors run SEQUENTIALLY — never in parallel — to avoid CDP port conflicts.
# See: resource-session-management.md § No Concurrent Sprawl

CONNECTORS = {
    "nfcu": lambda: _import("extractors.nfcu_connector", "NFCUConnector"),
    "chase": lambda: _import("extractors.chase_connector", "ChaseConnector"),
    # "fidelity": lambda: _import("extractors.fidelity_connector", "FidelityConnector"),
    # "tsp":      lambda: _import("extractors.tsp_connector", "TSPConnector"),
    "acorns": lambda: _import("extractors.acorns_connector", "AcornsConnector"),
    # "affirm":   lambda: _import("extractors.affirm_connector", "AffirmConnector"),
}


def _import(module: str, cls: str):
    """Lazy import a connector class to avoid loading Playwright at module level."""
    import importlib

    mod = importlib.import_module(module)
    return getattr(mod, cls)(headless=False)


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
    targets = institutions or list(CONNECTORS.keys())

    for inst_id in targets:
        factory = CONNECTORS.get(inst_id)
        if not factory:
            log.warning("No connector registered for: %s", inst_id)
            continue

        print(f"\n  ── {inst_id.upper()} {'─' * (44 - len(inst_id))}")
        try:
            connector = factory()
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

        except Exception as e:
            log.error("%s connector raised: %s", inst_id, e)
            print(f"  ❌  {inst_id} failed: {e}")

    return results


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

    # Fetch creds via broker for UAC + Headless flow
    targets = institutions or list(CONNECTORS.keys())
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
        # Mirror the thorough cleanup from the start of the script.
        # Runs even on crashes — double coverage with the startup cleanup.
        if not dev_mode:
            log.info("Final cleanup: closing browser after pipeline run...")
            close_chrome()
            print("  🧹  Browser closed")
        else:
            log.info("Dev mode: browser left open for debugging")

    print(f"  🏰  Done — {datetime.now():%H:%M:%S}\n")


if __name__ == "__main__":
    main()
