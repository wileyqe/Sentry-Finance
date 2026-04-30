# Claude Operating Manual

## Mission

Sentry Finance is a local-first personal finance command center for a single
household. It is not a static dashboard. Every feature, bug fix, and design
decision should help answer: "What should I do differently?"

Optimize for decision support, trend visibility, data trust, and forward-looking
insight. Prefer work that improves actionability over work that only adds more
numbers to the screen.

## Read Order

Start narrow, widen on demand. **Do not load companion docs unless the
task touches their domain.**

1. **This file** --- operating manual, guardrails, pointers.
2. **`docs/ROADMAP.md`** --- pick the next `[ ]`/`[!]` task. **If a
   `P0-*` entry is open, it's the only eligible task.** A `Prompt:`
   line points to `docs/prompts/<phase>/<file>.md` when one exists.
3. **`docs/ARCHITECTURE.md`** --- scan the TOC, open only the sections
   the task touches. Most sessions need 2--3 sections, not the whole doc.
4. **Code / tests / migrations** --- ground truth when docs lag.

**Companions, loaded on demand only:**

- `DESIGN.md` --- before any `frontend/**` work
- `HOUSEHOLD_PROFILE.md` --- owner-specific rules (mortgage, TSP, partner)
- `DUMMY_DATA_GENERATION_SPEC.md` --- seeder changes
- `COMMANDS.md` --- env / server / test commands
- `data-lineage/HOWTO.md` --- "where does this number come from?"
  questions; `ACTION_ITEMS.md` is the known-bug audit log
- `prompts/README.md` --- the prompt-file index and authoring policy

If docs and live code disagree, prefer code for executable truth
(entrypoints, router names, migration count, module layout); prefer
ARCHITECTURE for design intent. Fix drift in the doc or call it out
in the task summary --- do not copy stale claims forward.

## Graph Context Check

Graphify is a cheap context map for "what else might be connected?" Use it to
avoid misaligned edits, not as a permission gate. Live code and tests remain
executable truth; `docs/ARCHITECTURE.md` remains design truth; `docs/ROADMAP.md`
remains status truth.

Run a graph check before non-trivial edits, multi-file changes, roadmap tasks,
DAL/API/frontend data-flow work, connector/parser work, schema/migration work,
PR merge/rebase work, or whenever blast radius is unclear. It is optional for
typos, tiny doc fixes, obvious one-line fixes, generated report updates, and
narrow test-only changes.

Common commands:

```powershell
python tools\graphify\query_local.py search "<term>"
python tools\graphify\query_local.py impact "<task or concept>"
python tools\graphify\query_local.py neighbors "<node or term>"
python tools\graphify\query_local.py hubs --limit 10
python tools\graphify\query_local.py drift --min-confidence 0.85
python tools\graphify\query_local.py quality
```

- Use `impact` at task start to find related files, tests, docs, and lineage.
- Use `hubs` before editing shared functions or highly connected modules.
- Use `drift` when changing invariants, docs, category rules, lineage, or
  number-trust assets.
- If the graph is stale, missing, or contradicts live code, proceed from
  code/tests and mention the graph limitation in the summary.
- For graph refresh/extraction details, see `tools/graphify/README.md`; do not
  duplicate that workflow here.

## Claude's Job

Default working model:

- Keep one primary task per session
- Allow incidental cleanup that touches the same code path as the primary
  task (renames, dead-code removal, comment fixes); defer larger refactors
  or unrelated drift to a follow-up task
- Use `docs/ROADMAP.md` as the primary status tracker
- When working a roadmap task: read the prompt file if one exists, keep scope
  aligned, update status only after verification

**Prompt files** (`docs/prompts/<phase>/`) are institutional memory. Before
implementing any non-trivial task, author (or locate) a prompt file using the
five-section scaffold. The authoring policy, exception list, and phase index
live in `docs/prompts/README.md`.

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
- **Canonical investment seed direction:** the canonical audit seed now uses
  round starting balances plus deterministic monthly transfers only. Acorns
  starts at `$10,000` and receives `$500/mo`; Fidelity starts at `$50,000` and
  receives `$1,000/mo`; TSP starts at `$100,000` and receives `$1,500/mo`.
  No canonical seed growth, losses, dividends, sells, roundups, fees, or
  price-driven variance should be preserved as a design goal. Market realism
  belongs to later live-data or separately audited investment work.
- **Synthetic and live dates share one reference-clock contract:** date-sensitive
  finance windows/defaults use `dal.clock.reference_date()` /
  `reference_datetime()` on the backend and `RuntimeContext.referenceDate` in
  React. The trusted seed pins that clock; live mode currently falls back to
  real current time through the same path. Keep connector `as_of`, posting
  dates, statement dates, refresh timestamps, and event timestamps as separate
  data facts. Run `python scripts/audit_reference_clock_usage.py` after
  timeframe/default-date changes.

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

## Doc-Coupling Gate

The pre-commit + commit-msg hooks (installed by
`scripts/install_hooks.sh`) refuse commits where structural code
changes lack a matching doc update. Plan the doc edit alongside the
code, not after.

- **New / changed migration** → touch `ARCHITECTURE.md` §4.2 or a
  `data-lineage/lineage/*.yaml`
- **New file under `dal/` or `extractors/`** → update
  `data-lineage/events.yaml`
- **Edit to `backend/result_writer.py`** → re-read `ARCHITECTURE.md`
  §3.4 and update if pipeline steps changed
- **New `frontend/src/pages/*.tsx`** → add to `ARCHITECTURE.md` §6.2
- **Commit message contains `[v]` or "Verified"** → touch `ROADMAP.md`
  or `ROADMAP_ARCHIVE.md`
- **Lineage freshness** runs unconditionally; if `check_freshness.py`
  drifts the generated artifacts, re-stage them.

Bypass only with a deliberate, accountable signal:
`SKIP_DOCS_CHECK="<reason>" git commit ...` (env var) or a
`Skip-Docs-Check: <reason>` trailer in the commit message. Agents
must not use `--no-verify`.

## Branch & Worktree Hygiene

Load `docs/agent-rules/branch-hygiene.md` before starting new work or when
git state looks off. It enumerates the alert triggers (dirty tree, stale
main, parallel branches) and the actions to refuse without confirmation.

## Working Style

- For connector work, prefer self-contained changes inside `extractors/` and the
  associated writer or parser path.
- For analytical work, preserve transfer exclusions, owner scoping, and integer
  amount handling.

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
