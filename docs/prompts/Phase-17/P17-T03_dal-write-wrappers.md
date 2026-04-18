# P17-T03: DAL write wrappers for non-transactional tables

## Context

Phase 17 prepares the dummy → real-data cutover. The Phase-10 precedent
(`dal.transactions.upsert_transactions` + `_assert_sign_direction_invariant`)
made the transaction write path a single choke point shared by seeder
and live connectors: invariant-checked, fail-fast, deterministic.
Seven non-transactional tables still violated that shape today —
seeder and some connectors wrote them via raw SQL.

The tables: `balance_snapshots`, `investment_holdings`,
`portfolio_snapshots`, `credit_scores`, `loan_details`, `real_estate`,
`vehicle_valuations`.

Goal: every write to these tables flows through a DAL wrapper with a
consistent shape (caller-commits, ValueError on invariant violation),
so the cutover to real data is a no-op at the write layer — connectors
and seeder call the same functions.

## Starting State

**DAL wrappers inventory (pre-task):**

| Table | Wrapper function | Commit? | Return |
|---|---|---|---|
| balance_snapshots | `dal.balances.record_balance` | caller | None |
| loan_details | `dal.balances.record_loan_details` | caller | None |
| credit_scores | `dal.credit_scores.record_credit_score` | **internal** | bool |
| vehicle_valuations | `dal.vehicles.add_valuation` | **internal** | None |
| investment_holdings | *(none)* | — | — |
| portfolio_snapshots | *(none)* | — | — |
| real_estate | *(none)* | — | — |

**Bypassing wrappers (writing raw SQL):**

- `scripts/seed_dummy_data.py` — 5 seeder functions for
  balance_snapshots, loan_details, credit_scores, real_estate,
  vehicle_valuations (all 4 had wrappers; seeder bypassed them).
- `scripts/dummy_data/generator.py` — three `generate_*_investment_history`
  functions writing raw `conn.executemany` for `investment_holdings` and
  `portfolio_snapshots` (no wrappers existed).
- `extractors/acorns_connector.py:886` — raw `portfolio_snapshots` INSERT.
- `extractors/fidelity_connector.py:374` — raw `loan_details` INSERT
  (plus a **dead import** `from dal.derived import record_loan_details`
  that would `ImportError` if ever exercised; the raw INSERT was the
  actual write path).
- `extractors/tsp_connector.py:497–515` — raw `investment_holdings`
  + `portfolio_snapshots` INSERT.

**Golden-seed fingerprint (transactions-only, unaffected by this task):**
`a4ad2cd6f00f` at `end_date=2026-01-15, years=3`, 1854 txns
(`tests/test_golden_seed.py`).

## Task

Ten sequential steps (some mergeable):

1. Add `dal/real_estate.py` exposing `record_real_estate_valuations`
   with invariant guards (`estimated_value > 0`, parseable ISO date).
   Add `tests/test_dal_real_estate.py` (9 tests).
2. Add `dal/investments_writes.py` exposing
   `record_investment_holdings` (UNIQUE-index upsert),
   `record_portfolio_snapshots` (batch),
   `record_portfolio_snapshot` (single-row convenience).
   Invariants: non-negative shares/price/market_value; `|market_value
   − shares*close_price|` within 1¢ or 0.1% tolerance;
   `cash_balance ≤ total_account_value`.
   Add `tests/test_dal_investments_writes.py` (17 tests).
3. Harmonize existing wrappers. Remove internal `conn.commit()` from
   `record_credit_score`, `add_vehicle`, `add_valuation` so all
   wrappers follow the canonical caller-commits convention. Add
   invariants: FICO range `300 ≤ score ≤ 850` on `record_credit_score`,
   `estimated_value > 0` on `add_valuation`. Extend `add_vehicle` to
   accept optional `owner_id` (preserves existing on update via
   `COALESCE`). Add `tests/test_dal_harmonization.py` (8 tests
   including caller-commits regression guard).
4. Migrate `scripts/seed_dummy_data.py` five raw-SQL sites to call
   `record_balance`, `record_loan_details`, `record_credit_score`,
   `record_real_estate_valuations`, `add_vehicle`, `add_valuation`.
5. Migrate `scripts/dummy_data/generator.py` three
   `generate_*_investment_history` functions to call
   `record_portfolio_snapshots` and `record_investment_holdings`.
   `positions_ledger`, `tax_buckets`, `benchmark_prices` writes stay
   raw (explicit non-goal).
6. Migrate `extractors/acorns_connector.py:886` to
   `record_portfolio_snapshot`.
7. Migrate `extractors/fidelity_connector.py:353, 374` — fix the dead
   `dal.derived` import (→ `dal.balances`) and route through
   `record_loan_details`.
8. Migrate `extractors/tsp_connector.py` holdings + snapshot writes.
   Preserve the DELETE-before-INSERT at the call site (prevents
   duplicate rows when the same day is re-scraped).
9. Add `conn.commit()` after `record_credit_score` calls in
   `extractors/chase_connector.py` and `extractors/nfcu_connector.py`
   — without this, the commit-removal in step 3 silently drops
   scraped scores. (Bundled into the step-3 commit.)
10. Author this prompt file; update `ROADMAP.md` (flip item 3 to
    `[v]`); add a one-paragraph note to `ARCHITECTURE.md`.

## Verification

**Full backend test suite — 246 tests, all pass.** Includes:

- `tests/test_dal_real_estate.py` (9) — new wrapper invariants.
- `tests/test_dal_investments_writes.py` (17) — new wrapper invariants
  + UNIQUE upsert behavior.
- `tests/test_dal_harmonization.py` (8) — invariants on the existing
  four wrappers plus caller-commits regression guards (use a second
  connection to assert the wrapper didn't persist without an explicit
  `commit`).
- `tests/test_dal.py` (15) — pre-existing `record_balance` /
  `record_loan_details` coverage, unmoved.
- `tests/test_golden_seed.py` (11) — transactions fingerprint
  `a4ad2cd6f00f` still matches.

**Seed-parity check.** Ran the seeder at
`--end-date 2026-01-15 --years 3` on both pre- and post-migration code
and compared table-by-table hashes (excluding volatile
`created_at`/`as_of` columns that move with wall-clock time):

| Table | Pre vs post |
|---|---|
| `balance_snapshots` | **byte-identical** |
| `credit_scores` | **byte-identical** |
| `loan_details` | **byte-identical** |
| `real_estate` | **byte-identical** |
| `vehicle_valuations` | **byte-identical** |
| `investment_holdings` | drifts at 1e-5 price precision |
| `portfolio_snapshots` | drifts at ±1¢ notional |

The two drifting tables were also compared between two post-migration
seeds — those also drifted. Root cause: `scripts/seed_dummy_data.py`
wipes `benchmark_prices` on every run (line 739) and re-fetches from
yFinance, which returns float32 values that vary at ~1e-5 precision
between API calls for the same ticker+date. This non-determinism is
**pre-existing and unrelated to this task** — the seeder has behaved
this way since Phase 13 introduced the yFinance cache wipe.

**Ruff check.** All new DAL/test files pass `ruff check`. Remaining
violations in modified connector files are pre-existing in code this
task did not touch.

**Pre-existing issues discovered (not in scope):**

- **Seeder integrity check failure on main.** Running
  `scripts/seed_dummy_data.py` exits with `RuntimeError: liability
  account has positive balance` — 7 balance rows from 2023 for
  `summit_cc_3341` / `coastal_cc_8847` with small positive balances.
  Exists on `main` before any Phase-17 work; the seeded data is
  otherwise complete. Reported as a follow-up; does not block parity
  verification.

## Follow-ups (deferred)

- **Pure-function refactor of `generate_*_investment_history`.** They
  still take `conn` and write during generation. Phase-10 pattern is
  return-lists. Requires also wrapping `positions_ledger` /
  `tax_buckets` which were explicit non-goals here.
- **Harmonize return shapes.** `record_credit_score` returns bool,
  `add_valuation` returns None, new wrappers return dicts. Low-value
  churn; defer.
- **Extend `tests/test_golden_seed.py`** to fingerprint the
  non-transactional tables. Requires resolving the yFinance
  non-determinism first (pin prices, or skip cache wipe in
  deterministic mode).
- **DAL wrappers for remaining non-transactional tables**
  (`positions_ledger`, `tax_buckets`, `benchmark_prices`,
  `payroll_snapshots`, `document_drops`). Not in the Phase-17 roadmap
  text.
- **Pre-existing seeder integrity failure** (summit/coastal stale
  rows). Investigate and fix on its own commit.
