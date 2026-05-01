# P17-T18: Destructive Data-Wipe Tooling

## Context

The app needs a safe way to move between synthetic data, test data, and
eventual real household data. The trusted seed reset is intentionally
non-destructive in spirit: it rebuilds the canonical synthetic fixture for
proof work. The missing tool is different. It should make an explicit,
auditable data wipe possible for a chosen SQLite database without confusing
that path with the trusted-seed reset.

This task is assigned to **Codex** for the parallel overnight run.

## Multi-Agent Coordination

This task is intentionally paired with
`P17-T19_budgets-number-trust.md`, assigned to Claude. These branches may run
at the same time.

Codex owns only this write set unless the user redirects:

- `scripts/wipe_data.py`
- `tests/test_wipe_data.py` or similarly named wipe-tool tests
- `docs/COMMANDS.md` entries for the new command
- This prompt's outcome section after implementation

Do **not** edit these files in this branch:

- `frontend/src/pages/BudgetsPage.tsx`
- `docs/audits/number-trust/ui-number-registry.yaml`
- `scripts/audit_number_trust.py`
- `scripts/audit_number_trust_dom.py`
- `scripts/number_trust_oracle.mjs`
- `docs/ROADMAP.md` or `docs/ROADMAP_ARCHIVE.md`

If the implementation appears to require overlap, stop and write a short note
explaining the dependency instead of editing across the boundary.

Git/worktree discipline:

- Start from clean, up-to-date `main`.
- Create a dedicated branch/worktree, suggested name:
  `codex/p17-wipe-data-tooling`.
- Do not work directly on `main`.
- Do not rebase, merge, or delete Claude's branch/worktree.
- Do not run destructive commands against any DB except a temp test DB unless
  the user explicitly asks for a live/dev wipe.
- Leave roadmap status updates for the morning merge pass.

## Starting State

- `SENTRY_DB_PATH` is the single runtime DB authority.
- `SENTRY_DB_MODE` distinguishes trusted/dev/live intent.
- `scripts/seed_dummy_data.py` rebuilds the canonical trusted synthetic
  fixture.
- `backend/routers/dev.py` exposes `POST /api/dev/reset-trusted-seed` for
  local trusted-seed reset.
- `scripts/run_number_trust_proof.py` reseeds and proves the trusted fixture.
- No dedicated destructive wipe command exists yet.

## Task

Add a dependency-light CLI under `scripts/` that can inspect and wipe a target
SQLite DB safely.

Required behavior:

1. Resolve the target DB from `--db <path>` or `SENTRY_DB_PATH`; fail loudly if
   neither is provided.
2. Default to dry-run. A dry-run should print/report:
   - resolved DB path,
   - detected DB mode where available,
   - tables that would be wiped,
   - row counts by table,
   - tables intentionally preserved,
   - whether a trusted-seed manifest/fingerprint appears present.
3. Actual wiping must require both:
   - an explicit execute flag such as `--execute`, and
   - a typed confirmation token tied to the resolved absolute DB path.
4. Make a timestamped backup copy before destructive execution by default.
   The backup path should be reported clearly.
5. Preserve schema/migrations and any tables that are structural rather than
   household data. Do not drop tables.
6. Refuse to wipe the canonical trusted fixture by accident. At minimum, do
   not allow a normal destructive run against a DB that appears to contain the
   trusted seed manifest unless an intentionally named override is provided.
7. Avoid direct app DAL assumptions where a plain SQLite connection is safer.
   This should be an offline maintenance tool, not a hidden API behavior.
8. Return nonzero on unsafe input, missing DB, failed backup, failed
   confirmation, or SQLite errors.

Implementation notes:

- Prefer pure Python standard library.
- Keep the script testable by factoring planning/confirmation/wipe helpers.
- Tests should use temporary SQLite databases only.
- The command must not run automatically from backend startup, proof gate, or
  dev reset.

## Verification

Minimum verification:

```powershell
python -m py_compile scripts\wipe_data.py
python -m pytest tests\test_wipe_data.py -q
python scripts\wipe_data.py --db data\dummy.db
```

The final command should be a dry-run only. Do not execute a wipe against
`data/dummy.db` as part of verification.

If implementation touches command docs:

```powershell
rg -n "wipe_data|destructive|trusted seed" docs\COMMANDS.md scripts\wipe_data.py
```

## Done Criteria

- A future agent can run a safe dry-run and understand exactly what would be
  deleted.
- An actual wipe is hard to trigger accidentally.
- The trusted seed reset path remains separate and clearly documented.
- Tests prove dry-run, confirmation refusal, backup creation, table wiping,
  preserved tables, and trusted-fixture refusal.

## Outcome

Implemented on `codex/p17-wipe-data-tooling`.

- Added `scripts/wipe_data.py`, a stdlib-only offline SQLite maintenance CLI
  that resolves `--db`/`SENTRY_DB_PATH`, defaults to dry-run, reports row
  counts and preserved structural tables, requires `--execute` plus a
  path-bound confirmation token, creates a timestamped backup before wiping,
  and refuses trusted-seed manifests unless `--allow-trusted-seed-wipe` is
  intentionally supplied.
- Added `tests/test_wipe_data.py` covering missing DB input, dry-run manifest
  reporting, confirmation refusal, backup creation, data wiping, structural
  table preservation, trusted-fixture refusal, and trusted override behavior.
- Documented the dry-run and destructive command shape in `docs/COMMANDS.md`.
