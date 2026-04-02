# P8-T08: Logo Fallback and Minor Polish

## Context

You are working on Sentry Finance, a local-first personal finance app.
A UI audit found four minor polish issues across the frontend and one
backend pagination bug. None of these are data correctness issues -- the
underlying numbers and records are correct -- but they degrade usability,
waste network resources, and misrepresent data counts.

**Bug 1 -- TransactionLogo Clearbit lookups on dummy merchants.**
The `TransactionLogo` component treats merchant description strings as
domain names, firing 30+ failed network requests per page load to
`logo.clearbit.com` and `gstatic.com/faviconV2` with nonsense domains
like `brightonhysainterest.com`, `traderjoes567.com`,
`householdsettlement.com`. This creates visual noise in the network tab,
slows page rendering, and will fail for most real transaction
descriptions too. The component needs smarter domain extraction -- only
attempt logo lookup when the merchant name maps to a known domain.

**Bug 2 -- Budget category names truncated on Dashboard.**
The Dashboard budget section shows "ATM/Cash ...", "Cable/Satel...",
"Child/Depe..." because the category names don't fit in the allocated
space. Users cannot tell what category they are looking at without
guessing.

**Bug 3 -- Transactions page total count capped at 1000.**
The pagination text shows "Showing 1-25 of 1000" when the seed data
has 10,052 transactions. The backend query likely caps the total count
with a `LIMIT 1000` or similar constraint. The total count should
reflect all matching transactions so the pagination can calculate the
correct page count.

**Bug 4 -- Cash Flow x-axis labels overlap.**
The monthly Cash Flow chart's x-axis labels are squished and unreadable
when showing 18 months of data. Month labels overlap each other because
the chart does not rotate, abbreviate, or skip labels.

## Starting State

- `frontend/src/components/ui/TransactionLogo.tsx` -- attempts Clearbit
  and Google favicon lookups for every merchant string, regardless of
  whether the string resembles a real domain name
- `frontend/src/pages/DashboardPage.tsx` -- budget summary section
  truncates long category names without providing a tooltip or other
  way to see the full name
- `backend/routers/transactions.py` or `dal/transactions.py` -- the
  transaction listing endpoint returns a total count that appears to be
  capped at 1000
- `frontend/src/pages/CashFlowPage.tsx` -- the recharts `XAxis`
  component renders every month label at full length, causing overlap
  at 18+ data points

## Task

### 1. Fix TransactionLogo to avoid futile network requests

**File:** `frontend/src/components/ui/TransactionLogo.tsx`

The component currently treats every merchant description as a potential
domain name and fires off Clearbit/favicon requests that fail for most
merchants. Fix by:

1. **Default to the letter avatar.** The existing first-letter colored
   circle fallback should be the default rendering path -- no network
   request should fire unless the merchant is in a known-domain map.
2. **Add a known merchant-to-domain map.** Create a small map of common
   merchants to their actual domains, e.g.:

   ```typescript
   const MERCHANT_DOMAINS: Record<string, string> = {
     "amazon": "amazon.com",
     "netflix": "netflix.com",
     "spotify": "spotify.com",
     "trader joe's": "traderjoes.com",
     "walmart": "walmart.com",
     "target": "target.com",
     "costco": "costco.com",
     "starbucks": "starbucks.com",
     // add others as needed
   };
   ```

3. **Lookup logic:** normalize the merchant name to lowercase, check if
   it (or a substring of it) matches a key in the map, and only attempt
   the Clearbit/favicon lookup if a match is found. If no match, render
   the letter avatar immediately with no network request.
4. **Keep the error fallback.** If a matched domain's logo request
   fails (404, network error), fall back to the letter avatar as it
   does today.

This approach means:
- Dummy data merchants like "Brighton HYSA Interest" never trigger a
  network request.
- Real merchants like "Amazon Marketplace" match the "amazon" key and
  get a logo lookup.
- Unknown real merchants gracefully show the letter avatar without
  wasting a request.

### 2. Add tooltips to truncated budget category names

**File:** `frontend/src/pages/DashboardPage.tsx`

In the budget summary section, add a `title` attribute to the element
that renders the category name. This gives users a native browser
tooltip showing the full category name on hover.

```tsx
<span title={category.name} style={{ /* existing truncation styles */ }}>
  {category.name}
</span>
```

If the category name elements already use CSS `text-overflow: ellipsis`,
adding `title` is the only change needed. If not, ensure the element
has `overflow: hidden`, `text-overflow: ellipsis`, and `white-space:
nowrap` so truncation and tooltip work together.

### 3. Fix transaction total count cap

**Files:** `backend/routers/transactions.py` and/or `dal/transactions.py`

The transactions listing endpoint returns a total count that is capped
at 1000. Find the query that calculates the total count and remove or
fix the artificial limit. The total count should reflect all matching
transactions (with the same WHERE clause as the paginated query) so the
frontend can calculate the correct number of pages.

Check for:
- A `LIMIT 1000` on the `COUNT(*)` query
- A Python-side cap like `min(count, 1000)`
- A default `limit` parameter being used for both the data query and
  the count query

The paginated data query should still use `LIMIT` and `OFFSET` for the
current page -- only the count needs to be uncapped.

### 4. Fix Cash Flow x-axis label overlap

**File:** `frontend/src/pages/CashFlowPage.tsx`

The recharts `XAxis` component renders overlapping month labels when
there are 18+ data points. Fix by applying one or more of these
approaches:

1. **Set `interval` prop** -- use `interval="preserveStartEnd"` or
   `interval={1}` to skip alternating labels while always showing the
   first and last.
2. **Abbreviate labels** -- format month labels as 3-letter codes
   ("Jan", "Feb", "Mar") instead of longer formats.
3. **Rotate labels** -- set `angle={-45}` and `textAnchor="end"` on
   the `XAxis` tick to angle labels so they don't overlap.

The recommended combination is abbreviated 3-letter month labels with
`interval="preserveStartEnd"`. This keeps the chart clean at any data
density. If rotation is used, ensure the chart's bottom margin is
increased to accommodate the angled text.

The fix should work for all three Cash Flow views (Monthly, Quarterly,
Yearly) without breaking the layout of views that have fewer data
points.

## Files to Modify

1. `frontend/src/components/ui/TransactionLogo.tsx` -- logo lookup
   strategy with known-domain map and letter avatar default
2. `frontend/src/pages/DashboardPage.tsx` -- budget category tooltip
   via `title` attribute
3. `backend/routers/transactions.py` or `dal/transactions.py` -- remove
   artificial cap on transaction total count
4. `frontend/src/pages/CashFlowPage.tsx` -- x-axis label formatting
   and interval

## Files NOT to Modify

- Any migration or schema files -- no data model changes
- API response shapes -- the transactions endpoint already returns a
  total count field; only fix its value
- `dal/reports.py` -- summary and spending logic is not involved
- Sidebar, routing, or layout components

## Constraints

- The TransactionLogo fix must not break existing logo display for
  merchants that have valid logos. When running with real data, known
  merchants like Amazon and Netflix should still show Clearbit logos.
- The letter avatar fallback should use the first character of the
  merchant name in a colored circle. This likely already exists as the
  error fallback -- the fix is ensuring it is used as the default path
  instead of attempting a network request first.
- The transaction count fix must not cause performance issues. Use
  `COUNT(*)` with the same `WHERE` clause as the paginated query. Do
  not load all rows into memory to count them.
- The Cash Flow x-axis fix should work for all three views (Monthly,
  Quarterly, Yearly) and must not break charts with fewer data points
  (e.g., 3 quarters).
- Budget category tooltips should use the native `title` attribute for
  simplicity -- do not introduce a custom tooltip component for this.

## Done Checklist

- [ ] `TransactionLogo` defaults to letter avatar -- no network request
      fires for unknown merchants
- [ ] Known merchant map exists and matches common merchants (case
      insensitive) to their domains
- [ ] Clearbit/favicon lookup only fires for merchants in the known map
- [ ] Logo error fallback still works (matched merchant whose logo 404s
      gracefully shows letter avatar)
- [ ] Dashboard budget section: hovering over truncated category names
      shows the full name via native tooltip
- [ ] Transactions page: total count reflects actual number of matching
      transactions (e.g., "1-25 of 10052"), not capped at 1000
- [ ] Pagination calculates the correct number of pages based on the
      real total count
- [ ] Cash Flow monthly view with 18+ months: x-axis labels are
      readable and do not overlap
- [ ] Cash Flow quarterly and yearly views still render correctly
- [ ] Frontend builds cleanly (`cd frontend && npm run build`)
- [ ] All backend tests pass (`pytest tests/ -x --tb=short`)

## Verification

After completion, run:

1. `cd frontend && npm run build` -- clean build, no TypeScript errors
2. `pytest tests/ -x --tb=short` -- all backend tests pass (for the
   transaction count fix)
3. Seed dummy data and start dev servers (see CLAUDE.md for commands)
4. **Dashboard page:**
   - Open browser DevTools Network tab -- no requests to
     `logo.clearbit.com` or `gstatic.com/faviconV2` for dummy merchant
     names like "Brighton HYSA Interest" or "Household Settlement"
   - Budget section: hover over a truncated category name (e.g.,
     "ATM/Cash ...") -- full name appears as a tooltip
5. **Transactions page:**
   - Pagination shows the correct total count (e.g., "Showing 1-25 of
     10052 transactions"), not capped at 1000
   - Navigate to the last page -- it should contain the expected number
     of remaining transactions
6. **Cash Flow page (monthly view, 18 months of data):**
   - X-axis labels are readable and not overlapping
   - Switch to Quarterly and Yearly views -- labels still render
     correctly with no layout breakage
