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

1. **This file (CLAUDE.md)** --- operating manual, guardrails, pointers.
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
   task summary is insufficient. See `docs/prompts/README.md` for the
   phase index, authoring policy, and exceptions.
5. **Code, tests, migrations** --- ground truth for anything the docs
   lag. Read before editing.

Reference companions (load only when relevant to the task):

- `docs/DESIGN.md` --- UI design system: Ember palette, Newsreader /
  Inter / JetBrains Mono typography, component catalog (Built +
  Planned primitives), Do's and Don'ts. Load before any `frontend/**`
  work.
- `docs/HOUSEHOLD_PROFILE.md` --- owner context, accounts, income streams,
  property, credit cards, BNPL philosophy, TSP posture
- `docs/DUMMY_DATA_GENERATION_SPEC.md` --- rolling seeder design and
  determinism invariants
- `docs/SUPERPOWERS_TRIGGERS.md` --- confidence tiers for the structured
  workflow framework
- `docs/COMMANDS.md` --- environment setup, backend/frontend startup,
  test matrix, seeder

If architecture docs and live code disagree, use:

- `docs/ARCHITECTURE.md` for design intent and system boundaries
- current code for executable truth such as entrypoints, commands, router names,
  migration count, and module layout

Do not copy stale claims forward. If a mismatch matters, fix the doc or call it
out in the task summary.

## Claude's Job

Default working model:

- Keep one primary task per session
- Allow small, tightly related cleanup discovered during the task
- Use `docs/ROADMAP.md` as the primary status tracker
- When working a roadmap task: read the prompt file if one exists, keep scope
  aligned, update status only after verification

**Prompt files** (`docs/prompts/<phase>/`) are institutional memory. Before
implementing any non-trivial task, author (or locate) a prompt file using the
five-section scaffold. The authoring policy, exception list, and phase index
live in `docs/prompts/README.md`.

## Structured Workflow Framework

This repo uses the Superpowers plugin (`obra/superpowers-marketplace`) as the
opt-in structured workflow framework for multi-step work. Do not invoke
specific Superpowers skills by name --- they activate from context.

**Rule:** if you land below 85% confident the framework adds value, ask the
user before using it. Confidence triggers (high / medium / low) live in
`docs/SUPERPOWERS_TRIGGERS.md` --- load when deciding whether to lean on the
framework.

## Project Shape

`docs/ARCHITECTURE.md` §3 covers the process model, module layout, and the
post-ingestion pipeline. Two project-critical details live here because they
describe regression traps that are not obvious from reading the code:

- **Owner scoping is a first-class path end-to-end** (DAL → API → frontend).
  The `[Quintin | Household | Amy]` chip switcher renders unconditionally;
  Amy's view is a verified empty-state harness until her real data ingests.
  Every new query, endpoint, and page MUST thread `owner_id`. Use
  `dal/owners.build_account_filter(owner_id, account_ids)` which distinguishes
  `None` (no filter) from `[]` (owner-owns-nothing short-circuit via `AND 1=0`)
  --- the `if not account_ids:` truthy-list shortcut is a regression.
- **The rolling investment seeder** (`scripts/dummy_data/generator.py::generate_investment_history`)
  uses deterministic linear price drift (VTI +1.5/mo, VXUS +0.3/mo, BND −0.1/mo
  from fixed base prices), while the benchmark TWR shown on the Investments
  tab comes from live yfinance data via
  `dal/performance.get_benchmark_monthly_returns`. The seeded portfolio will
  appear to significantly underperform the S&P 500 in the "Performance vs.
  Benchmarks" cards --- mathematically correct but cosmetically misleading.
  Any reshape of the generator to match benchmark volatility is an explicit
  design decision, not a bug fix.

Before assuming a schema version or module layout, check the migration directory
and current entrypoints --- ARCHITECTURE may lag.

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

Soft guardrails: surface git state and offer options, do not block or resolve
unilaterally. Parallel work silently written against a stale `main` is the
most common source of regressions.

**Alert triggers** (at session start or before new work):

- Working tree has uncommitted or untracked changes
- More than one local branch, or more than one registered worktree
- Local `main` differs from `origin/main`
- Any non-main branch has > 10 commits of `main` ahead of its merge base

**What not to allow:**

- Starting feature work before `main` is confirmed clean and synced.
- A second active branch while the first is unmerged, unless named as an
  explicit parallel effort.
- Mixing small edits (doc, one-file, meta) with complex work (multi-file,
  schema, connector, phase-tracked) on the same branch --- small goes to
  `main`, complex goes to a named branch off clean `main`.
- Creating a worktree without naming the files it will touch and surfacing
  overlap with edits elsewhere; decide who wins before parallel edits begin.
- Deleting a branch holding unique unmerged work without explicit confirmation.
- Merging a worktree branch back without reviewing its diff against current
  `main` for schema/PII/sign-convention/dependency drift.

## Working Style

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

## Done Means

Before closing a task, make sure:

- the implementation matches the current architecture and repo structure
- tests or checks appropriate to the changed area have been run
- any important doc drift discovered during the task has been corrected or noted
- `docs/ROADMAP.md` is updated if the task maps to a tracked roadmap item
- if the prompt file policy required a prompt file for this task, it has
  been authored and updated to reflect what was actually built (outcomes,
  surprises, follow-ups) --- not just what was originally planned
