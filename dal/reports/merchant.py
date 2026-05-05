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

from dal import clock as _clock
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


def get_merchant_list(
    conn: sqlite3.Connection,
    months: int = 6,
    limit: int = 50,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Return ranked merchants by spend for the period with per-month totals.

    Each entry:
      { merchant, total, tx_count, category, monthly: [{month, total}, ...] }
    """
    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)

    excl_ph, excl = get_spend_exclusion_clause()

    # Compute lookback cutoff from the reference clock
    ref = _clock.reference_date(conn)
    cutoff = (ref - timedelta(days=months * 30)).isoformat()

    # Ranked totals — real spend only: no income, no transfers
    rank_rows = conn.execute(
        f"""
        SELECT
            COALESCE(merchant, description) AS merchant,
            SUM(ABS(signed_amount))         AS total,
            COUNT(*)                        AS tx_count,
            MAX(category)                   AS category
        FROM transactions
        WHERE signed_amount < 0
          AND transfer_tag IS NULL
          AND COALESCE(category, '') NOT IN ({excl_ph})
          AND posting_date >= ?
          {acct_filter}
          AND merchant IS NOT NULL
        GROUP BY COALESCE(merchant, description)
        ORDER BY total DESC
        LIMIT ?
        """,
        excl + [cutoff] + acct_params + [limit],
    ).fetchall()

    if not rank_rows:
        return []

    merchant_names = [r["merchant"] for r in rank_rows]
    placeholders_m = ",".join("?" for _ in merchant_names)

    # Monthly breakdown per merchant
    monthly_rows = conn.execute(
        f"""
        SELECT
            COALESCE(merchant, description) AS merchant,
            {_EM} AS month,
            SUM(ABS(signed_amount))         AS total
        FROM transactions
        WHERE signed_amount < 0
          AND transfer_tag IS NULL
          AND COALESCE(category, '') NOT IN ({excl_ph})
          AND posting_date >= ?
          AND COALESCE(merchant, description) IN ({placeholders_m})
          {acct_filter}
        GROUP BY COALESCE(merchant, description), {_EM}
        ORDER BY month
        """,
        excl + [cutoff] + merchant_names + acct_params,
    ).fetchall()

    # Index monthly data by merchant
    from collections import defaultdict
    monthly_map: dict[str, list] = defaultdict(list)
    for r in monthly_rows:
        monthly_map[r["merchant"]].append(
            {"month": r["month"], "total": round(r["total"] or 0, 2)}
        )

    result = []
    for r in rank_rows:
        result.append({
            "merchant": r["merchant"],
            "total": round(r["total"] or 0, 2),
            "tx_count": r["tx_count"],
            "category": r["category"],
            "monthly": monthly_map.get(r["merchant"], []),
        })
    return result


def get_merchant_flow_data(
    conn: sqlite3.Connection,
    months: int = 6,
    selected_merchants: Optional[list[str]] = None,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> dict:
    """
    Return Sankey-shaped data with selected merchants as spending nodes.

    If selected_merchants is None/empty → auto-select top 10.
    Unselected merchants are collapsed into "Other".

    Returns same shape as get_flow_data() for drop-in chart compatibility.
    """
    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)

    # Compute lookback cutoff from the reference clock
    ref = _clock.reference_date(conn)
    cutoff = (ref - timedelta(days=months * 30)).isoformat()

    # Income side — uses canonical exclusion set
    income_excl = list(_INCOME_EXCL_FROM_INC | {"Uncategorized"})
    income_excl_ph = ",".join("?" for _ in income_excl)

    income_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Other Income') AS category,
               SUM(signed_amount)                 AS total,
               COUNT(*)                           AS count
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount > 0
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Other Income') NOT IN ({income_excl_ph})
          AND posting_date >= ?
          {acct_filter}
        GROUP BY category ORDER BY total DESC
        """,
        income_excl + [cutoff] + acct_params,
    ).fetchall()

    total_income = round(sum(r["total"] or 0 for r in income_rows), 2)
    income_cats = [
        {"category": r["category"], "total": round(r["total"] or 0, 2), "count": r["count"]}
        for r in income_rows
    ]

    # Spending side — real spend only: signed_amount < 0, no transfers
    spend_excl_ph, spend_excl = get_spend_exclusion_clause()

    # All spending by merchant
    all_spend = conn.execute(
        f"""
        SELECT
            COALESCE(merchant, description) AS merchant,
            SUM(ABS(signed_amount))         AS total,
            COUNT(*)                        AS count
        FROM transactions
        WHERE signed_amount < 0
          AND transfer_tag IS NULL
          AND COALESCE(category, '') NOT IN ({spend_excl_ph})
          AND posting_date >= ?
          {acct_filter}
          AND merchant IS NOT NULL
        GROUP BY COALESCE(merchant, description)
        ORDER BY total DESC
        """,
        spend_excl + [cutoff] + acct_params,
    ).fetchall()

    # Auto-select top 10 if no selection provided
    if not selected_merchants:
        selected_merchants = [r["merchant"] for r in all_spend[:10]]

    selected_set = set(selected_merchants)
    selected_totals: dict[str, float] = {}
    other_total = 0.0

    for r in all_spend:
        m = r["merchant"]
        t = r["total"] or 0
        if m in selected_set:
            selected_totals[m] = round(t, 2)
        else:
            other_total += t

    # Build spending nodes in selection order
    spend_cats = [
        {"category": m, "total": selected_totals.get(m, 0), "count": 0}
        for m in selected_merchants
        if m in selected_totals
    ]
    if other_total > 0.01:
        spend_cats.append({"category": "Other", "total": round(other_total, 2), "count": 0})

    total_spending = round(sum(c["total"] for c in spend_cats), 2)
    net = round(total_income - total_spending, 2)
    savings_rate = round(net / total_income * 100, 1) if total_income > 0 else 0

    return {
        "income_categories": income_cats,
        "spending_categories": spend_cats,
        "total_income": total_income,
        "total_spending": total_spending,
        "net": net,
        "savings_rate": savings_rate,
        "available_merchants": [r["merchant"] for r in all_spend],
        "selected_merchants": selected_merchants,
    }
