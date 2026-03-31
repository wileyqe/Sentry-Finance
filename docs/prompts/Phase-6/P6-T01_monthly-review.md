# P6-T01: Monthly Review Page

## Context

You are working on Sentry Finance, a local-first personal finance app.
The analytical backend (Phases 1–5) is complete. Every individual metric
exists as an API endpoint, but there is no **synthesized** view that
assembles them into a single auto-generated monthly narrative.

The user wants to open one page on the 1st of each month and immediately
see: did last month go well or badly, what changed, and what needs attention.
This replaces the current workflow of manually checking five different pages.

### What the page must answer

1. **Income / Spending / Savings Rate** — how did last month compare to
   the month before and to the trailing 12-month average?
2. **Net Worth Delta** — how much did net worth change and in which direction?
3. **Budget Performance** — which categories were over or under budget?
4. **Subscription Changes** — did any recurring bills change amount or appear/disappear?
5. **Notable Transactions** — the top 5 largest non-recurring expenses.
6. **Uncategorized Count** — how many transactions still need categorization?
7. **Lifestyle Creep Flags** — which categories are growing faster than income?
   _(Depends on P6-T04 data — use `GET /api/lifestyle/creep` from that task.)_
8. **Data Freshness Status** — is any institution's data stale?

## Starting State

All data sources are live API endpoints:
- `GET /api/cash-flow/monthly` — per-month income, spending, net, savings_rate
- `GET /api/reports/summary?start=YYYY-MM-DD&end=YYYY-MM-DD` — period totals
- `GET /api/budgets?month=YYYY-MM` — budget vs actual per category
- `GET /api/recurring` — active recurring transactions
- `GET /api/recurring/{id}/mutations` — amount changes per recurring item
- `GET /api/transactions?start=YYYY-MM-DD&end=YYYY-MM-DD&limit=N` — transactions
- `GET /api/metrics/net-worth-velocity` — MoM net worth change
- `GET /api/freshness` — per-institution staleness
- `GET /api/lifestyle/creep` — (from P6-T04) category growth vs income growth

No `MonthlyReviewPage.tsx` exists yet. No `/api/review/monthly` endpoint exists.

## Task

### 1. Backend: `dal/review.py`

New module. The single function `get_monthly_review()` assembles the full
summary from existing DAL functions — it must NOT duplicate query logic.

```python
"""
dal/review.py — Monthly review assembler.

Calls existing DAL functions and stitches results into a single
structured summary for the monthly review page.
"""

import sqlite3
from datetime import date
import logging

log = logging.getLogger("sentry.dal.review")


def get_monthly_review(conn: sqlite3.Connection, month: str) -> dict:
    """
    Assemble the monthly review for a given YYYY-MM month string.

    Pulls from: cash_flow, reports, budgets, recurring, transactions,
    derived metrics, freshness. Does NOT recompute anything — reads
    from derived_summaries or calls existing DAL functions directly.

    Returns:
    {
        "month": "YYYY-MM",
        "income": {
            "total": float,
            "prior_month": float,
            "trailing_12m_avg": float,
            "mom_change_pct": float,
        },
        "spending": {
            "total": float,
            "prior_month": float,
            "trailing_12m_avg": float,
            "mom_change_pct": float,
        },
        "savings_rate": float,           # pct of income saved this month
        "net_worth_delta": {
            "amount": float,
            "pct": float,
            "direction": "up" | "down" | "flat",
        },
        "budget_highlights": [
            {
                "category": str,
                "budgeted": float,
                "actual": float,
                "variance": float,       # actual - budgeted; positive = over
                "pct_used": float,
            }, ...
        ],                               # top 5 over-budget + top 3 most improved
        "subscription_changes": [
            {
                "merchant": str,
                "change_type": "new" | "removed" | "price_change",
                "old_amount": float | None,
                "new_amount": float | None,
                "delta": float | None,
            }, ...
        ],
        "notable_transactions": [
            {
                "id": str,
                "date": "YYYY-MM-DD",
                "description": str,
                "merchant": str | None,
                "category": str,
                "amount": float,
            }, ...
        ],                               # top 5 largest non-recurring expenses
        "uncategorized_count": int,
        "lifestyle_flags": [             # from dal/lifestyle.py (P6-T04)
            {
                "category": str,
                "category_growth_pct": float,
                "income_growth_pct": float,
                "excess_pct": float,
            }, ...
        ],
        "freshness": [
            {
                "institution": str,
                "status": "fresh" | "stale" | "critical" | "no_data",
                "hours_since_update": float | None,
            }, ...
        ],
    }
    """
```

**Implementation rules:**
- `income` / `spending` / `savings_rate`: call `get_monthly_cash_flow(conn)`
  from `dal/cash_flow.py`, find the target month and the prior month row,
  compute trailing 12m average from the 12 rows ending at the target month.
- `net_worth_delta`: query `derived_summaries` for `metric = 'net_worth_velocity'`
  with `scope = 'global'` and `period = month`; fall back to computing
  MoM delta from two consecutive rows in `get_net_worth_history()`.
- `budget_highlights`: call `get_budget_vs_actual(conn, month)` from
  `dal/budgets.py`. Sort by `variance` descending. Return top 5
  over-budget (variance > 0) + top 3 most-improved (largest negative variance).
- `subscription_changes`: query `recurring_mutations` for mutations where
  `detected_at` falls within the target month. Also check `recurring_transactions`
  for new `first_seen` dates in the month (new subscriptions) and
  `last_seen` dates in the prior month without a match (removed).
- `notable_transactions`: query `transactions` for the target month,
  exclude transfer-tagged rows and income categories, order by
  `ABS(signed_amount) DESC`, limit 5.
- `uncategorized_count`: query transactions for the month where
  `category = 'Uncategorized'` and `transfer_tag IS NULL`.
- `lifestyle_flags`: call `get_lifestyle_creep(conn)` from `dal/lifestyle.py`
  (P6-T04). If that module doesn't exist yet, return `[]` gracefully with
  a log warning rather than raising.
- `freshness`: call `get_institution_freshness(conn)` from `dal/freshness.py`.

### 2. Backend: API Endpoint

Add to `backend/routers/reports.py`:

```python
@router.get("/api/review/monthly")
def monthly_review(month: str | None = None):
    """
    Returns the assembled monthly review for the given month.
    Defaults to the prior calendar month if no month is specified.
    Month format: YYYY-MM.
    """
    if month is None:
        today = date.today()
        first_of_month = today.replace(day=1)
        from dateutil.relativedelta import relativedelta
        prior = first_of_month - relativedelta(months=1)
        month = prior.strftime("%Y-%m")

    with get_db() as conn:
        return get_monthly_review(conn, month)
```

### 3. Frontend: `frontend/src/pages/MonthlyReviewPage.tsx`

New page at route `/review/monthly`.

**Layout (top to bottom):**

1. **Header row**: "Monthly Review — [Month Name Year]" with a `<select>`
   dropdown allowing the user to pick any of the past 24 months. Arrow
   buttons (← →) to navigate months.

2. **KPI strip** (4 cards across):
   - Income: `$X,XXX` with MoM change badge (green/red arrow + %)
   - Spending: `$X,XXX` with MoM change badge
   - Savings Rate: `XX%` with prior-month comparison
   - Net Worth Delta: `+$X,XXX` or `−$X,XXX` with direction arrow

3. **Budget Performance table**: category rows with budgeted/actual/
   variance columns. Over-budget rows highlighted amber/red. Under-budget
   rows highlighted green. Show top 8 categories only (sorted by variance).

4. **Two-column section:**
   - Left: **Subscription Changes** list. Each item shows merchant name,
     change type badge (New / Removed / Price Change), and delta amount.
     Empty state: "No subscription changes this month."
   - Right: **Notable Transactions** list. Each item: date, description,
     amount (formatted). Empty state: "No notable transactions."

5. **Status row** (3 cells across):
   - Uncategorized transactions: count with link to `/transactions?filter=uncategorized`.
   - Lifestyle creep flags: count of flagged categories with a detail
     expansion that shows each flagged category and its growth rate.
   - Data freshness: count of stale/critical institutions with a
     per-institution status list.

**Fetch strategy:** Single call to `GET /api/review/monthly?month=YYYY-MM`.
On month change, re-fetch with the new month param.

**Add nav item** to the sidebar: "Monthly Review" with a calendar icon,
linking to `/review/monthly`.

## Files to Create

1. `dal/review.py`
2. `frontend/src/pages/MonthlyReviewPage.tsx`

## Files to Modify

1. `backend/routers/reports.py` — add `/api/review/monthly` endpoint
2. `frontend/src/App.tsx` — add route `/review/monthly`
3. `frontend/src/components/Sidebar.tsx` (or nav equivalent) — add nav item

## Files NOT to Modify

- `dal/cash_flow.py` — call its functions, don't modify
- `dal/budgets.py` — call its functions, don't modify
- `dal/freshness.py` — call its functions, don't modify
- `dal/lifestyle.py` — call it if available, handle absence gracefully
- Any migration files — no schema changes needed

## Constraints

- `dal/review.py` must NOT execute raw SQL queries for data that already
  has a DAL function. Call the function; only write raw SQL for things
  that have no existing abstraction (e.g., `uncategorized_count`,
  `notable_transactions`, `subscription_changes`).
- The endpoint must default to the **prior** calendar month, not the
  current month (current month data is always incomplete).
- Month navigation on the frontend must not allow future months.
- Lifestyle flags section must render as an empty state if P6-T04 is
  not yet implemented — handle `GET /api/lifestyle/creep` returning 404
  gracefully (catch, log, display empty section).
- All currency values formatted as `$X,XXX.XX` with appropriate sign.
- MoM change badges: green for improvement (income up, spending down),
  red for deterioration (income down, spending up).

## Done Checklist

- [ ] `dal/review.py` created with `get_monthly_review()` assembler
- [ ] All 8 data sections populated via existing DAL functions
- [ ] Graceful fallback when lifestyle module is absent
- [ ] `GET /api/review/monthly` endpoint with prior-month default
- [ ] `MonthlyReviewPage.tsx` with all 5 layout sections
- [ ] Month selector with 24-month history and prev/next arrows
- [ ] Budget table highlights over/under correctly
- [ ] Subscription changes shows new/removed/price-change types
- [ ] Uncategorized count links to filtered transactions page
- [ ] Route and nav item wired

## Verification

After completion, Claude will:
1. Read `dal/review.py` — verify it calls existing DAL functions, not raw SQL
2. Verify the endpoint defaults to prior month
3. Run `python -c "from dal.review import get_monthly_review"` — no import errors
4. Write pytest tests:
   a. `get_monthly_review()` returns all 8 expected top-level keys
   b. `budget_highlights` correctly sorts over-budget categories first
   c. `uncategorized_count` returns 0 for an empty DB, not an error
   d. Missing lifestyle module is handled gracefully (no exception raised)
5. All tests pass
