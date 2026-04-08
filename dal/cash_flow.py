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

# ── Category sets — imported from canonical single source of truth ────────────
from dal.category_classifications import (
    ALL_EXCL_FROM_SPEND as _ALL_EXCL_FROM_SPEND,
    INCOME_EXCL_FROM_INC as _INCOME_EXCL_FROM_INC,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

# Attribution-aware month expression.  effective_month is 'YYYY-MM' when
# an attribution rule stamps a transaction; NULL otherwise.  This COALESCE
# makes attributed income appear in the correct month while leaving all
# other transactions grouped by their posting_date.
_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"


def _acct_filter_clause(account_ids: Optional[list[str]]) -> tuple[str, list]:
    """Return (sql_fragment, params) for optional account filter.

    Distinguishes ``None`` (no filter — return everything) from ``[]``
    (filter set but resolved to zero accounts — return nothing). See
    ``dal/owners.build_account_filter`` for the shared helper this
    mirrors; this inline version is kept so the cash_flow module stays
    a single Grep away from the canonical filter pattern.
    """
    if account_ids is None:
        return "", []
    if not account_ids:
        return " AND 1=0", []
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
    owner_id: str | None = None,
) -> list[dict]:
    """
    Income vs. spending for each month of ``year``.

    Returns 12-element list (Jan → Dec), zeroing months with no data:
      {month, label, income, spending, net, savings_rate}
    """
    income_excl = list(_INCOME_EXCL_FROM_INC)
    income_excl_ph = ", ".join("?" for _ in income_excl)

    excl = list(_ALL_EXCL_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)

    from dal.owners import resolve_owner_account_ids
    account_ids = resolve_owner_account_ids(conn, owner_id, account_ids)
    acct_sql, acct_params = _acct_filter_clause(account_ids)

    rows = conn.execute(
        f"""
        SELECT
            CAST(SUBSTR({_EM}, 6, 2) AS INTEGER) AS month_num,
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
          AND posting_date IS NOT NULL
          AND SUBSTR({_EM}, 1, 4) = ?
          {acct_sql}
        GROUP BY month_num
        ORDER BY month_num
        """,
        income_excl + excl + [str(year)] + acct_params,
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
    owner_id: str | None = None,
) -> list[dict]:
    """
    Income vs. spending aggregated by quarter for ``year``.

    Returns 4-element list (Q1 → Q4):
      {quarter, label, income, spending, net, savings_rate}
    """
    income_excl = list(_INCOME_EXCL_FROM_INC)
    income_excl_ph = ", ".join("?" for _ in income_excl)

    excl = list(_ALL_EXCL_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)

    from dal.owners import resolve_owner_account_ids
    account_ids = resolve_owner_account_ids(conn, owner_id, account_ids)
    acct_sql, acct_params = _acct_filter_clause(account_ids)

    rows = conn.execute(
        f"""
        SELECT
            CAST((CAST(SUBSTR({_EM}, 6, 2) AS INTEGER) - 1) / 3 + 1 AS INTEGER) AS quarter,
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
          AND posting_date IS NOT NULL
          AND SUBSTR({_EM}, 1, 4) = ?
          {acct_sql}
        GROUP BY quarter
        ORDER BY quarter
        """,
        income_excl + excl + [str(year)] + acct_params,
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
    owner_id: str | None = None,
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

    start_em = f"{periods[0][0]}-{periods[0][1]:02d}"
    end_y, end_m = periods[-1]
    end_em = f"{end_y}-{end_m:02d}"

    income_excl = list(_INCOME_EXCL_FROM_INC)
    income_excl_ph = ", ".join("?" for _ in income_excl)
    excl = list(_ALL_EXCL_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)
    from dal.owners import resolve_owner_account_ids
    account_ids = resolve_owner_account_ids(conn, owner_id, account_ids)
    acct_sql, acct_params = _acct_filter_clause(account_ids)

    # Filter by _EM (not posting_date) so attribution-stamped rows whose
    # effective_month is in-window but posting_date is out-of-window are
    # not silently dropped — and vice versa.
    rows = conn.execute(
        f"""
        SELECT
            CAST(SUBSTR({_EM}, 1, 4) AS INTEGER) AS year,
            CAST(SUBSTR({_EM}, 6, 2) AS INTEGER) AS month_num,
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
          AND posting_date IS NOT NULL
          AND {_EM} BETWEEN ? AND ?
          {acct_sql}
        GROUP BY year, month_num
        ORDER BY year, month_num
        """,
        income_excl + excl + [start_em, end_em] + acct_params,
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
    owner_id: str | None = None,
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

    # Build date range as YYYY-MM strings (canonical _EM filter).
    first_y, first_q = periods[0]
    start_month = (first_q - 1) * 3 + 1
    start_em = f"{first_y}-{start_month:02d}"

    last_y, last_q = periods[-1]
    end_month = last_q * 3
    end_em = f"{last_y}-{end_month:02d}"

    income_excl = list(_INCOME_EXCL_FROM_INC)
    income_excl_ph = ", ".join("?" for _ in income_excl)
    excl = list(_ALL_EXCL_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)
    from dal.owners import resolve_owner_account_ids
    account_ids = resolve_owner_account_ids(conn, owner_id, account_ids)
    acct_sql, acct_params = _acct_filter_clause(account_ids)

    # Filter by _EM (not posting_date) — see get_monthly_rolling_cash_flow.
    rows = conn.execute(
        f"""
        SELECT
            CAST(SUBSTR({_EM}, 1, 4) AS INTEGER) AS year,
            CAST((CAST(SUBSTR({_EM}, 6, 2) AS INTEGER) - 1) / 3 + 1 AS INTEGER) AS quarter,
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
          AND posting_date IS NOT NULL
          AND {_EM} BETWEEN ? AND ?
          {acct_sql}
        GROUP BY year, quarter
        ORDER BY year, quarter
        """,
        income_excl + excl + [start_em, end_em] + acct_params,
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
    owner_id: str | None = None,
) -> list[dict]:
    """
    Income vs. spending aggregated by year, across all available data.

    Returns oldest-first list:
      {year, label, income, spending, net, savings_rate}
    """
    income_excl = list(_INCOME_EXCL_FROM_INC)
    income_excl_ph = ", ".join("?" for _ in income_excl)

    excl = list(_ALL_EXCL_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)

    from dal.owners import resolve_owner_account_ids
    account_ids = resolve_owner_account_ids(conn, owner_id, account_ids)
    acct_sql, acct_params = _acct_filter_clause(account_ids)

    rows = conn.execute(
        f"""
        SELECT
            CAST(SUBSTR({_EM}, 1, 4) AS INTEGER) AS year,
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
          AND posting_date IS NOT NULL
          {acct_sql}
        GROUP BY year
        ORDER BY year ASC
        """,
        income_excl + excl + acct_params,
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
    owner_id: str | None = None,
) -> dict:
    """
    Full detail for a specific date range: KPIs + ranked income/expense categories.

    Filters by ``_EM`` (effective_month-aware) so attribution-stamped
    rows land in the same bucket as the top-graph aggregates that also
    use ``_EM``.  Filtering by raw posting_date here used to silently
    drift from the rolling/quarterly/yearly siblings — a top-graph bar
    for month X and the drill-down for month X could disagree the
    moment any income-attribution rule fired.

    Callers should pass month-aligned ranges (1st through last day of
    one or more whole months).  Mid-month ranges get rounded out to
    whole months — same semantics as the rolling cash-flow endpoints.

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

    from dal.owners import resolve_owner_account_ids
    account_ids = resolve_owner_account_ids(conn, owner_id, account_ids)
    acct_sql, acct_params = _acct_filter_clause(account_ids)

    # Convert ISO dates → YYYY-MM strings for canonical _EM filter.
    start_month = start_date[:7]
    end_month = end_date[:7]

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
          AND {_EM} BETWEEN ? AND ?
          {acct_sql}
        """,
        income_excl + excl + [start_month, end_month] + acct_params,
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
          AND {_EM} BETWEEN ? AND ?
          {acct_sql}
        GROUP BY category
        ORDER BY total DESC
        """,
        income_excl + [start_month, end_month] + acct_params,
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
          AND {_EM} BETWEEN ? AND ?
          {acct_sql}
        GROUP BY category
        ORDER BY total DESC
        """,
        excl + [start_month, end_month] + acct_params,
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

    # ── Gross (pre-tax) savings rate from payroll snapshots ─────────────
    # Sums payroll gross + tax for every month overlapping the period.
    # When no payroll data is present for the window, returns None and
    # the frontend hides the "/ Gross" subtitle rather than showing the
    # post-tax rate twice under different labels.
    gross_savings_rate: float | None = None
    gross_scope: str | None = None
    try:
        from dal.payroll import get_gross_income_for_month
        from dal.category_classifications import pre_tax_savings_rate

        # Walk every month covered by start_month..end_month inclusive.
        sy, sm = int(start_month[:4]), int(start_month[5:7])
        ey, em = int(end_month[:4]), int(end_month[5:7])
        gross_pay_total = 0.0
        tax_total = 0.0
        months_with_data = 0
        cy, cm = sy, sm
        while (cy, cm) <= (ey, em):
            row = get_gross_income_for_month(conn, cy, cm, owner_id=owner_id)
            if row is not None:
                gross_pay_total += row["gross_pay"]
                tax_total += row["federal_tax"] + row["state_tax"]
                months_with_data += 1
            cm += 1
            if cm > 12:
                cm = 1
                cy += 1

        if months_with_data > 0 and gross_pay_total > 0:
            gross_savings_rate = pre_tax_savings_rate(
                gross_pay_total, tax_total, spending
            )
            # Honest scope label: the payroll snapshot only covers the
            # myPay RAS pension stream, so this rate is pension-only,
            # not household-wide.  Frontend should disclose this.
            gross_scope = "pension_only"
    except Exception as e:
        log.warning("gross_savings_rate computation failed: %s", e)

    return {
        "income": income,
        "spending": spending,
        "net": net,
        "savings_rate": savings_rate,
        "gross_savings_rate": gross_savings_rate,
        "gross_savings_rate_scope": gross_scope,
        "income_categories": _cat_list(inc_rows, total_inc),
        "spending_categories": _cat_list(spd_rows, total_spd),
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
    from dal.owners import resolve_owner_account_ids
    account_ids = resolve_owner_account_ids(conn, owner_id, account_ids)
    acct_sql, acct_params = _acct_filter_clause(account_ids)

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
