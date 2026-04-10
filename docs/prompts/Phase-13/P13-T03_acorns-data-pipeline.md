# P13-T03: Acorns Data Pipeline — End-to-End

## Context

P13-T02 shipped the "Acorns Synthetic" account (`acorns_synthetic_0000`)
as a shell with $0 balance. The investments rebuild now needs its first
real data flow: money moving from checking to Acorns, shares being
purchased, and the pipeline that ties those two sides together.

Acorns is a unique data source because it doesn't offer a transaction
feed. Data arrives from three places with different timing and precision:

1. **Bank scraping** — captures debits leaving checking: recurring
   transfer (~$350/mo), roundups (~10/mo at $5-$12), monthly fee ($1-$3).
2. **Acorns web scraping** — captures total portfolio value and per-ETF
   share counts (VOO, IJH, IJR, IXUS) via delta-logging.
3. **Monthly statement PDF** — backfills precise purchase dates, per-ETF
   share quantities, and actual prices (available ~16th of following month).

A fourth source ("Acorns Earned" vendor kickbacks) is invisible to the
bank and stays lumped into regular IMPLIED_BUY entries — not worth
distinguishing at $1-$5/occurrence.

## Starting State

- Branch `investments-rebuild` at commit `434ea37`
- Acorns connector exists and works: login, scrape, delta-log, yFinance
  enrichment (`extractors/acorns_connector.py`)
- Statement PDF parser exists as standalone script
  (`scripts/parse_acorns_pdf.py`)
- 1099 parser in document drop pipeline (`dal/parsers/acorns_1099.py`)
- Reconciliation includes "acorns" in transfer keywords
- `positions_ledger`, `portfolio_snapshots`, `investment_holdings` tables
  exist with V4 decimal precision columns
- Investment seeding removed in P13-T01 (generator.py lines 726-732)
- `dal/performance.py` removed, TWR not computed
- Post-commit Acorns hook removed in P13-T01

## Key Design Decisions

1. **Fee = real expense.** The $1-$3 monthly Acorns fee stays in spending
   metrics. Transfers and roundups are excluded as investment contributions.
2. **No estimated/confirmed UI badges.** Internal `source` column tracks
   provenance (scraper/statement/seeder) but this is not surfaced to the
   user — data is always approximate until the statement arrives.
3. **No Acorns Earned distinction.** Small vendor kickback amounts stay
   lumped into regular IMPLIED_BUY entries.
4. **`transfer_tag = "invest:{ledger_id}"`** marks bank-side Acorns debits
   as investment contributions, excluded from spending without needing a
   phantom credit transaction.
5. **Date-anchored yFinance prices.** Use closing price on bank debit date
   (calibrated against real statements) instead of scrape-day price.
6. **Statement auto-download.** Acorns connector downloads statements when
   date >= 16th and last month's statement is unprocessed. Document drop
   as manual fallback.
7. **Weekly portfolio snapshots in seeder** (not monthly) for smoother
   charting. Per-transaction positions_ledger entries.

## Task

### Migration v24
Add columns: `positions_ledger.source`, `positions_ledger.bank_txn_id`,
`transactions.investment_link`.

### Seeder
- Bank-side: Acorns transfer, roundup, and fee transactions from checking
- Investment-side: per-debit positions_ledger entries with yFinance prices,
  weekly portfolio_snapshots, `transfer_tag` linkage

### DAL + API
- `dal/investments.py` — read functions for holdings, activity, performance
- `backend/routers/investments.py` — three endpoints

### Statement Parser
- `dal/parsers/acorns_statement.py` — document drop integration
- Refactor shared logic from `scripts/parse_acorns_pdf.py`

### Post-commit Pipeline
- Transfer matching (bank debits ↔ positions_ledger)
- Benchmark price cache refresh
- Derived metrics hook rewiring

## Verification

1. Seed round-trip: `python scripts/seed_dummy_data.py` then query
   `positions_ledger` for 3 years of entries with `bank_txn_id` linkage
2. API smoke test: hit holdings/activity/performance endpoints
3. Spending exclusion: cash flow query excludes Acorns transfers
4. Full test suite: `pytest tests/ -x --tb=short`
