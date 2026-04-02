# P8-T05: Header Label and Truncation Fixes

## Context

You are working on Sentry Finance, a local-first personal finance app.
A UI audit found four label/truncation issues across the frontend that
hurt readability and polish. None of these are data bugs -- the numbers
are correct, but they are clipped or mislabeled in the rendered UI.

**Bug 1 -- KPI cards truncated on Review pages.**
The Monthly Review page shows values like `$15,19...`, `$33,86...`,
`-3936.` because the KPI summary cards don't have enough horizontal
space. The 4-card row (INCOME, SPENDING, SAVINGS RATE, NET WORTH CHANGE)
clips the formatted values. The Yearly Wrap-Up page has the same card
layout and the same truncation risk.

**Bug 2 -- Header breadcrumb inconsistencies.**
Three page headers show incorrect or inconsistent labels:

- Cash Flow page header says "Cash-flow" (hyphenated) -- sidebar says
  "Cash Flow" (two words).
- Monthly Review header says "Review/monthly" -- should say
  "Monthly Review".
- Yearly Review header says "Review/yearly" -- should say
  "Yearly Wrap-Up".

The header component likely derives the page title from the URL path
instead of receiving an explicit display title from each page.

**Bug 3 -- Settings Refresh Policy table truncated.**
The rightmost column of the Refresh Policy table (containing "Reset"
buttons) is clipped by the viewport boundary. The table doesn't scroll
and the column is too narrow to display the buttons.

**Bug 4 -- Institution name casing.**
Settings Refresh Policy shows "Nfcu" instead of "NFCU". Institution
names should respect proper casing (NFCU, AMEX, etc.) or use a display
name mapping.

## Starting State

- `frontend/src/pages/MonthlyReviewPage.tsx` -- renders 4 KPI summary
  cards in a row; values truncate when they exceed the card width
- `frontend/src/pages/YearlyWrapUpPage.tsx` -- same KPI card layout,
  same truncation risk
- `frontend/src/components/layout/Header.tsx` -- renders the page
  header / breadcrumb; may derive the title from the URL path
- `frontend/src/pages/CashFlowPage.tsx` -- does not supply an explicit
  page title, so the header falls back to the route path
- `frontend/src/pages/SettingsPage.tsx` -- Refresh Policy table layout
  clips the Reset button column; institution names are title-cased
  instead of preserving acronym casing

## Task

### 1. Fix KPI card value truncation

**Files:** `frontend/src/pages/MonthlyReviewPage.tsx`,
`frontend/src/pages/YearlyWrapUpPage.tsx`

The 4-card KPI row clips large dollar amounts. Fix using one or both of
these approaches (preferred order):

1. **Auto-abbreviate large values** -- format amounts over $10K as
   abbreviated strings (e.g., `$15.2K`, `$207.4K`). Create or use a
   shared formatter so abbreviation is consistent across all pages.
2. **Responsive font size** -- if abbreviation alone isn't enough, add
   a smaller font size or CSS `clamp()` for the value text so longer
   strings shrink to fit.

Whichever approach is chosen, apply it consistently to both the Monthly
Review and Yearly Wrap-Up pages. Savings rate (a percentage) and net
worth change (a dollar amount) should both be fully visible.

### 2. Fix header breadcrumb labels

**Files:** `frontend/src/components/layout/Header.tsx` and/or the
individual page components (`CashFlowPage.tsx`,
`MonthlyReviewPage.tsx`, `YearlyWrapUpPage.tsx`)

Ensure each page supplies a proper display title to the header
component rather than having the header derive it from the URL path.
The correct display titles are:

| Route               | Display Title    |
|----------------------|------------------|
| `/cash-flow`         | Cash Flow        |
| `/review/monthly`    | Monthly Review   |
| `/review/yearly`     | Yearly Wrap-Up   |

Implementation options:

- Add a `pageTitle` prop or context value that each page sets
- Add a route-to-title map in the header component
- Have each page component set a document title or layout prop

The sidebar navigation labels should already be correct -- this fix
only affects the header breadcrumb.

### 3. Fix Settings Refresh Policy table layout

**File:** `frontend/src/pages/SettingsPage.tsx`

The Reset button column is clipped by the viewport boundary. Fix by:

- Wrapping the table in a horizontally scrollable container
  (`overflow-x: auto`), OR
- Making the table columns responsive so all columns fit within the
  desktop viewport width, OR
- Reducing padding / column widths so the Reset column is visible

The table must remain fully functional at standard desktop viewport
widths (1280px+).

### 4. Fix institution name casing

**File:** `frontend/src/pages/SettingsPage.tsx`

Institution names like "Nfcu" should display as "NFCU". Fix by:

- Creating an institution display name map (e.g.,
  `{ nfcu: "NFCU", amex: "AMEX", usaa: "USAA" }`) and looking up
  the raw name, OR
- Reading a `display_name` field from the institutions/accounts API
  if one exists, OR
- Applying `.toUpperCase()` for known acronym-based institutions

Prefer a centralized mapping so the display names can be reused if
other pages show institution names. If a name isn't in the map, fall
back to the raw value (don't crash or show undefined).

## Files to Modify

1. `frontend/src/pages/MonthlyReviewPage.tsx` -- KPI card sizing +
   page title
2. `frontend/src/pages/YearlyWrapUpPage.tsx` -- KPI card sizing +
   page title
3. `frontend/src/components/layout/Header.tsx` -- breadcrumb title
   logic
4. `frontend/src/pages/CashFlowPage.tsx` -- provide correct page title
5. `frontend/src/pages/SettingsPage.tsx` -- table layout + institution
   casing

## Files NOT to Modify

- Backend API files -- no data changes needed
- Router / route definitions -- do not change URL paths
- Sidebar navigation -- labels are already correct there
- Any DAL or migration files -- no schema changes

## Constraints

- Do not change the page routes -- only the display labels.
- KPI abbreviation must be consistent across all pages. If one page
  abbreviates `$15.2K`, all pages with KPI cards must use the same
  formatter.
- Institution display names should come from a centralized source
  (a shared map or utility) if possible, not inline conditionals.
- The Settings table must remain fully functional on desktop viewport
  sizes (1280px+). Don't break the layout to fix the truncation.
- Do not remove or rename any existing components or props that other
  parts of the app depend on.

## Done Checklist

- [ ] Monthly Review for Dec 2025: all 4 KPI values are fully visible
      (no `...` truncation)
- [ ] Yearly Wrap-Up: KPI values are fully visible with the same
      formatting as Monthly Review
- [ ] KPI abbreviation formatter is shared (not duplicated per page)
- [ ] Cash Flow page header shows "Cash Flow" not "Cash-flow"
- [ ] Monthly Review page header shows "Monthly Review" not
      "Review/monthly"
- [ ] Yearly Wrap-Up page header shows "Yearly Wrap-Up" not
      "Review/yearly"
- [ ] Settings page: Refresh Policy table Reset buttons are fully
      visible without clipping
- [ ] Settings page: institution names show "NFCU" not "Nfcu"
- [ ] Institution display name map is centralized and reusable
- [ ] No build errors (`cd frontend && npm run build`)

## Verification

After completion, run:

1. `cd frontend && npm run build` -- clean build, no errors
2. Start the dev servers and visually verify:
   - Monthly Review for Dec 2025: all 4 KPI values fully visible
     (no truncation or ellipsis)
   - Yearly Wrap-Up: same KPI formatting, no truncation
   - Cash Flow page header reads "Cash Flow" (not "Cash-flow")
   - Monthly Review header reads "Monthly Review" (not "Review/monthly")
   - Yearly Wrap-Up header reads "Yearly Wrap-Up" (not "Review/yearly")
   - Settings page Refresh Policy table: "NFCU" not "Nfcu", Reset
     buttons fully visible without horizontal clipping
3. Resize browser to 1280px width -- Settings table must still be
   functional with all columns visible or scrollable
