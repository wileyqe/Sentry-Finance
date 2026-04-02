# P8-T03: Dashboard Empty State and Date Bugs

## Context

You are working on Sentry Finance, a local-first personal finance app.
An audit of the Dashboard page uncovered four related UX bugs that make
the Dashboard misleading when the current month has no transaction data
(e.g., dummy data ends at Dec 2025 but today is April 2026).

**Bug 1 -- Invalid date `end_date=2026-04-31`.**
The Dashboard constructs `end_date` for the summary API call using
April 31, which does not exist. The frontend date construction for the
current month's end date is wrong. This produces a malformed API request
that may silently return incorrect data or fail depending on the backend
date parser.

**Bug 2 -- Dashboard defaults to empty current month.**
When dummy data ends at Dec 2025 and today is April 2026, all
current-month widgets (monthly net flow, spending comparison, budget)
show $0 with no explanation. The KPI cards for monthly net flow and
savings rate display misleading $0 / 0.0% instead of a muted empty
state that tells the user no data exists yet for the current month.

**Bug 3 -- Recent transactions are all year-end adjustments.**
The 8 most recent transactions returned by `GET /api/transactions?limit=8`
are Dec 31 bookkeeping entries ("Household Settlement", "Year-End HYSA
Adjustment") which are transfers. The recent transactions widget shows
only these transfer-category entries instead of real spending and income
transactions.

**Bug 4 -- Spending comparison uses future `reference_date`.**
The spending comparison API is called with `reference_date=2026-04-10`
when today is April 1. The frontend is calculating a reference date in
the future (appears to hardcode day 10 of the current month). This
produces a pace comparison against a date that has not happened yet.

## Starting State

- `frontend/src/pages/DashboardPage.tsx` -- builds the date parameters
  for the summary, spending comparison, and recent transactions API calls
- `backend/routers/transactions.py` -- serves `GET /api/transactions`
  with `limit` and other query params
- `dal/reports.py:40` -- `_EXCLUDED_FROM_SPEND` set includes "Transfers",
  "Transfer", "Credit Card Payments", etc.
- The summary API returns monthly net flow, savings rate, and totals for
  the requested date range
- The spending comparison API accepts a `reference_date` parameter for
  pace calculation

## Task

### 1. Fix end-of-month date construction

**File:** `frontend/src/pages/DashboardPage.tsx`

The current code constructs `end_date` with a hardcoded or incorrect day
value that produces invalid dates like April 31. Replace the end-of-month
calculation with a correct approach:

```typescript
const endOfMonth = new Date(year, month + 1, 0);
```

This gives the last valid day of any month, including February in leap
years (e.g., April -> April 30, February 2028 -> February 29).

### 2. Add empty state handling for current month

**File:** `frontend/src/pages/DashboardPage.tsx`

When the current month has no transactions, the Dashboard should show a
contextual empty state rather than misleading zeros. After the summary
data loads:

1. Detect when the current month has zero transactions (income and
   spending both zero, or the API returns an empty indicator).
2. Show a muted "No data yet this month" message in the KPI cards for
   monthly net flow and savings rate instead of $0 / 0.0%.
3. The Dashboard should still render normally when the current month does
   have data -- this is only for months with no transactions at all.

### 3. Filter transfers from recent transactions

The recent transactions widget should show real spending and income, not
transfer-category bookkeeping entries. Two possible approaches:

**Option A -- Backend filter (preferred):**
Add an `exclude_transfers` query parameter to
`GET /api/transactions` in `backend/routers/transactions.py`. When
`exclude_transfers=true`, exclude transactions whose category is in the
`_EXCLUDED_FROM_SPEND` set. Update the Dashboard's API call to pass
`exclude_transfers=true`.

**Option B -- Frontend filter:**
Filter transfer-category transactions out of the response in
`DashboardPage.tsx` before rendering the recent transactions list. Use
the same category set as `_EXCLUDED_FROM_SPEND` (define the list in the
frontend or add it to a shared constants module).

Either approach is acceptable. Option A is preferred because the
backend already has the canonical exclusion set and avoids fetching
rows that will be discarded.

### 4. Fix spending comparison `reference_date`

**File:** `frontend/src/pages/DashboardPage.tsx`

Replace the hardcoded or calculated future date with today's actual date:

```typescript
const referenceDate = new Date().toISOString().split("T")[0];
```

The spending comparison pace should always compare against today, not a
future date within the current month.

## Files to Modify

1. `frontend/src/pages/DashboardPage.tsx` -- fix date construction,
   empty state handling, reference_date
2. `backend/routers/transactions.py` -- add `exclude_transfers` query
   param (if using Option A for Bug 3)

## Files NOT to Modify

- `dal/reports.py` -- summary and spending comparison logic is correct
- `dal/cash_flow.py` -- already correct
- Any migration files -- no schema changes
- API response shapes -- keep existing response structures

## Constraints

- Do not change the API response shapes for summary, spending comparison,
  or transactions endpoints.
- The Dashboard must still show current-month data normally when
  transactions exist -- only add empty state for months with zero
  transactions.
- Transfer exclusion for recent transactions must use the same category
  set as `_EXCLUDED_FROM_SPEND` in `dal/reports.py` ("Transfers",
  "Transfer", "Credit Card Payments", "Refunds/Adjustments", "Mortgage",
  "Auto Loan").
- The end-of-month date fix must work for all months including February
  in leap years.
- The `reference_date` fix must use today's actual date, never a future
  date.

## Done Checklist

- [ ] End-of-month date uses `new Date(year, month + 1, 0)` or
      equivalent -- no invalid dates like April 31
- [ ] Summary API call uses valid `end_date` (e.g., `2026-04-30`)
- [ ] KPI cards show muted empty state when current month has no
      transactions instead of misleading $0 / 0.0%
- [ ] Dashboard renders normally when current month has data
- [ ] Recent transactions exclude transfer-category entries
- [ ] Recent transactions show real spending/income transactions
- [ ] Spending comparison `reference_date` is today's date, not a
      future date
- [ ] Frontend builds cleanly (`cd frontend && npm run build`)

## Verification

After completion, run:
1. `cd frontend && npm run build` -- frontend builds with no errors
2. Seed dummy data (ending Dec 2025) and start servers
   (see CLAUDE.md for commands)
3. Navigate to Dashboard -- KPI cards should show a contextual empty
   state message instead of misleading $0 / 0.0%
4. Open browser DevTools Network tab:
   - Summary endpoint `end_date` should be a valid date
     (e.g., `2026-04-30`, not `2026-04-31`)
   - Spending comparison `reference_date` should be today's date
     (e.g., `2026-04-01`), not a future date like `2026-04-10`
   - Transactions request should include `exclude_transfers=true`
     (if using Option A) or the response should be filtered client-side
5. Recent transactions widget should show real spending/income entries,
   not "Household Settlement" or "Year-End HYSA Adjustment" transfers
6. To confirm the fix works with data: temporarily set the system date
   to Dec 2025 or filter to Dec 2025 -- Dashboard should show real
   numbers, not empty state
