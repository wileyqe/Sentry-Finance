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

## Outcomes

### What was built

1. **Audit script deepened** (`scripts/audit_reference_clock_usage.py`):
   - Added `dal/budgets.py`, `dal/forecasting.py`, and `dal/reports/merchant.py`
     to `REFERENCE_SENSITIVE_PYTHON_FILES`.
   - Fixed `sqlite-date-now` regex to match `date('now', ...)` (with trailing
     args), not just `date('now')`. The old regex was a blind spot — the
     violations it was meant to catch never actually triggered.
   - Added `sqlite-datetime-now` pattern to catch SQL `datetime('now'...)`.
   - Added inline `# refclock-allow: <reason>` annotation support so
     legitimate wall-clock uses (e.g. `updated_at` timestamps) can be
     documented in-place and suppressed from the scan.

2. **Finance-window violations fixed**:
   - `dal/reports/merchant.py`: 4 SQL `date('now', ...)` → parameterized
     cutoff from `dal.clock.reference_date(conn)`.
   - `dal/budgets.py` `suggest_budget_targets`: 1 SQL `date('now', ...)` →
     parameterized cutoff. `set_budget_target`'s `datetime('now')` for
     `updated_at` annotated as allowed (audit timestamp).
   - `dal/forecasting.py`: 2 `datetime.now(timezone.utc)` →
     `dal.clock.reference_datetime(conn)` in `build_seasonal_income_model`
     and `get_cash_flow_forecast`; 2 SQL `date('now', ...)` → parameterized
     cutoff in `_get_rolling_averages`.
   - `dal/reports/spending.py` `get_category_trend`: 1 SQL
     `date('now', '-? months')` → parameterized cutoff (bonus fix caught by
     the widened regex).

3. **Regression tests added** (`tests/test_reference_clock_usage.py`):
   - `test_inline_refclock_allow_suppresses_violation` — proves the allow
     annotation works.
   - `test_merchant_budgets_forecasting_in_sensitive_files` — asserts the
     three new modules stay in the sensitive-files tuple.
   - `test_flags_sqlite_date_now_in_new_sensitive_files` — regression guard
     against reverting the SQL fixes.

### Surprises

- The `sqlite-date-now` regex `date\(\s*['"]now['"]\s*\)` required a
  closing paren immediately after `'now'`, so `date('now', '-6 months')`
  was **never caught**. This was the root blind spot — the audit was
  passing with false confidence.

### Verification

- `python scripts/audit_reference_clock_usage.py --json` → pass
- `pytest tests/test_reference_clock_usage.py tests/test_cashflow_invariants.py -x --tb=short` → 20 passed
- `pytest tests/ -x --tb=short -q` → 620 passed, 2 xfailed

## Agent Shutdown

Use branch `codex/p17-t33-reference-clock-audit` or
`claude/p17-t33-reference-clock-audit`. Commit and stop. Do not merge.

### Merge

Merged via `ea91788` ("Merge reference-clock audit hardening", direct merge of `claude/p17-t33-reference-clock-audit`). Issue #38 closed. ROADMAP updated to `[v]`.
