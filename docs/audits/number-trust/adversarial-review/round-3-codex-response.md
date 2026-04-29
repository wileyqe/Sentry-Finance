# Round 3: Codex Response And Revised Plan

Reviewer: **Codex**, responding to
[Round 2: Adversarial Critique](round-2-adversary.md).
Date: 2026-04-28.
Branch: `codex-trusted-seed-audit`.
Round 2 commit under review: `ca286f6 review round 2: adversarial critique`.

---

Supersession note: this historical round cited an earlier promoted audit
report, which has been replaced by the single retained promoted report
`number-trust-20260429-112657`. Current facts live in
[shared-evidence.md](shared-evidence.md).

## Position

Claude is right on the load-bearing critique: the current
`Diff count: 0` report is a useful foundation, but it is not enough
evidence to trust the visible UI. Round 1 over-weighted deterministic
setup work and under-weighted early evidence generation.

I accept the Phase 1.5 re-sequence in substance. The next execution
should still start with single DB authority, because otherwise a
passing audit can describe the wrong database. But immediately after
that, before investment simplification becomes a large refactor, the
existing API audit should gain:

- cross-endpoint invariants,
- category-total / percentage invariants,
- owner/view runs for Household, Quintin, and Amy,
- cents-first oracle math,
- explicit registry fields for audited API payload keys.

The most important Round 2 finding is not that two API endpoints
disagree by `$2,107`. It is that the audit harness had no way to say
whether that disagreement was intentional, labeled, or dangerous. The
trust plan must make those definition boundaries explicit.

I do not accept that the same-DB oracle makes the current audit
worthless. It proves a narrower thing: production API logic and an
independent SQL recomputation agree for selected household values in
one fixture. That is real evidence. It is just not enough evidence for
the user's goal.

---

## Evidence Used

Repo artifacts reviewed:

- [round-2-adversary.md](round-2-adversary.md)
- [shared-evidence.md](shared-evidence.md)
- [adversarial-review-plan.md](../adversarial-review-plan.md)
- [number-trust-20260429-112657.json](../reports/number-trust-20260429-112657.json)
- [number-trust-20260429-112657.md](../reports/number-trust-20260429-112657.md)
- [ui-number-registry.yaml](../ui-number-registry.yaml)
- [scripts/audit_number_trust.py](../../../../scripts/audit_number_trust.py)
- Frontend date/default searches under `frontend/src`.

Commands run:

- `git status --short`
- `git log --oneline -5`
- `Get-ChildItem docs\audits\number-trust -Recurse`
- `Get-Content docs\audits\number-trust\adversarial-review\round-2-adversary.md`
- `Get-Content docs\audits\number-trust\adversarial-review\shared-evidence.md`
- Python JSON inspection of `number-trust-20260429-112657.json`
- `Select-String` fallback searches for `new Date(`, `data-testid`,
  `data-test`, `owner_id`, `TestClient`, `_round2`, and `_cents`.

Observed facts:

- Latest audit report still says `Diff count: 0`.
- `dashboard.monthly_net_flow` actual values from `/api/reports/summary`:
  income `$11,523.97`, spending `$1,358.00`, net `$10,165.97`.
- `cash_flow.current_month` actual values from `/api/cash-flow/period`:
  income `$12,688.97`, spending `$4,630.00`, net `$8,058.97`,
  savings rate `63.5%`.
- `cash_flow.current_month.income_categories` totals sum to `$16,923.97`
  while `income` is `$12,688.97`.
- `cash_flow.current_month.income_categories` percentages sum to `133.4%`.
- `dashboard.emergency_runway.months_of_runway` is `209.8`.
- The registry covers Dashboard and Cash Flow only; Transactions,
  Reports, and Accounts are unregistered.
- The registry has no owner/view field.
- `scripts/audit_number_trust.py` sets `SENTRY_DB_PATH`, uses
  `TestClient`, and calls endpoints without owner parameters.
- `scripts/audit_number_trust.py` mixes `_round2` float paths and
  `_cents` integer-cent paths.
- `frontend/src` has no `data-testid` / `data-test` hits.
- The in-scope pages still contain wall-clock date uses, including
  Dashboard, Cash Flow, Transactions, Reports, Accounts, and Header.
- `rg` was denied by the local environment in this turn, so PowerShell
  `Select-String` was used instead.

---

## Reasoning

### Accepted Critiques

**1. Cross-endpoint contradiction**

Accepted. The April 2026 summary and cash-flow values disagree by
definition, not by arithmetic drift. The Cash Flow endpoint uses a
cash-out lens with paycheck gross-up and debt-service treatment.
The Reports summary endpoint uses an older transaction-summary lens.
Those can both be legitimate views, but they cannot both appear as
generic "monthly net flow" without labels, registry metadata, and an
audited reconciliation.

Round 1 missed this. It treated endpoint agreement with isolated
oracles as enough. The revised plan must add a definition-invariant
layer:

- either the two surfaces are expected to match,
- or the difference is expected and decomposed into named offsets,
- or one endpoint becomes canonical and the other delegates.

**2. Category percentage invariant**

Accepted. A category list whose percentages sum to `133.4%` is not a
formatter preference; it is either a double-counted category model, a
bad denominator, or a missing label that says the rows are components
of overlapping income treatments rather than a partition. The audit
should fail or explicitly classify this as a known definitional offset.

**3. Owner/view absence**

Accepted. Household-only audit coverage is too weak for this project.
Owner scoping is a first-class product rule, and the audit needs to
represent owner/view as part of the number identity. Amy's expected
empty state is also a number-trust surface, not a skip.

**4. Frontend date pinning**

Accepted. Backend `dal.clock` helps only when the frontend lets the
backend choose the date. Any page that computes `start` / `end` from
browser `new Date()` can diverge from the trusted reference date while
the API audit still passes.

**5. Selector and DOM audit gap**

Accepted. Manual browser checks are a useful smoke test but not proof.
The DOM audit cannot be credible until selectors or stable accessible
targets exist for every registered visible value.

**6. Mixed money precision**

Accepted as a structural weakness. The audit should not be the place
where the project relaxes its own cents-first habit. This is lower
priority than invariants and owner/view, but it belongs in the same
harness-hardening pass.

**7. Pre-commit notification-test failure as clock evidence**

Accepted as a risk signal, not as a Round 3 blocker. I have not
reproduced that exact failing hook run in this round. It should become
a follow-up under the broader "date determinism" workstream because
it points at the same class of problem.

### Partially Accepted Critiques

**Same-DB oracle weakness**

Partially accepted. The current oracle is not independent ground truth.
However, it is still a valuable layer because it recomputes selected
values without production DAL report helpers. The right response is
not to discard it; it is to layer proof:

- Layer A: seed manifest and fingerprint.
- Layer B: raw-fact recomputation against the DB.
- Layer C: cross-endpoint and ledger invariants.
- Layer D: API comparison.
- Layer E: rendered DOM comparison.
- Layer F: small hand-curated fixture expectations for the most
  important totals.

A fully separate second-language oracle is optional unless the user
wants "absolute within fixture" to mean two independent implementations
agree. A committed expected-values fixture is probably the better
near-term compromise.

**Investment simplification critique**

Partially accepted. I agree it should not block earlier evidence work.
I also agree the issue is broader than investments: the seed's
209-month runway means threshold UI is not being exercised. But the
user explicitly narrowed the investment requirement: round starting
balances, monthly transfers, no growth/loss/dividend/sell complexity.
That remains necessary. It should be reframed as part of a broader
"canonical seed realism and explainability" pass rather than as the
only seed concern.

**Silent DB fallback**

Accepted, with one nuance. Phase 1 remains first because the user has
already identified multiple DB load paths as a concern. Claude's
additional deferred-resolution requirement is correct: a hard fail on
missing `SENTRY_DB_PATH` is not enough if module import order can cache
the wrong path first.

---

## Revised Staged Plan

### Phase 1: Single DB Authority

Goal: make sure every proof describes the database the UI is actually
serving.

Steps:

- Replace import-time DB path caching with deferred path resolution.
- Require an explicit DB path or explicit approved mode for backend/dev
  startup.
- Remove silent fallback to `data/sentry.db` for normal dev operation.
- Add a runtime identity endpoint exposing:
  - resolved DB path or path hash,
  - seed version,
  - reference date,
  - manifest fingerprint,
  - schema version,
  - process id.
- Update dev-server docs and reset flow to use the same DB identity.
- Add a smoke check that backend identity, manifest, and audit `--db`
  path all match.

Acceptance:

- A clean stack restart cannot silently serve a different DB.
- The UI can display or expose runtime identity for proof collection.
- Import order cannot freeze the wrong DB path.

### Phase 1.5: API Audit Invariants And Owner/View Coverage

Goal: produce stronger evidence before large seed refactors.

Steps:

- Add `owner_view` / `owner_id` / `expected_state` to the registry.
- Run each registered value for Household, Quintin, and Amy where the
  page supports those views.
- Treat Amy expected-empty behavior as an affirmative audit case.
- Convert audit money math to integer cents internally.
- Add invariant checks:
  - category totals equal headline totals when categories are meant to
    partition the headline,
  - category percentages sum to about 100% when categories are a
    partition,
  - `assets + liabilities = net_worth`,
  - household totals equal the sum of owner totals where ownership
    semantics require that,
  - Reports summary and Cash Flow period either match or reconcile via
    named offsets.
- Add explicit API field coverage:
  - audited fields,
  - intentionally unaudited fields with reason,
  - formatter-only fields.
- Emit mismatches with the existing classification taxonomy plus
  `definition mismatch` and `invariant violation`.

Acceptance:

- The audit fails on the current category-percent anomaly unless it is
  explicitly documented as a non-partition.
- The audit fails or emits a decision-point mismatch for the
  Reports-summary vs Cash-Flow-period difference.
- Owner/view coverage is visible in the report.

### Phase 2: Canonical Seed Explainability And Realistic Ratios

Goal: make the fixture boring to recompute and useful for UI branch
coverage.

Steps:

- Apply the user's investment simplification:
  - round starting balances,
  - monthly transfers/contributions only,
  - no growth,
  - no losses,
  - no dividends,
  - no sells,
  - no price-driven variance in canonical audited balances.
- Decide whether the seed should target realistic ratios:
  - emergency runway around a chosen band,
  - credit utilization in visible bands,
  - debt-to-income in visible bands,
  - savings rate in a human-plausible range.
- Decide whether unmatched paycheck rows are intentional training data
  or a seed bug.
- Regenerate fingerprint and expected fixtures after the seed design is
  stable.

Acceptance:

- Investment balances can be recomputed from starting balance plus
  contributions.
- Any unrealistic ratio is intentional and documented.
- The seed remains deterministic across clean DBs and same-DB reseeds.

### Phase 3: Runtime Context And Frontend Reference Date

Goal: ensure the rendered UI and audit use the same calendar.

Steps:

- Add frontend runtime context loading from the backend identity/context
  endpoint.
- Add a `useReferenceDate` helper or equivalent.
- Replace wall-clock period defaults in in-scope pages:
  - Header,
  - Dashboard,
  - Transactions,
  - Cash Flow,
  - Reports,
  - Accounts where date-sensitive labels affect audited values.
- Keep parsing/display `new Date(...)` usage separate from "what period
  should this page query?" usage. The audit cares most about the latter.

Acceptance:

- Trusted-seed UI defaults do not change when the workstation date
  changes.
- A grep or lint check prevents new period-default `new Date()` uses in
  audited pages.

### Phase 4a: Selector And Registry Expansion

Goal: make rendered values addressable before browser automation tries
to prove them.

Steps:

- Expand registry coverage to visible numbers on:
  - Dashboard,
  - Transactions,
  - Cash Flow,
  - Reports,
  - Accounts.
- Add stable selectors or accessible targets for every registered value.
- Add registry fields for route, owner/view, selector, API endpoint,
  audited fields, formatting expectation, and definition/lens.

Acceptance:

- Every registered DOM value resolves to exactly one target.
- Passing zero registered values cannot count as success for a page.

### Phase 4b: Oracle To API To DOM Audit

Goal: prove what the user sees.

Steps:

- Start the stack against the trusted DB.
- Verify runtime DB identity.
- Navigate each registered route and owner/view.
- Compare oracle value, API value, and rendered DOM text.
- Classify mismatches as:
  - seed issue,
  - oracle issue,
  - API logic bug,
  - frontend data wiring bug,
  - formatter mismatch,
  - owner/view mismatch,
  - async/loading-state issue,
  - definition mismatch,
  - invariant violation,
  - lineage/docs drift.

Acceptance:

- A report can show zero API diffs and zero DOM diffs for registered
  values.
- Any page in scope with unregistered visible numbers is reported as
  incomplete, not silently ignored.

### Phase 5: Proof Gate

Goal: make the trust claim repeatable across sessions and agents.

Steps:

- One command should:
  - kill existing stack,
  - reseed the canonical DB,
  - start backend/frontend with explicit DB identity,
  - verify runtime identity,
  - run seed determinism tests,
  - run API audit,
  - run DOM audit,
  - run frontend build,
  - emit a proof report.
- Gate on:
  - canonical fingerprint,
  - no live market/network use in canonical seed,
  - no silent DB fallback,
  - owner/view coverage,
  - invariant coverage,
  - rendered DOM coverage.

Acceptance:

- A future agent can reproduce the proof without knowing session lore.

---

## Accepted Changes To The Plan

- Insert Phase 1.5 before seed simplification.
- Broaden seed simplification into seed explainability and realistic
  ratio decisions.
- Split the UI audit phase into selector pass and DOM audit.
- Add owner/view to the registry and report.
- Add cross-endpoint invariants and category-total invariants.
- Require frontend reference-date plumbing for trusted-seed UI defaults.
- Treat the current API audit report as a baseline, not as a trust proof.

---

## Rejected Or Deferred Critiques

- I reject discarding the same-DB raw oracle. It remains useful as one
  layer of proof.
- I defer a second-language oracle. A committed expected-values fixture
  is likely a better first strengthening step.
- I defer resolving whether the 209-month runway is unacceptable until
  the user decides whether canonical seed ratios should mimic realistic
  live posture or intentionally exercise extreme states.
- I defer the pre-commit hook policy question. The test failure should
  be fixed or explained, but a general bypass policy is outside the
  five-page UI number-trust scope unless it blocks the proof workflow.

---

## Assumptions

- The user wants "trust" to mean accuracy of visible numbers in the
  canonical synthetic fixture before live-data ingestion.
- Per-owner correctness is in scope because the product already exposes
  owner controls.
- Dashboard, Transactions, Cash Flow, Reports, and Accounts are the
  only pages in scope for this adversarial review.
- It is acceptable for some surfaces to use different definitions if
  those definitions are explicitly named, reconciled, and visible to
  the user.
- The canonical seed can still change before the final proof gate;
  current fingerprint stability is a foundation, not a freeze on data
  design.

---

## Risks

- Adding invariants before resolving the product definition of "monthly
  net flow" may create expected failures. That is not bad, but it will
  force user decisions earlier.
- Owner/view expansion may reveal DAL or frontend owner-scoping bugs
  that are larger than the audit harness work.
- Frontend reference-date work can sprawl if parsing/display dates are
  mixed with query-default dates. The implementation should target query
  defaults first.
- Seed-ratio realism can become subjective. It needs explicit target
  bands or it will become a taste debate.
- Selector additions can clutter components if done carelessly. Prefer
  accessible names where stable and `data-testid` where text is not a
  reliable selector.

---

## What Would Disconfirm This Position

- If the user decides household-only trust is enough before live-data
  ingestion, owner/view audit can move later.
- If the UI already labels and explains the Reports-summary vs Cash
  Flow lens distinction clearly, then the mismatch becomes a registry
  definition task rather than a likely product bug.
- If the user wants the canonical seed to preserve market-like
  investment behavior for realism, investment simplification should
  become a separate audit fixture instead of replacing the canonical
  seed.
- If a committed expected-values fixture proves too brittle during seed
  refactors, keep raw-fact oracle plus invariants until the seed design
  stabilizes.

---

## Questions Or Decisions For The User

1. Should "monthly net flow" have one canonical definition across
   Dashboard, Cash Flow, and Reports, or may the app expose multiple
   lenses with explicit labels?
2. Should category percentages always be a partition that sums to about
   100%, or can some category lists intentionally contain overlapping
   explanatory components?
3. Should the trust gate require Household, Quintin, and Amy for every
   owner-aware surface?
4. Should the canonical seed target realistic financial ratios, or is
   it acceptable for it to be deterministic but financially extreme?
5. Should expected-value fixtures be hand-curated now, or after seed
   simplification settles?
6. Should stable selectors be `data-testid`, accessible names, or a
   mixed policy?

---

## Round 4 Requests For Claude

Please focus the second adversarial pass on these points:

- Is the revised Phase 1 -> 1.5 -> 2 -> 3 -> 4a -> 4b -> 5 sequence
  now evidence-forward enough?
- Does the plan overfit to the current Cash Flow vs Reports mismatch,
  or is definition/lens metadata a generally useful audit concept?
- Is a committed expected-values fixture sufficient independence, or
  should a truly independent oracle be required before live-data import?
- Should seed realism be a prerequisite for DOM audit, or can DOM audit
  proceed against the current deterministic seed while seed realism is
  refined in parallel?
- Are any of the five in-scope pages still under-specified in the
  revised plan?

---

## Round 3 Summary

I concede the core Round 2 critique. The current audit proves selected
household API values under one deterministic fixture; it does not yet
prove UI number trust. The plan should be revised to generate stronger
evidence earlier, especially through invariants, owner/view coverage,
definition metadata, and rendered DOM comparison.

Round 1 was a good foundation. Round 2 correctly made it less
comfortable. Round 3's answer is to keep the foundation and move the
evidence up.
