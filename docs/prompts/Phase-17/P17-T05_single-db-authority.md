# P17-T05 Single DB Authority

## Context

The number-trust work depends on proving that the backend, seeder, audit
harness, and UI are all looking at the same database. Earlier rounds surfaced a
split-brain risk: some code paths could still open a default local DB when
`SENTRY_DB_PATH` was missing.

User decision: one database only for active runtime and proof. Test suites may
still use explicit temporary DB paths.

## Starting State

- `backend/api_server.py` required `SENTRY_DB_PATH` on startup, but then called
  `init_db()` and `get_db()` without passing the resolved path.
- `dal.connection.resolve_db_path()` still returned `DB_PATH` (`data/dummy.db`)
  when no env var or explicit path existed.
- `/api/runtime/identity` already reported manifest and live fingerprints.
- Some tests and utility scripts still assumed default DB resolution.

## Task

1. Make default DAL access fail loudly unless `SENTRY_DB_PATH` is set.
2. Preserve explicit temp DB paths for tests and one-off scripts.
3. Pass the resolved backend DB path through startup migration/seeding paths.
4. Keep a dependency-light runtime identity helper for proof and tests.
5. Update tests and docs to reflect the stricter authority model.

## Verification

- `python -m pytest tests/test_connection.py -q`
- `python -m pytest tests/test_document_drops.py -q`
- `python -m pytest tests/test_refresh_orchestrator.py -q`
- `python -m pytest tests/test_trusted_seed.py -q`
- `python -m pytest tests/test_cashflow_invariants.py -q`
- `python -m pytest tests/test_owner_scoping.py -q`
- `$env:SENTRY_DB_PATH="$PWD\data\dummy.db"; $env:SENTRY_DB_MODE="trusted"; python scripts/seed_dummy_data.py`
- `python scripts/audit_number_trust.py --db $env:SENTRY_DB_PATH`
- Runtime identity check should show matching manifest/live fingerprints.

## Outcome

Default DB fallback is retired. Backend/proof/default DAL access now has one
active DB authority: `SENTRY_DB_PATH`, unless a caller passes an explicit
`db_path` for isolated tests/scripts. Runtime identity remains the proof point
for path, seed version, reference date, manifest fingerprint, live fingerprint,
and match status.

## Follow-Ups

- Fold runtime identity verification into the later one-command proof gate.
- Continue Phase 17 number-trust hardening with owner/view/date certainty,
  independent oracle foundation, registry expansion, and DOM audit expansion.
