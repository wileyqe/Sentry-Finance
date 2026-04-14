# P13-T07: Data Provenance --- Real vs Synthetic Differentiation

## Context

During development, real connectors (TSP, future Amy accounts) run alongside
the synthetic seeder.  Once pipeline testing is complete the patterns are
modelled into the seeder and the DB is re-seeded to a clean synthetic state.
In the interim, real and synthetic data coexist with no reliable way to tell
them apart at a glance.

The user discovered they could not tell whether TSP data in the app was real
or synthetic.  (Answer: TSP is NOT in the synthetic seeder --- if `tsp_7777`
data exists, it came from the real connector or a document drop.)

Pre-existing ad-hoc markers:
- `institutions.extraction_method = 'dummy'`
- Transaction ID prefix `dummy_*`
- `refresh_run_id = 'dummy_seed'` on balance_snapshots / loan_details
- `positions_ledger.source = 'seeder'`

None of these are queryable from a single, consistent field across all levels.

## Starting State

- No `is_synthetic` column on institutions or accounts
- Seeder identifies its own data by institution/account ID membership
- Stale-institutions scrub (`seed_dummy_data.py:161-174`) deletes everything
  NOT in the canonical synthetic set --- intentional (returns DB to known
  synthetic state), but implicit
- Frontend has no visual indicator for data provenance

## Task

1. **Migration v26** (`dal/migrations/v26_data_provenance.py`)
   - Add `is_synthetic INTEGER DEFAULT 0` to `institutions` and `accounts`
   - Backfill from existing `extraction_method = 'dummy'` marker

2. **Seeder** (`scripts/seed_dummy_data.py`)
   - Set `is_synthetic = 1` on institution and account INSERTs
   - Refine stale-institutions scrub to use `is_synthetic` for clarity:
     - Delete stale synthetic institutions not in canonical set
     - Delete real institutions that crept in during pipeline testing
   - Same net effect (clean synthetic state after re-seed), but
     self-documenting

3. **DAL + API**
   - Include `is_synthetic` in accounts SELECT (`backend/routers/accounts.py`)
   - Include `a.is_synthetic` in investment queries (`dal/investments.py`)
   - Add `show_synthetic_data` to settings valid keys

4. **Frontend**
   - `SyntheticBadge` component (violet pill, compact variant for tables)
   - Wired into: AccountsPage account rows, TransactionsPage account column,
     InvestmentsHoldings account column, InvestmentsPage account filter
   - Settings toggle: "Show Synthetic Data" under new "Data Sources" section
   - `AccountInfo` type updated with `is_synthetic` field

## Verification

- [ ] Migration applies cleanly: `python -c "from dal.database import init_db; init_db()"`
- [ ] Re-seed marks synthetic data: `python scripts/seed_dummy_data.py` then
      verify `SELECT is_synthetic FROM institutions WHERE extraction_method = 'dummy'`
      all return 1
- [ ] Real institutions retain `is_synthetic = 0` after re-seed
- [ ] `pytest tests/ -x --tb=short` passes
- [ ] `cd frontend && npm run build` succeeds
- [ ] Visual: synthetic accounts show violet "Demo" badge
- [ ] Visual: TSP (real) account has no badge
- [ ] Settings toggle renders and persists

## Outcome

Badge renders correctly on synthetic accounts across accounts, transactions,
and investment pages.  Settings toggle persists.  The seeder scrub now uses
`is_synthetic` for explicit provenance-based cleanup.

The `is_synthetic` flag follows the same architectural pattern as `owner_id`:
defined on accounts, threaded through queries via FK joins.  Child tables
(transactions, balances, holdings) inherit provenance from their parent
account --- no per-row column needed.
