"""
dal/reports.py — Parameterized report queries for the Sentry Finance dashboard.

Provides structured data for:
  - Spending by category (period, account, owner)
  - Cash flow (income vs. expense by month)
  - Net worth history (monthly snapshots)
  - CSV transaction export

All queries are read-only and ownership-aware.
"""

import logging
import sqlite3
from datetime import timedelta
from typing import Optional

from dal.category_classifications import (
    INCOME_CATEGORIES as _INCOME_CATEGORIES,
    get_spend_exclusion_clause,
)
from dal.clock import reference_date as clock_reference_date
from dal.flow_aggregation import compute_period_totals
from dal.owners import build_account_filter

log = logging.getLogger("sentry.dal.reports")

# ── Phase 14 Phase B — bucket invariant tolerance ─────────────────────────────
# Rounding drift between integer-cents splits and float signed_amount can
# accumulate to ~50¢ over a busy month. A $1 tolerance is the published
# contract; wider drift emits a structured warning.
_BUCKET_INVARIANT_TOLERANCE_CENTS: int = 100

# Attribution-aware month expression (mirrors dal/cash_flow.py)
_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"

# ── Category sets — imported from canonical single source of truth ────────────


# ── Spending by Category ──────────────────────────────────────────────────────


def get_spending_by_category(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    account_ids: Optional[list[str]] = None,
    exclude_transfers: bool = True,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Spending breakdown by category for a date range.

    Returns a list sorted by total_spent descending:
      {category, total_spent, transaction_count, avg_transaction, pct_of_total}
    """
    if exclude_transfers:
        excl_placeholders, excl = get_spend_exclusion_clause()
    else:
        excl = list(_INCOME_CATEGORIES)
        excl_placeholders = ", ".join("?" for _ in excl)

    params: list = [start_date, end_date] + excl

    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)
    params.extend(acct_params)

    excl_clause = f"AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})" if excl else ""

    rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Uncategorized') as category,
               SUM(-signed_amount) as total_spent,
               COUNT(*) as transaction_count,
               AVG(-signed_amount) as avg_transaction
        FROM transactions
        WHERE status = 'posted'
          AND transfer_tag IS NULL
          AND posting_date >= ?
          AND posting_date <= ?
          {excl_clause}
          {acct_filter}
        GROUP BY category
        ORDER BY total_spent DESC
        """,
        params,
    ).fetchall()

    total = sum(r["total_spent"] or 0 for r in rows)
    result = []
    for r in rows:
        spent = round(r["total_spent"] or 0, 2)
        result.append({
            "category": r["category"],
            "total_spent": spent,
            "transaction_count": r["transaction_count"],
            "avg_transaction": round(r["avg_transaction"] or 0, 2),
            "pct_of_total": round(spent / total * 100, 1) if total > 0 else 0,
        })

    return result


def get_category_trend(
    conn: sqlite3.Connection,
    category: str,
    months: int = 12,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Monthly spending trend for a single category.

    Returns oldest-first list of {month, total_spent, transaction_count}.
    """
    ref = clock_reference_date(conn)
    cutoff = (ref - timedelta(days=months * 30)).isoformat()

    params: list = [category, cutoff]
    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)
    params.extend(acct_params)

    rows = conn.execute(
        f"""
        SELECT {_EM} as month,
               SUM(-signed_amount) as total_spent,
               COUNT(*) as transaction_count
        FROM transactions
        WHERE status = 'posted'
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') = ?
          AND posting_date >= ?
          {acct_filter}
        GROUP BY month
        ORDER BY month ASC
        """,
        params,
    ).fetchall()

    return [
        {
            "month": r["month"],
            "total_spent": round(r["total_spent"] or 0, 2),
            "transaction_count": r["transaction_count"],
        }
        for r in rows
    ]


def get_period_summary(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> dict:
    """
    High-level summary for a date range.

    This uses the same canonical cash-out/gross-up lens as Cash Flow
    period detail and Reports flow data.
    """
    totals = compute_period_totals(
        conn,
        start_date=start_date,
        end_date=end_date,
        owner_id=owner_id,
        account_ids=account_ids,
    )
    total_income = round(totals["income_cents"] / 100.0, 2)
    total_spending = round(totals["spending_cents"] / 100.0, 2)
    savings_rate = (
        round(totals["savings_rate"], 1)
        if totals["savings_rate"] is not None
        else 0.0
    )

    spending = []
    for row in totals["spending_breakdown"]:
        total_spent = round(row["total_cents"] / 100.0, 2)
        if total_spent <= 0:
            continue
        spending.append({
            "category": row["category"],
            "total_spent": total_spent,
            "transaction_count": row["count"],
            "avg_transaction": (
                round(total_spent / row["count"], 2) if row["count"] else 0.0
            ),
            "pct_of_total": (
                round(row["total_cents"] / totals["spending_cents"] * 100, 1)
                if totals["spending_cents"] > 0
                else 0.0
            ),
        })
    top_categories = spending[:3]

    return {
        "period": {"start": start_date, "end": end_date},
        "total_income": round(total_income, 2),
        "total_spending": round(total_spending, 2),
        "net": round(total_income - total_spending, 2),
        "savings_rate": savings_rate,
        "debt_service": round(totals["debt_service_cents"] / 100.0, 2),
        "debt_accumulated": round(totals["debt_accumulated_cents"] / 100.0, 2),
        "debt_paid_down": round(totals["debt_paid_down_cents"] / 100.0, 2),
        "net_debt_change": round(totals["net_debt_change_cents"] / 100.0, 2),
        "definition": "cash_out_grossup",
        "top_categories": top_categories,
        "categories_with_spend": len(spending),
    }


def get_spending_comparison(
    conn: sqlite3.Connection,
    reference_date: str,
    timeframe: str = "month_vs_last_month",
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Cumulative spending comparison for different timeframes.
    Timeframes: month_vs_last_month, month_vs_last_year, month_vs_avg_month, year_vs_last_year
    """
    from datetime import datetime
    import calendar
    from dateutil.relativedelta import relativedelta

    ref_dt = datetime.strptime(reference_date, "%Y-%m-%d")
    current_day = ref_dt.day
    current_month = ref_dt.month
    
    excl_ph, excl = get_spend_exclusion_clause()

    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)

    if timeframe == "year_vs_last_year":
        this_year = ref_dt.year
        last_year = this_year - 1
        
        ty_rows = conn.execute(
            f"""
            SELECT cast(strftime('%m', posting_date) as integer) as month, SUM(-signed_amount) as spent
            FROM transactions
            WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
              AND strftime('%Y', posting_date) = ?
              {acct_filter}
            GROUP BY month
            """,
            excl + [str(this_year)] + acct_params
        ).fetchall()
        
        ly_rows = conn.execute(
            f"""
            SELECT cast(strftime('%m', posting_date) as integer) as month, SUM(-signed_amount) as spent
            FROM transactions
            WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
              AND strftime('%Y', posting_date) = ?
              {acct_filter}
            GROUP BY month
            """,
            excl + [str(last_year)] + acct_params
        ).fetchall()
        
        ty_map = {r["month"]: float(r["spent"] or 0) for r in ty_rows}
        ly_map = {r["month"]: float(r["spent"] or 0) for r in ly_rows}
        
        months_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        
        result = []
        cum_ty = 0.0
        cum_ly = 0.0
        
        for m in range(1, 13):
            cum_ly += ly_map.get(m, 0.0)
            # Keep the response shape stable — always emit Current, even
            # for future months. None (not 0) so the frontend can distinguish
            # "no data yet" from "spent nothing". Previously this key was
            # conditionally omitted, which made the chart silently change
            # shape between timeframes and forced defensive ``?.Previous``
            # chains downstream.
            data_point = {
                "period": months_names[m-1],
                "Previous": round(cum_ly, 2),
                "Current": None,
            }
            if ref_dt.year < clock_reference_date(conn).year or m <= current_month:
                cum_ty += ty_map.get(m, 0.0)
                data_point["Current"] = round(cum_ty, 2)
            result.append(data_point)
            
        return result

    # Monthly timeframes
    this_month_start = ref_dt.replace(day=1)
    _, last_day_this_month = calendar.monthrange(ref_dt.year, ref_dt.month)
    this_month_end = ref_dt.replace(day=last_day_this_month)
    
    this_month_rows = conn.execute(
        f"""
        SELECT cast(strftime('%d', posting_date) as integer) as day, SUM(-signed_amount) as daily_spent
        FROM transactions
        WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
          AND posting_date >= ? AND posting_date <= ?
          {acct_filter}
        GROUP BY day
        """,
        excl + [this_month_start.strftime("%Y-%m-%d"), this_month_end.strftime("%Y-%m-%d")] + acct_params,
    ).fetchall()
    this_month_map = {r["day"]: float(r["daily_spent"] or 0) for r in this_month_rows}
    
    prev_map = {}
    max_days = last_day_this_month
    last_day_prev = 31

    if timeframe == "month_vs_last_month":
        last_month_start = this_month_start - relativedelta(months=1)
        _, last_day_prev = calendar.monthrange(last_month_start.year, last_month_start.month)
        last_month_end = last_month_start.replace(day=last_day_prev)
        max_days = max(max_days, last_day_prev, 31)
        
        prev_rows = conn.execute(
            f"""
            SELECT cast(strftime('%d', posting_date) as integer) as day, SUM(-signed_amount) as daily_spent
            FROM transactions
            WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
              AND posting_date >= ? AND posting_date <= ?
              {acct_filter}
            GROUP BY day
            """,
            excl + [last_month_start.strftime("%Y-%m-%d"), last_month_end.strftime("%Y-%m-%d")] + acct_params,
        ).fetchall()
        prev_map = {r["day"]: float(r["daily_spent"] or 0) for r in prev_rows}

    elif timeframe == "month_vs_last_year":
        last_year_start = this_month_start - relativedelta(years=1)
        _, last_day_prev = calendar.monthrange(last_year_start.year, last_year_start.month)
        last_year_end = last_year_start.replace(day=last_day_prev)
        max_days = max(max_days, last_day_prev, 31)
        
        prev_rows = conn.execute(
            f"""
            SELECT cast(strftime('%d', posting_date) as integer) as day, SUM(-signed_amount) as daily_spent
            FROM transactions
            WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
              AND posting_date >= ? AND posting_date <= ?
              {acct_filter}
            GROUP BY day
            """,
            excl + [last_year_start.strftime("%Y-%m-%d"), last_year_end.strftime("%Y-%m-%d")] + acct_params,
        ).fetchall()
        prev_map = {r["day"]: float(r["daily_spent"] or 0) for r in prev_rows}

    elif timeframe == "month_vs_avg_month":
        avg_end = this_month_start - relativedelta(days=1)
        avg_start = this_month_start - relativedelta(months=6)
        max_days = max(max_days, 31)
        last_day_prev = 31
        
        prev_rows = conn.execute(
            f"""
            SELECT cast(strftime('%d', posting_date) as integer) as day, SUM(-signed_amount) as daily_spent
            FROM transactions
            WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
              AND posting_date >= ? AND posting_date <= ?
              {acct_filter}
            GROUP BY day
            """,
            excl + [avg_start.strftime("%Y-%m-%d"), avg_end.strftime("%Y-%m-%d")] + acct_params,
        ).fetchall()
        prev_map = {r["day"]: float(r["daily_spent"] or 0) / 6.0 for r in prev_rows}

    result = []
    cum_this = 0.0
    cum_prev = 0.0

    for day in range(1, max_days + 1):
        if day <= last_day_prev:
            cum_prev += prev_map.get(day, 0.0)
            
        data_point: dict = {
            "period": f"Day {day}",
            "Previous": round(cum_prev, 2)
        }
        
        if day <= current_day and day <= last_day_this_month:
            cum_this += this_month_map.get(day, 0.0)
            data_point["Current"] = round(cum_this, 2)

        result.append(data_point)

    return result
