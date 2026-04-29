# Round 5: Final Synthesis And Execution Plan

Synthesizer: **Codex**, final round of the five-round adversarial
review.
Date: 2026-04-28.
Branch: `codex-trusted-seed-audit`.
Inputs:

- Round 1: embedded in [adversarial-review-plan.md](../adversarial-review-plan.md)
- Round 2: [round-2-adversary.md](round-2-adversary.md)
- Round 3: [round-3-codex-response.md](round-3-codex-response.md)
- Round 4: [round-4-adversary-second-pass.md](round-4-adversary-second-pass.md)
- Shared evidence: [shared-evidence.md](shared-evidence.md)

Post-review user decisions are recorded in
[implementation-decisions.md](../implementation-decisions.md). Those
decisions supersede the weaker Round 5 recommendation to defer a
second-language oracle: the implementation should use the stronger
independent-oracle path.

---

## Executive Position

The project has a credible foundation for number trust, but it is not
ready to claim visible UI accuracy across Dashboard, Transactions,
Cash Flow, Reports, and Accounts.

Current certainty:

- **Moderate** for selected household-level API values on Dashboard
  and Cash Flow, under the canonical trusted seed.
- **Low** for rendered UI values, because there is no automated DOM
  audit and the frontend still derives many query periods from the
  browser clock.
- **Low** for owner-specific views, because the audit currently runs
  household-only.
- **Low** for Transactions, Reports, and Accounts, because they have
  no meaningful registered audit coverage yet.
- **Not claimed** for Investments, even though investment seed data
  affects in-scope aggregate numbers.

The next implementation should not begin with a broad refactor. It
should begin by tightening the proof surface:

1. One DB authority.
2. Canonical category vocabulary and canonical financial definitions.
3. Early API invariants and owner/view coverage.
4. Then seed simplification, frontend reference dates, selectors, DOM
   audit, and a proof gate.

The central correction from the adversarial review is this: the
`Diff count: 0` report is a baseline, not a trust certificate. It
proves selected API values agree with a raw SQL recomputation. It does
not prove all visible numbers are accurate.

---

## Certainty Model

Use these terms going forward:

| Level | Meaning | Current status |
|---|---|---|
| Baseline consistency | Seed exists, API returns values, raw recomputation agrees for selected fields | Achieved for current registered Dashboard/Cash Flow household API values |
| High certainty | Registered raw facts, API responses, invariants, owner/view states, and rendered DOM all agree under the canonical seed | Not yet achieved |
| Absolute within fixture | Every registered visible value on the scoped pages is traced to canonical seed facts, independently recomputed, checked through API and DOM, and reproducible by one proof command | Target state for this work |
| Live-data trust | Real-data ingestion, validation, and imported facts have the same proof guarantees | Out of scope until synthetic proof is complete |

"Absolute" here never means "all future live data is guaranteed
correct." It means absolute within the canonical synthetic fixture and
registered UI states.

---

## Areas Of Agreement

The rounds converged on these points:

- The canonical trusted seed is valuable and should remain the base
  fixture for this work.
- The current audit report is useful but too narrow.
- Single DB authority must come before trust claims.
- Owner/view must be part of every audited number identity.
- The frontend must consume the trusted reference date for trusted
  seed UI defaults.
- The audit must add invariants, not only expected-vs-actual field
  comparisons.
- Audit money math should be cents-first.
- Rendered DOM values must be audited, not only API responses.
- Stable selectors or accessible targets are required before DOM audit.
- The Reports-vs-Cash-Flow mismatch is not acceptable as an unexplained
  user-facing difference.
- The proof gate should be reproducible by a future agent without
  session memory.

---

## Areas Still Debatable

These are not blockers to starting implementation, but they shape the
later sessions:

- Whether Investments should join the audit scope now or remain
  explicitly out of scope.
- What realistic financial ratio targets the canonical seed should
  use.
- How granular the expected-values fixture should be.
- Whether dev endpoints should be disabled in proof mode or merely
  asserted unreachable by the proof command.
- How much proof history should be committed versus generated locally.

My recommendations are below.

---

## Broad Decisions First

### Decision 1: What Is The Trust Contract?

Recommendation:

Adopt this contract for the current work:

> The app is trusted when every registered visible number on Dashboard,
> Transactions, Cash Flow, Reports, and Accounts matches canonical
> synthetic seed facts through oracle, API, and DOM checks for every
> registered owner/view state.

Reasoning:

- It is precise enough to test.
- It avoids claiming more than the synthetic fixture can prove.
- It matches the user's real question: "Where does this number come
  from, and is it accurate?"

Downside:

- It creates a registry maintenance obligation. New visible numbers
  on scoped pages become audit work, not casual UI additions.

Decision:

- **Recommended: accept.**

### Decision 2: Should There Be One Canonical Cash-Flow Definition?

Recommendation:

Use `dal.flow_aggregation.compute_period_totals` as the canonical
cash-out lens for monthly income, spending, net, savings rate, debt
service, and debt movement across Dashboard, Cash Flow, and Reports.
Migrate `dal/reports/spending.py::get_period_summary` to consume it.

Reasoning:

- `dal/flow_aggregation.py` already documents this as the shared
  aggregator.
- Cash Flow and Sankey already use it.
- The current Reports summary mismatch appears to be unfinished
  migration, not a deliberate second lens.
- One canonical definition reduces user confusion and makes invariants
  straightforward.

Downside:

- Some existing Dashboard/Reports numbers will change.
- If the app still needs a legacy posting-date/blacklist view, it must
  be reintroduced as an explicitly named view, not hidden behind the
  same "monthly net flow" language.

Decision:

- **Recommended: accept and migrate.**

### Decision 3: Should Investments Enter This Audit Scope?

Recommendation:

Do **not** add the Investments page to this trust phase. Keep the page
scope exactly as the user narrowed it: Dashboard, Transactions, Cash
Flow, Reports, Accounts.

However, do audit investment-derived values that appear on those pages:

- Dashboard net worth investment component.
- Accounts investment/retirement account balances.
- Transactions investment contributions/transfers/dividends if they
  remain visible on Transactions or affect Cash Flow.
- Reports totals that include investment-account balances or flows.

Reasoning:

- This honors the explicit narrowed scope.
- It prevents a large side quest into holdings, lots, allocation,
  performance, and tax buckets.
- It still covers the aggregate numbers that would be wrong if
  investment seeding is wrong.

Downside:

- The Investments page itself remains outside the trust claim.
- If Phase 2 rewrites holdings/lots/allocation data, those views may
  drift without this audit catching it.

Mitigation:

- Add a documented follow-on: "Investments page trust audit" after the
  five-page trust gate, or sooner if the user expands scope.
- During Phase 2, scope the investment simplification to the canonical
  balances and activity needed by the five in-scope pages. Avoid broad
  Investments-page behavior changes unless explicitly accepted.

Decision:

- **Recommended: keep Investments page out of scope, but audit
  investment-derived values on in-scope pages.**

### Decision 4: How Independent Must The Oracle Be?

Recommendation:

Use layered proof, including a second-language independent oracle:

1. Seed manifest and live fingerprint.
2. Independent second-language oracle, preferably TypeScript/Node,
   reading SQLite facts directly and importing no production DAL/API/UI
   code.
3. Python raw SQL oracle, independent from production DAL report
   helpers.
4. Cross-endpoint and ledger invariants.
5. Public API comparison.
6. Rendered DOM comparison.
7. Committed expected-values fixture with representative spot checks.

Reasoning:

- The current raw SQL oracle is useful but insufficient.
- A second-language oracle reduces shared implementation failure with
  the Python backend and is the stronger proof for pre-live-data trust.
- Representative row-level spot checks make the fixture harder to
  accidentally regenerate over a bad seed.

Downside:

- This adds a second audit runtime and dependency surface.
- Expected fixtures become another artifact to maintain when the seed
  changes.
- Implementation will take longer than a Python-only fixture strategy.

Decision:

- **User decision: use the stronger independent-oracle approach. Build
  the second-language oracle as part of the proof system.**

### Decision 5: What Should The Canonical Seed Optimize For?

Recommendation:

Optimize for determinism, explainability, and branch coverage.

Seed targets:

- Investment accounts use round starting balances and monthly
  contributions only.
- No investment growth, losses, dividends, sells, or price-driven
  variance in canonical audited balances.
- Emergency runway should be realistic enough to exercise UI states,
  preferably in a target band chosen by the user.
- Credit utilization, savings rate, debt-to-income, and cash-flow
  trends should exercise meaningful UI branches.

Reasoning:

- The seed is a proof instrument, not a market simulator.
- The current 209-month runway does not exercise warning/threshold
  behavior.
- Simple investment math makes aggregate balances hand-auditable.

Downside:

- Less market realism.
- Seed churn will change fingerprints and expected values.
- Choosing "realistic" ratios can become subjective unless target
  bands are explicit.

Decision:

- **Recommended: accept deterministic and explainable over market-like.
  Pick ratio bands before Phase 2 implementation.**

### Decision 6: How Strict Should Runtime Safety Be?

Recommendation:

Use explicit DB mode and path:

- Require `SENTRY_DB_PATH` for backend/dev startup.
- Add `SENTRY_DB_MODE=trusted|live|dev` or equivalent.
- Defer DB path resolution so import order cannot freeze the wrong DB.
- Runtime identity endpoint exposes both manifest fingerprint and live
  recomputed fingerprint.
- Gate `/api/dev/*` endpoints to dev/trusted reset mode only, and have
  proof mode reject or verify them unreachable.

Reasoning:

- The user already identified multiple DB load paths as a concern.
- Manifest-only identity does not detect post-seed DB mutation.
- Dev reset endpoints are useful, but they should not be reachable in
  proof mode.

Downside:

- More friction for casual dev startup.
- Live fingerprint computation has runtime cost unless cached or
  on-demand.

Decision:

- **Recommended: accept strict mode/path/fingerprint rules for proof
  and trusted-seed work.**

---

## Revised Specific Decisions

| Question | Recommendation | Reasoning | Downside |
|---|---|---|---|
| Should category percentages fail when they do not sum to about 100%? | Yes, when the category list is declared a partition. Use `overlapping_components` only when intentional. | Current `133.4%` income category sum is not trustworthy as a partition. | Requires registry metadata for category list semantics. |
| Is `Paycheck (no deposit matched)` allowed? | Treat as a seed issue unless explicitly retained as a single documented training case. | It currently contributes to confusing overlapping income totals. | Removing it may reduce coverage of unmatched-paycheck behavior. |
| Should per-owner accuracy be required? | Yes for owner-aware surfaces: Household, Quintin, Amy. | Owner scoping is a product invariant. Amy empty states are shipped behavior. | Roughly triples audit matrix. |
| Stable selector policy? | Mixed: prefer accessible names/roles; use `data-testid` for dense numeric values, chart labels, repeated rows, and formatter-sensitive text. | Keeps UI accessible while giving automation stable handles. | Adds UI attributes and registry upkeep. |
| Proof reports retention? | Commit the latest promoted canonical proof report; ignore or generate timestamped local reports unless promoted. | Keeps repo readable while preserving the current trusted baseline. | Less historical run detail in git. |
| Dev reset endpoint? | Gate by mode and verify in proof gate. | Prevents proof from running against a mutable dev surface. | Slightly more setup friction. |
| Pre-commit notification failure? | Triage under date-determinism work. Do not make bypass policy part of the trust proof unless it blocks implementation. | It is likely the same calendar class of risk. | It may interrupt commits again if left unresolved. |
| Lens vocabulary? | Controlled enum in registry header. | Enables invariants to know when two surfaces share a definition. | Enum must evolve with new product concepts. |

---

## Final Staged Execution Plan

### Phase 0: Audit Vocabulary And Registry Semantics

Goal: remove avoidable audit drift before expanding coverage.

Steps:

- Replace local category-set copies in `scripts/audit_number_trust.py`
  with imports from `dal/category_classifications.py`.
- Keep oracle SQL independent from production report helpers, but share
  canonical vocabulary.
- Add a small regression test that protects audit/category vocabulary
  from local-copy drift.
- Define registry semantics:
  - owner/view required,
  - field coverage required,
  - lens required from controlled enum,
  - category list semantics required (`partition` vs
    `overlapping_components`),
  - DOM target optional until Phase 4a.

Acceptance:

- Audit has no local category vocabulary copies that can drift from
  canonical DAL definitions.
- Registry can distinguish a partition from explanatory overlapping
  components.

### Phase 1: Single DB Authority

Goal: prove the backend, audit, and UI are talking to the same trusted
database.

Steps:

- Move DB path resolution from import-time constant to deferred runtime
  helper.
- Require explicit DB path for normal backend/dev startup, or require
  explicit mode for any fallback.
- Add runtime identity endpoint exposing:
  - resolved DB path or stable path hash,
  - DB mode,
  - process id,
  - schema version,
  - seed version,
  - reference date,
  - manifest fingerprint,
  - live recomputed fingerprint,
  - fingerprint match boolean.
- Gate `/api/dev/*` endpoints by mode, or make proof mode verify they
  are unreachable.
- Update dev-server docs and commands.

Acceptance:

- No silent `data/sentry.db` fallback in proof/trusted mode.
- A post-seed mutation makes live fingerprint differ from manifest
  fingerprint and fails proof.
- Backend startup and audit report name the same DB identity.

### Phase 1.5: API Truth, Invariants, Owner/View

Goal: generate stronger evidence before larger seed or browser work.

Steps:

- Migrate `dal/reports/spending.py::get_period_summary` to
  `compute_period_totals`.
- Update `/api/reports/summary` consumers as needed.
- Add registry entries for Reports headline values immediately, so the
  migration is audited.
- Add registry entries for Accounts headline balances immediately:
  - account displayed balance,
  - active cash account sum,
  - relationship to Dashboard liquid balance.
- Add owner/view to every registered audit entry:
  - Household,
  - Quintin,
  - Amy where the surface supports it.
- Convert audit money math to integer cents internally.
- Add invariant classes:
  - category totals vs headline totals,
  - category percentages,
  - net worth equation,
  - owner sum vs household where applicable,
  - Reports summary vs Cash Flow period convergence,
  - field coverage (audited, intentionally unaudited, formatter-only).
- Classify mismatches as:
  - seed issue,
  - oracle issue,
  - API logic bug,
  - frontend wiring bug,
  - formatter mismatch,
  - owner/view mismatch,
  - async state issue,
  - definition mismatch,
  - invariant violation,
  - lineage/docs drift.

Acceptance:

- The current Reports-vs-Cash-Flow mismatch either converges or fails
  as a migration bug.
- The `133.4%` income category anomaly is fixed, explicitly modeled as
  overlapping, or fails as an invariant violation.
- Household, Quintin, and Amy appear in the report for owner-aware
  values.

### Phase 2: Canonical Seed Explainability

Goal: make seed facts hand-auditable and suited to the five-page trust
scope.

Steps:

- Simplify investment seed for in-scope aggregates:
  - round starting balances,
  - deterministic monthly contributions/transfers,
  - no growth,
  - no losses,
  - no dividends,
  - no sells,
  - no price-driven audited balances.
- Decide and document financial ratio targets:
  - emergency runway,
  - credit utilization,
  - savings rate,
  - debt-to-income,
  - investment contribution cadence.
- Remove or explicitly document unmatched-paycheck artifacts.
- Regenerate canonical seed fingerprint.
- Update trusted seed tests, manifest, expected-values fixture, audit
  report, and docs.

Acceptance:

- Investment-derived balances on in-scope pages are recomputable from
  starting balances plus contributions.
- Any unrealistic seed ratio is documented as intentional.
- Seed determinism tests pass against clean DBs and same-DB reseed.

### Phase 3: Runtime Context And Frontend Reference Date

Goal: align UI query periods with the trusted reference date.

Steps:

- Add frontend runtime context fetch from backend identity/context.
- Add `useReferenceDate` or equivalent.
- Replace wall-clock period defaults for the five in-scope pages and
  Header:
  - Dashboard,
  - Transactions,
  - Cash Flow,
  - Reports,
  - Accounts where query defaults or freshness labels affect audited
    values.
- Keep date parsing/display utilities separate from query-default date
  selection.
- Triage the notification producer date test failure under this phase.

Acceptance:

- Trusted-seed UI defaults remain stable if the workstation date changes.
- The audit can run on a future calendar day and still compare against
  the trusted reference date.

### Phase 4a: Registry Expansion And Selectors

Goal: make every in-scope visible number addressable.

Steps:

- Expand registry coverage for:
  - Dashboard,
  - Transactions,
  - Cash Flow,
  - Reports,
  - Accounts.
- For every visible number, record:
  - route,
  - owner/view,
  - API endpoint,
  - oracle,
  - audited fields,
  - formatter expectation,
  - definition/lens enum,
  - category semantics where relevant,
  - DOM selector or accessible target.
- Add selectors or accessible names:
  - prefer role/name for stable single controls,
  - use `data-testid` for repeated numeric values, charts, tables, and
    compact cells.

Acceptance:

- Every registered DOM value resolves to exactly one target.
- Any visible number on a scoped page that is not registered is reported
  as incomplete.

### Phase 4b: Oracle To API To DOM Audit

Goal: prove what the user sees.

Steps:

- Start the stack against the trusted DB.
- Verify runtime DB identity and live fingerprint.
- Navigate registered routes.
- Switch registered owner/view states.
- Compare:
  - oracle value,
  - API value,
  - rendered DOM text,
  - formatter expectation.
- Emit JSON/Markdown report with:
  - expected,
  - API,
  - DOM,
  - owner/view,
  - route,
  - selector,
  - mismatch classification.

Acceptance:

- Registered values pass oracle/API/DOM comparison.
- Any missing selector, duplicated selector, async stale value, or
  formatter drift is reported as a proof failure.

### Phase 5: One-Command Proof Gate

Goal: make the trust proof reproducible across sessions.

Steps:

- Add one command that:
  - stops existing backend/frontend processes,
  - reseeds the canonical trusted DB,
  - starts backend/frontend with explicit DB identity,
  - verifies runtime identity,
  - verifies live fingerprint equals manifest fingerprint,
  - verifies dev endpoints are gated or unreachable in proof mode,
  - runs trusted seed tests,
  - runs backend regression slice,
  - runs frontend build,
  - runs API audit,
  - runs DOM audit,
  - writes a promoted proof report.
- Commit only promoted proof artifacts; keep transient run reports
  generated/ignored.

Acceptance:

- A new agent can run one command and reproduce the trust result.
- The proof report says exactly which pages, owners, values, and fields
  are trusted.
- A page or value omitted from the registry is explicitly not trusted.

---

## Session-Sized Execution Order

### Session 1: Authority And Vocabulary

Deliver:

- Phase 0 complete.
- Phase 1 DB identity endpoint and explicit path/mode behavior.
- Dev endpoint gating decision implemented.
- Tests for DB identity and vocabulary drift.

Why first:

- Prevents proving the wrong database.
- Removes audit-definition drift before adding more checks.

### Session 2: Canonical API Definitions And Invariants

Deliver:

- `get_period_summary` migrated to `compute_period_totals`.
- Reports and Accounts preliminary registry entries.
- Owner/view support in API audit.
- Cents-first audit math.
- Invariant report.

Why second:

- This resolves the most concrete mismatch before seed churn.

### Session 3: Seed Simplification And Expected Fixtures

Deliver:

- Investment aggregate simplification for in-scope pages.
- Realistic-ratio decisions applied.
- Fingerprint regenerated.
- Expected-values fixture added.
- Seed determinism and audit pass.

Why third:

- After canonical definitions are stable, seed values can change
  without chasing moving formulas.

### Session 4: Frontend Reference Date And Selectors

Deliver:

- Runtime context consumed by frontend.
- Trusted reference date used for query defaults.
- Registry expanded across five pages.
- Stable selectors/accessibility targets added.

Why fourth:

- DOM audit needs stable dates and stable targets.

### Session 5: DOM Audit And Proof Gate

Deliver:

- Browser audit harness.
- One-command proof workflow.
- Promoted zero-diff proof report.
- Documentation of trusted and untrusted surfaces.

Why fifth:

- This is the final proof layer, not the place to discover unresolved
  API definition disputes.

---

## Final User Decision Points

### Recommended Decisions To Accept Now

1. **Trust contract:** absolute within canonical synthetic fixture and
   registered UI states only.
2. **Canonical flow definition:** migrate Reports summary to
   `compute_period_totals`.
3. **Investments scope:** keep Investments page out of this phase, but
   audit investment-derived values on Dashboard/Reports/Accounts/
   Transactions/Cash Flow.
4. **Oracle strategy:** use the stronger independent-oracle approach.
   Build a second-language oracle, preferably TypeScript/Node, so the
   proof is not only another Python recomputation.
5. **Runtime safety:** require explicit DB path/mode, live fingerprint,
   and gated dev endpoints.
6. **Owner scope:** require Household, Quintin, and Amy where the UI
   supports them.
7. **Selectors:** use a mixed accessible-name plus `data-testid` policy.

### Decisions Needing User Input Before Phase 2

1. **Realistic seed bands:** choose target bands for emergency runway,
   savings rate, debt-to-income, and credit utilization.
2. **Unmatched paycheck artifact:** remove it from canonical seed or
   retain one documented training case.
3. **Proof report retention:** confirm "latest promoted proof report in
   repo, transient timestamped reports generated/ignored."

### Decisions That Can Wait

1. Whether to add the Investments page to the trust audit after the
   five-page scope is complete.
2. Whether to add a formal pre-commit bypass policy.

---

## What Implementation Should Not Do

- Do not expand the trust claim to pages outside Dashboard,
  Transactions, Cash Flow, Reports, and Accounts.
- Do not keep two unlabeled monthly flow definitions.
- Do not use manifest fingerprint alone as proof that the DB is still
  canonical.
- Do not let browser `new Date()` choose trusted-seed query periods.
- Do not count passing zero registered values as page coverage.
- Do not let seed realism become an open-ended aesthetic debate; pick
  target bands.

---

## Final Recommendation

Proceed with implementation in the staged order above.

The first implementation milestone should be:

> Phase 0 + Phase 1 + enough of Phase 1.5 to migrate Reports summary
> to `compute_period_totals`, add the first invariants, and rerun the
> API audit.

That milestone will immediately answer the biggest uncovered question:
whether the app has one trustworthy definition of monthly income,
spending, and net flow. Once that is true, the later work becomes much
more mechanical: seed simplification, frontend date alignment,
selectors, DOM audit, and proof gate.

This is the most conservative path that still moves quickly. It does
not try to prove everything at once. It first makes the proof system
capable of catching the mistakes the review already found.
