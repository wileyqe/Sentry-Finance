"""
dal/cash_flow.py — Cash Flow page data queries.

Provides month-by-month, quarter-by-quarter, and year-by-year
aggregated income / expense / net / savings_rate data, plus
per-period category breakdowns.

Canonical SQL pattern (used by ALL aggregates in this module):

    income   = SUM(CASE WHEN signed_amount > 0
                         AND transfer_tag IS NULL
                         AND COALESCE(category,'Other Income') NOT IN <INCOME_EXCL_FROM_INC>
                        THEN signed_amount ELSE 0 END)

    spending = SUM(CASE WHEN signed_amount < 0
                         AND transfer_tag IS NULL
                         AND COALESCE(category,'Uncategorized') NOT IN <ALL_EXCL_FROM_SPEND>
                        THEN -signed_amount ELSE 0 END)

Both top-graph aggregates and drill-down KPIs use this exact pattern so a
graph bar's totals always equal the drill-down's totals for the same period.
See tests/test_cashflow_invariants.py for the regression wall.
"""

import sqlite3
import calendar
from typing import Optional

# Attribution-aware month expression.  effective_month is 'YYYY-MM' when
# an attribution rule stamps a transaction; NULL otherwise.  Kept for
# get_available_years (the only function below that still hits the
# transactions table directly).
_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"


# ── Monthly ───────────────────────────────────────────────────────────────────

def get_monthly_cash_flow(
    conn: sqlite3.Connection,
    year: int,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> list[dict]:
    """Income vs. spending for each month of ``year``.

    Migrated to ``compute_period_totals`` per-month.

    Returns 12-element list (Jan → Dec), zeroing months with no data:
      {month, label, income, spending, net, savings_rate, debt_service}
    """
    from dal.flow_aggregation import compute_period_totals

    result = []
    for m in range(1, 13):
        last_day = calendar.monthrange(year, m)[1]
        r = compute_period_totals(
            conn,
            start_date=f"{year}-{m:02d}-01",
            end_date=f"{year}-{m:02d}-{last_day:02d}",
            owner_id=owner_id,
            account_ids=account_ids,
        )
        result.append({
            "month": m,
            "label": calendar.month_abbr[m],
            "income": round(r["income_cents"] / 100.0, 2),
            "spending": round(r["spending_cents"] / 100.0, 2),
            "net": round(r["net_cents"] / 100.0, 2),
            "savings_rate": round(r["savings_rate"], 1) if r["savings_rate"] is not None else 0.0,
            "debt_service": round(r["debt_service_cents"] / 100.0, 2),
        })

    return result


# ── Quarterly ─────────────────────────────────────────────────────────────────

def get_quarterly_cash_flow(
    conn: sqlite3.Connection,
    year: int,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> list[dict]:
    """Income vs. spending aggregated by quarter for ``year``.

    Migrated to ``compute_period_totals`` per-quarter.

    Returns 4-element list (Q1 → Q4):
      {quarter, label, income, spending, net, savings_rate, debt_service}
    """
    from dal.flow_aggregation import compute_period_totals

    result = []
    for q in range(1, 5):
        start_month = (q - 1) * 3 + 1
        end_month = q * 3
        last_day = calendar.monthrange(year, end_month)[1]
        r = compute_period_totals(
            conn,
            start_date=f"{year}-{start_month:02d}-01",
            end_date=f"{year}-{end_month:02d}-{last_day:02d}",
            owner_id=owner_id,
            account_ids=account_ids,
        )
        result.append({
            "quarter": q,
            "label": f"Q{q}",
            "income": round(r["income_cents"] / 100.0, 2),
            "spending": round(r["spending_cents"] / 100.0, 2),
            "net": round(r["net_cents"] / 100.0, 2),
            "savings_rate": round(r["savings_rate"], 1) if r["savings_rate"] is not None else 0.0,
            "debt_service": round(r["debt_service_cents"] / 100.0, 2),
        })

    return result


# ── Monthly Rolling ──────────────────────────────────────────────────────────

def get_monthly_rolling_cash_flow(
    conn: sqlite3.Connection,
    months: int = 18,
    account_ids: list[str] | None = None,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Rolling window of the most recent ``months`` calendar months.

    As of PR2 of the spending-semantics overhaul, each per-month period
    is computed via ``compute_period_totals`` so the trend bars agree
    to the cent with the period drill-down KPIs and with Reports' flow
    data for the same window. New ``debt_service`` field included per
    period for the upcoming Cash Flow page UI work.

    Returns oldest-first list:
      {year, month, label, income, spending, net, savings_rate, debt_service}
    """
    from datetime import date
    from dal.flow_aggregation import compute_period_totals

    today = date.today()
    periods: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(months):
        periods.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    periods.reverse()  # oldest first

    result = []
    for yr, mo in periods:
        last_day = calendar.monthrange(yr, mo)[1]
        r = compute_period_totals(
            conn,
            start_date=f"{yr}-{mo:02d}-01",
            end_date=f"{yr}-{mo:02d}-{last_day:02d}",
            owner_id=owner_id,
            account_ids=account_ids,
        )
        income = round(r["income_cents"] / 100.0, 2)
        spending = round(r["spending_cents"] / 100.0, 2)
        net = round(r["net_cents"] / 100.0, 2)
        rate = round(r["savings_rate"], 1) if r["savings_rate"] is not None else 0.0
        label = f"{calendar.month_abbr[mo]} '{yr % 100:02d}"
        result.append({
            "year": yr,
            "month": mo,
            "label": label,
            "income": income,
            "spending": spending,
            "net": net,
            "savings_rate": rate,
            "debt_service": round(r["debt_service_cents"] / 100.0, 2),
            "debt_accumulated": round(r["debt_accumulated_cents"] / 100.0, 2),
            "debt_paid_down": round(r["debt_paid_down_cents"] / 100.0, 2),
            "net_debt_change": round(r["net_debt_change_cents"] / 100.0, 2),
        })

    return result


# ── Quarterly Rolling ────────────────────────────────────────────────────────

def get_quarterly_rolling_cash_flow(
    conn: sqlite3.Connection,
    quarters: int = 9,
    account_ids: list[str] | None = None,
    owner_id: str | None = None,
) -> list[dict]:
    """Rolling window of the most recent ``quarters`` calendar quarters.

    Migrated to ``compute_period_totals`` per-quarter — same semantics
    as ``get_monthly_rolling_cash_flow``.

    Returns oldest-first list:
      {year, quarter, label, income, spending, net, savings_rate, debt_service}
    """
    from datetime import date
    from dal.flow_aggregation import compute_period_totals
    import math

    today = date.today()
    cur_q = math.ceil(today.month / 3)
    cur_y = today.year

    periods: list[tuple[int, int]] = []
    y, q = cur_y, cur_q
    for _ in range(quarters):
        periods.append((y, q))
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    periods.reverse()

    result = []
    for yr, qtr in periods:
        start_month = (qtr - 1) * 3 + 1
        end_month = qtr * 3
        last_day = calendar.monthrange(yr, end_month)[1]
        r = compute_period_totals(
            conn,
            start_date=f"{yr}-{start_month:02d}-01",
            end_date=f"{yr}-{end_month:02d}-{last_day:02d}",
            owner_id=owner_id,
            account_ids=account_ids,
        )
        result.append({
            "year": yr,
            "quarter": qtr,
            "label": f"Q{qtr} '{yr % 100:02d}",
            "income": round(r["income_cents"] / 100.0, 2),
            "spending": round(r["spending_cents"] / 100.0, 2),
            "net": round(r["net_cents"] / 100.0, 2),
            "savings_rate": round(r["savings_rate"], 1) if r["savings_rate"] is not None else 0.0,
            "debt_service": round(r["debt_service_cents"] / 100.0, 2),
        })

    return result


# ── Yearly ────────────────────────────────────────────────────────────────────

def get_yearly_cash_flow(
    conn: sqlite3.Connection,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> list[dict]:
    """Income vs. spending aggregated by year.

    Migrated to ``compute_period_totals`` per-year. We discover which
    years have any transaction activity via a single cheap distinct
    query, then aggregate each year via the unified path.

    Returns oldest-first list:
      {year, label, income, spending, net, savings_rate, debt_service}
    """
    from dal.flow_aggregation import compute_period_totals
    from dal.owners import build_account_filter

    acct_sql, acct_params = build_account_filter(conn, owner_id, account_ids)

    # Discover the year range cheaply (no aggregation; uses idx_txn_effective_month).
    year_rows = conn.execute(
        f"""
        SELECT DISTINCT CAST(SUBSTR({_EM}, 1, 4) AS INTEGER) AS year
          FROM transactions
         WHERE status = 'posted'
           AND posting_date IS NOT NULL
           {acct_sql}
         ORDER BY year ASC
        """,
        acct_params,
    ).fetchall()

    result = []
    for yr_row in year_rows:
        yr = yr_row["year"]
        if yr is None:
            continue
        r = compute_period_totals(
            conn,
            start_date=f"{yr}-01-01",
            end_date=f"{yr}-12-31",
            owner_id=owner_id,
            account_ids=account_ids,
        )
        result.append({
            "year": yr,
            "label": str(yr),
            "income": round(r["income_cents"] / 100.0, 2),
            "spending": round(r["spending_cents"] / 100.0, 2),
            "net": round(r["net_cents"] / 100.0, 2),
            "savings_rate": round(r["savings_rate"], 1) if r["savings_rate"] is not None else 0.0,
            "debt_service": round(r["debt_service_cents"] / 100.0, 2),
        })

    return result


# ── Period detail (KPIs + categories) ─────────────────────────────────────────

def get_period_detail(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> dict:
    """Full detail for a specific date range: KPIs + ranked income/expense categories.

    As of PR2 of the spending-semantics overhaul, this delegates to the
    unified ``compute_period_totals`` aggregator. Headline numbers
    (income, spending, net, savings_rate) now follow the cash-out lens:
    debt-service payments (mortgage interest+escrow, CC payments via
    paired transfer, auto loan payments) ARE counted as spending; CC
    merchant purchases are NOT (they create a liability — surfaced via
    ``debt_accumulated`` instead). Income reflects gross paycheck via
    payroll snapshots (with full-gross fallback for unmatched snapshots).

    Returns the same JSON shape as before plus four new debt-* fields:
        income, spending, net, savings_rate,
        gross_savings_rate (now == savings_rate; kept for FE compat),
        gross_savings_rate_scope (kept for FE compat),
        income_categories, spending_categories,
        debt_service, debt_accumulated, debt_paid_down, net_debt_change,
        start_date, end_date
    """
    from dal.flow_aggregation import compute_period_totals
    r = compute_period_totals(
        conn,
        start_date=start_date,
        end_date=end_date,
        owner_id=owner_id,
        account_ids=account_ids,
    )

    income = round(r["income_cents"] / 100.0, 2)
    spending = round(r["spending_cents"] / 100.0, 2)
    net = round(r["net_cents"] / 100.0, 2)
    savings_rate = (
        round(r["savings_rate"], 1) if r["savings_rate"] is not None else 0.0
    )

    def _to_dollars_breakdown(rows: list[dict], total_cents: int) -> list[dict]:
        out = []
        for c in rows:
            tot_dollars = round(c["total_cents"] / 100.0, 2)
            if tot_dollars <= 0:
                continue
            out.append({
                "category": c["category"],
                "total": tot_dollars,
                "count": c["count"],
                "pct": (
                    round(c["total_cents"] / total_cents * 100, 1)
                    if total_cents > 0 else 0.0
                ),
            })
        return out

    return {
        "income": income,
        "spending": spending,
        "net": net,
        "savings_rate": savings_rate,
        # Under D3=grossup, income IS gross income (with payroll grossup
        # baked in). gross_savings_rate is therefore the same number as
        # savings_rate. Kept for frontend compat; scope retained as a
        # disclosure label.
        "gross_savings_rate": savings_rate,
        "gross_savings_rate_scope": "household_grossup",
        "income_categories": _to_dollars_breakdown(
            r["income_breakdown"], r["income_cents"]
        ),
        "spending_categories": _to_dollars_breakdown(
            r["spending_breakdown"], r["spending_cents"]
        ),
        # New debt-* fields (Stage 2 enrichment)
        "debt_service": round(r["debt_service_cents"] / 100.0, 2),
        "debt_accumulated": round(r["debt_accumulated_cents"] / 100.0, 2),
        "debt_paid_down": round(r["debt_paid_down_cents"] / 100.0, 2),
        "net_debt_change": round(r["net_debt_change_cents"] / 100.0, 2),
        "start_date": start_date,
        "end_date": end_date,
    }


# ── Available years ────────────────────────────────────────────────────────────

def get_available_years(
    conn: sqlite3.Connection,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> list[int]:
    """Return sorted list of years that have transaction data for the given scope."""
    from dal.owners import build_account_filter
    acct_sql, acct_params = build_account_filter(conn, owner_id, account_ids)

    rows = conn.execute(
        f"""
        SELECT DISTINCT CAST(strftime('%Y', posting_date) AS INTEGER) AS yr
        FROM transactions
        WHERE status = 'posted' AND posting_date IS NOT NULL
          {acct_sql}
        ORDER BY yr ASC
        """,
        acct_params,
    ).fetchall()
    return [r["yr"] for r in rows]
