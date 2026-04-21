# Phase 14 — Dollar Accountability Overhaul

**Status:** Planned (2026-04-20)
**Type:** Multi-phase backend + DAL + frontend (5 phases, long-lived
feature branch)
**Replaces:** the previously `[DEFERRED]` Phase 14 (Budget Model
Redesign). Four terminal fate buckets are a more honest frame than
category budgets; this overhaul supersedes that idea.

## The Problem (in the user's words)

> "Every dollar comes from somewhere. Every dollar lands somewhere.
> There are transfers, expenses, investments, fees, deposits. And then
> there's storage and growth. I'm not particularly pleased with how the
> Sankey diagram just has a savings rate (income − expenses = savings).
> I want the diagram, but I'd love to know where that money is/went."

The current Sankey at `dal/reports.py:556` `get_flow_data()` uses
single-entry cash-flow accounting with a residual "savings" bucket.
That bucket silently conflates four fundamentally different dollar
fates that the app should be able to distinguish:

- **Spent** — truly consumed (utilities, taxes, mortgage interest).
- **Kept liquid** — checking/HYSA accumulation, uninvested brokerage
  cash.
- **Kept illiquid** — retirement contributions, HSA, mortgage
  principal paid, securities purchased.
- **Grown / Shrunk** — unrealized market moves on owned positions,
  real-estate valuation changes. No cash leg.

## Design decisions locked in

1. **Four fate buckets, but only three drawn on the Sankey.**
   Spent / Kept-liquid / Kept-illiquid appear on the right edge of
   the Sankey. `GROWN` exists in the enum but is never drawn —
   market moves on existing positions are a net-worth concept, not
   a cash flow, and drawing them would require a fictional left-edge
   source node and unsupported negative flows.

2. **Dividends and interest ARE cash flows.** They hit an account as
   new money, so they belong on the Sankey as income sources. A
   reinvested dividend is two visible legs: the dividend (income) and
   the buy (into Kept-illiquid). The underlying shares changing price
   afterward is invisible to the Sankey.

3. **Accountability scorecard (the reconciliation layer).** A header
   card on the Reports page:
   > "We've accounted for X% of your net-worth change this period."

   Identity:
   ```
   Δ NetWorth = (Dollars in)
              − (Dollars spent)
              ± (Change in market value of holdings)
              ± (Change in real-estate valuations)
              + unexplained
   ```
   Click through shows what's missing, each with a click-to-fix where
   possible. This is the real product — it converts "data trust" from
   a feeling into an improvable number.

4. **Capability-shaped data model, not hard-coded rules.** Income
   sources vary by tax treatment: source-withheld (W-2, pension),
   source-nontaxable, no-source-withholding (contractor,
   reconciled-annually), investment-yield, employer-match-bypass,
   rental. These are archetypes on a registry table, not branches in
   code. New household situations add a row, not a commit.

5. **Mortgage P&I split supports both statement-derived (exact) and
   amortization-derived (computed) methods in the same table.**
   `method` column records provenance so it's visible at a glance
   which loans have authoritative statement data and which rely on
   amortization math.

## Phase breakdown

Each phase ships on its own sub-branch and squash-merges into the
long-lived feature branch. Nothing merges to `main` until all four
core phases (A–D) are verified end-to-end on real data. Phase E lands
separately when triggered.

| Phase | Task prompt | What ships |
|---|---|---|
| **A** | `P14-T01_gross-paycheck-sankey.md` | Gross paycheck decomposition on the Sankey left edge. Withholdings become explicit outbound flows. No new tables. |
| **B** | `P14-T02_four-terminal-buckets.md` | Three-bucket Sankey right column. Mortgage P&I decomposition. Income-source registry. Brokerage cash-vs-position classification. |
| **C** | `P14-T03_dividends-interest-income.md` | Dividends and interest as first-class income sources. Reinvested dividends as two-leg flows. Contributions view. |
| **D** | `P14-T04_accountability-scorecard.md` | Reconciliation identity + header card + drilldown modal. Named drift sources with click-to-fix affordances. |
| **E** | `P14-T05_rental-property-support.md` | Rental income, rental expenses, per-property operational accounts. Deferred — triggered by the actual landlord transition, not the calendar. |

## New data model — summary

Three additions total. No column changes to existing tables.

- **`income_sources`** (Phase B, migration `v32`) — registry of income
  sources with a `tax_treatment` enum, `match_rule_json`, and an
  optional `bypass_cash_routing` flag for employer-match flows.
- **`loan_payment_splits`** (Phase B, migration `v33`) — per-payment
  principal / interest / escrow decomposition. `method` column
  distinguishes statement-derived from amortization-derived splits.
- **`v_investment_contributions`** (Phase C, SQL view) — joins
  `positions_ledger` to matching cash-side transfers via
  `transfer_tag`. Not materialized: contribution classification must
  track current user categorization.

## Architecture invariants this phase must preserve

Cross-references to `docs/ARCHITECTURE.md`:

- **§4.6 (Sign Convention).** All new aggregates MUST use the
  canonical blacklist + sign-check pattern with `signed_amount` and
  `transfer_tag IS NULL`. New code must NOT follow the legacy
  `SUM(CASE WHEN direction='Debit' THEN amount …)` pattern.
- **Owner scoping.** Every new query, endpoint, and page threads
  `owner_id` via `dal/owners.build_account_filter(owner_id,
  account_ids)`. `None` vs `[]` semantics are preserved.
- **Integer cents.** All money stays integer cents. No floats.
- **DAL isolation.** Routers call DAL. New SQL does not leak into the
  API layer.
- **Post-commit pipeline.** The existing categorization →
  reconciliation → recurring → derived → alerts → goal-sync chain is
  preserved. New post-commit step for `loan_payment_splits` slots
  between reconciliation and derived-recompute.
- **SSE event shapes.** No new SSE event shapes unless a phase
  prompt explicitly adds one to the registry.
- **PII policy.** All repo artifacts (migrations, seeder fixtures,
  tests) use abstract archetype labels — never real institution or
  source names.

## Pre-implementation gates

Phases A and B each require a **static HTML mockup** of the target
Sankey before code is written. The mockup lives outside the repo (in
the session workspace or `~/.claude/plans/`), uses inline SVG, and
demonstrates layout + color coding against a known month's data. The
mockup is throwaway; the custom SVG renderer is expensive to rework
and getting the layout right on paper saves a full rebuild.

## Branching strategy

- Long-lived: `feat/phase14-dollar-accountability`.
- Per phase: `feat/p14-a-gross-paycheck`, `feat/p14-b-four-buckets`,
  `feat/p14-c-dividends-interest`, `feat/p14-d-scorecard`.
- Each phase is independently verifiable — the long-lived branch is
  always a working app.
- Merge to `main` only after all of A–D verify end-to-end on real
  data (§ Exit criteria below).

## Exit criteria

Phase 14 is "done" when:

- All four core phases (A–D) have landed with their individual
  verification signed off.
- `accounted_for_pct ≥ 95%` on a 3-month window of real household
  data.
- A user can point at the Sankey and answer: "every dollar from every
  source this month — where did it end up?"
- The residual "savings" bar is gone, replaced by three labeled
  buckets.
- Market value changes are **invisible** on the Sankey and **visible**
  in the scorecard's reconciliation math.
- `python scripts/pii_scan.py --all-tracked` reports clean.
- Full backend test suite + frontend build are green.

## Reference

- Full implementation detail: per-task prompts `P14-T01` … `P14-T05`.
- Capability discussion and household-specific instance list: local
  plan file (not in repo).
- Companion context on how net-worth history is computed today:
  `dal/reports.py:189-381` `get_net_worth_history()`.
