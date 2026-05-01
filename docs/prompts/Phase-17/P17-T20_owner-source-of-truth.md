# P17-T20: Owner Source Of Truth And Durable Ownership Assignment

## Context

The app now treats owner scoping as a first-class contract: API calls thread
`owner_id`, owner-aware DAL helpers distinguish no-filter from owns-nothing,
and the ViewSelector renders Household / owner views unconditionally. The
remaining pre-trust-bar gap is durability of ownership assignment itself.

Today Settings can rename owners, and the backend already has an account-owner
patch endpoint, but there is not yet a clearly documented source of truth for
account ownership edits made in the UI. The target user workflow is: open
Settings, assign or modify account ownership, and have that assignment survive
restarts and trusted/dev rebuilds instead of being a fragile in-memory or
seed-only fact.

This task is assigned to **Codex** for the clean-context run.

## Multi-Agent Coordination

This task is intentionally paired with
`P17-T21_review-pages-number-trust.md`, assigned to Claude. These branches may
run at the same time.

Codex owns only this responsibility/write set unless the user redirects:

- Ownership source-of-truth design and implementation
- `dal/owners.py` and small adjacent ownership helpers if needed
- `backend/routers/accounts.py` owner endpoints, or a narrowly extracted
  owner router if that becomes cleaner
- `frontend/src/pages/SettingsPage.tsx` ownership assignment UI
- Targeted ownership tests such as `tests/test_owner_scoping.py` or a new
  ownership durability test file
- Documentation directly needed to explain the chosen source of truth
- This prompt's outcome section after implementation

Do **not** edit these files in this branch:

- `docs/audits/number-trust/ui-number-registry.yaml`
- `scripts/audit_number_trust.py`
- `scripts/audit_number_trust_dom.py`
- `scripts/number_trust_oracle.mjs`
- `frontend/src/pages/MonthlyReviewPage.tsx`
- `frontend/src/pages/YearlyWrapUpPage.tsx`
- `docs/ROADMAP.md` or `docs/ROADMAP_ARCHIVE.md`

If the implementation appears to require overlap with the Review page
number-trust branch, stop and write a short note explaining the dependency
instead of editing across the boundary.

Git/worktree discipline:

- Start from clean, up-to-date `main`.
- Create a dedicated branch/worktree, suggested name:
  `codex/p17-owner-source-of-truth`.
- Do not work directly on `main`.
- Do not rebase, merge, delete, or rewrite Claude's branch/worktree.
- Do not refresh Graphify extraction as part of this task.
- Leave roadmap status updates for the merge pass.

## Starting State

- `owners` is a real DB table and `accounts.owner_id` already drives owner
  scoping.
- `dal/owners.py` provides owner CRUD helpers, `assign_account_owner()`,
  `resolve_account_ids_for_view()`, and `build_account_filter()`.
- `backend/routers/accounts.py` exposes:
  - `GET /api/owners`
  - `PATCH /api/owners/{owner_id}` for display-name edits
  - `PATCH /api/accounts/{account_id}/owner` for owner assignment
- `SettingsPage.tsx` currently supports owner renames but does not present a
  durable account ownership assignment workflow.
- `ViewContext.tsx` and `ViewSelector.tsx` already consume owners from
  `/api/owners`.
- `owner_config.yaml` still seeds configured owners and primary-owner defaults.
- `accounts.yaml` is gitignored and remains the real-account identity source
  for opaque account ids; never expose real last-four digits in committed
  fixtures, docs, or logs.

Graph context at prompt-authoring time pointed at:

- `dal/owners.py`
- `backend/routers/accounts.py`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/context/ViewContext.tsx`
- `frontend/src/components/multi-user/ViewSelector.tsx`
- `tests/test_owner_scoping.py`
- `tests/test_dal.py`

Treat that graph as advisory only; live code and tests are executable truth.

## Task

Make account ownership assignment durable and make the source-of-truth boundary
explicit.

Required behavior:

1. Decide and document the ownership source-of-truth model.
   - Prefer a conservative model that fits local-first use.
   - A good target is hybrid: DB is the runtime authority; a gitignored local
     config/override file or equivalent local persistence is the rebuild
     authority for user edits that must survive DB rebuilds.
   - Do not commit live account identifiers or PII-bearing config.
2. Ensure account owner assignments made through the backend validate:
   - account exists,
   - owner exists when non-null,
   - `None`/null means household/shared,
   - unknown owners fail loudly,
   - account identifiers are redacted in logs.
3. Add a Settings workflow to assign account ownership.
   - Show accounts with enough non-sensitive context for the user to choose.
   - Let the user assign each account to Household/shared or a configured
     owner.
   - Keep owner display-name editing intact.
   - Avoid a large Settings redesign; this is a functional ownership tool.
4. Make assignments durable across restart and rebuild.
   - Restart durability can be DB-backed.
   - Rebuild durability must be explicit. If using a gitignored local file,
     provide load/apply behavior and safe creation/update behavior.
   - Trusted synthetic seed behavior must remain deterministic and should not
     accidentally consume real local ownership overrides unless deliberately
     designed and documented.
5. Preserve owner-scoping invariants.
   - Household view remains unfiltered.
   - Owner views include that owner's accounts plus shared/NULL-owner accounts
     where current architecture expects shared visibility.
   - Owners with no accounts must continue to return empty/zero account-scoped
     facts instead of leaking another owner's data.
6. Update docs only where the source-of-truth boundary needs to be recorded.
   If code and docs disagree while implementing, prefer live code for behavior
   and fix the doc drift in the same branch.

Implementation notes:

- Keep budgets household-only. Do not reintroduce budget `owner_id` semantics.
- Do not create cloud sync, telemetry, or remote persistence.
- Avoid direct DB queries outside DAL except for existing router patterns or
  test setup.
- Do not store credentials, real statements, real last-four digits, or live
  account identifiers in committed files.
- Keep migrations sequential if schema changes are truly required.

## Verification

Minimum verification:

```powershell
python -m py_compile dal\owners.py backend\routers\accounts.py
python -m pytest tests\test_owner_scoping.py -q
python -m pytest tests\test_dal.py -q
```

If frontend changes are made:

```powershell
cd frontend
npm run build
```

If schema or DAL behavior changes, also run:

```powershell
pytest tests/ -x --tb=short
```

Targeted search checks:

```powershell
rg -n "assign_account_owner|account_id.*owner|owner_id|ownership" dal backend frontend\src\pages\SettingsPage.tsx tests docs
```

Manual/dev check when practical:

1. Start the app against a temp/dev DB.
2. Change one account to an owner and one account to Household/shared.
3. Restart backend/frontend.
4. Confirm Settings still shows those assignments and owner-scoped pages reflect
   the expected account visibility.
5. If rebuild durability is file-backed, rebuild the DB in the documented safe
   way and confirm the ownership assignments reapply.

## Done Criteria

- Settings can assign account ownership without hand-editing the DB.
- The chosen source of truth is documented and matches implementation.
- Ownership edits survive restart and have an explicit rebuild path.
- Owner scoping tests still prove no leakage for empty-owner views.
- Budget household-only behavior remains untouched.

## Outcome

Implemented on `codex/p17-owner-source-of-truth`.

- Chosen source-of-truth model: hybrid/local-first. `accounts.owner_id` is the
  runtime authority; `config/account_ownership.local.yaml` is a gitignored
  rebuild-authority mirror for Settings edits; `config/owner_config.yaml`
  remains the committed owner roster.
- Backend ownership assignment now validates account existence, validates
  non-null owners, treats null/blank as Household/shared, redacts account ids in
  logs, and persists successful Settings assignments to the local override file.
- Real-account seeding replays the gitignored ownership override file after
  `accounts.yaml` stubs are present. The trusted synthetic seeder remains
  isolated and does not consume local real-account overrides.
- Settings now includes an account ownership assignment table without changing
  the existing owner display-name editing workflow.
- Added targeted durability/validation coverage in `tests/test_owner_scoping.py`.
