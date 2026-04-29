# Adversarial Review Plan For UI Number Trust

Post-review decisions are recorded in
[implementation-decisions.md](implementation-decisions.md). The accepted
investment-seed direction is now detailed in
[investment-simplification-plan.md](investment-simplification-plan.md):
the canonical trusted seed remains the single fixture, and investments
are simplified to round starting balances plus monthly transfers only.

## Adversarial Review Instructions

Run this as a five-round adversarial review before expanding the number-trust work.

Participants:

- Round 1: Codex is the initial author and current-state assessor.
- Round 2: A second model or agent is the adversarial reviewer.
- Round 3: Codex responds to the critique with a revised plan, concessions, rejected critiques, and new evidence requests.
- Round 4: The second model or agent provides a second adversarial review of the revised plan, focusing on remaining blind spots and decision points.
- Round 5: Codex synthesizes the full exchange into areas of agreement, disagreements, user decision points, and a final staged execution plan.

Review goal:

- Assess the overarching goal, current state, and proposed action plan for proving UI number accuracy before real financial data is trusted.
- The review should challenge whether the proposed plan actually proves accuracy, whether the seed is trustworthy enough, and whether the implementation order reduces risk.

Scope:

- Dashboard
- Transactions
- Cash Flow
- Reports
- Accounts

Everything is on the table and up for debate:

- Canonical seed design
- DB startup model
- Audit scope
- UI selectors and rendered-value assertions
- Owner/view handling
- Reference-date handling
- Data lineage and docs
- Test gates
- Whether this plan is sufficient to prove trust

Reasoning requirement for every round:

- State the position clearly.
- Cite evidence used from the repo, running app, audit reports, or tests.
- List assumptions.
- Explain risks and tradeoffs.
- Name what evidence would disconfirm the position.

Round outputs:

- Round 1: current-state assessment, proposed staged plan, known concerns, and reasoning.
- Round 2: adversarial critique, alternative plan, challenged assumptions, and reasoning.
- Round 3: response to critique, revised plan, accepted changes, rejected changes, evidence gaps, and reasoning.
- Round 4: second adversarial critique, remaining disagreements, alternative sequencing, user decision points, and reasoning.
- Round 5: final synthesis with areas of agreement, unresolved disagreements, decision points for the user, and a final staged execution plan.

At the end of Round 5, produce:

- Areas of agreement.
- Areas of disagreement.
- Decision points for the user.
- Final staged plan with execution order and concrete steps.

## Exchange Of Information

Each round must create or update a durable markdown artifact under `docs/audits/number-trust/adversarial-review/`.

Recommended files:

- `round-1-codex.md`
- `round-2-adversary.md`
- `round-3-codex-response.md`
- `round-4-adversary-second-pass.md`
- `round-5-final-synthesis.md`
- `shared-evidence.md`

`shared-evidence.md` should be the common input ledger. Every participant should add concise evidence references before making claims:

- repo paths inspected,
- commands run,
- audit report paths and diff counts,
- browser routes and visible values checked,
- seed fingerprint and manifest facts,
- assumptions inherited from prior rounds,
- open questions for the user.

Each round file should include these sections:

- Position.
- Evidence used.
- Reasoning.
- Assumptions.
- Risks.
- What would disconfirm this position.
- Proposed changes to the staged plan.
- Questions or decisions for the user.

Information exchange rules:

- Do not rely on memory alone when a fact can be cited from the repo, audit output, or browser state.
- If a participant disagrees with a prior round, quote or reference the exact claim being challenged.
- If new evidence changes the plan, update `shared-evidence.md` and state the impact.
- Keep claims scoped to Dashboard, Transactions, Cash Flow, Reports, and Accounts unless explicitly identifying out-of-scope risk.
- Separate observed facts from recommendations.
- Preserve unresolved disagreements instead of smoothing them over.

Commit instructions after every round:

- At the end of each completed round, commit that round's markdown artifacts to the current branch.
- Keep commits small and labeled for easy review.
- Use these commit message formats:
  - `review round 1: codex current-state plan`
  - `review round 2: adversarial critique`
  - `review round 3: codex revised plan`
  - `review round 4: second adversarial critique`
  - `review round 5: final synthesis`
- If a round includes supporting evidence updates, include them in the same round commit.
- Do not mix implementation code changes into round-review commits unless the user explicitly asks for a combined commit.

## Round 1 Current-State Assessment

The project now has a canonical trusted synthetic seed and a first API-level number-trust audit. The seed is deterministic, ends at 2026-04-27, uses 2026-04-28 as the trusted reference date, avoids live market/network inputs for synthetic prices and metadata, and writes a manifest with a canonical database fingerprint.

Current high-confidence evidence:

- Canonical seed version: `trusted-2026-04-27-v1`.
- Canonical DB fingerprint: `f061229325d607ffd06e8ea22dee2831a2db18bd91f140c16c88982548c8b9ec`.
- Latest audit report: `docs/audits/number-trust/reports/number-trust-20260429-124043.md`.
- Latest API audit diff count: `0`.
- Full backend test suite previously passed after the trusted-seed work.
- Browser checks showed Dashboard and Cash Flow can render the audited values when the backend is started against the trusted DB and the correct owner/view is selected.

Known concerns:

- Resolved after the review: backend startup and default DAL access now fail
  loudly if `SENTRY_DB_PATH` is missing, unless a test/script passes an
  explicit `db_path`.
- Cash Flow rendered a per-owner slice while the first audit checked household values; owner/view state must be part of every audited number identity.
- Some frontend period/date logic still uses browser time instead of backend trusted reference date.
- The current audit proves selected API values and spot-checked rendered values, not every visible number.
- The investment seed simplification landed after this Round 1 text was first
  written. Current canonical investment balances now come from round starting
  balances plus deterministic monthly transfers only; market realism remains
  deferred to live-data or separately audited work.

Round 1 position:

The next work should reduce sources of ambiguity before expanding coverage. The fastest path to real trust is not "audit more numbers immediately"; it is first to make the seed, runtime DB, reference date, owner/view state, and investment assumptions boring enough that a mismatch has a small search space.

Disconfirming evidence:

- If production/live import needs require the current investment simulation shape to remain in the canonical seed, investment simplification should become a separate fixture instead of replacing the canonical seed.
- If legitimate dev workflows require a fallback DB, they must be redesigned
  around an explicit DB path or mode rather than reviving silent fallback.

## Staged Execution Plan

### Phase 1: Single DB Authority

Goal: eliminate accidental DB split-brain.

- Backend and dev startup must use one explicit DB path.
- Remove silent fallback DB access for normal backend/dev operation.
- Add a runtime identity or health response exposing:
  - resolved DB identity,
  - trusted seed version,
  - trusted reference date,
  - trusted manifest fingerprint,
  - live DB fingerprint,
  - live-vs-manifest match status.
- Update dev-server docs, launch configs, and commands so all normal development uses the same canonical trusted DB path.
- Add tests or smoke checks proving the backend fails loudly or reports unhealthy when no DB path is configured.

Acceptance criteria:

- A clean stack restart shows exactly one backend, one frontend, and one trusted DB identity.
- The runtime identity live fingerprint matches `app_settings.trusted_seed_manifest`.
- A backend started without an approved DB path cannot silently serve UI data from any fallback database.

### Phase 2: Simplify Investment Seed

Goal: remove market behavior from the canonical audit fixture.

- Set every investment account to a round starting number.
- Model investment activity as deterministic monthly transfers/contributions only.
- Remove canonical-seed growth, losses, dividends, sells, live/fallback price variance, and market-price-driven account changes.
- Keep investment-related tables populated only as needed for UI shape and lineage, with values traceable to starting balance plus contributions.
- Regenerate the canonical seed fingerprint.
- Update trusted seed tests, manifest expectations, audit reports, and docs.

Acceptance criteria:

- Investment balances can be recomputed from round starting balances plus monthly contributions.
- No audited number depends on market price movement, dividends, sells, or synthetic return assumptions.
- The seed remains deterministic on clean DB and same-DB reseed.

### Phase 3: Runtime Context And Owner/View Certainty

Goal: make UI state part of the proof.

- Add a backend runtime context endpoint that returns trusted reference date, seed version, manifest fingerprint, and DB identity.
- Frontend trusted-seed surfaces consume backend reference date instead of browser `new Date()` for:
  - Header date,
  - Dashboard month defaults,
  - report reference periods,
  - Cash Flow period defaults,
  - spending comparison reference date.
- Extend the audit registry so every number declares owner/view state:
  - household,
  - Quintin,
  - Amy.
- Make owner/view controls accessible by stable names even in compact display.

Acceptance criteria:

- Browser date no longer changes trusted-seed periods.
- Audit entries cannot omit owner/view state.
- Browser automation can reliably select Household, Quintin, and Amy.

### Phase 4: API And Rendered UI Audit

Goal: prove what the user sees, not only what APIs return.

- Extend the audit harness from oracle-to-API to oracle-to-API-to-DOM.
- For each registry item, declare:
  - route,
  - owner/view,
  - API endpoint,
  - independent oracle,
  - rendered selector or accessible target,
  - formatter expectation.
- Cover visible numbers on:
  - Dashboard,
  - Transactions,
  - Cash Flow,
  - Reports,
  - Accounts.
- Classify mismatches as:
  - seed issue,
  - oracle issue,
  - API logic bug,
  - frontend data wiring bug,
  - formatter mismatch,
  - owner/view mismatch,
  - async/loading-state issue,
  - lineage/docs drift.

Acceptance criteria:

- Registered numbers pass raw oracle, API comparison, and rendered DOM comparison.
- Audit reports include expected value, API value, rendered value, owner/view, route, selector, and classification.

### Phase 5: Proof Gates

Goal: make trust reproducible across sessions and agents.

- Add one canonical proof command that:
  - kills existing dev stack,
  - reseeds the canonical DB,
  - starts backend and frontend with the approved DB path,
  - verifies runtime DB identity,
  - runs API audit,
  - runs browser audit,
  - writes a zero-diff proof report.
- Gate on:
  - canonical seed fingerprint,
  - no live market/network use,
  - backend DB identity,
  - frontend build,
  - backend tests,
  - API audit,
  - browser audit.

Acceptance criteria:

- A fresh session can reproduce the same proof report from the canonical command.
- Any DB-path mismatch, owner/view mismatch, date mismatch, or rendered-value mismatch fails the proof run.

## Certainty Model

- Low certainty: a number appears plausible but has no independent oracle.
- Medium certainty: a number has tests or API checks, but not full independent oracle coverage.
- High certainty: deterministic seed, independent oracle, API comparison, and browser spot check all pass.
- Absolute within synthetic scope: deterministic seed fingerprint, declared lineage, independent oracle, API parity, rendered DOM parity, owner/view/date state locked, clean-stack reproduction, and zero-diff proof report.

Absolute does not mean all future live-data ingestion is correct. It means the registered synthetic fixture and registered UI states are fully proved under the declared constraints.

## Round 1 Decision Points For Later Review

- Resolved: canonical backend/dev startup hard-fails without `SENTRY_DB_PATH`;
  `SENTRY_DB_MODE` is a label/gate input, not a DB resolver.
- Should investment simplification replace the canonical seed entirely, or should a separate no-market audit fixture exist?
- Should browser audit require stable test IDs, accessible labels, or both?
- Should reports store all proof artifacts, or only the latest canonical report?
- Should owner-specific UI accuracy be required before expanding beyond Dashboard and Cash Flow?
