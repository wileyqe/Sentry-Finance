"""
backend/automation_worker.py — Sequential institution automation.

Bridges the Refresh Orchestrator with existing InstitutionConnector
implementations. Runs institutions one at a time against a shared
Chrome instance, with support for:
  - Credential injection from the broker
  - Manual fallback (MFA, captchas, autofill clicks)
  - Transaction upsert to SQLite after each institution
"""
import logging
import time
from datetime import datetime
from pathlib import Path

from dal.database import get_db
from dal.transactions import upsert_transactions, compute_txn_id
from dal.balances import record_balance, record_loan_details

log = logging.getLogger("sentry")

BASE_DIR = Path(__file__).resolve().parent.parent


# ── Worker Function Registry ─────────────────────────────────────────────────

def _get_connector(institution_id: str):
    """Dynamically import and return a connector instance.

    This avoids importing all connectors at module load time,
    which would pull in Playwright and other heavy dependencies.
    """
    if institution_id == "nfcu":
        from extractors.nfcu_connector import NFCUConnector
        return NFCUConnector(headless=False)
    elif institution_id == "chase":
        from extractors.chase_connector import ChaseConnector
        return ChaseConnector(headless=False)
    else:
        raise ValueError(f"No connector for institution: "
                         f"{institution_id}")


def run_institution(institution_id: str,
                    credentials: dict | None = None) -> dict:
    """Run a full extraction for a single institution.

    This is the worker function passed to the orchestrator.

    Args:
        institution_id: e.g. "nfcu"
        credentials: {"username": "...", "password": "..."} or None

    Returns:
        dict with keys: txn_inserted, txn_updated, txn_deleted,
                        balances_recorded, accounts_processed
    """
    start = time.time()
    log.info("Worker starting: %s", institution_id)

    connector = _get_connector(institution_id)

    # Run the connector (existing infrastructure)
    # The connector handles login, navigation, extraction
    result = connector.run(
        force=True,
        credentials=credentials,
    )

    if result.status == "error":
        raise RuntimeError(
            f"Connector failed: {result.error or 'unknown error'}"
        )

    # ── Persist results to SQLite ─────────────────────────────
    summary = {
        "txn_inserted": 0,
        "txn_updated": 0,
        "txn_deleted": 0,
        "balances_recorded": 0,
        "accounts_processed": 0,
    }

    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        # Record balances
        if result.balances:
            for last4, info in result.balances.items():
                account_id = f"{institution_id}_{last4}"
                balance_str = info.get("balance", "0")

                # Parse balance string (remove $, commas, etc.)
                try:
                    balance = float(
                        str(balance_str)
                        .replace("$", "")
                        .replace(",", "")
                        .strip()
                    )
                except (ValueError, TypeError):
                    log.warning("Could not parse balance '%s' "
                                "for %s", balance_str, account_id)
                    continue

                record_balance(conn, account_id, balance, now)
                summary["balances_recorded"] += 1
                log.info("Balance recorded: %s = %.2f",
                         account_id, balance)

        # Record loan details
        if result.loan_details:
            for last4, details in result.loan_details.items():
                account_id = f"{institution_id}_{last4}"
                record_loan_details(conn, account_id, details, now)
                log.info("Loan details recorded: %s (%d fields)",
                         account_id, len(details))

        # Process transaction CSVs
        if result.files:
            import pandas as pd

            for csv_path in result.files:
                csv_path = Path(csv_path)
                if not csv_path.exists():
                    log.warning("CSV not found: %s", csv_path)
                    continue

                try:
                    df = pd.read_csv(csv_path)
                    if df.empty:
                        continue

                    # Determine account from filename
                    # Files are named like: {last4}_{date}.csv
                    stem = csv_path.stem
                    last4 = stem.split("_")[0]
                    account_id = f"{institution_id}_{last4}"

                    txns = _dataframe_to_txn_dicts(
                        df, institution_id, account_id
                    )

                    stats = upsert_transactions(conn, txns)
                    summary["txn_inserted"] += stats["inserted"]
                    summary["txn_updated"] += stats["updated"]
                    summary["accounts_processed"] += 1

                    log.info("Transactions upserted for %s: "
                             "+%d, ~%d, =%d",
                             account_id, stats["inserted"],
                             stats["updated"], stats["unchanged"])

                except Exception as e:
                    log.error("Failed to process %s: %s",
                              csv_path.name, e)

        conn.commit()

    elapsed = time.time() - start
    summary["duration_seconds"] = elapsed
    log.info("Worker completed: %s in %.1fs "
             "(+%d txns, %d balances)",
             institution_id, elapsed,
             summary["txn_inserted"],
             summary["balances_recorded"])

    return summary


def _dataframe_to_txn_dicts(df, institution_id: str,
                            account_id: str) -> list[dict]:
    """Convert a CSV DataFrame to transaction dicts for upsert."""
    import pandas as pd

    txns = []

    # Common column name mappings for NFCU CSVs
    date_col = None
    for candidate in ["Posting Date", "Date", "date",
                      "posting_date"]:
        if candidate in df.columns:
            date_col = candidate
            break

    amount_col = None
    for candidate in ["Amount", "amount"]:
        if candidate in df.columns:
            amount_col = candidate
            break

    desc_col = None
    for candidate in ["Description", "description", "Memo"]:
        if candidate in df.columns:
            desc_col = candidate
            break

    dir_col = None
    for candidate in ["Credit Debit Indicator", "direction",
                      "Direction"]:
        if candidate in df.columns:
            dir_col = candidate
            break

    cat_col = None
    for candidate in ["Category", "category"]:
        if candidate in df.columns:
            cat_col = candidate
            break

    if not date_col or not amount_col:
        log.warning("Missing essential columns in CSV. "
                    "Columns found: %s", list(df.columns))
        return []

    for _, row in df.iterrows():
        try:
            posting_date = str(
                pd.to_datetime(row[date_col]).date()
            )
        except Exception:
            continue

        amount = abs(float(row.get(amount_col, 0)))
        description = str(row.get(desc_col, "")) if desc_col else ""

        # Determine signed amount and direction
        if dir_col and pd.notna(row.get(dir_col)):
            direction_raw = str(row[dir_col]).strip().lower()
            is_credit = direction_raw == "credit"
        else:
            is_credit = float(row.get(amount_col, 0)) > 0

        signed_amount = amount if is_credit else -amount
        direction = "Credit" if is_credit else "Debit"

        category = (str(row[cat_col])
                     if cat_col and pd.notna(row.get(cat_col))
                     else "Uncategorized")

        txns.append({
            "account_id": account_id,
            "institution_id": institution_id,
            "posting_date": posting_date,
            "transaction_date": posting_date,
            "amount": amount,
            "signed_amount": signed_amount,
            "direction": direction,
            "description": description,
            "category": category,
            "status": "posted",
            "raw_description": description,
        })

    return txns

