# Sentry Finance --- Development Roadmap

> **Status tracking document.** Updated after each task verification.
> Read alongside `ARCHITECTURE.md` for full context.
>
> Last updated: 2026-04-06 (Phases 0–10 complete pending user acceptance)

## Status Key

- `[ ]` --- Planned (not started)
- `[->]` --- In progress (prompt written, executing or awaiting)
- `[v]` --- Complete (verified by Claude)
- `[!]` --- Needs revision (issues found, correction prompt needed)

## Session Handoff

New Claude session? Read in this order:
1. `docs/ARCHITECTURE.md` (full system context)
2. This file (current status, find the next `[ ]` or `[!]` task)
3. The specific prompt file for the current task

---

## Phase 0: Foundation & Data Quality

**Goal:** Ensure the analytical engine produces trustworthy numbers
before building new features on top of them. Fix categorization gaps,
transfer detection, and data freshness visibility.

**Why first:** Every subsequent feature depends on accurate income,
spending, and balance data. Building on bad foundations wastes effort.

### Tasks

- `[v]` **P0-T01: Income stream & categorization rules**
  Added Military Pension, VA Benefits, VA Education Benefits, and
  Officiating Income patterns to `categories.yaml` and both
  `_INCOME_CATEGORIES` sets. Verified 2026-03-29.
  Prompt: `docs/prompts/P0-T01_military-categorization.md`

- `[v]` **P0-T02: Teach-the-system flow (backend)**
  Created `dal/user_rules.py`, `dal/migrations/v13_user_rules.py`,
  `backend/routers/user_rules.py`. Layer 1.5 in categorization engine.
  Claude fixed: missing avg_interval in recurring INSERT, stale docstring.
  Verified 2026-03-29.
  Prompt: `docs/prompts/P0-T02_teach-the-system-backend.md`

- `[v]` **P0-T03: Transfer reconciliation hardening**
  Expanded keywords (+11), added same-institution transfer matching
  (1-day window, second pass), mortgage overfunding comment block,
  7 integration tests (all passing). Verified 2026-03-29.
  Prompt: `docs/prompts/P0-T03_transfer-hardening.md`

- `[v]` **P0-T04: Data freshness indicators (backend)**
  Created `dal/freshness.py` (3 functions + tier classification) and
  `backend/routers/freshness.py` (3 endpoints). Router registered in
  api_server.py. Claude fixed: `WHERE status = 'open'` → `WHERE is_active = 1`
  (accounts table has no `status` column). Verified 2026-03-29.
  Prompt: `docs/prompts/P0-T04_data-freshness-api.md`

- `[v]` **P0-T05: Acorns all-or-nothing scrape guard**
  Guard added in `_scrape_positions()`: collects all fund results in
  memory, returns `[]` on any failure (discarding all fund data),
  portfolio snapshot still written. Clean implementation, no bugs found.
  Verified 2026-03-29.
  Prompt: `docs/prompts/P0-T05_acorns-scrape-guard.md`

---

## Phase 1: Core Derived Metrics

**Goal:** Build the analytical metrics that transform raw data into
command-center-grade insights. These are the numbers the user actually
makes decisions from.

**Depends on:** Phase 0 (accurate categorization and transfer tagging)

### Tasks

- `[v]` **P1-T01: Emergency fund metric**
  Added `compute_emergency_fund_months()` to `dal/derived.py`. Uses
  account type (checking/savings), 6-month spending average, proper
  exclusions. Wired into recompute pipeline. Endpoint at
  `/api/metrics/emergency-fund`. No bugs found. Verified 2026-03-29.
  Prompt: `docs/prompts/P1-T01_emergency-fund-metric.md`

- `[v]` **P1-T02: Debt-to-income ratio (time series)**
  Added `compute_dti_ratio()` to `dal/derived.py`. Category-based debt
  detection only (Mortgage, Auto Loan, Credit Card Payments) — no
  account-type JOIN to prevent double-counting. Threshold bands: healthy
  <28%, moderate <36%, high <43%, critical ≥43%. Stored per-month in
  `derived_summaries`. Endpoint at `/api/metrics/dti`. Claude fixed:
  double-counting bug (removed OR clause + accounts JOIN; debt is
  category-only). 4/4 tests passing. Verified 2026-03-29.
  Prompt: `docs/prompts/P1-T02_debt-to-income.md`

- `[v]` **P1-T03: Interest cost tracking**
  Added `compute_interest_cost()` to `dal/derived.py`. Prefers
  `loan_details` YTD fields over transactions; falls back to Interest
  category transactions. Tracks interest earned (savings/HYSA credits)
  and net interest cost. Stored in `derived_summaries`. Endpoint at
  `/api/metrics/interest-cost`. No bugs found. 3/3 tests passing.
  Verified 2026-03-29.
  Prompt: `docs/prompts/P1-T03_interest-cost-tracking.md`

- `[v]` **P1-T04: Net worth velocity**
  Added `compute_net_worth_velocity()` to `dal/derived.py`. Computes
  MoM, rolling-3m, rolling-12m change rates from `get_net_worth_history()`
  output. Trend classification: accelerating/steady/decelerating/declining/
  insufficient_data. Stored in `derived_summaries`. Endpoint at
  `/api/metrics/net-worth-velocity`. No bugs found. 4/4 tests passing.
  Verified 2026-03-29.
  Prompt: `docs/prompts/P1-T04_net-worth-velocity.md`

- `[v]` **P1-T05: Fix real estate static history**
  Replaced static RE query in `get_net_worth_history()` with a per-month
  time-aware lookup: builds a per-property valuation timeline from
  `real_estate.as_of`, then for each history month picks the most recent
  valuation known at that time. Months before any valuation exist show 0.
  Source audit rows (name with `[`) excluded. `recompute_net_worth()` in
  `dal/derived.py` left unchanged (point-in-time latest is correct there).
  No bugs found. 7/7 tests passing. Verified 2026-03-29.
  Prompt: `docs/prompts/P1-T05_real-estate-history-fix.md`

- `[v]` **P1-T06: Derived metrics SQL fix**
  Fixed both broken queries in `recompute_account_metrics()`: spending
  and income now use proper f-string parameterized `NOT IN`/`IN` with
  category sets, plus `signed_amount` sign guards. Functional test
  confirms correct filtering. Verified 2026-03-29.
  Prompt: `docs/prompts/P1-T06_derived-sql-fix.md`

---

## Phase 2: TSP Connector & Document Drop

**Goal:** Close the biggest data quality gap (TSP staleness) and build
the document drop infrastructure for institutions that resist automation.

**Depends on:** Phase 0 (freshness indicators show the problem)

### Tasks

- `[v]` **P2-T01: TSP connector with MFA bridge**
  `extractors/tsp_connector.py` — full Playwright browser connector for
  TSP.gov using verified Okta selectors (`#okta-signin-username`,
  `#okta-signin-password`, `#okta-signin-submit`). Pauses at MFA screen,
  broadcasts `mfa_required` SSE event, resumes after code submission via
  `backend/mfa_bridge.py` (thread-safe bridge with timeout). Balance
  written to `self._result_balances["7777"]` — standard pipeline handles
  DB persistence. Graceful fallback to base-class polling if Okta MFA
  screen not detected. `backend/routers/mfa.py` — POST submit + GET
  status endpoints. `MFAModal.tsx` — independent SSE subscription,
  Framer Motion overlay, numeric input (max 6 chars). TSP registered in
  `extractors/__init__.py` and `selector_registry.yaml`. Account 7777
  wired in `config/accounts.yaml`. Verified 2026-03-29.
  Prompt: `docs/prompts/P2-T01_tsp-connector.md`

- `[v]` **P2-T02: Document drop backend**
  `dal/parsers/` package with `base.py` (ABC + ParseResult) and
  `tsp_statement.py` (adapts ingest_tsp.py to bytes input). `dal/document_drop.py`
  recognition chain. `backend/routers/documents.py` with upload, commit,
  history, pending-nudges endpoints. V14 migration (`document_drops` table).
  Claude fixed: `date` import moved to module level (was inside function,
  blocking patch), `refresh_run_id` column added to test fixture.
  Also fixed `documents.py` duplicate INSERT in upload endpoint.
  23/23 tests passing. Verified 2026-03-29.
  Prompt: `docs/prompts/P2-T02_document-drop-backend.md`

- `[v]` **P2-T03: Document drop frontend**
  `DocumentDrop.tsx` (6-state machine: idle/uploading/preview/committing/
  success/error), drag events with preventDefault, 50 MB client-side guard,
  FormData upload (no manual Content-Type), Framer Motion preview modal with
  parser type pill, snakeToTitle key rendering, contextual commit label.
  `DocumentsPage.tsx` at `/documents` with 5-column history table.
  `DocumentNudge.tsx` polling + localStorage dismiss-until-midnight.
  `/documents` route wired, nav item added, nudge rendered inside Router.
  TypeScript 0 errors, Vite build clean. Verified 2026-03-29.
  Prompt: `docs/prompts/P2-T03_document-drop-frontend.md`

- `[v]` **P2-T04: myPay RAS parser**
  `dal/parsers/mypay_ras.py` — DFAS Retiree Account Statement PDF parser.
  Extracts gross pension, federal/state tax, SBP premium, health/dental/
  vision deductions, net pay, pay period. V15 migration (`payroll_snapshots`
  table with UNIQUE(pay_period, source)). Registered in document drop chain.
  myPay nudge in pending-nudges endpoint. 15/15 tests passing.
  Verified 2026-03-31.
  Prompt: `docs/prompts/P2-T04_mypay-parser.md`

---

## Phase 3: Forecasting & Decision Support

**Goal:** Move the system from backward-looking to forward-looking.
Answer "what if" questions without manual math.

**Depends on:** Phase 1 (accurate derived metrics to project from)

### Tasks

- `[v]` **P3-T01: Seasonal income modeling**
  `dal/forecasting.py` — `build_seasonal_income_model()` decomposes income
  into 4 streams: flat pension, flat disability, episodic education (on/off
  months), seasonal officiating (per-month coefficients). Outlier exclusion
  via 3× median threshold. Composite projection integrated into
  `get_cash_flow_forecast()` with `use_seasonal=True`. Endpoint at
  `/api/income/seasonal-model`. Verified 2026-03-31.
  Prompt: `docs/prompts/P3-T01_seasonal-income.md`

- `[v]` **P3-T02: Recurring-to-loan linking**
  `dal/recurring.py` — `link_recurring_to_loans()` auto-matches recurring
  payments to loan accounts (3-strategy: same-institution, cross-institution,
  balance-relative). V16 migration adds `linked_account_id` to
  `recurring_transactions`. `get_recurring_with_payoff()` enriches with
  maturity_date, months_remaining, total_remaining. Freed cash flow
  projected in scenarios. Endpoints at `/api/recurring/link-loans` and
  `/api/recurring/with-payoff`. Verified 2026-03-31.
  Prompt: `docs/prompts/P3-T02_recurring-loan-link.md`

- `[v]` **P3-T03: Scenario projection engine**
  `dal/scenarios.py` — `project_scenario()` accepts user-defined events
  (income_change, expense_change, one_time, loan_payoff, investment_return)
  and projects up to 120 months. Tracks baseline vs. scenario with net
  worth impact. Uses seasonal model, recurring baseline, and debt schedule.
  Endpoint at `POST /api/scenarios/project`. Verified 2026-03-31.
  Prompt: `docs/prompts/P3-T03_scenario-engine.md`

- `[v]` **P3-T04: Debt payoff vs. invest comparison**
  `dal/debt.py` — `compare_debt_payoff_vs_invest()` computes break-even
  between extra loan payments (guaranteed APR savings) and investing
  (variable TWR). Includes avalanche/snowball payoff plans via
  `get_payoff_plan()`. Endpoints at `POST /api/analysis/debt-vs-invest`,
  `GET /api/analysis/debt-vs-invest/options`, `GET /api/debt/summary`,
  `GET /api/debt/payoff`. Verified 2026-03-31.
  Prompt: `docs/prompts/P3-T04_debt-vs-invest.md`

---

## Phase 4: Connector Enhancements & New Data Sources

**Goal:** Fill remaining data capture gaps identified in the audit.

**Depends on:** Phase 0 (foundation), can overlap with Phase 3

### Tasks

- `[v]` **P4-T01: NFCU credit card detail scraping**
  NFCU connector extracts APR, credit limit, minimum payment, due date
  via field patterns. Stored in `loan_details` key-value table.
  Verified 2026-03-31.
  Prompt: `docs/prompts/P4-T01_nfcu-cc-details.md`

- `[v]` **P4-T02: Credit score scraping**
  NFCU (`_scrape_credit_score()` → FICO) and Chase (`_scrape_credit_score()`
  → VantageScore 3.0) connectors extract scores. V17 migration creates
  `credit_scores` table. `dal/credit_scores.py` handles persistence with
  deduplication. Endpoint at `GET /api/metrics/credit-scores`.
  Verified 2026-03-31.
  Prompt: `docs/prompts/P4-T02_credit-score-scraping.md`

- `[v]` **P4-T03: Affirm HYSA APY scraping**
  Affirm connector extracts APY via regex pattern, persists alongside
  balance data. Verified 2026-03-31.
  Prompt: `docs/prompts/P4-T03_affirm-apy.md`

- `[v]` **P4-T04: Fidelity cost basis (Positions CSV)**
  `_download_positions_csv()` added to Fidelity connector as Phase 1.5
  download step. Cost basis parsed and stored in `investment_holdings`
  (v03 schema) and `loan_details`. Verified 2026-03-31.
  Prompt: `docs/prompts/P4-T04_fidelity-cost-basis.md`

- `[v]` **P4-T05: Eventlink import**
  `dal/parsers/eventlink.py` — XLSX/CSV parser with auto-detection by
  filename and PK ZIP header. Extracts game date, pay date, amount,
  sport, level, role. Deduplicates on 7-day window + exact amount.
  Registered in document drop chain. Verified 2026-03-31.
  Prompt: `docs/prompts/P4-T05_eventlink-import.md`

- `[v]` **P4-T06: Vehicle equity tracking**
  `dal/vehicles.py` with `add_vehicle()`, `add_valuation()`,
  `get_vehicle_equity_history()`. V18 migration creates `vehicle_assets`
  and `vehicle_valuations` tables. Vehicle values integrated into
  `get_net_worth_history()` with time-aware lookup. Endpoints at
  `GET /api/vehicles` and `GET /api/metrics/vehicle-equity`.
  Verified 2026-03-31.
  Prompt: `docs/prompts/P4-T06_vehicle-equity.md`

- `[v]` **P4-T07: Tax document parsers (1099, 1098)**
  Five parsers built: `dfas_1099r.py` (DFAS 1099-R), `fidelity_1099.py`
  (Fidelity consolidated), `acorns_1099.py` (Acorns), `affirm_1099int.py`
  (Affirm 1099-INT), `nfcu_1098.py` (NFCU mortgage interest). All
  registered in document drop chain. Tax summary endpoint at
  `GET /api/documents/tax-summary/{year}`. Verified 2026-03-31.
  Prompt: `docs/prompts/P4-T07_tax-doc-parsers.md`

---

## Phase 5: Frontend Live Data Integration

**Goal:** Connect all 7 existing frontend pages to real API data,
replacing dummy data. Add new dashboard KPI cards and the
teach-the-system categorization flow.

**Depends on:** Phase 0 (data quality), Phase 1 (derived metrics exist)

### Tasks

- `[v]` **P5-T01: Dashboard live data + new KPIs**
  DashboardPage.tsx wired to 11 API endpoints. KPI cards: net worth
  (with velocity arrow, color-coded), monthly net flow / savings rate,
  emergency fund runway, credit scores (dual pill with color brackets).
  Data freshness indicator (green <24h, amber <72h, red >72h).
  Verified 2026-03-31.
  Prompt: `docs/prompts/P5-T01_dashboard-live.md`

- `[v]` **P5-T02: Transactions page live data + teach-the-system**
  TransactionsPage.tsx wired to `/api/transactions` with pagination,
  filters, date ranges. Categorization teaching flow: category select,
  merchant naming, match type/string, mark recurring. Advanced filter
  UI (account, merchant search, amount range, custom dates). Recurring
  merchant highlighting via `/api/recurring`. Verified 2026-03-31.
  Prompt: `docs/prompts/P5-T02_transactions-live.md`

- `[v]` **P5-T03: Cash flow page live data**
  CashFlowPage.tsx wired to `/api/cash-flow/monthly-rolling`,
  `quarterly-rolling`, `yearly` with optional account_id filtering.
  Period detail on chart bar click. Verified 2026-03-31.
  Prompt: `docs/prompts/P5-T03_cashflow-live.md`

- `[v]` **P5-T04: Reports page live data**
  ReportsPage.tsx wired to `/api/reports/flow` and `/api/transactions`.
  Full Sankey chart (custom SVG, bi-color gradients, hover states,
  clickable nodes). Income/spending split with savings calculation.
  Verified 2026-03-31.
  Prompt: `docs/prompts/P5-T04_reports-live.md`

- `[v]` **P5-T05: Accounts page live data + freshness badges**
  AccountsPage.tsx wired to `/api/accounts`, `/api/freshness`,
  `/api/reports/net-worth-history`, `/api/documents/pending-nudges`.
  Per-institution freshness badges (green/yellow/red). Account grouping
  by type. Document drop nudge integration. Verified 2026-03-31.
  Prompt: `docs/prompts/P5-T05_accounts-live.md`

- `[v]` **P5-T06: Budgets page live data**
  BudgetsPage.tsx wired to `/api/budgets` with month selector.
  Create/update/delete via PUT/DELETE. Budget-vs-actual tracking with
  category breakdown. Spending pie chart. Verified 2026-03-31.
  Prompt: `docs/prompts/P5-T06_budgets-live.md`

- `[v]` **P5-T07: Investments page live data**
  InvestmentsPage.tsx wired to `/api/accounts`, `/api/investments/holdings`,
  `/api/investments/allocation`, `/api/investments/performance`. Account
  filter, sector allocation pie chart, performance cards with cumulative
  returns. Covers Fidelity, Acorns, TSP. Verified 2026-03-31.
  Prompt: `docs/prompts/P5-T07_investments-live.md`

---

## Phase 6: Reviews & Lifestyle Analysis

**Goal:** Build the periodic review system and the analytical features
that detect trends the user wouldn't notice from raw numbers.

**Depends on:** Phase 1 (derived metrics), Phase 5 (live frontend)

### Tasks

- `[v]` **P6-T04: Lifestyle creep detection**
  `dal/lifestyle.py` — per-category annualized spending growth rate vs.
  income growth rate. Flags categories growing faster than income by
  > 5 pp. Reusable `LifestyleCreepPanel.tsx` component. Endpoint at
  `GET /api/lifestyle/creep`. 5/5 Phase 6 tests passing. Verified 2026-03-31.
  Prompt: `docs/prompts/Phase-6/P6-T04_lifestyle-creep.md`

- `[v]` **P6-T05: Contributions vs. performance decomposition**
  `dal/performance.py` — `decompose_contributions_vs_performance()` separates
  deposits from market gains using Simple Dietz method. Per-account stacked
  bar on InvestmentsPage.tsx. Endpoint at
  `GET /api/investments/contributions-vs-performance`. Verified 2026-03-31.
  Prompt: `docs/prompts/Phase-6/P6-T05_contributions-vs-performance.md`

- `[v]` **P6-T01: Monthly review page**
  `dal/review.py` assembler + `MonthlyReviewPage.tsx`. Income/spending/
  savings rate vs. prior month, net worth delta, budget highlights,
  subscription changes, top 5 notable transactions, uncategorized count,
  lifestyle flags, data freshness. Endpoint: `GET /api/review/monthly`.
  Verified 2026-03-31.
  Prompt: `docs/prompts/Phase-6/P6-T01_monthly-review.md`

- `[v]` **P6-T02: Yearly wrap-up page (preliminary)**
  `dal/yearly_wrapup.py` assembler + `YearlyWrapUpPage.tsx`. Ten sections
  covering full yearly financial summary. Status always "preliminary."
  Endpoint: `GET /api/review/yearly`. Verified 2026-03-31.
  Prompt: `docs/prompts/Phase-6/P6-T02_yearly-wrapup-preliminary.md`

- `[v]` **P6-T03: Yearly wrap-up revised (tax doc integration)**
  `dal/yearly_wrapup.py` extended with `get_tax_doc_checklist()` and
  `overlay_tax_documents()`. Status upgrades: preliminary → revised → final.
  Checklist endpoint: `GET /api/review/yearly/tax-checklist`.
  Verified 2026-03-31.
  Prompt: `docs/prompts/Phase-6/P6-T03_yearly-wrapup-revised.md`

---

## Phase 7: Settings & Multi-User Prep

**Goal:** Build the settings infrastructure and ensure multi-user
readiness for partner integration.

**Depends on:** Phase 5 (frontend functional), Phase 6 (review pages)

### Tasks

- `[v]` **P7-T02: Owner-scoped DAL audit**
  `owner_id: str | None = None` added to ~30 DAL functions across
  transactions, balances, reports, cash_flow, derived, debt, recurring,
  freshness, lifestyle, review, yearly_wrapup, performance. Uses
  `resolve_account_ids_for_view()` inside each DAL function (not routers).
  All router endpoints pass `owner_id` through (86 occurrences).
  `tests/test_owner_scoping.py` with 3 test cases. 140/140 tests passing,
  0 regressions. Verified 2026-03-31.
  Prompt: `docs/prompts/Phase-7/P7-T02_owner-scoped-audit.md`

- `[v]` **P7-T01: Settings page**
  V20 migration creates `app_settings` key-value table with 6 seed defaults.
  `dal/settings.py` with get/set/get_all. `backend/routers/settings.py`
  with GET/PATCH, VALID_KEYS enforcement, refresh-policy merge, and
  multi-user-enabled convenience endpoint. `SettingsPage.tsx` with
  settings management UI. Verified 2026-03-31.
  Prompt: `docs/prompts/Phase-7/P7-T01_settings-page.md`

- `[v]` **P7-T03: Multi-user UI (selector + onboarding)**
  `ViewContext.tsx` provider with mine/theirs/household state, localStorage
  persistence. `ViewSelector.tsx` segmented control (hidden when disabled).
  `useOwnerApi` hook auto-appends `owner_id`. All 9 data pages updated
  (DashboardPage, AccountsPage, CashFlowPage, InvestmentsPage,
  MonthlyReviewPage, YearlyWrapUpPage use owner-scoped fetches).
  `PartnerOnboarding.tsx` 3-step flow. TypeScript clean. Verified 2026-03-31.
  Prompt: `docs/prompts/Phase-7/P7-T03_multi-user-ui.md`

---

## Phase 8: UI/UX Audit Fixes

**Goal:** Fix all accounting bugs, display issues, and UX problems
identified during a systematic audit of every page against dummy data.
Ensure numbers are trustworthy, formatting is consistent, and empty
states are handled gracefully before switching to real data.

**Depends on:** Phase 7 (all features functional)

### Tasks

- `[v]` **P8-T01: Income accounting fix**
  `_INCOME_STREAMS` in `yearly_wrapup.py` now imports from canonical
  `_INCOME_CATEGORIES` (sorted). `get_period_summary()` in `reports.py`
  replaced hardcoded `months=1` cash flow call with direct date-range
  income query respecting owner/account scoping. Yearly review: $195K
  income / 25.6% savings rate (was $3.6K / -3,936%). Verified 2026-04-01.
  Prompt: `docs/prompts/Phase-8/P8-T01_income-accounting-fix.md`

- `[v]` **P8-T02: Monthly review data accuracy**
  `net_worth_delta` now computes dynamic months-back for
  `get_net_worth_history()` (was hardcoded months=3). Spending
  replaced cash flow relay with direct query excluding debt service
  categories ("Mortgages", "Loan Payments") + standard exclusions.
  Dec 2025: spending $6,341 (was $33K), NW delta -$38,965 / -8.7%
  (was None). Verified 2026-04-01.
  Prompt: `docs/prompts/Phase-8/P8-T02_monthly-review-accuracy.md`

- `[v]` **P8-T03: Dashboard empty-state & date fixes**
  End-of-month uses `new Date(y, m+1, 0)` (no more Apr 31).
  Empty-month KPI shows "--" / "No data yet" instead of $0.
  `exclude_transfers` param added to transactions API + DAL; Dashboard
  passes `exclude_transfers=true` for recent transactions. Spending
  comparison `reference_date` uses today, not hardcoded day 10.
  Frontend builds clean. Verified 2026-04-01.
  Prompt: `docs/prompts/Phase-8/P8-T03_dashboard-empty-state.md`

- `[v]` **P8-T04: Number formatting & encoding**
  Created shared `formatCurrency()` utility in `frontend/src/lib/formatCurrency.ts`.
  Replaced all inline currency formatting across 11 files (DashboardPage,
  TransactionsPage, InvestmentsPage, MonthlyReviewPage, YearlyWrapUpPage,
  BudgetsPage, AccountsPage, CashFlowPage, ReportsPage, AccountsSummaryCard,
  LifestyleCreepPanel). Fixed en-dash mojibake in TransactionsPage (3 places).
  Frontend builds clean. Verified 2026-04-01.
  Prompt: `docs/prompts/Phase-8/P8-T04_number-formatting.md`

- `[v]` **P8-T05: Header, label & truncation fixes**
  Created shared `formatCompactCurrency()` for KPI abbreviation ($15.2K, $207.4K).
  Added `PAGE_META` route-to-title map in Header.tsx — "Cash Flow", "Monthly Review",
  "Yearly Wrap-Up" display correctly. Created `institutionDisplayName()` utility —
  Settings shows "NFCU" not "Nfcu". Table wrapped with `overflow-x-auto`, Reset
  buttons fully visible. Frontend builds clean. Verified 2026-04-01.
  Prompt: `docs/prompts/Phase-8/P8-T05_header-label-truncation.md`

- `[v]` **P8-T06: Charts & empty states**
  Credit scores now show institution name when duplicates exist (DashboardPage).
  Sankey guards against zero data — no NaN errors, shows "No data for this period"
  empty state. Net worth chart shows "Data through 2025-12" freshness annotation.
  Filter dropdowns labeled "Account" and "Category". Frontend builds clean.
  Verified 2026-04-01.
  Prompt: `docs/prompts/Phase-8/P8-T06_charts-empty-states.md`

- `[v]` **P8-T07: Review & investment polish**
  Holdings use dynamic account name lookup via `useAccounts()`. Sector
  allocation: fixed cache-override logic in `dal/allocation.py` so
  `_KNOWN_SECTORS` always wins over stale "Unknown" — 0% unclassified.
  Added VFIFX (Target Date Fund) mapping. Freshness shows "3 months ago"
  not "2211h ago". Notable transactions: $1,000 threshold, proper exclusions,
  new "Large Transfers" subsection, improved empty state. Performance shows
  "N/A" with "No snapshots" message when no data. Frontend builds clean,
  145 tests pass. Verified 2026-04-02.
  Prompt: `docs/prompts/Phase-8/P8-T07_review-investment-polish.md`

- `[v]` **P8-T08: Logo fallback & minor polish**
  TransactionLogo defaults to letter avatar; known-domain map only fires
  Clearbit for matched merchants. Budget categories have `title` tooltips.
  New `count_transactions()` DAL function returns uncapped total (10,052 not
  1,000). Cash Flow x-axis uses abbreviated 3-letter months with
  `interval="preserveStartEnd"`. Frontend builds clean, 145 tests pass.
  Verified 2026-04-02.
  Prompt: `docs/prompts/Phase-8/P8-T08_logo-fallback-minor-polish.md`

---

## Phase 9: Income Truth Metrics

**Goal:** Surface the dormant `payroll_snapshots` data (populated by the
myPay RAS parser since P2-T04) into two decisions the user couldn't make
before: pre-tax/gross savings rate and effective tax rate. Both metrics
share an aggregation module and slot into existing review/wrap-up
assemblers — no migrations, no new connectors, no schema changes.

**Depends on:** Phase 2 (myPay RAS parser writing to `payroll_snapshots`)
and Phase 8 (data accuracy overhaul, single-source category classifications).

### Tasks

- `[v]` **P9-T01: dal/payroll.py aggregation module**
  New thin DAL module owning all reads of `payroll_snapshots`. Functions:
  `get_payroll_snapshots()`, `get_gross_income_for_month()`,
  `get_gross_income_for_year()`, `get_effective_tax_rate()`. Returns
  `data_quality` field ("complete"/"partial"/"missing"). Owner-scoping
  documented as a known limitation — `payroll_snapshots` has no owner_id
  column and adding one is out of scope. 5 unit tests in
  `tests/test_payroll.py` (empty table, single month, full year, gap,
  partial year). Also added `pre_tax_savings_rate()` helper to
  `dal/category_classifications.py`. Verified 2026-04-06.

- `[v]` **P9-T02: Pre-tax savings rate (monthly review)**
  `dal/review.py:get_monthly_review()` calls
  `get_gross_income_for_month()` and attaches a `pre_tax` block to the
  response (gross_income, federal_tax, state_tax, deductions, net_pay,
  savings_rate_pct, data_quality). Returns `pre_tax = None` when no
  snapshot exists; frontend silently hides the card. Does not replace
  the existing net-basis savings rate — both are shown. Verified
  2026-04-06.

- `[v]` **P9-T03: Effective tax rate (yearly wrap-up)**
  `dal/yearly_wrapup.py:_build_preliminary()` attaches both `pre_tax`
  and `effective_tax` blocks. `overlay_tax_documents()` extended with a
  1099-R cross-validation hook: when DFAS 1099-R data is present, the
  effective_tax block gets a `validation` field comparing federal
  withholding (`payroll_snapshots` sum vs `dfas_1099r` total) with $1
  tolerance, `matches` boolean, and signed `delta`. Verified 2026-04-06.

- `[v]` **P9-T04: Backend route + frontend wiring**
  New `backend/routers/payroll.py` with two GETs:
  `/api/payroll/yearly?year=YYYY` and `/api/payroll/monthly?month=YYYY-MM`.
  Both accept `owner_id` (documented no-op pending the schema column).
  Registered in `backend/api_server.py`. Frontend:
  `MonthlyReviewPage.tsx` adds a "Pre-Tax (Gross) Snapshot" card (5-column
  grid: gross, federal, state, net pay, pre-tax savings rate with
  comparison line to net-basis SR). `YearlyWrapUpPage.tsx` adds an
  "Effective Tax Rate" section with three render branches (missing →
  empty state with link to `/documents`, partial → chip indicator,
  complete → 4-column grid with optional amber warning row when 1099-R
  validation `matches=false`). Dummy seeder writes 36 months of synthetic
  payroll snapshots so the UI paths are exercised by default. Frontend
  builds clean. Verified 2026-04-06.

- `[v]` **P9-T05: Doc drift cleanups (folded in)**
  `docs/ARCHITECTURE.md` schema version bumped from V12 (22 tables) to
  V20 (32 tables). `docs/prompts/Phase-8/Data-Accuracy-Overhaul.md` Phase
  6 status flipped from "⬜ Not started" to ✅ with verification commit
  reference. Verified 2026-04-06.

---

## Phase 10: Data Trust Overhaul

**Goal:** Restore numerical trust on the Cash Flow page (top-graph totals
must equal drill-down totals for the same date range), then make the
dummy dataset a *rolling generative fixture* so the dev UI always feels
current.

**Why:** Two parallel investigations confirmed the Cash Flow mismatch was
an accounting-logic bug, not a data bug — the top-graph SQL and drill-down
SQL inside `dal/cash_flow.py` had drifted to two different patterns
(whitelist vs. blacklist, with vs. without sign check). Wiping the database
would not fix it. Separately, the frozen JSON fixtures under `dummy_data/`
never rolled forward, so the dev UI looked progressively staler.

**Depends on:** Phase 8 (single-source category classifications) and
Phase 9 (payroll/income truth metrics — included in the rolling generator).

### Tasks

- `[v]` **P10-T01: Cash flow accounting fixes**
  Rewrote all 5 aggregates in `dal/cash_flow.py` (monthly, quarterly,
  yearly, monthly-rolling, quarterly-rolling) to use the canonical
  blacklist + sign-check pattern matching `get_period_detail()`. Fixed
  `get_yearly_cash_flow()` signature (was missing `owner_id`). Added
  owner scoping to `get_available_years()`. Removed `"Deposits"` from
  `INCOME_EXCL_FROM_INC` (it's an income catch-all, not a refund category).
  Fixed `dal/budgets.py` legacy `direction + amount` SUM. Fixed
  `dal/goals.py` mixed convention (income via signed_amount, spending via
  direction). Verified 2026-04-06.

- `[v]` **P10-T02: Sign/direction invariant choke point**
  Added `_assert_sign_direction_invariant()` to
  `dal/transactions.upsert_transactions()`. Both the dummy seeder and
  live institution connectors flow through this function, so any drift
  fails fast with a `ValueError` naming the offending account, posting
  date, and description. 5 unit tests in
  `tests/test_transaction_invariants.py`. Verified 2026-04-06.

- `[v]` **P10-T03: Rolling generative seeder**
  New `scripts/dummy_data/__init__.py` and
  `scripts/dummy_data/generator.py` with pure-function generators for
  transactions, balance snapshots, budgets, credit scores, investment
  holdings, portfolio snapshots, and payroll snapshots. Rewired
  `scripts/seed_dummy_data.py` to call the generators. Generated
  transactions still feed through `dal.transactions.upsert_transactions()`
  and the post-commit pipeline, so live and dummy data share the same
  enrichment path. Added `--end-date YYYY-MM-DD` and `--years N` CLI
  flags. Determinism: RNG seeded from end-date so the same flags produce
  the same byte-for-byte dataset. Round dollars only (e.g.
  groceries ∈ {50, 75, 100, 125, 150}) so totals are hand-auditable.
  ~3% of grocery/dining purchases emit a paired refund a few days later,
  exercising the sign-handling regression guard. Every cross-account
  transfer emits both legs within 1–3 days, exercising
  `reconcile_transfers()`. Deleted (via `git rm`) the stale time-series
  JSON fixtures: `transactions.json`, `transactions_dense.json`,
  `balance_snapshots.json`, `budgets.json`, `credit_scores.json`,
  `Investment_holdings.json`, `portfolio_snapshots.json`,
  `vehicle_valuations.json`. Structural fixtures (owners, institutions,
  recurring patterns, savings goals, real estate, vehicles, loans) kept
  as static JSON. Verified 2026-04-06.

- `[v]` **P10-T04: Invariants test suite**
  `tests/test_cashflow_invariants.py` (12 tests): hand-built ~30-txn
  fixture with paychecks, rent, refund pairs, deposits, transfers, and
  multi-owner data. Tests 1–5 assert top-graph totals exactly equal
  drill-down totals at every granularity (monthly, quarterly, yearly).
  Test 6 (refund regression for the original cash-flow bug). Test 7
  (Deposits-as-income regression). Test 8 (owner scoping isolation).
  Tests 9–10 (budgets.py and goals.py agree with cash_flow.py for
  identical filters). Tests 11–12 (yearly owner filter no-crash and
  available-years owner scoping).
  `tests/test_golden_seed.py` (11 tests): pinned `end_date=2026-01-15`
  with deterministic fingerprint check (`37581d9944c4`), expected txn
  count (1577), per-year per-category totals, closure property between
  balance snapshots and signed_amount sums. This is the hand-auditable
  regression wall. Verified 2026-04-06.

- `[v]` **P10-T05: Docs, skills, prompt record**
  Added `docs/ARCHITECTURE.md` §4.6 Sign Convention with the canonical
  SQL pattern. Added a Dummy Data Generation subsection to the Scripts
  module map. Added a `CLAUDE.md` guardrail line forbidding the legacy
  `direction + amount` pattern. Created `docs/prompts/Phase-10/Data-Trust-Overhaul.md`
  with full diagnosis, decisions, and verification record. Updated
  `.claude/skills/dev-server/SKILL.md` Step 2 to document the rolling
  generator and `--end-date` / `--years` flags so the next session
  doesn't end up here again. Verified 2026-04-06.

---

## Deferred / Backlog

Items identified during Phase 10 that are explicitly out of scope for
this overhaul but tracked here so they don't get lost.

- `[ ]` **DAL write wrappers for non-transactional tables.**
  `balance_snapshots`, `investment_holdings`, `portfolio_snapshots`,
  `credit_scores`, `loan_details`, `real_estate`, `vehicle_valuations`
  are still written via direct INSERTs from the seeder. Building DAL
  wrappers would close the last parity gap between seeder and live
  connectors. Touch when the next non-transactional connector lands.

- `[ ]` **Reconciliation hardening.**
  `dal/reconciliation.py` currently matches integer-cent absolute amounts
  in opposite directions within a 3-day window. Defer FX-aware matching,
  multi-day clearing windows > 3 days, and partial/fee-adjusted matches
  until a real-world miss surfaces.

- `[ ]` **Extractor changes touching the sign/direction convention.**
  Phase 10 fixed the analytical layer; the connectors already feed
  through `upsert_transactions()` so they're protected by the new
  invariant assertion. Defer any extractor refactor until they're being
  touched for other reasons.

- `[ ]` **Frontend refactors beyond verification.**
  No component edits in Phase 10. If a Cash Flow drill-down rendering
  improvement is needed beyond the current behavior, scope it as a
  separate frontend task.

- `[ ]` **Destructive data wipe tooling.**
  A dedicated `scripts/wipe_data.py` with explicit confirmation prompt
  for the day a real reset is needed. The Phase 10 seeder re-uses the
  existing DELETE-then-INSERT pattern, so this is only worth building
  when the user actually wants a one-command nuke.

- `[v]` **Re-anchor time-of-test fixtures in `tests/test_t02t03t04.py`
  and `tests/test_t05.py`.** Done 2026-04-06. The 5 originally-failing
  tests (2 KeyError in `test_t05.py`, 3 phantom-carry-forward velocity
  tests in `test_t02t03t04.py`) plus 12 rot-prone neighbors in the same
  files were all relativized to `date.today()` via three small inline
  helpers (`_months_back()`, `_month_str()`, `_date_str()`, plus
  `_last_day_str()` for end-of-month). No production code touched. No
  new dependencies. The full 150-test backend suite is now green
  (previously 143 passing / 7 failing — the 2 unrelated `test_failure_modes`
  Page-import errors also resolved themselves separately). Phase 10
  invariant wall (28 tests) still green.

### Future / Unphased

- `[ ]` Rewards points tracking (NFCU, Chase)
- `[ ]` NFCU savings APY tracking
- `[ ]` Mortgage extra payment simulator
- `[ ]` TSP switch/stay analysis
- `[ ]` myPay browser connector (if feasible after RAS parser)

---

## Dependency Graph

```
Phase 0 (Foundation)
  |
  +---> Phase 1 (Derived Metrics)
  |       |
  |       +---> Phase 3 (Forecasting)
  |       |
  |       +---> Phase 5 (Frontend Live) ---> Phase 6 (Reviews)
  |                                     |
  +---> Phase 2 (TSP + Doc Drop)        +---> Phase 7 (Settings/Multi-user)
  |                                               |
  +---> Phase 4 (Connector Enhancements)          +---> Phase 8 (UI/UX Audit)
                                                            |
                                                            +---> Phase 9 (Income Truth Metrics)
                                                                     |
                                                                     +---> Phase 10 (Data Trust Overhaul)
```

Phase 0 is the critical path. Phase 8 depends on all features being
functional (Phases 0-7). Within Phase 8, T01-T02 (accounting bugs)
should be done before T03-T08 (display/UX fixes). Phase 9 depends on
Phase 2 (myPay RAS parser) and Phase 8 (single-source classifications).
Phase 10 depends on Phase 8 (single-source category classifications) and
Phase 9 (payroll snapshot generators reused inside the rolling seeder).
