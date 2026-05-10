# TSP Live-Shape Contract

## Source Hierarchy

Real TSP values must be evidence-backed by one of these sources:

1. TSP statement PDF committed through `dal/parsers/tsp_statement.py`.
2. Future authenticated TSP scrape that captures the same top-line balance and
   per-fund shape.
3. Local TSP share-price history used only to interpolate market movement
   between statement/scrape anchors.
4. User-supplied metadata for facts TSP statements do not expose, such as the
   Roth/traditional/tax-exempt split.

No source may invent a monthly contribution. Contribution-like rows require
bank-side, payroll-side, or TSP-side evidence of actual new money.

## Balances

- `balance_snapshots` records the TSP account top-line balance as of the
  statement date or scrape date.
- `portfolio_snapshots.total_account_value` records the same account-level
  value for investment time series.
- `portfolio_snapshots.cash_balance` is `0.0` unless TSP later exposes an
  actual cash-equivalent holding.
- A recognized TSP statement with a positive top-line balance but no per-fund
  holdings must not commit a balance-only trusted snapshot.

## Per-Fund Units And NAV

- TSP funds are represented as `investment_holdings` rows.
- `shares` means TSP units.
- `close_price` means fund NAV / unit price.
- `market_value` means units times NAV, with normal rounding tolerance.
- Tickers use the canonical `TSP_*` namespace from
  `dal.parsers.tsp_statement._fund_to_ticker`: examples include `TSP_C`,
  `TSP_S`, `TSP_G`, `TSP_I`, `TSP_F`, `TSP_L2065`, and `TSP_LINCOME`.
- The per-fund market-value sum should reconcile to the top-line account
  balance within a documented rounding tolerance before trust-bar readiness.

## Price And Interpolation

`dal/tsp_prices.py` is a no-contribution market-movement path. It may create
daily `investment_holdings` and `portfolio_snapshots` rows from
statement/scrape-anchored units and daily TSP NAVs, but it must not create:

- bank transactions,
- `positions_ledger.bank_txn_id`,
- contribution classifications,
- income rows,
- spending rows.

Constant-unit interpolation is valid only inside a period with no
contribution, withdrawal, loan, rollover, or inter-fund-transfer evidence.
When a new statement/scrape anchor changes units, interpolation must treat that
date as a boundary.

## Allocation And X-Ray

The Investments page depends on:

- `ticker_metadata` for fund labels, sector, industry, and asset class fallback;
- `fund_composition` for look-through asset class, geography, and cap-class;
- `fund_sector_weights` for sector X-Ray of TSP_C, TSP_S, TSP_I, and derived
  lifecycle-fund exposure.

Current live expectation is enough for `TSP_L2065`, `TSP_C`, and `TSP_S`, but
future held L vintages need matching reference rows before X-Ray trust can be
claimed.

## YTD And Performance Details

`extractors/tsp_investment_details.py` parses per-fund `ytd_return` and
`fund_name` into `investment_details`. This is an investment-detail metadata
surface, not the authoritative account value. Failure to scrape YTD return may
skip the metadata row, but it must not silently alter balances, holdings, or
contribution reporting.

Trust-bar behavior should eventually include:

- fixture-backed parsing for current TSP page text;
- an `as_of` date tied to the scrape/source date, not an unrelated workstation
  date;
- proof coverage for visible TSP YTD and allocation values.

## Tax Buckets

TSP is `tax_status='mixed'`. Statements do not expose the Roth/traditional
split in the current parser path.

Current live parser behavior writes one placeholder `tax_buckets` row:
`bucket_type='traditional'`, full balance, `vested_pct=1.0`, and
`as_of=statement_date`. This is acceptable only as an explicit conservative
placeholder before tax-diversification trust. It is not acceptable as a final
live tax-bucket claim if the real account has Roth or tax-exempt money.

## Inter-Fund Transfers

Future TSP inter-fund transfers are intra-account reallocations. They should
move units and value between TSP funds without creating income, spending, or
user-contribution rows. See `inter-fund-transfer-model.md` for the proposed
event shape.
