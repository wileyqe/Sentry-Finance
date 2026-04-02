# P8-T06: Chart Rendering and Empty State Fixes

## Context

You are working on Sentry Finance, a local-first personal finance app.
A UI audit uncovered five chart rendering and empty state issues across
the Dashboard, Reports, and Accounts pages. These bugs produce duplicate
data labels, console errors, misleading chart visuals, and unlabeled
controls.

**Bug 1 -- Credit scores show duplicate bureau entries.**
The Dashboard credit score KPI shows two "TRANSUNION FICO" entries (720
and 776) from different institutions (coastal=NFCU, summit=Chase). The
UI displays the bureau name alone, so users see the same label twice
with no way to distinguish which score belongs to which institution. The
API response at `/api/metrics/credit-scores` already returns
`institution_id` for each score. The frontend should display the
institution label alongside or instead of the bureau name when there are
multiple scores from the same bureau (e.g., "NFCU FICO 720 | Chase FICO
776").

**Bug 2 -- Reports Sankey NaN console errors.**
When the Reports page loads with "Last 3 Months" selected (which has no
data in the dummy dataset), 8 console errors fire: `Received NaN for
the 'y'/'height' attribute`. The custom Sankey SVG component does not
guard against empty or zero data, causing it to compute NaN dimensions
when income and spending are both zero.

**Bug 3 -- Net worth chart flat line for 5 months.**
The Accounts page net worth chart shows a flat line from Dec 2025 to
Apr 2026 because balance snapshots only exist through Dec 2025 and the
system carries forward the last known balances. While the data is
technically correct, the chart is visually misleading -- users cannot
tell that the flat segment represents stale carried-forward data rather
than real account snapshots.

**Bug 4 -- Reports filter dropdowns unlabeled.**
Two "ALL" dropdown selectors on the Reports page have no labels. Users
cannot tell what each dropdown filters (category? account? owner?).

**Bug 5 -- Reports Sankey blank gray box with no data.**
When "Last 3 Months" is selected and there is no data, the Sankey chart
area renders as a blank gray rectangle. It should show an explicit empty
state message matching the pattern used elsewhere in the app (e.g., the
"No performance data for this period" message on the Investments page).

## Starting State

- `frontend/src/pages/DashboardPage.tsx` -- credit score KPI section
  displays bureau name only, does not use `institution_id` from the
  `/api/metrics/credit-scores` API response
- `frontend/src/pages/ReportsPage.tsx` -- contains the custom Sankey
  SVG component, filter dropdowns, and chart rendering logic
- `frontend/src/pages/AccountsPage.tsx` -- net worth chart rendering
  with carried-forward balance data
- `frontend/src/pages/InvestmentsPage.tsx` -- reference for empty state
  pattern ("No performance data for this period")
- `/api/metrics/credit-scores` returns `institution_id`, `bureau`,
  `score_type`, and `score` for each entry

## Task

### 1. Differentiate credit scores by institution

**File:** `frontend/src/pages/DashboardPage.tsx`

Update the credit score KPI section to display the institution name
alongside the bureau and score. When the API returns multiple scores
from the same bureau (e.g., two TRANSUNION FICO entries), the UI must
differentiate them by institution. Display format should be something
like "NFCU FICO 720" and "Chase FICO 776" -- use the institution name
or a readable label derived from `institution_id` as the primary
differentiator.

The display must work correctly for:
- 1 score (show bureau + score as today)
- 2 scores from different bureaus (show bureau + score for each)
- 2+ scores from the same bureau but different institutions (show
  institution + bureau + score)
- N scores in any combination

### 2. Guard Sankey SVG against empty data

**File:** `frontend/src/pages/ReportsPage.tsx`

Add a guard before the Sankey SVG rendering that checks whether the
flow data has zero income and zero spending. When data is empty:

1. Skip the SVG rendering entirely -- do not pass zero values into
   the SVG dimension calculations.
2. Render an empty state message instead (see Bug 5 below).

This must eliminate all NaN-related console errors when the selected
period has no data. No `NaN` warnings or errors should appear in the
browser console.

### 3. Add net worth chart data freshness annotation

**File:** `frontend/src/pages/AccountsPage.tsx`

Add a small annotation near the net worth chart that indicates when the
last real balance snapshot was recorded. This is the lightweight fix:
display a label like "Last snapshot: Dec 2025" or "Data through Dec
2025" so users understand that months beyond that point are
carried-forward estimates, not real data.

Do not alter the chart data itself or change how carried-forward
balances work. This is a display-only annotation.

### 4. Add labels to Reports filter dropdowns

**File:** `frontend/src/pages/ReportsPage.tsx`

Add visible labels to the two filter dropdowns on the Reports page.
The labels should clearly indicate what each dropdown filters, e.g.,
"Category" and "Account". Use either:
- A label element above the dropdown, or
- Placeholder text inside the dropdown (in addition to "ALL" as the
  default option)

Follow the labeling pattern used by other filter controls in the app.

### 5. Add Sankey empty state message

**File:** `frontend/src/pages/ReportsPage.tsx`

When the Sankey chart has no data to render, display an explicit empty
state message instead of a blank gray rectangle. The empty state should:

1. Match the styling pattern from the Investments page (reference
   `InvestmentsPage.tsx` for the "No performance data for this period"
   implementation).
2. Display a message like "No data for this period".
3. Be centered within the chart area.
4. Optionally include a muted icon consistent with other empty states.

## Files to Modify

1. `frontend/src/pages/DashboardPage.tsx` -- credit score display with
   institution differentiation
2. `frontend/src/pages/ReportsPage.tsx` -- Sankey NaN guard, empty
   state message, dropdown labels
3. `frontend/src/pages/AccountsPage.tsx` -- net worth chart data
   freshness annotation

## Files NOT to Modify

- Any backend files -- do not change API responses
- Any migration files -- no schema changes
- `frontend/src/pages/InvestmentsPage.tsx` -- read only as a reference
  for empty state patterns

## Constraints

- Do not change any backend API responses. All fixes are frontend-only.
- The Sankey NaN fix must prevent console errors entirely -- zero
  warnings or errors in the browser console when data is empty.
- Credit score display changes must work with 1, 2, or N scores from
  the API in any combination of bureaus and institutions.
- Empty state styling must match existing empty state patterns in the
  app (check `InvestmentsPage.tsx` for reference).
- Net worth chart annotation must not alter the actual chart data or
  change how carried-forward balances are computed -- display only.
- Dropdown labels must be visible without user interaction (not just
  tooltip or hover text).

## Done Checklist

- [ ] Credit score KPI shows institution names alongside bureau names
      when multiple scores exist from the same bureau
- [ ] Credit score display works correctly with 1, 2, or N scores
- [ ] Sankey SVG does not render when data is empty -- no NaN console
      errors
- [ ] Sankey empty state shows "No data for this period" message
      instead of blank gray box
- [ ] Empty state styling matches the Investments page pattern
- [ ] Reports filter dropdowns have visible "Category" and "Account"
      labels
- [ ] Net worth chart has a data freshness annotation (e.g., "Last
      snapshot: Dec 2025")
- [ ] Net worth chart data and carried-forward logic are unchanged
- [ ] Frontend builds cleanly (`cd frontend && npm run build`)

## Verification

After completion, run:
1. `cd frontend && npm run build` -- frontend builds with no errors
2. Seed dummy data and start servers (see CLAUDE.md for commands)
3. Navigate to Dashboard -- credit scores should show institution
   names, not duplicate "TRANSUNION FICO" entries
4. Navigate to Reports page, select "Last 3 Months":
   - Open browser DevTools Console -- no NaN errors
   - Sankey area shows "No data for this period" message, not a blank
     gray rectangle
5. Navigate to Reports page, select "All Time":
   - Sankey renders normally with income and spending flows
   - Filter dropdowns have visible labels ("Category", "Account")
6. Navigate to Accounts page:
   - Net worth chart has a freshness annotation (e.g., "Data through
     Dec 2025")
   - Chart data and shape are unchanged
