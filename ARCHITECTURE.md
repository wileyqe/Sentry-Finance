# Sentry Finance — Architecture Overview

> **Living document.** Update when major design decisions are made.
> Last updated: 2026-02-18

## Mission

Local-first personal finance dashboard. Replace flaky third-party aggregators
with direct browser automation against financial institutions. Prioritize
security, minimal manual intervention, and concurrent UI responsiveness.

## System Diagram

```
┌─────────────────── User's Machine (Windows) ───────────────────┐
│                                                                │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐  │
│  │   Frontend    │───▶│  API Server      │───▶│  SQLite DB   │  │
│  │  (Phase 8)    │    │  FastAPI :8000    │    │  WAL mode    │  │
│  └──────────────┘    └────────┬─────────┘    └──────────────┘  │
│                               │ SSE + REST            ▲        │
│                               ▼                       │        │
│                      ┌──────────────────┐             │        │
│                      │  Refresh         │  writes ────┘        │
│                      │  Orchestrator    │                      │
│                      └────────┬─────────┘                      │
│                  ┌────────────┼────────────┐                   │
│                  ▼            ▼            ▼                   │
│           ┌───────────┐ ┌──────────┐ ┌──────────┐             │
│           │ NFCU      │ │ Chase    │ │ Affirm   │  ...        │
│           │ Connector │ │Connector │ │Connector │             │
│           └─────┬─────┘ └────┬─────┘ └────┬─────┘             │
│                 │            │            │                    │
│                 └──────┬─────┘            │                    │
│                        ▼                  ▼                    │
│              ┌───────────────┐   ┌──────────────┐             │
│              │ Chrome (CDP)  │   │ Manual Login  │             │
│              │ + Broker      │   │ (SMS/MFA)     │             │
│              │   Creds       │   └──────────────┘             │
│              └───────────────┘                                │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Credential Broker (elevated, short-lived)               │  │
│  │  UAC → keyring (WinVaultKeyring) → IPC → exit            │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

## Trust Boundaries & Process Separation

| Process | Privilege | Lifetime | Role |
|---|---|---|---|
| **API Server** | Non-privileged | Long-running | Serves dashboard data, SSE events |
| **Refresh Orchestrator** | Non-privileged | Per-session | Staleness check, state machine, retry logic |
| **Automation Worker** | Non-privileged | Per-institution | Playwright → connector → SQLite |
| **Credential Broker** | **Elevated (UAC)** | **Seconds** | keyring read → IPC → exit. Never logs secrets. |

## Data Flow

```
Credential Broker → (IPC/JSON) → Orchestrator → Worker → Connector
                                                           │
                                              ┌────────────┤
                                              ▼            ▼
                                         Balances    Transactions
                                              │            │
                                              └──────┬─────┘
                                                     ▼
                                               SQLite (DAL)
                                                     │
                                              ┌──────┴──────┐
                                              ▼             ▼
                                         API Server    Derived Metrics
```

## Module Map

| Package | Module | Purpose |
|---|---|---|
| `backend/` | `api_server.py` | FastAPI, 11 endpoints, SSE stream |
| | `refresh_orchestrator.py` | Session lifecycle, staleness, retries |
| | `automation_worker.py` | Connector bridge, SQLite persistence |
| | `credential_broker.py` | UAC-elevated keyring access |
| | `state_machine.py` | RefreshState enum, transitions, error classes |
| | `ipc.py` | JSON stdin/stdout IPC across UAC privilege boundary, memory clearing |
| `dal/` | `database.py` | Schema (9 tables), WAL, migrations, seeding |
| | `transactions.py` | Upsert, SHA-256 identity, pending→posted |
| | `balances.py` | Balance snapshots, loan details |
| | `refresh_log.py` | Durable state machine (refresh_runs, events) |
| | `derived.py` | Scoped metrics (monthly spend/income, net worth) |
| | `migrate_csv.py` | One-time CSV → SQLite migration tool |
| `extractors/` | `nfcu_connector.py` | NFCU browser automation |
| | `chase_connector.py` | Chase browser automation |
| | `ai_backstop.py` | AI-powered selector healing |
| | `dom_healer.py` | DOM analysis for broken selectors |
| | `chrome_cdp.py` | Chrome DevTools Protocol launcher |
| | `selector_registry.yaml` | Centralized CSS selectors |
| `skills/` | `institution_connector.py` | Base class: lifecycle, CDP, MFA wait |
| `config/` | `refresh_policy.yaml` | Per-institution intervals, retries, MFA |

## Key Design Decisions

| Decision | Rationale | Date |
|---|---|---|
| SQLite + WAL over Postgres | Local-first, zero-config, concurrent reads | 2026-02 |
| Windows Credential Manager over .env | OS-level encryption, Windows Hello gate | 2026-02 |
| Separate credential broker process | Minimal privilege scope, UAC per-session | 2026-02 |
| CDP over Playwright-managed browser | Reuse Chrome profiles (session cookies, 2FA trust tokens) — creds via broker, not Password Manager | 2026-02 |
| Selector registry + AI backstop | Self-healing when bank UIs change | 2026-02 |
| Broker creds with autofill fallback | Graceful degradation if broker unavailable | 2026-02 |
| Affirm: SMS OTP manual (Level 1) | No password exists; Phone Link auto-capture planned | 2026-02 |
| Playwright codegen for new connectors | Record journey first, then port to connector framework | 2026-02 |

## Login Strategy Per Institution

| Institution | Auth Method | Broker Creds | MFA | Status |
|---|---|---|---|---|
| NFCU | Username + Password | ✔ Stored | SMS/Push (manual) | Connector built |
| Chase | Username + Password | ✔ Stored | SMS/Push (manual) | Connector built |
| Fidelity | Username + Password | ✔ Stored | — | Connector planned |
| TSP | Username + Password | ✔ Stored | — | Connector planned |
| Acorns | Username + Password | ✔ Stored | — | Connector planned |
| Affirm | Phone + SMS OTP | N/A | SMS code (manual) | Connector planned |

## Building New Connectors

All new connectors follow a **codegen → port → harden** workflow:

### Step 1: Record with Playwright Codegen

```powershell
npx playwright codegen --channel chrome https://www.fidelity.com
```

This opens a browser + inspector panel. Walk through the full journey:
- Login (credential entry → submit → MFA if needed)
- Navigate to accounts / statements / export page
- Download data or identify DOM elements to scrape

Codegen records every click, type, and navigation as Python code with selectors.

### Step 2: Extract the Journey Map

From the generated script, extract:
- **URLs**: login page, dashboard, export/download endpoints
- **Selectors**: username field, password field, submit button, account links
- **Flow branches**: popup dismissals, "remember me" checkboxes, MFA prompts

Add selectors to `extractors/selector_registry.yaml` under the institution key.

### Step 3: Port into Connector Framework

Create `extractors/{institution}_connector.py` extending `InstitutionConnector`:

```python
class FidelityConnector(InstitutionConnector):
    institution = "fidelity"
    login_url = "https://www.fidelity.com/..."

    def _perform_login(self, page, credentials=None):
        # Path A: broker creds → fill fields → submit
        # Path B: fallback to manual entry
        ...

    def _trigger_export(self, page, accounts):
        # Navigate + download / scrape balances
        ...
```

Discard the codegen boilerplate (browser launch, context creation) — the base
class handles all of that via CDP.

### Step 4: Harden

- Add selectors to the registry (not hardcoded in the connector)
- Add conditional branches (session valid? MFA? popups?)
- Wire into `accounts.yaml` and `refresh_policy.yaml`
- Test with `python run_all.py --institutions fidelity`

> [!TIP]
> Codegen selectors are a starting point — bank UIs change frequently.
> Register them in `selector_registry.yaml` so the AI backstop can heal them.

## Resource Management

> Rules enforced by `.agent/rules/resource-session-management.md`.

### Rule 1 — CDP Page Lifecycle

All `InstitutionConnector` implementations **must** ensure any temporary pages or contexts they open are correctly closed. The base class `_launch()` context manager handles this for the primary tab. For any subsequent tabs (e.g., popup windows, new tabs), you **must** use the `open_transient_tab` context manager provided by the base class rather than manually handling `try...finally` blocks:

```python
with self.open_transient_tab(context, trigger=lambda: some_btn.click()) as extra_page:
    # automation logic on the extra_page
    extra_page.wait_for_load_state("networkidle")
# Tab is automatically closed upon exiting the block, preventing zombie tabs
```

**Never close the browser** — it is a persistent singleton shared across all connectors in a session. Only close pages/contexts that your code opened.

### Rule 2 — Single Chrome Instance

`chrome_cdp.py` manages a **single** Chrome process on port 9222. Rules:
- `ensure_chrome_debuggable()` checks if Chrome is already running before launching
- Connectors run **sequentially** — never in parallel — to avoid CDP port conflicts
- Test runners must use `if __name__ == "__main__"` sequential blocks, not `pytest-xdist` or `threading`
- `run_all.py` enforces sequential execution via a simple `for` loop over the connector registry

### Rule 3 — Database Connections

- All write operations use `with get_db() as conn:` — the context manager closes the connection on exit
- DAL write functions (`upsert_transactions`, `record_balance`, `record_loan_details`) take a `conn` and **do not self-commit** — the caller commits after all writes for the session are complete
- Query scripts (one-off diagnostics, migration tools) must use `with get_db() as conn:` — never call `_connect()` directly
- WAL mode is set on every connection in `_connect()` — do not override it

### Live-Mode Checklist

Before a new connector goes into production:

- [ ] `_trigger_export()` has no bare `page = context.new_page()` (must use `with self.open_transient_tab()`)
- [ ] No exception swallowing via bare `except Exception:` (use `log.exception` or specific Playwright `TimeoutError`)
- [ ] No hardcoded `time.sleep()` calls (use event-driven `wait_for_timeout` or `wait_for_selector`)
- [ ] No `subprocess.Popen` or `threading.Thread` inside connector code
- [ ] All DAL calls go through `with get_db()` — no raw `sqlite3.connect()`
- [ ] Connector added to `CONNECTORS` registry in `run_all.py` (commented out until tested)
- [ ] `automation_worker._get_connector()` updated to handle the new institution ID

---

## Roadmap

See the corresponding `task.md` for detailed checklists from the relevant agent session.

| Phase | Status |
|---|---|
| 0-4: Core backend | ✔ Complete |
| 5: Connector refactor | ✔ Complete |
| 5.5: Project debloat | ✔ Complete |
| 6: Credential storage + E2E test | 🔄 In progress |
| 7: New connectors + Phone Link SMS | Planned |
| 8: Frontend migration | Planned |

