"""
dal/lifestyle.py — Lifestyle creep detection.

Compares per-category spending growth rates against income growth rate
to identify categories where spending is outpacing income.
"""

import sqlite3
import logging
from datetime import date, timedelta

log = logging.getLogger("sentry.dal.lifestyle")

# Import income categories from the canonical source
from dal.cash_flow import _INCOME_CATEGORIES

# Categories that should never be flagged (non-discretionary)
_EXCLUDED_FROM_CREEP = frozenset([
    "Mortgage",
    "Rent",
    "Auto Loan",
    "Utilities",
    "Health Insurance",
    "Insurance",
    "Transfers",
    "Credit Card Payments",
    "Tax Refund",
    "Non-Recurring Income",
])

# Minimum spending threshold — categories below this annual total
# are too small to flag meaningfully
_MIN_ANNUAL_SPEND = 500.0


def get_lifestyle_creep(
    conn: sqlite3.Connection,
    lookback_years: int = 2,
    flag_threshold_pct: float = 5.0,
    owner_id: str | None = None,
) -> dict:
    """
    Detect spending categories growing faster than income.

    Args:
        conn: DB connection
        lookback_years: Number of complete 12-month periods to analyze.
                        Requires at least 2 periods (can't compute growth
                        with less than 2 data points).
        flag_threshold_pct: Flag a category when its annualized growth
                            rate exceeds income growth by this many
                            percentage points.

    Returns:
    {
        "period_start": "YYYY-MM-DD",
        "period_end": "YYYY-MM-DD",
        "income_growth_pct": float | None,
        "categories": [...],
        "flagged_count": int,
        "flag_threshold_pct": float,
    }
    """
    lookback_years = max(2, lookback_years)

    # ── 1. Determine the analysis window ─────────────────────────────
    today = date.today()
    # End of last complete calendar month
    first_of_this_month = today.replace(day=1)
    period_end = first_of_this_month - timedelta(days=1)  # last day of prior month

    # Count back lookback_years * 12 months for the full window
    total_months = lookback_years * 12
    # Start of the window: go back total_months from start of last complete month
    y = period_end.year
    m = period_end.month
    for _ in range(total_months):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    period_start = date(y, m + 1, 1) if m < 12 else date(y + 1, 1, 1)
    # Simplify: first day of the month that is total_months before the end month
    end_y, end_m = period_end.year, period_end.month
    start_y = end_y
    start_m = end_m - total_months + 1
    while start_m <= 0:
        start_m += 12
        start_y -= 1
    period_start = date(start_y, start_m, 1)

    # ── Check for sufficient data ────────────────────────────────────
    acct_filter = ""
    params = []
    if owner_id:
        from dal.owners import resolve_owner_account_ids
        acct_ids = resolve_owner_account_ids(conn, owner_id)
        if acct_ids:
            placeholders = ", ".join("?" for _ in acct_ids)
            acct_filter = f" AND account_id IN ({placeholders})"
            params.extend(acct_ids)

    row = conn.execute(
        f"""
        SELECT MIN(posting_date) as min_date, MAX(posting_date) as max_date,
               COUNT(*) as cnt
        FROM transactions
        WHERE status = 'posted' AND posting_date IS NOT NULL
          AND transfer_tag IS NULL
          AND posting_date >= ? AND posting_date <= ?
          {acct_filter}
        """,
        [period_start.isoformat(), period_end.isoformat()] + params,
    ).fetchone()

    if not row or not row["min_date"] or row["cnt"] < 10:
        return {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "income_growth_pct": None,
            "categories": [],
            "flagged_count": 0,
            "flag_threshold_pct": flag_threshold_pct,
            "insufficient_data": True,
        }

    # Check actual date span
    actual_min = date.fromisoformat(row["min_date"])
    actual_max = date.fromisoformat(row["max_date"])
    actual_span_months = (actual_max.year - actual_min.year) * 12 + (actual_max.month - actual_min.month)
    if actual_span_months < 23:  # need at least ~24 months
        return {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "income_growth_pct": None,
            "categories": [],
            "flagged_count": 0,
            "flag_threshold_pct": flag_threshold_pct,
            "insufficient_data": True,
        }

    # ── 2. Build rolling 12-month period boundaries ──────────────────
    periods = []  # list of (label, start_date, end_date)
    for p in range(lookback_years):
        p_start_m = start_m + p * 12
        p_start_y = start_y
        while p_start_m > 12:
            p_start_m -= 12
            p_start_y += 1
        p_end_m = p_start_m + 11
        p_end_y = p_start_y
        while p_end_m > 12:
            p_end_m -= 12
            p_end_y += 1

        import calendar
        p_end_day = calendar.monthrange(p_end_y, p_end_m)[1]
        p_start_date = date(p_start_y, p_start_m, 1)
        p_end_date = date(p_end_y, p_end_m, p_end_day)

        label = str(p_end_y) if p_end_m >= 7 else str(p_end_y - 1)
        periods.append({
            "label": label,
            "start": p_start_date.isoformat(),
            "end": p_end_date.isoformat(),
        })

    # ── 3. Query income and spending per period ──────────────────────
    inc_cats = list(_INCOME_CATEGORIES)
    inc_ph = ", ".join("?" for _ in inc_cats)
    excl_cats = list(_EXCLUDED_FROM_CREEP | _INCOME_CATEGORIES)
    excl_ph = ", ".join("?" for _ in excl_cats)

    income_by_period = []
    category_by_period = {}  # {category: [total_per_period]}

    for period in periods:
        # Income total for this period
        irow = conn.execute(
            f"""
            SELECT SUM(signed_amount) as total
            FROM transactions
            WHERE status = 'posted'
              AND posting_date >= ? AND posting_date <= ?
              AND transfer_tag IS NULL
              {acct_filter}
              AND COALESCE(category, 'Other Income') IN ({inc_ph})
            """,
            [period["start"], period["end"]] + params + inc_cats,
        ).fetchone()
        income_by_period.append(round(irow["total"] or 0, 2))

        # Spending by category for this period
        srows = conn.execute(
            f"""
            SELECT COALESCE(category, 'Uncategorized') as cat,
                   SUM(-signed_amount) as total
            FROM transactions
            WHERE status = 'posted'
              AND posting_date >= ? AND posting_date <= ?
              AND transfer_tag IS NULL
              AND signed_amount < 0
              {acct_filter}
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
            GROUP BY cat
            """,
            [period["start"], period["end"]] + params + excl_cats,
        ).fetchall()

        for sr in srows:
            cat = sr["cat"]
            if cat not in category_by_period:
                category_by_period[cat] = [0.0] * len(periods)
            idx = periods.index(period)
            category_by_period[cat][idx] = round(sr["total"] or 0, 2)

    # ── 4. Compute income growth rate ────────────────────────────────
    income_growth_pct = None
    if income_by_period[0] and income_by_period[0] > 0:
        income_growth_pct = round(
            ((income_by_period[-1] / income_by_period[0]) - 1) * 100, 1
        )

    # ── 5. Compute per-category growth and flag ──────────────────────
    categories_out = []
    for cat, totals in category_by_period.items():
        first_total = totals[0]
        last_total = totals[-1]

        # Period totals for output
        period_totals = [
            {"label": periods[i]["label"], "total": round(totals[i], 2)}
            for i in range(len(periods))
        ]

        # Growth rate
        annualized_growth_pct = None
        if first_total and first_total > 0:
            annualized_growth_pct = round(
                ((last_total / first_total) - 1) * 100, 1
            )

        # Trend classification (for >2 periods)
        trend = "steady"
        if len(periods) > 2 and first_total and first_total > 0:
            # Compute growth per consecutive period pair
            period_growths = []
            for i in range(1, len(totals)):
                if totals[i - 1] > 0:
                    g = ((totals[i] / totals[i - 1]) - 1) * 100
                    period_growths.append(g)

            if len(period_growths) >= 2:
                most_recent = period_growths[-1]
                avg_prior = sum(period_growths[:-1]) / len(period_growths[:-1])
                diff = most_recent - avg_prior
                if diff > 3.0:
                    trend = "accelerating"
                elif diff < -3.0:
                    trend = "decelerating"

        # Excess
        excess_pct = None
        if annualized_growth_pct is not None and income_growth_pct is not None:
            excess_pct = round(annualized_growth_pct - income_growth_pct, 1)

        # Flagging: all 4 conditions
        flagged = False
        if (
            annualized_growth_pct is not None
            and income_growth_pct is not None
            and annualized_growth_pct > income_growth_pct + flag_threshold_pct
            and last_total >= _MIN_ANNUAL_SPEND
            and cat not in _EXCLUDED_FROM_CREEP
        ):
            flagged = True

        categories_out.append({
            "category": cat,
            "period_totals": period_totals,
            "annualized_growth_pct": annualized_growth_pct,
            "income_growth_pct": income_growth_pct,
            "excess_pct": excess_pct,
            "flagged": flagged,
            "trend": trend,
        })

    # ── 6. Sort: flagged first (by excess_pct desc), then non-flagged ─
    flagged_cats = sorted(
        [c for c in categories_out if c["flagged"]],
        key=lambda x: x["excess_pct"] or 0,
        reverse=True,
    )
    nonflagged_cats = sorted(
        [c for c in categories_out if not c["flagged"]],
        key=lambda x: x["annualized_growth_pct"] or -999,
        reverse=True,
    )
    categories_out = flagged_cats + nonflagged_cats

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "income_growth_pct": income_growth_pct,
        "categories": categories_out,
        "flagged_count": len(flagged_cats),
        "flag_threshold_pct": flag_threshold_pct,
        "insufficient_data": False,
    }
