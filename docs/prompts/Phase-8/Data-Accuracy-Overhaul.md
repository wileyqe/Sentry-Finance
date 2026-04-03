# Data Accuracy Overhaul — Full Pipeline Trust Fix

## Context

The app has a systemic data trust problem at every layer. Three deep audits
revealed issues far beyond display bugs:

1. **The dummy data pipeline and real data pipeline are completely different
   code paths.** Real data flows through `result_writer.py` → post-commit
   pipeline (categorization → reconciliation → derived metrics → alerts → goal
   sync). Dummy data bypasses ALL of this — raw SQL INSERTs, no enrichment, no
   reconciliation, no derived metrics. We're testing one path while shipping
   another.

2. **Category classification sets are duplicated across 10+ files** with active
   drift. "Loan Payments" is missing from most exclusion lists, causing it to
   appear as income. "Other Income" exists in `cash_flow.py` but not
   `reports.py`. Each module invents its own variant.

3. **The frontend fabricates data** — simulated S&P 500 benchmarks (portfolio ×
   0.9), fake tax lots, Math.abs() masking sign confusion.

4. **Investment data follows 3 different source-of-truth paths** that can
   disagree. Yearly Wrapup uses simple percentage change while the performance
   API uses TWR.

5. **Dummy data never calls yfinance.** Real Acorns/Fidelity connectors fetch
   live market prices. Dummy uses pre-generated deterministic interpolation. The
   enrichment paths are completely unexercised by dummy data.

6. **Transfer transactions are never reconciled in dummy data.** `transfer_tag`
   stays NULL. Queries that filter `WHERE transfer_tag IS NULL` will double-count
   every transfer pair.

---

## Core Principle

**Make the dummy data flow through the same pipeline as real data.** Don't
maintain two paths. The seeder should produce raw inputs that feed into
`result_writer.py` and `run_post_commit_pipeline()`, not bypass them.

---

## Phase 1: Single Source of Truth — Category Classifications ✅ DONE

**New file: `dal/category_classifications.py`**

All category sets defined once. Zero imports from other DAL modules.

```
INCOME_CATEGORIES           — what counts as income
EXCLUDED_FROM_SPEND         — transfers, debt service, refunds
                              (ADD "Loan Payments", "Mortgages")
ALL_EXCL_FROM_SPEND         — union of above
INCOME_EXCL_FROM_INC        — spending categories never counted as income
TRANSFER_CATEGORIES         — for reconciliation
LOAN_CATEGORIES             — for recurring/loan linking
EXCLUDED_FROM_CREEP         — lifestyle creep exclusions
EXCLUDED_FROM_FORECAST      — forecasting exclusions
NON_PROJECTION_INCOME       — tax refunds, non-recurring (forecasting)
```

**Updated consumer files** (local definitions deleted, import canonical):
`cash_flow.py`, `reports.py`, `derived.py`, `review.py`, `yearly_wrapup.py`,
`lifestyle.py`, `forecasting.py`, `merchant_normalizer.py`, `recurring.py`,
`reconciliation.py`, `transactions.py`

### Shared calculation utilities (in `category_classifications.py`):
- `savings_rate(income, spending) → float` — single formula
- `month_range(year, month) → (start_str, end_str)` — canonical month boundaries
- `prev_month(year, month) → (year, month)` — handles Jan→Dec rollover

**Status**: ✅ Complete. 94/94 backend tests passing.

---

## Phase 2: Unify the Data Pipeline — Seeder Uses Real Path

**Problem**: `seed_dummy_data.py` does direct `INSERT INTO transactions` (line
151), bypassing `result_writer.py`, `upsert_transactions()`, categorization,
reconciliation, and derived metrics.

**Fix**: Refactor the seeder to feed data through the real pipeline:

### 2a: Transaction seeding → route through `upsert_transactions()`

Replace the direct INSERT in `seed_transactions()` (line 136-158) with:
```python
from dal.transactions import upsert_transactions
txn_dicts = [...]  # build from JSON, same format as result_writer output
upsert_transactions(conn, txn_dicts)
```

This gets deduplication for free and uses the same schema contract.

### 2b: Fix direction enum

Seeder uses `"inflow"/"outflow"` (line 145). Real pipeline uses
`"Credit"/"Debit"` (result_writer.py line 75). Align the seeder to use
`"Credit"/"Debit"`.

### 2c: Run post-commit pipeline after seeding

After all transactions/balances are inserted, call the real pipeline per
institution:

```python
from backend.result_writer import run_post_commit_pipeline

for institution_id in seeded_institutions:
    run_post_commit_pipeline(institution_id)
```

This triggers:
- ✅ Categorization (`backfill_uncategorized`)
- ✅ Derived metrics (`recompute_for_institution`)
- ✅ Alerts (`evaluate_alerts`)
- ✅ Goal sync (`sync_goal_balances`)

### 2d: Run transfer reconciliation

The real post-commit pipeline does NOT currently call `reconcile_transfers()`.
This is a gap for BOTH paths. Add it to `run_post_commit_pipeline()`:

```python
# In result_writer.py:run_post_commit_pipeline(), after categorization:
from dal.reconciliation import reconcile_transfers
reconcile_transfers(conn, institution_id)
```

Now both real and dummy data get transfer tags. Queries filtering
`WHERE transfer_tag IS NULL` will correctly exclude transfer pairs.

**Status**: ✅ Complete. Seeder routes through `upsert_transactions()`, uses
Credit/Debit direction, runs full post-commit pipeline (categorization →
reconciliation → derived → alerts → goals), and backfills merchant names.
160 transfer pairs tagged, 85 derived summaries computed, 42 alerts fired.

---

## Phase 3: Fix Income/Expense Query Logic ✅ DONE (merged into Phase 1)

With Phase 1's updated `EXCLUDED_FROM_SPEND` (adding "Loan Payments",
"Mortgages") and canonical `INCOME_EXCL_FROM_INC`, the core calculation issues
are resolved.

### Specific fixes applied:
- reports.py `get_flow_data()` lines 576-583: replaced inline `income_excl`
  with canonical `INCOME_EXCL_FROM_INC`
- reports.py category trend lines 790-793: same replacement

**Status**: ✅ Complete.

---

## Phase 4: Fix Frontend Display Trust

### 4a: ReportsPage.tsx — Summary panel (P0)

**Lines 544-558**: Replace `Math.abs()` aggregation with sign-aware totals.
Show income total or spending total based on the active filter side, matching
what the Sankey and transaction list show.

### 4b: ReportsPage.tsx — Filter consistency (P0)

**Lines 500-532**: Make category dropdown and Sankey click-filter use the same
logic. When filtering by category, always apply the income/spending side
classification.

### 4c: InvestmentsPage.tsx — Honest labeling (P0)

**Benchmark cards** (lines 136-137, 152-160): Add "(Simulated)" to S&P 500, US
Stocks, US Bonds card titles. Add footnote: "Benchmark returns are estimated
approximations, not actual index data."

**Tax lots** (lines 556-575): Add header: "Estimated Tax Lots — actual lot data
not yet available" with visual distinction (muted border/text).

### 4d: Frontend Math.abs() cleanup (P1)

| File | Line | Fix |
|------|------|-----|
| DashboardPage.tsx | ~380 | Remove Math.abs() on spending (backend sends positive) |
| AccountsPage.tsx | ~119 | Raise split margin 1.0 → 10.0 |
| AccountsPage.tsx | ~419 | Remove Math.abs() on utilization |
| InvestmentsPage.tsx | ~417 | Use signed values in CVP chart bars |

**Status**: ✅ Complete. ReportsPage summary is sign-aware with dynamic
"Total income"/"Total spending" label. Tag filter bug fixed. Benchmark cards
labeled "(Est.)", footnote added. Tax lots labeled as estimated. DashboardPage
redundant Math.abs() removed.

---

## Phase 5: Investment Calculation Consistency

### 5a: Yearly Wrapup — wrong performance method

**File**: `dal/yearly_wrapup.py` lines 199-223

Replaced naive `(end/start - 1)` with call to existing
`decompose_contributions_vs_performance()` from `dal/performance.py` (which uses
proper Simple Dietz method with contribution decomposition).

### 5b: Document investment total priority

Added to `docs/ARCHITECTURE.md` under Investment tables section:
1. `portfolio_snapshots.total_account_value` (preferred)
2. `SUM(investment_holdings.market_value)` (fallback)
3. `balance_snapshots.balance` (last resort)

**Status**: ✅ Complete.

---

## Phase 6: Verification

### Backend
```bash
pytest tests/ -x --tb=short
```

### Re-seed with pipeline
```bash
SENTRY_DB_PATH=data/dummy.db python scripts/seed_dummy_data.py
```
Verify it now runs categorization, reconciliation, and derived metrics.

### SQL spot-checks
```sql
-- Transfers should be reconciled (transfer_tag NOT NULL)
SELECT COUNT(*) FROM transactions
WHERE category IN ('Transfers', 'Credit Card Payments')
  AND transfer_tag IS NOT NULL;

-- Loan payments should NOT appear in income reports
-- (verify via /api/reports/flow endpoint)

-- Derived metrics should exist
SELECT COUNT(*) FROM derived_summaries;
```

### Browser verification
1. Reports → All Time → "Loan Payments" NOT in income Sankey
2. Reports → click spending category → tag, summary, and list all agree
3. Cash Flow → Dec 2025 income doesn't include loan payments
4. Monthly Review income matches Cash Flow for same month
5. Investments → benchmark cards say "(Simulated)"
6. Investments → tax lots say "Estimated"
7. Dashboard net worth = Accounts page net worth

**Status**: ⬜ Not started.

---

## Audit Findings Summary (for reference)

### Category Classification Drift (10+ files had independent definitions)
| File | Had local sets | Now imports from |
|------|---------------|-----------------|
| `dal/cash_flow.py` | `_INCOME_CATEGORIES`, `_EXCLUDED_FROM_SPEND`, `_ALL_EXCL_FROM_SPEND`, `_INCOME_EXCL_FROM_INC` | `dal.category_classifications` |
| `dal/reports.py` | `_INCOME_CATEGORIES`, `_EXCLUDED_FROM_SPEND`, inline `income_excl` ×2 | `dal.category_classifications` |
| `dal/derived.py` | imported from `dal.reports` | `dal.category_classifications` |
| `dal/review.py` | imported from `dal.reports` + inline additions | `dal.category_classifications` |
| `dal/yearly_wrapup.py` | imported from both `dal.reports` and `dal.cash_flow` | `dal.category_classifications` |
| `dal/lifestyle.py` | `_EXCLUDED_FROM_CREEP` (frozenset), imported `_INCOME_CATEGORIES` from `dal.cash_flow` | `dal.category_classifications` |
| `dal/forecasting.py` | `_EXCLUDED_CATEGORIES`, `_NON_PROJECTION_INCOME_CATEGORIES` | `dal.category_classifications` |
| `dal/merchant_normalizer.py` | `_INCOME_CATS`, `_EXCLUDED` (4th copy!) | `dal.category_classifications` |
| `dal/recurring.py` | `_LOAN_CATEGORIES` | `dal.category_classifications` |
| `dal/reconciliation.py` | `_TRANSFER_CATEGORIES` | `dal.category_classifications` |
| `dal/transactions.py` | imported from `dal.reports` ×2 | `dal.category_classifications` |

### Frontend Fabrication Issues
| Issue | File | Lines | Severity |
|-------|------|-------|----------|
| Simulated benchmarks (portfolio × 0.9 etc.) shown unlabeled | InvestmentsPage.tsx | 136-137, 152-160 | P0 |
| Fabricated tax lots shown as real | InvestmentsPage.tsx | 556-575 | P0 |
| Math.abs() on summary totals masks sign confusion | ReportsPage.tsx | 544-558 | P0 |
| Category dropdown vs Sankey filter show different transactions | ReportsPage.tsx | 500-532 | P0 |
| Investment account split with $1 margin | AccountsPage.tsx | 119 | P1 |
| Math.abs() on spending display | DashboardPage.tsx | ~380 | P1 |

### Pipeline Divergence (Real vs Dummy)
| Pipeline Step | Real Path | Dummy Seeder |
|--------------|-----------|--------------|
| Transaction insert | `upsert_transactions()` with deduplication | Raw `INSERT INTO` |
| Direction enum | `"Credit"/"Debit"` | `"inflow"/"outflow"` |
| Categorization | `backfill_uncategorized()` | Pre-categorized in JSON |
| Transfer reconciliation | NOT called (gap in both paths) | Not called |
| Derived metrics | `recompute_for_institution()` | Skipped |
| Alerts | `evaluate_alerts()` | Skipped |
| Goal sync | `sync_goal_balances()` | Skipped |
| yfinance prices | Live fetch for Acorns/Fidelity | Pre-generated interpolation |

### Investment Calculation Inconsistencies
| Issue | Location | Severity |
|-------|----------|----------|
| 3 different sources for investment totals | accounts.py, allocation.py, derived.py | High |
| Simple % vs TWR for performance | yearly_wrapup.py vs performance.py | High |
| Acorns backfill assumes constant share counts | investments.py:337-448 | Medium |
| Holdings query uses per-ticker MAX(date) | allocation.py:225-240 | Medium |

---

## Files Modified

| File | Action |
|------|--------|
| `dal/category_classifications.py` | **NEW** — all category sets + calc utilities |
| `dal/cash_flow.py` | Remove local sets, import canonical |
| `dal/reports.py` | Remove local sets, fix inline income_excl |
| `dal/derived.py` | Update imports |
| `dal/review.py` | Update imports |
| `dal/yearly_wrapup.py` | Update imports, fix investment perf |
| `dal/lifestyle.py` | Update imports, fix month boundary bug |
| `dal/forecasting.py` | Update imports |
| `dal/merchant_normalizer.py` | Update imports |
| `dal/recurring.py` | Update imports |
| `dal/reconciliation.py` | Update imports |
| `dal/transactions.py` | Update imports |
| `backend/result_writer.py` | Add reconcile_transfers to post-commit pipeline |
| `scripts/seed_dummy_data.py` | Route through upsert_transactions + run_post_commit_pipeline |
| `frontend/src/pages/ReportsPage.tsx` | Fix summary Math.abs(), align filters |
| `frontend/src/pages/InvestmentsPage.tsx` | Add benchmark/tax lot disclaimers |
| `frontend/src/pages/AccountsPage.tsx` | Fix split margin |
| `frontend/src/pages/DashboardPage.tsx` | Remove Math.abs() |

## What This Does NOT Change

- No new migrations or schema changes
- No new API endpoints or page layouts
- Transaction data stays the same in the DB — the fix is in pipeline routing,
  classification, and display
- Real connector pipeline is already correct — we're making dummy match it
- yfinance integration unchanged — dummy data intentionally uses pre-generated
  prices (documenting this is part of the fix)
