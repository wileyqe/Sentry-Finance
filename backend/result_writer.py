"""
backend/result_writer.py — Shared persistence for connector results.

Consolidates the duplicated logic between run_all.py (dev CLI) and
automation_worker.py (API-triggered refresh) for writing connector
output (balances, loan details, transaction CSVs) to the database.

Also provides the post-commit pipeline (categorization → derived
metrics → alerts → goal sync) as a single callable.
"""

import logging
from datetime import datetime
from pathlib import Path

from dal.database import get_db
from dal.balances import record_balance, record_loan_details, get_latest_balance
from dal.transactions import upsert_transactions
from dal.categorization import backfill_uncategorized
from dal.derived import recompute_for_institution
from dal.alerts import evaluate_alerts
from dal.goals import sync_goal_balances

log = logging.getLogger("sentry.backend.result_writer")


def _parse_balance(raw: str | float) -> float | None:
    """Parse a balance value from $-formatted string or float."""
    try:
        return float(str(raw).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def dataframe_to_txn_dicts(df, institution_id: str, account_id: str) -> list[dict]:
    """Convert a CSV DataFrame to transaction dicts for upsert.

    Handles multiple CSV column naming conventions (NFCU, Chase, etc.)
    """
    import pandas as pd

    txns = []
    seen_transactions = {}  # Tracks (date, amount, desc) -> count

    # Flexible column name mappings
    date_col = _find_column(df, ["Posting Date", "Date", "date", "posting_date"])
    amount_col = _find_column(df, ["Amount", "amount"])
    desc_col = _find_column(df, ["Description", "description", "Memo"])
    dir_col = _find_column(df, ["Credit Debit Indicator", "direction", "Direction"])
    cat_col = _find_column(df, ["Category", "category"])

    if not date_col or not amount_col:
        log.warning(
            "Missing essential columns in CSV. Columns found: %s", list(df.columns)
        )
        return []

    for _, row in df.iterrows():
        try:
            posting_date = str(pd.to_datetime(row[date_col]).date())
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

        # Unique sequence index for same-day identical amounts and descriptions
        sig = (posting_date, amount, description)
        sequence_index = seen_transactions.get(sig, 0)
        seen_transactions[sig] = sequence_index + 1

        category = (
            str(row[cat_col])
            if cat_col and pd.notna(row.get(cat_col))
            else "Uncategorized"
        )

        txns.append(
            {
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
                "sequence_index": sequence_index,
            }
        )

    return txns


def _find_column(df, candidates: list[str]) -> str | None:
    """Find the first matching column name from a list of candidates."""
    for name in candidates:
        if name in df.columns:
            return name
    return None


def persist_connector_result(institution_id: str, result, *, conn=None) -> dict:
    """Write balances, loan details, and transactions from a connector result.

    Args:
        institution_id: e.g. "nfcu"
        result: ConnectorResult with .balances, .loan_details, .files
        conn: Optional existing connection (caller manages commit).
              If None, opens its own connection and commits.

    Returns:
        dict with keys: txn_inserted, txn_updated, balances_recorded, accounts_processed
    """
    summary = {
        "txn_inserted": 0,
        "txn_updated": 0,
        "txn_deleted": 0,
        "balances_recorded": 0,
        "accounts_processed": 0,
    }

    owns_connection = conn is None
    if owns_connection:
        ctx = get_db()
        conn = ctx.__enter__()

    now = datetime.now().replace(microsecond=0).isoformat()

    try:
        # ── Balances ──
        if result.balances:
            for last4, info in result.balances.items():
                account_id = f"{institution_id}_{last4}"
                balance_str = info.get("balance", "0")
                balance = _parse_balance(balance_str)
                if balance is None:
                    log.warning(
                        "Could not parse balance '%s' for %s", balance_str, account_id
                    )
                    continue

                # Sanity check: flag balances that changed by >10x
                prev = get_latest_balance(conn, account_id)
                if prev and prev.get("balance"):
                    prev_bal = prev["balance"]
                    if prev_bal != 0:
                        ratio = balance / prev_bal
                        if ratio > 10 or ratio < 0.1:
                            log.warning(
                                "BALANCE ANOMALY for %s: previous=%.2f, "
                                "scraped=%.2f (%.1fx change). Recording but "
                                "flagging for review.",
                                account_id,
                                prev_bal,
                                balance,
                                ratio,
                            )
                            summary.setdefault("anomalies", []).append(
                                {
                                    "account_id": account_id,
                                    "previous": prev_bal,
                                    "scraped": balance,
                                    "ratio": round(ratio, 2),
                                }
                            )

                record_balance(conn, account_id, balance, now)
                summary["balances_recorded"] += 1
                log.info("Balance recorded: %s = %.2f", account_id, balance)

        # ── Loan details ──
        if result.loan_details:
            for last4, details in result.loan_details.items():
                account_id = f"{institution_id}_{last4}"
                record_loan_details(conn, account_id, details, now)
                log.info(
                    "Loan details recorded: %s (%d fields)", account_id, len(details)
                )

        # ── Transaction CSVs ──
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
                    last4 = csv_path.stem.split("_")[0]
                    account_id = f"{institution_id}_{last4}"

                    txns = dataframe_to_txn_dicts(df, institution_id, account_id)
                    stats = upsert_transactions(conn, txns)
                    summary["txn_inserted"] += stats["inserted"]
                    summary["txn_updated"] += stats["updated"]
                    summary["accounts_processed"] += 1

                    log.info(
                        "Transactions upserted for %s: +%d, ~%d, =%d",
                        account_id,
                        stats["inserted"],
                        stats["updated"],
                        stats["unchanged"],
                    )
                except Exception as e:
                    log.error("Failed to process %s: %s", csv_path.name, e)

        conn.commit()
    finally:
        if owns_connection:
            ctx.__exit__(None, None, None)

    return summary


def _link_acorns_bank_debits(conn) -> int:
    """Link unlinked bank-side Acorns debits to positions_ledger entries.

    Scans for bank transactions that match Acorns transfers/roundups
    (description LIKE '%ACORNS INVEST%', NOT '%FEE%') that don't yet
    have a transfer_tag starting with 'invest:'.  For each, finds a
    positions_ledger entry from the same date and sets the linkage.

    Returns the number of debits linked.
    """
    unlinked = conn.execute("""
        SELECT id, posting_date, amount
        FROM transactions
        WHERE description LIKE '%ACORNS INVEST%'
          AND description NOT LIKE '%FEE%'
          AND direction = 'Debit'
          AND (transfer_tag IS NULL OR transfer_tag NOT LIKE 'invest:%')
        ORDER BY posting_date
    """).fetchall()

    linked = 0
    for txn in unlinked:
        txn_id = txn["id"]
        txn_date = txn["posting_date"][:10]

        ledger_row = conn.execute("""
            SELECT id FROM positions_ledger
            WHERE account_id LIKE 'acorns%'
              AND timestamp LIKE ?
              AND bank_txn_id IS NULL
            ORDER BY id LIMIT 1
        """, (f"{txn_date}%",)).fetchone()

        if ledger_row:
            ledger_id = ledger_row["id"]
            conn.execute(
                "UPDATE transactions SET transfer_tag = ?, investment_link = ? WHERE id = ?",
                (f"invest:{ledger_id}", str(ledger_id), txn_id),
            )
            conn.execute(
                "UPDATE positions_ledger SET bank_txn_id = ? WHERE id = ?",
                (txn_id, ledger_id),
            )
            linked += 1

    return linked


def run_post_commit_pipeline(institution_id: str) -> dict:
    """Run the post-commit pipeline: categorize → recompute → alerts → goals.

    Returns dict with pipeline results.
    """
    pipeline_results = {}

    # 1. Categorization backfill
    try:
        with get_db() as conn:
            backfill_stats = backfill_uncategorized(conn)
            log.info(
                "Categorization backfill: %d matched, %d still uncategorized",
                backfill_stats["matched"],
                backfill_stats["still_uncategorized"],
            )
            conn.commit()
            pipeline_results["categorization"] = backfill_stats
    except Exception as e:
        log.warning("Categorization backfill failed (non-fatal): %s", e)

    # 2. Transfer reconciliation
    try:
        from dal.reconciliation import reconcile_transfers
        with get_db() as conn:
            recon_stats = reconcile_transfers(conn)
            pipeline_results["reconciliation"] = recon_stats
    except Exception as e:
        log.warning("Transfer reconciliation failed (non-fatal): %s", e)

    # 2.5. Investment linkage (Acorns: link bank debits → positions_ledger)
    if institution_id == "acorns":
        try:
            with get_db() as conn:
                linked = _link_acorns_bank_debits(conn)
                conn.commit()
                if linked:
                    pipeline_results["investment_linked"] = linked
                    log.info("Linked %d bank debits to Acorns positions", linked)
        except Exception as e:
            log.warning("Acorns investment linkage failed (non-fatal): %s", e)

    # 3. Derived metrics
    try:
        with get_db() as conn:
            recompute_for_institution(conn, institution_id)
            conn.commit()
    except Exception as e:
        log.warning("Derived metric recompute failed (non-fatal): %s", e)

    # 4. Alerts
    try:
        with get_db() as conn:
            fired_alerts = evaluate_alerts(conn, institution_id=institution_id)
            if fired_alerts:
                conn.commit()
                pipeline_results["alerts_fired"] = len(fired_alerts)
                log.info(
                    "Alerts fired after %s refresh: %d",
                    institution_id, len(fired_alerts),
                )
    except Exception as e:
        log.warning("Alert evaluation failed (non-fatal): %s", e)

    # 5. Goal sync
    try:
        with get_db() as conn:
            goals_updated = sync_goal_balances(conn)
            if goals_updated:
                conn.commit()
                pipeline_results["goals_synced"] = goals_updated
                log.info(
                    "Goal balances synced after %s refresh: %d goals",
                    institution_id, goals_updated,
                )
    except Exception as e:
        log.warning("Goal balance sync failed (non-fatal): %s", e)

    return pipeline_results
