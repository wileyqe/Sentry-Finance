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
from dal.apy_history import detect_apy_changes, parse_apy_string, record_apy_history
from dal.investment_details import record_investment_details
from dal.transactions import upsert_transactions, derive_signed_amount
from dal.categorization import backfill_uncategorized
from dal.derived import recompute_for_institution
from dal.alerts import evaluate_alerts
from dal.goals import sync_goal_balances
from dal.notifications import record_notification
from dal.bills import get_upcoming_bills
from dal.clock import reference_date
from dal.documents import get_pending_nudges
from dal.recurring import list_all_mutations

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


def persist_connector_result(
    institution_id: str,
    result,
    *,
    conn=None,
    refresh_run_id: str | None = None,
) -> dict:
    """Write balances, loan details, and transactions from a connector result.

    Args:
        institution_id: e.g. "nfcu"
        result: ConnectorResult with .balances, .loan_details, .files
        conn: Optional existing connection (caller manages commit).
              If None, opens its own connection and commits.
        refresh_run_id: Optional UUID of the orchestrator's refresh run.
            Threaded through to ``record_balance`` /
            ``record_loan_details`` so the snapshot rows can be traced
            back to a specific run for forensic queries. ``None`` is
            valid — the live writer should pass it; the legacy CLI
            (``run_all.py``) does not.

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
            # Connectors that ingest documents (e.g. myPay RAS) may
            # populate a synthetic _marker_* balance entry purely to
            # satisfy the lifecycle's "no data" check after a run that
            # produced no real balance data. Filter them out before the
            # batch SELECT so we never persist or anomaly-check them.
            real_balances = {
                last4: info
                for last4, info in result.balances.items()
                if not last4.startswith("_marker")
            }
            if not real_balances:
                _prev_balances = {}
            else:
                # Batch-load previous balances once; avoids N+1 SELECT inside the loop.
                _incoming_ids = [
                    f"{institution_id}_{last4}" for last4 in real_balances
                ]
                _prev_balances = get_latest_balances(conn, _incoming_ids)

            for last4, info in real_balances.items():
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

                record_balance(
                    conn, account_id, balance, now, refresh_run_id
                )
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
                    record_loan_details(
                        conn, account_id, details, now, refresh_run_id
                    )
                    log.info(
                        "Loan details recorded: %s (%d fields)",
                        _redact_account_id(account_id),
                        len(details),
                    )

        # ── Investment details (P15-T09) ──
        # Per-account investment metadata (Fidelity SPAXX SEC yield,
        # TSP per-fund YTD, Acorns round-ups + per-ETF YTD). Two-tier
        # shape: ``account_level`` (fund_ticker NULL) + ``funds`` keyed
        # by ticker. The shape distinction is carried by the dict
        # structure — the writer does not need a per-institution branch.
        investment_details = getattr(result, "investment_details", None) or {}
        if investment_details:
            today_iso = datetime.now().date().isoformat()
            for last4, payload in investment_details.items():
                account_id = f"{institution_id}_{last4}"
                if not isinstance(payload, dict):
                    continue
                acct_fields = payload.get("account_level") or {}
                if acct_fields:
                    try:
                        record_investment_details(
                            conn,
                            account_id,
                            acct_fields,
                            as_of=today_iso,
                            refresh_run_id=refresh_run_id,
                        )
                        summary["investment_details_recorded"] = (
                            summary.get("investment_details_recorded", 0)
                            + len(acct_fields)
                        )
                    except ValueError as e:
                        log.warning(
                            "Skipping invalid investment_details "
                            "(account-level) for %s: %s",
                            _redact_account_id(account_id),
                            e,
                        )
                funds = payload.get("funds") or {}
                for ticker, fields in funds.items():
                    if not isinstance(fields, dict) or not fields:
                        continue
                    try:
                        record_investment_details(
                            conn,
                            account_id,
                            fields,
                            fund_ticker=ticker,
                            as_of=today_iso,
                            refresh_run_id=refresh_run_id,
                        )
                        summary["investment_details_recorded"] = (
                            summary.get("investment_details_recorded", 0)
                            + len(fields)
                        )
                    except ValueError as e:
                        log.warning(
                            "Skipping invalid investment_details "
                            "(fund=%s) for %s: %s",
                            ticker,
                            _redact_account_id(account_id),
                            e,
                        )
                if acct_fields or funds:
                    log.info(
                        "Investment details recorded: %s "
                        "(account_level=%d funds=%d)",
                        _redact_account_id(account_id),
                        len(acct_fields),
                        len(funds),
                    )

        # ── Transaction CSVs ──
        # This branch is for transaction-history CSVs only. Connectors
        # that ingest documents (e.g. myPay RAS) commit through
        # `backend.document_ingest` BEFORE returning and surface the
        # downloaded PDF in `result.files` only as a marker for the
        # lifecycle's "no data" check. Filter to .csv so a PDF can
        # never accidentally hit `pd.read_csv` and silently fail.
        csv_files = [
            Path(p) for p in (result.files or [])
            if Path(p).suffix.lower() == ".csv"
        ]
        non_csv_files = [
            Path(p) for p in (result.files or [])
            if Path(p).suffix.lower() != ".csv"
        ]
        for skipped in non_csv_files:
            log.info(
                "Skipping non-CSV connector file (handled out-of-band): %s",
                skipped.name,
            )

        if csv_files:
            import pandas as pd

            for csv_path in csv_files:
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
                    # Surface failure to caller so an otherwise-successful
                    # refresh isn't mistaken for a clean one when a CSV
                    # couldn't be parsed. Caller can branch on the list's
                    # presence / length.
                    summary.setdefault("failed_csvs", []).append(
                        {"path": csv_path.name, "error": str(e)}
                    )

        # ── Surface anomalies + CSV failures as notifications ──
        # Both lists were previously write-only (AI-033 / AI-036). Emit
        # one notification per refresh-run / institution per kind so the
        # bell badge fires when something demands attention. dedup_key
        # collapses repeated runs; payload carries the per-account /
        # per-file details so the click-through can drill in.
        anomalies = summary.get("anomalies") or []
        if anomalies:
            try:
                accounts = [a.get("account_id") for a in anomalies]
                dedup_run = refresh_run_id or "no_run_id"
                record_notification(
                    conn,
                    type="balance_anomaly",
                    severity="warning",
                    title=f"{institution_id.upper()}: balance anomaly detected",
                    body=(
                        f"{len(anomalies)} balance(s) changed >10× "
                        f"vs the previous snapshot. The new value was "
                        f"recorded but flagged for review."
                    ),
                    payload={
                        "institution": institution_id,
                        "refresh_run_id": refresh_run_id,
                        "anomalies": anomalies,
                    },
                    dedup_key=(
                        f"balance_anomaly:{institution_id}:{dedup_run}"
                    ),
                    link="/accounts",
                )
            except Exception as _exc:
                # Per CLAUDE.md, observability writes must not break the
                # commit path. Log and continue.
                log.debug(
                    "balance_anomaly notification emit failed (non-fatal): %s",
                    _exc,
                )

        failed_csvs = summary.get("failed_csvs") or []
        if failed_csvs:
            try:
                dedup_run = refresh_run_id or "no_run_id"
                paths = ", ".join(f["path"] for f in failed_csvs[:3])
                more = (
                    f" (+{len(failed_csvs) - 3} more)"
                    if len(failed_csvs) > 3
                    else ""
                )
                record_notification(
                    conn,
                    type="csv_parse_failure",
                    severity="warning",
                    title=(
                        f"{institution_id.upper()}: "
                        f"{len(failed_csvs)} CSV(s) failed to parse"
                    ),
                    body=f"Failed: {paths}{more}",
                    payload={
                        "institution": institution_id,
                        "refresh_run_id": refresh_run_id,
                        "failures": failed_csvs,
                    },
                    dedup_key=(
                        f"csv_parse_failure:{institution_id}:{dedup_run}"
                    ),
                    link="/settings",
                )
            except Exception as _exc:
                log.debug(
                    "csv_parse_failure notification emit failed (non-fatal): %s",
                    _exc,
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

    def _normalize_merchants():
        # AI-022 fix: backfill the canonical merchant column from raw
        # description after categorization. Pre-AI-022 this was a
        # build-time-only step in the seeder, so live refreshes left
        # `transactions.merchant` NULL and merchant aggregations fell
        # back to raw descriptions. Idempotent — only updates rows where
        # merchant IS NULL or empty.
        from dal.merchant_normalizer import backfill_merchant_column
        with get_db() as conn:
            updated = backfill_merchant_column(conn)
            if updated:
                log.info(
                    "Merchant normalization: filled %d transactions",
                    updated,
                )
            return updated

    def _reconcile():
        from dal.reconciliation import reconcile_transfers
        with get_db() as conn:
            return reconcile_transfers(conn)

    def _detect_recurring():
        # AI-008 fix: recurring-pattern detection now runs after every
        # refresh instead of only on POST /api/recurring/scan. Caller
        # had been treating staleness as the user's problem; the cost
        # of the scan is small (<1s for typical data) and a stale
        # `recurring_transactions` table degrades the Bills page,
        # forecast, and recurring-with-payoff views.
        from dal.recurring import detect_recurring
        with get_db() as conn:
            stats = detect_recurring(conn)
            conn.commit()
            return stats

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

    def _enrich_tickers():
        # AI-024 fix: enrich ticker_metadata for any new tickers that
        # appeared in `investment_holdings` since the last refresh. Was
        # previously seeder-only, so a user's first refresh that
        # introduced a ticker outside the hardcoded seeder list (e.g.
        # buying a new stock) left it with NULL metadata and the
        # Holdings/Allocation/Overview tabs rendered "Unknown" /
        # "Unknown" / "Equity" fallback rows. The 30-day staleness
        # skip inside `enrich_ticker_metadata` keeps the per-refresh
        # cost low. yfinance failures fall back to the hardcoded
        # `_TICKER_METADATA_FALLBACK` dict, so the step never throws.
        from scripts.dummy_data.generator import enrich_ticker_metadata
        with get_db() as conn:
            held = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT ticker FROM investment_holdings "
                    "WHERE ticker IS NOT NULL"
                ).fetchall()
            ]
            if not held:
                return 0
            enriched = enrich_ticker_metadata(conn, tickers=held)
            conn.commit()
            return enriched

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

    merch_updated = _run_step("Merchant normalization", _normalize_merchants)
    if merch_updated:
        pipeline_results["merchants_normalized"] = merch_updated

    recon_stats = _run_step("Transfer reconciliation", _reconcile)
    if recon_stats is not None:
        pipeline_results["reconciliation"] = recon_stats

    rec_stats = _run_step("Recurring pattern detection", _detect_recurring)
    if rec_stats is not None:
        pipeline_results["recurring_detection"] = rec_stats

    if institution_id == "acorns":
        linked = _run_step("Acorns investment linkage", _link_acorns)
        if linked:
            pipeline_results["investment_linked"] = linked

    written = _run_step("Mortgage payment decomposition", _mortgage_splits)
    if written:
        pipeline_results["mortgage_splits_written"] = written

    enriched = _run_step("Ticker metadata enrichment", _enrich_tickers)
    if enriched:
        pipeline_results["tickers_enriched"] = enriched

    _run_step("Derived metric recompute", _derived)

    fired = _run_step("Alert evaluation", _alerts)
    if fired:
        pipeline_results["alerts_fired"] = len(fired)

    updated = _run_step("Goal balance sync", _goals)
    if updated:
        pipeline_results["goals_synced"] = updated

    # _notifications must be defined after `fired` is assigned so the closure
    # captures the resolved value.
    _alerts_fired: list[dict] = fired or []

    def _notifications():
        with get_db() as conn:
            count = 0

            # ── Budget / large-txn / balance-low alerts ───────────────────────
            for alert in _alerts_fired:
                rtype = alert.get("rule_type", "")
                rule_id = alert.get("rule_id", "")

                if rtype == "budget_pct":
                    sev = "critical" if alert.get("severity") == "over" else "warning"
                    month = alert.get("month", "")
                    cat = alert.get("category", "")
                    pct = alert.get("pct_used", 0)
                    actual = alert.get("actual", 0)
                    target = alert.get("target", 0)
                    notif_id = record_notification(
                        conn,
                        type="budget_alert",
                        severity=sev,
                        title=f"{cat} {pct:.0f}% of budget",
                        body=f"${actual:.2f} spent of ${target:.2f} budget",
                        payload=alert,
                        dedup_key=f"alert:{rule_id}:{month}:{cat}",
                        link="/budgets",
                    )
                elif rtype == "large_txn":
                    txn_id = alert.get("txn_id", "")
                    amount = alert.get("amount", 0)
                    desc = alert.get("description", "")
                    notif_id = record_notification(
                        conn,
                        type="budget_alert",
                        severity="warning",
                        title=f"Large transaction: ${amount:.2f}",
                        body=desc[:100] if desc else None,
                        payload=alert,
                        dedup_key=f"alert:{rule_id}:{txn_id}",
                        link="/transactions",
                    )
                elif rtype == "balance_low":
                    account_id = alert.get("account_id", "")
                    balance = alert.get("balance", 0)
                    acct_name = alert.get("account_name", account_id)
                    notif_id = record_notification(
                        conn,
                        type="budget_alert",
                        severity="warning",
                        title=f"{acct_name} balance low",
                        body=f"${balance:.2f} remaining",
                        payload=alert,
                        dedup_key=f"alert:{rule_id}:{account_id}",
                        link="/accounts",
                    )
                else:
                    continue

                if notif_id is not None:
                    count += 1

            # ── Upcoming / overdue bills ──────────────────────────────────────
            bills = get_upcoming_bills(conn, days=7)
            for bill in bills:
                status = bill["status"]
                if status not in ("overdue", "due_soon"):
                    continue
                bill_id = bill["id"]
                next_exp = bill["next_expected"]
                merchant = bill["merchant"] or "Bill"
                expected = bill.get("expected_amount") or bill.get("last_amount")

                if status == "overdue":
                    days_overdue = abs(bill["days_until"])
                    body = f"${expected:.2f} — {days_overdue}d overdue" if expected else f"{days_overdue}d overdue"
                    notif_id = record_notification(
                        conn,
                        type="bill_overdue",
                        severity="critical",
                        title=f"{merchant} overdue",
                        body=body,
                        payload={"id": bill_id, "next_expected": next_exp, "amount": expected},
                        dedup_key=f"bill_overdue:{bill_id}:{next_exp}",
                        link="/recurring",
                    )
                else:
                    days_until = bill["days_until"]
                    body = f"${expected:.2f} — due in {days_until}d" if expected else f"Due in {days_until}d"
                    notif_id = record_notification(
                        conn,
                        type="bill_due_soon",
                        severity="warning",
                        title=f"{merchant} due soon",
                        body=body,
                        payload={"id": bill_id, "next_expected": next_exp, "amount": expected},
                        dedup_key=f"bill_due_soon:{bill_id}:{next_exp}",
                        link="/recurring",
                    )

                if notif_id is not None:
                    count += 1

            # ── Doc-drop nudges ───────────────────────────────────────────────
            trusted_today = reference_date(conn)
            nudges = get_pending_nudges(conn, as_of=trusted_today)
            ym = trusted_today.strftime("%Y-%m")
            for nudge in nudges:
                inst = nudge["institution"]
                notif_id = record_notification(
                    conn,
                    type="doc_drop_nudge",
                    severity="info",
                    title=f"{nudge['display_name']} statement pending",
                    body=nudge["message"],
                    payload={"institution": inst, "month": ym},
                    dedup_key=f"doc_drop:{inst}:{ym}",
                    link="/documents",
                )
                if notif_id is not None:
                    count += 1

            # ── APY rate changes (P16-T02) ────────────────────────────────────
            for change in detect_apy_changes(conn):
                acct_label = change.get("account_name") or change["account_id"]
                arrow = "↑" if change["delta"] > 0 else "↓"
                bp = round(abs(change["delta"]) * 100)  # 0.05 pct → 5 bp
                notif_id = record_notification(
                    conn,
                    type="apy_rate_change",
                    severity=change["severity"],
                    title=(
                        f"{acct_label} APY {arrow} "
                        f"{change['old_rate']:.2f}% → {change['new_rate']:.2f}%"
                    ),
                    body=f"{arrow} {bp} bp change as of {change['as_of']}",
                    payload=change,
                    dedup_key=(
                        f"apy_change:{change['account_id']}"
                        f":{change['new_rate']:.4f}:{change['as_of']}"
                    ),
                    link="/accounts",
                )
                if notif_id is not None:
                    count += 1

            # ── Recurring price mutations (P16-T02) ───────────────────────────
            for mut in list_all_mutations(conn):
                merchant = mut.get("merchant") or "Subscription"
                old_amt = mut.get("old_amount")
                new_amt = mut.get("new_amount")
                if old_amt is None or new_amt is None:
                    continue
                arrow = "↑" if new_amt > old_amt else "↓"
                notif_id = record_notification(
                    conn,
                    type="recurring_price_mutation",
                    severity="warning",
                    title=(
                        f"{merchant} price {arrow} "
                        f"${old_amt:.2f} → ${new_amt:.2f}"
                    ),
                    body=mut.get("description"),
                    payload={
                        "mutation_id": mut["id"],
                        "recurring_id": mut["recurring_id"],
                        "old_amount": old_amt,
                        "new_amount": new_amt,
                        "detected_at": mut.get("detected_at"),
                    },
                    dedup_key=f"recurring_mutation:{mut['id']}",
                    link="/recurring",
                )
                if notif_id is not None:
                    count += 1

            if count:
                conn.commit()
                log.info(
                    "Notifications emitted after %s refresh: %d",
                    institution_id, count,
                )
            return count

    notif_count = _run_step("Notification emission", _notifications)
    if notif_count:
        pipeline_results["notifications_emitted"] = notif_count

    return pipeline_results
