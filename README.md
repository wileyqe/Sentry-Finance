# 🚀 Sentry Finance — Personal Finance Dashboard

> **Local-first.** No cloud. No third-party aggregators. Direct browser automation against your financial institutions, stored in a local SQLite database, served via a FastAPI REST + SSE backend.

---

## Architecture

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the full design document. Summary:

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
│       ┌───────────┬───────────┼───────────┬───────────┐              │
│       ▼           ▼           ▼           ▼           ▼              │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │  NFCU   │ │  Chase  │ │Fidelity │ │ Acorns  │ │  TSP    │       │
│  │Connector│ │Connector│ │Connector│ │Connector│ │(scripts)│       │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘       │
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

---

## Quick Start

### 1. Install dependencies
```powershell
pip install -r requirements.txt
playwright install chromium
```

### 2. Store credentials
Credentials are stored in **Windows Credential Manager** (never in `.env` or plaintext).
The credential broker handles UAC elevation automatically at runtime.

```powershell
# The broker will prompt for credentials on first run via UAC
python backend/credential_broker.py --store chase
python backend/credential_broker.py --store nfcu
```

### 3. Configure accounts
Edit **`accounts.yaml`** to list your accounts and what to export:

```yaml
chase:
  - name: "Premier Plus CKG"
    last4: "8973"
    type: checking
    export:
      balance: true
      transactions: true

nfcu:
  - name: "Active Duty Checking"
    last4: "1167"
    type: checking
    export:
      balance: true
      transactions: true
```

### 4. Start the API server
```powershell
python backend/api_server.py
# → http://127.0.0.1:8000/docs
```

### 5. Trigger a refresh
```powershell
# Via API (recommended)
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/refresh/start" -Method POST

# Or directly
python run_all.py
```

The browser will open. Complete MFA when prompted — the script continues automatically.

---

## How It Works

### Refresh Pipeline

1. **Staleness check** — `refresh_orchestrator.py` reads `refresh_policy.yaml` to decide which institutions need a refresh (default: Chase every 7 days, NFCU every 2 days).
2. **Credential broker** — A short-lived UAC-elevated subprocess reads credentials from Windows Credential Manager and passes them over IPC. It exits immediately after.
3. **Browser automation** — Each connector attaches to a persistent Chrome profile via CDP, fills credentials, waits for MFA, then scrapes balances and downloads transaction CSVs.
4. **SQLite persistence** — Transactions are upserted with SHA-256 identity hashing (deduplication). Balances are snapshotted. Loan details are stored separately.
5. **API serving** — FastAPI serves the data via REST endpoints and SSE for real-time refresh progress.

### Connector Flow (per institution)

```
_perform_login()        # Fill creds or wait for autofill
_wait_for_mfa()         # Poll until dashboard URL appears
_trigger_export()       # Phase 1: scrape balances
                        # Phase 2: download transaction CSVs
```

### Session Reuse

Chrome profiles are stored in `profiles/{institution}/`. Once logged in and MFA-trusted, subsequent runs reuse the session cookie — no re-login needed until the session expires.

---

## Module Map

See **[ARCHITECTURE.md § Module Map](ARCHITECTURE.md#module-map)** for the complete table. Key packages:

| Package | Key Modules |
|---|---|
| `backend/` | `api_server.py`, `refresh_orchestrator.py`, `automation_worker.py`, `credential_broker.py`, `state_machine.py`, `ipc.py`, `routers/cash_flow.py` |
| `dal/` | `database.py` (V9: 16 tables), `transactions.py`, `balances.py`, `reports.py`, `cash_flow.py`, `recurring.py`, `budgets.py`, `forecasting.py`, `alerts.py`, `derived.py` |
| `extractors/` | `nfcu_connector.py`, `chase_connector.py`, `acorns_connector.py`, `fidelity_connector.py`, `sms_otp.py`, `ai_backstop.py`, `dom_healer.py`, `chrome_cdp.py`, `selector_registry.yaml` |
| `frontend/src/` | `App.tsx`, `index.css`, `pages/DashboardPage.tsx`, `pages/TransactionsPage.tsx`, `pages/CashFlowPage.tsx`, `pages/ReportsPage.tsx`, `pages/AccountsPage.tsx`, `pages/BudgetsPage.tsx`, `pages/InvestmentsPage.tsx` |
| `scripts/` | `ingest_tsp.py`, `fetch_tsp_prices.py`, `ingest_fidelity_history.py`, `parse_acorns_pdf.py`, `chart_acorns_performance.py` |
| `skills/` | `institution_connector.py`, `SKILL.md`, `new-connector-playbook.md`, `dev-session-cleanup.md` |
| `config/` | `refresh_policy.yaml`, `logging_config.py` |
| `tests/` | `test_dal.py`, `test_live_db.py`, `test_sms_otp.py`, `test_sms_schema.py`, `test_phone_db.py`, `test_ts.py` |

---

## Configured Accounts

| Institution | Account | Type | Balance | Transactions |
|---|---|---|---|---|
| NFCU | Mortgage or Rent (0459) | Checking | ✔ | ✔ |
| NFCU | Active Duty Checking (1167) | Checking | ✔ | ✔ |
| NFCU | Visa Signature GO REWARDS (0837) | Credit Card | ✔ | ✔ |
| NFCU | New Vehicle Loan (3533) | Loan | ✔ | ✔ + loan details |
| NFCU | Mortgage (6167) | Loan | ✔ | — + loan details |
| Chase | Premier Plus CKG (8973) | Checking | ✔ | ✔ |
| Chase | Slate Edge (8115) | Credit Card | ✔ | ✔ |
| Acorns | Invest (0000) | Investment | ✔ | — (Delta-Logging) |
| Fidelity | Individual Brokerage (0827) | Investment | ✔ | ✔ (CSV download) |
| TSP | Uniformed Services (7777) | Retirement | ✔ | — (script-only) |

---

## Adding a New Connector

All connectors follow a **codegen → port → harden** workflow. See [ARCHITECTURE.md § Building New Connectors](ARCHITECTURE.md#building-new-connectors) for the full guide.

**Short version:**
```powershell
# 1. Record the journey
npx playwright codegen --channel chrome https://www.fidelity.com

# 2. Create the connector
# extractors/fidelity_connector.py — extend InstitutionConnector

# 3. Add selectors to selector_registry.yaml

# 4. Wire into accounts.yaml + refresh_policy.yaml

# 5. Test
python run_all.py --institutions fidelity
```

---

## Project Status

| Component | Status | Notes |
|---|---|---|
| FastAPI backend | ✅ Complete | REST + SSE; cash-flow rolling-window endpoints added |
| SQLite DAL | ✅ Complete | V9 schema (16 tables), WAL, SHA-256 dedup, cash-flow DAL |
| Credential broker | ✅ Complete | UAC + Windows Credential Manager |
| Refresh orchestrator | ✅ Complete | Staleness, retries, state machine |
| AI selector healing | ✅ Complete | Auto-heals broken CSS selectors via Gemini |
| Centralized logging | ✅ Complete | Rotating file handlers, hierarchical loggers |
| NFCU connector | ✅ Complete | Checking, credit card, loans |
| Chase connector | ✅ Complete | Checking, credit card + SMS OTP auto-capture |
| Acorns connector | ✅ Complete | Investment tracking via Delta-Logging + yFinance |
| Fidelity connector | ✅ Complete | CSV-download automation + historical ingestion |
| TSP ingestion | ✅ Complete | Script-only: PDF parser + MaxTSP API (no browser connector) |
| Affirm connector | 🔄 Planned | Phone + SMS OTP (manual); Phone Link capture planned |
| Frontend — Dashboard | ⚠️ In Progress | UI built; testing with dummy data. Live data integration + edge case review pending |
| Frontend — Transactions | ⚠️ In Progress | UI built; testing with dummy data. Live data integration + edge case review pending |
| Frontend — Cash Flow | ⚠️ In Progress | UI built; testing with dummy data. Live data integration + edge case review pending |
| Frontend — Reports | ⚠️ In Progress | UI built; testing with dummy data. Live data integration + edge case review pending |
| Frontend — Accounts | ⚠️ In Progress | UI built; testing with dummy data. Live data integration + edge case review pending |
| Frontend — Budgets | ⚠️ In Progress | UI built; testing with dummy data. Live data integration + edge case review pending |
| Frontend — Investments | ⚠️ In Progress | UI built; testing with dummy data. Live data integration + edge case review pending |

---

## Security Notes

- **Credentials**: Stored in Windows Credential Manager (OS-level encryption, Windows Hello gate). Never in `.env`, plaintext files, or version control.
- **Credential broker**: Runs elevated for seconds only — reads keyring, passes over IPC, exits. The main process never holds elevated privileges.
- **Browser profiles**: `profiles/` contains session cookies. Keep out of version control (already in `.gitignore`).
- **Terms of service**: This tool automates your own accounts for personal use. Ensure compliance with your institutions' ToS.

---

## License

MIT — Personal finance tool. Use at your own risk.

