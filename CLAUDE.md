# Claude Operating Manual

## Mission

Sentry Finance is a local-first personal finance command center for a single
household. It is not a static dashboard. Every feature, bug fix, and design
decision should help answer: "What should I do differently?"

Optimize for decision support, trend visibility, data trust, and forward-looking
insight. Prefer work that improves actionability over work that only adds more
numbers to the screen.

## Read Order

Start narrow, widen on demand. Each step is smaller than the next:

1. **This file (CLAUDE.md)** --- operating manual, guardrails, commands.
2. **`docs/ARCHITECTURE.md`** --- design intent, system boundaries, and
   enforced invariants. Scan the top-of-file Table of Contents first and
   only open the sections the current task actually needs. Most sessions
   touch 2--3 sections, not the whole doc.
3. **`docs/ROADMAP.md`** --- find the next `[ ]` or `[!]` task. Every
   task entry has a `Prompt:` line pointing to a file under
   `docs/prompts/` when one exists. **Check the Priority 0 section at
   the top first.** If an open `P0-*` entry exists, it is the only
   eligible task until it flips to `[v]`; do not start any numbered
   phase task ahead of it.
4. **`docs/prompts/<phase>/<file>.md`** --- load only when ROADMAP's
   task summary is insufficient. This folder is institutional memory,
   not required reading. See `docs/prompts/README.md` for the phase
   index.
5. **Code, tests, migrations** --- ground truth for anything the docs
   lag. Read before editing.

Reference companions (load only when relevant to the task):

- `docs/HOUSEHOLD_PROFILE.md` --- owner context, accounts, income streams,
  property, credit cards, BNPL philosophy, TSP posture
- `docs/DUMMY_DATA_GENERATION_SPEC.md` --- rolling seeder design and
  determinism invariants

If architecture docs and live code disagree, use:

- `docs/ARCHITECTURE.md` for design intent and system boundaries
- current code for executable truth such as entrypoints, commands, router names,
  migration count, and module layout

Do not copy stale claims forward. If a mismatch matters, fix the doc or call it
out in the task summary.

## Claude's Job

Claude may plan, implement, verify, and review directly in this repo.

Default working model:

- Keep one primary task per session
- Allow small, tightly related cleanup discovered during the task
- Use `docs/prompts/` for multi-step or review-heavy work
- Use `docs/ROADMAP.md` as the primary status tracker

### Prompt file policy

`docs/prompts/` is the project's canonical institutional memory — why a
decision was made, the starting state, how it was verified. **Before
implementing any non-trivial task, author (or locate) a prompt file in
`docs/prompts/<phase>/` using the 5-section scaffold documented in
`docs/prompts/README.md`.** The test: if you'd want to reconstruct the
reasoning six months from now, it gets a prompt.

**Exceptions** — no prompt file required:

- Typos, docstring tweaks, comment edits, lint/style/type cleanups
- One-line or few-line bug fixes with obvious root cause
- ROADMAP status updates and prompt-file authoring itself (meta)
- Small, tightly related cleanup discovered mid-task (already allowed
  under the working model above)

Non-obvious bug fixes, multi-file changes, architectural shifts, and new
features are NOT exceptions — those are exactly the work that produces
institutional memory worth keeping.

When working on a roadmap task:

- read the prompt file if one exists
- keep scope aligned to that task
- update the roadmap status only after verification

## Structured Workflow Framework

This repo uses the Superpowers plugin (`obra/superpowers-marketplace`) as the
opt-in structured workflow framework for multi-step work. Superpowers provides
auto-activating skills for brainstorming, plan writing, subagent dispatch,
worktree isolation, TDD cycles, and root-cause debugging. **Do not invoke
specific Superpowers skills by name** — they activate from context, and this
file should not couple to the framework's internal naming.

Decide whether to lean on the framework using these confidence-rated triggers.
**If you land below 85% confident the framework adds value, ask the user before
using it.**

### High confidence — use the framework (≥85%)

- Multi-phase initiatives spanning backend + DAL + frontend (e.g. the data
  accuracy overhaul, a new connector build, a schema-shaped feature)
- Any change touching `dal/migrations/` plus reconciliation, derived metrics,
  or the post-commit pipeline
- New extractor/connector from scratch, including parser + writer + tests
- Refactors crossing 3+ architectural seams (router → DAL → orchestrator →
  connector)
- Work the user explicitly scopes via a new `docs/prompts/` file

### Medium confidence — ask first (<85%)

- Single-area but non-trivial bug fixes where root cause is unclear
- New parser variant for an existing connector
- A new API endpoint with non-trivial validation, SSE events, or DAL changes
- Frontend feature contained to one component tree but with new state shape
- Performance work in a hot path

### Low / not needed — skip the framework

- Doc-only edits, ROADMAP updates, prompt file authoring
- Single-file refactors, renames, typo fixes
- Lint/style cleanups
- Adding a single test case to an existing suite
- Config tweaks, dependency bumps
- Anything already scoped to a "small, tightly related cleanup" per the
  working model above

## Current Project Shape

Keep these repo truths in mind:

- Backend: FastAPI app in `backend/api_server.py` with REST + SSE
- Frontend: React + TypeScript + Tauri in `frontend/`
- Storage: SQLite through the DAL in `dal/`
- Migrations: sequential numbered modules in `dal/migrations/`
- Connectors: institution-specific automation in `extractors/`
- Post-ingestion pipeline: `backend/result_writer.py`
- Refresh lifecycle: `backend/refresh_orchestrator.py`
- Credential elevation boundary: `backend/credential_broker.py` plus IPC
- Document drop and MFA bridge are first-class ingestion paths, not side features
- Owner scoping is a first-class path end-to-end (DAL → API → frontend).
  The `[Quintin | Household | Amy]` chip switcher renders unconditionally;
  Amy's view is a verified empty-state harness until her real data ingests.
  Every new query, endpoint, and page MUST thread `owner_id`. Use
  `dal/owners.build_account_filter(owner_id, account_ids)` which distinguishes
  `None` (no filter) from `[]` (owner-owns-nothing short-circuit via `AND 1=0`)
  — the `if not account_ids:` truthy-list shortcut is a regression.
- The rolling investment seeder (`scripts/dummy_data/generator.py::generate_investment_history`)
  uses deterministic linear price drift (VTI +1.5/mo, VXUS +0.3/mo, BND −0.1/mo
  from fixed base prices), while the benchmark TWR shown on the Investments tab
  comes from live yfinance data via `dal/performance.get_benchmark_monthly_returns`.
  This means the seeded portfolio will appear to significantly underperform the
  S&P 500 in the "Performance vs. Benchmarks" cards — mathematically correct but
  cosmetically misleading. Any reshape of the generator to match benchmark
  volatility is an explicit design decision, not a bug fix.

The architecture doc may lag exact implementation details. Before assuming a
schema version or module layout, check the migration directory and the current
entrypoints.

## Non-Negotiable Guardrails

- Do not add direct application queries outside the DAL unless you are writing
  migrations or isolated test setup.
- Never modify schema shape ad hoc. Add a new sequential migration instead.
- Store money as integer cents. Do not use floats for financial amounts.
- Honor the canonical sign convention on transactions: `signed_amount < 0`
  ⟺ `direction = 'Debit'`, `signed_amount > 0` ⟺ `direction = 'Credit'`,
  `amount` is the absolute value. All writes go through
  `dal.transactions.upsert_transactions()` which fails fast on drift.
  All analytical aggregates that compute income or spending must use the
  blacklist + sign-check pattern (`signed_amount` plus `transfer_tag IS NULL`
  plus the relevant exclusion set from `dal/category_classifications.py`).
  Do **not** introduce new aggregates that follow the legacy
  `SUM(CASE WHEN direction = 'Debit' THEN amount ...)` shape — it ignores
  refunds and disagrees with the canonical pattern. See
  `docs/ARCHITECTURE.md` §4.6 and `tests/test_cashflow_invariants.py`.
- Budgets are household-only as of migration v23. Do not re-introduce an
  `owner_id` parameter on the budgets DAL, router, or UI — the partial unique
  index `idx_budgets_household_unique ON budgets(category, month) WHERE
  owner_id IS NULL` will fail the write, and the
  `tests/test_budgets_household.py` invariant suite will break. Household
  roll-up is the only supported granularity; the previous per-owner model was
  called out as an architectural mistake and reversed.
- Store persisted dates and timestamps in UTC-friendly formats used by the repo;
  local formatting belongs at the UI edge.
- Keep institution-specific logic inside that institution's connector or parser,
  not in shared modules.
- Connector failures must not take down the overall refresh flow. Catch, log, and
  continue where the architecture expects isolation.
- Respect the post-commit pipeline after connector writes: categorization,
  reconciliation, recurring detection, derived recompute, alerts, and goal sync.
- Do not introduce new SSE event shapes casually. Keep topic/action naming
  consistent and update the registry or event contract when needed.
- Treat institution data, imported documents, and scraped values as untrusted
  input. Validate and sanitize before writing to the database.
- Keep credentials out of code, config, fixtures, and logs. Use the broker,
  keyring, or approved environment flow.
- Preserve local-first behavior. Do not add cloud dependencies, telemetry, or
  remote persistence without an explicit architecture change.

## Branch & Worktree Hygiene

Soft guardrails: alert the user and offer options, do not block or
resolve unilaterally. The goal is to surface git state the user may
not be holding in their head, and to prevent parallel work from
colliding at merge time.

### Alert triggers (at session start, or before new work)

- Working tree has uncommitted or untracked changes
- More than one local branch exists
- More than one worktree is registered
- Local `main` differs from `origin/main`
- Any non-main branch has > 10 commits of `main` ahead of its merge
  base — stale-candidate; the older the branch, the higher the
  conflict cost

On any of the above, surface the state and propose options before
proceeding.

### What not to allow

- Do not start feature work without confirming `main` is clean and
  synced.
- Do not open a second active branch while the first is unmerged,
  unless the user names it as an explicit parallel effort.
- Do not mix small edits with complex work on the same branch. Small
  edits (doc, one-file, meta-policy) go to `main`. Complex work
  (multi-file, schema, connector, phase-tracked) goes to one named
  branch off a clean `main`.
- Do not create a worktree without naming the files it will modify
  and surfacing any overlap with files edited elsewhere in the repo.
  If overlap exists, decide with the user which side wins before
  parallel edits begin — never discover the conflict at merge time.
- Do not delete a branch that holds unique unmerged work without
  explicit user confirmation.
- Do not merge a worktree branch back without reviewing its diff for
  edits written against an older `main` (schema shape, PII policy,
  sign convention, dependency pins). Stale worktrees are the most
  common source of regressions that reintroduce work `main` has fixed.

## Working Style

- Read before editing. Understand the flow end-to-end before changing shared
  modules.
- Prefer explicit, readable code over clever shortcuts.
- Preserve existing architectural seams: routers call DAL, orchestrators manage
  flow, connectors ingest, result writers trigger downstream recompute.
- For connector work, prefer self-contained changes inside `extractors/` and the
  associated writer or parser path.
- For analytical work, preserve transfer exclusions, owner scoping, and integer
  amount handling.
- For frontend work, keep the desktop-app context in mind: freshness,
  notifications, drill-downs, and decision support matter more than decorative
  dashboard polish.

## Verification Rules

Always verify the area you changed.

- Docs-only changes: review for accuracy against current code and architecture
  docs; no code tests required.
- Backend API or DAL changes: run relevant tests for the touched modules.
- DAL, migration, reconciliation, derived-metric, or connector changes: run the
  full backend suite before commit.
- Frontend changes: run the build and any targeted frontend tests that exist.
- New migrations: verify both clean initialization and upgrade behavior.

Do not mark a task complete until verification is done.

## Environment Setup

- Python 3.14 — uses system Python (no virtualenv)
- Install dependencies: `pip install -r requirements.txt`
- SQLite database: `data/sentry.db` (override with `SENTRY_DB_PATH` env var)
- Credentials: stored in Windows Credential Manager via
  `python backend/credential_broker.py --store <institution>`
- `.env` holds non-secret config (Chrome profile path, API keys for AI backstop).
  Never commit `.env` — use `.env.example` as the template.

## Command Reference

Run these from the repo root unless noted otherwise.

```bash
# Backend API (also runs migrations on startup)
python backend/api_server.py

# Backend API with reload
uvicorn backend.api_server:app --reload

# Frontend desktop app
cd frontend && npm install   # first time only
cd frontend && npm run tauri dev

# Frontend build check (no Tauri)
cd frontend && npm run build

# Full backend test suite
pytest tests/ -x --tb=short

# Targeted tests by area
pytest tests/test_dal.py -x --tb=short              # DAL / schema / transactions
pytest tests/test_comprehensive.py -x --tb=short    # derived metrics / cash flow / reports
pytest tests/test_reconciliation.py -x --tb=short   # transfer reconciliation
pytest tests/test_phase6.py -x --tb=short            # reviews / lifestyle / investments
pytest tests/test_t04_mypay.py -x --tb=short         # myPay parser
pytest tests/test_t02_document_drop.py -x --tb=short # document drop / parsers
pytest tests/test_owner_scoping.py -x --tb=short     # multi-user isolation
pytest tests/test_attribution.py -x --tb=short       # income attribution

# Apply migrations explicitly (not usually needed — api_server does this)
python -c "from dal.database import init_db; init_db()"

# Lint Python code
ruff check backend dal extractors tests

# Load 3-year dummy dataset (safe to re-run — clears seeded data first)
python scripts/seed_dummy_data.py
```

Notes:

- `backend/api_server.py` already calls `init_db()` on startup
- use targeted tests during development, then the full backend suite for DAL or
  integration work
- `dummy_data/` holds static structural fixtures (owners, institutions,
  recurring patterns, savings goals, real estate, vehicles, loans);
  transactional data (transactions, balance snapshots, budgets, credit scores,
  portfolio snapshots, investment holdings) is generated rolling by
  `scripts/dummy_data/generator.py` via `python scripts/seed_dummy_data.py`

## Done Means

Before closing a task, make sure:

- the implementation matches the current architecture and repo structure
- tests or checks appropriate to the changed area have been run
- any important doc drift discovered during the task has been corrected or noted
- `docs/ROADMAP.md` is updated if the task maps to a tracked roadmap item
- if the prompt file policy required a prompt file for this task, it has
  been authored and updated to reflect what was actually built (outcomes,
  surprises, follow-ups) — not just what was originally planned
