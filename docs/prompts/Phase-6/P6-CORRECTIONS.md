# Phase 6 — Corrections Report

> Generated 2026-03-31 after verification of all 5 Phase 6 tasks.
> Backend logic for all tasks is correct. Three frontend issues found.

---

## Issue 1: LifestyleCreepPanel lookback selector is inert (P6-T04)

**File:** `frontend/src/components/LifestyleCreepPanel.tsx`

**Problem:** The full-mode panel declares `const [lookback, setLookback] = useState(2)`
and renders a `<select>` dropdown that updates this state, but the `lookback`
value is never used. Changing the dropdown has no effect on the displayed data.

**Spec requirement:** (P6-T04 prompt, line 202)
> "`lookback_years` selector (2/3 years) that re-fetches with updated param"

**Fix:** The panel is a reusable component that receives `data` as a prop —
it doesn't own the fetch. The fix has two parts:

1. Add an `onLookbackChange` callback prop:
```tsx
interface LifestyleCreepPanelProps {
  data: LifestyleCreepResult | null;
  compact?: boolean;
  onLookbackChange?: (years: number) => void;  // NEW
}
```

2. Wire the `<select>` onChange to call the callback:
```tsx
onChange={(e) => {
  const val = Number(e.target.value);
  setLookback(val);
  onLookbackChange?.(val);
}}
```

3. In the parent page (`YearlyWrapUpPage.tsx`), handle the callback by
re-fetching `/api/lifestyle/creep?lookback_years=N` and updating state.

---

## Issue 2: InvestmentsPage missing Contributions vs. Performance section (P6-T05)

**File:** `frontend/src/pages/InvestmentsPage.tsx`

**Problem:** The backend endpoint `GET /api/investments/contributions-vs-performance`
is fully implemented and working, but `InvestmentsPage.tsx` has no UI section
that calls it. The page still only has three tabs: Investments, Holdings, and
Allocation.

**Spec requirement:** (P6-T05 prompt, lines 159-180)
> Add a "Contributions vs. Market Growth" section below the existing
> performance chart. Stacked horizontal bar per account.

**Fix:** Add a new section (or a 4th tab) to `InvestmentsPage.tsx`:

1. Add state and fetch:
```tsx
const [cvpYear, setCvpYear] = useState(new Date().getFullYear() - 1);
const [cvpData, setCvpData] = useState<CvpAccount[] | null>(null);

useEffect(() => {
  fetch(`/api/investments/contributions-vs-performance?year=${cvpYear}`)
    .then(r => r.json())
    .then(d => setCvpData(d.accounts))
    .catch(() => setCvpData(null));
}, [cvpYear]);
```

2. Render a stacked horizontal bar per account:
   - Dark teal segment = `performance_gain` (market)
   - Lighter segment = `net_contributions` (deposits)
   - Red segment if `performance_gain < 0`
   - Below each bar: `Start: $X → End: $X | Performance: +X.X%`

3. Add a year `<select>` that updates `cvpYear`.

4. For accounts where `has_sufficient_data === false`, show a muted
   "Insufficient data for [year]" placeholder.

---

## Issue 3: YearlyWrapUpPage missing "Drop File →" link for pending tax docs (P6-T03)

**File:** `frontend/src/pages/YearlyWrapUpPage.tsx`

**Problem:** The tax document checklist panel shows received documents with
their committed_at date, but pending documents only show a "Pending" badge —
no link to the Documents page for uploading.

**Spec requirement:** (P6-T03 prompt, line 213)
> "Pending documents show a 'Drop File →' link that navigates to `/documents`."

**Fix:** In the checklist map (around line 154), add a conditional link
for pending documents:

```tsx
{doc.received ? (
  <span className="text-xs text-zinc-500">
    {new Date(doc.committed_at).toLocaleDateString()}
  </span>
) : (
  <a
    href="/documents"
    className="text-sm text-sky-400 hover:text-sky-300 hover:underline"
  >
    Drop File →
  </a>
)}
```

This replaces the empty space for pending docs with a navigable link.

---

## Execution Order

All three fixes are independent and can be applied in any order.
None require backend changes or new tests (existing tests cover backend logic).
Frontend-only changes — verify with `npx tsc --noEmit` after each fix.
