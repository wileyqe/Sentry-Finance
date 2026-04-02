# P8-T07: Review and Investment Page Polish

## Context

You are working on Sentry Finance, a local-first personal finance app.
A UI audit of the Monthly Review and Investments pages uncovered five
display and data-quality issues that make these pages misleading or
confusing. Three are frontend display bugs, one is a seed data quality
gap, and one is a backend detection logic issue.

**Bug 1 -- Holdings tab shows raw account IDs.**
The Investments page Holdings tab displays internal account IDs like
`vanguard_inv_5501`, `greenleaf_inv_1001`, `vanguard_ret_5502` instead
of human-friendly account names. The `GET /api/accounts` endpoint
already returns account names -- the frontend just needs to
cross-reference them.

**Bug 2 -- Allocation: 36.5% "Unknown" sector.**
Over a third of the investment portfolio shows "Unknown" sector
classification in the allocation breakdown. The root cause is that the
seed script does not populate `sector` for many holdings in the
`investment_holdings` table. The known tickers in the seed data are:
VOO (US Large Cap), VXUS (International), BND (Bonds), IJH (US Mid Cap),
IXUS (International), VMFXX (Money Market), STABLE (Stable Value).

**Bug 3 -- Data freshness shows hours, not human-readable.**
The Monthly Review data freshness section shows "2211h ago" instead of
a human-readable format like "3 months ago" or "92 days". The raw hour
count is meaningless to users at that scale.

**Bug 4 -- Notable transactions empty for December.**
December 2025 has a $45K "Household Settlement" and a $19K "HYSA
Adjustment" but the "Notable Transactions" widget in the Monthly Review
shows empty. The detection threshold or logic in `assemble_monthly_review()`
is failing to flag these large amounts.

**Bug 5 -- Investment performance shows 0% with no context.**
"Your Portfolio: 0.00%" appears next to "S&P 500: +12.80%" giving the
false impression of zero returns. The portfolio performance value is
0.00% because no performance snapshots exist for the selected period,
not because the portfolio actually returned 0%.

## Starting State

- `frontend/src/pages/InvestmentsPage.tsx` -- Holdings tab renders
  `account_id` directly; performance section shows `0.00%` without
  distinguishing missing data from genuine zero return
- `scripts/seed_dummy_data.py` -- investment holdings seeding section
  leaves `sector` null or empty for many tickers
- `frontend/src/pages/MonthlyReviewPage.tsx` -- data freshness section
  displays raw hour count
- `dal/review.py` -- `assemble_monthly_review()` notable transactions
  detection either has a threshold too high or logic that filters out
  the large December entries
- `GET /api/accounts` returns account objects with `account_id` and
  `account_name` fields

## Task

### 1. Map account IDs to names in Holdings tab (Bug 1)

**File:** `frontend/src/pages/InvestmentsPage.tsx`

The Holdings tab displays raw `account_id` values. Fetch accounts data
from `GET /api/accounts` (or use existing account state if the page
already fetches it) and build a lookup map from `account_id` to
`account_name`. Replace the raw ID display with the human-friendly name.

Example mappings (based on seed data):
- `vanguard_inv_5501` -> "Vanguard Brokerage" (or whatever the account
  name is in the accounts table)
- `greenleaf_inv_1001` -> "Greenleaf Investment"
- `vanguard_ret_5502` -> "Vanguard Retirement"

Do not hardcode these names. Use the API response to build the mapping
dynamically so it works with any account data.

### 2. Add sector data to seed holdings (Bug 2)

**File:** `scripts/seed_dummy_data.py`

Find the investment holdings seeding section and assign realistic sector
values based on ticker symbols. Use this mapping:

| Ticker | Sector           |
|--------|------------------|
| VOO    | US Large Cap     |
| VXUS   | International    |
| BND    | Bonds            |
| IJH    | US Mid Cap       |
| IXUS   | International    |
| VMFXX  | Money Market     |
| STABLE | Stable Value     |

Ensure every holding row gets a sector value. If there are holdings with
tickers not in this list, assign a reasonable sector based on the ticker
or default to "Other".

Also update the frontend allocation component in `InvestmentsPage.tsx`
to handle any remaining "Unknown" entries gracefully -- display
"Unclassified" with a muted/subdued visual style instead of "Unknown".

### 3. Convert data freshness to human-readable format (Bug 3)

**File:** `frontend/src/pages/MonthlyReviewPage.tsx`

Replace the raw hour display in the data freshness section with a
human-readable relative time string. Implement conversion logic:

- `hours < 1` -> "Just now"
- `hours < 24` -> "Xh ago"
- `hours < 48` -> "Yesterday"
- `hours < 720` (30 days) -> "X days ago"
- `hours >= 720` -> "X months ago"

Handle edge cases: negative values (treat as "Just now"), zero, very
large values, null/undefined (show "Unknown" or "--").

### 4. Fix notable transactions detection (Bug 4)

**File:** `dal/review.py`

Investigate the notable transactions section of `assemble_monthly_review()`.
December 2025 has transactions of $45K and $19K that should be flagged
as notable but are not appearing.

Possible issues to check:
1. The dollar threshold may be set too high
2. The detection may filter out transactions with certain categories
3. Transfer-tagged transactions may be excluded entirely

Fix the logic so that notable transactions are detected using at least
one of these criteria:
- Any single transaction with an absolute amount exceeding a reasonable
  threshold (e.g., $1,000)
- Any transaction that is unusually large relative to the average for
  that category

Important: transactions with a `transfer_tag` are internal movements
between accounts. These should NOT be flagged as notable spending.
However, if the widget ends up empty because all large transactions
are transfers, consider either:
- Showing a "No notable transactions this month" message instead of
  an empty widget, OR
- Adding a separate "Large transfers" subsection so users are aware
  of significant money movements

### 5. Distinguish missing performance data from 0% return (Bug 5)

**File:** `frontend/src/pages/InvestmentsPage.tsx`

When the portfolio return displays `0.00%`, determine whether this is
a genuine 0% return or a default value due to missing data. Check the
API response for indicators:

- A `has_data` flag or similar field
- Whether the returned data array/object is empty
- Whether the value is exactly `0` with no supporting data points

When the value is determined to be missing (not a real 0% return):
- Display "No data" or "N/A" with a muted style instead of "0.00%"
- Optionally add a tooltip or subtitle: "No performance snapshots
  for this period"

When the value is a genuine 0% return (has supporting data):
- Continue displaying "0.00%" normally

## Files to Modify

1. `frontend/src/pages/InvestmentsPage.tsx` -- holdings account name
   mapping, allocation "Unknown" label, performance empty state
2. `scripts/seed_dummy_data.py` -- add sector values to investment
   holdings
3. `frontend/src/pages/MonthlyReviewPage.tsx` -- human-readable data
   freshness
4. `dal/review.py` -- notable transactions detection threshold/logic

## Files NOT to Modify

- Backend API response shapes -- these are display-layer fixes except
  for the notable transactions logic in `dal/review.py`
- Any migration files -- no schema changes needed
- `dal/database.py` -- no schema changes
- `backend/api_server.py` -- no endpoint changes

## Constraints

- Account name mapping must use the existing `/api/accounts` data, not
  hardcoded name strings. The mapping must work with any account data,
  not just the seed dataset.
- Sector assignments in seed data should be realistic for the given
  tickers. Use the mapping table above.
- The human-readable time conversion must handle edge cases: negative
  hours (treat as "Just now"), zero, null/undefined, and very large
  values (e.g., 50,000 hours should show "X months ago" or "X years
  ago", not overflow).
- Notable transaction detection must not flag transactions that have a
  non-null `transfer_tag` as notable spending. These are internal
  movements, not notable expenses.
- Investment performance display must distinguish between "genuinely
  0% return" (real data exists) and "no data available" (default/missing
  value). Do not hide real 0% returns.
- All money amounts remain stored as integer cents in the database.
  Display formatting uses the existing `formatCurrency` utility.

## Done Checklist

- [ ] Holdings tab shows "Vanguard Brokerage" (or actual account name),
      not `vanguard_inv_5501`
- [ ] Account name mapping is dynamic via `/api/accounts`, not hardcoded
- [ ] Seed data assigns sector to every investment holding based on
      ticker
- [ ] Allocation breakdown shows "Unknown" reduced to < 5% (ideally 0%)
- [ ] Any remaining "Unknown" sectors display as "Unclassified" with
      muted styling
- [ ] Data freshness shows "3 months ago" or "92 days ago", not "2211h
      ago"
- [ ] Freshness conversion handles edge cases (negative, zero, null,
      very large)
- [ ] Notable Transactions for Dec 2025 is either populated or shows a
      meaningful empty state message
- [ ] Transfer-tagged transactions are not flagged as notable spending
- [ ] Investment performance shows "No data" when portfolio has no
      return data, not "0.00%"
- [ ] Genuine 0% returns still display as "0.00%" when data exists
- [ ] Frontend builds cleanly (`cd frontend && npm run build`)
- [ ] All backend tests pass (`pytest tests/ -x --tb=short`)

## Verification

After completion, run:
1. `pytest tests/ -x --tb=short` -- all tests pass (covers the notable
   transactions backend fix in `dal/review.py`)
2. `cd frontend && npm run build` -- clean build, no TypeScript errors
3. Seed dummy data and start servers:
   ```bash
   SENTRY_DB_PATH=data/dummy.db python scripts/seed_dummy_data.py
   SENTRY_DB_PATH=data/dummy.db python backend/api_server.py
   ```
4. Navigate to Investments page, Holdings tab -- account column shows
   "Vanguard Brokerage", "Greenleaf Investment", etc., not raw IDs
5. Investments page, Allocation tab -- "Unknown" sector is eliminated
   or minimal (< 5%); any remaining unclassified entries show
   "Unclassified" with subdued styling
6. Navigate to Monthly Review for any month -- data freshness shows
   "3 months ago" or "X days ago", not "2211h ago"
7. Monthly Review for Dec 2025 -- Notable Transactions section is
   populated with large non-transfer transactions, or shows a clear
   empty state message if all large items are transfers
8. Investments page, Performance section -- shows "No data" or "N/A"
   when portfolio has no performance snapshots, not "0.00%" next to
   a real S&P 500 benchmark figure
