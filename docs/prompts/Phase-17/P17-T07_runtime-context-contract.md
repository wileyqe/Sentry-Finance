# P17-T07: Backend Runtime Context Contract

## Context

The trusted seed and single-DB work removed the biggest source of DB ambiguity,
but the UI and audit still needed a stable backend contract for the effective
runtime context. The next proof steps need one place to read DB identity,
trusted seed identity, manifest/live fingerprint status, and the backend
reference clock.

## Starting State

- `GET /api/runtime/identity` existed as a flat DB identity/status response.
- `dal.clock.reference_date()` and `reference_datetime()` already used the
  trusted seed manifest when present.
- The number-trust audit read the manifest directly but did not fail on runtime
  context readiness.

## Task

1. Add a nested backend runtime context contract for UI and proof clients.
2. Preserve the existing flat identity endpoint as a compatibility projection.
3. Expose the effective backend clock source and reference date/datetime.
4. Make the audit record the runtime context and fail when the trusted seed is
   not proof-ready.
5. Fix any local verification path that mutates the canonical trusted DB.
6. Document the completed contract and remaining frontend/proof-gate work.

## Verification

- `python -m pytest tests/test_connection.py -q`
- `python -m ruff check backend/runtime_context.py backend/runtime_identity.py backend/api_server.py dal/clock.py scripts/audit_number_trust.py tests/test_connection.py`
- `$env:SENTRY_DB_PATH="$PWD\data\dummy.db"; $env:SENTRY_DB_MODE="trusted"; python scripts/seed_dummy_data.py`
- `python scripts/audit_number_trust.py --db $env:SENTRY_DB_PATH`
- `python -m pytest tests/ -x --tb=short`
- Runtime context fingerprint check after the full suite

## Outcome

Implemented `GET /api/runtime/context` with contract version
`runtime-context-v1`. The response includes runtime mode/process, DB path/hash,
schema version, live fingerprint, trusted seed manifest fields, effective
reference clock, and `proof.trusted_seed_ready` with blocking reasons.

`GET /api/runtime/identity` now projects the same contract into the older flat
shape. The audit report includes the runtime context and gates zero-diff status
on trusted seed readiness.

The new gate caught a `derived_summaries` fingerprint drift caused by
`tests/test_dal.py::test_derived_metrics` recomputing against the canonical
fixture. That test now backs up the fixture to a temporary SQLite database
before recomputing, so the full backend suite leaves the trusted DB proof-ready.
