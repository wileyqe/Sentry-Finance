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
