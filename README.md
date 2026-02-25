# 🚀 Sentry Finance — Personal Finance Dashboard

> **Local-first.** No cloud. No third-party aggregators. Direct browser automation against your financial institutions, stored in a local SQLite database, served via a FastAPI REST + SSE backend.

---

## Architecture

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the full design document. Summary:

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
│           │ NFCU      │ │ Chase    │ │ (future) │             │
│           │ Connector │ │Connector │ │          │             │
│           └─────┬─────┘ └────┬─────┘ └──────────┘             │
│                 └──────┬─────┘                                 │
│                        ▼                                       │
│              ┌───────────────┐                                 │
│              │ Chrome (CDP)  │                                 │
│              │ + Credential  │                                 │
│              │   Broker      │                                 │
│              └───────────────┘                                 │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Credential Broker (elevated, short-lived)               │  │
│  │  UAC → keyring (WinVaultKeyring) → IPC → exit            │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
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

| Package | Module | Purpose |
|---|---|---|
| `backend/` | `api_server.py` | FastAPI, REST + SSE endpoints |
| | `refresh_orchestrator.py` | Staleness check, state machine, retry logic |
| | `automation_worker.py` | Connector bridge, SQLite persistence |
| | `credential_broker.py` | UAC-elevated keyring access |
| | `state_machine.py` | `RefreshState` enum, transitions |
| | `ipc.py` | JSON IPC across UAC privilege boundary |
| `dal/` | `database.py` | Schema (9 tables), WAL, migrations |
| | `transactions.py` | Upsert, SHA-256 dedup, pending→posted |
| | `balances.py` | Balance snapshots, loan details |
| | `refresh_log.py` | Durable refresh run log |
| | `derived.py` | Monthly spend/income, net worth metrics |
| `extractors/` | `nfcu_connector.py` | NFCU browser automation |
| | `chase_connector.py` | Chase browser automation |
| | `ai_backstop.py` | AI-powered selector healing |
| | `chrome_cdp.py` | Chrome DevTools Protocol launcher |
| | `selector_registry.yaml` | Centralized CSS selectors |
| `skills/` | `institution_connector.py` | Base class: lifecycle, CDP, MFA wait |
| `config/` | `refresh_policy.yaml` | Per-institution intervals, retries, MFA |

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

## Automated Scheduling

The pipeline can be scheduled via Windows Task Scheduler. See **[.agent/workflows/scheduled_run.md](.agent/workflows/scheduled_run.md)** for the workflow.

---

## Project Status

| Component | Status | Notes |
|---|---|---|
| FastAPI backend | ✅ Complete | REST + SSE, 11 endpoints |
| SQLite DAL | ✅ Complete | 9 tables, WAL, SHA-256 dedup |
| Credential broker | ✅ Complete | UAC + Windows Credential Manager |
| Refresh orchestrator | ✅ Complete | Staleness, retries, state machine |
| AI selector healing | ✅ Complete | Auto-heals broken CSS selectors |
| NFCU connector | ✅ Complete | Checking, credit card, loans |
| Chase connector | ✅ Complete | Checking, credit card |
| Fidelity connector | 🔄 Planned | Username + password, broker creds |
| TSP connector | 🔄 Planned | Username + password, broker creds |
| Acorns connector | 🔄 Planned | Username + password, broker creds |
| Affirm connector | 🔄 Planned | Phone + SMS OTP (manual); Phone Link capture planned |
| Frontend (Phase 8) | 🔄 Planned | Dashboard UI |

---

## Security Notes

- **Credentials**: Stored in Windows Credential Manager (OS-level encryption, Windows Hello gate). Never in `.env`, plaintext files, or version control.
- **Credential broker**: Runs elevated for seconds only — reads keyring, passes over IPC, exits. The main process never holds elevated privileges.
- **Browser profiles**: `profiles/` contains session cookies. Keep out of version control (already in `.gitignore`).
- **Terms of service**: This tool automates your own accounts for personal use. Ensure compliance with your institutions' ToS.

---

## License

MIT — Personal finance tool. Use at your own risk.

