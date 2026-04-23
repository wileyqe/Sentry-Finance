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
from dal.balances import record_balance, record_loan_details, get_latest_balances
from dal.apy_history import parse_apy_string, record_apy_history
from dal.transactions import upsert_transactions, derive_signed_amount
from dal.categorization import backfill_uncategorized
from dal.derived import recompute_for_institution
from dal.alerts import evaluate_alerts
from dal.goals import sync_goal_balances

log = logging.getLogger("sentry.backend.result_writer")


def _redact_account_id(account_id: str | None) -> str:
    # account_id is ``{institution_id}_{last4}`` where last4 comes from
    # live web scraping; logs must not persist real card/account digits.
    if not account_id:
        return "<unknown>"
    if "_" not in account_id:
        return account_id
    institution, _sep, _last4 = account_id.rpartition("_")
    return f"{institution}_****"


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

        direction = "Credit" if is_credit else "Debit"
        signed_amount = derive_signed_amount(amount, direction)

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


def _run_step(name: str, fn):
    """Run a post-commit pipeline step, swallowing and logging any exception.

    Each step is independent — a categorizer crash must not prevent alerts or
    goal sync from running. Returns ``fn()``'s result on success, ``None`` on
    failure (caller decides what to store in ``pipeline_results``).
    """
    try:
        return fn()
    except Exception as e:
        log.warning("%s failed (non-fatal): %s", name, e)
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
            # Batch-load previous balances once; avoids N+1 SELECT inside the loop.
            _incoming_ids = [f"{institution_id}_{last4}" for last4 in result.balances]
            _prev_balances = get_latest_balances(conn, _incoming_ids)

            for last4, info in result.balances.items():
                account_id = f"{institution_id}_{last4}"
                balance_str = info.get("balance", "0")
                balance = _parse_balance(balance_str)
                if balance is None:
                    log.warning(
                        "Could not parse balance '%s' for %s",
                        balance_str,
                        _redact_account_id(account_id),
                    )
                    continue

                # Sanity check: flag balances that changed by >10x
                prev = _prev_balances.get(account_id)
                if prev and prev.get("balance"):
                    prev_bal = prev["balance"]
                    if prev_bal != 0:
                        ratio = balance / prev_bal
                        if ratio > 10 or ratio < 0.1:
                            log.warning(
                                "BALANCE ANOMALY for %s: previous=%.2f, "
                                "scraped=%.2f (%.1fx change). Recording but "
                                "flagging for review.",
                                _redact_account_id(account_id),
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
                log.info(
                    "Balance recorded: %s = %.2f",
                    _redact_account_id(account_id),
                    balance,
                )

        # ── Loan details ──
        # P15-T04 Phase B: ``apy`` routes to the dedicated time-series
        # ``apy_history`` table instead of the key-value ``loan_details``.
        # Everything else still flows through ``record_loan_details``.
        if result.loan_details:
            today_iso = datetime.now().date().isoformat()
            for last4, details in result.loan_details.items():
                account_id = f"{institution_id}_{last4}"

                apy_raw = details.pop("apy", None) if isinstance(details, dict) else None
                if apy_raw is not None:
                    try:
                        apy_rate = parse_apy_string(apy_raw)
                        record_apy_history(
                            conn,
                            account_id=account_id,
                            apy_rate=apy_rate,
                            as_of=today_iso,
                            source="scrape",
                        )
                        summary["apy_recorded"] = summary.get("apy_recorded", 0) + 1
                        log.info(
                            "APY recorded: %s = %.3f%%",
                            _redact_account_id(account_id),
                            apy_rate,
                        )
                    except ValueError as e:
                        log.warning(
                            "Skipping invalid APY for %s: %s",
                            _redact_account_id(account_id),
                            e,
                        )

                if details:
                    record_loan_details(conn, account_id, details, now)
                    log.info(
                        "Loan details recorded: %s (%d fields)",
                        _redact_account_id(account_id),
                        len(details),
                    )

        # ── Transaction CSVs ──
        if result.files:
            import pandas as pd

            for csv_path in result.files:
                csv_path = Path(csv_path)
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
                        _redact_account_id(account_id),
                        stats["inserted"],
                        stats["updated"],
                        stats["unchanged"],
                    )
                except Exception as e:
                    log.error(
                        "Failed to process CSV (inst=%s): %s",
                        institution_id,
                        e,
                    )

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

    # Pre-fetch all candidate ledger rows in one query (previously this
    # loop issued one SELECT per unlinked transaction, up to 100+ per
    # refresh). Bucket by date, ordered by id ASC so pop(0) mirrors the
    # original ``ORDER BY id LIMIT 1`` pick.
    available: dict[str, list[int]] = {}
    for row in conn.execute("""
        SELECT id, substr(timestamp, 1, 10) AS ldate
          FROM positions_ledger
         WHERE account_id LIKE 'acorns%'
           AND bank_txn_id IS NULL
         ORDER BY id
    """).fetchall():
        available.setdefault(row["ldate"], []).append(row["id"])

    pairs: list[tuple[int, int]] = []  # (txn_id, ledger_id)
    for txn in unlinked:
        bucket = available.get(txn["posting_date"][:10])
        if bucket:
            pairs.append((txn["id"], bucket.pop(0)))

    if pairs:
        conn.executemany(
            "UPDATE transactions SET transfer_tag = ?, investment_link = ? WHERE id = ?",
            [(f"invest:{lid}", str(lid), tid) for tid, lid in pairs],
        )
        conn.executemany(
            "UPDATE positions_ledger SET bank_txn_id = ? WHERE id = ?",
            [(tid, lid) for tid, lid in pairs],
        )

    return len(pairs)


def run_post_commit_pipeline(institution_id: str) -> dict:
    """Run the post-commit pipeline: categorize → recompute → alerts → goals.

    Each step is independent — a crash in one must not block the others.
    Returns dict with pipeline results (keys only populated when a step
    produces something worth reporting).
    """
    pipeline_results: dict = {}

    def _categorize():
        with get_db() as conn:
            stats = backfill_uncategorized(conn)
            log.info(
                "Categorization backfill: %d matched, %d still uncategorized",
                stats["matched"], stats["still_uncategorized"],
            )
            conn.commit()
            return stats

    def _reconcile():
        from dal.reconciliation import reconcile_transfers
        with get_db() as conn:
            return reconcile_transfers(conn)

    def _link_acorns():
        with get_db() as conn:
            linked = _link_acorns_bank_debits(conn)
            conn.commit()
            if linked:
                log.info("Linked %d bank debits to Acorns positions", linked)
            return linked

    def _mortgage_splits():
        # Phase 14 Phase B — decompose any mortgage payments that landed on
        # this refresh so the Sankey can route principal → STORED_ILLIQUID
        # and interest/escrow → CONSUMED. Runs between reconciliation (which
        # may have tagged a mortgage payment as a transfer — if so it's
        # excluded from spending, not decomposed here) and derived-recompute
        # (which the bucket classifier will consult).
        from dal.debt import decompose_unsplit_mortgage_payments
        with get_db() as conn:
            written = decompose_unsplit_mortgage_payments(conn)
            if written:
                conn.commit()
                log.info(
                    "Mortgage payment decomposition: %d new splits written",
                    written,
                )
            return written

    def _derived():
        with get_db() as conn:
            recompute_for_institution(conn, institution_id)
            conn.commit()

    def _alerts():
        with get_db() as conn:
            fired = evaluate_alerts(conn, institution_id=institution_id)
            if fired:
                conn.commit()
                log.info("Alerts fired after %s refresh: %d", institution_id, len(fired))
            return fired

    def _goals():
        with get_db() as conn:
            updated = sync_goal_balances(conn)
            if updated:
                conn.commit()
                log.info(
                    "Goal balances synced after %s refresh: %d goals",
                    institution_id, updated,
                )
            return updated

    cat_stats = _run_step("Categorization backfill", _categorize)
    if cat_stats is not None:
        pipeline_results["categorization"] = cat_stats

    recon_stats = _run_step("Transfer reconciliation", _reconcile)
    if recon_stats is not None:
        pipeline_results["reconciliation"] = recon_stats

    if institution_id == "acorns":
        linked = _run_step("Acorns investment linkage", _link_acorns)
        if linked:
            pipeline_results["investment_linked"] = linked

    written = _run_step("Mortgage payment decomposition", _mortgage_splits)
    if written:
        pipeline_results["mortgage_splits_written"] = written

    _run_step("Derived metric recompute", _derived)

    fired = _run_step("Alert evaluation", _alerts)
    if fired:
        pipeline_results["alerts_fired"] = len(fired)

    updated = _run_step("Goal balance sync", _goals)
    if updated:
        pipeline_results["goals_synced"] = updated

    return pipeline_results
