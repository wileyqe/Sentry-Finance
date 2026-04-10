# P13-T04: Trade Confirmation Pipeline

## Context

P13-T03 shipped the full Acorns data pipeline with delta-logging as the
primary data source (scrape share counts → infer trades → estimate prices
with yFinance → backfill from monthly statement). During that work, the
user discovered that Acorns publishes **daily trade confirmations** in a
"Confirmations" section of the website — one PDF per trade day, listing
every trade that settled with exact ticker, price, quantity, and principal.

This is the same precision as the monthly statement's transaction page but
available same-day. Confirmations become the primary data source;
delta-logging demotes to sanity check; yFinance is no longer needed for
purchase price estimation.

## Starting State

- Branch `investments-rebuild` at commit `081d251`
  (`feat(investments): P13-T03 Acorns end-to-end data pipeline`)
- Confirmation PDF format verified: `Trade Confirmation` header, one or
  more `Buy`/`Sell` blocks with columns: Symbol, Trade Date, Settlement
  Date, Price ($), Quantity, Principal ($), Order Type
- Real confirmation available at
  `Downloads/50f167a3-...-daily_user_trade_confirmation-2026-04-06.pdf`
- Acorns website Confirmations section shows date-labeled rows with
  Download links, one per trade day, going back through current + prior
  month at minimum

## Key Design Decisions

1. **Confirmations = primary source.** `source = 'confirmation'` in
   positions_ledger. Exact prices, no estimation.
2. **Delta-logging = fallback.** Only writes when no confirmations found.
   Always runs as sanity check comparing scraped shares to running totals.
3. **Document drop integration.** Confirmation parser registered alongside
   statement parser for manual fallback.
4. **yFinance removed from purchase path.** Kept only for daily held-share
   valuation in the seeder and benchmark_prices cache.

## Task

### Parser
`dal/parsers/acorns_confirmation.py` — parse trade confirmation PDFs,
write to positions_ledger with `source = 'confirmation'`.

### Connector
Add confirmation download phase to `_trigger_export()`. Navigate to
Confirmations section, download unprocessed PDFs, parse and persist.
Demote delta-logging to fallback/sanity-check.

### Document Drop
Register `AcornsConfirmationParser` in `dal/document_drop.py`.

## Verification

1. Parse real confirmation PDF — verify 2 IXUS buys match visible data
2. Full test suite passes
3. (Manual) Connector navigates to Confirmations and downloads PDFs
