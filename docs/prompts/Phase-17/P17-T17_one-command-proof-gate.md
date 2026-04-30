# P17-T17 One-Command Number-Trust Proof Gate

## Context

The trusted synthetic number-trust work has deterministic seed facts,
runtime DB identity, independent Python and Node/sql.js oracle checks, and
selector-backed DOM coverage for Dashboard, Transactions, Cash Flow, Reports,
and Accounts. The remaining proof gap is reproducibility: a future session
needs one command that rebuilds and proves the stack without relying on handoff
memory.

## Starting State

- `scripts/seed_dummy_data.py` reseeds the canonical trusted database when
  `SENTRY_DB_PATH` is explicit.
- `GET /api/runtime/context` and `/api/runtime/identity` expose the active DB
  path, trusted seed version, reference date, manifest fingerprint, live
  fingerprint, and proof readiness.
- `scripts/audit_number_trust.py` writes zero-diff API/oracle reports.
- `scripts/audit_number_trust_dom.py` writes zero-diff selector-backed DOM
  reports against a running frontend.
- The latest manual proof path still requires several commands and a running
  stack.

## Task

- Add a single proof command under `scripts/`.
- The command must reseed the canonical trusted DB, start or verify the
  backend/frontend stack, verify runtime identity, run API and DOM audits, run
  frontend build and required tests, and write one final report.
- Pass one absolute `SENTRY_DB_PATH` and `SENTRY_DB_MODE=trusted` to every
  child process.
- Clean up only backend/frontend processes started by the proof command.

## Verification

- `python -m pytest tests/test_number_trust_proof_gate.py -q`
- `python -m ruff check scripts/run_number_trust_proof.py tests/test_number_trust_proof_gate.py`
- `python scripts/run_number_trust_proof.py`

## Outcome

Implemented `scripts/run_number_trust_proof.py`. The promoted proof report
`docs/audits/number-trust/reports/number-trust-proof-20260430-000704.md`
passes reseed, stack verification, runtime identity, API/oracle audit,
DOM/browser audit, frontend build, audit vocabulary tests, and trusted seed
tests.
