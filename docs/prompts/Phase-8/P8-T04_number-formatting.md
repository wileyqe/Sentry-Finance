# P8-T04: Number and Text Formatting Fixes

## Context

You are working on Sentry Finance, a local-first personal finance app.
A UI audit uncovered four number/text formatting bugs across multiple
pages. All four share a root cause: the frontend has no single shared
currency formatter, so each page applies its own ad-hoc formatting
(or none at all). The fix is to create one canonical `formatCurrency`
utility and replace every inline formatting call with it.

**Bug 1 -- Pagination encoding mojibake.**
On the Transactions page, "Showing 1--25 of 1000" renders as
"1a]--25" because the en-dash character U+2013 is encoded incorrectly.
The source file contains a raw en-dash byte sequence that is
misinterpreted at render time.

**Bug 2 -- Transaction amounts missing comma separators.**
Amounts like `-$19462.04` and `+$13760.85` appear without thousand
separators. They should display as `-$19,462.04` and `+$13,760.85`.
This affects both the Transactions page table and the Dashboard recent
transactions list.

**Bug 3 -- Negative dollar sign placement.**
The Dashboard recurring section shows `$-139`, `$-350` instead of
`-$139`, `-$350`. The negative sign must come before the dollar sign.

**Bug 4 -- Missing trailing zeros.**
Recurring amounts show `$43.5` instead of `$43.50`. Investment
allocation shows `$20,801.2` instead of `$20,801.20`. All currency
values must always display exactly 2 decimal places.

## Starting State

- No shared currency formatting utility exists in `frontend/src/lib/`
- Each page formats amounts inline with varying approaches
- `frontend/src/pages/TransactionsPage.tsx` contains a raw en-dash
  character in the pagination text
- `frontend/src/pages/DashboardPage.tsx` recurring section formats
  negative amounts as `$-X` instead of `-$X`
- `frontend/src/pages/InvestmentsPage.tsx` allocation section drops
  trailing zeros
- Multiple pages display amounts without comma thousand separators

## Task

### 1. Create shared currency formatter

**File:** `frontend/src/lib/formatCurrency.ts` (new file)

Create a single utility function:

```typescript
/**
 * Format a number as a USD currency string.
 *
 * - Sign before dollar sign: -$1,234.56
 * - Always 2 decimal places: $43.50, not $43.5
 * - Comma thousand separators: $1,234.56, not $1234.56
 * - Handles zero, positive, negative, null, undefined
 */
export function formatCurrency(amount: number | null | undefined): string {
  if (amount == null || isNaN(amount)) return "$0.00";

  const abs = Math.abs(amount);
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  if (amount < 0) return `-$${formatted}`;
  return `$${formatted}`;
}
```

Adjust the implementation as needed, but preserve these guarantees:
- `formatCurrency(-19462.04)` returns `"-$19,462.04"`
- `formatCurrency(13760.85)` returns `"$13,760.85"`
- `formatCurrency(-139)` returns `"-$139.00"`
- `formatCurrency(43.5)` returns `"$43.50"`
- `formatCurrency(20801.2)` returns `"$20,801.20"`
- `formatCurrency(0)` returns `"$0.00"`
- `formatCurrency(null)` returns `"$0.00"`
- `formatCurrency(undefined)` returns `"$0.00"`

### 2. Fix pagination encoding (Bug 1)

**File:** `frontend/src/pages/TransactionsPage.tsx`

Find the pagination text that contains the en-dash character (U+2013)
causing mojibake. Replace it with a simple ASCII hyphen `-` or use
a JSX entity `&ndash;` that renders correctly regardless of file
encoding. A plain hyphen is the safest fix.

### 3. Replace all inline currency formatting

**Files:** All frontend pages and components that display dollar amounts.

Search the frontend codebase for patterns like:
- `$${...}` template literals used for dollar formatting
- `.toFixed(2)` calls on amounts
- `toLocaleString` calls on amounts
- Hardcoded `$` prefixing a number variable

Replace each occurrence with a call to `formatCurrency()`. Import the
function from `@/lib/formatCurrency` (or the project's path alias).

Pay particular attention to:

- **DashboardPage.tsx** -- recurring section (`$-139` bug), recent
  transactions list (missing commas)
- **TransactionsPage.tsx** -- transaction table amount column (missing
  commas)
- **InvestmentsPage.tsx** -- allocation section (missing trailing zeros)
- **MonthlyReviewPage.tsx** -- any amount displays
- **YearlyWrapUpPage.tsx** -- any amount displays
- **CashFlowPage.tsx** -- any amount displays
- **ReportsPage.tsx** -- any amount displays
- **BudgetsPage.tsx** -- any amount displays
- **AccountsPage.tsx** -- any amount displays

Do a project-wide search to ensure no dollar-formatted amounts are
missed. Some components in `frontend/src/components/` may also have
inline formatting.

## Files to Create

1. `frontend/src/lib/formatCurrency.ts` -- shared currency formatter

## Files to Modify

1. `frontend/src/pages/TransactionsPage.tsx` -- fix encoding, use
   shared formatter
2. `frontend/src/pages/DashboardPage.tsx` -- use shared formatter
   (recurring section, recent transactions)
3. `frontend/src/pages/InvestmentsPage.tsx` -- use shared formatter
   (allocation section)
4. `frontend/src/pages/MonthlyReviewPage.tsx` -- use shared formatter
5. `frontend/src/pages/YearlyWrapUpPage.tsx` -- use shared formatter
6. `frontend/src/pages/CashFlowPage.tsx` -- use shared formatter
   (if applicable)
7. `frontend/src/pages/ReportsPage.tsx` -- use shared formatter
   (if applicable)
8. `frontend/src/pages/BudgetsPage.tsx` -- use shared formatter
   (if applicable)
9. `frontend/src/pages/AccountsPage.tsx` -- use shared formatter
   (if applicable)
10. Any components in `frontend/src/components/` that format dollar
    amounts inline

## Files NOT to Modify

- Backend files -- this is purely a frontend display issue
- Any DAL, migration, or database files
- API response types -- format at the display layer only

## Constraints

- The `formatCurrency` function must handle edge cases: `0`, negative
  numbers, very large numbers, `null`, and `undefined`. Never return
  `NaN` or crash on bad input.
- Do not change the data type of amounts in API responses. All
  formatting happens at the display layer in React components.
- The en-dash fix must not introduce other character encoding
  regressions. If the source file has other non-ASCII characters,
  verify they still render correctly.
- Use a single canonical import path for `formatCurrency` across all
  files. Do not duplicate the function.
- Preserve any existing sign indicators used in the UI (e.g., if some
  pages show `+$X` for positive amounts, keep that behavior using
  `formatCurrency` output with a `+` prefix).
- Do not change how the backend stores or transmits amounts (integer
  cents in the database, decimal numbers in API responses).

## Done Checklist

- [ ] `formatCurrency.ts` exists in `frontend/src/lib/` with correct
      behavior for negative, positive, zero, null, and undefined inputs
- [ ] Pagination on Transactions page shows "1-25" or "1&ndash;25"
      (no mojibake)
- [ ] Transaction amounts display with comma separators on both the
      Transactions page and Dashboard recent transactions
- [ ] Dashboard recurring section shows `-$139.00` not `$-139`
- [ ] All currency values show exactly 2 decimal places (no `$43.5`
      or `$20,801.2`)
- [ ] Investment allocation amounts show trailing zeros
- [ ] No remaining inline `$${...}` currency formatting patterns in
      page files (project-wide grep confirms)
- [ ] `cd frontend && npm run build` succeeds with no TypeScript errors
- [ ] No other character encoding regressions introduced

## Verification

After completion, run:
1. `cd frontend && npm run build` -- clean build, no TypeScript errors
2. Project-wide search for remaining inline currency formatting:
   `grep -rn '\$\${' frontend/src/pages/` -- should return zero hits
   for dollar-amount formatting (template literals for other purposes
   are fine)
3. Start the dev server and visually verify:
   - Transactions page: amounts show as `-$19,462.04` with commas,
     pagination shows "1-25" with no mojibake
   - Dashboard: recurring section shows `-$139.00` not `$-139`,
     recent transactions have comma separators
   - Investments page: allocation amounts show `$20,801.20` not
     `$20,801.2`
   - Monthly Review: all currency values have 2 decimal places
   - Yearly Wrap-Up: all currency values have 2 decimal places
4. Spot-check that `$0.00` renders correctly where amounts are zero
