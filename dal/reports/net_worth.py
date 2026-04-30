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

from dal.clock import reference_date
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


def get_net_worth_history(
    conn: sqlite3.Connection,
    months: int = 24,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Monthly net worth snapshots for the last N months, reconstructed from
    balance_snapshots + portfolio_snapshots + real_estate table.

    Returns oldest-first list of:
      {month, assets, liabilities, net_worth}
    """
    # Resolve owner filter via build_account_filter (returns the correct
    # AND 1=0 short-circuit when an owner owns zero accounts, so we don't
    # need a manual early-return to avoid falling through to "all
    # accounts").
    from dal.owners import build_account_filter
    acct_filter_and, acct_params = build_account_filter(
        conn, owner_id, None, column="a.id"
    )
    # First fragment slots after a CROSS JOIN with no WHERE of its own;
    # prepend WHERE when non-empty so the query parses. The " AND 1=0"
    # short-circuit equally works in either position.
    if acct_filter_and:
        acct_filter = "WHERE" + acct_filter_and[len(" AND"):]
    else:
        acct_filter = ""
    ref_date = reference_date(conn).isoformat()

    # Build monthly asset snapshots from balance_snapshots (banking accounts)
    banking_rows = conn.execute(
        f"""
        WITH RECURSIVE month_series AS (
            SELECT date(date(?, 'start of month'), '-{months - 1} months') as m_date
            UNION ALL
            SELECT date(m_date, '+1 month')
            FROM month_series
            WHERE m_date < date(?, 'start of month')
        ),
        latest_balances AS (
            SELECT ms.m_date, a.id as account_id, a.type, a.is_active,
                   (SELECT bs.balance 
                    FROM balance_snapshots bs
                    WHERE bs.account_id = a.id
                      AND bs.as_of < date(ms.m_date, '+1 month')
                    ORDER BY bs.as_of DESC LIMIT 1) as balance
            FROM month_series ms
            CROSS JOIN accounts a
            {acct_filter}
        )
        SELECT strftime('%Y-%m', m_date) as month,
               SUM(CASE WHEN type IN ('checking', 'savings') THEN balance ELSE 0 END) as banking,
               SUM(CASE WHEN type IN ('credit_card', 'loan', 'bnpl', 'mortgage') AND is_active = 1
                        THEN balance ELSE 0 END) as liabilities
        FROM latest_balances
        WHERE balance IS NOT NULL
        GROUP BY month
        ORDER BY month ASC
        """,
        [ref_date, ref_date] + acct_params,
    ).fetchall()

    # Portfolio monthly values (investment / retirement accounts)
    portfolio_rows = conn.execute(
        f"""
        WITH RECURSIVE month_series AS (
            SELECT date(date(?, 'start of month'), '-{months - 1} months') as m_date
            UNION ALL
            SELECT date(m_date, '+1 month')
            FROM month_series
            WHERE m_date < date(?, 'start of month')
        ),
        latest_portfolios AS (
            SELECT ms.m_date, a.id as account_id,
                   (SELECT ps.total_account_value
                    FROM portfolio_snapshots ps
                    WHERE ps.account_id = a.id
                      AND ps.timestamp < date(ms.m_date, '+1 month')
                    ORDER BY ps.timestamp DESC LIMIT 1) as total_account_value
            FROM month_series ms
            CROSS JOIN accounts a
            WHERE a.type IN ('investment', 'retirement')
            {acct_filter_and}
        )
        SELECT strftime('%Y-%m', m_date) as month,
               SUM(total_account_value) as portfolio
        FROM latest_portfolios
        WHERE total_account_value IS NOT NULL
        GROUP BY month
        """,
        [ref_date, ref_date] + acct_params,
    ).fetchall()

    portfolio_map = {r["month"]: (r["portfolio"] or 0) for r in portfolio_rows}

    # Build time-aware real estate values per month.
    # When owner-scoped, restrict to that owner's properties (added in v22).
    re_sql = """
        SELECT name, estimated_value, as_of
        FROM real_estate
        WHERE name NOT LIKE '%[%'
    """
    re_params: list = []
    if owner_id:
        re_sql += " AND LOWER(owner_id) = LOWER(?)"
        re_params.append(owner_id)
    re_sql += " ORDER BY name, as_of ASC"
    re_rows = conn.execute(re_sql, re_params).fetchall()

    from collections import defaultdict
    re_timeline: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in re_rows:
        re_timeline[r["name"]].append((r["as_of"][:7], r["estimated_value"]))

    re_by_month: dict[str, float] = {}
    for r in banking_rows:
        month_str = r["month"]
        total = 0.0
        for prop_name, valuations in re_timeline.items():
            latest = None
            for val_month, val_amount in valuations:
                if val_month <= month_str:
                    latest = val_amount
                else:
                    break
            if latest is not None:
                total += latest
        re_by_month[month_str] = total

    # Build time-aware vehicle values per month.
    # When owner-scoped, restrict via vehicle_assets.owner_id (added in v22).
    veh_by_month: dict[str, float] = {}
    try:
        veh_sql = """
            SELECT vv.vehicle_id as name, vv.estimated_value,
                   vv.valuation_date as as_of
            FROM vehicle_valuations vv
        """
        veh_params: list = []
        if owner_id:
            veh_sql += """
                JOIN vehicle_assets va ON va.id = vv.vehicle_id
                WHERE LOWER(va.owner_id) = LOWER(?)
            """
            veh_params.append(owner_id)
        veh_sql += " ORDER BY name, as_of ASC"
        vehicle_rows = conn.execute(veh_sql, veh_params).fetchall()

        veh_timeline: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for r in vehicle_rows:
            veh_timeline[r["name"]].append((r["as_of"][:7], r["estimated_value"]))

        for r in banking_rows:
            month_str = r["month"]
            total = 0.0
            for veh_name, valuations in veh_timeline.items():
                latest = None
                for val_month, val_amount in valuations:
                    if val_month <= month_str:
                        latest = val_amount
                    else:
                        break
                if latest is not None:
                    total += latest
            veh_by_month[month_str] = total
    except sqlite3.OperationalError:
        pass

    result = []
    for r in banking_rows:
        month = r["month"]
        banking = r["banking"] or 0
        liabilities = r["liabilities"] or 0
        portfolio = portfolio_map.get(month, 0)
        re_value_for_month = re_by_month.get(month, 0.0)
        veh_value_for_month = veh_by_month.get(month, 0.0)
        
        assets = round(banking + portfolio + re_value_for_month + veh_value_for_month, 2)
        net_worth = round(assets + liabilities, 2)  # liabilities are already negative

        result.append({
            "month": month,
            "banking_assets": round(banking, 2),
            "investment_assets": round(portfolio, 2),
            "real_estate_assets": round(re_value_for_month, 2),
            "vehicle_assets": round(veh_value_for_month, 2),
            "assets": assets,
            "liabilities": round(liabilities, 2),
            "net_worth": net_worth,
        })

    return result
