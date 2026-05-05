# P17-T35: Analytical Transaction Window Module

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/42

## Context

`dal/flow_aggregation.compute_period_totals` is already a deep module and
should be protected. The remaining shallow part is lower-level SQL policy:
effective-month attribution, explicit/reference-date windows, and canonical
income/spend filters are repeated across reports, budgets, forecasting, and
merchant analytics.

This is an AFK overnight slice for Codex or Claude, but it should be done
after P17-T33 if both are in flight.

## Starting State

- `_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"` is
  repeated in multiple DAL/report modules.
- `tests/test_cashflow_invariants.py` has effective-month drift coverage.
- `tests/test_cashflow_reports_parity.py` protects parity through
  `compute_period_totals`.
- `dal/category_classifications.py` already owns category exclusion sets and
  helper clauses.

## Task

1. Read `docs/ARCHITECTURE.md` section 4.6, `dal/flow_aggregation.py`,
   and the cash-flow invariant/parity tests.
2. Add a small analytical query helper module that owns effective-month
   expression/window fragments and canonical income/spend predicate helpers.
3. Migrate a narrow set of callers to prove the module earns its keep.
   Prefer merchant reports, budget suggestions, or forecasting windows over
   the headline `compute_period_totals` interface.
4. Preserve `compute_period_totals` as the primary interface for headline
   cash-flow facts.

## Non-Goals

- Do not replace `compute_period_totals`.
- Do not rewrite the Sankey/accountability engine.
- Do not change category vocabulary unless a test proves current vocabulary
  is wrong.
- Do not mix this with reference-clock audit hardening unless the same line
  must change.

## Verification

- Run:
  `pytest tests/test_cashflow_invariants.py tests/test_cashflow_reports_parity.py -x --tb=short`
- Run targeted tests for every migrated caller.
- Run `python scripts/audit_reference_clock_usage.py`.

## Agent Shutdown

Use branch `codex/p17-t35-analytical-window-module` or
`claude/p17-t35-analytical-window-module`. Commit and stop. Do not merge.

## Outcomes (post-merge, 2026-05-05)

**Status:** `[v]` complete. Merged via PR [#48](https://github.com/wileyqe/Sentry-Finance/pull/48) at `5bd345b`. Issue #42 closed.

**What was built (Codex commit `0db291c`):**
- New `dal/analytical_window.py` with four helpers:
  - `effective_month_expr(*, txn_alias=None)` — canonical effective-month SQL, optional table alias
  - `effective_month_between_clause(*, start_date, end_date, txn_alias=None)` — month BETWEEN range
  - `canonical_spend_predicate(*, category_expr, signed_amount_expr, transfer_tag_expr)` — sign + transfer + exclusion-list spend filter
  - `canonical_income_predicate(*, ...)` — same shape for income
- Migrated narrow callers as planned: `dal/budgets.py`, `dal/forecasting.py`, `dal/reports/merchant.py`
- Preserved `compute_period_totals` untouched (per non-goals)
- Lineage notes added to `docs/data-lineage/events.yaml` (`analytical_window_sql_fragments` topic)

**Surprise (positive):**
- The migration of `dal/forecasting.py` also corrected a pre-existing CLAUDE.md §4.6 guardrail violation: the legacy `direction = 'Debit'/'Credit'` pattern was replaced with canonical `signed_amount < 0 / > 0` sign-checks. This was not in the original task scope but landed as a side effect of the cleanup.

**Review additions (Claude commit `110550e`):**
- New `tests/test_analytical_window.py` — 14 unit tests locking the helper contract:
  - effective-month expr with/without alias
  - between-clause YYYY-MM truncation
  - spend/income predicate composition + custom column expressions
  - transfer/loan exclusion sanity guard
  - mutual exclusivity by sign
  - SQLite syntax integration smoke test

**Verification at merge:**
- `pytest tests/test_cashflow_invariants.py tests/test_cashflow_reports_parity.py tests/test_budgets_household.py tests/test_attribution.py::TestQueryIntegration tests/test_reference_clock_usage.py tests/test_owner_scoping.py::test_phase_a_aggregate_metrics_scoping tests/test_analytical_window.py` — 53/53 passed
- `python scripts/audit_reference_clock_usage.py` — passed

**Follow-ups (not in scope of this PR):**
- `effective_month_between_clause` is defined but currently unused. Kept as a primitive for future month-range migrations; locked by tests so it cannot bit-rot. First caller to need a month-window filter should adopt it.
- Default `category_expr='Uncategorized'` in `canonical_spend_predicate` doesn't match `merchant.py`'s `'COALESCE(category, '')'`. Callers override correctly; a richer signature could remove the override pattern.
- Future PR could migrate `compute_period_totals`' headline path if helper proves stable.
