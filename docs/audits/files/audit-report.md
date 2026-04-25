# Sentry Finance — Numeric Correctness Audit (2026-04-24)

- **Run date:** 2026-04-24
- **Branch:** `main` @ `1da4c30`
- **Schema:** v38 (notifications)
- **DB:** `data/sentry.db` — read-only access throughout
- **Owner data:** Quintin owns 12 accounts, Amy owns 0 (Amy=∅ per-owner view is exercised explicitly in xc_001)
- **Investment surface:** treated as **live** (orchestrator prompt's P13-dormancy carve-out is stale; tables are populated)
- **Pipeline:** 1 inventory pass → 82 invariants → 8 parallel checker agents → 5 parallel diagnostician agents
- **Inputs:** [`inventory.json`](inventory.json), [`invariants.json`](invariants.json), [`results-*.json`](.) (per group), [`aggregated-results.json`](aggregated-results.json)

## 1. Executive Summary

| Status | Count | Notes |
|---|---|---|
| ✅ pass | **76** | Backed by executed code in `query_or_script` |
| ❌ fail | **4** | All diagnosed, fix locations identified |
| ⚠️ could_not_verify | **2** | 1 spec_gap (documented), 1 reclassified to data_bug below |
| **Total** | **82** | Across 8 page-groups |

**Headline findings — see §6 punch list for details.**

| # | Severity | One-liner |
|---|---|---|
| 1 | P0 | Recurring Bills monthly total inflated ~$520 by `'semi-annual'` vs `'semiannual'` key mismatch |
| 2 | P0 | Yearly Wrap-Up "Net Interest Cost" sign-flipped on the preliminary path — UI shows interest income as a red loss |
| 3 | P0 | Mortgage payment decomposition broken: `loan_payment_splits` is empty for every seeded mortgage payment; Sankey P/I/E stripes on Reports page are fed sentinel `'unsplit'` rows |
| 4 | P0 | 12 aggregate endpoints don't thread `owner_id` (CLAUDE.md non-negotiable); 2 are pure router bugs, 10 are spec gaps |
| 5 | P1 | `freshness.get_institution_freshness(owner_id=...)` raises `OperationalError: ambiguous column name: id` — owner-scoped freshness is silently broken |
| 6 | P2 | Benchmark prices lag portfolio snapshots by 1 trading day (yfinance limitation, not a bug — recommend relaxing invariant) |
| 7 | P2 | Seeded portfolio drift vs live yfinance benchmarks (cosmetic, documented `spec_gap`) |

## 2. Inventory snapshot

Full inventory at [`inventory.json`](inventory.json). Coverage across 13 pages (SettingsPage skipped — no numeric content):

| Page | Numeric elements catalogued |
|---|---|
| DashboardPage.tsx | 14 |
| TransactionsPage.tsx | 3 |
| CashFlowPage.tsx | 11 |
| ReportsPage.tsx | 26 (Sankey + buckets + accountability + payroll) |
| AccountsPage.tsx | 5 |
| BudgetsPage.tsx | 6 (household-only) |
| InvestmentsOverview.tsx | 3 |
| InvestmentsHoldings.tsx | 8 |
| InvestmentsAllocation.tsx | 4 |
| MonthlyReviewPage.tsx | 6 |
| YearlyWrapUpPage.tsx | 5 |
| DocumentsPage.tsx | 1 |

Plus 9 cross-page pairs flagged for consistency checking.

## 3. Invariant catalog (by group)

Full list at [`invariants.json`](invariants.json). 82 invariants total, dispatched to 8 checker groups.

| Group | Invariants | Pass | Fail | CNV |
|---|---|---|---|---|
| dashboard | 10 | 9 | 1 | 0 |
| cashflow | 12 | 12 | 0 | 0 |
| reports | 14 | 13 | 0 | 1 |
| accounts_budgets | 10 | 10 | 0 | 0 |
| investments | 10 | 8 | 1 | 1 |
| monthly_yearly | 9 | 8 | 1 | 0 |
| txns_docs | 5 | 5 | 0 | 0 |
| **cross_cutting** | 12 | 11 | 1 | 0 |
| **Total** | **82** | **76** | **4** | **2** |

## 4. Per-group highlights (passed checks)

The 76 passed checks are too numerous to list; selected highlights below confirm the project's most load-bearing properties hold.

- **Sign-direction law (`xc_011`, `txns_001`).** All 2,027 transactions satisfy `(signed_amount<0 ⟺ direction='Debit') AND (signed_amount>0 ⟺ direction='Credit') AND amount = abs(signed_amount)`. Zero violations.
- **Owner scoping with Amy=∅ (`xc_001`).** Every owner-scoped DAL aggregate called with `owner_id='amy'` returns zero/empty. The `dal.owners.build_account_filter([])` short-circuit (`AND 1=0`) holds — no leakage from Quintin.
- **Household = Quintin (`xc_002`).** Since Quintin owns 100% of accounts, household-view aggregates exactly match Quintin's per-owner aggregates.
- **No legacy aggregate pattern (`xc_003`).** Code search across `dal/**/*.py` finds zero `SUM(CASE WHEN direction='Debit' ...)` patterns. Canonical pattern is enforced.
- **Transfer-tag balanced (`xc_004`).** All 174 reconciled (non-`invest:*`) transfer tags appear on exactly two rows whose signed_amounts sum to ~0. The 405 `invest:*` single-leg tags are investment-link markers, out of scope for transfer-pair reconciliation.
- **Canonical pattern matches recompute (`xc_005`).** Hand-rolled canonical SQL matches `dal.cash_flow.get_monthly_cash_flow(owner_id=None)` exactly for 2026-01, 02, 03.
- **Budgets household-only (`bud_001`, `xc_006`).** Partial unique index `idx_budgets_household_unique ON budgets(category, month) WHERE owner_id IS NULL` exists; all 324 budget rows have `owner_id IS NULL`.
- **Cross-page net worth coherence (`xc_008`).** Dashboard NetWorthCard latest equals Accounts NetWorthChart latest (same DAL fn).
- **Cross-page spending coherence (`xc_009`).** Dashboard "spending this month" equals Reports flow `total_spending` for the same window.
- **Yearly = sum of monthly (`xc_010`, `cf_006`).** Yearly cash flow equals sum of monthly for 2025 (last complete year), within $0.01.
- **Money is REAL, not integer cents (`xc_007`).** PRAGMA confirms `transactions.amount` and `signed_amount` are stored as REAL. CLAUDE.md aspires to integer cents but the live schema diverges — flagged as a doc/code drift but not an audit failure.

## 5. Cross-page consistency

The orchestrator's planned cross-page pass was folded into the `cross_cutting` group (xc_005, xc_008, xc_009, xc_010). All four passed — Dashboard, Cash Flow, Reports, and Yearly Wrap-Up agree on the same facts within tolerance.

The `bud_003` invariant (Budget summary totals match per-row aggregates) also passed, confirming Dashboard budget widget = Budgets page totals = sum of per-category rows.

## 6. Findings — punch list

Findings are ordered by severity, with file paths, line numbers (where supplied by diagnosticians), and the diagnostician's cause classification. **Locations only — fixes are deliberately not proposed; the user decides what to action.**

---

### 1 · P0 · Recurring Bills monthly total inflated ~$520

**Invariant:** `dash_007_recurring_total_normalized` · **Page:** [DashboardPage.tsx](frontend/src/pages/DashboardPage.tsx) (RecurringWidget)
**Cause:** `convention_mismatch`
**Numbers:** DAL returned `-$6,327.01`; canonical recompute = `-$5,807.05`; diff `$519.96`

The dummy seed fixture writes the GEICO AUTO insurance row's `frequency` as `'semi-annual'` (with hyphen). The detector at [dal/recurring.py](dal/recurring.py) `classify_frequency` emits `'semiannual'` (no hyphen), and the consumer dict `MONTHLY_FACTORS` at line ~403 only keys on `'semiannual'`. Result: the $624 semi-annual premium falls back to factor `1.0` and is treated as a $624/month bill, inflating the monthly total by $624 − ($624/6) = $520.

**Fix locations** (do not edit yet):
- [dal/recurring.py:403](dal/recurring.py:403) — `MONTHLY_FACTORS` dict in `get_monthly_recurring_total` (the consumer)
- [dal/recurring.py:693](dal/recurring.py:693) — same bug-class in `get_recurring_with_payoff` inline factor dict
- [dummy_data/recurring_transactions.json](dummy_data/recurring_transactions.json) — GEICO AUTO entry's `frequency` field
- [scripts/seed_dummy_db.py:171](scripts/seed_dummy_db.py:171) — `freq_days` dict with hyphenated key

**Blocking question for the user:** which spelling is canonical — `'semiannual'` (used by the detector and 5 DAL files including budgets/forecasting/scenarios) or `'semi-annual'` (used by the seed fixture)? Need this to know whether to fix the writer or the reader side.

---

### 2 · P0 · Yearly Wrap-Up "Net Interest Cost" is sign-flipped on the preliminary path

**Invariant:** `yr_003_interest_net_cost_definition` · **Page:** [YearlyWrapUpPage.tsx](frontend/src/pages/YearlyWrapUpPage.tsx)
**Cause:** `convention_mismatch`
**Numbers:** For 2025/quintin: `total_paid=$0, total_earned=$1140`; UI shows `+$1140` colored red as a "Net Interest Cost"; user actually netted +$1140 of interest income.

Three sites disagree on the sign of `interest.net_cost`:

1. [dal/derived.py:608](dal/derived.py:608) `compute_interest_cost` returns `net_interest = interest_earned - ytd_total` — positive means interest **income**.
2. [dal/yearly_wrapup.py:176](dal/yearly_wrapup.py:176) `_build_preliminary` maps that value directly into a field literally named `net_cost`.
3. The tax-overlay branches in the SAME file compute the OPPOSITE:
   - [dal/yearly_wrapup.py:546](dal/yearly_wrapup.py:546) Affirm 1099-INT: `net_cost = total_paid - interest_income`
   - [dal/yearly_wrapup.py:560](dal/yearly_wrapup.py:560) NFCU 1098: `net_cost = mtg_interest - total_earned`
4. [frontend/src/pages/YearlyWrapUpPage.tsx:123](frontend/src/pages/YearlyWrapUpPage.tsx:123) and [:393](frontend/src/pages/YearlyWrapUpPage.tsx:393) label the field "Net Interest Cost" and color `>0` as `text-loss` (red), confirming the UI expects `paid - earned`.

The preliminary path is the outlier; the UI/label/overlay convention all agree. With paid=$0 and earned=$1140 the user sees red as if losing $1140 to interest expense when the truth is +$1140 of interest income.

**Fix locations:**
- [dal/yearly_wrapup.py:176](dal/yearly_wrapup.py:176) — `_build_preliminary` interest block (high confidence — minimal blast radius, aligns with field name and UI)
- [dal/derived.py:608](dal/derived.py:608) — alternative: flip the canonical sign at the source (medium confidence — affects all callers)
- [frontend/src/pages/YearlyWrapUpPage.tsx:123](frontend/src/pages/YearlyWrapUpPage.tsx:123) `:393` — only if backend is changed to earned-positive

**Blocking question:** which convention is canonical on the wire — `paid - earned` (matches name/UI/overlay) or `earned - paid` (matches `compute_interest_cost`)?

---

### 3 · P0 · Mortgage payment decomposition does not work for any seeded data

**Invariant:** `rep_009_mortgage_split_components_sum` (originally `could_not_verify`, reclassified to `data_bug` by diagnostician) · **Page:** [ReportsPage.tsx](frontend/src/pages/ReportsPage.tsx) (Sankey mortgage P/I/E stripes; TerminalBucketsPanel)
**Cause:** `data_bug`
**Numbers:** All 4 mortgage payments in `[2026-01-01, 2026-04-24]` have `method='unsplit'`; `loan_payment_splits` table has 0 rows total.

The DB schema in [dal/migrations/v33_loan_payment_splits.py](dal/migrations/v33_loan_payment_splits.py) only permits methods `('amortization','statement','manual')`. `'unsplit'` is a sentinel synthesized by [dal/reports.py:903](dal/reports.py:903) when the LEFT JOIN to `loan_payment_splits` returns NULL — i.e., decomposition has never been computed.

Two layered causes:

1. The seeder ([scripts/dummy_data/generator.py:267-275](scripts/dummy_data/generator.py:267)) writes the mortgage cash-leg debit to `summit_chk` (a `checking` account, with `category='Mortgages'`) and the credit leg to `summit_mtg` (a `loan` account). It does NOT invoke the post-commit pipeline, so `_mortgage_splits` never runs after seeding.
2. Even when invoked, [dal/debt.py:554](dal/debt.py:554) `decompose_unsplit_mortgage_payments` filters by `a.type IN ('mortgage','loan')` on the transaction's own account. The cash-leg debit is on a `checking` account — excluded by the filter. The offsetting credit on the loan account is `signed_amount > 0`, also excluded by the `signed_amount < 0` clause. **The function as written cannot decompose any seeded mortgage payment regardless of whether it is invoked.**

Meanwhile, [dal/reports.py](dal/reports.py) selects mortgage rows by `t.category IN ('Mortgage','Mortgages')` with NO account-type constraint — so it picks up the checking-leg debit and surfaces it as a "mortgage_split" with `method='unsplit'`. Reader and writer disagree on what a "mortgage payment" looks like.

**User-visible impact:** Reports page Sankey mortgage P/I/E stripes never populate; the Terminal Buckets panel shows 4 unsplit mortgage rows with a manual-classification warning the user can never satisfy because the DAL won't accept their input.

**Fix locations:**
- [dal/debt.py](dal/debt.py) `decompose_unsplit_mortgage_payments` — high confidence (writer/reader drift origin)
- [scripts/dummy_data/generator.py:267-275](scripts/dummy_data/generator.py:267) — medium confidence (seeder design choice)
- [backend/result_writer.py](backend/result_writer.py) `_mortgage_splits` — low confidence (called from real-ingest path, not seeder path)

**Blocking question:** should the decomposer key off `category='Mortgages'` and resolve the linked loan via `recurring_loan_link` (migration v16), or should the seeder change to post the debit on the loan account itself?

---

### 4 · P0 · 12 aggregate endpoints missing `owner_id` threading

**Invariant:** `xc_012_owner_id_threading_in_routers` · **Page:** cross-page
**Cause:** mixed — 2 are pure `aggregation_bug`, 10 are `spec_gap`
**Counts:** 12/55 aggregate-style GET endpoints across `reports.py`, `recurring.py` (resource-scoped `{x_id}` and mutating endpoints excluded as out-of-scope).

CLAUDE.md guardrail: "Every new query, endpoint, and page MUST thread `owner_id`. Use `dal/owners.build_account_filter`."

**Pure `aggregation_bug` (DAL accepts `owner_id`, router fails to pass it through) — high-confidence two-line fixes:**

| Route | Router fn | DAL fn |
|---|---|---|
| `GET /api/export/transactions` | `export_transactions` ([backend/routers/reports.py:530](backend/routers/reports.py:530)) | `dal.reports.export_transactions_csv(..., owner_id=None)` |
| `GET /api/lifestyle/creep` | `lifestyle_creep` ([backend/routers/reports.py:642](backend/routers/reports.py:642)) | `dal.lifestyle.get_lifestyle_creep(..., owner_id=None)` |

**`spec_gap` (DAL never accepted `owner_id`) — product decisions required:**

| Route | DAL fn | Notes |
|---|---|---|
| `GET /api/metrics/summary` | `dal.derived.get_summary_metrics` | Reads pre-aggregated `derived_summaries` table (refactor touches recompute pipeline) |
| `GET /api/metrics/dti` | `dal.derived.compute_dti_ratio` | DTI is naturally a household metric (joint debt vs joint income) |
| `GET /api/metrics/interest-cost` | `dal.derived.compute_interest_cost` | Loans have `owner_id`; per-owner is plausible but DAL never accepted |
| `GET /api/forecast` | `dal.forecasting.get_cash_flow_forecast` | Documented as household-level (Phase 3 design) |
| `GET /api/income/seasonal-model` | `dal.forecasting.build_seasonal_income_model` | Income streams (pension/disability/officiating) are conceptually owner-scoped |
| `GET /api/attribution-rules` | `dal.attribution.get_attribution_rules` | Configuration table, plausibly household-only |
| `GET /api/review/yearly/tax-checklist` | `dal.yearly_wrapup.get_tax_doc_checklist` | Joint-filing context; sibling `/api/review/yearly` DOES thread owner_id (inconsistent) |
| `GET /api/bills/upcoming` | `dal.bills.get_upcoming_bills` | DAL queries `recurring_transactions` directly; needs JOIN to `accounts` first |
| `GET /api/bills/overdue` | `dal.bills.get_overdue_bills` | Same shape as above |
| `GET /api/bills/summary` | `dal.bills.get_bills_summary` | Same shape as above |

**Blocking questions:**
- For metrics_summary, dti, forecast, attribution-rules, tax-checklist: do these stay household-only by design (analogous to budgets-as-of-v23), or be elevated to per-owner?
- For the three bills endpoints: scope by `accounts.owner_id` joined through `recurring_transactions.account_id`, or add an explicit owner column?

---

### 5 · P1 · `freshness.get_institution_freshness(owner_id=...)` raises `OperationalError`

**Source:** Side-finding from `dash_008` (which itself passed by falling back to the household call)
**Cause:** `aggregation_bug` (likely)

The function passes `column="id"` to `dal.owners.build_account_filter` but joins `accounts` with `balance_snapshots`/`portfolio_snapshots` (both have an `id` column). SQLite raises `OperationalError: ambiguous column name: id`. The owner-scoped freshness path is silently broken; the household path works.

**Fix location:**
- `dal.freshness.get_institution_freshness` — change `column="id"` to a fully-qualified column reference like `accounts.id` (mirror the pattern other DAL fns use). Read the function's source to confirm exact symbol path.

---

### 6 · P2 · `spec_gap` · Benchmark prices lag portfolio snapshots by 1 trading day

**Invariant:** `inv_008_benchmark_prices_complete` · **Page:** [InvestmentsOverview.tsx](frontend/src/pages/InvestmentsOverview.tsx)
**Cause:** `spec_gap`
**Numbers:** `portfolio_snapshots.max=2026-04-24`, `benchmark_prices.max=2026-04-23` (1-day lag).

Today (2026-04-24) is a Friday. The seeder fetches benchmark prices via `yfinance.download` ([scripts/dummy_data/generator.py](scripts/dummy_data/generator.py) `_fetch_and_cache_prices`, lines 865-956), which cannot return today's adjusted close until US markets settle. The seeder is fully aware of this gap — `_closest_price` (lines 997-1005) has a 5-day lookback, so today's snapshot uses yesterday's price by design.

UI impact: zero. [dal/investments.py:119](dal/investments.py:119) and [:206](dal/investments.py:206) both use `ORDER BY price_date DESC LIMIT 1`, picking up yesterday's price silently.

**Recommendation:** relax `inv_008` in `invariants.json` to allow trailing-edge gap of up to 1 trading day (or "up to today if US market hasn't settled"). No code change needed.

---

### 7 · P2 · `spec_gap` · Seeded portfolio drift vs live yfinance benchmarks

**Invariant:** `inv_010_seeded_drift_vs_benchmark_spec_gap` · **Page:** [InvestmentsOverview.tsx](frontend/src/pages/InvestmentsOverview.tsx)
**Cause:** `spec_gap` (documented in CLAUDE.md and orchestrator prompt)

Linear price drift in the seeder (VTI +1.5/mo, VXUS +0.3/mo, BND −0.1/mo) is bound to underperform the live yfinance S&P 500 benchmark. Cosmetic; not a bug. No action.

---

## 7. Verification of this audit

Per the plan's verification section:

- ✅ [`inventory.json`](inventory.json) parses, covers every numeric page in the orchestrator's table.
- ✅ [`invariants.json`](invariants.json) parses; all 82 invariants have `id`, `page`, `description`, `data_sources`, `tolerance`, `assigned_to`.
- ✅ Every `pass`/`fail` in the per-group `results-*.json` files has a non-empty `query_or_script` field. Spot-check ⊆ {dash_001, cf_004, xc_001, xc_011, inv_001} confirmed.
- ✅ Every `fail` and one of the two `could_not_verify` entries have a corresponding diagnostician entry with `fix_location` pointing at real files in the repo. The other CNV (inv_010) is an explicitly documented spec_gap requiring no further work.
- ✅ The punch list above has no "TBD" entries; every finding has fix locations and (where the diagnostician identified one) a `blocking_questions` payload.

## 8. Non-goals (per plan)

- Not fixing anything — punch list only.
- DB never modified. No seeder, no migration, no test runs.
- No dev-server start. UI claims verified via DAL recompute, not browser inspection.

---

*End of report. To work through the punch list: start at finding #1 and work down. Findings #1–4 are P0 (real numeric divergence users see); #5 is P1 (latent owner-scoped path broken); #6–7 are P2/spec_gap (documentation/invariant updates, no code fix).*
