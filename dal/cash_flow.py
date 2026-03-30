"""
dal/cash_flow.py — Cash Flow page data queries.

Provides month-by-month, quarter-by-quarter, and year-by-year
aggregated income / expense / net / savings_rate data, plus
per-period category breakdowns.
"""

import sqlite3
import calendar
from typing import Optional

# ── Shared category sets (mirrors dal/reports.py) ─────────────────────────────

_INCOME_CATEGORIES = {
    "Income",
    "Paychecks/Salary",
    "Rental Income",
    "Deposits",
    "Interest",
    "Investment Income",
    "Retirement Income",
    "Tax Refund",
    "Other Income",
    "Military Pension",
    "VA Benefits",
    "VA Education Benefits",
    "Officiating Income",
}

_EXCLUDED_FROM_SPEND = {
    "Transfers",
    "Transfer",
    "Credit Card Payments",
    "Refunds/Adjustments",
    "Mortgage",
    "Auto Loan",
}

# income categories that are NOT spending (used to exclude from expense rows)
_ALL_EXCL_FROM_SPEND = _EXCLUDED_FROM_SPEND | _INCOME_CATEGORIES

# spending categories that are NOT income
_INCOME_EXCL_FROM_INC = _EXCLUDED_FROM_SPEND | {
    "Deposits", "Transfer", "Mortgage",
    "Groceries", "Dining", "Shopping", "Entertainment",
    "Travel", "Utilities", "Auto", "Medical", "Insurance",
    "Home Improvement",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _acct_filter_clause(account_ids: Optional[list[str]]) -> tuple[str, list]:
    """Return (sql_fragment, params) for optional account filter."""
    if not account_ids:
        return "", []
    placeholders = ", ".join("?" for _ in account_ids)
    return f" AND account_id IN ({placeholders})", list(account_ids)


def _row_to_period(row) -> dict:
    income = round(row["income"] or 0, 2)
    spending = round(row["spending"] or 0, 2)
    net = round(income - spending, 2)
    savings_rate = round(net / income * 100, 1) if income > 0 else 0.0
    return {
        "income": income,
        "spending": spending,
        "net": net,
        "savings_rate": savings_rate,
    }


# ── Monthly ───────────────────────────────────────────────────────────────────

def get_monthly_cash_flow(
    conn: sqlite3.Connection,
    year: int,
    account_ids: Optional[list[str]] = None,
) -> list[dict]:
    """
    Income vs. spending for each month of ``year``.

    Returns 12-element list (Jan → Dec), zeroing months with no data:
      {month, label, income, spending, net, savings_rate}
    """
    inc_cats = list(_INCOME_CATEGORIES)
    inc_ph = ", ".join("?" for _ in inc_cats)

    excl = list(_ALL_EXCL_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)

    acct_sql, acct_params = _acct_filter_clause(account_ids)

    rows = conn.execute(
        f"""
        SELECT
            CAST(strftime('%m', posting_date) AS INTEGER) AS month_num,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND COALESCE(category, 'Other Income') IN ({inc_ph})
                     THEN signed_amount ELSE 0 END) AS income,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
                     THEN -signed_amount ELSE 0 END) AS spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND strftime('%Y', posting_date) = ?
          {acct_sql}
        GROUP BY month_num
        ORDER BY month_num
        """,
        inc_cats + excl + [str(year)] + acct_params,
    ).fetchall()

    row_map = {r["month_num"]: r for r in rows}

    result = []
    for m in range(1, 13):
        r = row_map.get(m)
        label = calendar.month_abbr[m]  # "Jan", "Feb", …
        if r:
            period = _row_to_period(r)
        else:
            period = {"income": 0.0, "spending": 0.0, "net": 0.0, "savings_rate": 0.0}
        result.append({"month": m, "label": label, **period})

    return result


# ── Quarterly ─────────────────────────────────────────────────────────────────

def get_quarterly_cash_flow(
    conn: sqlite3.Connection,
    year: int,
    account_ids: Optional[list[str]] = None,
) -> list[dict]:
    """
    Income vs. spending aggregated by quarter for ``year``.

    Returns 4-element list (Q1 → Q4):
      {quarter, label, income, spending, net, savings_rate}
    """
    inc_cats = list(_INCOME_CATEGORIES)
    inc_ph = ", ".join("?" for _ in inc_cats)

    excl = list(_ALL_EXCL_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)

    acct_sql, acct_params = _acct_filter_clause(account_ids)

    rows = conn.execute(
        f"""
        SELECT
            CAST((CAST(strftime('%m', posting_date) AS INTEGER) - 1) / 3 + 1 AS INTEGER) AS quarter,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND COALESCE(category, 'Other Income') IN ({inc_ph})
                     THEN signed_amount ELSE 0 END) AS income,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
                     THEN -signed_amount ELSE 0 END) AS spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND strftime('%Y', posting_date) = ?
          {acct_sql}
        GROUP BY quarter
        ORDER BY quarter
        """,
        inc_cats + excl + [str(year)] + acct_params,
    ).fetchall()

    row_map = {r["quarter"]: r for r in rows}
    result = []
    for q in range(1, 5):
        r = row_map.get(q)
        label = f"Q{q}"
        if r:
            period = _row_to_period(r)
        else:
            period = {"income": 0.0, "spending": 0.0, "net": 0.0, "savings_rate": 0.0}
        result.append({"quarter": q, "label": label, **period})

    return result


# ── Monthly Rolling ──────────────────────────────────────────────────────────

def get_monthly_rolling_cash_flow(
    conn: sqlite3.Connection,
    months: int = 18,
    account_ids: list[str] | None = None,
) -> list[dict]:
    """
    Rolling window of the most recent ``months`` calendar months.

    Returns oldest-first list:
      {year, month, label, income, spending, net, savings_rate}
    """
    from datetime import date

    today = date.today()
    # Build list of (year, month) tuples for the window
    periods: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(months):
        periods.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    periods.reverse()  # oldest first

    start_date = f"{periods[0][0]}-{periods[0][1]:02d}-01"
    end_y, end_m = periods[-1]
    end_day = calendar.monthrange(end_y, end_m)[1]
    end_date = f"{end_y}-{end_m:02d}-{end_day:02d}"

    inc_cats = list(_INCOME_CATEGORIES)
    inc_ph = ", ".join("?" for _ in inc_cats)
    excl = list(_ALL_EXCL_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)
    acct_sql, acct_params = _acct_filter_clause(account_ids)

    rows = conn.execute(
        f"""
        SELECT
            CAST(strftime('%Y', posting_date) AS INTEGER) AS year,
            CAST(strftime('%m', posting_date) AS INTEGER) AS month_num,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND COALESCE(category, 'Other Income') IN ({inc_ph})
                     THEN signed_amount ELSE 0 END) AS income,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
                     THEN -signed_amount ELSE 0 END) AS spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND posting_date >= ? AND posting_date <= ?
          {acct_sql}
        GROUP BY year, month_num
        ORDER BY year, month_num
        """,
        inc_cats + excl + [start_date, end_date] + acct_params,
    ).fetchall()

    row_map = {(r["year"], r["month_num"]): r for r in rows}

    result = []
    for yr, mo in periods:
        r = row_map.get((yr, mo))
        label = f"{calendar.month_abbr[mo]} '{yr % 100:02d}"
        if r:
            period = _row_to_period(r)
        else:
            period = {"income": 0.0, "spending": 0.0, "net": 0.0, "savings_rate": 0.0}
        result.append({"year": yr, "month": mo, "label": label, **period})

    return result


# ── Quarterly Rolling ────────────────────────────────────────────────────────

def get_quarterly_rolling_cash_flow(
    conn: sqlite3.Connection,
    quarters: int = 9,
    account_ids: list[str] | None = None,
) -> list[dict]:
    """
    Rolling window of the most recent ``quarters`` calendar quarters.

    Returns oldest-first list:
      {year, quarter, label, income, spending, net, savings_rate}
    """
    from datetime import date
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
    periods.reverse()  # oldest first

    # Build date range
    first_y, first_q = periods[0]
    start_month = (first_q - 1) * 3 + 1
    start_date = f"{first_y}-{start_month:02d}-01"

    last_y, last_q = periods[-1]
    end_month = last_q * 3
    end_day = calendar.monthrange(last_y, end_month)[1]
    end_date = f"{last_y}-{end_month:02d}-{end_day:02d}"

    inc_cats = list(_INCOME_CATEGORIES)
    inc_ph = ", ".join("?" for _ in inc_cats)
    excl = list(_ALL_EXCL_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)
    acct_sql, acct_params = _acct_filter_clause(account_ids)

    rows = conn.execute(
        f"""
        SELECT
            CAST(strftime('%Y', posting_date) AS INTEGER) AS year,
            CAST((CAST(strftime('%m', posting_date) AS INTEGER) - 1) / 3 + 1 AS INTEGER) AS quarter,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND COALESCE(category, 'Other Income') IN ({inc_ph})
                     THEN signed_amount ELSE 0 END) AS income,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
                     THEN -signed_amount ELSE 0 END) AS spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND posting_date >= ? AND posting_date <= ?
          {acct_sql}
        GROUP BY year, quarter
        ORDER BY year, quarter
        """,
        inc_cats + excl + [start_date, end_date] + acct_params,
    ).fetchall()

    row_map = {(r["year"], r["quarter"]): r for r in rows}

    result = []
    for yr, qtr in periods:
        r = row_map.get((yr, qtr))
        label = f"Q{qtr} '{yr % 100:02d}"
        if r:
            period = _row_to_period(r)
        else:
            period = {"income": 0.0, "spending": 0.0, "net": 0.0, "savings_rate": 0.0}
        result.append({"year": yr, "quarter": qtr, "label": label, **period})

    return result


# ── Yearly ────────────────────────────────────────────────────────────────────

def get_yearly_cash_flow(
    conn: sqlite3.Connection,
    account_ids: Optional[list[str]] = None,
) -> list[dict]:
    """
    Income vs. spending aggregated by year, across all available data.

    Returns oldest-first list:
      {year, label, income, spending, net, savings_rate}
    """
    inc_cats = list(_INCOME_CATEGORIES)
    inc_ph = ", ".join("?" for _ in inc_cats)

    excl = list(_ALL_EXCL_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)

    acct_sql, acct_params = _acct_filter_clause(account_ids)

    rows = conn.execute(
        f"""
        SELECT
            CAST(strftime('%Y', posting_date) AS INTEGER) AS year,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND COALESCE(category, 'Other Income') IN ({inc_ph})
                     THEN signed_amount ELSE 0 END) AS income,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
                     THEN -signed_amount ELSE 0 END) AS spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          {acct_sql}
        GROUP BY year
        ORDER BY year ASC
        """,
        inc_cats + excl + acct_params,
    ).fetchall()

    result = []
    for r in rows:
        period = _row_to_period(r)
        yr = r["year"]
        result.append({"year": yr, "label": str(yr), **period})

    return result


# ── Period detail (KPIs + categories) ─────────────────────────────────────────

def get_period_detail(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    account_ids: Optional[list[str]] = None,
) -> dict:
    """
    Full detail for a specific date range: KPIs + ranked income/expense categories.

    Returns:
      {income, spending, net, savings_rate, gross_savings_rate,
       income_categories: [{category, total, pct}],
       spending_categories: [{category, total, pct}]}
    """
    # ── income excl list for income side ─────────────────────────────────────
    income_excl = list(_INCOME_EXCL_FROM_INC)
    income_excl_ph = ", ".join("?" for _ in income_excl)

    excl = list(_ALL_EXCL_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)

    acct_sql, acct_params = _acct_filter_clause(account_ids)

    # KPIs
    kpi_row = conn.execute(
        f"""
        SELECT
            SUM(CASE WHEN transfer_tag IS NULL
                          AND signed_amount > 0
                          AND COALESCE(category, 'Other Income') NOT IN ({income_excl_ph})
                     THEN signed_amount ELSE 0 END) AS income,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND signed_amount < 0
                          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
                     THEN -signed_amount ELSE 0 END) AS spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date >= ? AND posting_date <= ?
          {acct_sql}
        """,
        income_excl + excl + [start_date, end_date] + acct_params,
    ).fetchone()

    income = round(kpi_row["income"] or 0, 2)
    spending = round(kpi_row["spending"] or 0, 2)
    net = round(income - spending, 2)
    savings_rate = round(net / income * 100, 1) if income > 0 else 0.0

    # Income categories
    inc_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Other Income') AS category,
               SUM(signed_amount) AS total,
               COUNT(*) AS count
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount > 0
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Other Income') NOT IN ({income_excl_ph})
          AND posting_date >= ? AND posting_date <= ?
          {acct_sql}
        GROUP BY category
        ORDER BY total DESC
        """,
        income_excl + [start_date, end_date] + acct_params,
    ).fetchall()

    # Spend categories
    spd_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Uncategorized') AS category,
               SUM(-signed_amount) AS total,
               COUNT(*) AS count
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount < 0
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
          AND posting_date >= ? AND posting_date <= ?
          {acct_sql}
        GROUP BY category
        ORDER BY total DESC
        """,
        excl + [start_date, end_date] + acct_params,
    ).fetchall()

    def _cat_list(rows, total):
        return [
            {
                "category": r["category"],
                "total": round(r["total"] or 0, 2),
                "count": r["count"],
                "pct": round((r["total"] or 0) / total * 100, 1) if total > 0 else 0.0,
            }
            for r in rows
            if (r["total"] or 0) > 0
        ]

    total_inc = sum(r["total"] or 0 for r in inc_rows)
    total_spd = sum(r["total"] or 0 for r in spd_rows)

    return {
        "income": income,
        "spending": spending,
        "net": net,
        "savings_rate": savings_rate,
        "gross_savings_rate": savings_rate,   # same until pre-tax data available
        "income_categories": _cat_list(inc_rows, total_inc),
        "spending_categories": _cat_list(spd_rows, total_spd),
        "start_date": start_date,
        "end_date": end_date,
    }


# ── Available years ────────────────────────────────────────────────────────────

def get_available_years(conn: sqlite3.Connection) -> list[int]:
    """Return sorted list of years that have transaction data."""
    rows = conn.execute(
        """
        SELECT DISTINCT CAST(strftime('%Y', posting_date) AS INTEGER) AS yr
        FROM transactions
        WHERE status = 'posted' AND posting_date IS NOT NULL
        ORDER BY yr ASC
        """
    ).fetchall()
    return [r["yr"] for r in rows]
