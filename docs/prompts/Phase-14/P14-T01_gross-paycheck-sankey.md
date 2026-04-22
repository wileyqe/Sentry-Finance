# P14-T01 — Gross Paycheck on the Sankey (Phase A)

## Context

The Sankey diagram at `frontend/src/pages/ReportsPage.tsx` currently
treats the net-deposit amount that hits a checking account as
"income." For any income source with source-withheld taxes and
pre-tax deductions (W-2, pension), this hides the majority of the
gross amount — taxes, insurance premiums, and retirement
contributions are invisible.

The `payroll_snapshots` table (migration v15) already stores
gross / federal_tax / state_tax / SBP / health_insurance /
dental_vision / other_deductions / net_pay per pay period. The parser
at `dal/parsers/mypay_ras.py` populates it. `get_flow_data()` at
`dal/reports.py:556` does not read this table — it only aggregates
from the `transactions` table.

Phase A closes that gap: gross pay becomes the Sankey's left-edge
number for any source with a payroll snapshot, and each withholding
line becomes its own explicit outbound flow.

This is the smallest viable unlock. No new tables. No bucket
reclassification (that's Phase B). No frontend re-layout beyond
rendering the new data.

## Starting State

- `dal/reports.py:556-663` — `get_flow_data(conn, start, end, owner_id)`
  aggregates income from `transactions` with `signed_amount > 0`,
  `transfer_tag IS NULL`, and the blacklist + sign-check pattern.
  Returns `{income_categories, spending_categories, total_income,
  total_spending, net, savings_rate}`.
- `backend/routers/reports.py:308-331` — `/api/reports/flow`
  endpoint. Owner-scoped, accepts `start` and `end` query params.
- `dal/payroll.py:58-204` — read helpers over `payroll_snapshots`
  (`gross_income_for_year`, `effective_tax_rate`, etc.). No
  "flow contribution" helper yet.
- `payroll_snapshots` schema (from `dal/migrations/v15_payroll_snapshots.py`):
  `pay_period`, `source`, `gross_pay`, `federal_tax`, `state_tax`,
  `sbp_premium`, `health_insurance`, `dental_vision`,
  `other_deductions`, `net_pay`. One row per month per source.
- `frontend/src/pages/ReportsPage.tsx:95-200+` — custom SVG Sankey
  renderer. Reads `income_categories` and `spending_categories` from
  the `/api/reports/flow` response.

## Task

### Task 1 — `dal/payroll.get_flow_contribution`

Add a new DAL function:

```python
def get_flow_contribution(
    conn, start: str, end: str, owner_id: Optional[int] = None
) -> dict:
    """
    Roll up payroll_snapshots into Sankey flow contributions for the
    period [start, end).

    Returns:
        {
          "payroll_rows": [
            {
              "source_label": "...",
              "owner_id": N,
              "pay_period": "YYYY-MM",
              "gross_cents": int,
              "net_cents": int,
              "withholdings": [
                {"kind": "federal_tax",  "cents": int, "bucket": "CONSUMED"},
                {"kind": "state_tax",    "cents": int, "bucket": "CONSUMED"},
                {"kind": "sbp_premium",  "cents": int, "bucket": "CONSUMED"},
                {"kind": "health",       "cents": int, "bucket": "CONSUMED"},
                {"kind": "dental_vision","cents": int, "bucket": "CONSUMED"},
                {"kind": "other",        "cents": int, "bucket": "CONSUMED"},
              ],
            },
            ...
          ],
          "total_gross_cents": int,
          "total_net_cents":   int,
        }
    """
```

- Query `payroll_snapshots` rows whose `pay_period` falls in
  `[start, end)`, filtered to `owner_id` when provided.
- Each withholding field becomes one entry in the `withholdings`
  list. Zero-valued fields are omitted.
- The `bucket` label on each withholding is a forward-declaration
  for Phase B — in Phase A it is stored but not consumed. Default
  all withholdings to `"CONSUMED"`.
- `other_deductions` bucket stays `CONSUMED` in Phase A. Phase B will
  reclassify TSP / 401k portions into `STORED_ILLIQUID` via the
  income-source registry.

### Task 2 — Deposit-match dedup

When `get_flow_data` is modified to merge payroll decomposition, the
existing net-pay *transaction* that already contributes to
`total_income` must be excluded to avoid double-counting.

Rules:
- Match key: `(owner_id, month, source_label_substring)` on the
  payroll snapshot against the transaction's `merchant` or `description`
  field. Amount is a tiebreaker only — amounts drift as deductions
  change and should not be the primary match signal.
- When a payroll row matches a transaction: **exclude that transaction
  from the income aggregation**, emit the payroll decomposition in its
  place.
- When a payroll row has no matching transaction: emit the
  decomposition anyway. The scorecard in Phase D will flag
  "missing deposit" as a drift source.
- When a transaction has no matching payroll row: fall through to the
  existing transaction-derived income path unchanged.

### Task 3 — Extend `get_flow_data` and `/api/reports/flow`

- Import and call `get_flow_contribution` from `get_flow_data`.
- Add a `payroll_decomposition` key to the returned dict containing
  the output of `get_flow_contribution` plus a list of `excluded_transaction_ids`
  for diagnostic visibility.
- Preserve all existing response keys (`income_categories`,
  `spending_categories`, `total_income`, `total_spending`, `net`,
  `savings_rate`). They must continue to work for callers that have
  not upgraded.
- `total_income` semantics change: for matched rows, it counts
  `gross_cents`, not `net_cents`. Note this in the docstring; existing
  tests that assert exact dollar totals may need updated fixtures.

### Task 4 — Frontend: render alongside old

- In `ReportsPage.tsx`, read the new `payroll_decomposition` block
  when present. Render it in a debug panel next to the existing
  Sankey so the visual diff is obvious. **No change to the Sankey SVG
  in Phase A.** The SVG rework lands in Phase B behind the mockup gate.

### Task 5 — HTML mockup

Before any of the above code is written, produce a static HTML file
demonstrating the target Sankey shape for one month of real data:

- Gross pay on the left edge as one wide node.
- Withholdings as thin edges branching to a collective "Spent" sink.
- Net pay as a single edge continuing into the existing middle.
- Colors for each category of withholding.

Location: user's local scratch area, NOT in repo. See the phase
overview for rationale.

User approves the mockup before Task 3 merges.

## Verification

### Unit tests (new file `tests/test_payroll_flow.py`)

1. `test_get_flow_contribution_aggregates_by_owner` — multiple owners
   with overlapping months return owner-scoped totals.
2. `test_withholdings_list_omits_zero_fields` — a payroll snapshot
   with `$0` dental/vision produces a `withholdings` list with no
   `dental_vision` entry.
3. `test_deposit_match_excludes_transaction` — a synthetic
   payroll snapshot + matching net-pay transaction produces
   `excluded_transaction_ids` containing the transaction id, and the
   `income_categories` total excludes the net deposit.
4. `test_deposit_no_match_emits_decomposition_only` — payroll row
   with no matching deposit transaction still emits decomposition;
   `excluded_transaction_ids` is empty.
5. `test_transaction_no_payroll_falls_through` — a deposit
   transaction without a payroll row contributes to `income_categories`
   at its own amount.

### Regression

- `pytest tests/test_t04_mypay.py` passes.
- `pytest tests/test_owner_scoping.py` passes.
- `pytest tests/ -x --tb=short` passes end-to-end.

### Manual UI check

- Load ReportsPage for a month with a known gross-pay value. The
  debug panel next to the Sankey shows gross ≈ net + expected
  withholdings, to within a few dollars of the lender's statement.
- Switch owner chip (Quintin / Household / Amy) — numbers update
  correctly.
- Mockup diff: the planned Sankey layout (from Task 5) and the live
  debug panel data agree on the shape of the new flow.

## Post-Implementation Checklist

- [ ] Update `docs/ROADMAP.md` — flip `P14-T01` from `[ ]` to `[v]`
      with verification date and commit reference.
- [ ] Note any deposit-match false negatives encountered on real
      data in the "Outcomes" section of this prompt.
- [ ] Confirm `scripts/pii_scan.py --all-tracked` still clean.

## Out of Scope (explicitly deferred to later phases)

- Bucket reclassification of `other_deductions` into
  `STORED_ILLIQUID` for retirement portions (Phase B).
- Visible Sankey SVG redesign (Phase B).
- Employer-match bypass flows (Phase B).
- Dividend/interest income sources (Phase C).
- Accountability scorecard (Phase D).

## Outcomes (2026-04-21)

**Branch:** `feat/p14-a-gross-paycheck` → to be squash-merged into the
long-lived `phase-14-dollar-accountability`.

### What shipped

- **`dal/payroll.get_flow_contribution(conn, start, end, owner_id)`** —
  rolls `payroll_snapshots` into a gross/net/withholdings structure
  in integer cents. Zero-valued withholding fields are omitted. All
  withholdings default to bucket `CONSUMED` in Phase A. The
  `_WITHHOLDING_FIELDS` tuple at module top documents the
  snapshot-column → flow-kind → bucket map; Phase B's income-source
  registry will override the bucket for retirement portions.
- **`dal/payroll.find_matching_deposit_tx_id(conn, source_label,
  pay_period, owner_id)`** — finds a candidate deposit transaction
  whose merchant or description contains the payroll source as a
  case-insensitive substring, scoped by owner + effective-month.
  Amount is not part of the match key (deductions drift). Returns
  the transaction string-id or None. Short source labels (< 3 chars)
  never match.
- **`dal/reports.get_flow_data`** now folds
  `get_flow_contribution(…)` into the response: new
  `payroll_decomposition` block with `payroll_rows`,
  `total_gross_cents`, `total_net_cents`, `excluded_transaction_ids`,
  and a per-row `matched_txn_id`. Matched deposits are excluded from
  income aggregation via `id NOT IN (…)`; `total_income` is bumped by
  the matched rows' gross-vs-net delta so it reflects gross pay.
  Unmatched payroll rows are still emitted into
  `payroll_decomposition` but do NOT change income totals — Phase D's
  scorecard will flag them as drift.
- **`ReportsPage.tsx`** — new `PayrollDecompositionDebugPanel`
  component renders below the Sankey card (amber-outlined, labeled
  "Phase 14 · Phase A debug view — Sankey SVG unchanged"). Shows
  aggregate gross/withheld/net, per-row table with period / source /
  owner / gross / net / withholding chips / match-status badge. The
  existing Sankey SVG is untouched per spec.
- **Mockup-server infra** — `.claude/launch.json` gained a `mockups`
  entry (`python -m http.server 8787 --directory ~/.claude/plans`)
  so throwaway Sankey mockups can render in the preview panel
  without living in the repo. Phase B's mockup will reuse this.

### Deviations from the original spec

- `find_matching_deposit_tx_id` returns `Optional[str]`, not
  `Optional[int]`. Transaction IDs in this codebase are TEXT primary
  keys (e.g., `"tx_abc123"`), not integers — original spec drift.
- `get_flow_contribution(… owner_id: Optional[str])` instead of
  `Optional[int]` for the same reason (owner_ids are strings:
  `"quintin"`, `"amy"`, etc).
- The response's `payroll_decomposition` block adds a per-row
  `matched_txn_id` field that the prompt did not pre-specify — the
  frontend needs per-row linkage to render the "matched" vs "no
  deposit" badge without a fragile heuristic. Adds no data the
  backend wasn't already computing; just surfaces it.

### Verification

- `pytest tests/test_payroll_flow.py -x` → 5/5 passed.
- `pytest tests/ -x` → 304/304 passed (no regressions).
- `cd frontend && npm run build` → green, 19.6s.
- `python scripts/pii_scan.py --all-tracked` → clean.
- Manual UI smoke: loaded /reports against seeded `data/dummy.db`,
  confirmed debug panel renders with 3 snapshots for the default
  "Last 3 Months" window (Quintin / household view): gross $15,600,
  withheld $2,895 (federal $1,560 + state $390 + SBP $810 + dental
  $135), net $12,705. All 3 rows show "no deposit" badge — expected
  because the seeded payroll source is `dummy_seeder` which does not
  substring-match the seeded paycheck merchant `ACME CORP PAYROLL`
  (independent seeded data streams). Phase D's scorecard will surface
  this as "missing deposit" drift; no Phase A code change needed.

### Known not-now issues surfaced during work

- **Seeded payroll source ↔ transaction merchant mismatch.**
  The seeder at `scripts/dummy_data/generator.py::generate_payroll_snapshots`
  writes `source = "dummy_seeder"`, but the paycheck transaction at
  `generate_transactions` uses merchant `"ACME CORP PAYROLL"`. These
  are independent data streams today — no seeded payroll row will
  match any seeded deposit. Leaving as-is for Phase A (the matched
  path is exercised by `tests/test_payroll_flow.py` fixtures with
  controlled source/merchant values). Could be aligned later (e.g.,
  source `"acme_payroll"`) as part of Phase D's scorecard work when
  we want a clean "100% accounted" seeded demo.
- **Pre-existing `data/dummy.db` at schema v30.** Local dummy DB was
  stuck at v30 with the old digit-containing account ids
  (`summit_chk_4501` etc.) predating P0-SEC Track B's slug rewrite.
  v31 migration refused to translate because accounts.yaml now uses
  slug ids. Resolved by deleting `data/dummy.db` and re-seeding
  fresh. Seeder ran to completion of all data writes, but its final
  integrity check raised `RuntimeError: liability account has
  positive balance` — data is committed and usable (37 tables, 1860
  txns, 36 payroll rows), but the seeder's post-commit assertion
  should be investigated. Flagging as a follow-up.
