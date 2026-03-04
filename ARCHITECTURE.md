# Sentry Finance — Architecture Overview

> **Living document.** Update when major design decisions are made.
> Last updated: 2026-03-03

## Mission

Local-first personal finance dashboard. Replace flaky third-party aggregators
with direct browser automation against financial institutions. Prioritize
security, minimal manual intervention, and concurrent UI responsiveness.

## System Diagram

```
┌──────────────────── User's Machine (Windows) ────────────────────┐
│                                                                  │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐    │
│  │   Frontend    │───▶│  API Server      │───▶│  SQLite DB   │    │
│  │  (Phase 8)    │    │  FastAPI :8000    │    │  WAL mode v2 │    │
│  └──────────────┘    └────────┬─────────┘    └──────────────┘    │
│                               │ SSE + REST            ▲          │
│                               ▼                       │          │
│                      ┌──────────────────┐             │          │
│                      │  Refresh         │  writes ────┘          │
│                      │  Orchestrator    │                        │
│                      └────────┬─────────┘                        │
│            ┌──────────────────┼──────────────────┐               │
│            ▼                  ▼                  ▼               │
│     ┌───────────┐      ┌──────────┐       ┌──────────┐          │
│     │ NFCU      │      │ Chase    │       │ Acorns   │  ...     │
│     │ Connector │      │Connector │       │Connector │          │
│     └─────┬─────┘      └────┬─────┘       └────┬─────┘          │
│           │                 │                   │                │
│           └────────┬────────┘                   │                │
│                    ▼                            ▼                │
│          ┌───────────────┐            ┌──────────────────┐       │
│          │ Chrome (CDP)  │            │ Delta-Logging    │       │
│          │ + Broker Creds│            │ scrape + yFinance│       │
│          └───────┬───────┘            └────────┬─────────┘       │
│                  │                             │                 │
│                  ▼                             ▼                 │
│          ┌───────────────┐            ┌──────────────────┐       │
│          │ SMS OTP       │            │ yFinance API     │       │
│          │ (sms_otp.py)  │            │ (external)       │       │
│          └───────────────┘            └──────────────────┘       │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Credential Broker (elevated, short-lived)                 │  │
│  │  UAC → keyring (WinVaultKeyring) → IPC → exit              │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
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
| | `ipc.py` | Temp-file IPC across UAC privilege boundary, memory clearing |
| `dal/` | `database.py` | Schema (V1: 9 tables, V2: +`portfolio_snapshots`, `positions_ledger`), WAL, migrations, seeding |
| | `transactions.py` | Upsert, SHA-256 identity, pending→posted |
| | `balances.py` | Balance snapshots, loan details |
| | `refresh_log.py` | Durable state machine (refresh_runs, events) |
| | `derived.py` | Scoped metrics (monthly spend/income, net worth) |
| | `migrate_csv.py` | One-time CSV → SQLite migration tool |
| `extractors/` | `nfcu_connector.py` | NFCU browser automation |
| | `chase_connector.py` | Chase browser automation |
| | `acorns_connector.py` | Acorns browser automation + Delta-Logging pipeline |
| | `sms_otp.py` | Windows Phone Link SMS OTP capture (PowerShell → Phone Link DB → CLI fallback) + auto-dismiss |
| | `ai_backstop.py` | AI-powered selector healing |
| | `dom_healer.py` | DOM analysis for broken selectors |
| | `chrome_cdp.py` | Chrome DevTools Protocol launcher |
| | `selector_registry.yaml` | Centralized CSS selectors (login + logout groups per institution) |
| `scripts/` | `parse_acorns_pdf.py` | Acorns PDF statement parser for historical positions backfill |
| | `chart_acorns_performance.py` | Acorns portfolio value chart (matplotlib + yfinance) |
| `skills/` | `institution_connector.py` | Base class: lifecycle, CDP, MFA wait, logout, popup dismissal |
| | `new-connector-playbook.md` | Step-by-step guide for building new connectors |
| | `dev-session-cleanup.md` | Milestone/end-of-session cleanup workflow |
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
| Acorns Delta-Logging | Extract snapshot shares + yFinance pricing instead of brittle UI scraping | 2026-03 |

## Login Strategy Per Institution

| Institution | Auth Method | Broker Creds | MFA | Status |
|---|---|---|---|---|
| NFCU | Username + Password | ✔ Stored | SMS/Push (manual) | ✔ Connector built |
| Chase | Username + Password | ✔ Stored | SMS (auto via `sms_otp.py` + Phone Link) | ✔ Connector built |
| Acorns | Username + Password | ✔ Stored | SMS (auto via `sms_otp.py`) | ✔ Connector built + Delta-Logging |
| Fidelity | Username + Password | ✔ Stored | **Authenticator app** (manual — no automation yet) | Connector planned |
| TSP | Username + Password | ✔ Stored | **Authenticator app** (manual — no automation yet) | Connector planned |
| Affirm | Phone + SMS OTP | N/A | SMS code (manual) | Connector planned |

## Acorns Delta-Logging Architecture (Investment Scraper)

To track investments from institutions (like Acorns) that obfuscate underlying ledger histories in their UI, we utilize the **Delta-Logging Architecture**:

1. **Scrape:** Pull current exact share counts and cash/portfolio total balances dynamically from the live UI (`portfolio_snapshots`).
2. **Compare:** Identify the delta against the last known share counts in the local DB.
3. **Calculate:** If shares increased computationally log an `IMPLIED_BUY` transaction type (`positions_ledger`). 
4. **Enrich:** Instantly query `yfinance` API for the closing price on the transaction date to estimate cost-basis dynamically.
5. **Backfill:** If the `yfinance` call fails due to rate limits or API outage, the price is saved as `NULL` and backfilled via a weekly cleanup cron operation.

## Building New Connectors

All new connectors follow a **codegen → port → harden** workflow:

### Step 1: Record with Playwright Codegen

```powershell
npx playwright codegen --channel chrome https://www.fidelity.com
```

This opens a browser + inspector panel. Walk through the full journey:
1. Launch persistent context
2. Navigate directly to export or account activity URL
3. If redirected to login → perform automated login
4. Wait for MFA (human approval or auto SMS capture)
5. Trigger CSV/QFX export
6. Save file with standardized naming
7. Dismiss blocking popups → **logout** (multi-strategy per institution)
8. Update `state.json`
9. Close browser tab (browser closed at pipeline end by `run_all.py`)

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
| 6: Credential storage, IPC security, repo hardening | ✔ Complete |
| 7: Acorns connector + SMS OTP + Delta-Logging | ✔ Complete |
| 7.1: Logout lifecycle + popup dismissal + browser cleanup | ✔ Complete |
| 7.5: Remaining connectors (Fidelity, TSP, Affirm) | Planned |
| 8: Frontend migration | Planned |

## Unmitigated Technical Debt & Code Review Findings

The following items were identified in a codebase review. Items marked ✔ have been addressed; the rest remain open.

- **Connector Extensibility (F-06):** Transition from hardcoded connector routing (`run_all.py`, `automation_worker._get_connector()`) to a single Plugin Registry and Institution Capability Manifest.
- **Orchestrator Integration Tests (F-07):** Add deterministic integration tests for the `RefreshOrchestrator` to validate retry/cooldown/session summary logic using a mocked worker.
- ~~**Data Privacy & Retention (F-08):**~~ ✔ `.gitignore` hardening and `data/extracted/` purge completed (commit `991284e`). Remaining: file-age pruning job for `raw_exports/` and browser profiles.
- **Auth Model Contract (F-09):** Introduce a typed credential schema (`kind: password|token|otp`) and explicit `auth_mode` contract to standardise credential retrieval, specifically needed before building the Affirm Phone/OTP connector.
- **Event Taxonomy & Observability (F-10):** Add explicit failure taxonomy and dashboard counters (e.g. selector-heal count, MFA wait timeouts by institution) and machine-readable event codes to the state machine for rapid triage.
- **Pre-existing `dom_healer.py` IndentationError (line 98):** Compile error predating this session. Needs fix before next use of DOM healing.

