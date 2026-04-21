# Sentry Finance --- Development Roadmap

> **Status tracking document.** Read alongside `ARCHITECTURE.md`; load
> the matching `docs/prompts/<Phase-N>/` folder only when a task
> summary below isn't enough.
>
> Last updated: 2026-04-19 (P0-SEC Track A + Track B complete —
> source-code PII scrub, pii_scan.py + pre-commit hook,
> categorization user-overlay, accounts.yaml opaque `id:` scheme,
> v31 migration, dummy-seeder rewrite. Git history filter-repo is
> the final step and runs as a one-off operation outside the
> conventional commit cadence).

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
| **14** | Dollar Accountability Overhaul | `[ ]` Planned (reclaims deferred Budget slot) | `docs/prompts/Phase-14/` |
| **15** | Decision Support Features | `[~]` T03 + T03b + T04 (A+B full-stretch) complete; T01/T02 deferred; T05/T06 planned | `docs/prompts/Phase-15/` |
| **16** | Notifications & Active Surveillance | `[ ]` Planned | (to be authored) |
| **17** | Real-Data Transition Prep | `[~]` T03 complete; T01/T02 planned | `docs/prompts/Phase-17/` |
| **18** | Investments --- Tax Lots | `[ ]` Blocked on broker statements | (to be authored) |
| **19** | Multi-User Infrastructure Polish | `[ ]` Planned (post hard-line) | (to be authored) |
| **20** | Partner MFA Pipeline | `[ ]` Planned (post hard-line) | `docs/PARTNER_MFA_DESIGN.md` |

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
- `[ ]` **P14-T03: Dividends and interest as real income (Phase C).**
  Dividends and HYSA/bank interest become first-class income sources
  via the registry. Reinvested dividends draw as two-leg flows
  (dividend income → account → `STORED_ILLIQUID` buy). Market value
  changes on owned positions remain invisible on the Sankey (no
  fake source nodes, no negative flows). New SQL view
  `v_investment_contributions` (migration v34).
  Prompt: `docs/prompts/Phase-14/P14-T03_dividends-interest-income.md`.
- `[ ]` **P14-T04: Accountability scorecard (Phase D).** Identity:
  `Δ NetWorth = (Dollars in) − (Dollars spent) ± (Market value Δ) ±
  (Real-estate Δ) ± (Vehicle Δ) + unexplained`. Sticky header card
  above the Sankey with `accounted_for_pct`; drilldown modal lists
  named drift sources with click-to-fix affordances (uncategorized
  transactions, stale portfolio snapshot, missing payroll snapshot,
  stale home valuation, CC-payment boundary timing, unrecorded
  vehicle depreciation, interpolated real-estate valuation,
  contractor-season tax ambiguity). New
  `/api/reports/accountability`. Target: ≥95% accounted on a 3-month
  real-data window before the long-lived branch merges.
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
- `[ ]` **P15-T06: Account Details UI subsection.** Per-account-card
  details panel on `AccountsPage.tsx` that surfaces every scraped
  field from `loan_details` plus the latest `apy_history` row in a
  consistent layout (checking fees, savings APY, credit card APR +
  credit limit + min payment + due date + rewards, loan APR + next
  payment, etc.). Works off the existing generic
  `/api/accounts/{id}/details` endpoint — no new backend. Follow-on
  after T04/T05 have broadened the capture surface. Surfaced
  2026-04-18 during T04 clarification.

### Phase 16: Notifications & Active Surveillance

**Goal:** Fill the dead placeholder on the header bell with a real
notification feed; give Phases 14–15 a natural place to emit alerts.

- `[ ]` **Notification feed (header bell).** Decide producers
  (refresh failures, budget threshold breaches, upcoming bills,
  document drop nudges, rate changes) then wire producer + badge
  logic on the bell icon. Surfaced 2026-04-08 during dashboard
  click/hover audit.

### Phase 17: Real-Data Transition Prep

**Goal:** Make the dummy → real-data cutover a safe one-time
operation with seeder/live-connector parity.  Rethink this approach.
When the servers are started, it takes deliberate action to load it with
dummy data. What does the fully empty state look like?  Is the synthetic database
in the same shape as the real one? Parity there can make a smooth transition.

- `[ ]` **Destructive data wipe tooling.** Dedicated
  `scripts/wipe_data.py` with explicit confirmation prompt. Prep for
  the day the user actually flips from dummy to real data.  Is this 
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
