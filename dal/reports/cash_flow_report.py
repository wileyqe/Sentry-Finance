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
    brokerage_buy_matches_transfer,
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


def get_cash_flow_report(
    conn: sqlite3.Connection,
    months: int = 12,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """
    Monthly cash flow: income vs. spending vs. net for a date window.

    Two ways to specify the window:
      1. Explicit ``start_date`` / ``end_date`` (YYYY-MM-DD).  Preferred.
         Anchored in local time on the frontend, no UTC drift.
      2. Legacy ``months`` int — UTC-anchored ``date('now', '-N months')``.
         Kept for backwards compat.  When both are supplied, the explicit
         dates win.

    Returns a list (oldest first) of:
      {month, income, spending, net, savings_rate}
    """
    # Canonical pattern (matches dal/cash_flow.py and get_flow_data):
    # income = positive signed_amount in any non-spend, non-transfer category;
    # spending = negative signed_amount in any non-income, non-transfer category.
    # Both sides drop transfer_tag rows.  Whitelist-based income filters
    # silently miss any new income category — switched to blacklist for
    # consistency with sibling endpoints.
    inc_excl_placeholders, income_excl = get_income_exclusion_clause()
    excl_placeholders, excl = get_spend_exclusion_clause()

    params_base = income_excl + excl

    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)

    # Resolve window — explicit dates win over legacy months int.
    if start_date and end_date:
        start_em = start_date[:7]
        end_em = end_date[:7]
        date_filter = f"AND {_EM} BETWEEN ? AND ?"
        date_params: list = [start_em, end_em]
    else:
        date_filter = f"AND posting_date >= date('now', '-{months} months')"
        date_params = []

    rows = conn.execute(
        f"""
        SELECT
            {_EM} as month,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND signed_amount > 0
                          AND COALESCE(category, 'Other Income') NOT IN ({inc_excl_placeholders})
                     THEN signed_amount ELSE 0 END) as income,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND signed_amount < 0
                          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
                     THEN -signed_amount ELSE 0 END) as spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          {date_filter}
          {acct_filter}
        GROUP BY month
        ORDER BY month ASC
        """,
        params_base + date_params + acct_params,
    ).fetchall()

    result = []
    for r in rows:
        income = round(r["income"] or 0, 2)
        spending = round(r["spending"] or 0, 2)
        net = round(income - spending, 2)
        savings_rate = round(net / income * 100, 1) if income > 0 else 0
        result.append({
            "month": r["month"],
            "income": income,
            "spending": spending,
            "net": net,
            "savings_rate": savings_rate,
        })

    return result
