# Sentry Finance — Architecture Overview

> **Living document.** Update when major design decisions are made.
> Last updated: 2026-03-16

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
│  │ React + Tauri │    │  FastAPI :8000    │    │  WAL mode V9 │        │
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
| `dal/` | `database.py` | Schema (V9: 16 tables incl. `owners`, `investment_holdings`, `real_estate`, `budgets`, `alert_rules`), WAL, migrations, seeding |
| | `transactions.py` | Upsert, SHA-256 identity, pending→posted |
| | `categorization.py` | 4-layer categorization engine: user override > keyword rules > bank category > Uncategorized |
| | `budgets.py` | Monthly budget targets CRUD, budget-vs-actual, historical suggestions |
| | `recurring.py` | Recurring transaction detection: frequency bands, merchant normalization, mutation tracking |
| | `bills.py` | Bill tracking: upcoming/overdue/summary from recurring_transactions.next_expected |
| | `forecasting.py` | Cash flow forecasting: recurring baseline + rolling average, N-month projections |
| | `alerts.py` | Spending alert engine: budget_pct / large_txn / balance_low rules, dedup, SSE-ready |
| | `reports.py` | Parameterized reports: spending by category, cash flow, net worth history, category trend, CSV export |
| | `cash_flow.py` | Rolling-window cash flow aggregation: 18-month, 9-quarter, yearly; income/spending/net/savings-rate per period |
| | `balances.py` | Balance snapshots, loan details |
| | `refresh_log.py` | Durable state machine (refresh_runs, events) |
| | `derived.py` | Scoped metrics (monthly spend/income, net worth, interest earned; transfer-aware) |
| | `investments.py` | Investment holdings CRUD (daily per-ticker positions, portfolio totals) |
| | `owners.py` | Ownership CRUD, config-driven view resolution (mine/theirs/ours), account assignment |
| | `reconciliation.py` | Cross-institution transfer matching and tagging |
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
| `frontend/src/` | `App.tsx` | Tauri + React app root: routing, sidebar, layout |
| | `index.css` | Global design tokens (OKLCH palette, dark mode, typography, animations) |
| | `pages/DashboardPage.tsx` | Net worth + spending charts (Tremor AreaChart), KPI snapshot cards, recent transactions, budget & recurring widgets |
| | `pages/TransactionsPage.tsx` | Paginated transaction table, multi-field filter popover, recurring toggle, add-transaction dialog, transaction detail sheet |
| | `pages/CashFlowPage.tsx` | 18-month/9-quarter/4-year rolling ComposedChart (Recharts), animated solid→dotted trend line, year-break separators, bar click drill-down, reset chip |
| | `pages/ReportsPage.tsx` | Spending by category, Sankey flow chart, net worth history, category trend |
| | `pages/AccountsPage.tsx` | Account list with balance history sparklines, account-filtered transaction navigation |
| | `pages/BudgetsPage.tsx` | Budget vs. actual per category, progress bars, month navigation |
| | `pages/InvestmentsPage.tsx` | Portfolio summary, holdings table, performance line chart |
| `scripts/` | `parse_acorns_pdf.py` | Acorns PDF statement parser for historical positions backfill |
| | `chart_acorns_performance.py` | Acorns portfolio value chart (matplotlib + yfinance) |
| | `ingest_fidelity_history.py` | One-shot Fidelity CSV → daily portfolio reconstruction + yfinance market data ingestion (outputs to `data/fidelity/`) |
| | `ingest_tsp.py` | TSP statement PDF parser + MaxTSP API → daily portfolio snapshot + SQLite persistence (no browser automation) |
| | `fetch_tsp_prices.py` | One-time Playwright fetch of TSP share price history CSV from tsp.gov |
| | `migrate_fidelity_to_db.py` | One-time Fidelity CSV → `investment_holdings` table migration (797 days × 18 tickers) |
| | `compute_acorns_daily.py` | Daily Acorns portfolio valuation from positions_ledger × yfinance prices |
| | `seed_real_estate.py` | Multi-source property valuation: Zillow + Redfin + Realtor.com (Playwright) + NFCU DB → mean estimate → `real_estate` table |
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
| Schema V3: `investment_holdings` + `real_estate` | Persist daily per-ticker positions in SQLite, track property values for net worth | 2026-03 |
| Transfer reconciliation | Tag matching debit/credit pairs cross-institution to prevent double-counting income/spending | 2026-03 |
| BNPL staleness tracking | Mark unseen Affirm contracts as inactive; filter UI-element slugs | 2026-03 |
| Net worth rollup includes investments + real estate | Prior version only used `balance_snapshots`; now includes `portfolio_snapshots`, `investment_holdings`, and `real_estate` | 2026-03 |
| Typed credential schema (`__auth_payload__`) | Supports password, token, and phone_otp credential types via JSON payload in Windows Credential Manager | 2026-03 |
| Ownership toggle (yours/ours/mine) | `owner_id` FK on `accounts` → `owners` table. NULL = shared ("ours"). Config-driven view resolution, no auth system needed for 1–2 trusted users | 2026-03 |
| Rolling-window cash flow endpoints | `/api/cash-flow/monthly-rolling` (18 months) and `/api/cash-flow/quarterly-rolling` (9 quarters) added to avoid recomputing on every date selector change | 2026-03 |
| Cash Flow bar click drill-down | `onClick` on individual Recharts `<Bar>` components (not parent `ComposedChart`) required for reliable event propagation through SVG | 2026-03 |
| Transactions filter popover (Option B) | Multi-field filter popover replaces single Category dropdown; Category, Account, Merchant, Amount range, Date Range in one 340px panel with count badge | 2026-03 |

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
| 7.9: Ownership toggle (yours/ours/mine) | ✔ Complete — Schema V5, `dal/owners.py`, API view filter |
| 7.10: Transaction Categorization | ✔ Complete — 4-layer engine, 250+ rules, backfill, user overrides (Schema V6) |
| 7.11: Recurring Detection + Bills + Budgeting | ✔ Complete — Schema V7+V8, `dal/recurring.py`, `dal/bills.py`, `dal/budgets.py` |
| 7.12: Cash Flow Forecasting + Spending Alerts + Reports | ✔ Complete — Schema V9, `dal/forecasting.py`, `dal/alerts.py`, `dal/reports.py` |
| 8: Frontend — Dashboard + core pages | ⚠️ In Progress — UI built; all pages functional with dummy data. Live data integration + edge case testing pending |
| 8.1: Frontend — Cash Flow rolling charts + drill-down | ⚠️ In Progress — UI built; 18-month/9-quarter/4yr rolling windows, animated trend line, bar drill-down. Live data testing pending |
| 8.2: Frontend — Transactions multi-field filter | ⚠️ In Progress — Popover filter built; Category, Account, Merchant, Amount, Date Range. Live data testing pending |
| 9: Live polling index box + MFA bridge | 🔄 Planned |

## Unmitigated Technical Debt & Code Review Findings

The following items were identified in a codebase review. Items marked ✔ have been addressed; the rest remain open.

- ~~**Connector Extensibility (F-06):**~~ Downgraded. Hardcoded `CONNECTORS` dict in `run_all.py` + `_get_connector()` in `automation_worker.py` works well at current scale (4 active connectors). Revisit plugin registry if institution count exceeds 6.
- **Orchestrator Integration Tests (F-07):** Add deterministic integration tests for the `RefreshOrchestrator` to validate retry/cooldown/session summary logic using a mocked worker. *(Nice-to-have — no test framework in place yet.)*
- ~~**Data Privacy & Retention (F-08):**~~ ✔ `.gitignore` hardening and `data/extracted/` purge completed (commit `991284e`). Remaining: file-age pruning job for `raw_exports/` — low priority since files are small CSVs replaced on each run.
- ~~**Auth Model Contract (F-09):**~~ ✔ Typed credential schema implemented (`__auth_payload__` JSON in Windows Credential Manager, supports `password`/`token`/`phone_otp`). Affirm connector updated for `phone_otp` kind.
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

### Planned Data Pipeline Features

**Chase Transaction Categorization** ✔ Complete
- ✔ V1 rule-based categorizer in `dal/categorization.py` + `config/categories.yaml` (250+ rules)
- ✔ User override/correction endpoint `PATCH /api/transactions/{id}/category`
- ✔ Retroactive backfill: `POST /api/categorize/backfill`
- V2 AI-assisted categorization (Gemini, for ambiguous merchants) — queued

**Budget Targets** ✔ Complete
- ✔ `budgets.yaml` + `budgets` table (Schema V8)
- ✔ Budget-vs-actual per category with pct_used + status (under/on_track/warning/over)
- ✔ Historical spend-based suggestions with 10% buffer rounded to $25
- ✔ REST API: full CRUD + `/api/budgets/suggest` + `/api/budgets/initialize`

**Recurring Transaction Detection** ✔ Complete
- ✔ Merchant normalization engine + frequency band classification
- ✔ Price mutation tracking + auto-deactivation after 2× missed interval
- ✔ REST API: scan, list, dismiss, reactivate, monthly summary

**Cash Flow Forecasting** ✔ Complete
- ✔ `dal/forecasting.py`: recurring baseline + rolling average, N-month projections
- ✔ REST API: `GET /api/forecast?months=6`

**Spending Alerts** ✔ Complete
- ✔ `dal/alerts.py`: budget_pct / large_txn / balance_low rule types
- ✔ Schema V9: `alert_rules` + `alert_events` (dedup by calendar month / 24h window)
- ✔ Fires automatically after each refresh via `automation_worker.py`
- ✔ REST API: list rules, update threshold/enabled, list events, evaluate now

**Reports & Data Export** ✔ Complete
- ✔ `dal/reports.py`: spending by category, cash flow 12-month, net worth history, category trend
- ✔ REST API: `/api/reports/spending`, `/api/reports/cash-flow`, `/api/reports/net-worth-history`, `/api/reports/category-trend`, `/api/reports/summary`
- ✔ CSV export: `GET /api/export/transactions`

**Sector Tagging for Investments** (queued)
- One-time yfinance enrichment: map each Fidelity ticker to sector/industry
- Store in `investment_holdings` or new `ticker_metadata` table
- Enables sector allocation pie chart on dashboard

### AI Financial Assistant

**Problem**: Querying financial data requires direct DB access or API calls. Users would benefit from natural language questions like "How much did I spend on groceries last month?" or "What's my average monthly income?"

**Vision**: Natural language Q&A over financial data via Gemini API, reusing existing infrastructure from `ai_backstop.py`.

1. Accept natural language query via `POST /api/ai/ask`
2. Generate read-only, parameterized SQL or DAL calls (never expose raw DB to the model)
3. Return structured answer with the generated query, result, and cost

**Architecture implications**:
- `backend/ai_assistant.py` module: query generation, SQL safety, response formatting
- Reuse Gemini API key and cost-tracking pattern from `ai_backstop.py`
- Session-level caching to avoid redundant API calls for similar questions
- Rate limiting consistent with backstop pattern
- API endpoint: `POST /api/ai/ask` → `{question, answer, cost_usd}`

**Priority**: Long-term. For a 1–2 user audience, direct DB queries suffice for now.

### Real Estate Add-Ons

**Current state**: Multi-source property valuation (Zillow, Redfin, Realtor.com, NFCU) via `scripts/seed_real_estate.py`. Exceeds competitors who use only Zillow.

**Planned extensions**:
- **Market trends**: Track neighborhood-level price trends over time (monthly snapshots of Zillow/Redfin estimates)
- **Comp sales**: Surface recent comparable sales within a configurable radius/timeframe
- **Rental price tracking**: For properties on the rental market eventually — track area rental prices (Zillow Rent Zestimate, Rentometer, or similar)
- Store historical estimates in `real_estate` table with `source` and `as_of` for trend analysis

**Priority**: Future — revisit when rental properties are in play.

### Credit Score Tracking

- Manual entry or automated scrape from free source (Credit Karma, NFCU dashboard)
- `credit_scores` table: `id INTEGER PK, score INTEGER, source TEXT, as_of TEXT`
- Historical chart on dashboard

**Priority**: Low — on the backlog list.

