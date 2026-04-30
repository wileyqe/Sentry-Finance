# Number Trust Implementation Decisions

These decisions were provided by the user after the five-round
adversarial review and supersede any weaker recommendations in
[adversarial-review/round-5-final-synthesis.md](adversarial-review/round-5-final-synthesis.md).

Date: 2026-04-28.
Branch: `codex-trusted-seed-audit`.

---

## Accepted Decisions

### 1. Trust Contract

Decision: accepted.

The trust contract is:

> Every registered visible number on Dashboard, Transactions, Cash
> Flow, Reports, and Accounts must match canonical synthetic seed facts
> through independent oracle, API, and DOM checks for every registered
> owner/view state.

Implementation implication:

- Registry coverage is not optional for visible numbers on scoped
  pages.
- Unregistered visible numbers are explicitly outside the trust claim.

### 2. Canonical Cash-Flow Definition

Decision: accepted and migrate.

Use `dal.flow_aggregation.compute_period_totals` as the canonical
cash-out definition for monthly income, spending, net, savings rate,
debt service, and debt movement across Dashboard, Cash Flow, and
Reports.

Implementation implication:

- Migrate `dal/reports/spending.py::get_period_summary` to consume
  `compute_period_totals`.
- The Reports-vs-Cash-Flow mismatch is treated as unfinished migration,
  not as a permanent two-lens product decision.

Implementation status:

- Completed 2026-04-29.
- `get_period_summary` now consumes `compute_period_totals`.
- `/api/reports/summary` exposes the same canonical cash-out/gross-up fields
  as Cash Flow and Reports flow: income, spending, net, savings rate, debt
  service, debt accumulated, debt paid down, and net debt change.
- `tests/test_cashflow_reports_parity.py` enforces parity across Cash Flow
  period detail, Reports flow, and Reports summary for ordinary, debt,
  mortgage, payroll, and owner-scoped cases.

### 3. Investments Scope

Decision: accepted.

Keep the Investments page out of this phase. Still audit
investment-derived values that appear on Dashboard, Transactions, Cash
Flow, Reports, and Accounts.

Implementation implication:

- Phase 2 may simplify investment seed data needed for in-scope
  aggregates.
- Do not claim trust for the Investments page until a later dedicated
  audit.

### 4. Oracle Independence

Decision: use the stronger approach. If a second-language independent
oracle gives more confidence, use it.

Implementation recommendation:

- Build an independent second-language oracle as part of the proof
  system. Prefer TypeScript/Node because the app already has a
  TypeScript toolchain, and it reduces shared implementation failure
  with the Python backend.
- The oracle must read seed facts directly from SQLite and neutral
  data/config artifacts. It must not import production DAL helpers,
  backend routers, frontend formatters, or the Python audit formulas.
- Keep the existing Python audit harness as one proof layer, but do
  not treat it as the strongest oracle.

Implementation implication:

- Add a neutral shared semantic vocabulary for category/exclusion sets
  before the second-language oracle depends on those definitions. The
  strongest version is a data artifact consumed by both production and
  audit code, not duplicated Python constants.
- The final proof should compare:
  - trusted seed facts,
  - independent second-language oracle values,
  - Python raw-fact audit values,
  - public API values,
  - rendered DOM values.

Implementation status:

- Completed 2026-04-29 for all currently registered value families across
  Dashboard, Transactions, Cash Flow, Reports, and Accounts.
- `scripts/number_trust_oracle.mjs` reads the canonical SQLite database
  directly with `sql.js` and emits `node-sqljs-oracle-v1` expected values.
- `docs/audits/number-trust/oracle-vocabulary.json` is the neutral vocabulary
  artifact for shared category semantics; `tests/test_audit_vocabulary.py`
  guards it against drift from the canonical DAL category sets.
- The Python audit runs the Node oracle and fails on second-language execution,
  check-id, or expected-value mismatch. Current second-language coverage is 60
  owner/view-scoped checks.
- Promoted zero-diff report:
  `docs/audits/number-trust/reports/number-trust-20260429-193407.md`.

Downside accepted:

- This adds tooling and maintenance cost.
- It may require a small Node SQLite dependency or a bundled runtime
  choice.
- It will take longer than a Python-only expected-values fixture.

Reasoning:

- The goal is confidence before live financial data is imported.
- More independence is worth the extra work because the project
  controls the synthetic data stream and should be able to prove it
  rigorously.

### 5. Canonical Seed Design

Decision: accepted.

Use a deterministic, explainable seed first. Add more complicated and
accurate investment behavior only after this simpler level is clean.

Implementation implication:

- Investment accounts use round starting balances and monthly
  contributions/transfers only.
- No growth, losses, dividends, sells, or price-driven variance in the
  canonical audited investment balances.
- Acorns Synthetic starts at `$10,000` and receives `$500/mo`.
- Fidelity Brokerage starts at `$50,000` and receives `$1,000/mo`.
- TSP Uniformed Services starts at `$100,000` and receives `$1,500/mo`
  in the canonical audit fixture.
- The TSP monthly transfer is a proof-fixture simplification. It does
  not replace the live-data expectation that the user's real TSP has no
  ongoing contributions after military retirement.
- Once the simple proof passes, investment realism can be added in
  controlled, separately audited increments.

Detailed plan:

- [Canonical Investment Seed Simplification Plan](investment-simplification-plan.md)

Implementation status:

- Completed 2026-04-29 in the canonical trusted seed.
- Latest investment balances are Acorns `$28,000`, Fidelity `$86,000`,
  and TSP `$154,000`.
- Canonical DB fingerprint:
  `f061229325d607ffd06e8ea22dee2831a2db18bd91f140c16c88982548c8b9ec`.
- Promoted audit report:
  `docs/audits/number-trust/reports/number-trust-20260429-193407.md`.

### 6. Database Authority

Decision: one database only.

Implementation implication:

- No silent fallback database.
- No competing `sentry.db` / `dummy.db` truths for the active runtime.
- The backend, frontend, seeder, reset flow, API audit, independent
  oracle, DOM audit, and proof command must all resolve to the same
  explicit DB identity.
- Test suites may still create isolated temp databases, but the
  application stack and proof workflow must have exactly one active DB
  authority.

Downside accepted:

- Startup becomes stricter and less forgiving.
- Some casual dev workflows may need command/docs updates.

Implementation status:

- Completed 2026-04-29 for backend/proof/default DAL access.
- `resolve_db_path()` now raises when neither `SENTRY_DB_PATH` nor an explicit
  `db_path` is provided.
- Backend startup resolves one path up front and uses it for migration,
  manifest inspection, startup fixture seeding, and orphaned-run recovery.
- `GET /api/runtime/identity` reports the resolved DB path plus manifest and
  live DB fingerprints with a `fingerprint_match` boolean.
- `GET /api/runtime/context` is now the canonical backend contract for UI and
  proof clients. It exposes contract version, runtime mode/process, DB
  path/hash, schema version, live fingerprint, trusted seed manifest fields,
  effective backend reference clock, and `proof.trusted_seed_ready` with
  blocking reasons.
- `GET /api/runtime/identity` is retained as a flat compatibility projection of
  the same contract.
- The number-trust audit records this runtime context and fails if the trusted
  seed is not proof-ready. This immediately caught a local `derived_summaries`
  drift, which was cleared by canonical reseed before promoting the latest
  zero-diff report:
  `docs/audits/number-trust/reports/number-trust-20260429-193407.md`.
- The same check exposed that `tests/test_dal.py::test_derived_metrics` was
  mutating canonical `data/dummy.db`; that test now uses a temporary SQLite
  backup before recomputing derived summaries. The full backend suite now
  leaves the canonical fixture fingerprint matched to the manifest.
- Frontend consumption is complete for the first trust-bar date defaults:
  `RuntimeProvider` loads `GET /api/runtime/context`, and Header, Dashboard,
  Transactions, Reports, and Cash Flow derive their date-sensitive defaults
  from the backend reference date.
- Owner/view coverage is complete for the current API audit: registry values
  declare Household, Quintin, and Amy; the audit report records each view state;
  and the Python oracle/API comparison passes with zero diffs across 234
  value/view contexts. Amy is intentionally payroll-only with no account
  balances in this fixture, so account-balance values are empty or zero while
  cash-flow values include her payroll snapshots.
- Registry expansion is now complete at value-family level for Dashboard,
  Transactions, Cash Flow, Reports, and Accounts. The registry distinguishes
  `api_oracle` from `registered_pending`, and the latest report records 234
  registered value/view contexts, 234 API/oracle-audited contexts, and 0
  pending contexts.
- First browser comparison is selector-backed for a high-signal slice:
  `scripts/audit_number_trust_dom.py` reruns the API/oracle prerequisite,
  switches Household, Quintin, and Amy through stable ViewSelector hooks, and
  requires every first-slice rendered value to resolve through one stable DOM
  selector before comparing text on Dashboard, Transactions, Cash Flow,
  Reports, and Accounts. Report `number-trust-dom-20260429-204821` records 86
  selector-backed DOM checks, 23 distinct registered contexts touched, and 0
  diffs.
- Remaining proof work: expand stable per-value selectors and DOM checks to
  every registered rendered value, then build the one-command stack/audit gate.

---

## Revised Implementation Priority

1. Phase 0: neutral audit vocabulary and registry semantics.
2. Phase 1: one explicit DB authority with live fingerprint.
3. Phase 1.5: canonical API definitions, owner/view coverage, and
   invariants. Completed for the first-pass API audit.
4. Phase 1.75: independent second-language oracle foundation. Completed for
   first-pass registered values.
5. Phase 2: deterministic/explainable seed simplification.
6. Phase 3: frontend trusted reference date consumption. Completed for
   Dashboard, Transactions, Cash Flow, Reports, and Header defaults; Accounts
   has no browser-clock query default in this slice.
7. Phase 4a: registry expansion and selectors. Registry expansion is complete;
   ViewSelector hooks and first-slice value selectors exist; remaining
   registered values still need per-value selectors.
8. Phase 4b: oracle-to-API-to-DOM audit. First selector-backed browser slice is
   complete; full registry-wide selector-level DOM proof is pending.
9. Phase 5: one-command proof gate.

The second-language oracle began after the DB and vocabulary decisions
stabilized. As registry coverage expands, new values should be added to the
Node oracle before they are claimed as API- or DOM-audited.
