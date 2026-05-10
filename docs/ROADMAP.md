# Sentry Finance - Development Roadmap

> **Status tracking document.** Pick the next task from **Next Up**;
> open the matching `docs/prompts/<Phase-N>/` folder when a summary
> below is not enough. Closed phase detail lives in
> [`ROADMAP_ARCHIVE.md`](ROADMAP_ARCHIVE.md).
>
> Last updated: 2026-05-09. P17-T44 myPay password rotation now handles
> the observed post-change return-to-login branch. If the user chooses
> `Change now`, completes the change in the live browser, and myPay
> signs out afterward, the dashboard asks the user to save the new
> password in Windows Credential Manager, verifies non-secret credential
> metadata, refreshes broker credentials through the normal elevation
> path, and attempts one clean re-login before continuing to RAS export.
> The post-login completion branch also waits for the same local credential
> update confirmation before export. Gmail OTP remains opt-in until the user
> chooses to make it default.
>
> P17-T42 myPay live-shape work is verified:
> login, email MFA, password-change, DoD consent, retired eRAS
> navigation, and blob-backed PDF modal selectors have live receipts;
> the downloaded local RAS remains gitignored and was used to harden
> parser behavior. Live connector download/ingest was verified from
> the authenticated session, with committed `mypay_ras` document-drop
> and `payroll_snapshots` evidence in the trusted dummy DB. Follow-up
> hardening ensures direct browser OTP entry does not wait out the
> dashboard MFA timeout, and myPay dev runs now log out and close the
> automation browser.
> Remaining Fidelity follow-up slices (`P17-T30`..`P17-T32`) stay
> scoped under P17 Live-Shape Alignment with mismatch IDs
> `FID-LS-001`..`FID-LS-017`. Current priority is the single-user
> trust bar: live-shape validation and safe synthetic-to-real cutover
> mechanics.

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
3. `[v]` **P17 myPay live selector and MFA walkthrough** - Live
   login/email-MFA/RAS selector facts are captured, connector/parser
   cleanup is written, focused tests pass, and authenticated-session
   connector download/ingest verified committed `mypay_ras` document
   and payroll rows. Follow-up hardening removes direct-browser OTP
   timeout waits and enforces logout/browser cleanup. Prompt:
   `docs/prompts/Phase-17/P17-T42_mypay-live-selector-mfa-walkthrough.md`.
   Issue: [#64](https://github.com/wileyqe/Sentry-Finance/issues/64).
4. `[v]` **P17 myPay Gmail OAuth OTP automation** - Replace the
   temporary manual MFA bridge with a local Gmail OAuth OTP provider
   that reads only recent myPay/DFAS challenge emails and falls back to
   manual MFA on ambiguity, timeout, or OAuth failure. Depends on the
   P17-T25 connector seam and can start behind an opt-in flag using
   the P17-T42 email-MFA facts. Prompt:
   `docs/prompts/Phase-17/P17-T43_mypay-gmail-oauth-otp-automation.md`.
   Issue: [#65](https://github.com/wileyqe/Sentry-Finance/issues/65).
5. `[v]` **P17 owner source-of-truth and durable ownership assignment** -
   Decide where account ownership lives and make Settings ownership edits
   durable. The ideal user workflow is: assign/modify account ownership
   in Settings, and have that assignment survive restarts and rebuilds.
   Prompt:
   `docs/prompts/Phase-17/P17-T20_owner-source-of-truth.md`.
6. `[~]` **P17 Fidelity live-shape, cost basis, and tax-lot readiness** -
   Audit slice complete (P17-T26 `[v]`); 6 follow-up slices
   (`P17-T27`..`P17-T32`) scoped below under P17 Live-Shape Alignment.
   Audit prompt:
   `docs/prompts/Phase-17/P17-T26_fidelity-live-shape-readiness.md`.
   Audit deliverables: `docs/audits/fidelity-live-shape/`.
   Issue: [#76](https://github.com/wileyqe/Sentry-Finance/issues/76).
7. `[ ]` **P17-T45 TSP live-shape alignment** - Ensure synthetic and live TSP
   assumptions line up around balances, allocation, performance, and the
   fact that real ongoing TSP contributions are not expected.
   Prompt:
   `docs/prompts/Phase-17/P17-T45_tsp-live-shape-alignment.md`.
   Issue: [#79](https://github.com/wileyqe/Sentry-Finance/issues/79).
8. `[v]` **P17 subscription-vs-utility classifier audit** - Move the
   subscription/utility boundary out of fuzzy backlog and prove the
   classifier matches the household decision rule before live trust.
   Prompt:
   `docs/prompts/Phase-17/P17-T24_subscription-utility-classifier-audit.md`.
9. `[v]` **P17 Investments number-trust expansion** - Extend registry,
   API oracle, second-language oracle, and DOM proof to Investments
   visible values and tabs. Prompt:
   `docs/prompts/Phase-17/P17-T23_investments-number-trust.md`.
10. `[v]` **P17 Review pages number-trust expansion** - Extend
   number-trust proof to Monthly Review and Yearly Wrap-Up. Prompt:
   `docs/prompts/Phase-17/P17-T21_review-pages-number-trust.md`.
11. `[v]` **P17 Yearly Wrap-Up interest panel number-trust promotion** -
   Promote four interest values from `registered_pending` to
   `api_oracle` (selectors already shipped in P17-T21). Prompt:
   `docs/prompts/Phase-17/P17-T22_yearly-interest-number-trust.md`.
12. `[v]` **P17 Budgets page number-trust expansion** - Prove the Budgets
    page directly; Dashboard budget widgets are already covered, but the
    primary Budgets surface is not. Prompt:
    `docs/prompts/Phase-17/P17-T19_budgets-number-trust.md`.
13. `[v]` **P17 architecture deepening overnight queue** - Package the
    evidence-backed architecture audit findings into Codex/Claude-friendly
    autonomous slices. Each slice has a prompt file, GitHub issue, explicit
    non-goals, verification commands, and branch/commit/shutdown rules.
    See "P17: Architecture Deepening Overnight Queue" below. Parent issue:
    [#35](https://github.com/wileyqe/Sentry-Finance/issues/35).
    All seven child slices (T27, T28, T29, T33, T34, T35, T36) plus the
    T36 fan-out (T37-T41) merged on 2026-05-06.

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

- `[v]` **P17-T42 myPay live selector and MFA walkthrough.**
  Live HITL walkthrough captured login, email MFA, password-change,
  DoD consent, retired eRAS navigation, RAS page, and blob-backed PDF
  modal facts. The connector now handles the observed flow, and the
  parser was hardened against the downloaded gitignored RAS layout. A
  direct-browser OTP path was also fixed so user-entered myPay OTPs do
  not leave the connector blocked on the dashboard MFA bridge. Focused
  tests pass, and live authenticated-session download/ingest verified
  committed `mypay_ras` document-drop and payroll rows. Follow-up
  hardening removes direct-browser OTP timeout waits and enforces eRAS
  modal close, logout, survey decline, tab close, and final browser
  cleanup for myPay dev runs. Prompt:
  `docs/prompts/Phase-17/P17-T42_mypay-live-selector-mfa-walkthrough.md`.
  Issue: [#64](https://github.com/wileyqe/Sentry-Finance/issues/64).

- `[v]` **P17-T43 myPay Gmail OAuth OTP automation.**
  Follow-on to P17-T25. Replace the temporary manual MFA bridge with a
  local Gmail OAuth OTP provider that uses least-privilege Gmail read
  access, stores tokens only in gitignored/keyring-backed local storage,
  filters to recent myPay/DFAS challenge messages after the challenge
  start time, extracts only the OTP, redacts logs, and falls back to the
  manual MFA bridge on OAuth failure, no match, ambiguity, or timeout.
  P17-T42 has confirmed the email factor and OTP screen shape. T43 is
  unit-verified and remains opt-in via `MYPAY_OTP_PROVIDER=gmail`.
  Live OAuth bootstrap, Gmail OTP lookup, and a full myPay scrape are
  verified against the observed `DFAS-SmartDocs@mail.mil` sender. Gmail
  OTP remains opt-in until the user chooses to make it default.
  Prompt:
  `docs/prompts/Phase-17/P17-T43_mypay-gmail-oauth-otp-automation.md`.
  Issue: [#65](https://github.com/wileyqe/Sentry-Finance/issues/65).

- `[v]` **P17 myPay password-rotation UX.**
  The live password-rotation flow is verified.
  When myPay shows its periodic password-change prompt, the connector
  emits a non-secret `credential_action_required` SSE event. The
  dashboard surfaces a persistent toast with `Change now` and
  `Remind me later`; no-UI and timeout paths still default to
  `Remind Me Later` and record the durable
  `credential_action_needed` notification. `Change now` leaves the
  live myPay browser available for the user to rotate the password; the
  connector no longer clicks myPay password-change controls on the user's
  behalf. After the site accepts the change, the UI can launch
  `backend/credential_broker.py --store mypay` in a local prompt so the
  updated password goes straight to the OS credential store and never through
  the dashboard. The app confirms that local store update only through
  non-secret Credential Manager metadata. Live testing on 2026-05-09
  confirmed Gmail OTP and prompt detection, found and fixed stale-CDP-profile
  attachment, and added menu-opening coverage for the post-consent RAS page.
  The normal `/api/refresh/start` path now accepts
  targeted connector refreshes such as `{"institutions":["mypay"],"force":true}`
  and runs them inside the API process, so dashboard SSE/toast verification no
  longer depends on a one-off dev endpoint. Live API-process testing on
  2026-05-09 fixed redirected Windows Unicode output and tightened `Change now`
  to pause for manual site interaction instead of attempting to drive sensitive
  password-change controls. A follow-up live run on 2026-05-09 reached the OTP
  page but Gmail capture missed the delivered code because the email can arrive
  just before the connector records the challenge timestamp; the Gmail provider
  now uses a bounded lookback window and leaves more time for manual fallback,
  while the MFA modal stops spinning when an institution fails. A final live
  API run on 2026-05-09 completed the full branch: Gmail/manual MFA reached
  post-login, the dashboard `Change now` branch paused for manual password
  rotation, the local broker stored the updated password in Windows Credential
  Manager, the app confirmed non-secret credential metadata, and the connector
  downloaded/ingested `mypay_ras_unknown_20260509_173914.pdf` before closing the
  automation browser. Follow-up hardening now makes every completed `Change now`
  branch wait for local credential-store confirmation before export, and also
  covers the branch where myPay accepts the new password but returns to the
  login page: the UI exposes `Continue refresh` / `Stop`, verifies the stored
  credential metadata, pulls fresh broker credentials through elevation, and
  attempts one post-change re-login. If password rotation succeeded but RAS
  export still fails, the app records a durable warning that the password is
  updated while the RAS export is incomplete. Remaining caution: avoid repeated
  live myPay runs in a tight window because DFAS can surface security-concern
  stops. Prompt:
  `docs/prompts/Phase-17/P17-T44_mypay-password-rotation-ux.md`.

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

- `[v]` **P17-T27 Fidelity live writer for holdings, snapshots, and
  ledger rows.** Persist parsed Fidelity history and positions into
  `positions_ledger`, `investment_holdings`, and `portfolio_snapshots`
  instead of stopping at output CSVs plus a SPAXX balance snapshot.
  Include SPAXX cash/equivalent handling, preserve settlement dates
  where present, and create unlinked zero-share `DEPOSIT` / `WITHDRAWAL`
  marker rows for Fidelity EFT evidence. Receipts: `FID-LS-001`,
  `FID-LS-003`, `FID-LS-009`.
  Verified by fixture-backed writer tests, targeted Fidelity/investment
  suites, reference-clock audit, and full backend suite. Remaining live-shape
  work stays in P17-T28..T32. Prompt:
  `docs/prompts/Phase-17/P17-T27_fidelity-live-writer.md`.
  Issue: [#36](https://github.com/wileyqe/Sentry-Finance/issues/36).

- `[v]` **P17-T28 Fidelity live EFT cash-leg linker.**
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
  Merged: PR [#47](https://github.com/wileyqe/Sentry-Finance/pull/47) (`8bb55de`).

- `[v]` **P17-T29 Fidelity dividend and capital-gain income writer.**
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
  Merged: PR [#46](https://github.com/wileyqe/Sentry-Finance/pull/46) (`8e087a2`).

- `[v]` **P17-T30 Fidelity per-position cost-basis persistence.**
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
  Verified: per-position basis persists through
  `dal/fidelity_investment_writes.py::write_fidelity_investment_state`;
  `_clean_number` covers parenthesized negatives + blanks; legacy
  `loan_details.cost_basis` write retired (no shim). Tests: 39
  targeted + 148 investments-suite passing; full suite green except
  one pre-existing flake unrelated to P17-T30. Prompt:
  `docs/prompts/Phase-17/P17-T30_fidelity-cost-basis-persistence.md`.
  Issue: [#69](https://github.com/wileyqe/Sentry-Finance/issues/69).

- `[ ]` **P17-T31 Fidelity live-shape parser hardening and source
  capture.** Harden action-verb, currency, multi-account,
  SELL/closed-position, and header/footer fixture coverage before
  live trust. Capture a HItL sample for missing SELL/closed-position
  events if available; otherwise keep the gap explicit. Receipts:
  `FID-LS-002`, `FID-LS-008`, `FID-LS-010`, `FID-LS-011`,
  `FID-LS-012`, `FID-LS-013`. Severity: `gap`. Blast radius:
  Fidelity parser tests/fixtures, connector download contract,
  docs/audit fixtures. Prompt:
  `docs/prompts/Phase-17/P17-T31_fidelity-parser-hardening.md`.
  Issue: [#77](https://github.com/wileyqe/Sentry-Finance/issues/77).

- `[x]` **P17-T32 Fidelity tax-lot and 1099 reconciliation source
  audit.** Decide the next authoritative tax-lot source
  (GainsKeeper/export, in-page lot detail, Closed Positions,
  statements, or 1099-B) and run a separate redacted reconciliation
  audit against `dal/parsers/fidelity_1099.py`. Receipts:
  `FID-LS-007`, `FID-LS-014`, `FID-LS-015` decided; new follow-ups
  `FID-LS-016` (1099 parser silent-drop on 1099-B totals) and
  `FID-LS-017` (wash-sale stress-test deferred). Severity: audit
  closed; gaps remain on FID-LS-016/017. Blast radius: tax-lot docs,
  Fidelity 1099 parser tests, yearly wrap-up tax document flow.
  Outcomes: closed-lot source = `Closed_Positions_<year>.csv`
  (cents-perfect against 2023 1099-B); open-lot per-position basis
  via P17-T30; **FID-LS-014 schema declined** (subtype already
  preserved in `transactions.description` + `raw_description`); no
  migration shipped. Prompt:
  `docs/prompts/Phase-17/P17-T32_fidelity-tax-lot-source-audit.md`.
  Audit deliverables:
  `docs/audits/fidelity-live-shape/tax-lot-source-recommendation.md`,
  `docs/audits/fidelity-live-shape/1099-reconciliation.md`.
  Issue: [#78](https://github.com/wileyqe/Sentry-Finance/issues/78).

- `[ ]` **P17-T45 TSP live-shape alignment.**
  Real ongoing TSP contributions are not expected. Audit live TSP paths
  so the app models balance, allocation, per-fund performance, and future
  inter-fund-transfer behavior without implying a live monthly cash
  contribution that will not exist.
  Prompt:
  `docs/prompts/Phase-17/P17-T45_tsp-live-shape-alignment.md`.
  Issue: [#79](https://github.com/wileyqe/Sentry-Finance/issues/79).

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

- `[v]` **P17-T33 Reference-clock audit coverage hardening.**
  The reference-clock audit currently passes while omitting finance-window
  modules that still use wall-clock SQL/Python patterns. Deepen the audit
  so `dal/reports/merchant.py`, `dal/budgets.py`, and `dal/forecasting.py`
  are either covered or explicitly allowed, then fix the newly-covered
  finance-window paths. Prompt:
  `docs/prompts/Phase-17/P17-T33_reference-clock-audit-hardening.md`.
  Issue: [#38](https://github.com/wileyqe/Sentry-Finance/issues/38).
  Merged: `ea91788` (direct merge of `claude/p17-t33-reference-clock-audit`).

- `[v]` **P17-T34 Owner-aware frontend request helper.**
  Preserve `dal/owners.build_account_filter` and `useOwnerApi`, but add a
  shared owner-aware request path for imperative frontend fetches so pages
  stop hand-building `owner_id=` query strings. This is the frontend half
  of owner scoping; do not broaden household-only budgets. Prompt:
  `docs/prompts/Phase-17/P17-T34_owner-aware-request-helper.md`.
  Issue: [#37](https://github.com/wileyqe/Sentry-Finance/issues/37).
  Merged: PR [#45](https://github.com/wileyqe/Sentry-Finance/pull/45) (`d256b60`).

- `[v]` **P17-T35 Analytical transaction window module.**
  Protect `dal/flow_aggregation.compute_period_totals`; deepen the smaller
  query-window layer underneath it by centralizing effective-month
  attribution and canonical income/spend SQL fragments for reports,
  budgets, forecasts, and merchant analytics. Prompt:
  `docs/prompts/Phase-17/P17-T35_analytical-transaction-window-module.md`.
  Issue: [#42](https://github.com/wileyqe/Sentry-Finance/issues/42).
  Merged: PR [#48](https://github.com/wileyqe/Sentry-Finance/pull/48) (`5bd345b`).

- `[v]` **P17-T36 Number-trust proof metadata/spec design.**
  Human-in-the-loop design item. Decide what number-trust proof metadata
  becomes declarative while preserving independent Python and Node oracle
  math. Decision: round-then-exact-equal at registry-declared display
  precision; tolerance fuzz dies; `display_precision`/`empty_state`/
  `owner_scope` become declarative; DOM uses default-builder + named
  overrides; binary `audit_stage` with `pending_since` TTL. Split into
  five AFK implementation slices T37–T41. Prompt:
  `docs/prompts/Phase-17/P17-T36_number-trust-proof-spec.md` (Outcomes
  section captures full decision tree).
  Issue: [#39](https://github.com/wileyqe/Sentry-Finance/issues/39).
  Closed by: design + AFK slice fan-out 2026-05-05.

- `[v]` **P17-T37 Number-trust schema fields + validator + backfill.**
  Foundation slice from T36. Add `display_precision`, `empty_state`,
  `owner_scope`, `pending_since` to every registry entry. Validator
  branches on `audit_stage`. No comparator, oracle, or DOM behavior
  change. Backfill ~140 entries with safe defaults + explicit override
  list for non-`household_only` and non-`null` cases. Prompt:
  `docs/prompts/Phase-17/P17-T37_number-trust-schema-fields.md`.
  Issue: [#50](https://github.com/wileyqe/Sentry-Finance/issues/50).
  Blocked by: none. Unblocks T38, T39, T40, T41.
  Closed by: PR [#56](https://github.com/wileyqe/Sentry-Finance/pull/56) on 2026-05-06.

- `[v]` **P17-T38 Number-trust comparator display-precision exact equality.**
  Strip tolerance fuzz. Round both oracle outputs to `display_precision`
  then compare exact. Real Py/Node divergences surfaced by this slice
  become per-divergence bug-fix PRs, not bundled in. Prompt:
  `docs/prompts/Phase-17/P17-T38_number-trust-comparator-display-precision.md`.
  Issue: [#51](https://github.com/wileyqe/Sentry-Finance/issues/51).
  Blocked by: T37.
  Closed by: PR [#57](https://github.com/wileyqe/Sentry-Finance/pull/57) on 2026-05-06.

- `[v]` **P17-T39 Number-trust default DOM builder pilot (`dashboard.kpis`).**
  Build generic `default_dom_builder(entry, api_value, view_state)` and
  named-override registry. Migrate `dashboard.kpis` only to prove the
  pattern. Other surfaces stay hand-coded for T40 to sweep. Prompt:
  `docs/prompts/Phase-17/P17-T39_number-trust-default-dom-builder-pilot.md`.
  Issue: [#52](https://github.com/wileyqe/Sentry-Finance/issues/52).
  Blocked by: T37, T38.
  Closed by: PR [#59](https://github.com/wileyqe/Sentry-Finance/pull/59) on 2026-05-06.

- `[v]` **P17-T40 Number-trust DOM migration sweep.**
  Migrate every non-`dashboard.kpis` surface (~21 surfaces, ~135 entries)
  to default builder or named override. Target: ~2232-line DOM script
  collapses to ~500–700 lines. Orphan-handler check prevents drift. Prompt:
  `docs/prompts/Phase-17/P17-T40_number-trust-dom-migration-sweep.md`.
  Issue: [#53](https://github.com/wileyqe/Sentry-Finance/issues/53).
  Blocked by: T37, T38, T39.
  Completed on branch `codex/p17-t40-number-trust-dom-migration-sweep`:
  non-`dashboard.kpis` entries now dispatch through registry-named builders,
  orphan-builder tests pass, and the full proof gate passed with 616 DOM checks.

- `[v]` **P17-T41 Number-trust `pending_since` TTL enforcement.**
  Validator fails on `registered_pending` entries older than 60 days
  (vs. `dal.clock.reference_date()`). Forcing function to keep the
  pending bucket from becoming a junk drawer. Independent code path —
  can land in parallel with T39 and T40. Prompt:
  `docs/prompts/Phase-17/P17-T41_number-trust-pending-since-ttl.md`.
  Issue: [#54](https://github.com/wileyqe/Sentry-Finance/issues/54).
  Blocked by: T37 only.
  Closed by: PR [#58](https://github.com/wileyqe/Sentry-Finance/pull/58) on 2026-05-06.
  Completed on branch
  `codex/p17-t41-number-trust-pending-since-ttl`: TTL constant and schema
  validation added, operator note recorded, and number-trust proof gate passed.

---

## Deferred And Trigger-Gated

These items stay visible but should not displace the pre-trust-bar list
unless their trigger happens or the user explicitly pulls them forward.

- `[~]` **P14-T05 rental property support.**
  Deferred, likely relevant soon. Add rental income, rental expenses,
  per-property accounts, and security-deposit handling when a real rental
  planning/data signal appears. Prompt:
  `docs/prompts/Phase-14/P14-T05_rental-property-support.md`.
  Issue: [#70](https://github.com/wileyqe/Sentry-Finance/issues/70).

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
