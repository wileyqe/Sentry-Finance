# AGENTS.md

Working notes for Codex agents in this repository. These instructions are
derived from `CLAUDE.md`, `README.md`, and the full `docs/` tree as of
2026-04-28. Treat live code as executable truth when docs drift, but preserve
the design intent captured in `docs/ARCHITECTURE.md`.

## Mission

Sentry Finance is a local-first personal finance command center for one
household. It replaces third-party aggregators with local browser automation,
local SQLite storage, direct institution connectors, and a React/Tauri UI.

The product is not "more numbers on a dashboard." Every change should help the
household answer: "What should I do differently?" Prefer data trust, decision
support, trend visibility, and forward-looking insight over decorative metrics.

## Start Here

At the beginning of a session:

1. Check branch and worktree state. Read `docs/agent-rules/branch-hygiene.md`
   before starting feature work or when git state looks off.
2. Read `CLAUDE.md` for current operating rules.
3. Read `docs/ROADMAP.md`, especially `Next Up`. If any P0 item is open, it
   is the only eligible task unless the user explicitly redirects.
4. For the active task, scan `docs/ARCHITECTURE.md` sections that touch that
   domain.
5. Load companion docs only when relevant:
   - `docs/DESIGN.md` before frontend work.
   - `docs/HOUSEHOLD_PROFILE.md` for owner, mortgage, TSP, income, or partner
     rules.
   - `docs/DUMMY_DATA_GENERATION_SPEC.md` for seeder changes.
   - `docs/COMMANDS.md` for commands and test slices.
   - `docs/data-lineage/HOWTO.md` for "where does this number come from?"
     questions.
   - `docs/prompts/README.md` before authoring or using task prompt files.

Do not blindly load all prompt files. `ROADMAP.md` points to the prompt file
when one matters.

## Current Priority Shape

The roadmap is authoritative and may change. As of the latest docs, the main
hard line is the single-user trust bar:

- Finish trust-bar work before Phase 19+ partner integration.
- Open trust-bar items include myPay browser connector and the decision about
  destructive data-wipe tooling.
- Partner MFA has a closed design in `docs/PARTNER_MFA_DESIGN.md`, but build
  is deferred until the user affirms the app is trustworthy for their own data.
- Phase 18 tax lots are blocked on real broker statements.

Do not pull deferred items without reconfirming: mortgage extra-payment
simulator, TSP switch/stay analysis, and rental property support.

## Non-Negotiable Engineering Rules

- Do not add direct application SQL outside the DAL except migrations and
  isolated test setup.
- Never change schema ad hoc. Add a sequential migration under
  `dal/migrations/`.
- Money is integer cents where schema expects cents. Avoid floats for financial
  amounts in new logic.
- All transaction writes go through `dal.transactions.upsert_transactions()`.
  It enforces the canonical sign invariant:
  - `signed_amount < 0` means `direction = 'Debit'`.
  - `signed_amount > 0` means `direction = 'Credit'`.
  - `amount` is absolute.
- Analytical income/spending aggregates must use the canonical pattern:
  `signed_amount`, `transfer_tag IS NULL`, and exclusion sets from
  `dal/category_classifications.py`. Do not introduce
  `SUM(CASE WHEN direction = 'Debit' THEN amount ...)`.
- Owner scoping is first-class end to end. Thread `owner_id` through DAL, API,
  and frontend. Use `dal/owners.build_account_filter(owner_id, account_ids)`;
  it distinguishes `None` from `[]`.
- Budgets are household-only. Do not reintroduce owner-scoped budgets in DAL,
  router, or UI.
- Keep institution-specific logic inside that connector/parser path.
- Connector failures should log and continue where the architecture expects
  isolation.
- Respect the post-ingestion pipeline after connector/document writes:
  categorization, merchant normalization, reconciliation, recurring detection,
  Acorns linkage when relevant, mortgage decomposition, ticker enrichment,
  derived recompute, alerts, goal sync, notifications.
- Do not casually add new SSE shapes. Use `backend/sse_topics.py` and
  `frontend/src/lib/sseTopics.ts`.
- Treat imported/scraped data as untrusted. Validate before writing.
- Never commit credentials, account last-4 values, profiles, raw exports, or
  sensitive logs. Preserve the PII security gate.
- Preserve local-first behavior. No cloud persistence, telemetry, or aggregator
  dependency without explicit architecture approval.

## Architecture Map

Core runtime:

- Frontend: React 19, TypeScript, Vite 7, Tauri 2, Tailwind 3.4, Recharts only.
- Backend: FastAPI REST plus SSE on localhost.
- Database: SQLite in WAL mode. Current schema version is the highest
  `dal/migrations/v##_*.py`; do not trust stale doc version numbers.
- Ingestion: institution connectors, document drop parsers, and seeder all
  converge through DAL writers and the post-commit pipeline.
- Credential broker: short-lived elevated Windows process, keyring backed,
  passes secrets over hardened IPC.

Important modules:

- `backend/api_server.py`, `backend/routers/`, `backend/result_writer.py`,
  `backend/refresh_orchestrator.py`, `backend/events.py`.
- `dal/` for all persistence and analytical reads.
- `extractors/` for Chase, NFCU, Fidelity, Acorns, Affirm, TSP and selector
  healing paths.
- `scripts/seed_dummy_data.py` and `scripts/dummy_data/generator.py` for the
  canonical trusted synthetic dataset.
- `frontend/src/pages/`, `frontend/src/components/`, `frontend/src/lib/`,
  `frontend/src/hooks/`.

## Data Lineage

`docs/data-lineage/` is a completed reference map:

- Start with `docs/data-lineage/HOWTO.md`.
- Use `inverse-index.yaml` first for table.column or UI-surface fan-out.
- Per-event source records live in `lineage/*.yaml`.
- Mermaid diagrams in `diagrams/*.mmd` are generated from YAML.
- Regenerate after lineage YAML edits:
  - `python docs/data-lineage/build_inverse_index.py`
  - `python docs/data-lineage/build_diagrams.py`
  - or run `python docs/data-lineage/check_freshness.py`.

The lineage map is reference documentation, not runtime truth. If it disagrees
with code, fix the YAML and regenerate generated artifacts.

## Frontend Rules

Before frontend edits, read `docs/DESIGN.md`.

- Use existing primitives in `frontend/src/components/ui/` before hand-rolling:
  `Button`, `Card`, `Table`, `Select`, `Sheet`, `Input`, `Skeleton`,
  `EmptyState`, `ErrorState`, `PageHeader`, `SectionHeader`, `FilterBar`,
  `StatCard`, `Chip`, `PageShell`, etc.
- Use `useOwnerApi()` for owner-scoped data fetches.
- Use `formatCurrency`, `formatCompactCurrency`, `formatDetailField`, and
  `.text-numeric` for money and aligned numbers.
- Use design tokens and semantic utilities. Avoid hardcoded hex, RGB, OKLCH
  literals in TSX, and Tailwind palette names like `emerald`, `rose`, or
  `slate` for sentiment.
- Recharts is the only chart library.
- The UI language is warm, restrained, data-dense, and craft/editorial:
  cream surfaces, terracotta actions, amber attention, green/red sentiment,
  Newsreader headings, Inter body, JetBrains Mono numerics.
- Owner chip switcher `[Quintin | Household | Amy]` renders unconditionally.
  Amy's view is a verified empty-state harness until real data arrives.

## Seeder And Dummy Data

The active seeder is `scripts/seed_dummy_data.py`; the old JSON-file seeder was
removed. The synthetic dataset is now one canonical trusted fixture:

- `seed_version = trusted-2026-04-27-v1`.
- Public seed dates are fixed: end date `2026-04-27`, reference date
  `2026-04-28`, three-year lookback.
- Normal seeding does not use live market/network inputs.
- The canonical local trusted-seed database is `data/dummy.db`.
- Backend/proof runs must set `SENTRY_DB_PATH` explicitly and can verify the
  active path/fingerprint at `GET /api/runtime/identity`.
- Missing `SENTRY_DB_PATH` is a hard error for default DAL access; test suites
  may still pass explicit temp DB paths.
- Every run writes a manifest to `app_settings.trusted_seed_manifest` and
  `data/trusted_seed_manifest.json` with row counts and table fingerprints.
- Transactions go through `upsert_transactions()` and the post-commit pipeline.
- Refunds and paired transfers intentionally exercise sign and reconciliation
  invariants.
- Static structural fixtures remain under `dummy_data/`; time-series data is
  generated.
- The dev reset endpoint is `POST /api/dev/reset-trusted-seed`; the old
  advance-dummy flow is retired.
- Number-trust audit assets live in `docs/audits/number-trust/`; run
  `python scripts/audit_number_trust.py --db $env:SENTRY_DB_PATH` after seed
  or UI-number changes.
- With the trusted-seed backend and frontend running, run
  `python scripts/audit_number_trust_dom.py --db $env:SENTRY_DB_PATH --frontend-url http://127.0.0.1:1420`
  for the first browser DOM number-trust slice.

Investment seeding: the canonical audit seed uses round starting balances plus
deterministic monthly transfers only. Acorns starts at `$10,000` and receives
`$500/mo`; Fidelity starts at `$50,000` and receives `$1,000/mo`; TSP starts
at `$100,000` and receives `$1,500/mo`. Do not reintroduce linear drift,
dividends, sells, roundups, fees, or price-driven variance as canonical
audit-seed requirements. Market realism belongs to later live-data or
separately audited investment work.

## Prompt Files And Docs

Prompt files under `docs/prompts/` are institutional memory. Use one for
non-obvious bugs, multi-file changes, architectural shifts, or new features.
Small typos, obvious one-line fixes, lint/style cleanups, and roadmap edits do
not require a prompt file.

Prompt scaffold:

1. Context
2. Starting State
3. Task
4. Verification
5. Outcomes or follow-ups when the task is done

Keep docs coupled to structural code changes. The installed hooks enforce this:

- Migration changes touch `ARCHITECTURE.md` section 4.2 or lineage YAML.
- New `dal/` or `extractors/` files update `docs/data-lineage/events.yaml`.
- `backend/result_writer.py` pipeline edits update architecture if ordering or
  steps change.
- New page files update `ARCHITECTURE.md` section 6.2.
- Verified roadmap work updates `ROADMAP.md` or `ROADMAP_ARCHIVE.md`.

Do not use `--no-verify`. If a docs check must be bypassed, use an accountable
`SKIP_DOCS_CHECK="<reason>"` or `Skip-Docs-Check: <reason>` trailer.

## Commands

Run from repo root unless noted:

```powershell
$env:SENTRY_DB_PATH = "$PWD\data\dummy.db"
$env:SENTRY_DB_MODE = "trusted"
python backend/api_server.py
uvicorn backend.api_server:app --reload
python scripts/seed_dummy_data.py
python scripts/audit_number_trust.py --db $env:SENTRY_DB_PATH
python scripts/audit_number_trust_dom.py --db $env:SENTRY_DB_PATH --frontend-url http://127.0.0.1:1420
pytest tests/ -x --tb=short
ruff check backend dal extractors tests
```

Frontend:

```powershell
cd frontend
npm install
npm run build
npm run tauri dev
```

Targeted backend tests from `docs/COMMANDS.md`:

```powershell
pytest tests/test_dal.py -x --tb=short
pytest tests/test_comprehensive.py -x --tb=short
pytest tests/test_reconciliation.py -x --tb=short
pytest tests/test_owner_scoping.py -x --tb=short
pytest tests/test_attribution.py -x --tb=short
pytest tests/test_t02_document_drop.py -x --tb=short
pytest tests/test_t04_mypay.py -x --tb=short
```

## Verification Expectations

Always verify the area changed:

- Docs-only: review for accuracy against code and architecture docs.
- Backend API/DAL: run targeted tests for touched modules.
- DAL, migrations, reconciliation, derived metrics, connectors, or pipeline:
  run the full backend suite before calling complete.
- Frontend: run `npm run build` and targeted checks; use browser verification
  for visual or interaction work when practical.
- New migrations: verify fresh initialization and upgrade behavior.

Report any tests not run, why, and residual risk.

## Audits And Known Risk Areas

Audit docs are under `docs/audits/` and `docs/dashboard-click-audit.md`.
Recurring hotspots include owner scoping, PII/log redaction, frontend token
drift, accessibility/focus states, N+1 report queries, API contract drift, and
type escape hatches.

`docs/data-lineage/ACTION_ITEMS.md` is currently clear of open items as of
2026-04-27, with resolved items retained for audit trail. If lineage work finds
new out-of-scope issues, add an `AI-NNN` entry immediately instead of burying it
in session notes.

## Git And Safety

- The user may have uncommitted work. Never revert changes you did not make.
- Keep one primary task per session. Incidental cleanup is okay only when it
  touches the same path.
- Small doc/meta edits can stay on `main`; complex multi-file/schema/connector
  work should happen on a named branch from clean `main`.
- Do not delete branches or unique unmerged work without explicit confirmation.
- Do not run destructive commands or data wipes without explicit confirmation.
- Avoid broad filesystem searches through generated/vendor folders when a
  narrower path works.

## When Unsure

Use this order of truth:

1. Live code and tests for executable behavior.
2. `docs/ARCHITECTURE.md` for intended architecture.
3. `docs/ROADMAP.md` for current status and priority.
4. Prompt files for historical reasoning.
5. Data-lineage YAML/index for event fan-out and UI impact.

If docs and code disagree, call out the drift and either fix the doc as part of
the task or mention it in the task summary.
