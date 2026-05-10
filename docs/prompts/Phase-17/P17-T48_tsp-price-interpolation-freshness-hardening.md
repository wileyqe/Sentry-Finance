# P17-T48: TSP Price Interpolation And Freshness Hardening

## Context

P17-T45 confirmed that constant-unit interpolation is the right market-movement
path for a retired/no-contribution TSP account, but only between valid anchors
and only when price freshness is visible.

## Starting State

- `dal/tsp_prices.py` loads local TSP price CSVs, fetches MaxTSP current prices,
  writes `benchmark_prices`, and interpolates holdings from anchor units.
- `_HELD_FUNDS` is hard-coded to L2065/C/S.
- `fetch_current_prices()` does not expose the source date it used.
- `load_price_history()` says weekends/holidays are forward-filled, but the
  implementation only filters/sorts loaded rows.
- Interpolation writes holdings/snapshots and does not invent cash flows.

## Task

1. Bound interpolation to statement/scrape anchor windows.
2. Derive fund-label mapping from canonical ticker mapping or anchor rows rather
   than relying on hard-coded held funds.
3. Surface price source date/freshness and stale/no-data failure modes.
4. Decide whether non-trading-day forward-fill is desired; if yes, implement
   and test it explicitly.
5. Prove interpolation never creates bank-side cash, user contributions,
   income, or spending.

## Non-Goals

- Do not change `dal/investments.py` for #80 performance-by-asset-class work
  unless coordination is explicit.
- Do not log into TSP or use credentials.

## Verification

- Add focused `dal/tsp_prices.py` tests for anchor windows, fund mapping,
  stale price behavior, and no cash-flow side effects.
- Run touched tests plus `python scripts/audit_reference_clock_usage.py` if any
  date-window defaults change.
