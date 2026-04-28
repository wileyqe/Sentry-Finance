"""
dal/reports.py — Parameterized report queries for the Sentry Finance dashboard.

Provides structured data for:
  - Spending by category (period, account, owner)
  - Cash flow (income vs. expense by month)
  - Net worth history (monthly snapshots)
  - CSV transaction export

All queries are read-only and ownership-aware.
"""

import csv
import io
import logging
import sqlite3
from datetime import date, timedelta
from typing import Optional

from dal.owners import build_account_filter
from dal.payroll import find_matching_deposit_tx_id, get_flow_contribution
from dal.flow_classification import (
    BucketLabel,
    match_rule_matches,
)
from dal import income_sources as income_sources_dal

log = logging.getLogger("sentry.dal.reports")

# ── Phase 14 Phase B — bucket invariant tolerance ─────────────────────────────
# Rounding drift between integer-cents splits and float signed_amount can
# accumulate to ~50¢ over a busy month. A $1 tolerance is the published
# contract; wider drift emits a structured warning.
_BUCKET_INVARIANT_TOLERANCE_CENTS: int = 100

# Attribution-aware month expression (mirrors dal/cash_flow.py)
_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"

# ── Category sets — imported from canonical single source of truth ────────────
from dal.category_classifications import (
    INCOME_CATEGORIES as _INCOME_CATEGORIES,
    INCOME_EXCL_FROM_INC as _INCOME_EXCL_FROM_INC,
    get_income_exclusion_clause,
    get_spend_exclusion_clause,
)


# ── Spending by Category ──────────────────────────────────────────────────────


def export_transactions_csv(
    conn: sqlite3.Connection,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_ids: Optional[list[str]] = None,
    institution_id: Optional[str] = None,
    owner_id: str | None = None,
) -> str:
    """
    Export transactions to a CSV string.

    Columns: date, description, category, amount, direction, account_id,
             institution_id, status
    """
    clauses = ["status != 'deleted'"]
    params: list = []

    if start_date:
        clauses.append("posting_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("posting_date <= ?")
        params.append(end_date)
    if institution_id:
        clauses.append("institution_id = ?")
        params.append(institution_id)
    # This function composes its WHERE via a `clauses` list rather than a
    # single string, so we strip the leading " AND " the helper prepends.
    acct_sql, acct_params = build_account_filter(conn, owner_id, account_ids)
    if acct_sql:
        clauses.append(acct_sql.lstrip()[4:])
        params.extend(acct_params)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT posting_date, description, category, amount, signed_amount,
               direction, account_id, institution_id, status
        FROM transactions
        WHERE {where}
        ORDER BY posting_date DESC, created_at DESC
        """,
        params,
    ).fetchall()

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "date", "description", "category", "amount", "signed_amount",
            "direction", "account_id", "institution_id", "status",
        ],
    )
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "date": r["posting_date"],
            "description": r["description"] or "",
            "category": r["category"] or "Uncategorized",
            "amount": r["amount"],
            "signed_amount": r["signed_amount"],
            "direction": r["direction"],
            "account_id": r["account_id"],
            "institution_id": r["institution_id"],
            "status": r["status"],
        })

    return output.getvalue()
