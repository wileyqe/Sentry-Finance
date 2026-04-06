# Sentry Finance --- Architecture & Design Document

> **Single source of truth.** All design decisions, system boundaries, and
> conventions are recorded here. Update when decisions change.
>
> Last updated: 2026-03-29

---

## 1. Mission

Sentry Finance is a **local-first personal financial command center** for a
single household. It replaces third-party aggregators (Mint, Monarch, Plaid)
with direct browser automation, local storage, and full owner control.

**It is not a dashboard.** A dashboard shows numbers. A command center
provides the depth, trend history, and derived analysis to make decisions
with lasting financial impact:

- Debt sequencing (which balance to attack first)
- Savings rate optimization (am I keeping enough of what I earn)
- Investment rebalancing (is my allocation still right)
- Lifestyle creep detection (is spending growing faster than income)
- Major purchase timing (can I absorb this and stay on track)
- Retirement trajectory (am I where I need to be)

Every feature and design decision is evaluated against that standard.

### Guiding Principles

| # | Principle | Implication |
|---|-----------|-------------|
| 1 | **Automate everything** | If data can be fetched programmatically, it must be. Manual steps are a last resort with a clear nudge system to minimize staleness. |
| 2 | **Local-first, no cloud** | All data stays on the user's machine. No third-party aggregator APIs. No telemetry. |
| 3 | **Security by architecture** | Credentials in OS keyring, short-lived elevated processes, IPC hardening, log redaction. |
| 4 | **Owner-scoped from day one** | Multi-user is architecturally present but UI-toggled off until activated. Every query respects owner context. |
| 5 | **Teach the system** | Unrecognized transactions prompt the user; the user's classification becomes a permanent rule. The system gets smarter with use. |
| 6 | **Preliminary then revised** | Reports use the best available data now and upgrade when authoritative documents arrive. |

---

## 2. Household Financial Profile

This section defines the real-world context the system is built for.
All design decisions trace back to these facts.

### Owner

- Retired U.S. military (no longer active duty)
- Located in Bloomington, IN area
- Partner integration planned but deferred (separate financial pictures
  first, then merged household view via selector toggle)

### Income Streams

| Stream | Source | Frequency | Variability | Arrives in |
|--------|--------|-----------|-------------|------------|
| Military pension | DFAS / myPay | Monthly | Stable (COLA annually, Jan) | NFCU checking |
| VA disability | VA | Monthly | Stable (COLA annually) | NFCU checking |
| VA education (Ch. 33 or VR&E) | VA | Monthly during enrollment | Episodic --- on break, restarting late summer 2026 | NFCU checking |
| Sports officiating | Schools / districts / Eventlink | Seasonal (Aug--Mar) | Variable, ~$6K/season across many payors | NFCU (direct deposit + mobile check deposit) |

### Institutions & Accounts

| Institution | Account | Type | Connector | Data Captured |
|-------------|---------|------|-----------|---------------|
| **NFCU** | Checking (0459) --- mortgage funding | Checking | CDP (Phase 1-3) | Balance, transactions, loan details |
| **NFCU** | Savings (1167) | Savings | CDP | Balance, transactions |
| **NFCU** | Visa Signature GO REWARDS (0837) | Credit Card (rewards) | CDP | Balance, transactions |
| **NFCU** | New Vehicle Loan (3533) | Loan | CDP | Balance, transactions, loan details (APR, term, YTD interest) |
| **NFCU** | Mortgage (6167) | Mortgage | CDP + HomeSquad | Balance, loan details, escrow, home value estimate |
| **Chase** | Checking (8115) | Checking | CDP | Balance, transactions |
| **Chase** | Sapphire (8973) | Credit Card (rewards) | CDP | Balance, available credit, transactions |
| **Fidelity** | Brokerage (0827) | Investment | CDP + CSV | Holdings, transactions (buys/sells/dividends), portfolio value |
| **Acorns** | Invest (0000) | Investment | CDP + Delta-Logging | Portfolio value, per-fund shares (VOO/IJH/IJR/IXUS), yFinance prices |
| **TSP** | Uniformed Services (7777) | Retirement | **To be built: CDP + MFA bridge** (currently script-only) | Per-fund units/prices (L2065, C, S), total balance |
| **Affirm** | High Yield Savings (HYSA) | Savings | CDP | Balance, transactions (incl. interest), APY (planned) |
| **Affirm** | Buy Now Pay Later (BNPL) | Loan (episodic) | CDP | Contract details, balance, APR, schedule |

**Dummy/dev accounts** (not real institutions):
- Amex Blue Cash Preferred --- UI/UX testing only
- Rocket Home Mortgage --- UI/UX testing only

### Property

- Primary residence with NFCU mortgage (6167)
- Escrow covers PITI (principal, interest, tax, insurance) in one payment
- NFCU checking 0459 is a **dedicated mortgage funding account** ---
  intentionally overfunded to build a buffer for maintenance and
  future extra principal payments
- HomeSquad integration provides estimated home value

### Credit Cards

- Neither card typically carries a balance (paid in full monthly)
- Combined credit card spending is <5% of total spending
- APR is currently irrelevant for the owner but will matter when
  partner integration adds accounts that carry balances
- Both are rewards cards --- rewards tracking is a future addition

### BNPL Philosophy

- ~2 purchases per year, $600--1,200 each
- Active contracts: track balance, remaining payments, merchant, APR
- Completed contracts: visible through **end of the next calendar year**
  after completion (supports yearly wrap-up analysis), then archived
  to database-only (removed from active views)
- This retention policy applies system-wide to any closed account or
  paid-off loan

### TSP Posture

- No new contributions (retired --- cannot contribute)
- Held for ease of use and low fee structure
- Allocation: ~30% L2065, remainder split between C and S funds
- **Largest investment account by far (~10x the next largest)**
- Switch/stay analysis is a future feature
- Staleness of TSP data is the single biggest data quality risk

---

## 3. System Architecture

### 3.1 Process Model

```
+-------------------- User's Machine (Windows) --------------------+
|                                                                    |
|  +-------------+    +----------------+    +--------------+         |
|  |  Frontend   |--->|  API Server    |--->|  SQLite DB   |         |
|  | React+Tauri |    |  FastAPI :8000 |    |  WAL mode    |         |
|  +-------------+    +-------+--------+    +--------------+         |
|                             | SSE + REST          ^                |
|                             v                     |                |
|                     +----------------+            |                |
|                     |   Refresh      |  writes ---+                |
|                     |  Orchestrator  |                             |
|                     +-------+--------+                             |
|      +----------+----------+----------+----------+-------+        |
|      v          v          v          v          v       v        |
|  +------+  +------+  +-------+  +------+  +-----+  +------+     |
|  | NFCU |  |Chase |  |Fidelity| |Acorns|  | TSP |  |Affirm|     |
|  +--+---+  +--+---+  +---+---+  +--+---+  +--+--+  +--+---+     |
|     |         |           |         |         |         |          |
|     +----+----+           |         |    MFA Bridge     |          |
|          |                |         |    (SSE toast)    |          |
|          v                v         v         |         v          |
|   +-----------+    +----------+  +--------+   |   +---------+     |
|   |Chrome CDP |    |CSV Ingest|  | Delta  |   |   |DOM Scrape|    |
|   +-----+-----+    +----------+  |Logging |   |   +---------+     |
|         |                         +--------+   |                   |
|         v                                      |                   |
|   +-----------+                                |                   |
|   | SMS OTP   |    +---------------------------+                   |
|   | auto-cap  |    |                                               |
|   +-----------+    v                                               |
|              +--------------+     +-------------------+            |
|              | Document Drop |     | AI Backstop +     |           |
|              | (PDF/XLSX)    |     | Selector Healing   |          |
|              +--------------+     +-------------------+            |
|                                                                    |
|   +----------------------------------------------------------+    |
|   | Credential Broker (UAC-elevated, seconds only)            |    |
|   | keyring -> IPC -> exit                                    |    |
|   +----------------------------------------------------------+    |
+--------------------------------------------------------------------+
```

### 3.2 Trust Boundaries

| Process | Privilege | Lifetime | Role |
|---------|-----------|----------|------|
| API Server | Non-privileged | Long-running | REST + SSE serving |
| Refresh Orchestrator | Non-privileged | Per-session | Staleness, state machine, retries |
| Automation Worker | Non-privileged | Per-institution | Connector execution, DB writes |
| Credential Broker | **Elevated (UAC)** | **Seconds** | Keyring read, IPC, exit |

### 3.3 Data Ingestion Tiers

The system supports three tiers of data ingestion, in priority order:

| Tier | Method | Institutions | Freshness |
|------|--------|-------------|-----------|
| **Tier 1: Full automation** | Orchestrated connector on schedule | NFCU, Chase, Fidelity, Acorns, Affirm | Per refresh policy (hours/days) |
| **Tier 2: Semi-automation** | Connector with interactive MFA bridge | TSP (planned) | Daily (session reuse minimizes MFA prompts) |
| **Tier 3: Document drop** | Drag-and-drop on UI, auto-recognize, parse | TSP statements, myPay RAS, tax documents (1099/1098), Eventlink XLSX | Monthly (nudge system if overdue) |

**Document Drop Design:**
- UI accepts drag-and-drop of PDF and XLSX files
- Auto-recognition: file content is matched against known document
  parsers (TSP statement, myPay RAS, 1099-R, 1098, Eventlink export)
- Parsed data is ingested into the appropriate tables
- If a Tier 3 institution hasn't been updated by the 5th of the month,
  a **persistent toast** (small, unmovable) remains on screen until the
  document is dropped
- Document parsers: `ingest_tsp.py` (exists), myPay RAS (to build),
  1099/1098 tax docs (to build), Eventlink XLSX (to build)

### 3.4 Post-Ingestion Pipeline

After every connector writes data, the post-commit pipeline runs:

```
Connector writes -> Categorization backfill
                 -> Transfer reconciliation
                 -> Recurring detection
                 -> Derived metrics recompute
                 -> Alert evaluation
                 -> Goal balance sync
```

This pipeline is implemented in `backend/result_writer.py` and runs
per-institution after each refresh.

---

## 4. Data Architecture

### 4.1 Database

- **Engine:** SQLite 3 with WAL mode
- **Schema version:** V20 (32 tables)
- **Connection:** `dal/connection.py` --- WAL, foreign keys, busy timeout
- **Migrations:** `dal/migrations/v01..v20` --- sequential DDL

### 4.2 Schema Overview

**Core tables:**
- `institutions` --- registered financial institutions
- `accounts` --- individual accounts with owner assignment
- `transactions` --- all transactions (SHA-256 identity hashing for dedup)
- `balance_snapshots` --- immutable time-series balance records
- `loan_details` --- key-value loan metadata snapshots

**Investment tables:**
- `portfolio_snapshots` --- total account value + cash balance per date
- `positions_ledger` --- share delta events (buys/sells/rebalances)
- `investment_holdings` --- daily per-ticker positions
- `benchmark_prices` --- cached market benchmark data (S&P 500, VTI, BND)
- `ticker_metadata` --- sector, industry, asset class per ticker

**Investment total priority** (when multiple sources disagree):
1. `portfolio_snapshots.total_account_value` --- preferred; scraped from brokerage
2. `SUM(investment_holdings.market_value)` --- fallback; per-ticker rollup
3. `balance_snapshots.balance` --- last resort; generic balance snapshot

**Derived/analytical tables:**
- `derived_summaries` --- scoped metric cache (net worth, monthly spend/income)
- `recurring_transactions` --- detected recurring patterns
- `recurring_mutations` --- price change history for recurring items
- `category_overrides` --- user-applied category corrections
- `merchant_snapshots` --- normalized merchant aggregations

**Planning tables:**
- `budgets` --- monthly budget targets per category
- `alert_rules` --- spending alert definitions
- `savings_goals` --- named financial targets with progress tracking
- `real_estate` --- property valuations

**System tables:**
- `refresh_runs` --- refresh session lifecycle
- `refresh_events` --- per-institution refresh event log
- `institution_refresh_status` --- staleness tracking
- `owners` --- multi-user ownership (active but UI-hidden until toggled)

### 4.3 Categorization Engine

Four-layer priority system (`dal/categorization.py`):

1. **User override** (`category_overrides` table) --- always wins
2. **Keyword rules** (`config/categories.yaml`) --- regex on description,
   first match wins, ~100 rules covering income, transfers, housing,
   food, transport, shopping, bills, entertainment, healthcare, financial
3. **Bank-provided category** --- e.g., NFCU sends categories from scraping
4. **Fallback:** "Uncategorized" --- triggers a toast prompting user action

**Teach-the-system flow (new):**

When a user categorizes an unknown transaction (e.g., a check):
1. User assigns category and merchant name
2. System offers: "Make this a recurring rule?"
3. If yes: match by exact amount or amount range?
4. Future matching transactions auto-categorize with assigned
   merchant name and category

This handles check-based utility payments (water/sewer monthly ~$55,
trash/recycling quarterly ~$105) and any other anonymous transactions.

### 4.4 Transfer Reconciliation

`dal/reconciliation.py` matches cross-institution debit/credit pairs:
- Same absolute amount (integer cents comparison)
- Opposite directions
- Different institutions
- Within 3-day posting window
- At least one has transfer keyword or category

Tagged pairs are excluded from income/spending calculations via
`transfer_tag IS NULL` in all analytical queries.

**Known risk:** A missed transfer inflates both income and spending.
The mortgage overfunding pattern (transfer to 0459 > mortgage payment)
requires special handling --- the excess is earmarked savings, not spending.

### 4.5 Archival Policy

System-wide rule for closed/completed accounts and contracts:
- **Active:** full visibility in all views and reports
- **Completed/closed:** visible through **December 31 of the year
  following completion**
- **Archived:** data remains in database, excluded from active views
  and reports unless explicitly queried

Applies to: BNPL contracts, paid-off loans, closed accounts.

---

## 5. Analytical Engine

### 5.1 Current Capabilities

| Capability | Module | Status |
|-----------|--------|--------|
| Monthly/quarterly/yearly cash flow | `dal/cash_flow.py` | Complete |
| Savings rate (post-tax) | `dal/cash_flow.py` | Complete (accuracy depends on categorization) |
| Spending by category | `dal/reports.py` | Complete |
| Spending comparison (vs. prior period) | `dal/reports.py` | Complete |
| Sankey flow (income sources -> spending categories) | `dal/reports.py` | Complete |
| Merchant ranking and trends | `dal/reports.py` | Complete |
| Net worth time series | `dal/reports.py` | Complete (real estate flaw: static across history) |
| Net worth point-in-time | `dal/derived.py` | Complete |
| Recurring detection + mutation tracking | `dal/recurring.py` | Complete |
| Cash flow forecasting | `dal/forecasting.py` | Complete (flat extrapolation only) |
| Budget vs. actual | `dal/budgets.py` | Complete |
| Debt payoff modeling (avalanche/snowball) | `dal/debt.py` | Complete |
| Investment TWR + benchmark comparison | `dal/performance.py` | Complete |
| Sector/asset-class allocation | `dal/allocation.py` | Complete |
| Savings goals with linked accounts | `dal/goals.py` | Complete |
| Spending alerts (budget %, large txn, low balance) | `dal/alerts.py` | Complete |
| Bill tracking (upcoming/overdue) | `dal/bills.py` | Complete |
| CSV transaction export | `dal/reports.py` | Complete |

### 5.2 Planned Capabilities

| Capability | What It Requires | Priority |
|-----------|------------------|----------|
| **Debt-to-income ratio (time series)** | Combine `debt.py` totals with `cash_flow.py` income. New DAL function. | High |
| **Interest cost tracking** | Aggregate interest paid YTD across all liabilities from `loan_details` (auto loan, mortgage) and transaction categories (credit card interest). Surface as "anti-wealth" metric. | High |
| **Net worth velocity** | Month-over-month and rolling-3mo/12mo rate of change. Computed from `get_net_worth_history()` output. | High |
| **Lifestyle creep detection** | Per-category annualized spending growth rate vs. income growth rate. Flag categories growing faster. | Medium |
| **Contributions vs. performance decomposition** | Separate "money I put in" from "market growth" for investment accounts. Use `positions_ledger` deltas + portfolio value changes. | Medium |
| **Savings rate (pre-tax/gross)** | Requires myPay RAS data for gross income. Blocked on document drop or myPay connector. | Medium |
| **Seasonal income modeling** | Recognize officiating income seasonality (Aug-Mar) from historical patterns. Override flat rolling averages in forecasting. | Medium |
| **Scenario projection engine** | User-defined future events (loan payoff, income change, major purchase) overlaid on current trajectory. New `dal/scenarios.py`. | Medium |
| **Emergency fund metric** | Liquid balance / avg monthly spending = months of runway. Simple computation, needs frontend surface. | High |
| **Recurring-to-loan linking** | Connect detected recurring payments to their source loan accounts, enabling payoff-date-aware forecasting. | Medium |
| **Vehicle equity tracking** | One-time vehicle detail entry + automated KBB/NADA value lookup. Asset = value - loan balance. | Low |
| **Credit score tracking** | Scrape from NFCU and Chase dashboards during Phase 1. Display as dual-pill KPI card. | Low |
| **Affirm HYSA APY tracking** | Scrape current APY from Affirm savings page. Display alongside interest earned. | Low |
| **Rewards points tracking** | Scrape from NFCU and Chase. Minor liquid asset. | Low |

### 5.3 Review System

**Monthly Review** (auto-generates on 1st of month or first app open):
- Income vs. spending vs. prior month
- Savings rate
- Net worth change from last month
- Budget vs. actual highlights
- Subscription price changes detected
- Notable transactions
- Account freshness status
- Data quality indicators

**Yearly Wrap-Up** (dedicated page, two-stage):
- **Preliminary** (January): built from transaction data, derived metrics,
  balance snapshots. Labeled "Preliminary."
- **Revised/Final** (February-March): overlays authoritative tax documents
  (1099s, 1098) as they arrive via document drop. Checklist toast tracks
  received vs. expected documents. Upgrades to "Final" when complete.

Yearly wrap-up contents:
- Total income (by stream), total spending (by category)
- Net worth trajectory for the year
- Category spending shifts vs. prior year
- Total interest paid vs. earned
- Investment performance vs. benchmark
- Debt paid down
- Recurring cost changes (subscription mutations)
- Savings goals progress
- Credit score trend

---

## 6. Frontend Architecture

### 6.1 Tech Stack

- **Framework:** React 18 + TypeScript
- **Desktop wrapper:** Tauri (Rust-based, lightweight)
- **Charting:** Recharts (primary), Tremor (KPI cards)
- **Styling:** Tailwind CSS + OKLCH design tokens, dark mode
- **State:** React hooks + fetch (no Redux)
- **API communication:** REST + SSE for real-time refresh progress

### 6.2 Pages

| Page | Purpose | Status |
|------|---------|--------|
| **Dashboard** | KPI cards (net worth, savings rate, credit scores, emergency fund months), spending chart, recent transactions, budget & recurring widgets | In progress (dummy data) |
| **Transactions** | Paginated table, filter popover, recurring toggle, add/categorize transaction, teach-the-system flow | In progress (dummy data) |
| **Cash Flow** | 18-month/9-quarter/4-year rolling charts, bar click drill-down, savings rate trend | In progress (dummy data) |
| **Reports** | Spending by category, Sankey flow, net worth history, category trend, spending comparison | In progress (dummy data) |
| **Accounts** | Account list with balance sparklines, institution freshness indicators, account-detail navigation | In progress (dummy data) |
| **Budgets** | Budget vs. actual per category, progress bars, month navigation | In progress (dummy data) |
| **Investments** | Portfolio summary, holdings table, performance vs. benchmark, contribution vs. growth decomposition | In progress (dummy data) |
| **Monthly Review** | Auto-generated monthly summary (see 5.3) | Planned |
| **Yearly Wrap-Up** | Preliminary -> Final annual review (see 5.3) | Planned |
| **Settings** | Multi-user toggle, refresh policy, document drop management, notification preferences | Planned |

### 6.3 Multi-User UI

- **Default:** Single-user mode. No selector visible. All data shown.
- **Activated via:** Settings menu toggle
- **When active:** Selector appears at top of app: **Mine | Theirs | Household**
- **Mine/Theirs:** Filters all views to accounts owned by that person
- **Household:** Combined view across both owners
- Architecture supports this from day one; every DAL query accepts
  optional `owner_id` filter

### 6.4 Notification System

| Type | Trigger | Behavior |
|------|---------|----------|
| **Document drop nudge** | Tier 3 institution not updated by 5th of month | Persistent toast, small, unmovable until resolved |
| **Uncategorized transaction** | New transactions land as Uncategorized | Toast prompting categorization action |
| **Subscription price change** | `recurring_mutations` entry created | Informational toast |
| **Budget alert** | Spending exceeds threshold | Toast per `alert_rules` configuration |
| **Refresh status** | Connector running/complete/failed | SSE-driven progress indicator |
| **MFA required** | TSP (or similar) connector paused at MFA | Modal toast with code entry field |
| **Tax document checklist** | Yearly wrap-up incomplete | Persistent toast in Jan-Mar tracking received vs. expected docs |

---

## 7. Data Capture Gaps & Planned Additions

### 7.1 Existing Connector Enhancements

| Institution | Missing Data | Value | Effort |
|------------|-------------|-------|--------|
| NFCU | Credit card APR, credit limit, min payment, due date | Debt modeling (partner), credit utilization | Medium --- add to Phase 1 scrape |
| NFCU | Savings APY/dividend rate | Cash comparison | Low |
| NFCU | Credit score (dashboard) | KPI pill | Low --- Phase 1 scrape addition |
| Chase | Credit score (Credit Journey) | KPI pill | Low --- Phase 1 scrape addition |
| Chase | APR, min payment, due date | Debt modeling (partner) | Medium |
| Fidelity | Cost basis (Positions CSV) | Unrealized P&L, tax-loss harvesting | Medium --- new CSV download |
| Fidelity | Dividend history aggregation | Passive income tracking | Low --- DAL function on existing data |
| Acorns | Fund allocation targets | Drift detection | Low |
| Affirm | HYSA APY | Cash rate comparison | Low --- Phase 1 scrape addition |
| TSP | Full browser connector with MFA bridge | Automated daily refresh of largest account | High --- new connector |

### 7.2 New Data Sources

| Source | Method | What It Provides | Priority |
|--------|--------|-----------------|----------|
| **myPay (DFAS)** | Document drop (RAS PDF); connector if feasible | Gross pension, tax withholding, SBP/insurance deductions, net pay | High |
| **Eventlink** | XLSX import + potential API | Historical officiating payments for seasonal modeling | Medium |
| **KBB/NADA** | Background API after one-time vehicle entry | Vehicle value for equity tracking | Low |
| **Tax documents** | Document drop (1099, 1098) | Authoritative yearly figures for revised wrap-up | Medium |

---

## 8. Pipeline Risk Mitigations

### 8.1 Transfer Detection Failures

**Risk:** Missed transfer inflates both income and spending.
**Mitigation:**
- Expand `_TRANSFER_KEYWORDS` as real data reveals missed patterns
- Monthly review flags unusual income spikes for manual verification
- Mortgage overfunding pattern: system must recognize that NFCU 0459
  receives more than the mortgage debits; excess is earmarked savings

### 8.2 Acorns Delta-Logging Partial Scrapes

**Risk:** Partial fund page loads record incomplete deltas; next full
scrape creates phantom implied transactions on wrong dates.
**Mitigation:**
- Connector must treat partial scrapes as failures (all-or-nothing)
- If any fund page times out, discard the entire scrape and log an error
- Never write partial position updates

### 8.3 TSP Data Staleness

**Risk:** As the largest account (~10x others), stale TSP data makes
net worth unreliable.
**Mitigation:**
- Build TSP browser connector with MFA bridge (Tier 2)
- Until then, document drop with persistent nudge toast
- All dashboard views must show data freshness per institution
- Net worth display should include a "data as of" indicator showing
  the oldest balance snapshot date across all contributing accounts

### 8.4 Categorization Accuracy

**Risk:** Uncategorized transactions count as spending (not income),
distorting savings rate.
**Mitigation:**
- Teach-the-system flow reduces Uncategorized over time
- Add income stream patterns to `categories.yaml` (Military Pension,
  VA Benefits, VA Education Benefits, Officiating Income)
- Officiating income: broad regex + teach-the-system for new districts
- Monthly review surfaces Uncategorized count as a data quality metric

---

## 9. Module Map

### Backend (`backend/`)

| Module | Purpose |
|--------|---------|
| `api_server.py` | FastAPI app, 45+ endpoints across 10 routers, SSE stream |
| `refresh_orchestrator.py` | Session lifecycle, staleness checks, retry logic |
| `automation_worker.py` | Connector bridge, SQLite persistence |
| `credential_broker.py` | UAC-elevated keyring access (seconds only) |
| `state_machine.py` | RefreshState enum, transitions, error classes |
| `ipc.py` | Temp-file IPC across UAC boundary, memory clearing |
| `result_writer.py` | Post-commit pipeline: categorize -> reconcile -> derive -> alert -> goal sync |
| `events.py` | SSE event bus for real-time refresh progress |

### Data Access Layer (`dal/`)

| Module | Purpose |
|--------|---------|
| `database.py` | Facade re-exporting public API from sub-modules |
| `connection.py` | SQLite connection factory: WAL, foreign keys, busy timeout |
| `migrations/` | Sequential schema DDL (v01--v12) |
| `seed.py` | Institution + account seeding from `accounts.yaml` |
| `transactions.py` | Upsert with SHA-256 identity hashing, pending->posted |
| `categorization.py` | 4-layer categorization engine |
| `balances.py` | Balance snapshots (immutable time-series), loan details |
| `investments.py` | Investment holdings CRUD, Decimal-precision columns |
| `recurring.py` | Recurring detection, frequency classification, mutation tracking |
| `bills.py` | Bill tracking: upcoming/overdue from recurring_transactions |
| `cash_flow.py` | Rolling-window cash flow: monthly/quarterly/yearly |
| `reports.py` | Spending by category, net worth history, Sankey, CSV export |
| `derived.py` | Scoped metric recomputation (net worth, monthly spend/income) |
| `forecasting.py` | Cash flow projection: recurring baseline + rolling averages |
| `budgets.py` | Monthly budget targets, budget-vs-actual |
| `alerts.py` | Spending alert engine with SSE-ready notifications |
| `goals.py` | Savings goal CRUD, progress tracking, linked-account sync |
| `debt.py` | Debt payoff modeling: avalanche/snowball strategies |
| `performance.py` | Investment TWR, benchmark comparison (S&P 500, VTI, BND) |
| `allocation.py` | Sector/asset-class allocation, yFinance enrichment |
| `reconciliation.py` | Cross-institution transfer matching and tagging |
| `merchant_normalizer.py` | Merchant name normalization |
| `owners.py` | Multi-user ownership, config-driven view resolution |
| `refresh_log.py` | Refresh run + event persistence |

### Extractors (`extractors/`)

| Module | Purpose |
|--------|---------|
| `nfcu_connector.py` | NFCU: 3-phase (balances, CSV, loan details + HomeSquad) |
| `chase_connector.py` | Chase: 2-phase (balances + available credit, CSV) |
| `fidelity_connector.py` | Fidelity: CSV-download automation + ingest pipeline |
| `acorns_connector.py` | Acorns: DOM scrape + delta-logging + yFinance enrichment |
| `affirm_connector.py` | Affirm: HYSA balance/txn + BNPL contract discovery |
| `tsp_connector.py` | **To be built:** TSP browser automation with MFA bridge |
| `sms_otp.py` | SMS OTP auto-capture via Windows Phone Link |
| `ai_backstop.py` | AI-powered selector healing (Gemini) |
| `dom_healer.py` | DOM analysis for broken selectors |
| `chrome_cdp.py` | Chrome DevTools Protocol launcher |
| `selector_registry.yaml` | Centralized CSS selectors per institution |

### Scripts (`scripts/`)

| Module | Purpose |
|--------|---------|
| `ingest_tsp.py` | TSP PDF statement parser + MaxTSP API enrichment |
| `fetch_tsp_prices.py` | TSP.gov share price history download |
| `ingest_fidelity_history.py` | Fidelity historical CSV backfill |
| `parse_acorns_pdf.py` | Acorns PDF statement parser for backfill |

### Frontend (`frontend/src/`)

| Module | Purpose |
|--------|---------|
| `App.tsx` | Tauri + React root: routing, sidebar, layout |
| `index.css` | OKLCH design tokens, dark mode, typography |
| `pages/DashboardPage.tsx` | KPI cards, spending charts, widgets |
| `pages/TransactionsPage.tsx` | Transaction table, filters, categorization |
| `pages/CashFlowPage.tsx` | Rolling cash flow charts |
| `pages/ReportsPage.tsx` | Category spend, Sankey, net worth, trends |
| `pages/AccountsPage.tsx` | Account list, balance sparklines |
| `pages/BudgetsPage.tsx` | Budget vs. actual |
| `pages/InvestmentsPage.tsx` | Portfolio, holdings, performance |

### Config (`config/`)

| File | Purpose |
|------|---------|
| `refresh_policy.yaml` | Per-institution refresh intervals |
| `categories.yaml` | Keyword -> category regex rules |
| `budgets.yaml` | Budget target definitions |
| `owner_config.yaml` | Multi-user ownership configuration |
| `logging_config.py` | Rotating file handlers, hierarchical loggers |

---

## 10. Development Workflow

### 10.1 Execution Model

Development uses a **plan-execute-verify** workflow across two AI models:

- **Claude (architect/verifier):** Creates architecture, writes detailed
  task prompts, verifies completed work, fixes small issues, sends back
  tasks with major issues
- **Gemini (implementer):** Executes individual task prompts. Receives
  one task at a time with tight scope boundaries. Never makes
  architectural decisions.

### 10.2 Document Structure

```
docs/
+-- ARCHITECTURE.md          <- this file (single source of truth)
+-- ROADMAP.md               <- phased plan with status markers
+-- prompts/                  <- one file per task, Gemini-ready
    +-- P1-T01_[name].md
    +-- P1-T02_[name].md
    +-- ...
```

### 10.3 Session Handoff Protocol

A fresh Claude session picks up work by:

1. Reading `docs/ARCHITECTURE.md` --- full system understanding
2. Reading `docs/ROADMAP.md` --- current status, what's done, what's next
3. Reading the specific task prompt for the current work item
4. Reading any files modified by the most recent Gemini execution

Status markers in ROADMAP.md:
- `[ ]` --- planned (not started)
- `[->]` --- in progress (prompt written, Gemini executing or awaiting)
- `[v]` --- complete (verified by Claude)
- `[!]` --- needs revision (Claude found issues, correction prompt needed)

### 10.4 Verification Protocol

After each Gemini task execution:

1. Claude reads all changed/created files
2. Checks against the task prompt's "done" checklist
3. Runs any specified tests
4. One of three outcomes:
   - **Approve:** Mark task `[v]` in ROADMAP.md, move to next task
   - **Fix:** Small issues corrected directly by Claude, mark `[v]`
   - **Revise:** Major issues documented, correction prompt written,
     task stays `[!]` until re-executed and re-verified
