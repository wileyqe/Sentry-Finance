# Sentry Finance - Development Roadmap

> **Status tracking document.** Pick the next task from **Next Up**;
> open the matching `docs/prompts/<Phase-N>/` folder when a summary
> below is not enough. Closed phase detail lives in
> [`ROADMAP_ARCHIVE.md`](ROADMAP_ARCHIVE.md).
>
> Last updated: 2026-05-03. P17-T25 myPay browser connector foundation
> and P17-T26 Fidelity live-shape readiness audit merged; six Fidelity
> follow-up slices (`P17-T27`..`P17-T32`) now scoped under P17
> Live-Shape Alignment with mismatch IDs `FID-LS-001`..`FID-LS-015`.
> Current priority is the single-user trust bar: live-shape validation,
> safe synthetic-to-real cutover mechanics, and number-trust coverage
> for the remaining primary pages.

## Status Key

- `[ ]` - Planned (not started)
- `[->]` - In progress
- `[~]` - Partially done, deferred, or trigger-gated
- `[v]` - Complete (verified)
- `[!]` - Needs revision

## Session Handoff

See `CLAUDE.md > Read Order`. This file is step 2: scan **Next Up**,
pick a task, then open its prompt file if one exists. For non-trivial
tasks without a prompt file, author a scoped prompt first using
`docs/prompts/README.md`.

Use the Graph Context Check in `CLAUDE.md` before roadmap work, multi-file
changes, data-flow changes, connector/parser work, schema work, merge work,
or whenever blast radius is unclear.

---

## Next Up

These are the active pre-trust-bar items. Pick from this list before
opening deferred or post-trust-bar work.

1. `[v]` **P17 destructive data-wipe tooling** - Build the safe,
   explicit wipe/rebuild path needed for synthetic, test, and eventual
   real data without accidental loss. Prompt:
   `docs/prompts/Phase-17/P17-T18_destructive-data-wipe-tooling.md`.
2. `[v]` **P17 myPay browser connector foundation** - Automates
   myPay/RAS PDFs so the existing parser and manual document-drop flow
   become closer to a live pipeline. Manual MFA bridge works as the
   temporary route; Gmail OAuth OTP automation is the next slice.
   Prompt:
   `docs/prompts/Phase-17/P17-T25_mypay-browser-connector-foundation.md`.
3. `[ ]` **P17 myPay Gmail OAuth OTP automation** - Replace the
   temporary manual MFA bridge with a local Gmail OAuth OTP provider
   that reads only recent myPay/DFAS challenge emails and falls back to
   manual MFA on ambiguity, timeout, or OAuth failure. Depends on the
   P17-T25 connector seam now merged. Prompt: TBD.
4. `[v]` **P17 owner source-of-truth and durable ownership assignment** -
   Decide where account ownership lives and make Settings ownership edits
   durable. The ideal user workflow is: assign/modify account ownership
   in Settings, and have that assignment survive restarts and rebuilds.
   Prompt:
   `docs/prompts/Phase-17/P17-T20_owner-source-of-truth.md`.
5. `[~]` **P17 Fidelity live-shape, cost basis, and tax-lot readiness** -
   Audit slice complete (P17-T26 `[v]`); 6 follow-up slices
   (`P17-T27`..`P17-T32`) scoped below under P17 Live-Shape Alignment.
   Audit prompt:
   `docs/prompts/Phase-17/P17-T26_fidelity-live-shape-readiness.md`.
   Audit deliverables: `docs/audits/fidelity-live-shape/`.
6. `[ ]` **P17 TSP live-shape alignment** - Ensure synthetic and live TSP
   assumptions line up around balances, allocation, performance, and the
   fact that real ongoing TSP contributions are not expected.
7. `[v]` **P17 subscription-vs-utility classifier audit** - Move the
   subscription/utility boundary out of fuzzy backlog and prove the
   classifier matches the household decision rule before live trust.
   Prompt:
   `docs/prompts/Phase-17/P17-T24_subscription-utility-classifier-audit.md`.
8. `[v]` **P17 Investments number-trust expansion** - Extend registry,
   API oracle, second-language oracle, and DOM proof to Investments
   visible values and tabs. Prompt:
   `docs/prompts/Phase-17/P17-T23_investments-number-trust.md`.
9. `[v]` **P17 Review pages number-trust expansion** - Extend
   number-trust proof to Monthly Review and Yearly Wrap-Up. Prompt:
   `docs/prompts/Phase-17/P17-T21_review-pages-number-trust.md`.
10. `[v]` **P17 Yearly Wrap-Up interest panel number-trust promotion** -
   Promote four interest values from `registered_pending` to
   `api_oracle` (selectors already shipped in P17-T21). Prompt:
   `docs/prompts/Phase-17/P17-T22_yearly-interest-number-trust.md`.
11. `[v]` **P17 Budgets page number-trust expansion** - Prove the Budgets
    page directly; Dashboard budget widgets are already covered, but the
    primary Budgets surface is not. Prompt:
    `docs/prompts/Phase-17/P17-T19_budgets-number-trust.md`.
12. `[ ]` **P17 architecture deepening overnight queue** - Package the
    evidence-backed architecture audit findings into Codex/Claude-friendly
    autonomous slices. Each slice has a prompt file, GitHub issue, explicit
    non-goals, verification commands, and branch/commit/shutdown rules.
    See "P17: Architecture Deepening Overnight Queue" below. Parent issue:
    [#35](https://github.com/wileyqe/Sentry-Finance/issues/35).

---

## Phase Overview

| Phase | Title | Status | Notes |
|---|---|---|---|
| **0-13** | Foundation through Investments Rebuild | `[v]` Archived | See `ROADMAP_ARCHIVE.md`. |
| **14** | Dollar Accountability Overhaul | `[~]` Deferred tail | P14-T05 rental support is deferred and likely relevant soon. |
| **15** | Decision Support Features | `[v]` Closed | Completed active work archived; user-dropped items recorded in archive. |
| **16** | Notifications & Active Surveillance | `[v]` Archived | Complete. |
| **17** | Real-Data Transition Prep | `[ ]` Active | Current pre-trust-bar lane. |
| **18** | Investments - Tax Lots | `[ ]` Consolidated | Folded into P17 Fidelity live-shape/tax-lot readiness. |
| **19** | Multi-User Infrastructure Polish | `[ ]` Post trust bar | Durable ownership source moved into P17; lifecycle/cosmetics remain later. |
| **20** | Partner MFA Pipeline | `[ ]` Post trust bar | Starts only after the hard line. |
| **21** | Design System Consolidation | `[v]` Archived | Logo/cosmetic leftovers removed from active roadmap. |

## Current Trust Baseline

- Canonical trusted seed: `trusted-2026-04-27-v1`.
- Backend reference date for the trusted seed: `2026-04-28`.
- The one-command proof gate exists at
  `scripts/run_number_trust_proof.py`.
- Latest promoted proof report:
  `docs/audits/number-trust/reports/number-trust-proof-20260501-171611.md`.
- API/DOM number-trust proof currently covers Dashboard, Transactions,
  Cash Flow, Reports, Accounts, Investments, Budgets, Monthly Review, and
  Yearly Wrap-Up for Household, Quintin, and Amy.
- Remaining primary user-facing proof gaps before trust bar:
  none for registered synthetic primary pages.
- This proof is a claim about the canonical synthetic fixture and
  registered UI states. It is not yet a claim about live ingestion,
  unregistered UI values, or realistic investment behavior.

## Forward-Looking Dependency Graph

```
            [Single-User Trust Bar - all required]

       Safe wipe/reset          Durable ownership assignment
              |                           |
              v                           v
          myPay connector        Live-shape alignment
                                (Fidelity, TSP, classifier)
                                      |
                                      v
                         Expanded number-trust coverage
                         (Investments, Reviews, Budgets)
                                      |
                                      v
                      User affirms the app is trustworthy
                      for their own financial decisions

  ===================== HARD LINE - Trust Bar =====================
     Do not begin partner-integration work until the user affirms
     the single-user app is production-trustworthy for household
     financial data and decisions.
  =================================================================

                                      |
                                      v
                         Post-trust owner lifecycle polish
                                      |
                                      v
                              Partner MFA pipeline
```

---

## Before Trust Bar

### P17: Safe Data Reset And Real-Data Cutover

- `[v]` **Destructive data-wipe tooling.**
  Add a safe `scripts/wipe_data.py`-style command with dry-run output,
  explicit typed confirmation, backup guidance, and guardrails that keep
  the trusted synthetic reset path separate from real-data deletion.
  Prompt:
  `docs/prompts/Phase-17/P17-T18_destructive-data-wipe-tooling.md`.

- `[v]` **P17-T25 myPay browser connector foundation.**
  Automates the currently manual myPay/RAS PDF retrieval path through a
  browser connector, downloads the latest RAS PDF into a gitignored raw
  export location, and ingests it through the existing
  `dal/parsers/mypay_ras.py` parser-backed document pipeline. Manual
  MFA bridge is the temporary route; phone-app/push approval is surfaced
  as MFA-required and polled. Prompt:
  `docs/prompts/Phase-17/P17-T25_mypay-browser-connector-foundation.md`.

- `[ ]` **myPay Gmail OAuth OTP automation.**
  Follow-on to P17-T25. Replace the temporary manual MFA bridge with a
  local Gmail OAuth OTP provider that uses least-privilege Gmail read
  access, stores tokens only in gitignored/keyring-backed local storage,
  filters to recent myPay/DFAS challenge messages after the challenge
  start time, extracts only the OTP, redacts logs, and falls back to the
  manual MFA bridge on OAuth failure, no match, ambiguity, or timeout.

### P17: Ownership Source Of Truth

- `[v]` **Owner source-of-truth and durable ownership assignment.**
  Decide whether ownership assignment is DB-first, YAML-first, or hybrid.
  Target behavior: Settings can modify account ownership durably, and
  owner-aware views consume that durable source. The old "Owner
  ViewSelector fully owner-driven slots" item is folded into this work:
  once owners and ownership assignments have a clean source, the selector
  should follow that source instead of preserving separate hardcoded
  assumptions. Prompt:
  `docs/prompts/Phase-17/P17-T20_owner-source-of-truth.md`.

### P17: Live-Shape Alignment

- `[v]` **P17-T26 Fidelity live-shape readiness audit.**
  Read-mostly audit comparing the live Fidelity CSV shape (history
  + positions) against the synthetic seed, ingest pipeline, schema,
  and downstream investment consumers. Produced a typed live-shape
  contract, mismatch ledger (4 `block`, 9 `gap`, 2 `cosmetic`), 8/0/2
  regression gauntlet, and 6 follow-up slice drafts. Surprise: the
  current live ingest only persists a SPAXX cash balance — live
  Fidelity holdings, activity, dividends, EFT links, and per-position
  cost basis do not reach the investment tables yet. Prompt:
  `docs/prompts/Phase-17/P17-T26_fidelity-live-shape-readiness.md`.
  Audit:
  `docs/audits/fidelity-live-shape/`.

- `[ ]` **P17-T27 Fidelity live writer for holdings, snapshots, and
  ledger rows.** Persist parsed Fidelity history and positions into
  `positions_ledger`, `investment_holdings`, and `portfolio_snapshots`
  instead of stopping at output CSVs plus a SPAXX balance snapshot.
  Include SPAXX cash/equivalent handling, preserve settlement dates
  where present, and create unlinked zero-share `DEPOSIT` / `WITHDRAWAL`
  marker rows for Fidelity EFT evidence. Receipts: `FID-LS-001`,
  `FID-LS-003`, `FID-LS-009`.
  Severity: `block`. Blast radius: `scripts/ingest_fidelity_history.py`,
  `extractors/fidelity_connector.py`, investment DAL tests, flow /
  accountability tests. Prompt:
  `docs/prompts/Phase-17/P17-T27_fidelity-live-writer.md`.
  Issue: [#36](https://github.com/wileyqe/Sentry-Finance/issues/36).

- `[ ]` **P17-T28 Fidelity live EFT cash-leg linker.**
  Map live `Electronic Funds Transfer Received/Paid (Cash)` rows to
  existing imported bank-side cash transactions, set Acorns-compatible
  `transfer_tag` / `investment_link`, and stamp exactly one Fidelity
  `DEPOSIT` / `WITHDRAWAL` marker row with `bank_txn_id` so Shape B
  cash-flow/accountability reports remain truthful without synthesizing
  bank rows. Receipts: `FID-LS-004`, AI-010.
  Severity: `block`. Blast radius: Fidelity ingest writer,
  reconciliation/linking helpers, `dal/reports/flow.py`,
  `tests/test_investment_contributions_view.py`,
  `tests/test_flow_shape_b_brokerage.py`. Prompt:
  `docs/prompts/Phase-17/P17-T28_fidelity-eft-cash-leg-linker.md`.
  Issue: [#41](https://github.com/wileyqe/Sentry-Finance/issues/41).

- `[ ]` **P17-T29 Fidelity dividend and capital-gain income writer.**
  Convert live `DIVIDEND RECEIVED` and `CAP GAIN` rows into posted
  cash transactions with `category='Investment Income'`, positive
  `signed_amount`, no `transfer_tag`, and enough ticker/description
  structure for reinvestment-flow pairing. Use Fidelity `Run Date` as
  the factual cash-transaction date, preserve the raw action as source
  evidence instead of adding subtype schema, and skip rows with missing
  factual date/positive amount. Receipts: `FID-LS-005`, `FID-LS-014`,
  AI-016. Severity: `block`. Blast radius: Fidelity ingest writer,
  `dal/transactions.py`, `dal/reports/flow.py`, dividend / interest flow
  tests. Prompt:
  `docs/prompts/Phase-17/P17-T29_fidelity-dividend-income-writer.md`.
  Issue: [#40](https://github.com/wileyqe/Sentry-Finance/issues/40).

- `[ ]` **P17-T30 Fidelity per-position cost-basis persistence.**
  Persist `Cost Basis Total` from the Positions CSV to
  `investment_holdings.cost_basis`, use `Average Cost Basis` as a
  validation/fallback signal, and populate
  `positions_ledger.cost_basis_dec` only where trade/reinvestment
  evidence supports a lot-forming row. Retire or bypass the legacy
  aggregate Fidelity cost-basis write to `loan_details`; if any
  account-details naming remains misleading, clean it up or document the
  remaining compatibility boundary. Receipts: `FID-LS-006`,
  `FID-LS-011`. Severity: `block`. Blast radius: Fidelity positions
  parser/writer, `dal/investments.py`, account-details composition,
  investment details/panel tests, number-trust Investments oracle.
  Prompt:
  `docs/prompts/Phase-17/P17-T30_fidelity-cost-basis-persistence.md`.

- `[ ]` **P17-T31 Fidelity live-shape parser hardening and source
  capture.** Harden action-verb, currency, multi-account,
  SELL/closed-position, and header/footer fixture coverage before
  live trust. Capture a HItL sample for missing SELL/closed-position
  events if available; otherwise keep the gap explicit. Receipts:
  `FID-LS-002`, `FID-LS-008`, `FID-LS-010`, `FID-LS-011`,
  `FID-LS-012`, `FID-LS-013`. Severity: `gap`. Blast radius:
  Fidelity parser tests/fixtures, connector download contract,
  docs/audit fixtures. Prompt: TBD
  (`docs/prompts/Phase-17/P17-T31_fidelity-parser-hardening.md`).

- `[ ]` **P17-T32 Fidelity tax-lot and 1099 reconciliation source
  audit.** Decide the next authoritative tax-lot source
  (GainsKeeper/export, in-page lot detail, Closed Positions,
  statements, or 1099-B) and run a separate redacted reconciliation
  audit against `dal/parsers/fidelity_1099.py`. Receipts:
  `FID-LS-007`, `FID-LS-015`. Severity: `gap`. Blast radius:
  tax-lot docs, Fidelity 1099 parser tests, yearly wrap-up tax
  document flow. Prompt: TBD
  (`docs/prompts/Phase-17/P17-T32_fidelity-tax-lot-source-audit.md`).

- `[ ]` **TSP live-shape alignment.**
  Real ongoing TSP contributions are not expected. Audit live TSP paths
  so the app models balance, allocation, per-fund performance, and future
  inter-fund-transfer behavior without implying a live monthly cash
  contribution that will not exist.

- `[v]` **Subscription-vs-utility classifier audit.**
  Audit `dal/category_classifications.py` and related classifier behavior
  against the household rule: subscriptions can generally be turned off
  without disrupting daily life; utilities cannot. This affects budgets,
  lifestyle-creep analysis, cash-flow interpretation, and review pages.
  Prompt:
  `docs/prompts/Phase-17/P17-T24_subscription-utility-classifier-audit.md`.

### P17: Remaining Number-Trust Coverage

- `[v]` **Investments number-trust expansion.**
  Extend `docs/audits/number-trust/ui-number-registry.yaml`, API audit,
  second-language oracle, and browser DOM audit to Investments page
  values. Include overview, holdings, allocation, performance, and
  tax-related visible values where the synthetic fixture supports them.
  Prompt:
  `docs/prompts/Phase-17/P17-T23_investments-number-trust.md`.

- `[v]` **Review pages number-trust expansion.**
  Extend number-trust proof to `MonthlyReviewPage` and `YearlyWrapUpPage`,
  including pre-tax snapshot, budget performance, notable transactions,
  tax document/checklist sections, and visible yearly summary values where
  present. Prompt:
  `docs/prompts/Phase-17/P17-T21_review-pages-number-trust.md`.

- `[v]` **Yearly Wrap-Up interest panel number-trust promotion.**
  Promote the four interest values (`net_interest_cost`,
  `interest.paid`, `interest.earned`, `interest.net_cost`) on
  `/review/yearly` from `registered_pending` to `api_oracle`. The P17-T21
  selectors are now backed by independent Python and Node oracles for
  `compute_interest_cost`. Prompt:
  `docs/prompts/Phase-17/P17-T22_yearly-interest-number-trust.md`.

- `[v]` **Budgets page number-trust expansion.**
  Prove the primary Budgets page directly: assigned, spent, remaining,
  category rows, budget-vs-actual values, and month-scoped totals. Keep
  the household-only budget invariant intact. Prompt:
  `docs/prompts/Phase-17/P17-T19_budgets-number-trust.md`.

### P17: Architecture Deepening Overnight Queue

These slices come from the May 2026 `improve-codebase-architecture`
audit. They are deliberately packaged for overnight Codex and Claude
agents: each item has bounded scope, non-goals, exact evidence files,
verification commands, and shutdown instructions. Agents may create a
branch, implement, run verification, commit, and stop. They must not
merge. Morning review should inspect the resulting branches or draft PRs
and merge in dependency order.

- `[ ]` **P17-T33 Reference-clock audit coverage hardening.**
  The reference-clock audit currently passes while omitting finance-window
  modules that still use wall-clock SQL/Python patterns. Deepen the audit
  so `dal/reports/merchant.py`, `dal/budgets.py`, and `dal/forecasting.py`
  are either covered or explicitly allowed, then fix the newly-covered
  finance-window paths. Prompt:
  `docs/prompts/Phase-17/P17-T33_reference-clock-audit-hardening.md`.
  Issue: [#38](https://github.com/wileyqe/Sentry-Finance/issues/38).

- `[ ]` **P17-T34 Owner-aware frontend request helper.**
  Preserve `dal/owners.build_account_filter` and `useOwnerApi`, but add a
  shared owner-aware request path for imperative frontend fetches so pages
  stop hand-building `owner_id=` query strings. This is the frontend half
  of owner scoping; do not broaden household-only budgets. Prompt:
  `docs/prompts/Phase-17/P17-T34_owner-aware-request-helper.md`.
  Issue: [#37](https://github.com/wileyqe/Sentry-Finance/issues/37).

- `[ ]` **P17-T35 Analytical transaction window module.**
  Protect `dal/flow_aggregation.compute_period_totals`; deepen the smaller
  query-window layer underneath it by centralizing effective-month
  attribution and canonical income/spend SQL fragments for reports,
  budgets, forecasts, and merchant analytics. Prompt:
  `docs/prompts/Phase-17/P17-T35_analytical-transaction-window-module.md`.
  Issue: [#42](https://github.com/wileyqe/Sentry-Finance/issues/42).

- `[ ]` **P17-T36 Number-trust proof metadata/spec design.**
  Human-in-the-loop design item. Decide what number-trust proof metadata
  becomes declarative while preserving independent Python and Node oracle
  math. After the decision, split implementation into AFK slices. Prompt:
  `docs/prompts/Phase-17/P17-T36_number-trust-proof-spec.md`.
  Issue: [#39](https://github.com/wileyqe/Sentry-Finance/issues/39).

---

## Deferred And Trigger-Gated

These items stay visible but should not displace the pre-trust-bar list
unless their trigger happens or the user explicitly pulls them forward.

- `[~]` **P14-T05 rental property support.**
  Deferred, likely relevant soon. Add rental income, rental expenses,
  per-property accounts, and security-deposit handling when a real rental
  planning/data signal appears. Prompt:
  `docs/prompts/Phase-14/P14-T05_rental-property-support.md`.

- `[~]` **Cut `vehicle_assets.linked_loan_id` hand-wired seed link.**
  Triggered after the first real NFCU vehicle/loan scrape proves the live
  connector can stamp the vehicle-to-loan relationship from real evidence
  such as VIN/account data. Until then, the synthetic link can remain as a
  fixture convenience.

- `[~]` **Reconciliation hardening.**
  Backlog. Improve matching for delayed clears, wider windows, FX effects,
  partial matches, and fee-adjusted transfers when real misses surface.

- `[~]` **Extractor sign/direction guardrail.**
  Backlog tied to extractor work. Existing extractor/sign convention work
  is mostly complete; keep this visible so live extractor changes preserve
  the canonical signed-amount invariant.

---

## HARD LINE - Trust Bar

```
============================================================
  STOP. Do not begin partner-integration work until the
  pre-trust-bar list is complete and the user has affirmed the
  app is production-trustworthy for their own household
  financial data and decisions.

  Partner integration is not a substitute for the trust bar.
  It compounds on top of it.
============================================================
```

---

## Post-Trust-Bar Work

- `[ ]` **Owner delete/archive lifecycle.**
  Decide how to hide, archive, delete, or reassign owners without
  corrupting historical household data.

- `[ ]` **Owner cosmetic fields.**
  Add owner display polish such as avatar/color fields if they still feel
  useful after durable ownership assignment is complete.

- `[ ]` **Partner MFA pipeline.**
  Build the partner-side MFA/OTP handoff after the single-user app has
  crossed the trust bar. Current design reference:
  `docs/PARTNER_MFA_DESIGN.md`.

---

## Archived Or Dropped By Consolidation

The 2026-05-01 consolidation moved completed/stale active items and
user-dropped work to `ROADMAP_ARCHIVE.md`. Highlights:

- Completed Phase 17 number-trust foundation and proof-gate detail.
- Completed Phase 21 design-system continuation work, including logo/cosmetic
  leftovers removed from active scope.
- Completed P15-T09 investment detail scraping and related stale `Next Up`
  entries.
- User-dropped work recorded in the archive so it does not remain active.
