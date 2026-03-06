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
from pathlib import Path
from backend.ipc import request_credentials
from dal.database import get_db
from dal.balances import record_balance, record_loan_details
from dal.transactions import upsert_transactions
from config.logging_config import setup_logging

from dotenv import load_dotenv

load_dotenv()
setup_logging()

log = logging.getLogger("sentry")


# ── Institution registry ─────────────────────────────────────────────────────
# Add new connectors here as they are built.
# Connectors run SEQUENTIALLY — never in parallel — to avoid CDP port conflicts.
# See: resource-session-management.md § No Concurrent Sprawl

CONNECTORS = {
    "nfcu": lambda: _import("extractors.nfcu_connector", "NFCUConnector"),
    "chase": lambda: _import("extractors.chase_connector", "ChaseConnector"),
    "fidelity": lambda: _import("extractors.fidelity_connector", "FidelityConnector"),
    # "tsp":      lambda: _import("extractors.tsp_connector", "TSPConnector"),
    "acorns": lambda: _import("extractors.acorns_connector", "AcornsConnector"),
    "affirm": lambda: _import("extractors.affirm_connector", "AffirmConnector"),
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
    _persist_thread: threading.Thread | None = None

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
    """Persist connector results (balances, loan details, transactions) to SQLite.

    This mirrors the persistence logic in automation_worker.run_institution()
    so that run_all.py (direct runner) and the orchestrator path both write
    to the same database.
    """
    now = datetime.utcnow().isoformat()
    bal_count = 0
    txn_count = 0

    with get_db() as conn:
        # ── Balances ──
        if result.balances:
            for last4, info in result.balances.items():
                account_id = f"{institution_id}_{last4}"
                balance_str = info.get("balance", "0")
                try:
                    balance = float(
                        str(balance_str).replace("$", "").replace(",", "").strip()
                    )
                except (ValueError, TypeError):
                    log.warning(
                        "Could not parse balance '%s' for %s", balance_str, account_id
                    )
                    continue
                record_balance(conn, account_id, balance, now)
                bal_count += 1

        # ── Loan details ──
        if result.loan_details:
            for last4, details in result.loan_details.items():
                account_id = f"{institution_id}_{last4}"
                record_loan_details(conn, account_id, details, now)

        # ── Transaction CSVs ──
        if result.files:
            import pandas as pd

            for csv_path in result.files:
                csv_path = Path(csv_path)
                if not csv_path.exists():
                    continue
                try:
                    df = pd.read_csv(csv_path)
                    if df.empty:
                        continue
                    last4 = csv_path.stem.split("_")[0]
                    account_id = f"{institution_id}_{last4}"

                    # Reuse the worker's conversion logic
                    from backend.automation_worker import _dataframe_to_txn_dicts

                    txns = _dataframe_to_txn_dicts(df, institution_id, account_id)
                    stats = upsert_transactions(conn, txns)
                    txn_count += stats["inserted"]
                except Exception as e:
                    log.error("Failed to process %s: %s", csv_path.name, e)

        conn.commit()

    log.info(
        "Persisted %s: %d balances, %d new txns", institution_id, bal_count, txn_count
    )
    if bal_count:
        print(f"  💾  Saved {bal_count} balance(s) to DB")
    if txn_count:
        print(f"  💾  Saved {txn_count} new transaction(s) to DB")


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
