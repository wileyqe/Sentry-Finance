# Sentry Finance — Competitor Analysis & Feature Backlog

> **Audience**: 1–2 users (you + partner eventually).  
> **Competitors surveyed**: Monarch Money, YNAB, Copilot Money, Empower, Simplifi by Quicken, Quicken Classic, Rocket Money.  
> **Date**: 2026-03-10  
> **Last updated**: 2026-03-10 (Session 2)

---

## How to read this document

Each feature lists:

- **Feature** — what it is
- **Description** — what competitors do
- **Seen In** — which competitors offer it
- **Sentry Status** — ✔ Already built, ⚙ Planned/partial, ✦ New, 🔧 In progress
- **Backend Requirements** — what Sentry Finance needs to support it

Features are ordered by priority: first the ownership toggle (your immediate request), then the highest-value gaps, then nice-to-haves.

---

## 1. Yours / Ours / Mine Ownership Toggle ✔

- **Description**: Dashboard view selector that filters all data by ownership context. "Mine" shows only your accounts. "Theirs" shows only your partner's. "Ours" shows the full combined picture. Every widget, metric, and report respects the active context. Monarch Money is the only competitor that does this well (they allow a second household member at no extra cost with separate logins and a shared dashboard).
- **Seen In**: Monarch Money (household member collaboration)
- **Sentry Status**: ✔ Complete — Schema V5, `dal/owners.py`, `owners` table, `owner_id` FK on `accounts`, `?view=mine|theirs|ours` query param on all account/transaction/budget endpoints
- **Built**: `dal/owners.py`, Schema V5 migration in `dal/database.py`, `config/owner_config.yaml`

---

## 2. Transaction Categorization ✔

- **Description**: Assign a category (Food & Dining, Utilities, Transportation, etc.) to every transaction. Most competitors use AI + rules. Monarch uses auto-categorize with user-trainable rules. YNAB requires manual categorization (part of their "every dollar has a job" philosophy). Copilot's AI categorization is considered best-in-class.
- **Seen In**: All competitors
- **Sentry Status**: ✔ Complete — 4-layer categorization engine (user override > keyword rules > bank category > fallback), refund/return rules, federal/state tax refund rules, backfill endpoint
- **Built**: `dal/categorization.py`, `config/categories.yaml` (250+ rules), `category_overrides` table (Schema V6), `PATCH /api/transactions/{id}/category`, `POST /api/categorize/backfill`

---

## 3. Budgeting ✔

- **Description**: Set monthly spending limits per category and track actuals against targets. YNAB's zero-based approach assigns every dollar. Monarch offers flex and category budgeting. Simplifi's "Spending Plan" computes what's left after bills and goals. Copilot adapts budgets based on spending patterns.
- **Seen In**: All competitors
- **Sentry Status**: ✔ Complete — budget targets per category/month, budget vs. actual (with pct_used + status), AI-style suggestions from historical spend (10% buffer, rounded to $25), ownership-aware
- **Built**: `dal/budgets.py`, `config/budgets.yaml`, `budgets` table (Schema V8), full REST API (`GET/PUT/DELETE /api/budgets/{category}`, `/api/budgets/summary`, `/api/budgets/suggest`, `/api/budgets/initialize`)

---

## 4. Cash Flow Forecasting 🔧

- **Description**: Project future account balances based on historical income/spending patterns and known upcoming bills. PocketSmith forecasts up to 30 years. Simplifi provides 12-month projected cash flow. Copilot shows income vs. spending vs. net income comparisons.
- **Seen In**: Simplifi, PocketSmith, Copilot Money, Empower
- **Sentry Status**: 🔧 In progress — recurring/bills infrastructure complete, `dal/forecasting.py` being built next
- **Backend Requirements**:
  - ~~`recurring_transactions` table (see #5 — dependency)~~ ✔ Done
  - `dal/forecasting.py` module: rolling average income/spend by category, project forward N months
  - Algorithm: sum known recurring + rolling average discretionary, apply to current balances
  - API endpoint: `GET /api/forecast?months=6` → array of `{month, projected_income, projected_spending, projected_balance}`
  - Ownership-aware: forecast scoped to mine/theirs/ours

---

## 5. Recurring Transaction Detection ✔

- **Description**: Automatically identify subscriptions and recurring bills (same merchant, similar amount, regular interval). Monarch and Rocket Money both auto-detect and surface a subscription list. Simplifi has a dedicated Bills & Subscriptions tracker with payment reminders.
- **Seen In**: Monarch, Rocket Money, Simplifi, Copilot
- **Sentry Status**: ✔ Complete — merchant normalization engine, frequency band classification (weekly/biweekly/monthly/quarterly/semiannual/annual), price mutation detection, auto-deactivation after 2× missed interval
- **Built**: `dal/recurring.py`, `recurring_transactions` + `recurring_mutations` tables (Schema V7), full REST API (`GET /api/recurring`, `POST /api/recurring/scan`, `PATCH /api/recurring/{id}`, `GET /api/recurring/summary`)

---

## 6. Bill Tracking & Reminders ✔

- **Description**: Track upcoming bills with due dates and amounts. Alert when a bill is approaching or overdue. Simplifi's "Bill Connect" automates recurring credit card payments. Emma groups bills by due date.
- **Seen In**: Monarch, Simplifi, Emma, Rocket Money
- **Sentry Status**: ✔ Complete — upcoming/overdue bill lists with days_until, due_soon (≤3 days), dashboard bill summary
- **Built**: `dal/bills.py`, REST API (`GET /api/bills/upcoming`, `GET /api/bills/overdue`, `GET /api/bills/summary`)

---

## 7. Spending Alerts 🔧

- **Description**: Notify the user when spending in a budget category exceeds a threshold (e.g., 80% of monthly target, or 100%). Copilot and Simplifi provide real-time spending warnings. Rocket Money sends alerts for unusual large charges.
- **Seen In**: Copilot, Simplifi, Rocket Money, Spendee
- **Sentry Status**: 🔧 In progress — SSE broadcast infrastructure already exists; `alert_rules` table + `dal/alerts.py` being built next
- **Backend Requirements**:
  - `alert_rules` table: `id TEXT PK, rule_type TEXT, scope TEXT, threshold REAL, enabled INTEGER, created_at TEXT`
  - Rule types: `budget_pct` (80% of budget), `large_txn` (single transaction > $X), `balance_low` (account balance < $X)
  - `dal/alerts.py` module: evaluate rules after each refresh, emit alert events
  - Alert delivery: SSE events (existing `_broadcast_event()` in `api_server.py`), Windows toast via PowerShell
  - ~~Depends on: Budgeting (#3)~~ ✔ Done

---

## 8. Savings Goals ✔

- **Description**: Set financial goals (emergency fund, vacation, down payment) with target amounts and deadlines. Track progress over time. Copilot's AI suggests goals based on cash flow. YNAB integrates goals directly into the budget.
- **Seen In**: YNAB, Copilot, Simplifi, Monarch
- **Sentry Status**: ✔ Complete — CRUD, auto-sync from linked savings accounts, deadline-aware trajectory (on_track/behind/overdue), dashboard summary
- **Built**: `dal/goals.py`, `savings_goals` table (Schema V10), REST API (`GET/POST /api/goals`, `PATCH /api/goals/{id}/amount`, `POST /api/goals/sync`, `DELETE /api/goals/{id}`, `GET /api/goals/summary`)

---

## 9. Investment Performance & Benchmarking ✔

- **Description**: Track portfolio performance over time and compare against benchmarks (S&P 500, total market). Empower is the gold standard here with portfolio analysis, fee analyzer, and Monte Carlo retirement projections. Monarch compares performance against the S&P 500.
- **Seen In**: Empower, Monarch, Copilot
- **Sentry Status**: ✔ Complete — time-weighted return (TWR) calculation, ^GSPC/VTI/BND benchmark caching via yfinance, alpha computation, multi-account summary
- **Built**: `dal/performance.py`, `benchmark_prices` table (Schema V10), REST API (`GET /api/investments/performance`)

---

## 10. Sector / Asset Allocation Visualization ✔

- **Description**: Pie chart or sunburst showing portfolio breakdown by sector, asset class, or account type. Empower shows asset allocation by class (stocks, bonds, cash, alternatives). Monarch shows investment allocation to help adjust risk profiles.
- **Seen In**: Empower, Monarch, Copilot
- **Sentry Status**: ✔ Complete — lazy yfinance enrichment with hardcoded ETF/TSP overrides, 30-day staleness cache, three allocation views (by sector, by asset class, by account)
- **Built**: `dal/allocation.py`, `ticker_metadata` table (Schema V10), REST API (`GET /api/investments/allocation`)

---

## 11. AI Financial Assistant ✦

- **Description**: Natural language Q&A over your financial data. Monarch launched an AI assistant that answers questions like "How much did I spend on groceries last month?" or "What's my average monthly income?" Copilot uses AI for transaction categorization and budget suggestions.
- **Seen In**: Monarch, Copilot
- **Sentry Status**: ✦ New — but infrastructure partially exists (Gemini API integration via `ai_backstop.py`)
- **Backend Requirements**:
  - `backend/ai_assistant.py` module: accept natural language query, generate SQL or DAL calls, return structured answer
  - Reuse existing Gemini API key and cost-tracking pattern from `ai_backstop.py`
  - Safety: read-only queries only, parameterized SQL, never expose raw DB to the model
  - API endpoint: `POST /api/ai/ask` → `{question, answer, cost_usd}`
  - Rate limiting: reuse session caching pattern from `ai_backstop.py`
  - Low priority for 1–2 user audience — you can just query the DB directly

---

## 12. Real Estate Tracking ✔

- **Description**: Track property values for net worth computation. Monarch syncs with Zillow Zestimates. Copilot supports manual real estate entries. Simplifi added Zillow integration in 2025.
- **Seen In**: Monarch, Copilot, Simplifi
- **Sentry Status**: ✔ Already built — `real_estate` table + multi-source valuation (Zillow, Redfin, Realtor.com, NFCU) via [scripts/seed_real_estate.py](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/scripts/seed_real_estate.py)
- **Backend Requirements**: None — already exceeds competitors by using multi-source mean estimation instead of single-source Zillow

---

## 13. Debt Payoff Planning ✔

- **Description**: Track debt balances with interest rates, model payoff strategies (snowball vs. avalanche), show total interest saved. YNAB has a built-in loan calculator. Monarch tracks loan details. Empower shows liability breakdown.
- **Seen In**: YNAB, Monarch, Empower
- **Sentry Status**: ✔ Complete — avalanche and snowball simulation, month-by-month amortization, APR from loan_details, minimum payment rollover, comparison table
- **Built**: `dal/debt.py`, REST API (`GET /api/debt/summary`, `GET /api/debt/payoff?strategy=avalanche&extra_payment=200`)

---

## 14. Customizable Reports & Data Export ✦

- **Description**: Generate spending reports by category, time period, account, or tag. Export to CSV/PDF. Monarch offers Sankey diagrams for cash flow. Quicken Classic has the most advanced reporting with custom saved reports.
- **Seen In**: All competitors (varying depth)
- **Sentry Status**: ✦ New (API data exists, no report generation)
- **Backend Requirements**:
  - `backend/reports.py` module: parameterized report queries (spending by category, income vs. expense, net worth over time)
  - API endpoints: `GET /api/reports/spending`, `GET /api/reports/cash-flow`, `GET /api/reports/net-worth-history`
  - CSV export: `GET /api/export/transactions?format=csv`
  - Ownership-aware: all reports filterable by owner
  - Frontend (Phase 8): chart rendering (Chart.js or similar)

---

## 15. Net Worth Tracking Over Time ✔

- **Description**: Historical net worth chart showing assets vs. liabilities over months/years. All competitors offer this. Monarch and Empower have the most detailed breakdowns.
- **Seen In**: All competitors
- **Sentry Status**: ✔ Already built — `recompute_net_worth()` stores in `derived_summaries`, `balance_snapshots` and `portfolio_snapshots` provide history
- **Backend Requirements**: Minor — `GET /api/net-worth/history` endpoint querying date-stamped snapshots from `balance_snapshots` (being added with reports module)

---

## 16. Multi-Currency Support ✦

- **Description**: Handle accounts in different currencies with exchange rate conversion. Monarch supports multi-currency. Quicken Classic has built-in multi-currency.
- **Seen In**: Monarch, Quicken Classic
- **Sentry Status**: ✦ New — No need currently (all USD accounts)
- **Backend Requirements**:
  - `currency TEXT DEFAULT 'USD'` column on [accounts](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/backend/api_server.py#115-135) table
  - Exchange rate lookup (via free API like exchangerate-api.com)
  - Net worth computation in a base currency
  - **Priority: Very Low** — skip unless partner has non-USD accounts

---

## 17. Credit Score Tracking ✦

- **Description**: Display credit score and score history. Simplifi added this in 2025. Monarch and Credit Karma provide it.
- **Seen In**: Simplifi, Credit Karma (via Monarch integration)
- **Sentry Status**: ✦ New
- **Backend Requirements**:
  - `credit_scores` table: `id INTEGER PK, score INTEGER, source TEXT, as_of TEXT, created_at TEXT`
  - Manual entry or scrape from a free source (Credit Karma, NFCU dashboard)
  - API endpoint: `GET /api/credit-score/history`
  - **Priority: Low** — nice-to-have, not core financial management

---

## Summary: What Sentry Already Beats Competitors On

- **Data sovereignty**: All data local, no cloud dependency, no Plaid/MX aggregator outages
- **Multi-source real estate valuation**: Competitors use only Zillow; Sentry uses 4 sources with mean estimation
- **Self-healing selectors**: AI backstop for bank UI changes — no competitor has this
- **Fractional-share precision**: TEXT-based decimal columns avoid IEEE 754 drift
- **Zero subscription cost**: Competitors charge $95–$109/year; Sentry is free forever
- **Direct browser automation**: No dependency on data aggregators (Plaid, MX, Finicity) that frequently break connections

---

## Build Order & Status

| # | Feature | Status | Session |
|---|---------|--------|--------|
| 1 | Ownership Toggle | ✔ Complete | Session 1 |
| 2 | Transaction Categorization | ✔ Complete | Session 1 |
| 3 | Recurring Transaction Detection | ✔ Complete | Session 1 |
| 4 | Budgeting (targets + vs-actual + suggestions) | ✔ Complete | Session 1 |
| 5 | Bill Tracking (upcoming / overdue / summary) | ✔ Complete | Session 1 |
| 6 | Cash Flow Forecasting | ✔ Complete | Session 2 |
| 7 | Spending Alerts (budget_pct / large_txn / balance_low) | ✔ Complete | Session 2 |
| 8 | Reports & Data Export (spending, cash-flow, net-worth history) | ✔ Complete | Session 2 |
| 9 | Savings Goals (CRUD, deadline trajectory, linked accounts) | ✔ Complete | Session 2 |
| 10 | Investment Performance & Benchmarking (TWR vs S&P 500) | ✔ Complete | Session 2 |
| 11 | Sector / Asset Allocation (by sector, asset class, account) | ✔ Complete | Session 2 |
| 12 | Debt Payoff Planning (avalanche vs. snowball, comparison) | ✔ Complete | Session 2 |
| 13 | AI Financial Assistant | ✦ Backlog | — |
| 14 | Multi-Currency | ✦ Low Priority | — |
| 15 | Credit Score Tracking | ✦ Low Priority | — |
