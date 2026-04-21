# P14-T02b: Payroll withholdings visible on the Sankey (cosmetic follow-up)

## Context

Phase B shipped three terminal buckets on the Sankey's right edge
(`CONSUMED` / `STORED_LIQUID` / `STORED_ILLIQUID`) and the gross
paycheck on the left, but the **withholdings** that live between
them are invisible on the SVG itself — they only show up in the
amber `PayrollDecompositionDebugPanel` table below the chart.

The approved Phase B mockup at
`~/.claude/plans/phase14-phase-b-sankey-mockup.html` draws each
withholding (Federal Tax, State Tax, SBP Premium, Dental/Vision)
as a **color-coded ribbon** peeling off the gross-military-pay
bar and flying straight into the `CONSUMED` bucket, bypassing the
cash hub. The current SVG still routes all income into the hub as
a single gross trunk, so a reader can't tell at a glance how much
of each paycheck was taxed away before cash ever reached the hub.

P14-T02 closed with this gap documented under **Follow-ups →
"P14-T02-followup (cosmetic Sankey rework)"**. This prompt tracks
closing it.

## Starting State

- `/api/reports/flow` already returns the data needed:
  - `payroll_decomposition.payroll_rows[].withholdings[]` — list of
    `{kind, cents, bucket}` per snapshot (Phase A).
  - `bucket_totals.CONSUMED` already includes withholdings (Phase B).
- `frontend/src/pages/ReportsPage.tsx::SankeyChart` is a 4-column
  custom SVG (source | hub | mid | buckets) with:
  - Income → hub ribbons sized against `hubInflow = totalIncome`
    (gross).
  - Hub → mid (spending cats, mortgage, illiquid transfers)
    → buckets.
  - Hub → `STORED_LIQUID` bulk residual (direct edge).
  - Bypass synthetic sources (employer match) → `STORED_ILLIQUID`
    (direct pseudo-flows with dashed stroke).
- `_WITHHOLDING_LABEL` / `_WITHHOLDING_COLOR` maps already exist
  for the debug panel (underscore-prefixed because nothing outside
  that panel used them yet).
- No dedicated SankeyChart unit tests — verification is the frontend
  build + visual inspection via the dev server.

Accounting invariant already enforced by `_compute_bucket_totals`:
`STORED_LIQUID = total_inflow - CONSUMED - STORED_ILLIQUID`, so
re-routing withholdings on the visual layer changes nothing
dollar-side.

## Task

1. **Promote the withholding maps** — rename `_WITHHOLDING_LABEL`
   / `_WITHHOLDING_COLOR` to drop the underscore so `SankeyChart`
   can reuse them alongside `PayrollDecompositionDebugPanel`.

2. **Aggregate withholdings by kind** in the `sankeyData` memo.
   Walk `flowData.payroll_decomposition.payroll_rows[].withholdings[]`,
   sum cents per `kind` where `bucket === "CONSUMED"`, drop zero-
   valued kinds, sort desc. Expose as a new `withholdings:
   WithholdingAgg[]` field (typed shape: `{kind, label, color,
   value}` — value in dollars).

3. **Thread the prop into `SankeyChart`.** New prop
   `withholdings: WithholdingAgg[]`. Empty array → renders
   identically to today (no regression for Amy's empty view, or
   any window without matched payroll).

4. **Pick the primary paycheck bar.** Largest income bar whose
   `value >= totalWithheld`. That bar absorbs all withholding
   ribbons. If no income bar can hold them (edge case: withholding
   data without a matching income category), draw nothing — the
   debug panel still shows the breakdown.

5. **Shrink hub inflow to net.** `hubInflow = max(0, totalIncome
   - totalWithheld)`. This means the primary bar's income→hub
   ribbon must start BELOW the withheld stripes (source `sy`
   advances past `primaryWithheldBottomY`), and its hub
   destination height is sized against the new (smaller)
   `hubInflow`. Non-primary bars unchanged.

6. **Build `withholdingLinks`.** For each withholding kind, draw
   a direct ribbon from the primary bar's right edge (at a slice
   proportional to `w.value / primary.value`) to the CONSUMED
   bucket's left edge (at a slice proportional to `w.value /
   totalInflow`). Stack them FIRST into the bucket so they sit
   at the top of `CONSUMED` (above mortgage interest/escrow and
   spending categories). Color = kind color, stroke solid
   (real flows, not pseudo).

7. **Paint internal stripes on the primary income bar** using the
   same kind colors at 0.80 opacity. This gives the "gross =
   withheld + net" visual hint the mockup uses.

8. **Preserve hover/click semantics.** Withholding ribbons get
   names like `"Federal Tax · withheld"` and a `side: "withhold"`
   tag. `<title>` tooltips, dimming, and opacity transitions
   follow the same pattern as bypass flows.

## Verification

- **Frontend build:** `cd frontend && npm run build` succeeds.
- **Manual eyeball** (dev server):
  - Quintin view on "Last 3 Months": gross Mil bar sprouts four
    thin colored ribbons (fed/state/SBP/dental) flying directly
    into the top of the red `Spent` bucket. Hub bar is visibly
    shorter than before (net, not gross).
  - Amy view: her W-2 bar behaves the same way (smaller
    withholdings, stripes still visible).
  - Household view: both paychecks' withholdings are aggregated
    and drawn off whichever bar is largest (usually Quintin's
    gross Mil).
  - Hover a withholding ribbon → `<title>` shows the kind + amount.
  - `CONSUMED` bucket still visually full — sum of
    (withholding ribbons + spend cats + mortgage interest/escrow
    ribbons) lands cleanly on its left edge, no daylight gap.
- **No regressions:** time window with no payroll rows
  (historical backfill gap) renders identically to today; income
  bars that can't absorb the withholdings (defensive fallback)
  skip the rework cleanly.
- **Accounting:** `bucket_invariant_drift_cents` stays at 0 — no
  server changes, just visual routing.

## Known Issues / Follow-ups

- Per-ribbon floating labels are intentionally omitted — the
  debug panel's withholding table is the authoritative breakdown.
  If users want inline labels, add them later (scope creep risk).
- Withholding attribution uses `max(value)` primary-bar heuristic.
  For a single-earner household this is exact; for a dual-earner
  household it visually pins all withholdings to the larger
  paycheck. If a future dataset needs per-source attribution, wire
  `source_label` from `payroll_rows` to a matching income
  category.
- TSP-on-paycheck routing (bypass to `STORED_ILLIQUID` from the
  gross bar) still blocked on the mypay-parser TSP line item —
  deferred to Phase C per `P14-T02_four-terminal-buckets.md`
  Follow-ups.
