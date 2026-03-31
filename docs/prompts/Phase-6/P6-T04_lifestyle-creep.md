# P6-T04: Lifestyle Creep Detection

## Context

You are working on Sentry Finance, a local-first personal finance app.
All transaction data and derived metrics are live.

"Lifestyle creep" is the gradual, often unnoticed increase in spending
that tracks (or exceeds) income growth. A household might earn 5% more
this year and unconsciously spend 12% more on dining and 20% more on
subscriptions, eroding the gains. The user can't see this from the
monthly view alone because each month's delta looks small.

This task detects lifestyle creep by:
1. Computing the **annualized growth rate** of each spending category
   over a configurable lookback window (default: 2 years of rolling
   12-month periods).
2. Computing the **annualized income growth rate** over the same window.
3. **Flagging** categories where spending growth exceeds income growth
   by more than a configurable threshold (default: 5 percentage points).

The results surface in:
- The **Monthly Review page** (P6-T01) — shows current flags
- The **Yearly Wrap-Up page** (P6-T02) — shows YoY summary

## Starting State

- `dal/cash_flow.py` — `get_monthly_cash_flow(conn)` returns per-month
  income and spending totals
- `dal/reports.py` — `get_spending_by_category(conn, start, end)` returns
  category totals for a date range
- `_INCOME_CATEGORIES` set exists in `dal/cash_flow.py` and `dal/reports.py`
- No `dal/lifestyle.py` exists yet
- No `/api/lifestyle/*` endpoints exist

## Task

### 1. Create `dal/lifestyle.py`

```python
"""
dal/lifestyle.py — Lifestyle creep detection.

Compares per-category spending growth rates against income growth rate
to identify categories where spending is outpacing income.
"""

import sqlite3
import logging
from datetime import date, timedelta

log = logging.getLogger("sentry.dal.lifestyle")

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
        "income_growth_pct": float,      # annualized income growth rate
        "categories": [
            {
                "category": str,
                "period_totals": [       # one entry per rolling 12m period
                    {"label": "2024", "total": float},
                    {"label": "2025", "total": float},
                ],
                "annualized_growth_pct": float,
                "income_growth_pct": float,    # same for all rows
                "excess_pct": float,           # growth - income_growth
                "flagged": bool,               # excess_pct > flag_threshold_pct
                "trend": "accelerating" | "steady" | "decelerating",
            }, ...
        ],                               # sorted: flagged first, then by excess_pct desc
        "flagged_count": int,
        "flag_threshold_pct": float,
    }
    """
```

**Algorithm:**

1. Determine the analysis window: `lookback_years` complete 12-month
   periods ending at the last complete calendar month.
   Example with `lookback_years=2`, evaluated in March 2026:
   - Period 1 (baseline): Apr 2024 – Mar 2025
   - Period 2 (current): Apr 2025 – Mar 2026

2. For each period, query income total and per-category spending total
   from `transactions` where `transfer_tag IS NULL`.
   Income = categories IN `_INCOME_CATEGORIES`.
   Spending = categories NOT IN `_INCOME_CATEGORIES` and NOT IN
   `_EXCLUDED_FROM_CREEP`.

3. Compute **annualized growth rate** between the first and last period:
   ```
   growth_pct = ((last_period_total / first_period_total) - 1) * 100
   ```
   If `first_period_total == 0`, set `growth_pct = None` (can't compute).

4. For `lookback_years > 2`, compute trend by comparing growth in the
   most recent period vs. the average of all prior periods:
   - "accelerating" — most recent year's growth > avg of prior years
   - "decelerating" — most recent year's growth < avg of prior years
   - "steady" — within ±3 percentage points of the average

5. Flag a category when ALL are true:
   - `annualized_growth_pct` is not None
   - `annualized_growth_pct > income_growth_pct + flag_threshold_pct`
   - Category's last-period total >= `_MIN_ANNUAL_SPEND`
   - Category is not in `_EXCLUDED_FROM_CREEP`

6. Sort output: flagged categories first (by `excess_pct` descending),
   then non-flagged (by `annualized_growth_pct` descending).

### 2. API Endpoints

Add to `backend/routers/reports.py`:

```python
@router.get("/api/lifestyle/creep")
def lifestyle_creep(
    lookback_years: int = 2,
    flag_threshold_pct: float = 5.0,
):
    """
    Returns lifestyle creep analysis across spending categories.

    Query params:
      lookback_years (int, default 2): Rolling 12-month periods to compare.
      flag_threshold_pct (float, default 5.0): Excess growth % to flag.
    """
    with get_db() as conn:
        return get_lifestyle_creep(
            conn,
            lookback_years=max(2, min(lookback_years, 5)),
            flag_threshold_pct=flag_threshold_pct,
        )
```

### 3. Frontend: Lifestyle Creep Component

Create `frontend/src/components/LifestyleCreepPanel.tsx` — a reusable
panel consumed by both the Monthly Review (P6-T01) and Yearly Wrap-Up
(P6-T02) pages.

**Props:**
```typescript
interface LifestyleCreepPanelProps {
  data: LifestyleCreepResult | null;   // null = loading/unavailable
  compact?: boolean;                   // true = Monthly Review mode (top 3 + count)
                                       // false = full list (Yearly Wrap-Up mode)
}
```

**Compact mode (Monthly Review):**
- Show count of flagged categories: "3 categories outpacing income"
- List top 3 flagged categories with a simple badge: category name +
  `+X.X%` excess growth in red.
- "View full analysis →" link to `/review/yearly`.

**Full mode (Yearly Wrap-Up):**
- Summary line: "Income grew X.X% — [N] spending categories exceeded that"
- Table with columns: Category | [Year 1] | [Year 2] | Growth | vs. Income | Flag
- Flagged rows highlighted with a red left border.
- Non-flagged rows shown in a muted style.
- Empty state if no categories are flagged: "No lifestyle creep detected."
- `lookback_years` selector (2/3 years) that re-fetches with updated param.

## Files to Create

1. `dal/lifestyle.py`
2. `frontend/src/components/LifestyleCreepPanel.tsx`

## Files to Modify

1. `backend/routers/reports.py` — add `/api/lifestyle/creep` endpoint

## Files NOT to Modify

- `dal/cash_flow.py`, `dal/reports.py` — call functions, don't modify
- `frontend/src/pages/MonthlyReviewPage.tsx` — it already handles
  graceful degradation; this task makes the data available
- Any migration files — no schema changes needed

## Constraints

- The function must require **at least 2 complete periods**. With fewer
  than 24 months of transaction history, return a result with
  `{"flagged_count": 0, "categories": [], "income_growth_pct": null,
  "insufficient_data": true}` rather than raising.
- `lookback_years` is capped at 5 on the API side to prevent runaway queries.
- Categories with `first_period_total == 0` (new in the most recent period)
  are **not** flagged — a new subscription isn't lifestyle creep, it's a
  decision point. Include them in output with `annualized_growth_pct: null`
  and `flagged: false`.
- All growth percentages rounded to 1 decimal place.
- The `_EXCLUDED_FROM_CREEP` set must be defined at module level so it
  can be extended without changing the algorithm.

## Done Checklist

- [ ] `dal/lifestyle.py` created with `get_lifestyle_creep()`
- [ ] `_EXCLUDED_FROM_CREEP` set defined at module level
- [ ] Algorithm uses rolling 12-month periods, not calendar years
- [ ] Growth rate computes correctly (last/first - 1) * 100
- [ ] Trend classification (accelerating/steady/decelerating) implemented
- [ ] Flagging logic checks all 4 conditions correctly
- [ ] Insufficient data returns gracefully (no exception)
- [ ] Output sorted: flagged first, then by excess_pct desc
- [ ] `GET /api/lifestyle/creep` endpoint added with param validation
- [ ] `LifestyleCreepPanel.tsx` created with compact and full modes

## Verification

After completion, Claude will:
1. Run `python -c "from dal.lifestyle import get_lifestyle_creep"` — no errors
2. Write pytest tests:
   a. Function returns `insufficient_data: true` with < 24 months of data
   b. Category with growth 20% vs income growth 5% is flagged (excess = 15%)
   c. Category with growth 8% vs income growth 5% is NOT flagged
      (below 5 pt threshold)
   d. Mortgage category is never flagged even if growth > threshold
   e. Category with zero first-period spend is not flagged
   f. Output is sorted flagged-first
3. All tests pass
