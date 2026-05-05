# P17-T33: Reference-Clock Audit Coverage Hardening

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/38

## Context

The reference-clock contract is load-bearing before live trust:
date-sensitive finance windows/defaults must use the backend reference
clock, while connector `as_of`, posting dates, statement dates, refresh
timestamps, and event timestamps remain separate facts. The current audit
passes while missing finance-window modules that still contain
`date('now')` or `datetime.now()` patterns.

This is an AFK overnight slice suitable for Codex or Claude.

## Starting State

- `scripts/audit_reference_clock_usage.py` scans a small
  `REFERENCE_SENSITIVE_PYTHON_FILES` tuple.
- The audit currently passes.
- `dal/reports/merchant.py` uses SQLite `date('now', ...)` in merchant
  report lookbacks.
- `dal/budgets.py` and `dal/forecasting.py` also contain finance-window
  wall-clock patterns that are not currently covered by the audit.
- `CLAUDE.md` and `docs/ARCHITECTURE.md` require the backend reference
  clock for date-sensitive finance windows.

## Task

1. Read `CLAUDE.md`, `docs/ARCHITECTURE.md` section 3.4, and
   `scripts/audit_reference_clock_usage.py`.
2. Deepen the audit so finance-window modules are covered by policy, not
   a stale hand list. A broader scanner with explicit allow annotations is
   acceptable if the false-positive surface is controlled.
3. Fix newly-covered finance-window violations in merchant reports,
   budgets, and forecasting where they are true reference-clock bugs.
4. Keep legitimate real-time uses allowed and documented.

## Non-Goals

- Do not change connector refresh timestamps or event timestamps to the
  reference clock.
- Do not rewrite unrelated analytical queries.
- Do not change frontend RuntimeContext behavior unless a test proves it is
  part of the same violation.

## Verification

- Add or update tests for the audit coverage itself.
- Run:
  `python scripts/audit_reference_clock_usage.py --json`
- Run:
  `pytest tests/test_reference_clock_usage.py tests/test_cashflow_invariants.py -x --tb=short`
- Run targeted tests for any DAL modules touched.

## Agent Shutdown

Use branch `codex/p17-t33-reference-clock-audit` or
`claude/p17-t33-reference-clock-audit`. Commit and stop. Do not merge.
