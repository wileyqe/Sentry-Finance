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
- Once the simple proof passes, investment realism can be added in
  controlled, separately audited increments.

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

---

## Revised Implementation Priority

1. Phase 0: neutral audit vocabulary and registry semantics.
2. Phase 1: one explicit DB authority with live fingerprint.
3. Phase 1.5: canonical API definitions, owner/view coverage, and
   invariants.
4. Phase 1.75: independent second-language oracle foundation.
5. Phase 2: deterministic/explainable seed simplification.
6. Phase 3: frontend trusted reference date.
7. Phase 4a: registry expansion and selectors.
8. Phase 4b: oracle-to-API-to-DOM audit.
9. Phase 5: one-command proof gate.

The second-language oracle should begin after the DB and vocabulary
decisions are stable, but before the final DOM/proof gate, so it can
serve as a real independent comparator rather than a late decoration.
