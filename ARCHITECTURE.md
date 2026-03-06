# Sentry Finance — Architecture Overview

> **Living document.** Update when major design decisions are made.
> Last updated: 2026-03-05

## Mission

Local-first personal finance dashboard. Replace flaky third-party aggregators
with direct browser automation against financial institutions. Prioritize
security, minimal manual intervention, and concurrent UI responsiveness.

## System Diagram

```
┌────────────────────── User's Machine (Windows) ──────────────────────┐
│                                                                      │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐        │
│  │   Frontend    │───▶│  API Server      │───▶│  SQLite DB   │        │
│  │  (Phase 8)    │    │  FastAPI :8000    │    │  WAL mode v2 │        │
│  └──────────────┘    └────────┬─────────┘    └──────────────┘        │
│                               │ SSE + REST            ▲              │
│                               ▼                       │              │
│                      ┌──────────────────┐             │              │
│                      │  Refresh         │  writes ────┘              │
│                      │  Orchestrator    │                            │
│                      └────────┬─────────┘                            │
│       ┌───────────┬───────────┼───────────┬───────────┬──────────┐   │
│       ▼           ▼           ▼           ▼           ▼          ▼   │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────┐│
│  │  NFCU   │ │  Chase  │ │Fidelity │ │ Acorns  │ │  TSP    │ │ Affirm ││
│  │Connector│ │Connector│ │Connector│ │Connector│ │(scripts)│ │Connector││
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └───┬────┘│
│       │           │           │           │           │              │
│       └─────┬─────┘           │           │      PDF + MaxTSP       │
│             │                 │           │       API (no CDP)       │
│             ▼                 ▼           ▼                          │
│    ┌───────────────┐  ┌──────────────┐  ┌──────────────────┐        │
│    │ Chrome (CDP)  │  │ CSV Download │  │ Delta-Logging    │        │
│    │ + Broker Creds│  │ (activity)   │  │ scrape + yFinance│        │
│    └───────┬───────┘  └──────────────┘  └────────┬─────────┘        │
│            │                                      │                  │
│            ▼                                      ▼                  │
│    ┌───────────────┐                    ┌──────────────────┐        │
│    │ SMS OTP       │                    │ yFinance API     │        │
│    │ (sms_otp.py)  │                    │ (external)       │        │
│    └───────────────┘                    └──────────────────┘        │
│                                                                      │
│    ┌──────────────────────────────────────────────────────────────┐  │
│    │  AI Backstop + Selector Registry (self-healing selectors)    │  │
│    │  Gemini API → dom_healer.py → selector_registry.yaml patch   │  │
│    └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│    ┌──────────────────────────────────────────────────────────────┐  │
│    │  Credential Broker (elevated, short-lived)                   │  │
│    │  UAC → keyring (WinVaultKeyring) → IPC → exit                │  │
│    └──────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
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
| *(root)* | `run_all.py` | Direct connector runner for development and manual testing (sequential execution) |
| | `accounts.yaml` | Per-institution account list + export config (balance, transactions, loan details) |
| | `state.json` | Last-successful-run timestamps per institution (gitignored) |
| | `requirements.txt` | Python dependencies |
| | `.env.example` | Template for non-secret config (Gemini API key, Chrome profile path) |
| `backend/` | `api_server.py` | FastAPI, 11 endpoints, SSE stream |
| | `refresh_orchestrator.py` | Session lifecycle, staleness, retries |
| | `automation_worker.py` | Connector bridge, SQLite persistence |
| | `credential_broker.py` | UAC-elevated keyring access |
| | `state_machine.py` | RefreshState enum, transitions, error classes |
| | `ipc.py` | Temp-file IPC across UAC privilege boundary, memory clearing |
| `dal/` | `database.py` | Schema (V2: 11 tables incl. `portfolio_snapshots`, `positions_ledger`), WAL, migrations, seeding |
| | `transactions.py` | Upsert, SHA-256 identity, pending→posted |
| | `balances.py` | Balance snapshots, loan details |
| | `refresh_log.py` | Durable state machine (refresh_runs, events) |
| | `derived.py` | Scoped metrics (monthly spend/income, net worth) |
| | `migrate_csv.py` | One-time CSV → SQLite migration tool |
| `extractors/` | `nfcu_connector.py` | NFCU browser automation |
| | `fidelity_connector.py` | Fidelity CSV-download automation + ingest pipeline |
| | `chase_connector.py` | Chase browser automation |
| | `acorns_connector.py` | Acorns browser automation + Delta-Logging pipeline |
| | `affirm_connector.py` | Affirm browser automation — HYSA balance/txn scraping + BNPL contract discovery |
| | `sms_otp.py` | Windows Phone Link SMS OTP capture (PowerShell → Phone Link DB → CLI fallback) + auto-dismiss |
| | `ai_backstop.py` | AI-powered selector healing |
| | `dom_healer.py` | DOM analysis for broken selectors |
| | `chrome_cdp.py` | Chrome DevTools Protocol launcher |
| | `selector_registry.yaml` | Centralized CSS selectors (login + logout groups per institution) |
| `scripts/` | `parse_acorns_pdf.py` | Acorns PDF statement parser for historical positions backfill |
| | `chart_acorns_performance.py` | Acorns portfolio value chart (matplotlib + yfinance) |
| | `ingest_fidelity_history.py` | One-shot Fidelity CSV → daily portfolio reconstruction + yfinance market data ingestion (outputs to `data/fidelity/`) |
| | `ingest_tsp.py` | TSP statement PDF parser + MaxTSP API → daily portfolio snapshot + SQLite persistence (no browser automation) |
| | `fetch_tsp_prices.py` | One-time Playwright fetch of TSP share price history CSV from tsp.gov |
| `skills/` | `institution_connector.py` | Base class: lifecycle, CDP, MFA wait, logout, popup dismissal |
| | `SKILL.md` | InstitutionConnector skill specification (v2) — philosophy, lifecycle, security |
| | `new-connector-playbook.md` | Step-by-step guide for building new connectors |
| | `dev-session-cleanup.md` | Milestone/end-of-session cleanup workflow |
| `config/` | `refresh_policy.yaml` | Per-institution intervals, retries, MFA |
| | `logging_config.py` | Centralized logging: console + rotating file handlers (`logs/sentry.log`, `logs/sentry_errors.log`) |
| `tests/` | `test_dal.py` | DAL unit tests: schema, upsert, dedup, balances, loans, refresh log, derived metrics |
| | `test_live_db.py` | Production DB integrity smoke test |
| | `test_sms_otp.py` | SMS OTP capture tests |
| | `test_sms_schema.py` | Phone Link DB schema tests |
| | `test_phone_db.py` | Phone Link DB access tests |
| | `test_ts.py` | Timestamp utility tests |

## Directory Layout (Runtime & Data)

> All directories below are **gitignored**. They are created at runtime or by manual ingestion scripts.

```
data/
├── sentry.db                  # SQLite database (WAL mode, V2 schema)
├── extracted/                 # Staging area for raw balance/txn extracts (currently empty)
├── fidelity/                  # Fidelity ingestion outputs:
│   ├── daily_portfolio_snapshot.csv
│   ├── raw_market_data.csv
│   └── corporate_actions.csv
├── outputs/
│   └── tsp/
│       └── daily_portfolio_snapshot.csv
└── screenshots/               # NFCU HomeSquad detail screenshots

logs/
├── sentry.log                 # All-level rotating log (weekly, 4-week retention)
├── sentry_errors.log          # WARNING+ rotating log (weekly, 8-week retention)
└── ai_repairs.jsonl           # AI backstop heal events (model, tokens, cost, confidence)

screenshots/                   # Automation debug screenshots (per-institution, timestamped)
profiles/                      # Persistent Playwright browser profiles (session cookies, 2FA trust)
├── acorns/
├── affirm/
├── chase/
├── fidelity/
└── nfcu/

raw_exports/                   # Downloaded CSV/QFX files per institution
├── TSP/
├── acorns/
├── affirm/
├── chase/
├── fidelity/
└── nfcu/

.ai_cache/                     # AI backstop session-level DOM cache (avoids redundant API calls)
```

> [!IMPORTANT]
> **Screenshot Policy:** Screenshots are produced **only on automation errors** (login failures, missing selectors, export failures). They must never reach GitHub (gitignored). Every screenshot represents an issue that should be documented, investigated, and corrected promptly.

> [!IMPORTANT]
> **Raw Exports Policy:** Downloaded CSV/QFX files in `raw_exports/` contain real financial data. They must **never** reach GitHub (gitignored). Files are small and replaced on each run; no retention pruning is needed.

> [!NOTE]
> **No Automated Scheduling:** The pipeline requires biometric authentication (MFA) at every institution, making unattended scheduled runs architecturally impossible. All runs are human-initiated.

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
| Fidelity CSV ingestion | One-shot historical pipeline: backward-calc baseline from positions, forward-roll daily, over-collect yfinance OHLCV + corporate actions | 2026-03 |

## Login Strategy Per Institution

| Institution | Auth Method | Broker Creds | MFA | Status |
|---|---|---|---|---|
| NFCU | Username + Password | ✔ Stored | SMS/Push (manual) | ✔ Connector built |
| Chase | Username + Password | ✔ Stored | SMS (auto via `sms_otp.py` + Phone Link) | ✔ Connector built |
| Acorns | Username + Password | ✔ Stored | SMS (auto via `sms_otp.py`) | ✔ Connector built + Delta-Logging |
| Fidelity | Username + Password | ✔ Stored | **Authenticator app** (manual TOTP approval) | ✔ Connector built |
| TSP | Username + Password | ✔ Stored | **Authenticator app** (manual — no automation yet) | ⚙ Script-only (`scripts/ingest_tsp.py` — no browser connector) |
| Affirm | Phone + SMS OTP | ✔ Stored (phone) | SMS (auto via `sms_otp.py` + Phone Link) | ✔ Connector built |

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

## Investment Valuation Model

Investment accounts (Fidelity, Acorns) use a **previous-close valuation model** to avoid noisy intraday fluctuations:

```
today's value = (baseline_positions ± activity_deltas) × yfinance_prev_close
```

| Component | Source |
|---|---|
| **Baseline positions** | One-time ingestion (`ingest_fidelity_history.py`) |
| **Activity deltas** | Automated CSV download (buys, sells, dividends, transfers) |
| **Previous close prices** | yfinance API (`generate_outputs()`) |
| **Cash balance** | Derived from SPAXX money market balance in activity ledger |
| **Last update timestamp** | `institution_refresh_status.last_success` |

No live scraping of positions pages is needed — holdings are fully derivable from the baseline + activity history.

### Dashboard: Live Polling Index Box (Planned)

For real-time market awareness during trading hours, the frontend dashboard will include a **live polling index box** showing:
- Major indices (S&P 500, NASDAQ, Dow)
- Portfolio-weighted intraday change estimate
- Last updated timestamp

This is display-only — it does **not** affect the stored portfolio valuation, which always uses previous-close pricing for consistency.

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
| 7.5: Fidelity historical data ingestion pipeline | ✔ Complete |
| 7.6: Fidelity CSV-download connector (activity-only) | ✔ Complete |
| 7.7: TSP statement + API ingestion | ✔ Complete (script-only — no browser connector) |
| 7.8: Affirm connector (HYSA + BNPL) | ✔ Complete (pending live test) |
| 8: Frontend migration + live polling index box | Planned |

## Unmitigated Technical Debt & Code Review Findings

The following items were identified in a codebase review. Items marked ✔ have been addressed; the rest remain open.

- ~~**Connector Extensibility (F-06):**~~ Downgraded. Hardcoded `CONNECTORS` dict in `run_all.py` + `_get_connector()` in `automation_worker.py` works well at current scale (4 active connectors). Revisit plugin registry if institution count exceeds 6.
- **Orchestrator Integration Tests (F-07):** Add deterministic integration tests for the `RefreshOrchestrator` to validate retry/cooldown/session summary logic using a mocked worker. *(Nice-to-have — no test framework in place yet.)*
- ~~**Data Privacy & Retention (F-08):**~~ ✔ `.gitignore` hardening and `data/extracted/` purge completed (commit `991284e`). Remaining: file-age pruning job for `raw_exports/` — low priority since files are small CSVs replaced on each run.
- **Auth Model Contract (F-09):** Introduce a typed credential schema (`kind: password|token|otp`) and explicit `auth_mode` contract to standardise credential retrieval. *(Target: Phase 7.8, needed before Affirm Phone/OTP connector.)*
- **Event Taxonomy & Observability (F-10):** Add explicit failure taxonomy, dashboard counters (e.g. selector-heal count, MFA wait timeouts by institution) and machine-readable event codes. *(Target: Phase 8, requires frontend dashboard.)*
- ~~**Pre-existing `dom_healer.py` compile error:**~~ ✔ Fixed — removed BOM byte (U+FEFF), updated stale import (`_extract_relevant_html` → `_minify_dom`), fixed `_call_gemini` return value handling (dict, not string), cleaned unused imports.

---

## Future Plans & Ideas

> **Living scratchpad.** Capture ideas here as they come up during development.
> Move items to the Roadmap table above when they become concrete phases.

### Interactive Dashboard Notifications (MFA Bridge)

**Problem**: Fidelity and TSP require authenticator app TOTP codes. The user currently must interact directly with the browser automation window to enter them.

**Vision**: The dashboard (Phase 8 frontend) should support **interactive toast notifications** pushed from the automation pipeline via SSE. When a connector hits an MFA wall:

1. The automation worker publishes an SSE event: `{"type": "mfa_required", "institution": "fidelity", "method": "totp", "prompt": "Enter your authenticator code"}`
2. The dashboard renders an interactive toast with a code input field
3. The user enters the code directly in the dashboard UI
4. The dashboard posts the code back via the API: `POST /api/mfa/respond {"institution": "fidelity", "code": "123456"}`
5. The automation worker receives the code and injects it into the browser page

**Key benefit**: The user never touches the backend, terminal, or browser automation window. The entire interaction happens through the polished dashboard UI — even on a phone or tablet if the dashboard is exposed on the local network.

**Architecture implications**:
- Requires a bidirectional channel between the frontend and the automation worker (SSE for push, REST for response)
- The `_wait_for_mfa()` lifecycle phase would need to poll an API endpoint (or use an event/queue) instead of only watching the browser
- Security: the code must be memory-cleared after use (same pattern as credential broker)

**Potential extensions**:
- Push notifications via Windows toast or mobile push (ntfy.sh, Pushover) for when the user isn't at the dashboard
- Approval-only prompts ("Approve this login?") for push-based MFA
- OTP auto-fill from `pyotp` if the user stores their TOTP secret securely in Windows Credential Manager

### AI Backstop Dashboard Notifications

**Problem**: When the AI backstop fires at runtime (a selector broke and Gemini healed it), the repair is logged silently to `logs/ai_repairs.jsonl`. The user only discovers it later by reading the log file.

**Vision**: Surface AI backstop events as **toast notifications** in the dashboard UI. Each notification includes the heal result, confidence score, and exact cost:

1. The backstop publishes an SSE event: `{"type": "selector_healed", "intent": "Sign In submit button", "confidence": 95, "cost_usd": 0.0003, "diagnostic": "Chase removed #signin-button ID"}`
2. The dashboard renders a toast: **🔧 Selector Healed** — "Sign In submit button" → `button[data-testid='login-submit']` (95% confidence, $0.0003)
3. If auto-patch succeeded, the toast is informational-only. If confidence was borderline (70-80), style it as a warning suggesting manual review.
4. A **Cost Summary** widget in the dashboard aggregates cumulative AI spend from `ai_repairs.jsonl`

**Data source**: The `logs/ai_repairs.jsonl` already contains all needed fields: `model`, `tokens_in`, `tokens_out`, `cost_usd`, `confidence`, `diagnostic`.

**Architecture implications**:
- SSE event emission from the backstop (or read from JSONL tail at pipeline end)
- Dashboard widget: cumulative cost, heal history table, confidence distribution
- Alerts threshold: notify if cumulative monthly cost exceeds a configurable cap (e.g., $0.50)


