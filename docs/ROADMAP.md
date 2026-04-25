# Sentry Finance --- Development Roadmap

> **Status tracking document.** Read alongside `ARCHITECTURE.md`; load
> the matching `docs/prompts/<Phase-N>/` folder only when a task
> summary below isn't enough.
>
> Last updated: 2026-04-24 (P16-T01 Notification feed foundation —
> `notifications` table v38, `dal/notifications.py`, `dal/documents.py`,
> `backend/routers/notifications.py`, 4 producers wired (budget alerts,
> bills, doc-drop nudges, refresh failures), `NotificationPopover.tsx`
> replaces dead Header bell stub. 32 new tests, 423 total. Prompt file:
> `docs/prompts/Phase-16/P16-T01_notification-feed-foundation.md`.
> Previous session (2026-04-24): Phase 21 design-system consolidation.

## Status Key

- `[ ]` --- Planned (not started)
- `[->]` --- In progress
- `[v]` --- Complete (verified)
- `[!]` --- Needs revision

## Session Handoff

See `CLAUDE.md > Read Order`. This file is step 3: scan the Phase
Overview, pick the next `[ ]`/`[!]` task, then open the matching
`docs/prompts/` entry when one exists. **While Priority 0 is `[ ]`,
it is the only task eligible to start.**

## Phase Overview

| Phase | Title | Status | Prompt folder |
|---|---|---|---|
| **0** | Foundation & Data Quality | `[v]` Complete | `docs/prompts/Phase-0/` |
| **1** | Core Derived Metrics | `[v]` Complete | `docs/prompts/Phase-1/` |
| **2** | TSP Connector & Document Drop | `[v]` Complete | `docs/prompts/Phase-2/` |
| **3** | Forecasting & Decision Support | `[v]` Complete | `docs/prompts/Phase-3/` |
| **4** | Connector Enhancements | `[v]` Complete | `docs/prompts/Phase-4/` |
| **5** | Frontend Live Data Integration | `[v]` Complete | `docs/prompts/Phase-5/` |
| **6** | Reviews & Lifestyle Analysis | `[v]` Complete | `docs/prompts/Phase-6/` |
| **7** | Settings & Multi-User Prep | `[v]` Complete | `docs/prompts/Phase-7/` |
| **8** | UI/UX Audit Fixes | `[v]` Complete | `docs/prompts/Phase-8/` |
| **9** | Income Truth Metrics | `[v]` Complete | (inline) |
| **10** | Data Trust Overhaul | `[v]` Complete | `docs/prompts/Phase-10/` |
| **11** | End-to-End Numerical Audit | `[v]` Complete | (inline) |
| **12** | Synthetic Attribution + Owner Edit | `[v]` Complete | (inline + `empty_state_audit.md`) |
| **13** | Investments Rebuild | `[v]` Complete | `docs/prompts/Phase-13/` |
| **14** | Dollar Accountability Overhaul | `[~]` A/B/C/D (all core) complete; E deferred (rental trigger) | `docs/prompts/Phase-14/` |
| **15** | Decision Support Features | `[~]` T03 + T03b + T04 (A+B full-stretch) + T05 + T06 complete; T01/T02 deferred; T07/T08/T09 planned | `docs/prompts/Phase-15/` |
| **16** | Notifications & Active Surveillance | `[~]` T01 complete; T02/T03 planned | `docs/prompts/Phase-16/` |
| **17** | Real-Data Transition Prep | `[~]` T03 complete; T01/T02 planned | `docs/prompts/Phase-17/` |
| **18** | Investments --- Tax Lots | `[ ]` Blocked on broker statements | (to be authored) |
| **19** | Multi-User Infrastructure Polish | `[ ]` Planned (post hard-line) | (to be authored) |
| **20** | Partner MFA Pipeline | `[ ]` Planned (post hard-line) | `docs/PARTNER_MFA_DESIGN.md` |
| **21** | Design System Consolidation | `[v]` T01-T05 + T04-continuation (A–R) complete 2026-04-24; Tremor dependency removed | `docs/prompts/Phase-21/` |

## Forward-Looking Dependency Graph

```
  ========== PRIORITY 0: PII SECURITY GATE (P0-SEC) ==========
       Blocks EVERY numbered-phase task below. Repo is the
       gate for all identifier surfaces (DAL, extractors,
       migrations, dummy-data, scripts) plus a git-history
       remediation decision.
  ============================================================
                                |
                                v
            [Single-User Trust Bar --- all required]

    Phase 14          Phase 15          Phase 16
    Dollar            Decision support  Notification feed
    Accountability     (mortgage sim,    (header bell
    (gross paycheck    TSP switch,       producer + logic)
     + 4 buckets +     rewards, APY)
     scorecard)
                          |    |    |
                          v    v    v
                 Phase 17: Real-Data Transition Prep
                 (wipe tooling + myPay connector
                  + DAL write wrappers)
                                |
                                v
                 Phase 18: Investments --- Tax Lots
                 (blocked: needs real broker statements)

  ============== HARD LINE --- Trust Bar ==============
       App must be production-trustworthy for the
       user's own data/decisions before any partner
       integration work begins.
  =====================================================

                                |
                                v
                 Phase 19: Multi-User Infra Polish
                 (owner SoT, ViewSelector slots,
                  delete/archive, cosmetic fields)
                                |
                                v
                 Phase 20: Partner MFA Pipeline
                 (Tasker -> Tailscale MFA forward,
                  per-owner credential namespaces)
```

---

## Priority 0: PII Security Gate

- `[v]` **P0-SEC: Account identifier refactor + full PII audit.**
  Verified 2026-04-19. Both tracks landed in session 2026-04-19.

  **Track A landed (commit `ff58bd2`):** source-code scrub. All real
  last-4 literals removed from tracked Python, routed through
  `dal/accounts_config.py` which reads gitignored `accounts.yaml`.
  Location PII (user city, state, and state-specific merchant /
  utility / university names) purged from tracked files and moved to
  gitignored `config/categories.user.yaml` overlay (new loader in
  `dal/categorization.py`). `scripts/pii_scan.py` +
  `.git/hooks/pre-commit` guardrail installed.

  **Track B landed (commit `f0998c1`):** DB identifier layer.
  `accounts.yaml` gained an opaque `id:` field per account, generated
  by `scripts/init_accounts_yaml.py`. `get_account_id()` returns that
  field directly — no more `f"{institution}_{last4}"` construction
  anywhere in the tracked tree. Migration v31 is a data-only rewrite
  (`PRAGMA foreign_keys=OFF`, UPDATE across 12 FK columns in 11
  tables, rewrite JSON-embedded ids in `document_drops.summary_json`,
  then UPDATE `accounts.id` last, `PRAGMA foreign_key_check` gate
  before commit). Dummy-data seeder rewritten to use digit-free
  semantic slugs (`summit_chk`, `coastal_cc`, `fidelity_brokerage`,
  `tsp_synthetic`, …); golden-seed fingerprint re-baselined
  `a4ad2cd6f00f` → `c2b706b7881f` with year-totals unchanged.
  Production sites that still hard-coded synthetic-account ids
  (`extractors/tsp_connector.py` 7×, `dal/parsers/tsp_statement.py`
  4×, `dal/derived.py` 3× `affirm_HYSA`, etc.) now all route through
  the `accounts_config` choke point.

  **Git history scrub** (the final Track B step) runs via
  `git filter-repo --replace-text` and `git push --force` as a one-
  off destructive operation — see
  `docs/prompts/P0-SEC_pii-security-gate.md` Outcomes for the
  pre-flight checklist, blast-radius note, and post-scrub
  verification commands.

  **Verification closed:**
  - `python scripts/pii_scan.py --all-tracked` → `clean`.
  - `pytest tests/ -x --tb=short` → 299 passed.
  - `cd frontend && npm run build` → green.
  - v31 applies cleanly on fresh empty DBs (no-ops) and verified on
    a seeded DB (FK rewrites across 12 columns, no orphans).
  - Pre-commit hook blocks regressions; scanner loads 8 real last-4
    values from accounts.yaml (synthetic skipped).

  Prompt file: [`docs/prompts/P0-SEC_pii-security-gate.md`](prompts/P0-SEC_pii-security-gate.md)
  — full Outcomes (both tracks) recorded there.

---

## Completed Work (Phases 0--13)

Each entry: tight summary, verification date, and prompt path (when
one exists). Full implementation detail lives in the prompt files.

### Phase 0: Foundation & Data Quality
- `[v]` **P0-T01: Income stream & categorization rules** --- Added Military Pension, VA Benefits, VA Education Benefits, Officiating Income to `categories.yaml` + `_INCOME_CATEGORIES`. Verified 2026-03-29 · `docs/prompts/P0-T01_military-categorization.md`
- `[v]` **P0-T02: Teach-the-system flow (backend)** --- Built `dal/user_rules.py` + v13 migration + `routers/user_rules.py` as Layer 1.5 of the categorization engine. Verified 2026-03-29 · `docs/prompts/P0-T02_teach-the-system-backend.md`
- `[v]` **P0-T03: Transfer reconciliation hardening** --- +11 keywords, same-institution 1-day-window second pass, 7 integration tests. Verified 2026-03-29 · `docs/prompts/P0-T03_transfer-hardening.md`
- `[v]` **P0-T04: Data freshness indicators (backend)** --- `dal/freshness.py` (3 functions + tier classification) + 3-endpoint router. Verified 2026-03-29 · `docs/prompts/P0-T04_data-freshness-api.md`
- `[v]` **P0-T05: Acorns all-or-nothing scrape guard** --- `_scrape_positions()` collects funds in memory, returns `[]` on any failure (snapshot still written). Verified 2026-03-29 · `docs/prompts/P0-T05_acorns-scrape-guard.md`

### Phase 1: Core Derived Metrics
- `[v]` **P1-T01: Emergency fund metric** --- `compute_emergency_fund_months()` in `dal/derived.py` uses checking/savings balances + 6-month spending average. Endpoint `/api/metrics/emergency-fund`. Verified 2026-03-29 · `docs/prompts/P1-T01_emergency-fund-metric.md`
- `[v]` **P1-T02: Debt-to-income ratio (time series)** --- `compute_dti_ratio()` category-only (no account JOIN, prevents double-counting); bands healthy <28% / critical ≥43%. Verified 2026-03-29 · `docs/prompts/P1-T02_debt-to-income.md`
- `[v]` **P1-T03: Interest cost tracking** --- `compute_interest_cost()` prefers `loan_details` YTD, falls back to Interest-category transactions; tracks paid/earned/net. Verified 2026-03-29 · `docs/prompts/P1-T03_interest-cost-tracking.md`
- `[v]` **P1-T04: Net worth velocity** --- `compute_net_worth_velocity()` MoM/3m/12m with accelerating/steady/decelerating/declining classification. Verified 2026-03-29 · `docs/prompts/P1-T04_net-worth-velocity.md`
- `[v]` **P1-T05: Fix real estate static history** --- Per-month time-aware RE valuation lookup in `get_net_worth_history()`; point-in-time path unchanged. 7/7 tests. Verified 2026-03-29 · `docs/prompts/P1-T05_real-estate-history-fix.md`
- `[v]` **P1-T06: Derived metrics SQL fix** --- Rewrote both broken queries in `recompute_account_metrics()` to parameterized IN/NOT IN + signed_amount sign guards. Verified 2026-03-29 · `docs/prompts/P1-T06_derived-sql-fix.md`

### Phase 2: TSP Connector & Document Drop
- `[v]` **P2-T01: TSP connector with MFA bridge** --- Playwright connector for TSP.gov (Okta selectors); pauses at MFA, broadcasts `mfa_required` SSE, resumes via `backend/mfa_bridge.py`. `MFAModal.tsx` overlay. Verified 2026-03-29 · `docs/prompts/P2-T01_tsp-connector.md`
- `[v]` **P2-T02: Document drop backend** --- `dal/parsers/` package + `document_drops` table (v14) + upload/commit/history/pending-nudges endpoints. 23/23 tests. Verified 2026-03-29 · `docs/prompts/P2-T02_document-drop-backend.md`
- `[v]` **P2-T03: Document drop frontend** --- `DocumentDrop.tsx` 6-state machine, `DocumentsPage.tsx`, `DocumentNudge.tsx` with dismiss-until-midnight. Verified 2026-03-29 · `docs/prompts/P2-T03_document-drop-frontend.md`
- `[v]` **P2-T04: myPay RAS parser** --- `dal/parsers/mypay_ras.py` extracts gross/federal/state/SBP/health/dental/vision/net. v15 creates `payroll_snapshots` with `UNIQUE(pay_period, source)`. 15/15 tests. Verified 2026-03-31 · `docs/prompts/P2-T04_mypay-parser.md`

### Phase 3: Forecasting & Decision Support
- `[v]` **P3-T01: Seasonal income modeling** --- `build_seasonal_income_model()` decomposes into 4 streams (pension/disability/education/officiating) with 3×-median outlier exclusion. Verified 2026-03-31 · `docs/prompts/P3-T01_seasonal-income.md`
- `[v]` **P3-T02: Recurring-to-loan linking** --- `link_recurring_to_loans()` with 3 matching strategies (same-institution, cross-institution, balance-relative). v16 adds `linked_account_id`. Verified 2026-03-31 · `docs/prompts/P3-T02_recurring-loan-link.md`
- `[v]` **P3-T03: Scenario projection engine** --- `project_scenario()` accepts 5 event types (income/expense/one-time/loan-payoff/investment-return); projects up to 120 months. Verified 2026-03-31 · `docs/prompts/P3-T03_scenario-engine.md`
- `[v]` **P3-T04: Debt payoff vs. invest comparison** --- `compare_debt_payoff_vs_invest()` break-even analysis + avalanche/snowball via `get_payoff_plan()`. Verified 2026-03-31 · `docs/prompts/P3-T04_debt-vs-invest.md`

### Phase 4: Connector Enhancements
- `[v]` **P4-T01: NFCU credit card detail scraping** --- APR, credit limit, minimum payment, due date extracted + stored in `loan_details`. Verified 2026-03-31 · `docs/prompts/P4-T01_nfcu-cc-details.md`
- `[v]` **P4-T02: Credit score scraping** --- NFCU (FICO) + Chase (VantageScore 3.0); v17 creates `credit_scores`; endpoint `/api/metrics/credit-scores`. Verified 2026-03-31 · `docs/prompts/P4-T02_credit-score-scraping.md`
- `[v]` **P4-T03: Affirm HYSA APY scraping** --- Affirm connector extracts APY via regex, persists alongside balance. Verified 2026-03-31 · `docs/prompts/P4-T03_affirm-apy.md`
- `[v]` **P4-T04: Fidelity cost basis (Positions CSV)** --- `_download_positions_csv()` added as Phase 1.5 download; cost basis stored in `investment_holdings` + `loan_details`. Verified 2026-03-31 · `docs/prompts/P4-T04_fidelity-cost-basis.md`
- `[v]` **P4-T05: Eventlink import** --- `dal/parsers/eventlink.py` XLSX/CSV parser with filename + PK ZIP auto-detect + 7-day dedup. Verified 2026-03-31 · `docs/prompts/P4-T05_eventlink-import.md`
- `[v]` **P4-T06: Vehicle equity tracking** --- `dal/vehicles.py` + v18 (`vehicle_assets` + `vehicle_valuations`); time-aware lookup integrated into net worth history. Verified 2026-03-31 · `docs/prompts/P4-T06_vehicle-equity.md`
- `[v]` **P4-T07: Tax document parsers (1099/1098)** --- Five parsers: DFAS 1099-R, Fidelity 1099, Acorns 1099, Affirm 1099-INT, NFCU 1098. Endpoint `/api/documents/tax-summary/{year}`. Verified 2026-03-31 · `docs/prompts/P4-T07_tax-doc-parsers.md`

### Phase 5: Frontend Live Data Integration
- `[v]` **P5-T01: Dashboard live data + new KPIs** --- 11 endpoints wired; KPI cards for NW (velocity arrow), net flow / SR, emergency runway, dual credit scores, freshness indicator. Verified 2026-03-31 · `docs/prompts/P5-T01_dashboard-live.md`
- `[v]` **P5-T02: Transactions page live data + teach-the-system** --- `/api/transactions` with pagination/filters/date ranges; teach flow (category/merchant/match/recurring). Verified 2026-03-31 · `docs/prompts/P5-T02_transactions-live.md`
- `[v]` **P5-T03: Cash flow page live data** --- Monthly-rolling / quarterly-rolling / yearly endpoints + account filter + bar-click drill-down. Verified 2026-03-31 · `docs/prompts/P5-T03_cashflow-live.md`
- `[v]` **P5-T04: Reports page live data** --- `/api/reports/flow` + `/api/transactions` wired; custom-SVG Sankey with clickable nodes + income/spending split. Verified 2026-03-31 · `docs/prompts/P5-T04_reports-live.md`
- `[v]` **P5-T05: Accounts page live data + freshness badges** --- Accounts / freshness / NW history / pending-nudges wired; traffic-light badges per institution + doc-drop nudges. Verified 2026-03-31 · `docs/prompts/P5-T05_accounts-live.md`
- `[v]` **P5-T06: Budgets page live data** --- `/api/budgets` + month selector + create/update/delete + budget-vs-actual pie. Verified 2026-03-31 · `docs/prompts/P5-T06_budgets-live.md`
- `[v]` **P5-T07: Investments page live data** --- Holdings / allocation / performance endpoints + account filter + sector pie + cumulative return cards (Fidelity/Acorns/TSP). Verified 2026-03-31 · `docs/prompts/P5-T07_investments-live.md`

### Phase 6: Reviews & Lifestyle Analysis
- `[v]` **P6-T01: Monthly review page** --- `dal/review.py` assembler + `MonthlyReviewPage.tsx`: income/spending/SR vs prior, NW delta, budget highlights, top-5 notables, uncategorized count. Verified 2026-03-31 · `docs/prompts/Phase-6/P6-T01_monthly-review.md`
- `[v]` **P6-T02: Yearly wrap-up (preliminary)** --- `dal/yearly_wrapup.py` + `YearlyWrapUpPage.tsx`; 10 sections, status "preliminary". Endpoint `/api/review/yearly`. Verified 2026-03-31 · `docs/prompts/Phase-6/P6-T02_yearly-wrapup-preliminary.md`
- `[v]` **P6-T03: Yearly wrap-up revised (tax integration)** --- Added `get_tax_doc_checklist()` + `overlay_tax_documents()`; status progresses preliminary → revised → final. Verified 2026-03-31 · `docs/prompts/Phase-6/P6-T03_yearly-wrapup-revised.md`
- `[v]` **P6-T04: Lifestyle creep detection** --- `dal/lifestyle.py` per-category spending vs income growth; flags categories growing >5 pp faster. `LifestyleCreepPanel.tsx`. Verified 2026-03-31 · `docs/prompts/Phase-6/P6-T04_lifestyle-creep.md`
- `[v]` **P6-T05: Contributions vs. performance decomposition** --- `dal/performance.py::decompose_contributions_vs_performance()` using Simple Dietz; per-account stacked bar on Investments. Verified 2026-03-31 · `docs/prompts/Phase-6/P6-T05_contributions-vs-performance.md`

### Phase 7: Settings & Multi-User Prep
- `[v]` **P7-T01: Settings page** --- v20 `app_settings` table + `dal/settings.py` + router (GET/PATCH, VALID_KEYS, multi-user convenience endpoint) + `SettingsPage.tsx`. Verified 2026-03-31 · `docs/prompts/Phase-7/P7-T01_settings-page.md`
- `[v]` **P7-T02: Owner-scoped DAL audit** --- `owner_id` threaded through ~30 DAL functions via `resolve_account_ids_for_view()`; 86 router sites pass it through. 140/140 tests. Verified 2026-03-31 · `docs/prompts/Phase-7/P7-T02_owner-scoped-audit.md`
- `[v]` **P7-T03: Multi-user UI (selector + onboarding)** --- `ViewContext` (mine/theirs/household), `ViewSelector.tsx`, `useOwnerApi` hook. 9 data pages owner-scoped; 3-step `PartnerOnboarding.tsx`. Verified 2026-03-31 · `docs/prompts/Phase-7/P7-T03_multi-user-ui.md`

### Phase 8: UI/UX Audit Fixes
- `[v]` **P8-T01: Income accounting fix** --- `_INCOME_STREAMS` now imports canonical `_INCOME_CATEGORIES`; `get_period_summary()` uses direct date-range income query. Yearly review: $195K / 25.6% SR (was $3.6K / -3,936%). Verified 2026-04-01 · `docs/prompts/Phase-8/P8-T01_income-accounting-fix.md`
- `[v]` **P8-T02: Monthly review data accuracy** --- Dynamic months-back for `net_worth_delta`; spending excludes debt service + standard exclusions. Dec 2025: $6,341 (was $33K). Verified 2026-04-01 · `docs/prompts/Phase-8/P8-T02_monthly-review-accuracy.md`
- `[v]` **P8-T03: Dashboard empty-state & date fixes** --- EOM `new Date(y, m+1, 0)`; "--" / "No data yet" empty state; `exclude_transfers` threaded through transactions API. Verified 2026-04-01 · `docs/prompts/Phase-8/P8-T03_dashboard-empty-state.md`
- `[v]` **P8-T04: Number formatting & encoding** --- Shared `formatCurrency()` utility across 11 files; en-dash mojibake fixed. Verified 2026-04-01 · `docs/prompts/Phase-8/P8-T04_number-formatting.md`
- `[v]` **P8-T05: Header, label & truncation fixes** --- `formatCompactCurrency()`, `PAGE_META` route titles, `institutionDisplayName()` ("NFCU" not "Nfcu"), overflow-x-auto. Verified 2026-04-01 · `docs/prompts/Phase-8/P8-T05_header-label-truncation.md`
- `[v]` **P8-T06: Charts & empty states** --- Duplicate-institution credit scores; Sankey zero-guard; NW freshness annotation; labeled filter dropdowns. Verified 2026-04-01 · `docs/prompts/Phase-8/P8-T06_charts-empty-states.md`
- `[v]` **P8-T07: Review & investment polish** --- Dynamic account names; sector-allocation cache fix (0% unclassified); VFIFX mapping; human freshness; notable threshold $1k + Large Transfers; "N/A" performance empty state. 145 tests. Verified 2026-04-02 · `docs/prompts/Phase-8/P8-T07_review-investment-polish.md`
- `[v]` **P8-T08: Logo fallback & minor polish** --- TransactionLogo letter-avatar default (Clearbit only for known domains); budget tooltips; uncapped `count_transactions()`; abbreviated Cash Flow x-axis. 145 tests. Verified 2026-04-02 · `docs/prompts/Phase-8/P8-T08_logo-fallback-minor-polish.md`

### Phase 9: Income Truth Metrics
- `[v]` **P9-T01: `dal/payroll.py` aggregation module** --- Thin DAL with `get_payroll_snapshots()`, `get_gross_income_for_month/year()`, `get_effective_tax_rate()`; returns `data_quality` field. 5 unit tests. Verified 2026-04-06.
- `[v]` **P9-T02: Pre-tax savings rate (monthly review)** --- `get_monthly_review()` attaches `pre_tax` block (gross/fed/state/deductions/net/SR/quality); silently hides when no snapshot. Coexists with net-basis SR. Verified 2026-04-06.
- `[v]` **P9-T03: Effective tax rate (yearly wrap-up)** --- `_build_preliminary()` attaches `pre_tax` + `effective_tax` blocks; `overlay_tax_documents()` adds 1099-R cross-validation hook ($1 tolerance). Verified 2026-04-06.
- `[v]` **P9-T04: Backend route + frontend wiring** --- `backend/routers/payroll.py` (yearly + monthly). MonthlyReview "Pre-Tax (Gross) Snapshot" card; YearlyWrapUp "Effective Tax Rate" section. Seeder writes 36 months of synthetic snapshots. Verified 2026-04-06.
- `[v]` **P9-T05: Doc drift cleanups** --- `ARCHITECTURE.md` bumped V12 → V20 (22 → 32 tables); Data-Accuracy-Overhaul Phase 6 flipped to complete. Verified 2026-04-06.

### Phase 10: Data Trust Overhaul
- `[v]` **P10-T01: Cash flow accounting fixes** --- All 5 aggregates in `dal/cash_flow.py` rewritten to canonical blacklist + sign-check pattern; owner scoping on `get_available_years()`; legacy `direction + amount` patterns fixed in `budgets.py` + `goals.py`. Verified 2026-04-06.
- `[v]` **P10-T02: Sign/direction invariant choke point** --- `_assert_sign_direction_invariant()` in `upsert_transactions()` fails fast with named `ValueError`. 5 unit tests. Verified 2026-04-06.
- `[v]` **P10-T03: Rolling generative seeder** --- New `scripts/dummy_data/generator.py` pure-function generators; `--end-date` / `--years` flags; RNG seeded from end-date (deterministic); 3% refund pairs; stale JSON fixtures deleted. Verified 2026-04-06.
- `[v]` **P10-T04: Invariants test suite** --- `tests/test_cashflow_invariants.py` (12 tests: top-graph = drill-down + regressions) + `tests/test_golden_seed.py` (11 tests; pinned `end_date=2026-01-15`, fingerprint `37581d9944c4`, 1577 txns). Verified 2026-04-06.
- `[v]` **P10-T05: Docs, skills, prompt record** --- `ARCHITECTURE.md` §4.6 Sign Convention; `CLAUDE.md` guardrail forbidding legacy pattern; `docs/prompts/Phase-10/Data-Trust-Overhaul.md`; dev-server SKILL updated. Verified 2026-04-06.
- `[v]` **Test fixture time-anchor refresh** --- Relativized 5 originally-failing tests + 12 rot-prone neighbors in `tests/test_t02t03t04.py` and `tests/test_t05.py` to `date.today()` via small inline helpers. 150-test suite green. Verified 2026-04-06.

### Phase 11: End-to-End Numerical Audit
- `[v]` **P11-T01: Seeder integrity foundation (Phase A)** --- Unconditional `balance_snapshots` DELETE; investment seed runs before balance seed so investment balance = `portfolio_snapshots.total + cash`. CC payment block pulls from prior cycle's charges (was overpaying Coastal by ~$10k). Ghost-account deactivation + integrity asserts; golden-seed refreshed (1577 → 1569). Verified 2026-04-08.
- `[v]` **P11-T02: Sign + canonical SQL pattern across DAL (Phase B)** --- Fixed `recompute_net_worth` sign-flip (assets + liabilities); added vehicles + `'mortgage'` to liability types. Synced `INCOME_EXCL_FROM_INC` to real category names (refunds were silently inflating income). Rewrote budgets/reports/yearly_wrapup to canonical pattern; fixed cash_flow `effective_month` filter drift. 150 tests. Verified 2026-04-08.
- `[v]` **P11-T03: Phase-9 income-truth wire-up + ghost-account filter (Phase C)** --- `get_period_detail` computes real `gross_savings_rate` (was hardcoded); `gross_savings_rate_scope: "pension_only"` disclosure. Fixed 3-layered interest-panel bug in yearly wrap-up. Added `owner_id` to review endpoints. Filtered empty-stub accounts. Verified 2026-04-08.
- `[v]` **P11-T04: Time-window normalization (Phase D)** --- `start_date` / `end_date` added to `/api/reports/flow|cash-flow`. Reports YTD = Jan 1 (was trailing 12m, overstated $104k); "Last 30 Days" = 30 calendar days; "All Time" passes `null`. Reports YTD reconciles to Cash Flow Jan–Apr to the cent. Freshness UTC-slip fixed. Verified 2026-04-08.
- `[v]` **P11-T05: Frontend cleanup (Phase E)** --- Removed `target > 0` filter hiding unbudgeted over-spend; Transactions chip uses canonical blacklist (was 3× inflated); `CATEGORY_COLORS` aliased abstract + real names; Dashboard `/mo` normalizes by frequency; Investments uses geometric compounding; dropped fabricated benchmark cards and fake Tax Lots data. Verified 2026-04-08.

### Phase 12: Synthetic Attribution + Owner Edit
- `[v]` **P12-T01: Reattribute synthetic data to one owner** --- Generator stamps `owner_id="quintin"` on every row; seeder writes owner_id for budgets/goals/real-estate/vehicles/payroll. Amy's view is now a true empty state. Verified 2026-04-08.
- `[v]` **P12-T02: Migration v22 --- owner_id on misc tables** --- Nullable `owner_id TEXT REFERENCES owners(id)` added to `payroll_snapshots`, `vehicle_assets`, `real_estate` + backfill + owner-aware indexes. 195 tests. Verified 2026-04-08.
- `[v]` **P12-T03: Read-path owner threading** --- `dal/payroll.py`, `dal/vehicles.py`, and `dal/reports.py` net worth/vehicle joins now honor `owner_id`; cash_flow / yearly_wrapup / review thread through. Verified 2026-04-08.
- `[v]` **P12-T04: myPay parser writes owner_id** --- `dal/parsers/mypay_ras.py:commit()` stamps `owner_id = get_primary_owner()` on every insert. 15/15 tests. Verified 2026-04-08.
- `[v]` **P12-T05: Owner edit scaffolding (rename)** --- `dal/owners.update_owner` (keyword-only kwargs), `PATCH /api/owners/{owner_id}` + `OwnerUpdate`, "Owners" section in Settings, `ViewSelector` pulls names from context + defensive fallback. Surfaced 4 deferred items. 195/195 tests. Verified 2026-04-08.
- `[v]` **P12-T06: Empty-state audit (Amy view)** --- Three Explore subagents audited Amy vs Quintin. Root cause: `if not account_ids:` collapsed `[]` into `None`. 5 leaky endpoints + 2 frontend pages + 12 polish items in `docs/prompts/empty_state_audit.md`. Code fixes out of scope (see P12-T07). Verified 2026-04-08.
- `[v]` **P12-T07: Empty-state audit fix-up** --- 4-commit follow-up to P12-T06. New `dal/owners.build_account_filter` distinguishes `None` (no filter) from `[]` (short-circuit `AND 1=0`). Migrated 26 call sites across 12 DAL modules + 4 leaky investment router sites. Frontend `owner_id` threaded through Budgets/Reports/Transactions. +24 regression tests. Amy view now renders clean empty-state across all 9 pages. Verified 2026-04-08.
- `[v]` **Budgets household-only migration (v23)** --- User clarified per-owner budgets were an architectural mistake. `v23_budgets_household_only.py` dedupes `(category, month)`, nullifies `owner_id`, adds partial unique index `idx_budgets_household_unique ON budgets(category, month) WHERE owner_id IS NULL`. `dal/budgets.py` drops `owner_id` from 6 functions; router drops from 5 endpoints; frontend stops threading ownerParam for budget calls. `tests/test_budgets_household.py` (8 tests). Verified 2026-04-08.

### Phase 13: Investments Rebuild (branch `investments-rebuild`)
- `[v]` **P13-T01: Strip investments to shell** --- Deleted `dal/investments.py`, `dal/allocation.py`, `dal/performance.py`; renamed investments router → debt.py; gutted `InvestmentsPage.tsx` to empty-state shell; re-baselined golden seed (1569 → 1425 txns). Commit `9ef66a3`, net -4217 lines. 210 tests. Verified 2026-04-09 · `docs/prompts/Phase-13/P13-T01_investments-rebuild-strip.md`
- `[v]` **P13-T02: Acorns Synthetic account exists** --- Added `acorns_synthetic_0000` (owner `quintin`, $0 starting). Shrank hard-reset so canonical investment accounts survive re-seed. Rewrote `InvestmentsPage.tsx` as a lightweight account-list filtered to investment/retirement. Verified 2026-04-09 · `docs/prompts/Phase-13/P13-T02_investments-acorns-synthetic.md`
- `[v]` **P13-T03: Acorns data pipeline (end-to-end)** --- Full pipeline from bank debit to investment display. v24 adds `source`, `bank_txn_id`, `investment_link`. Seeder emits bank-side debits + investment-side positions_ledger with real yFinance prices (cached) + weekly portfolio snapshots. New `dal/investments.py`, statement parser, post-commit linkage via `transfer_tag = "invest:{id}"`. Verified 2026-04-09 · `docs/prompts/Phase-13/P13-T03_acorns-data-pipeline.md`
- `[v]` **P13-T04: Trade confirmation pipeline** --- Daily trade confirmation PDFs become the primary data source (exact ticker/price/quantity/principal, same-day). New `dal/parsers/acorns_confirmation.py`; connector downloads unprocessed confirmations before delta-logging fallback. `source = 'confirmation'` in positions_ledger. Verified 2026-04-09 · `docs/prompts/Phase-13/P13-T04_trade-confirmations.md`
- `[v]` **P13-T05: Wire investment data to frontend** --- Re-added `holdings_value` enrichment to `/api/accounts` (Accounts page now shows $18,753 instead of $0). Rewrote `InvestmentsPage.tsx` for portfolio summary card + per-ETF holding cards. Investment-account clicks route to `/investments`. Verified 2026-04-09.
- `[v]` **P13-T06: Fidelity synthetic data pipeline** --- Generator for 8 tickers with monthly $500 deposits, 2–3 BUYs/mo (whole-share pref), quarterly dividends (40% reinvest), 2–3 SELLs/yr (FIFO + realized gain/loss), SPAXX cash tracking. v25 adds cost_basis/realized/settlement/commission/fees to positions_ledger. New `get_holdings/lots/allocation/performance()` + 3 endpoints; 3 frontend tabs wired. 210 tests. Verified 2026-04-09 · `docs/prompts/Phase-13/P13-T06_fidelity-synthetic-data.md`
- `[v]` **P13-T08: Investment tax treatment tracking** --- TSP statement revealed 3 internal tax buckets (Traditional 33% / Roth 60% / Tax-exempt 7%). v29 adds `accounts.tax_status` + `tax_buckets` table + 2 endpoints. Frontend: tax badges per account, TSP bucket panel with stacked bar, ST/LT labels on taxable lots, Tax Diversification card, dual donuts in Allocation X-Ray. 158 tests. Verified 2026-04-09 · `docs/prompts/Phase-13/P13-T08_tax-treatment.md`
- `[v]` **Backend simplification pass** --- Cross-phase `/simplify` cleanup: 6 new helpers (exclusion clauses, batched balance lookup, `derive_signed_amount`, pipeline `_run_step`, `column_exists`, `poll_with_timeout`/`retry_with_backoff`), ~25 exclusion sites migrated, balance N+1 fixed in `result_writer`, 10 owner-scoping call sites migrated to `build_account_filter` (closing the Phase 12 falsy-list risk in `get_transactions`/`count_transactions`), policy YAML caching (`refresh_orchestrator` + `freshness.py`), new `get_institution_status` single-institution DAL overload, SSE unsubscribe cleanup verified, `SELECT *` → projections. 212 tests. Verified 2026-04-16 · `docs/prompts/backend-simplification.md`
- `[v]` **Details-panel simplification pass** --- Post-P15-T10 `/simplify` cleanup shipped as three independent PRs. #17 consolidated the composer + DAL details-panel join: extracted `resolve_latest_identity` (one scan replaces three correlated subqueries duplicated in two files), routed asset-side composers to pass their already-fetched collateral into `get_loan_panel_bundle` (eliminates a redundant `vehicle_assets`/`real_estate` round-trip), derived `apy_latest` from `apy_history[-1]`, collapsed `_account_has_linked_asset` to one `UNION ALL` query, factored `_empty_loan_bundle()`, fixed `VehicleCollateral`/`RealEstateCollateral` TypedDicts to include the `kind` discriminator they actually return, and exported `COLLATERAL_FIELDS` from `dal/balances.py` so the seeder integrity check builds its `IN(...)` clause from the same frozenset. #18 hoisted shared frontend helpers out of the two Details panels: new `lib/sentimentClass.ts` with `sentimentStrokeClass`/`sentimentTextClass` (replacing 3 inline IIFE ladders + 2 ternary copies), generalized `formatMonthYearFull` in `dateUtils.ts` to accept any ISO prefix (drops duplicated local `formatMonthYear` from both panels), simplified the dead `isInvestmentLike` guard inside `useMemo(rows)`, replaced `oldestAsOf`'s sort-then-take-first with a single-pass min, added `INVESTMENT_TYPES` constant, and changed synthesized collateral rows to carry an empty `as_of` so the "Scraped…" footer reflects real scrape time instead of render time. #19 stripped P15-T10 task narrative from 8 files per the project comment policy (module docstrings, migration preambles, seeder comments, interface annotations in both panels) — no code logic changes. 391/391 backend tests pass across all three PRs; frontend build clean; live preview verified Summit Auto Loan collateral block + Primary Residence trend annotation render identically to before. Verified 2026-04-24.

---

## Remaining Work: Single-User Trust Bar

The user's bar for declaring the app "done enough for my own financial
data/decisions" before any partner-integration work. Phases 14–18 must
all land before Phase 19. Within this band: 14/15/16 can be built in
parallel; 17 gates the real-data cutover; 18 is blocked on real broker
statements arriving.

### Phase 14: Dollar Accountability Overhaul

**Goal:** Replace the single-residual "savings" bar in the Sankey with
a complete terminal-fate accounting: every dollar that enters the
household in a period is traced to one of three drawn buckets
(**Spent**, **Kept liquid**, **Kept illiquid**), and market value
changes on already-owned holdings are reconciled against net-worth
history via a top-of-page **accountability scorecard** ("We've
accounted for X% of your net worth change this period").

**Replaces:** the previously `[DEFERRED]` Phase 14 Budget Model
Redesign. Four terminal fate buckets are a more honest frame than
category budgets, so this overhaul supersedes that idea. The baseline
+ specials budget concept can return later as a Phase 15 decision-
support task if real usage still demands it.

**Status:** Planned 2026-04-21. Long-lived feature branch
`feat/phase14-dollar-accountability` with per-phase sub-branches;
merges to `main` only after Phases A–D verify end-to-end on real
data. Phase E lands separately when the landlord transition actually
triggers.

**Phase overview:** `docs/prompts/Phase-14/Dollar-Accountability-Overhaul.md`

- `[v]` **P14-T01: Gross paycheck on the Sankey (Phase A).** Landed
  2026-04-21 on `feat/p14-a-gross-paycheck`. New
  `dal/payroll.get_flow_contribution` rolls `payroll_snapshots` into a
  gross/net/withholdings structure (integer cents, zero-valued fields
  omitted, all buckets `CONSUMED` in Phase A). New
  `dal/payroll.find_matching_deposit_tx_id` dedups via
  `(owner_id, month, source_label substring)`; amount is not part of
  the match key. `dal/reports.get_flow_data` folds the decomposition
  into `/api/reports/flow` as a new `payroll_decomposition` block
  (+ `excluded_transaction_ids` + per-row `matched_txn_id`), excludes
  matched net-deposit txns from income aggregation, and bumps
  `total_income` by the matched gross-vs-net delta. Frontend adds a
  `PayrollDecompositionDebugPanel` below the Sankey card (amber-outlined
  debug view — Sankey SVG unchanged per spec). Static HTML mockup
  at `~/.claude/plans/phase14-phase-a-sankey-mockup.html` approved
  before code merged. 5 new tests in `tests/test_payroll_flow.py`
  (owner scope, zero-omission, match-excludes, no-match-emits-only,
  txn-without-snapshot fall-through); 304/304 suite + frontend build
  green; PII scan clean. Mockup-server config added to
  `.claude/launch.json` as reusable infra for Phase B.
  Prompt: `docs/prompts/Phase-14/P14-T01_gross-paycheck-sankey.md`.
- `[v]` **P14-T02: Four terminal buckets (Phase B).** Three terminal
  buckets (`CONSUMED` / `STORED_LIQUID` / `STORED_ILLIQUID`) ship in
  the `/api/reports/flow` response as a `bucket_totals` block plus
  integer-cents `bucket_totals_cents`, `total_inflow_cents`, and a
  `bucket_invariant_drift_cents` field. `GROWN` reserved in the
  `BucketLabel` enum but not drawn. Migration v32 (`income_sources`
  registry, thin CRUD in `dal/income_sources.py`) and v33
  (`loan_payment_splits` keyed by `transaction_id TEXT`). Classifier
  module `dal/flow_classification.py` with peer-account-type rules +
  brokerage-buy match helper (`share_delta > 0` within 5 days) +
  match-rule JSON blob interpreter. `dal.debt.decompose_payment`
  runs amortization math (statement-parser path reserved for a
  future wiring, method tag already in the CHECK set); a new
  post-commit pipeline step between reconciliation and
  derived-recompute decomposes any un-split mortgage payments.
  `get_flow_data` uses the **residual-liquid** accounting identity —
  STORED_LIQUID = inflow − CONSUMED − STORED_ILLIQUID — so the
  Phase B invariant holds by construction (drift is always 0 on the
  mathematical path, the warning remains for belt-and-suspenders).
  `bypass_flows` are driven by income_sources rows with
  `bypass_cash_routing=1` and an optional `monthly_amount_cents` in
  the match_rule_json blob. Frontend adds a `TerminalBucketsPanel`
  (emerald-outlined, muted-red/blue/green chips) below the Phase A
  debug panel; the existing Sankey SVG renderer stays intact (user's
  "cosmetic/UX changes later" — landed in P14-T02b below).
  Seeder adds Amy monthly W-2 payroll snapshots, a `seed_income_sources`
  step that registers Quintin's employer-match bypass, officiating
  contractor source, and Amy's W-2 source. Static HTML mockup at
  `~/.claude/plans/phase14-phase-b-sankey-mockup.html` approved before
  code merged. 25 new tests across
  `tests/test_flow_classification.py`,
  `tests/test_loan_decomposition.py`, and
  `tests/test_income_sources_registry.py`. 329/329 backend suite +
  frontend build + PII scan all green. Golden-seed fingerprint
  unchanged (Phase B does not touch the transaction RNG stream).
  Prompt: `docs/prompts/Phase-14/P14-T02_four-terminal-buckets.md`.
- `[v]` **P14-T02b: Payroll withholdings visible on the Sankey
  (cosmetic follow-up).** Closes the Phase B gap where the Sankey
  SVG hid withholdings inside the hub. Each kind (Federal Tax,
  State Tax, SBP, Dental/Vision) now paints as a colored stripe
  on the top of the primary paycheck bar plus a direct ribbon
  flying straight into `CONSUMED`, skipping the hub. Hub inflow
  drops from gross to net by construction (`hubInflow =
  totalIncome − totalWithheld`); the `CONSUMED` bucket tooltip
  lists withholdings first, above spending and mortgage
  contributors. Attribution uses a largest-bar heuristic — fine
  for single-earner households; for dual-earner households all
  withholdings visually pin to whichever paycheck is larger.
  Frontend-only change in `frontend/src/pages/ReportsPage.tsx`
  (new `WithholdingAgg` prop through `SankeyChart`). No backend
  or migration work; accounting invariant unchanged. `npm run
  build` green.
  Prompt: `docs/prompts/Phase-14/P14-T02b_sankey-withholdings.md`.
- `[v]` **P14-T03: Dividends and interest as real income (Phase C).**
  Landed 2026-04-22. Migration v34 ships `v_investment_contributions`
  as a view (DDL-only, no data change) that classifies every
  `positions_ledger` row as `user_contribution` /
  `intra_account_credit` / `sale_or_transfer_out` / `unknown`.
  Fidelity dividend generation now emits a cash-side transaction
  (category `Investment Income`) alongside the existing
  `positions_ledger` `DIVIDEND`/`REINVESTMENT` rows — routed through
  `upsert_transactions` so the sign/direction invariant fires. The
  categorizer YAML was reordered: ticker-prefixed `"<TICKER> DIVIDEND"`
  descriptions now route to `Investment Income`; credit-union share
  yields (`SHARE DIVIDEND`, `SHARES DIVIDEND`) still route to
  `Interest`. Two new seeded `income_sources` rows (HYSA interest,
  Fidelity dividends) with `tax_treatment='interest_dividend'` and
  `bypass_cash_routing=0`. `/api/reports/flow` gains a new
  `reinvestment_flows` block (same-day same-ticker same-account pair
  between a dividend cash txn and a `REINVESTMENT`/`BUY` ledger row
  within 2 calendar days; amount tolerance ±$1). Matched amounts
  bump `illiquid_cents` by construction; invariant drift stays 0.
  Frontend adds a dividend-reinvestment mid-node per ticker (same
  illiquid color family as Transfer→retirement aggregators), dashed-
  blue stroke marker to hint at the two-leg pairing with the
  `Investment Income` left-edge bar. Market-value changes on already-
  owned positions remain invisible — no fake left-edge node, no
  negative flows, per the Phase D reconciliation design.
  9 new unit tests: `tests/test_investment_contributions_view.py` (4)
  + `tests/test_dividend_interest_flows.py` (5). 338/338 backend
  suite + frontend build green; live Sankey verified end-to-end
  via browser preview on YTD-2026 with 2 reinvested dividends (SPG
  $29.96 + TGT $17.65). Static mockup at
  `~/.claude/plans/phase14-phase-c-sankey-mockup.html` approved
  before frontend merged.
  Prompt: `docs/prompts/Phase-14/P14-T03_dividends-interest-income.md`.
- `[v]` **P14-T04: Accountability scorecard (Phase D).** Landed
  2026-04-22. New `dal/reports.get_accountability` reconciles the
  identity `Δ NetWorth = (Dollars in) − (Dollars spent) ± (Market Δ)
  ± (RE Δ) ± (Vehicle Δ) + unexplained` in integer cents;
  `accounted_for_pct = max(0, 1 − |unexplained| / |Δ NW|)`. Helpers
  `_net_worth_at_date`, `_user_contributions_in_window` (reads
  `v_investment_contributions` for Phase-C-aware contribution
  classification), `_home_improvement_capex_in_window`. New
  `dal/accountability_drift.py` implements all 8 detectors from the
  prompt with sqlite-OperationalError tolerance for older schemas;
  results sort warnings-before-info then magnitude descending. New
  `GET /api/reports/accountability` on `backend/routers/reports.py`.
  Frontend `ReportsPage.tsx` adds the `AccountabilityScorecard`
  (green/yellow/red card, 95/85 thresholds, empty-state handling) and
  `AccountabilityModal` (7-tile identity equation + drift list with
  `useNavigate`-routed fix buttons → `/transactions`, `/accounts`,
  `/documents`). **Exit criterion met:** household YTD 2026
  (Jan 1 → Mar 31) reports 99.34% accounted ($29,261.40 Δ NW,
  $193.66 unexplained) — above the ≥95% / 3-month-window bar.
  7 new pytest tests in `tests/test_accountability.py` (identity
  reconciles, 4 drift detectors, market-gain/loss symmetry, owner
  scoping); 345/345 backend suite + `npm run build` + PII scan all
  green. Performance: ~1.0s/call dominated by the pre-existing
  `get_flow_data` call (Phase D helpers add <5ms); materialization
  of `v_investment_contributions` or shared upstream-flow is the
  right follow-up, not a Phase D blocker per the prompt. Mockup at
  `~/.claude/plans/phase14-phase-d-scorecard-mockup.html` approved
  before frontend merged.
  Prompt: `docs/prompts/Phase-14/P14-T04_accountability-scorecard.md`.
- `[ ]` **P14-T05: Rental property support (Phase E, deferred).**
  Rental income, rental expenses with sub-labels, per-property
  dedicated checking accounts seeded from savings, household rent
  as a regular housing expense. Security deposits as `STORED_LIQUID`
  with a restricted-balance warning (full restricted-balance table
  is backlog). Depreciation stays off the Sankey. Opens when any of
  three triggers fires: rental-income registry row added,
  `real_estate.type='rental'` flag set, or a per-property account
  starts receiving a recurring rent-shaped deposit.
  Prompt: `docs/prompts/Phase-14/P14-T05_rental-property-support.md`.

### Phase 15: Decision Support Features

**Goal:** Ship forward-looking "what should I do differently"
features. All four items are independent — pick any order.

- `[~]` **P15-T01: Mortgage extra payment simulator.** User deferred 4/18/26. Project the impact of
  extra principal payments against the existing `loan_details`
  schedule — months saved, interest saved, amortized vs linear.
- `[~]` **P15-T02: TSP switch/stay analysis.** User deferred 4/18/26. Compare current fund allocation
  vs alternative lifecycle/index allocations using historical TSP
  return series. Builds on the benchmark-price infrastructure from
  Phase 13.
- `[v]` **P15-T03: NFCU rewards points tracking.** `accounts.yaml`
  already configured `rewards_points` on the NFCU CC; pipeline from
  connector → `_result_loan_details` → `result_writer.persist_connector_result`
  → `record_loan_details` was already correct. Added: pivot column
  on `/api/accounts`, amber rewards chip on `AccountsPage.tsx`
  (only renders on finite integer; hides on missing field),
  `seed_credit_card_rewards` seeder for `summit_cc_3341`, 5-test
  `tests/test_rewards_points.py`. Chase excluded — not a rewards
  card (split to T05 for detail-scraping parity only). Golden seed
  fingerprint unchanged (static row, no RNG). 251/251 tests.
  Verified 2026-04-18 · `docs/prompts/Phase-15/P15-T03_nfcu-rewards-points.md`
- `[v]` **P15-T04: NFCU APY tracking + per-account capture audit.**
  **Phase A** (2026-04-18) — interactive NFCU walk, output at
  `P15-T04_audit_capture_proposal.md`. User locked full-stretch
  scope for Phase B. **Phase B** (2026-04-19) — shipped
  `v30_apy_history` migration, `dal/apy_history.py` DAL wrapper
  (record/get-latest/get-history, `[0,100]`+ISO+source invariants,
  `INSERT OR IGNORE` dedup, `parse_apy_string` helper),
  `result_writer` intercepts the `apy` key and routes to
  `apy_history` so every connector gets the cutover for free,
  Affirm's direct `record_loan_details` write replaced with
  `record_apy_history`, freshness tracker gained a 4th
  `MAX(as_of)` block (with pre-v30 try/except), NFCU
  `_extract_field_value` alternation extended for enrollment/Yes/No
  values, `field_patterns` gained 15 new fields (apy, dividends_ytd,
  cash_advance_limit, payoff_today, VIN capture-group, etc.),
  `accounts.yaml` fixed NFCU XXXX type drift (savings →
  checking) and wired 48 loan_details scrapes across 5 NFCU
  accounts, rolling `generate_apy_history` + `seed_apy_history`
  producing 72 deterministic rows over 36 months, stretch
  `seed_loan_details_stretch` stamps 30+ representative
  loan_details rows across 5 proxy accounts. 19 new tests in
  `tests/test_apy_history.py` (invariants, round-trip, dedup,
  history, freshness integration). Suite 280/280, zero
  regressions. UI surfacing deferred to T06.
  Verified 2026-04-19 ·
  `docs/prompts/Phase-15/P15-T04_apy-history-phase-b.md`
- `[v]` **P15-T03b: NFCU rewards points regex fix.** Surfaced during
  T04 Phase A — live NFCU portal renders rewards as a button label
  `"10,142pts Rewards"` (digits → `pts` → `Rewards`), and none of
  T03's label-first patterns matched. Fix landed: added
  `r"(\d[\d,]*)\s*pts\s+Rewards?"` as the first rewards pattern, and
  taught `_extract_field_value` to use any pattern containing its
  own capture group (detected via `\((?!\?:)`) as the full regex —
  future value-first connectors inherit this convention for free.
  10 new extractor unit tests in `tests/test_nfcu_extractor.py`; suite
  261/261. No DAL/seeder/UI change. Live re-verification deferred
  to the next NFCU refresh. Verified 2026-04-18 ·
  `docs/prompts/Phase-15/P15-T03b_nfcu-rewards-regex-fix.md`
- `[v]` **P15-T05: Chase detail scraping (credit card + checking).**
  Built parity with NFCU's detail scraper. Phase A walkthrough
  (2026-04-19) flipped both Chase account identities — XXXX is
  **Premier Plus Checking** (not Sapphire credit), XXXX is
  **Slate Edge** credit card (not Checking). Phase B rewrote the
  Chase `accounts.yaml` block, added `chase.detail.*` selectors,
  implemented `_scrape_account_details` with Chase-local
  `_extract_field_value` (line-boundary walking, no plain-number
  fallback, case-sensitive flag matching — driven by Chase's
  interposing "as of 12:00 AM ET on 04/17/2026" subtitle lines that
  broke NFCU's gap-based helper), wired Phase 3 into
  `_trigger_export`, and added 19 regex unit tests in
  `tests/test_chase_extractor.py`. Suite 299/299, zero regressions.
  Dropped out of scope: `14_day_payoff`, `ytd_interest`,
  `date_opened`, `direct_deposit_enrolled`, `overdraft_protection`,
  `rewards_points` — none surfaced on Chase's details views or
  agreed not worth the scrape. Live Chase refresh verification
  deferred to the next cycle. Verified 2026-04-19 ·
  `docs/prompts/Phase-15/P15-T05_chase-detail-scraping.md`
- `[v]` **P15-T06: Account Details UI subsection.** Inline expand
  panel on each eligible account row in `AccountsPage.tsx` showing
  every scraped `loan_details` field plus the latest `apy_history`
  row in a consistent, type-aware layout. New
  `AccountDetailsPanel.tsx` self-fetches via `useOwnerApi` with
  `{skip: !open}` (lazy per-row fetch, inherits view scoping for
  free). New `formatDetailField.ts` utility dispatches ~25 known
  field names to one of 7 kinds (currency / percent / date / count /
  boolean / months / text); hide-if-missing rule drops null/empty/
  unparseable rows so the card stays clean. Two-column responsive
  grid with APY hero row + "Scraped {as_of}" footer.
  `/api/accounts/{id}/details` handler gained a one-line
  `get_latest_apy` call so the endpoint now merges APY alongside
  `loan_details` — no new route, no migration. Auto-loan +
  mortgage share one `LOAN_ORDER` (seeded mortgage is `type='loan'`,
  DB doesn't distinguish — hide-if-missing naturally splits them).
  Manual assets + investment/retirement rows correctly do not
  render the toggle. 5 new tests in
  `tests/test_accounts_details_endpoint.py` (merge, loan-only,
  apy-only, both-empty, dedup); suite green; `npm run build`
  green; PII scan clean. Dev-server walkthrough confirmed
  summit_cc (7 fields), summit_chk (APY + 5 fields), summit_mtg
  (12 fields), Amy empty-state, and row-body navigation still
  works via `stopPropagation`. Verified 2026-04-23 ·
  `docs/prompts/Phase-15/P15-T06_account-details-ui.md`
- `[v]` **P15-T07: APY history chart on Account Details panel.**
  Shipped inline-SVG `Sparkline` component + pure `apyTrend` helper
  + backend `apy_history` on the `/details` response (12-month
  window, ascending, always a list — never null). T06's APY hero
  row upgraded to a **trend card**: rate on top, sparkline +
  direction annotation below. Color is asset/liability-aware via
  `directionSentiment` — savings/checking treat up as
  `--color-gain`, credit/loans treat up as `--color-loss`. Plain
  language copy: `↑ Up 0.04% since May 2025`, `Unchanged since
  March 2026`, `Unchanged over the last 12 months`. Half-basis-point
  flat threshold (0.0005%) guards against float wiggle. Accounts
  with `< 2` history rows fall back to T06's single-line hero.
  Backend: one-line `get_apy_history` call in
  `backend/routers/reports.py`; wire-minimal `{apy_rate, as_of}`
  shape. 3 new tests in `tests/test_accounts_details_endpoint.py`
  (ascending order, empty-list fallback, 12-month window cap).
  Suite 362/362, zero regressions. `npm run build` green, PII scan
  clean. Dev-server walkthrough confirmed rising-asset (Fidelity
  Brokerage Cash, +0.04% → green), flat-with-last-change (Summit
  Savings Feb 2026, Summit Checking Mar 2026, Brighton Savings
  Mar 2026 → muted), and no-history fallback (Summit CC / Auto /
  Mortgage → hero hidden, loan_details rows unaffected).
  Verified 2026-04-23 ·
  `docs/prompts/Phase-15/P15-T07_apy-trend-sparkline.md`
- `[v]` **P15-T08: Manual-asset details subsection (home + vehicle).**
  Shipped v35 migration adding `vehicle_assets.linked_loan_id`
  (idempotent via `column_exists`), a new parameterized
  `ManualAssetDetailsPanel.tsx` (single component, two asset kinds)
  reusing `Sparkline` + `formatDetailField` from T06/T07, a
  `valueTrend.ts` sibling of `apyTrend.ts` with a `valueTrendSentiment`
  helper that treats rising home value as good/green but makes
  vehicle depreciation neutral (not red — expected behavior), two
  new endpoints `/api/real_estate/{id}/details` and
  `/api/vehicles/{id}/details` joining linked loan fields server-side
  via a shared `_linked_loan_bundle` helper. Seeder wires the Civic to
  `summit_auto`; threading propagated through both
  `seed_dummy_data.py` and `seed_dummy_db.py` + `dal.vehicles.add_vehicle`
  (linked_loan_id preserved on re-run via `COALESCE`). 13 new tests
  across `test_vehicle_linked_loan_migration.py` (column lands,
  idempotent replay) + `test_real_estate_details_endpoint.py` (6
  cases) + `test_vehicle_details_endpoint.py` (5 cases). Suite
  375/375, zero regressions. `npm run build` green, PII scan clean.
  `ManualAssetEditModal` kept as-is — read-only surfacing only,
  per-row click still opens the edit modal via stopPropagation.
  Dev-server walkthrough confirmed Primary Residence (green, "↑ Up
  $3,016.48 since July 2025" across 12 quarterly valuations) and
  2020 Honda Civic (muted foreground, "↓ Down $1,800.00 since July
  2025" across 4 KBB valuations, VIN/GAP/collateral fields render
  because the seed pre-populates them even though live NFCU scrape
  doesn't — tracked in Scraper Adjustments Backlog below).
  Verified 2026-04-24 ·
  `docs/prompts/Phase-15/P15-T08_manual-asset-details.md`
- `[ ]` **P15-T09: Investment detail scraping.** Fidelity SEC yield
  (SPAXX cash fund), TSP per-fund YTD returns, Acorns contribution
  summary. Raised in T04 Phase A audit; populates the
  investment/retirement layout T06 explicitly leaves empty.
  Per-institution extractor work.
- `[v]` **P15-T10: Account/asset details panel — single source of
  truth.** Surfaced 2026-04-24 when the auto-loan Details panel was
  rendering "2022 KIA NIRO" collateral against a Toyota RAV4 vehicle
  row — the seeder had hardcoded a real Kia VIN that matched the
  household's actual vehicle. Three-PR fix: PR0 (commit 7e77822 after
  history rewrite) scrubbed the leak, rounded suspect mortgage/auto
  numbers, standardized `date_opened` strings, extended `pii_scan.py`
  with a VIN-shape detector, and force-pushed scrubbed history to the
  public repo. PR1 (commit ac95db9) shipped migrations v36
  (vehicle_assets.vin + gap_insurance) and v37 (real_estate.address +
  purchase_price + purchase_date), surfaced them through the DAL,
  added a denylist to `record_loan_details` that refuses
  collateral-identity field writes for loans with a linked asset, and
  introduced a composer module (`dal/account_details_composer.py`)
  that returns identical `collateral` slots from both sides of the
  loan↔asset join. 16 new invariant tests cover the denylist + composer
  convergence. PR2 (this PR) routes the seeder to write canonical
  sources only, adds credit-card derivation helpers (14_day_payoff,
  payment_due_date, ytd_interest), extends coastal_cc coverage, and
  gates a re-seed on three new post-seed asserts (no collateral
  drift, no orphaned secured loans, no stale due dates). PR3
  (commit dcb307d) swapped the three routers to call the composer
  and updated both panel components to consume the typed `collateral`
  slot — the loan side and asset side cannot visually disagree
  because both render from one shared source. Verified live with
  end_date=2026-04-24 dummy DB: Summit Auto Loan + 2020 Honda Civic
  panels show identical VIN / purchase_price / dates; Summit Mortgage
  + Primary Residence panels show identical address + purchased
  date; both credit cards now populated with end_date-rolling
  payment_due_date and balance-derived 14_day_payoff. Investment
  accounts render an explicit empty-state until P15-T09 ships
  per-fund yield. 391/391 backend tests pass; pii_scan clean.
  Prompt file: `docs/prompts/Phase-15/P15-T10_details-panel-single-source.md`
  Verified 2026-04-24.

### Scraper Adjustments Backlog

**Goal:** Parking lot for scrape gaps surfaced by UI work — fields
that are visible on a portal but not yet captured by the extractor.
Not tied to a phase; will be swept as a single extractor-focused
pass in a later phase once the list is long enough to warrant a
dedicated session.

- `[ ]` **NFCU auto-loan VIN capture.** Surfaced 2026-04-23 during
  P15-T08. NFCU renders the VIN on the auto-loan details view but
  `field_patterns` doesn't extract it — so scraped auto-loan
  `loan_details` rows carry everything except the VIN. T08's seeder
  populates `vehicle_assets.linked_loan_id` by hand; once the VIN
  scrape lands, connectors can join the asset → loan relationship
  from real data, and the hand-wired seed link becomes redundant.

### Phase 16: Notifications & Active Surveillance

**Goal:** Fill the dead placeholder on the header bell with a real
notification feed; give Phases 14–15 a natural place to emit alerts.

- `[v]` **P16-T01: Notification feed foundation.** Shipped `notifications`
  table (v38 migration), `dal/notifications.py` (record/list/mark-read/
  dismiss, caller-commits style, `INSERT OR IGNORE` dedup by `dedup_key`),
  `dal/documents.py` DAL helper (extracted `get_pending_nudges` from
  inline router SQL), `backend/routers/notifications.py` (4 endpoints:
  GET feed, GET unread-count, POST mark-read, POST dismiss). Four producers
  wired: budget alerts + large-txn + balance-low alerts routed from the
  existing `alert_events` pipeline via new `_notifications()` step at the
  tail of `result_writer.py::run_post_commit_pipeline`; upcoming/overdue
  bills from `dal.bills.get_upcoming_bills(days=7)`; doc-drop nudges from
  `dal.documents.get_pending_nudges`; refresh failures from the orchestrator
  failure branch in `refresh_orchestrator.py`. Frontend: new
  `NotificationPopover.tsx` replaces the dead Header stub — polls unread
  count every 60 s for badge, lazy-fetches feed on open, marks-all-read on
  open, per-row dismiss with optimistic UI. All Ember tokens; no emerald.
  32 new tests across 3 files (`test_notifications_dal.py`,
  `test_notifications_router.py`, `test_notifications_producers.py`);
  fixed 1 pre-existing test (`test_pending_nudges_suppressed_before_5th`)
  whose `date` patch target moved when pending-nudges logic migrated to the
  DAL. 423/423 backend tests pass; `npm run build` green; `pii_scan` clean.
  Verified 2026-04-24 ·
  `docs/prompts/Phase-16/P16-T01_notification-feed-foundation.md`
- `[ ]` **P16-T02: APY rate-change + recurring price-mutation producers.**
  `dal/apy_history.py` lacks a "changed since last snapshot" detector;
  `recurring_mutations` table has no notification emission. Wire both.
- `[ ]` **P16-T03: SSE push for notifications.** Broadcast a `notification`
  event on `/api/refresh/events` on record so the bell live-updates without
  polling. Formalise SSE topic registry.

### Phase 17: Real-Data Transition Prep

**Goal:** Make the dummy → real-data cutover a safe one-time
operation with seeder/live-connector parity.  Rethink this approach.
When the servers are started, it takes deliberate action to load it with
dummy data. What does the fully empty state look like?  Is the synthetic database
in the same shape as the real one? Parity there can make a smooth transition.

- `[ ]` **Destructive data wipe tooling.** Dedicated
  `scripts/wipe_data.py` with explicit confirmation prompt. Prep for
  the day the user actually flips from dummy to real data.  Questions from user: Is this 
  necessary?  Should we retain the ability to quickly load the app with 
  synthetic data for future development efforts?
- `[ ]` **myPay browser connector.** Automate the manual RAS PDF
  drop; feasibility informed by the existing P2-T04 parser. Closes
  the last manual-drop institution on the user's side. Key issue here
  will be choosing email OTP option, linking system to grab email OTP securely.
- `[v]` **P17-T03: DAL write wrappers for non-transactional tables.**
  New `dal/real_estate.py` + `dal/investments_writes.py` exposing
  `record_real_estate_valuations`, `record_investment_holdings`,
  `record_portfolio_snapshots`, `record_portfolio_snapshot`. Existing
  `record_credit_score` + `add_valuation` harmonized to caller-commits
  + invariant guards (FICO 300-850; `estimated_value > 0`; shares /
  price / market_value non-negative with shares*price tolerance). All
  seeder sites, generator investment writes, and the Acorns / Fidelity
  / TSP connector direct-INSERTs routed through wrappers. Fixed dead
  `from dal.derived import record_loan_details` in Fidelity. 246/246
  tests; seed-parity byte-identical on deterministic tables
  (yFinance-derived tables drift from pre-existing API
  non-determinism, not this change). Verified 2026-04-18 ·
  `docs/prompts/Phase-17/P17-T03_dal-write-wrappers.md`

### Phase 18: Investments — Tax Lots

**Goal:** Replace the honest "Cost basis not available" empty-state
(P11-T05) with real per-lot data once real broker statements arrive.

- `[ ]` **Cost Basis & Tax Lots.** Scope: per-institution parsers
  (Vanguard/Fidelity/Schwab/Greenleaf, myPay/TSP pattern), new
  `investment_tax_lots` table `(account_id, ticker, lot_id,
  acquired_date, shares, cost_per_share, cost_basis, currency)`,
  `dal/tax_lots.py`, `/api/investments/holdings` extension with
  optional `tax_lots` array, Holdings-tab lot table (acquired /
  shares / basis / MV / unrealized $/% / ST-vs-LT), and post-commit
  lot reconciliation. **Blocked on:** user wants real broker
  statements on hand before wiring. Surfaced 2026-04-09.

---

## HARD LINE — Trust Bar

```
============================================================
  STOP. Do not begin Phase 19+ work until Phases 14–18 are
  complete and the user has affirmed the app is production-
  trustworthy for their own financial data/decisions.

  The bar: "a fully working app I would be willing to trust
  with my own financial data/decisions." Partner integration
  is not a substitute for this bar — it compounds on top.
============================================================
```

---

## Remaining Work: Partner Integration

### Phase 19: Multi-User Infrastructure Polish

**Goal:** Close the four deferred items surfaced by P12-T05 so
multi-user infrastructure is ready for a real second owner before
Phase 20 wires live MFA.

- `[ ]` **Owner schema source-of-truth: YAML vs DB.**
  `config/owner_config.yaml` seeds `owners` on first init. After a
  Settings rename, YAML still says the old name but DB has the new
  one; renames survive re-seeds but a `data/sentry.db` wipe reverts
  to YAML. Pick one source of truth before multi-user real data.
  Surfaced 2026-04-08 during P12-T05.
- `[ ]` **Owner ViewSelector — fully owners-driven slots.**
  `ViewSelector.tsx` pulls labels from `useView().owners` but the
  3-slot layout is hardcoded `{quintin, ours, amy}`. Refactor to
  render one chip per owner + a fixed "Household" chip when owner
  #3 is added. Surfaced 2026-04-08.
- `[ ]` **Owner delete / archive lifecycle.** `update_owner` handles
  rename only — no delete/archive path. Cascade strategy non-trivial
  (block when owner has accounts/txns/payroll? soft-archive with
  `archived_at`? hard-delete with reassignment?). `ViewContext`
  defensive fallback already handles missing owner. Surfaced
  2026-04-08.
- `[ ]` **Owner cosmetic fields (avatar/color).** `OwnerUpdate`
  Pydantic + `update_owner` kwargs are shaped to accept
  `avatar_emoji`, `color_hex`, `archived_at` without redesign — but
  the columns don't exist. Add per-field migrations when each is
  wired into UI (one migration per field, not a speculative bundle).
  Surfaced 2026-04-08.

### Phase 20: Partner MFA Pipeline

**Goal:** Final gate for partner real-data ingestion — capture Amy's
MFA codes without the laptop needing her phone in person.

- `[ ]` **Partner MFA pipeline.** Tasker on Android → Tailscale
  overlay POST to `/api/mfa/forward`, multi-owner plumbing through
  `mfa_bridge`, per-owner credential namespaces. Full design in
  `docs/PARTNER_MFA_DESIGN.md`. Trigger when Phases 14–19 are done
  and partner banking ingestion is the active phase.

### Phase 21: Design System Consolidation

**Goal:** Close the gap between `docs/DESIGN.md` (the spec) and
`frontend/src/**` (the code) so changing a card / chip / palette
happens in one file, not N. Spec is frozen; implementation ships
in five tasks.

- `[v]` **P21-T01: Author DESIGN.md.** Locked the token source of
  truth (colors, typography, layout, elevation, component catalog)
  and catalogued the drift between spec and code (Known Drift
  block). Verified 2026-04-23.
- `[v]` **P21-T02: Tailwind config cleanup + typography swap.**
  Removed Manrope + Geist; installed Inter / Newsreader / JetBrains
  Mono via `@fontsource-variable/*`; bound Tailwind `primary` to
  `var(--primary)` instead of hardcoded `#11d483`; dropped orphan
  `background-light` / `background-dark`; deleted duplicate
  `--chart-1..5` aliases; migrated 4 `text-background-dark` and 11
  `'Geist Variable'` inline literals. Verified 2026-04-23 ·
  `docs/prompts/Phase-21/P21-T02_tailwind-config-cleanup.md`
- `[v]` **P21-T03: Build 8 missing primitives.** `<EmptyState>`,
  `<ErrorState>`, `<PageHeader>`, `<SectionHeader>`, `<FilterBar>`,
  `<StatCard>`, `<Chip>`, `<PageShell>` under
  `frontend/src/components/ui/`, matching DESIGN.md prop signatures.
  Verified 2026-04-23 ·
  `docs/prompts/Phase-21/P21-T03_build-primitives.md`
- `[v]` **P21-T04: Migrate pages to primitives.** Wave 1: 10 hand-
  rolled card shapes → `<Card>` across 6 files. Wave 2: 5 inline
  `animate-pulse` skeletons → `<Skeleton>`. Wave 3: ReportsPage +
  TransactionsPage wrapped in `<PageShell>`. Wave 4: bespoke empty
  states in DocumentsPage / CashFlowPage → `<EmptyState>`.
  Verified 2026-04-23 ·
  `docs/prompts/Phase-21/P21-T04_migrate-to-primitives.md`
- `[v]` **P21-T05: Ember palette swap.** `:root` and `.dark` in
  `index.css` replaced wholesale with Ember Studio terracotta +
  amber + warm-cream tokens. Added `--primary-hover`,
  `--surface-raised`, `--color-warning`. Chart palette rotated to
  terracotta-anchored 8-hue spread (teal / amber / plum / olive /
  burgundy / slate-blue / gold) with dark-mode lightness +~0.10 for
  contrast. Four utility-level emerald literals inside `index.css`
  (`.card-interactive:hover` border, `.chip-l2`, `.bg-gain-subtle`
  / `.bg-loss-subtle`, `.focus-ring`) moved to `color-mix` /
  `var(--surface-raised)` / `var(--foreground)`. Verified
  2026-04-24 · `docs/prompts/Phase-21/P21-T05_ember-palette-swap.md`

**Follow-ons** (T04-continuation — five parallel agents landed all
Blocker + High + Medium items 2026-04-24; one Low queued):

- `[v]` **T04-cont-A: Chrome-shell emerald purge (Blocker).** The
  app's chrome still flashes emerald on every route, masking the
  Ember swap. Sites:
  - `components/layout/Sidebar.tsx:54, 60, 86` — active nav item +
    active icon + Settings footer NavLink all hardcode
    `bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600
    dark:text-emerald-400`. Swap to `bg-primary/10 text-primary`.
  - `components/layout/Sidebar.tsx:55, 78, 87` — inactive items
    use `text-slate-500` / `border-slate-*` / `hover:bg-slate-50
    dark:hover:bg-slate-800/60`. Swap to `text-muted-foreground`,
    `border-border`, `hover:bg-surface-raised`.
  - `components/layout/Header.tsx` — page-icon badge (every route)
    `bg-emerald-50 dark:bg-emerald-500/10 text-emerald-500`;
    refresh button `bg-emerald-50 ... text-emerald-500`; refresh
    ping halo (line ~130) `ring-emerald-400/40 animate-ping`;
    search input `focus:ring-emerald-500/30
    focus:border-emerald-500/50 bg-slate-50 dark:bg-slate-800/60
    border-slate-200 placeholder:text-slate-400`. All swap to
    `bg-primary/10 text-primary` / `var(--ring)` / `bg-card
    border-border placeholder:text-muted-foreground`.
  - `App.tsx:95` — global `selection:bg-emerald-500/20` text-
    selection. Swap to `selection:bg-primary/20`.
  - `components/RefreshBanner.tsx:85` — `bg-emerald-500
    animate-pulse` status dot. Swap to `bg-primary` (or
    `.text-gain` background equivalent if it signals "live").
- `[v]` **T04-cont-B: Settings Save buttons + toggles (Blocker).**
  `pages/SettingsPage.tsx:216, 309, 422` — toggle switches use
  `multiUserEnabled ? "bg-emerald-500" : "bg-slate-300
  dark:bg-slate-600"`. CTA Save buttons use `bg-emerald-500
  hover:bg-emerald-600 text-white`. Either migrate inline to
  `bg-primary hover:bg-primary-hover text-primary-foreground` or
  replace with the `<Button>` primitive (existing tokenized
  CVA variants are default + secondary + destructive).
- `[v]` **T04-cont-C: Dashboard KPI + freshness + chart leaks
  (Blocker).**
  - `pages/DashboardPage.tsx:276` — freshness ladder
    `'text-emerald-500' / 'text-amber-500' / 'text-rose-500'`
    → `'text-gain' / 'text-warning' / 'text-loss'` (or
    `sentimentClass(value)` if wired).
  - Net-worth area chart gradient `id="emerald"` with
    `className="text-emerald-500"` — rebind to `var(--chart-c1)`.
  - Lines 926 — `whileHover backgroundColor: 'rgba(16, 185, 129,
    0.05)'` framer-motion hover → `color-mix(in oklch,
    var(--primary) 5%, transparent)` or drop.
  - Lines 931, 978 — `focus-visible:ring-emerald-500/50` →
    `focus-visible:ring-[var(--ring)]/50` or use `.focus-ring`.
  - Credit-score numerics — `text-indigo-600 dark:text-indigo-400`
    (component likely `CreditScoreCard.tsx`; verify) → `text-
    foreground` or `--chart-c7` (slate-blue) if we want
    credit-score-specific hue.
  - KPI deltas — 10+ sites pair `text-emerald-500` / `text-rose-
    500`; migrate to `.text-gain` / `.text-loss`.
- `[v]` **T04-cont-D: Reports Sankey + withholding palette
  (High).** `pages/ReportsPage.tsx:68-86` hardcodes a 16-entry
  INCOME/EXPENSE hex palette (`#00a3bf`, `#5a67d8`, `#e53e3e`,
  `#dd6b20`, etc.); lines 1122-1127 hardcode `WITHHOLDING_COLOR`
  map (federal / state / sbp / health / dental / other). Build a
  `getChartColor(idx)` helper that reads `--chart-c1..c8` via
  `getComputedStyle` or CSS custom-property lookup; swap both
  palettes to it. Same helper serves recharts tooltip fills
  elsewhere.
- `[v]` **T04-cont-E: Recharts tooltip + axis hex (High).**
  Tooltip chrome is hardcoded navy-slate in 5+ files:
  - `pages/AccountsPage.tsx:416, 419, 426, 427, 430` — tooltip
    `backgroundColor: '#1e293b'`, axis `fill: '#94a3b8'`, grid
    `stroke: "#334155"`.
  - `pages/InvestmentsAllocation.tsx`, `InvestmentsOverview.tsx`,
    `BudgetsPage.tsx:338` — same pattern.
  Tokenize via a shared `rechartsTooltipStyle()` + `axisTickStyle()`
  helper reading `var(--card)` / `var(--muted-foreground)` /
  `var(--border)`.
- `[v]` **T04-cont-F: Inline oklch(0.52 0.13 155) chart-series
  literals (High).** 5 files, 7 sites:
  `DashboardPage.tsx:220` (Cash map),
  `BudgetsPage.tsx:36, 37, 54` (Food & Dining + palette array),
  `AccountsPage.tsx:233` (assets chart config),
  `AccountsSummaryCard.tsx:43` (`--chart-c1 emerald` inline
  comment + literal). All → `var(--chart-c1)` (or other slot).
- `[v]` **T04-cont-G: SyntheticBadge violet → amber (High).**
  `components/ui/SyntheticBadge.tsx:11-12, 24-25` uses
  `bg-violet-100 dark:bg-violet-900/30 text-violet-600
  dark:text-violet-400`. Shared component means every "DEMO" chip
  across the app inherits the violet. Swap to
  `bg-accent/15 text-accent-foreground` (Ember amber) or a
  dedicated `--chart-c4` plum slot — design call.
- `[v]` **T04-cont-H: Account-group + category decorative colors
  (High).** `pages/AccountsPage.tsx:277-282` maps Credit Cards,
  Loans, and per-category icons to `text-rose-500` / `text-amber-
  500` / `text-purple-500` / `text-indigo-500` / `text-sky-500`.
  Decide: keep sentiment-style decoration (migrate to
  `--color-loss` / `--color-warning` / `var(--chart-c4..c7)`) or
  switch to neutral `muted-foreground` icons. Same decision
  applies to `MonthlyReviewPage.tsx` icon accents
  (`text-orange-500` / `text-indigo-500` / `text-sky-500` /
  `text-purple-500`, ~4 sites).
- `[v]` **T04-cont-I: Neutral-palette bulk sweep (Medium, largest
  mechanical pass — 576 hits / 26 files).** Primary offenders:
  `TransactionsPage.tsx` (79 slate hits), `DashboardPage.tsx`
  (73), `YearlyWrapUpPage.tsx` (60), `MonthlyReviewPage.tsx`
  (48), `ReportsPage.tsx` (47). Mostly
  `text-slate-{400,500,600}`, `bg-slate-{50,100,800}`, and
  `border-slate-{200,700,800}/60`. Target substitutions:
  `text-muted-foreground`, `bg-surface-raised`, `border-border`.
  Light-mode cool vs cream contrast is the main visual fix; dark-
  mode `dark:bg-primary/5` sites also need audit (see J below).
- `[v]` **T04-cont-J: Primary-opacity dark-mode audit (Medium).**
  75 sites use `bg-primary/{5,10,20,30}` or `text-primary/60`
  patterns that looked quiet on emerald (luminance ~0.7) and may
  now look like muddy-pink tint on terracotta (luminance ~0.52 +
  chroma 0.17). Hotspot: `TransactionsPage.tsx` (51 hits —
  especially the `dark:bg-primary/5` table header + row
  alternation at lines 509-510, 793, 795-799); also
  `AccountsPage.tsx:471, 490, 518, 527, 667, 694`. Action: visual-
  QA each dark-mode case, substitute `bg-surface-raised` where
  the intent was "quietly raised panel" rather than "primary
  sentiment".
- `[v]` **T04-cont-K: `font-mono` currency → `.text-numeric`
  (High, small mechanical pass).** 21 sites across 8 files:
  `DashboardPage.tsx` (8 sites), `MonthlyReviewPage.tsx` (5),
  `LifestyleCreepPanel.tsx` (3), `BudgetsPage.tsx` (1),
  `InvestmentsOverview.tsx` (1), plus 3 more. Per DESIGN.md §
  Typography rule; `font-mono` picks whatever mono the OS ships,
  losing JetBrains' tabular-nums alignment.
- `[v]` **T04-cont-L: Sentiment-palette migration (Medium).**
  85 hits of `text-rose-*` / `bg-red-*` / `text-amber-*` /
  `bg-yellow-*` / `text-orange-*` across 15 files. Most are
  status pills and alert banners. Migrate to `.text-loss` /
  `.text-warning` / `.bg-loss-subtle` utilities — `--color-loss
  oklch(0.58 0.22 27)` already matches rose; `--color-warning
  oklch(0.67 0.15 55)` already matches amber.
- `[v]` **T04-cont-M: TransactionLogo deterministic hex palette
  (Medium).** `components/ui/TransactionLogo.tsx:112-114` has a
  20-entry hash-to-color palette (indigo, violet, pink, cyan
  families). The deterministic-color intent is legitimate (stable
  identity per merchant) but the hex values are off-palette.
  Rotate to `--chart-c1..c8` indexed by hash, or keep the 20-slot
  variety but regenerate from Ember OKLch hue wheel (`oklch(0.55
  0.12 <h>)` with h stepped by 18°).
- `[v]` **T04-cont-N: `font-feature-settings` body alignment
  (Low).** `index.css:126` sets `"cv02", "cv03", "cv04", "cv11"`;
  DESIGN.md § Typography specifies `"cv11", "ss01"` for Inter.
  Cosmetic-only; fold into this pass.
- `[ ]` **T04-cont-O: Logo asset (Low).** `public/logo.png` (or
  wherever Sidebar renders it) bakes a slate-900 panel +
  emerald-green mark. Post-swap it reads as "wrong brand, wrong
  era." Commission a cream/terracotta variant; also drop the
  `border-[color:var(--color-loss)]` wrapper the visual audit
  flagged (a stray 3-px red border around the logo image).
- `[v]` **T04-cont-P: Focus-ring literal sweep (Medium).** 4
  sites hardcode emerald focus ring: `DashboardPage.tsx:931,
  978`, `CashFlowPage.tsx:321`, `Header.tsx:94`,
  `MFAModal.tsx:184`. Swap to `.focus-ring` utility (now
  `color-mix(var(--primary) 40%, transparent)`).
- `[v]` **T04-cont-Q: MFAModal inline-style purge (Medium).**
  11 inline-style sites converted: header gradient →
  `var(--primary-hover) → var(--primary)`; focus ring →
  `.focus-ring`; body/border/input/Cancel/error → tokens; Submit
  gradient → primary-hover → primary; font-mono MFA input →
  `.text-numeric`. Scrim `rgba(0,0,0,0.6)` and disabled-overlay
  `rgba(255,255,255,0.1)` kept (neutral alphas, no color
  semantics).

**New follow-ons surfaced during the T04-continuation sweep:**

- `[v]` **T04-cont-R: Tremor → Recharts migration (High).**
  Both Tremor `<AreaChart>` usages (Dashboard net-worth hero +
  CreditScorePopup multi-series) rewritten as Recharts with
  `var(--chart-c1..cN)` gradient fills + `rechartsAxisTickStyle`
  / `rechartsTooltipStyle` helpers. `@tremor/react` removed from
  `package.json`; `./node_modules/@tremor/**` content path
  dropped from `tailwind.config.js`. Bundle shrank CSS 120.50KB →
  97.07KB (−19%), JS 2,065KB → 1,314KB (−36%). DESIGN.md's
  "Tremor tolerated for legacy, being phased out" direction now
  realized.
- `[ ]` **T04-cont-S: Sankey 12-slot palette collision (Low).**
  `pages/ReportsPage.tsx` `SPEND_COLORS` was remapped from 12
  hardcoded hexes to the 8-slot `chartColor(i)` cycle, so slots
  now repeat (c1 at index 4 & 8; c2 at 1 & 9; c5 at 0 & 6).
  Either add `--chart-c9..c12` to `index.css` or consolidate
  SPEND categories to 8.
- `[ ]` **T04-cont-T: ReportsPage bucket shade collapse review.**
  Agent 4 collapsed the 2-shade `BUCKET_FILL` / `BUCKET_INK`
  pattern (muted fill + solid ink per bucket) to a single
  semantic token per bucket, relying on rendering-site opacity
  (`opacity={0.75}`) to produce fill/ink contrast. If Sankey
  terminal buckets look flat on visual QA, restore the 2-shade
  pattern via new `--chart-bucket-*-fill`/`-ink` tokens.
- `[ ]` **T04-cont-U: TransactionLogo border tokenization (Low).**
  Agent 5 migrated the 20-entry hash-to-color palette in
  `components/ui/TransactionLogo.tsx` to Ember OKLch hues but
  left border styling at line 169 (`border-slate-200
  dark:border-slate-700/50 bg-white dark:bg-slate-800`). Migrate
  to `border-border bg-card`.

**Non-palette loose thread surfaced during the audit:** visual
agent observed `/cashflow`, `/monthly-review`, `/yearly-review`
rendering with owner-chip only and no content below on the
running dev server. May be a data-wire / empty-state issue, may
be pre-existing, may be an artifact of the agent's navigation
timing. Worth a 5-minute look before the next session declares
those pages clean.

---

## Backlog (quality / deferred — triggered, not scheduled)

Items that don't block any phase and fire only when a specific
trigger arrives.

- `[ ]` **Reconciliation hardening.** `dal/reconciliation.py`
  matches integer-cent absolute amounts in opposite directions
  within a 3-day window. Defer FX-aware matching, multi-day clearing
  windows > 3 days, and partial/fee-adjusted matches until a
  real-world miss surfaces.
- `[ ]` **Extractor changes touching the sign/direction convention.**
  Phase 10 fixed the analytical layer; connectors already flow
  through `upsert_transactions()` so they're protected by the
  invariant assertion. Defer until extractors are touched for other
  reasons.
- `[ ]` **Move `/api/accounts/{id}/details` handler to `accounts.py`
  + route through DAL.** Handler currently lives in
  `backend/routers/reports.py` with inline SQL (pre-dates the
  "no direct queries outside the DAL" guardrail). Wrap in a new thin
  `dal/loan_details.py::get_latest_loan_details(conn, account_id)`
  and relocate the route to `backend/routers/accounts.py` alongside
  the other account endpoints. Triggered by the next unrelated touch
  on `reports.py` or `accounts.py` — do not bundle with unrelated
  feature work. Surfaced 2026-04-23 during P15-T06.
- `[ ]` **Track UI/UX P0 audit deferrals (2026-04-23) in ROADMAP.**
  Add a pointer from ROADMAP to
  `docs/audits/2026-04-23-uiux-execution-log.md` so the 14 deferred
  P0s (dark-mode contrast × 4, ViewSelector CSS tokenization, Card
  primitive pattern extraction, BudgetsPage Button swaps × 3 design
  decisions, CashFlow filter Button swaps × 2, Header Notifications
  chrome restructure, DashboardPage keyboard a11y shim, BudgetsPage
  Sheet primitive) are findable from the main status doc.
  One-paragraph pointer, not a re-paste. Surfaced 2026-04-23 during
  P15-T06 planning.
