# Sentry Finance - Development Roadmap

> **Status tracking document.** Pick the next task from **Next Up**;
> open the matching `docs/prompts/<Phase-N>/` folder when a summary
> below is not enough. Closed phase detail lives in
> [`ROADMAP_ARCHIVE.md`](ROADMAP_ARCHIVE.md).
>
> Last updated: 2026-05-01. The roadmap was consolidated after the
> one-command number-trust proof gate landed. Completed/stale active
> items moved to the archive; dropped items are recorded there. Current
> priority is the single-user trust bar: live-shape validation, safe
> synthetic-to-real cutover mechanics, and number-trust coverage for the
> remaining primary pages.

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
2. `[ ]` **P17 myPay browser connector** - Automate retrieval of
   myPay/RAS PDFs so the existing parser and manual document-drop flow
   become closer to a live pipeline.
3. `[ ]` **P17 owner source-of-truth and durable ownership assignment** -
   Decide where account ownership lives and make Settings ownership edits
   durable. The ideal user workflow is: assign/modify account ownership
   in Settings, and have that assignment survive restarts and rebuilds.
4. `[ ]` **P17 Fidelity live-shape, cost basis, and tax-lot readiness** -
   Use real Fidelity data as soon as available to make synthetic
   investment data, investment APIs, and migration assumptions match the
   real brokerage shape.
5. `[ ]` **P17 TSP live-shape alignment** - Ensure synthetic and live TSP
   assumptions line up around balances, allocation, performance, and the
   fact that real ongoing TSP contributions are not expected.
6. `[ ]` **P17 subscription-vs-utility classifier audit** - Move the
   subscription/utility boundary out of fuzzy backlog and prove the
   classifier matches the household decision rule before live trust.
7. `[ ]` **P17 Investments number-trust expansion** - Extend registry,
   API oracle, second-language oracle, and DOM proof to Investments
   visible values and tabs.
8. `[ ]` **P17 Review pages number-trust expansion** - Extend
   number-trust proof to Monthly Review and Yearly Wrap-Up.
9. `[v]` **P17 Budgets page number-trust expansion** - Prove the Budgets
   page directly; Dashboard budget widgets are already covered, but the
   primary Budgets surface is not. Prompt:
   `docs/prompts/Phase-17/P17-T19_budgets-number-trust.md`.

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
  `docs/audits/number-trust/reports/number-trust-proof-20260501-020034.md`.
- API/DOM number-trust proof currently covers Dashboard, Transactions,
  Cash Flow, Reports, Accounts, and Budgets for Household, Quintin, and Amy.
- Remaining primary user-facing proof gaps before trust bar:
  Investments, Monthly Review, and Yearly Wrap-Up.
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

- `[ ]` **myPay browser connector.**
  Automate the currently manual myPay/RAS PDF retrieval path. The
  existing `dal/parsers/mypay_ras.py` parser remains the parser truth;
  this work is about securely getting the source document. Open design
  question: email/OTP capture flow.

### P17: Ownership Source Of Truth

- `[ ]` **Owner source-of-truth and durable ownership assignment.**
  Decide whether ownership assignment is DB-first, YAML-first, or hybrid.
  Target behavior: Settings can modify account ownership durably, and
  owner-aware views consume that durable source. The old "Owner
  ViewSelector fully owner-driven slots" item is folded into this work:
  once owners and ownership assignments have a clean source, the selector
  should follow that source instead of preserving separate hardcoded
  assumptions.

### P17: Live-Shape Alignment

- `[ ]` **Fidelity live-shape, cost basis, and tax-lot readiness.**
  Consolidates the old Phase 18 cost-basis/tax-lot item and Fidelity
  Live Alignment backlog item. Use real Fidelity data when available to
  verify synthetic account shape, holdings, dividends, cost basis, and
  lot data assumptions. Dividend transaction rows must land as
  `Investment Income` so live and synthetic income reporting agree.
  Full tax-lot perfection may depend on statement/detail availability,
  but live-shape validation should happen before trust bar.

- `[ ]` **TSP live-shape alignment.**
  Real ongoing TSP contributions are not expected. Audit live TSP paths
  so the app models balance, allocation, per-fund performance, and future
  inter-fund-transfer behavior without implying a live monthly cash
  contribution that will not exist.

- `[ ]` **Subscription-vs-utility classifier audit.**
  Audit `dal/category_classifications.py` and related classifier behavior
  against the household rule: subscriptions can generally be turned off
  without disrupting daily life; utilities cannot. This affects budgets,
  lifestyle-creep analysis, cash-flow interpretation, and review pages.

### P17: Remaining Number-Trust Coverage

- `[ ]` **Investments number-trust expansion.**
  Extend `docs/audits/number-trust/ui-number-registry.yaml`, API audit,
  second-language oracle, and browser DOM audit to Investments page
  values. Include overview, holdings, allocation, performance, and
  tax-related visible values where the synthetic fixture supports them.

- `[ ]` **Review pages number-trust expansion.**
  Extend number-trust proof to `MonthlyReviewPage` and `YearlyWrapUpPage`,
  including pre-tax snapshot, budget performance, notable transactions,
  tax document/checklist sections, and visible yearly summary values where
  present.

- `[v]` **Budgets page number-trust expansion.**
  Prove the primary Budgets page directly: assigned, spent, remaining,
  category rows, budget-vs-actual values, and month-scoped totals. Keep
  the household-only budget invariant intact. Prompt:
  `docs/prompts/Phase-17/P17-T19_budgets-number-trust.md`.

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
