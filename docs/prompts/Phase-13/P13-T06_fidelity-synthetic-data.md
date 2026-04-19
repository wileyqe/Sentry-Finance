# P13-T06: Fidelity Synthetic Data Pipeline

## Context

The investments rebuild needs its second data source. Acorns (T03) proved
the pipeline works for automated micro-investing with 4 ETFs. Fidelity is
fundamentally different: individual equities, manual buy/sell decisions,
dividends, reinvestments, cost basis tracking, and a cash position (SPAXX).
It's the account that makes the Investments page feel like a real portfolio
tool.

This task builds the synthetic data generator for Fidelity — everything
except the real connector. The data structures, DB writes, and pipeline
flow must be identical to what the production `fidelity_connector.py` +
`ingest_fidelity_history.py` will produce, so that wiring the real
connector later is just swapping the data source.

### Why Fidelity matters for the UI

- **Holdings tab:** Only source of individual stocks (Acorns has 4 ETFs).
  Fidelity adds 8 tickers with diverse sectors → makes the Holdings table
  and sort/filter feel real.
- **Allocation tab:** Individual stocks have known sectors → sector
  exposure bars show real data instead of approximations. Treemap shows
  individual-stock concentration alongside ETF positions.
- **Tax lots:** Fidelity buys are explicit transactions with dates and
  prices → each BUY row is a tax lot. Expandable lot detail works with
  real data.
- **Cash position:** SPAXX shows as "Cash / Equivalents" across all
  visualizations — donut, treemap, portfolio composition. Surfaces how
  much dry powder is sitting idle.
- **Dividends:** History CSV captures every dividend payment → enables
  dividend contribution to total return (surfacing TBD, but data must be
  there).

## Starting State

- Branch `investments-rebuild` at latest commit
- Acorns Synthetic pipeline works end-to-end (T03, T04)
- Frontend skeleton with 3 tabs built (T05) — using inline mock data
- Fidelity account `fidelity_XXXX` exists in DB, type=investment, zero data
- Real Fidelity connector exists: `extractors/fidelity_connector.py` (479 lines)
- Real Fidelity ingest exists: `scripts/ingest_fidelity_history.py` (660 lines)
- Real CSVs in `raw_exports/fidelity/` (3 years of history, 18 real holdings)
- `investment_holdings` table exists (V03) but is currently empty
- `ticker_metadata` table exists (V10) but is currently empty

## Architecture: Three-Layer Data Model

| Table | Role | Granularity |
|-------|------|-------------|
| `positions_ledger` | Transaction log — what happened | Per-event (buy/sell/dividend) |
| `investment_holdings` | Daily snapshot — what was held | Per-ticker per-day |
| `portfolio_snapshots` | Headline number — total value | Per-account per-day |

All three are written by the same function in a single pass. The ledger is
source of truth; snapshots are materialized views of ledger state.

## Task

### Step 1: Migration — extend `positions_ledger`

New migration (next sequential number) adding 5 columns:

```sql
ALTER TABLE positions_ledger ADD COLUMN cost_basis_dec TEXT;
ALTER TABLE positions_ledger ADD COLUMN realized_gain_dec TEXT;
ALTER TABLE positions_ledger ADD COLUMN settlement_date TEXT;
ALTER TABLE positions_ledger ADD COLUMN commission_dec TEXT;
ALTER TABLE positions_ledger ADD COLUMN fees_dec TEXT;
```

These support:
- `cost_basis_dec` — what was paid for the shares in a BUY entry (qty × price + fees)
- `realized_gain_dec` — gain/loss on SELL entries (proceeds − FIFO cost basis)
- `settlement_date` — T+1 settlement, relevant for wash sale tracking
- `commission_dec`, `fees_dec` — part of IRS cost basis calculation

### Step 2: Synthetic Fidelity data generator

Add `generate_fidelity_investment_history()` to `scripts/dummy_data/generator.py`.

**Tickers (8 — representative subset):**
```python
_FIDELITY_TICKERS = {
    "AAPL": {"sector": "Technology",           "cap": "Large Cap"},
    "MSFT": {"sector": "Technology",           "cap": "Large Cap"},
    "AMZN": {"sector": "Consumer Discretionary","cap": "Large Cap"},
    "GOOG": {"sector": "Communication Services","cap": "Large Cap"},
    "SPG":  {"sector": "Real Estate",          "cap": "Large Cap"},
    "QQQM": {"sector": "Technology",           "cap": "Large Cap", "type": "ETF"},
    "TGT":  {"sector": "Consumer Staples",     "cap": "Mid Cap"},
    "SBUX": {"sector": "Consumer Discretionary","cap": "Large Cap"},
}
```

**Transaction pattern (3-year window):**
- Monthly deposits: $500 EFT on ~1st of month (`transaction_type = 'DEPOSIT'`)
- Monthly buys: 2-3 stocks per month, rotating through tickers
  - Whole shares preferred, occasional fractional for QQQM
  - Buy amounts $150-$400 per stock
  - `transaction_type = 'BUY'`
  - `cost_basis_dec = qty × price + commission + fees`
  - `settlement_date = trade_date + 1 business day`
- Quarterly dividends: AAPL, MSFT, SPG, TGT, SBUX
  - Use approximate real ex-dates (quarterly cadence)
  - `transaction_type = 'DIVIDEND'` (cash received)
  - Some reinvested: `transaction_type = 'REINVESTMENT'` (shares bought)
- Occasional sells: 2-3 per year (position trimming)
  - `transaction_type = 'SELL'`
  - FIFO lot matching to compute `realized_gain_dec`
  - `share_delta` is negative
- SPAXX cash: residual cash after buys
  - Track as `cash_balance` in portfolio_snapshots

**Price data:** Use `_fetch_and_cache_prices()` (same as Acorns) to get
real yfinance closing prices. Fall back to `_fallback_linear_prices()` if
yfinance unavailable.

**Output — positions_ledger entries:**
```python
{
    "account_id": "fidelity_XXXX",
    "timestamp": "2024-01-15T10:30:00",
    "ticker": "AAPL",
    "transaction_type": "BUY",
    "share_delta": 2.0,
    "new_total_shares": 5.0,
    "yfinance_closing_price": 185.50,
    "estimated_transaction_value": 371.00,
    "source": "seeder",
    "bank_txn_id": None,       # Fidelity deposits aren't linked to external bank txns
    "cost_basis_dec": "371.00",
    "realized_gain_dec": None,  # only for SELL
    "settlement_date": "2024-01-16",
    "commission_dec": "0.00",
    "fees_dec": "0.00",
    # + decimal variants for shares/price
}
```

### Step 3: Snapshot generation

After all positions_ledger entries are written:

1. Walk each calendar day from `start_date` to `end_date`
2. For each day, compute per-ticker state from the ledger:
   - `shares` = running total from last positions_ledger entry on or before this date
   - `close_price` = from benchmark_prices (closest date)
   - `market_value` = shares × close_price
   - `cost_basis` = sum of `cost_basis_dec` from all unsold BUY lots (FIFO)
3. Write `investment_holdings` rows — one per ticker per day
   (sample every ~2 days for efficiency; weekly for dates > 6 months old)
4. Write `portfolio_snapshots` row — sum of all holdings + SPAXX cash balance

### Step 4: Ticker metadata enrichment

Add `enrich_ticker_metadata()` to generator.py:

```python
def enrich_ticker_metadata(conn, tickers: list[str]) -> int:
    """Fetch sector/industry/asset_class from yfinance, cache in ticker_metadata."""
```

- Check `last_updated` — skip if < 30 days old
- For each ticker: `yf.Ticker(symbol).info` → `sector`, `industry`, `quoteType`
- Map `quoteType`: EQUITY → "Equity", ETF → "ETF"
- INSERT OR REPLACE into `ticker_metadata`
- Call for both Acorns tickers (VOO, IJH, IJR, IXUS) and Fidelity tickers

### Step 5: Wire into seed_dummy_data.py

- Call `generate_fidelity_investment_history()` after `seed_acorns_investments()`
- Call `enrich_ticker_metadata()` for all distinct tickers
- Clear `investment_holdings` for `fidelity_XXXX` before re-seeding (idempotent)
- Fidelity flows through `run_post_commit_pipeline("fidelity")` like all institutions

### Step 6: DAL enhancements

**Enhance `get_holdings()` (dal/investments.py):**
- Read from `investment_holdings` (latest date) instead of aggregating positions_ledger
- Include `cost_basis`, `total_gain_loss`, `gain_loss_pct` per holding
- Separate `cash_balance` (SPAXX/FDRXX entries) from equity holdings
- `CASH_EQUIVALENTS = {"SPAXX", "FDRXX"}` — partition at the DAL level

**Add `get_lots(conn, account_id, ticker)`:**
- Read BUY/REINVESTMENT/INITIAL_BASELINE/IMPLIED_BUY entries from positions_ledger
- Compute current value per lot from latest benchmark_prices
- Return: date, quantity, cost_basis, current_value, gain_loss, holding_period_days

**Add `get_allocation(conn, owner_id)`:**
- Aggregate across all investment accounts
- Join ticker_metadata for sector, industry, asset_class
- Return: `by_asset_class`, `by_sector`, `by_geography`, `by_market_cap`
- Handle CASH_EQUIVALENTS as their own asset class

**Enhance `get_performance()`:**
- Support adaptive granularity based on date range requested
- Read from `investment_holdings` for daily/every-2-day resolution (1D–3M)
- Read from `portfolio_snapshots` for weekly resolution (6M–1Y)
- Aggregate from snapshots for monthly resolution (All)

### Step 7: Router enhancements

**Enhance `GET /api/investments/holdings`:**
Add `cost_basis`, `total_gain_loss`, `gain_loss_pct`, `sector`, `asset_class`
to each holding. Add `cash_balance` to each account.

**Add `GET /api/investments/lots?account_id=...&ticker=...`:**
Returns tax lot detail for the Holdings tab expansion.

**Add `GET /api/investments/allocation?owner_id=...`:**
Returns aggregated allocation data for the Allocation tab.

**Enhance `GET /api/investments/performance`:**
Add `timeframe` parameter to control adaptive granularity.
| Timeframe | Granularity | ~Points |
|-----------|------------|---------|
| 1D | Daily | 1 |
| 1W | Daily | 5-7 |
| 1M | Daily | ~22 |
| 3M | Every ~2 days | ~45 |
| 6M | Weekly | ~26 |
| YTD | Weekly | ~16-52 |
| 1Y | Weekly | ~52 |
| All | Monthly | ~36 |

### Step 8: Frontend wiring

Replace mock data in all three tab components with real API calls:
- `InvestmentsOverview.tsx` → `useOwnerApi` for holdings, performance
- `InvestmentsHoldings.tsx` → `useOwnerApi` for holdings, fetch lots on expand
- `InvestmentsAllocation.tsx` → `useOwnerApi` for allocation endpoint
- Remove fake "Fidelity Roth IRA" and "TSP" mock data from all components

## Verification

### Data integrity
1. `python scripts/seed_dummy_data.py` completes without errors
2. `python -c` queries confirm:
   - positions_ledger has Fidelity entries with BUY, SELL, DIVIDEND types
   - investment_holdings has daily snapshots with cost_basis populated
   - portfolio_snapshots has daily total values
   - ticker_metadata has sector/industry for all 12 tickers (4 Acorns + 8 Fidelity)
   - SELL entries have realistic realized_gain_dec values

### API verification
3. `curl /api/investments/holdings` returns both Acorns + Fidelity with cost basis
4. `curl /api/investments/lots?account_id=fidelity_XXXX&ticker=AAPL` returns lot detail
5. `curl /api/investments/allocation` returns aggregated sector/geo/cap data
6. Cash balance (SPAXX) appears as separate field, not mixed into equity holdings

### Test suite
7. `pytest tests/ -x --tb=short` — full backend suite passes
8. Fidelity data does not break Acorns data (both coexist)

### Frontend
9. Holdings tab shows mixed Acorns ETFs + Fidelity individual stocks
10. Expanding a Fidelity holding shows real tax lots with gain/loss
11. Allocation treemap shows ~12 boxes with correct proportional sizing
12. Sector exposure bars show real sector data from ticker_metadata
13. Cash/Equivalents appears in donut, treemap, and portfolio composition
14. Account filter dropdown works — shows Acorns-only, Fidelity-only, or both

## Known Complexity

- **FIFO lot matching for sells:** Must track which lots are "consumed" by
  each SELL. Use a running queue per ticker — dequeue oldest lots first.
  Mark consumed lots (or track remaining shares per lot) to avoid
  double-counting in cost basis computation.
- **Dividend timing:** Real dividends land on pay dates, not ex-dates.
  For synthetic data, use approximate quarterly cadence per ticker.
  Don't need to match real ex-dates exactly.
- **yfinance rate limits:** Fetching prices for 12 tickers × 3 years can
  be slow. Use the existing `_fetch_and_cache_prices()` cache in
  benchmark_prices to avoid redundant fetches.
- **Snapshot density:** Writing `investment_holdings` for every ticker for
  every day for 3 years = 12 tickers × 1095 days = 13,140 rows. This is
  fine for SQLite. For efficiency, skip weekends and holidays (market
  closed — prices don't change).
