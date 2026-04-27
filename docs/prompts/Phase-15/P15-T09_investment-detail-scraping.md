# P15-T09: Investment Detail Scraping

## Context

P15-T06 built the Account Details drawer (`AccountDetailsPanel.tsx`)
but intentionally left investment / retirement accounts blank — the
panel rendered a static "No investment details captured yet… tracked
in P15-T09" message. T09 fills that gap by scraping per-account
investment metadata from three institutions and surfacing them
through the existing details bundle.

**Decision-support framing (per user):** per-ticker performance is
what drives diversification calls — *"this account has VTI doing
well; I have enough VTI across the whole portfolio; next purchase in
a different account should be something else."* The per-fund row
design supports that question end-to-end.

## Locked design choices

| Question | Decision |
|---|---|
| Per-account opt-in vs default-on | **Default-on** for `type IN ('investment','retirement')` |
| TSP L-fund granularity | One row per dated vintage (`L2030`, `L2040`, …) |
| SPAXX storage | `fund_ticker='SPAXX'` (consistent with TSP funds) |
| Acorns account-level fields | Round-ups YTD + lifetime ONLY |
| Acorns per-ETF rows | Yes — capture YTD return per held ETF |
| Per-ETF generalization | Same pattern extended to Fidelity holdings |

## What shipped

### Schema (migration v41)

`dal/migrations/v41_investment_details.py` — single
`investment_details` table with nullable `fund_ticker` and a
`COALESCE`-aware unique index so account-level + fund-level rows
share one writer:

```sql
CREATE TABLE investment_details (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  fund_ticker TEXT,
  field_name TEXT NOT NULL,
  field_value TEXT,
  as_of TEXT NOT NULL,
  refresh_run_id INTEGER,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX idx_investment_details_unique
  ON investment_details(
    account_id, COALESCE(fund_ticker,''), field_name, refresh_run_id
  );
```

Field vocabulary:

- Account-level (fund_ticker NULL): `round_up_ytd`, `round_up_lifetime`
- Fund-level: `sec_yield` (SPAXX), `ytd_return` (everything else),
  `fund_name` (TSP labels)

### DAL — `dal/investment_details.py` (new)

- `record_investment_details(conn, account_id, fields, *, fund_ticker, as_of, refresh_run_id)` —
  INSERT OR IGNORE writer, caller-commits, fail-fast invariants
  (ISO-8601 `as_of`, non-empty `field_name`, ticker matches
  `^[A-Z][A-Z0-9_]{0,11}$` to allow `TSP_C` / `TSP_L2065`).
- `get_latest_investment_details(conn, account_id)` — newest-per-
  (fund_ticker, field_name) snapshot.
- `get_investment_field_history(conn, …)` — for a future
  `returnTrend` sparkline.

### Composer — `dal/account_details_composer.py`

`get_investment_panel_bundle(conn, account_id)` returns a structural
**superset** of the loan-side bundle:

```python
{
    "account_id": str,
    "kind": "investment",
    "details": {field: {value, as_of}},   # account-level + merged loan-side
    "funds": [
        {"ticker": str, "name": str | None,
         "fields": {field: {value, as_of}}},
        ...                                # alphabetical
    ],
    "apy_latest": ApyLatest | None,        # merged from loan_panel
    "apy_history": [...],                  # merged from loan_panel
    "collateral": None,
}
```

The merge with `get_loan_panel_bundle` is load-bearing: brokerage
accounts like Fidelity carry **both** investment_details (per-equity
YTD + SPAXX SEC yield) **and** loan_details (cash-side
`available_balance`, `dividends_ytd`) **and** apy_history (SPAXX
sweep yield as a time series). The AccountsPage splits the brokerage
into "(Cash)" and "(Investments)" virtual rows but both hit the same
`/api/accounts/{id}/details` endpoint, so the bundle has to carry
everything.

### API dispatch — `backend/routers/reports.py`

`/api/accounts/{id}/details` now type-dispatches:
`investment` / `retirement` → `get_investment_panel_bundle`,
everything else → `get_loan_panel_bundle`.

A `# TODO(post-T09): relocate to routers/accounts.py per ROADMAP
backlog` comment notes the deferred relocate item.

### Result writer — `backend/result_writer.py`

New `investment_details` block routes connector
`result.investment_details` of shape
`{last4: {account_level: {...}, funds: {ticker: {...}}}}` through
`record_investment_details`. The shape distinction is carried by
the dict structure, not a per-institution branch.

### Connector contract — `skills/institution_connector.py`

`ConnectorResult` extended with optional `investment_details`
parameter. `InstitutionConnector.run()` initializes
`self._result_investment_details: dict[str, dict]` and threads it
into the result on success.

### Per-institution parsers (text-in / fields-out)

All three parsers are pure functions: take `page.inner_text("body")`
output, return field dicts. Live navigation lives on the connector;
the parsers are unit-tested against fixture page-text dumps without
a browser.

- **Fidelity** — `extractors/fidelity_investment_details.py` (+
  `_scrape_investment_details` orchestrator on the connector).
  SPAXX SEC yield (`7-Day Yield (SEC)`); per-position YTD return
  (`YTD Return` / `Year-to-Date Return`).
- **TSP** — `extractors/tsp_investment_details.py` (+ second-pass
  call after `_parse_investments_page` so the existing balance
  scrape isn't refactored). Per-fund YTD + `fund_name`. Tickers
  via `dal.parsers.tsp_statement._fund_to_ticker` so on-disk +
  scrape paths agree on naming.
- **Acorns** — `extractors/acorns_investment_details.py` (+ Phase 5
  in `_trigger_export`). Round-ups (account-level) +
  per-ETF YTD return.

### Shared regex helper — `extractors/_investment_extract.py`

`extract_field(page_text, patterns)` mirrors Chase's
`_extract_field_value` but with an investment value alternation
(currency, signed percent, plain number — no slash dates / on-off
flags). Capture detection uses
`re.compile(pattern).groups > 0` instead of scanning for raw `(`
so escaped parens (`\(SEC\)`) and non-capturing groups don't
false-trigger the value-first branch.

### Frontend — `AccountDetailsPanel.tsx`

- `DetailsResponse` extended with optional `kind?: string` and
  `funds?: FundEntry[]` (structural superset; loan/manual-asset
  paths unchanged).
- `INVESTMENT_ORDER` populated with round-ups + cash-side fields
  (`available_balance`, `dividends_ytd`, …) for brokerage merge.
- New investment branch: APY card (when present) + account-level
  row grid + per-fund table with `Fund | YTD Return | SEC Yield`
  columns. SEC Yield column is conditionally rendered when at
  least one fund has it.
- New field kinds + labels in `formatDetailField.ts`: `sec_yield`,
  `ytd_return` (both `percent`); `round_up_ytd`, `round_up_lifetime`
  (both `currency`).

### AccountsPage toggle — `frontend/src/pages/AccountsPage.tsx`

`hasDetailsToggle` pre-T09 was hardcoded to exclude
investment/retirement accounts (panel had nothing to show).
Updated to enable Details across all account types.

### Seeder — `scripts/seed_dummy_data.py::seed_investment_details`

Stamps deterministic round-ups + per-ETF YTD return rows for the
three synthetic investment accounts so the Details drawer renders
without a refresh:

- `acorns_synthetic` — round-ups YTD/lifetime + 4 ETF rows
  (VOO/IJH/IJR/IXUS).
- `fidelity_brokerage` — SPAXX SEC yield + 8 equity rows
  (AAPL/AMZN/GOOG/MSFT/QQQM/SBUX/SPG/TGT).
- `tsp_synthetic` — 3 fund rows with `fund_name` labels
  (TSP_C / TSP_S / TSP_L2065).

## Tests

- `tests/test_investment_details.py` (15) — DAL invariants,
  COALESCE-unique-index, latest-per-(fund,field) semantics,
  TSP underscore tickers.
- `tests/test_investment_panel_bundle.py` (6) — composer shape,
  mixed account+fund rows, alphabetical sort.
- `tests/test_result_writer_investment.py` (4) — end-to-end
  routing, account-level + funds, invalid-ticker skip,
  backward compat for connectors without `investment_details`.
- `tests/test_accounts_details_endpoint.py` (10) — type-dispatch
  to investment bundle, no regression on credit-card / depository.
- `tests/test_fidelity_investment_extractor.py` (11) — SPAXX yield,
  per-equity YTD, signed percentages, dispatcher.
- `tests/test_tsp_investment_extractor.py` (6) — static funds,
  L-vintages, negative returns, missing-return skip.
- `tests/test_acorns_investment_extractor.py` (11) — round-ups,
  per-ETF YTD, two-letter-code skip, lookahead window.

**62 new + extended backend tests, all green. Frontend `tsc`
clean, vite build clean.**

## Verification

- Full backend pytest sweep (62 P15-T09 tests + 8 endpoint
  regression tests).
- `tsc --noEmit` + `npm run build` clean.
- Browser smoke via `/dev-server`: expanded all four investment-
  account rows (Acorns, Fidelity Cash, Fidelity Investments, TSP)
  and confirmed account-level rows + APY card + per-fund table
  render with the seeded data. Confirmed credit-card, auto-loan,
  and HYSA panels still render their existing details unchanged.

## Out of scope / follow-ups

- Per-fund history sparkline (`returnTrend.ts`) — needs ≥3
  refreshes of history. Schedule when data accumulates.
- Relocating `/api/accounts/{id}/details` to `accounts.py`
  (ROADMAP backlog trigger) — bundled into post-T09 cleanup,
  not T09 itself.
- Acorns recurring-contributions / portfolio-label / all-time-gain
  — user opted out of these for T09 scope.
- Cost-basis / lot-level data — that's P18, blocked on real
  broker statements.
- Live-portal layout drift on the SPAXX modal / Acorns dashboard
  / TSP SPA. Per-position try/except + page-text dumps on failure
  mitigate; the regex fixtures pin the contract so drift fails
  loudly.
