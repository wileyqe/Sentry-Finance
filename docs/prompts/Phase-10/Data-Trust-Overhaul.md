# Phase 10 — Data Trust Overhaul

**Status:** Complete (awaiting user acceptance + commit)
**Started:** 2026-04-06
**Type:** Multi-phase backend + tests + docs (no frontend changes)

## The Problem (in the user's words)

> "On the Cash Flow page the top-of-page graphs don't match the drill-down
> numbers when I click a period. Trust in the system is paramount."

And:

> "I want round numbers I can verify by hand. And the dummy data is frozen
> to a stale calendar range — make the seeder roll forward so the dev UI
> always feels like 'today'."

## Diagnosis

Three parallel investigations confirmed:

1. **The cash-flow mismatch is an accounting-logic bug, not a data bug.**
   The top-graph SQL and drill-down SQL inside `dal/cash_flow.py` were
   written in two passes using different classification styles
   (whitelist vs. blacklist) and different sign-handling rules. They
   legitimately compute different numbers for the same date range.
   Wiping the database would not fix it.

2. **The ingestion pipeline itself is healthy.** Both the synthetic seeder
   and live institution connectors route transactions through
   `dal.transactions.upsert_transactions()` and run the same post-commit
   pipeline. Sign convention (`signed_amount`: debits negative, credits
   positive) is canonical across 90% of the DAL but two regressions
   existed in `budgets.py` and `goals.py`.

3. **The frozen JSON fixtures under `dummy_data/` don't roll forward** —
   the seeder loaded them verbatim, so the dev UI always looked stale
   after the dataset's last calendar date.

## Confirmed bugs (with line references)

### `dal/cash_flow.py`
1. `get_yearly_cash_flow()` referenced `owner_id` without declaring it in
   the signature → `NameError` on any owner-filtered yearly query.
2. Top-graph income used **whitelist** `category IN INCOME_CATEGORIES`;
   drill-down used **blacklist** `category NOT IN INCOME_EXCL_FROM_INC`.
3. Top-graph spending had **no `signed_amount < 0` check** → grocery
   refunds (positive amount in a spending category) silently subtracted
   from the spending total.
4. `get_available_years()` did not apply owner/account scoping.

### `dal/category_classifications.py`
5. `"Deposits"` was in `INCOME_EXCL_FROM_INC` but is an income catch-all,
   not a spending refund category. Belongs only in `INCOME_CATEGORIES`.

### `dal/budgets.py` and `dal/goals.py`
6. `budgets.py` used legacy `SUM(CASE WHEN direction='Debit' THEN amount …)`
   pattern instead of `signed_amount` — disagrees with cash_flow.py for
   any category with refunds.
7. `goals.py` used mixed convention: income via `signed_amount`, spending
   via `direction + amount`. Inconsistent within a single query.

### `dal/transactions.py`
8. No invariant assertion that
   `(signed_amount < 0) ⟺ (direction='Debit')` and
   `(signed_amount > 0) ⟺ (direction='Credit')`. Silent drift possible.

## Decisions locked in

- **Canonical SQL pattern:** blacklist + sign-check (drill-down style).
  Both top-graph and drill-down use:
  ```sql
  income   = SUM(CASE WHEN signed_amount > 0
                       AND transfer_tag IS NULL
                       AND COALESCE(category,'Other Income') NOT IN <INCOME_EXCL_FROM_INC>
                      THEN signed_amount ELSE 0 END)
  spending = SUM(CASE WHEN signed_amount < 0
                       AND transfer_tag IS NULL
                       AND COALESCE(category,'Uncategorized') NOT IN <ALL_EXCL_FROM_SPEND>
                      THEN -signed_amount ELSE 0 END)
  ```
- **Rolling end-date:** `scripts/seed_dummy_data.py` generates all
  transactional history relative to `end_date = date.today() - 1 day`.
  Override via `--end-date YYYY-MM-DD` for reproducibility.
- **Hard end, soft start.** Walk back `--years 3` (default) from end_date.
- **Determinism.** RNG seeded from `int(end_date.strftime("%Y%m%d"))` so
  the same end-date produces the same dataset byte-for-byte.
- **Round numbers only.** All amounts drawn from fixed tiers; no arbitrary
  floats. Every total computable by hand.
- **Single command.** `scripts/seed_dummy_data.py` stays the only entry
  point; CLI gains `--end-date` and `--years` flags.

## Phases (single session)

### Phase A — Accounting correctness ✅
- Fixed `get_yearly_cash_flow()` signature.
- Rewrote all 5 cash_flow.py aggregates (monthly, quarterly, yearly,
  monthly-rolling, quarterly-rolling) to use the canonical pattern.
- Added owner scoping to `get_available_years()`.
- Removed `"Deposits"` from `INCOME_EXCL_FROM_INC`; updated docstring.
- Fixed `dal/budgets.py` to use canonical signed_amount pattern.
- Fixed `dal/goals.py` to use canonical pattern with `transfer_tag IS NULL`.
- Added `_assert_sign_direction_invariant()` choke point in
  `dal/transactions.py:upsert_transactions()`.

### Phase B — Rolling generative seeder ✅
- Created `scripts/dummy_data/__init__.py` and
  `scripts/dummy_data/generator.py` with pure-function generators for
  transactions, balance snapshots, budgets, credit scores, investment
  holdings, portfolio snapshots, and payroll snapshots.
- Rewired `scripts/seed_dummy_data.py` to call the generators, preserve
  the upsert path through `dal.transactions.upsert_transactions()`, and
  run `run_post_commit_pipeline()` per institution.
- Added `--end-date YYYY-MM-DD` and `--years N` CLI flags.
- Deleted (via `git rm`) the stale time-series JSON fixtures:
  `transactions.json`, `transactions_dense.json`, `balance_snapshots.json`,
  `budgets.json`, `credit_scores.json`, `Investment_holdings.json`,
  `portfolio_snapshots.json`, `vehicle_valuations.json`.
- Kept structural fixtures (owners, institutions, recurring patterns,
  savings goals, real estate, vehicles, loans) as static JSON.

### Phase C — Invariants test suite ✅
- `tests/test_cashflow_invariants.py` — 12 tests, hand-built ~30-txn
  fixture covering paychecks, rent, refund pairs, deposits, transfers,
  multi-owner data. Tests 1–5 assert top-graph totals exactly equal
  drill-down totals at every granularity.
- `tests/test_transaction_invariants.py` — 5 tests covering the new
  sign/direction invariant choke point.
- `tests/test_golden_seed.py` — 11 tests using pinned `end_date=2026-01-15`
  with deterministic fingerprint check, year-by-year category totals,
  closure property between balance snapshots and signed_amount sums.

### Phase D — Docs, skills, roadmap ✅
- `docs/ARCHITECTURE.md`: added §4.6 Sign Convention with the canonical
  pattern, plus a Dummy Data Generation subsection in the Scripts module
  map describing the rolling end-date design.
- `CLAUDE.md`: added a guardrail line forbidding the legacy
  `direction + amount` pattern.
- `docs/prompts/Phase-10/Data-Trust-Overhaul.md` (this file): durable
  record of diagnosis, decisions, results.
- `.claude/skills/dev-server/SKILL.md`: updated Step 2 (seed dummy data)
  to reflect the rolling generator and document `--end-date` / `--years`
  overrides.
- `.claude/skills/dev-stop/SKILL.md`: reviewed and updated as needed.
- `docs/ROADMAP.md`: added Phase 10 entry plus a Deferred/Backlog section
  with explicit entries for every out-of-scope item.

## Verification results

### Phase A gate ✅
- `pytest tests/test_dal.py tests/test_comprehensive.py
  tests/test_reconciliation.py tests/test_phase6.py -x --tb=short` —
  all green.
- `ruff check backend dal extractors tests` — clean.

### Phase B gate ✅
- `SENTRY_DB_PATH=data/dummy.db python scripts/seed_dummy_data.py` —
  ~1577 txns/year for 3 years, post-commit pipeline green for every
  institution, no errors.
- Re-run with pinned `--end-date 2026-01-15 --years 3` produced
  byte-identical output (fingerprint `37581d9944c4`).

### Phase C gate ✅
- 28/28 new Phase 10 tests passing.
- 122/122 targeted backend tests passing.
- Full backend suite: 186 passing, 5 pre-existing time-of-test failures
  (verified unrelated via `git stash` round-trip on pre-Phase-10 state).
- `ruff check` clean on all Phase 10 files.
- Frontend build clean (1942.80 kB, 23.96s).

### Phase D gate
- ARCHITECTURE.md, CLAUDE.md, prompts file, skills, ROADMAP all updated.
- Final manual verification (dev server + Cash Flow click-through) is the
  remaining acceptance step before commit.

## Out of scope (tracked in ROADMAP.md Deferred/Backlog)

1. DAL write wrappers for non-transactional tables
   (`balance_snapshots`, `investment_holdings`, `portfolio_snapshots`,
   `credit_scores`, `loan_details`, `real_estate`, `vehicle_valuations`)
2. Reconciliation hardening (FX, multi-day clearing windows > 3 days,
   partial/fee-adjusted matches)
3. Extractor changes touching the sign/direction convention
4. Frontend refactors beyond verifying behavior
5. Destructive data wipe tooling (`scripts/wipe_data.py`)
6. The 5 pre-existing time-of-test failures
   (`tests/test_t02t03t04.py`, `tests/test_t05.py`) — fixtures use
   2025-2026 dates that fall outside their rolling windows when run on
   real today; should be re-anchored using the same `--end-date`
   philosophy from Phase 10.

## Lessons / forward guidance

- **Two SQL patterns will always drift.** The blacklist + sign-check
  pattern is documented in ARCHITECTURE.md §4.6 and protected by
  `tests/test_cashflow_invariants.py`. Anyone introducing a new aggregate
  must use it.
- **The single choke point in `upsert_transactions()` is load-bearing.**
  Both the dummy seeder and live connectors write through it. The new
  invariant assertion converts silent sign drift into a `ValueError` with
  enough context to locate the bad row.
- **Rolling generators beat frozen fixtures for dev UX.** Re-running
  `seed_dummy_data.py` any day rolls the dataset window forward; pinning
  `--end-date` keeps tests reproducible. Both audiences served by the
  same code path.
- **Round-number tier amounts make hand-auditing possible.** This is the
  property that lets us trust the dataset without having to read the
  generator source.
