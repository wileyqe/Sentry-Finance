# P13-T01: Investments — Strip to Shell

## Context

The investments feature was built up incrementally across Phases 3, 4,
5, 6, 8, and 10, and then hit by two trust-audit passes in early Phase
13 (`investments_trust_pass2.md`). The shape that resulted is a
912-line frontend page wired to five backend endpoints that read from
four DAL modules (holdings, allocation, performance, debt-vs-invest),
with a sixth endpoint in `reports.py` for the debt-vs-invest comparison
and parser-side writes inside `dal/parsers/tsp_statement.py`. The
accumulated design debt is hard to untangle incrementally.

Decision: rebuild ground-up. Only `extractors/` (institution
connectors) is preserved as a long-term asset. Everything else goes
in this task; data sources return one at a time in subsequent P13
tasks, starting with **Acorns Synthetic**.

After this task:

- The Investments tab renders an explicit empty state.
- The seeded dummy DB contains **zero** investment/retirement accounts,
  zero holdings, zero portfolio snapshots, zero ticker metadata, zero
  benchmark prices, zero positions-ledger rows.
- `dal/investments.py`, `dal/allocation.py`, and `dal/performance.py`
  are deleted. Connectors in `extractors/` still reference them and
  will fail at runtime if invoked — this is an accepted trade-off
  because dev mode is synthetic-only.
- Backend starts clean. The full pytest suite passes (minus the tests
  we deleted as part of the strip).

Branch: `investments-rebuild`, cut from `main` at commit `59c8e89`.
Does not merge to main until the rebuild is complete.

## Starting State

- `frontend/src/pages/InvestmentsPage.tsx` is 912 lines with 4 inline
  tabs and 6 endpoint calls.
- `backend/routers/investments.py` hosts five `/api/investments/*`
  routes plus two `/api/debt/*` routes.
- `backend/routers/reports.py` hosts `/api/analysis/debt-vs-invest`
  and its `options` companion.
- `dal/investments.py` owns holdings CRUD, Decimal precision, and
  Acorns portfolio backfill.
- `dal/allocation.py` owns sector / asset-class breakdown and
  yfinance metadata enrichment.
- `dal/performance.py` owns TWR math, benchmark fetching, and the
  Simple Dietz contributions-vs-performance decomposition.
- `dal/debt.py` hosts `compare_debt_payoff_vs_invest()` which lazy
  imports `dal.performance`.
- `dal/derived.py::recompute_net_worth()` has an investment branch
  that prefers `portfolio_snapshots` over `investment_holdings` over
  `balance_snapshots`.
- `dal/derived.py::recompute_for_institution()` has an Acorns-specific
  post-commit hook that calls `compute_acorns_portfolio_snapshots()`.
- `dal/yearly_wrapup.py` has two investment sections wired to
  `decompose_contributions_vs_performance`.
- `dal/scenarios.py` has `_get_historical_return()` which calls
  `get_all_accounts_performance()`.
- `dal/parsers/tsp_statement.py` has a **module-level** import of
  `upsert_holding` from `dal.investments`. This file is pulled in at
  backend startup via `dal/document_drop.py:11`, so deleting
  `dal.investments` without fixing this would break `uvicorn`.
- The seeder (`scripts/dummy_data/generator.py` and
  `scripts/seed_dummy_data.py`) generates three investment accounts
  (Vanguard Brokerage, Vanguard 401k Rollover, Greenleaf Invest),
  monthly holdings with deterministic linear-drift prices, monthly
  portfolio snapshots, ticker metadata for VTI/VXUS/BND, and paired
  auto-invest transfer transactions.
- Five test files touch the deleted modules:
  - `tests/test_investments_trust.py` — wholly dedicated
  - `tests/test_owner_scoping.py` — module-level imports + 2 tests
  - `tests/test_comprehensive.py` — 4 test functions
  - `tests/test_failure_modes.py` — 1 test function
  - `tests/test_phase6.py` — 1 test function

## Task

### 1. Delete DAL modules

- `dal/investments.py`
- `dal/allocation.py`
- `dal/performance.py`

### 2. Backend routers

- Rename `backend/routers/investments.py` to `backend/routers/debt.py`;
  rewrite as a ~50-line file containing only `/api/debt/summary` and
  `/api/debt/payoff`. Update `backend/api_server.py` to import `debt`
  instead of `investments` (35–44, 108).
- Remove the `holdings_value` enrichment (the
  `investment_holdings`-sourced subquery and its `holdings_map`
  merge) from `backend/routers/accounts.py`.
- Delete `@router.post("/api/analysis/debt-vs-invest")` and
  `@router.get("/api/analysis/debt-vs-invest/options")` from
  `backend/routers/reports.py`, along with the `DebtVsInvestRequest`
  pydantic model.

### 3. DAL cleanup to keep imports clean

- `dal/debt.py` — delete `compare_debt_payoff_vs_invest()`, leave a
  one-paragraph tombstone comment in its place.
- `dal/derived.py::recompute_net_worth()` — delete the investment
  branch entirely. Investment and retirement accounts contribute zero
  to net worth during the rebuild. Renumber the surviving section
  headers.
- `dal/derived.py::recompute_for_institution()` — delete the Acorns
  hook at the bottom of the function (it imported
  `compute_acorns_portfolio_snapshots` lazily).
- `dal/yearly_wrapup.py` — replace the two investment blocks with
  `investment_performance = []` and
  `contributions_vs_performance = []`. The surrounding wrap-up still
  includes the keys; consumers that iterated them get empty lists and
  continue to work.
- `dal/scenarios.py::_get_historical_return()` — collapse to a
  one-liner that returns `_DEFAULT_ANNUAL_RETURN`.
- `dal/parsers/tsp_statement.py` — remove both the
  `from dal.investments import upsert_holding` import and the
  `upsert_holding(...)` call inside `persist_to_db`. Also remove the
  `portfolio_snapshots` insert that lives next to it. The parser
  keeps extracting per-fund data and returning it in the result; the
  write path will be reconnected when the new investments read path
  exists.

### 4. Seeder strip

- `scripts/dummy_data/generator.py`
  - Remove the three investment account entries from `ACCOUNTS`
    (`vanguard_inv_5501`, `vanguard_ret_5502`, `greenleaf_inv_1001`).
  - Remove the Vanguard and Greenleaf auto-invest transfer pairs from
    `generate_transactions`.
  - Delete `_TICKER_BASKET`, `_TICKER_BASE_PRICE`,
    `_TICKER_MONTHLY_DRIFT`, `_TICKER_METADATA`,
    `generate_ticker_metadata()`, and `generate_investment_history()`.
  - Remove the `portfolio_by_acct` kwarg from
    `generate_balance_snapshots()` and strip the
    investment/retirement branch that bypassed the closure walk.
- `scripts/seed_dummy_data.py`
  - Delete `seed_investment_history()`, `seed_ticker_metadata()`, and
    `cleanup_orphaned_investment_accounts()`.
  - Delete the `portfolio_by_acct` pre-query inside
    `seed_balance_snapshots()`.
  - Delete the corresponding three calls from `main()`.
  - In `main()`, after `seed_transactions`, emit a block of targeted
    `DELETE` statements for every investment-surface table plus
    investment/retirement accounts. This is the "verify ALL gone"
    enforcement — even if some future code path tries to write to
    these tables, re-running the seed reasserts empty state.
- Delete `scripts/migrate_fidelity_to_db.py` (dead Phase 4 one-shot).

### 5. Frontend gut

Replace `frontend/src/pages/InvestmentsPage.tsx` with a ~30-line empty
state shell. Keep `useView()` wired so the owner chip in the header
stays consistent. Keep the route in `App.tsx`, the sidebar entry in
`Sidebar.tsx:11`, and the header page meta in `Header.tsx:10`.

### 6. Tests

- Delete `tests/test_investments_trust.py` entirely.
- `tests/test_owner_scoping.py` — remove the two module-level imports
  and gut the `get_allocation` / `get_all_accounts_performance`
  assertions from `test_empty_owner_no_leak`. Other owner-scoping
  tests are unchanged.
- `tests/test_comprehensive.py` — delete four investments test
  functions (decimal precision, upsert idempotency, portfolio total
  no-data, batch upsert) and their calls from `__main__`.
- `tests/test_failure_modes.py` — delete `test_decimal_precision`
  (section 3) and its call from `__main__`.
- `tests/test_phase6.py` — delete `test_contributions_vs_performance`
  and its call from `__main__`. The `test_yearly_wrapup_*` tests
  still pass because the wrap-up now returns empty lists for
  `investment_performance` / `contributions_vs_performance` and
  asserts only `isinstance(..., list)`.

### 7. Documentation

- This prompt file.
- `docs/ROADMAP.md` — add a Phase 13 section with an entry for this
  task (`[v]` on completion) and a placeholder for P13-T02.
- `docs/ARCHITECTURE.md` §4.2 — note that the investment schema is
  dormant during the rebuild.
- `docs/DUMMY_DATA_GENERATION_SPEC.md` — mark the investment sections
  dormant (the spec describes a generation shape that no longer
  exists).

## Verification

1. **Backend imports clean** —
   `python -c "from backend.api_server import app; print('OK')"`
   must print `OK` with no traceback.
2. **Seed runs clean** —
   `SENTRY_DB_PATH=data/dummy.db python scripts/seed_dummy_data.py`
   completes without a traceback and the summary shows zero rows for
   `investment_holdings` and `portfolio_snapshots`.
3. **Empty investments surface (SQL)** — with `sqlite3 data/dummy.db`,
   the counts for `accounts WHERE type IN ('investment','retirement')`,
   `investment_holdings`, `portfolio_snapshots`, `positions_ledger`,
   `ticker_metadata`, and `benchmark_prices` are all zero.
4. **Backend server** — starts clean on port 8000;
   `/api/accounts` returns no investment/retirement rows;
   `/api/investments/holdings` returns 404;
   `/api/debt/summary` still returns 200.
5. **Frontend shell** — `http://localhost:1420/investments` renders
   the icon + "Investments is being rebuilt" message; DevTools
   Network tab shows no `/api/investments/*` calls; sidebar entry is
   still clickable.
6. **Tests** — `pytest tests/ -x --tb=short` passes with zero
   failures. Expected: fewer tests collected than before.
7. **Idempotent re-seed** — running the seed a second time produces
   the same empty-investment state; no "row already exists" errors.

## Post-Implementation Notes

- Actual outcomes, surprises, and follow-ups go here after the work
  is verified. Fill this section in when marking P13-T01 `[v]` in
  `docs/ROADMAP.md`.
