# P6-T02: Yearly Wrap-Up Page (Preliminary)

## Context

You are working on Sentry Finance, a local-first personal finance app.
The analytical backend is complete and all pages show live data.

Once a year, the user needs a **comprehensive annual review**: a single
page that tells the story of the financial year. This is distinct from
the monthly review — it is a retrospective, not a diagnostic tool.
The page is labeled **"Preliminary"** because the authoritative tax
document figures haven't been reconciled yet (that happens in P6-T03).

### Sections the page must include

1. **Income by Stream** — total for the year per income category
   (Military Pension, VA Benefits, VA Education Benefits, Officiating
   Income, Other Income) with YoY comparison.
2. **Spending by Category** — top categories by total, ranked.
   Bubble sizes or bar widths visualize relative scale.
3. **Net Worth Trajectory** — 12-month line chart anchored to Jan 1.
4. **Interest Paid vs. Earned** — from `compute_interest_cost()`.
5. **Investment Performance** — portfolio return for the year, split
   by account (Fidelity, Acorns, TSP). Uses `dal/performance.py`.
6. **Debt Progress** — for each tracked loan: starting balance,
   ending balance, principal paid, interest paid, months remaining.
7. **Recurring Cost Changes** — subscriptions/bills that changed
   price during the year, new recurring charges, removed ones.
8. **Goals Progress** — each savings goal: target, current, % funded.
9. **Contributions vs. Performance** — (from P6-T05) how much came
   from deposits vs. market growth per investment account.
   If P6-T05 is not yet implemented, render a placeholder section.
10. **Lifestyle Creep Summary** — (from P6-T04) which categories
    grew faster than income YoY. If P6-T04 is not implemented, omit.

The page is labeled **"Preliminary"** prominently until all expected
tax documents are received (P6-T03 upgrades this to "Final").

## Starting State

All data sources exist:
- `dal/cash_flow.py` — `get_cash_flow_yearly(conn)` for annual totals
- `dal/reports.py` — `get_spending_by_category()`, `get_net_worth_history()`
- `dal/derived.py` — `compute_interest_cost(conn)`, `compute_dti_ratio(conn)`
- `dal/performance.py` — `get_portfolio_performance(conn, months)` TWR data
- `dal/debt.py` — `get_debt_summary(conn)`, `get_payoff_plan(conn)`
- `dal/goals.py` — `get_goals_summary(conn)`
- `dal/recurring.py` — `get_recurring_with_payoff(conn)`
- `recurring_mutations` table — tracks amount changes
- `dal/lifestyle.py` — (P6-T04) `get_lifestyle_creep(conn)` if available
- `dal/performance.py` — `decompose_contributions_vs_performance(conn)` (P6-T05) if available

No `YearlyWrapUpPage.tsx` or `/api/review/yearly` endpoint exists.

## Task

### 1. Backend: `dal/yearly_wrapup.py`

New module. `get_yearly_wrapup()` assembles all sections. It must call
existing DAL functions — do NOT re-query data that already has an abstraction.

```python
"""
dal/yearly_wrapup.py — Annual wrap-up assembler.

Calls existing DAL functions to build a comprehensive year-end review.
Labeled 'preliminary' until tax documents are received (P6-T03).
"""

import sqlite3
import logging
from datetime import date

log = logging.getLogger("sentry.dal.yearly_wrapup")

# Income categories to break out by stream
_INCOME_STREAMS = [
    "Military Pension",
    "VA Benefits",
    "VA Education Benefits",
    "Officiating Income",
    "Other Income",
    "Non-Recurring Income",
    "Tax Refund",
]


def get_yearly_wrapup(conn: sqlite3.Connection, year: int) -> dict:
    """
    Assemble the annual wrap-up for the given calendar year.

    Returns:
    {
        "year": int,
        "status": "preliminary",         # always preliminary from this function
        "income_by_stream": [
            {
                "stream": str,
                "total": float,
                "prior_year": float | None,
                "yoy_change_pct": float | None,
            }, ...
        ],
        "total_income": float,
        "total_spending": float,
        "savings_rate": float,
        "spending_by_category": [
            {
                "category": str,
                "total": float,
                "pct_of_spending": float,
                "prior_year": float | None,
                "yoy_change_pct": float | None,
            }, ...
        ],                               # sorted descending by total
        "net_worth_trajectory": [        # Jan–Dec monthly snapshots
            {"month": "YYYY-MM", "net_worth": float}, ...
        ],
        "interest": {
            "total_paid": float,
            "total_earned": float,
            "net_cost": float,
            "by_account": [
                {"account_id": str, "name": str, "interest_paid": float}, ...
            ],
        },
        "investment_performance": [
            {
                "account_id": str,
                "name": str,
                "start_value": float,
                "end_value": float,
                "total_return_pct": float,
                "contributions": float | None,  # from P6-T05 if available
                "performance_gain": float | None,
            }, ...
        ],
        "debt_progress": [
            {
                "account_id": str,
                "name": str,
                "balance_jan1": float,
                "balance_dec31": float,
                "principal_paid": float,
                "months_remaining": int | None,
                "apr": float | None,
            }, ...
        ],
        "recurring_changes": {
            "new": [{"merchant": str, "amount": float, "first_seen": str}],
            "removed": [{"merchant": str, "last_amount": float, "last_seen": str}],
            "price_changes": [
                {
                    "merchant": str,
                    "old_amount": float,
                    "new_amount": float,
                    "delta": float,
                    "annualized_delta": float,
                }
            ],
        },
        "goals_progress": [
            {
                "name": str,
                "target": float,
                "current": float,
                "pct_funded": float,
                "on_track": bool,
            }, ...
        ],
        "contributions_vs_performance": [  # from P6-T05; [] if not available
            {
                "account_id": str,
                "name": str,
                "net_contributions": float,
                "performance_gain": float,
                "total_gain": float,
            }, ...
        ],
        "lifestyle_flags": [             # from P6-T04; [] if not available
            {
                "category": str,
                "category_growth_pct": float,
                "income_growth_pct": float,
                "excess_pct": float,
            }, ...
        ],
    }
    """
```

**Implementation rules per section:**

- **income_by_stream**: query `transactions` for the target year and prior
  year with `category IN (_INCOME_STREAMS)`, grouped by category. Compute
  YoY change. Include `total_income` as sum of all income categories.

- **spending_by_category**: query `transactions` for the year excluding
  income categories and transfer_tag rows. Group by category, sort desc.
  Compute `prior_year` the same way for YoY comparison.

- **net_worth_trajectory**: call `get_net_worth_history(conn, months=24)`,
  filter to rows where `month` starts with the target year.

- **interest**: call `compute_interest_cost(conn)` from `dal/derived.py`.
  This returns YTD figures — use them directly.

- **investment_performance**: query `balance_snapshots` for investment/
  retirement account types at Jan 1 and Dec 31 of the target year
  (use the closest snapshots to those dates). Compute total return %.
  Attempt to call `decompose_contributions_vs_performance(conn, year)`
  from `dal/performance.py` (P6-T05) — if it raises `AttributeError`
  or `ImportError`, set `contributions` and `performance_gain` to `None`.

- **debt_progress**: call `get_debt_summary(conn)` from `dal/debt.py`.
  For `balance_jan1`, query `balance_snapshots` for each loan account
  at the earliest snapshot in the target year (or last snapshot before it).

- **recurring_changes**: query `recurring_mutations` for mutations detected
  within the target year. Query `recurring_transactions` for `first_seen`
  in target year (new) and `last_seen` in prior year with no target-year
  activity (removed). Compute `annualized_delta = delta * 12` for price changes.

- **goals_progress**: call `get_goals_summary(conn)` from `dal/goals.py`.

- **contributions_vs_performance**: attempt to call
  `decompose_contributions_vs_performance(conn, year)` from `dal/performance.py`
  (P6-T05). Return `[]` on any import or attribute error.

- **lifestyle_flags**: attempt to call `get_lifestyle_creep(conn)` from
  `dal/lifestyle.py` (P6-T04). Return `[]` on any import or attribute error.

### 2. Backend: API Endpoint

Add to `backend/routers/reports.py`:

```python
@router.get("/api/review/yearly")
def yearly_wrapup(year: int | None = None):
    """
    Returns the assembled yearly wrap-up for the given year.
    Defaults to the prior calendar year if not specified.
    """
    if year is None:
        year = date.today().year - 1
    with get_db() as conn:
        return get_yearly_wrapup(conn, year)
```

### 3. Frontend: `frontend/src/pages/YearlyWrapUpPage.tsx`

New page at route `/review/yearly`.

**Layout:**

1. **Header**: "Year in Review — [YEAR]" with a "Preliminary" badge
   (amber color, pill shape). Year selector (`<select>` with available
   years from `GET /api/cash-flow/available-years`).

2. **Summary strip** (3 cards):
   - Total Income: `$XXX,XXX` with YoY arrow
   - Total Spending: `$XXX,XXX` with YoY arrow
   - Savings Rate: `XX%` for the year

3. **Income by Stream** — horizontal bar chart. Each stream is a bar
   with its total. Color each stream distinctly. Show YoY change
   as a small badge on each bar.

4. **Spending by Category** — horizontal bar chart, sorted by total
   descending. Top 10 categories visible; "Show more" expands the rest.
   Include YoY change badge per category.

5. **Net Worth Trajectory** — line chart (reuse the existing chart
   component if available), Jan–Dec of the selected year.

6. **Two-column section:**
   - Left: **Interest Paid vs. Earned** — two numbers side-by-side with
     a net cost line. Below: per-account breakdown table.
   - Right: **Investment Performance** — per-account table with start
     value, end value, and return %. If P6-T05 is available, show a
     stacked bar for contributions vs. market gain.

7. **Debt Progress** — table: Loan | Jan Balance | Dec Balance |
   Principal Paid | Months Left | APR. One row per loan.

8. **Three-column section:**
   - **Recurring Changes**: lists for New / Removed / Price Changes.
     Annualized delta shown for price changes.
   - **Goals Progress**: list of goals with progress bars (% funded).
   - **Lifestyle Creep**: flagged categories with growth rate vs income
     growth rate. Empty state if P6-T04 not available.

**Fetch strategy**: Single call to `GET /api/review/yearly?year=YYYY`.
On year change, re-fetch. Show full-page skeleton loader while fetching.

**Add nav item** to sidebar: "Yearly Review" with a trophy/star icon,
linking to `/review/yearly`.

## Files to Create

1. `dal/yearly_wrapup.py`
2. `frontend/src/pages/YearlyWrapUpPage.tsx`

## Files to Modify

1. `backend/routers/reports.py` — add `/api/review/yearly` endpoint
2. `frontend/src/App.tsx` — add route `/review/yearly`
3. `frontend/src/components/Sidebar.tsx` (or nav equivalent) — add nav item

## Files NOT to Modify

- `dal/cash_flow.py`, `dal/reports.py`, `dal/derived.py` — call them, don't change
- `dal/debt.py`, `dal/goals.py`, `dal/recurring.py` — call them, don't change
- `dal/performance.py` — call it; P6-T05 adds to it but don't anticipate that here
- Any migration files

## Constraints

- The `"status": "preliminary"` field must always be returned by this
  function. P6-T03 will extend `get_yearly_wrapup()` to set it to
  `"final"` when all tax documents are present.
- The page must be functional even when P6-T04 and P6-T05 are not yet
  implemented. Both sections must degrade gracefully to empty state.
- `income_by_stream` must include ALL `_INCOME_STREAMS` categories in
  the output, even if a stream had $0 for the year.
- YoY comparisons require data for two consecutive years. If prior-year
  data is absent, set `prior_year: null` and `yoy_change_pct: null`
  rather than omitting the field.
- The "Preliminary" badge must be visually prominent — the user must
  know these numbers may change once tax docs arrive.

## Done Checklist

- [ ] `dal/yearly_wrapup.py` created with `get_yearly_wrapup()` assembler
- [ ] All 10 sections populated (2 with graceful degradation)
- [ ] `GET /api/review/yearly` endpoint with prior-year default
- [ ] `YearlyWrapUpPage.tsx` with all layout sections
- [ ] "Preliminary" badge rendered prominently
- [ ] Year selector using `/api/cash-flow/available-years`
- [ ] Income by stream horizontal bar chart
- [ ] Spending by category bar chart (top 10 + expand)
- [ ] Net worth trajectory line chart
- [ ] Debt progress table
- [ ] Recurring changes (new/removed/price changes)
- [ ] Goals progress bars
- [ ] Route and nav item wired

## Verification

After completion, Claude will:
1. Read `dal/yearly_wrapup.py` — verify it calls existing DAL functions
2. Verify `status: "preliminary"` is always returned
3. Run `python -c "from dal.yearly_wrapup import get_yearly_wrapup"` — no errors
4. Write pytest tests:
   a. All 10 top-level keys present in return value
   b. `income_by_stream` includes all `_INCOME_STREAMS` even with zero data
   c. `status` is always `"preliminary"` from this function
   d. Both P6-T04 and P6-T05 dependencies degrade to `[]` gracefully
5. All tests pass
