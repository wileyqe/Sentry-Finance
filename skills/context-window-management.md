---
name: context-window-management
description: How to load context efficiently when working with AI agents on this codebase — structured hierarchy to maximize signal while minimizing noise.
---

# Context Window Management

## The Core Problem

This project currently spans **~80 Python files across 7 packages**, plus config, skills docs, and the database schema. Loading every file in a prompt is a guaranteed way to make an agent lose the thread of the architecture — it will mix up the connector layer with the DAL, treat `run_all.py` as canonical when the API path is preferred, and generally get confused by the volume.

The solution is a strict, **three-level context hierarchy**. Use only the level you need for the task at hand.

---

## Level 1 — The Map (Global Context)

**What to provide:** The directory tree only. No file contents.

**Goal:** Orient the agent to where things live without burning tokens on implementation details.

```powershell
# Generate the project map (excludes noise directories)
Get-ChildItem -Recurse -File |
  Where-Object { $_.FullName -notmatch '\\.(venv|git|__pycache__|data|profiles|raw_exports)\\' } |
  Select-Object -ExpandProperty FullName |
  ForEach-Object { $_.Replace((Get-Location).Path + '\', '') } |
  Sort-Object
```

**When to use:** Starting a new session, orienting after a long conversation, or asking "where does X live?"

**Key packages to call out in the tree:**

| Directory | What it is |
|-----------|-----------|
| `dal/` | Data Access Layer — all SQLite reads/writes |
| `dal/migrations/` | One file per schema version (V1–V10) |
| `extractors/` | Institution connectors (Playwright automation) |
| `backend/` | FastAPI app, orchestrator, SSE event bus |
| `backend/routers/` | One router per domain (accounts, budgets, etc.) |
| `config/` | YAML-based settings (accounts, categories, owners) |
| `skills/` | Agent guidance docs (like this one) |
| `tests/` | DAL test suite — run with `.venv/Scripts/python tests/test_dal.py` |

---

## Level 2 — The Skeleton (Structural Context)

**What to provide:** Class and function signatures only — `def` lines plus their docstrings, with logic bodies omitted.

**Goal:** Let the agent understand *what is available* without the *how*. Crucial before writing new code that calls existing functions.

**How to generate a skeleton for a module:**

```powershell
# Print all def/class lines + their docstrings from a file
python -c "
import ast, sys
tree = ast.parse(open(sys.argv[1]).read())
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        ds = ast.get_docstring(node) or ''
        print(f'  Line {node.lineno}: def {node.name}()')
        if ds:
            print(f'    \"\"\"{ds[:80]}\"\"\"')
" path/to/module.py
```

**Key skeletons to load before common tasks:**

| Task | Load skeleton for |
|------|--------------------|
| Writing a new DAL query | `dal/connection.py`, target DAL module |
| Adding an API endpoint | `backend/routers/<domain>.py`, relevant DAL module |
| Adding a new connector | `extractors/base_connector.py`, `extractors/__init__.py` |
| Changing the schema | `dal/migrations/__init__.py`, highest existing `v??_*.py` |
| Touching the post-refresh pipeline | `backend/result_writer.py` |

---

## Level 3 — The Focus (Operational Context)

**What to provide:** Full content of the specific file being edited **plus** its immediate import neighbors.

**Goal:** Give the agent complete, unambiguous knowledge of the code it's about to change.

**The "neighbors" rule for this project:**

- Editing `dal/goals.py` → also load `dal/connection.py` (knows the contract) and `backend/routers/goals.py` (knows what the caller commits)
- Editing a migration file → also load `dal/migrations/__init__.py` (the runner that discovers it)
- Editing a connector → also load `extractors/__init__.py` (the registry) and `extractors/base_connector.py` (the contract)
- Editing a router → also load the corresponding DAL module (what functions exist) and `backend/events.py` (if SSE-related)

---

## The `.contextignore` — Never Load These

The following should **never** appear in an agent's context unless explicitly debugging them:

```
.venv/                  # 10,000+ files, zero project signal
__pycache__/            # Compiled bytecode
.git/                   # Git internals
data/                   # Live SQLite DB and extracted CSVs
data/extracted/         # Raw connector output files
profiles/               # Playwright browser session storage
raw_exports/            # Downloaded CSVs from institutions
logs/                   # Runtime logs
*.db                    # Database binary
*.db-wal                # WAL journal files
*.db-shm                # Shared memory files
screenshots/            # Debug screenshots from connectors
```

> **Rule:** If a directory would be in `.gitignore`, it should also be in the mental `.contextignore`. The project `.gitignore` is a reliable reference.

---

## Token Budgeting

| Context tier | Recommended token allocation |
|---|---|
| Level 1 (tree) | ≤ 5% of window |
| Level 2 (skeletons) | ≤ 15% of window |
| Level 3 (full files) | ≤ 30% of window |
| **Task / active work** | ≥ 50% of window |

**Hard limits for this project:**
- Never load more than **3 full files** in a single prompt unless the task explicitly requires cross-file reasoning
- Never load `dal/derived.py` and `dal/investments.py` in the same context — they're large and mostly independent; load only the module relevant to the task
- The test file (`tests/test_dal.py`, ~1,200 lines) should only be loaded when debugging a test failure — summarize it otherwise

---

## Summary Chaining (for Very Long Sessions)

When a session has been running long enough that the conversation history is eating context budget, use a **folder summary** instead of re-reading files.

**Standard folder summaries for this project:**

> **`dal/`** — SQLite DAL for Sentry Finance. Core modules: `connection.py` (WAL-mode `get_db()` context manager), `migrations/` (auto-discovery runner, v01–v10 schema), `seed.py` (institutions from `accounts.yaml`). Business logic split by domain: `transactions`, `balances`, `derived`, `categorization`, `recurring`, `budgets`, `alerts`, `goals`, `investments`, `performance`, `allocation`, `debt`, `forecasting`, `reports`. Convention: functions receive `conn`, never commit internally — callers commit.

> **`backend/`** — FastAPI app + automation orchestration. `api_server.py` is a 115-line stub that registers 9 routers from `backend/routers/`. `result_writer.py` is the shared persistence layer used by both `run_all.py` (dev CLI) and `automation_worker.py` (API-triggered). `refresh_orchestrator.py` manages the staleness check and sequential institution run. `events.py` is the SSE pub/sub bus. Credentials always flow through `credential_broker.py`.

> **`extractors/`** — Playwright-based institution connectors. `CONNECTOR_REGISTRY` dict in `__init__.py` is the single source of truth for available institutions. `base_connector.py` defines the `InstitutionConnector` contract: `_launch()` context manager, `open_transient_tab()` for popup handling, `ConnectorResult` dataclass. Active connectors: NFCU, Chase, Acorns, Fidelity, Affirm. AI self-healing backed by `selector_registry.yaml` + Gemini.

> **`skills/`** — Agent guidance docs. `SKILL.md`: connector architecture and lifecycle. `dev-session-cleanup.md`: end-of-session checklist (docs → cleanup → compile check → commit to main). `new-connector-playbook.md`: step-by-step for adding a new institution. `context-window-management.md`: this document.

---

## Practical Loading Checklist

Before starting any task, answer these three questions:

1. **What is the entry point?** (Which file gets changed first?)
2. **What does it import?** (Those are your skeleton candidates)
3. **What calls it?** (That's your commit-convention context)

Then load:
- [ ] Level 1 tree if session is new
- [ ] Skeleton of the module being changed
- [ ] Full content of the 1–3 files being directly edited
- [ ] Skeleton of any file that *calls* the code you're changing (to understand commit ownership)
- [ ] Nothing from `.contextignore`
