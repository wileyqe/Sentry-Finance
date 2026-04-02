# P0-T05: Acorns All-or-Nothing Scrape Guard

## Context

You are working on Sentry Finance, a local-first personal finance app.
The Acorns connector scrapes portfolio data by navigating to each fund's
detail page individually (VOO, IJH, IJR, IXUS) to extract share counts.
If some fund pages load successfully but others timeout, the connector
currently writes partial data — recording deltas only for successful
funds and silently skipping failed ones.

This creates a dangerous failure mode: the skipped fund shows no delta
(indistinguishable from "no activity"), and the next full scrape creates
a phantom implied transaction on the wrong date, distorting portfolio
performance calculations.

## Starting State

- `extractors/acorns_connector.py` exists and handles login, portfolio
  value scraping, and per-fund share count extraction
- Share counts are extracted by navigating to individual fund detail pages
- Delta-logging compares current shares to the last known count in the DB
- The connector writes to `positions_ledger` and `portfolio_snapshots`
- Known tickers: VOO, IJH, IJR, IXUS

## Task

Modify `extractors/acorns_connector.py` to enforce all-or-nothing
behavior for the fund share scraping phase:

### 1. Collect All Fund Data Before Writing

Currently, the connector likely scrapes each fund page and writes to
the database incrementally. Change this to:

1. Scrape portfolio total value (this can succeed independently)
2. Attempt to scrape ALL fund pages, collecting results in memory
3. If ALL funds succeeded: proceed with delta-logging and writes
4. If ANY fund failed: discard ALL fund data for this scrape, log an
   error, but still write the portfolio total value (balance snapshot)

### 2. Implementation Pattern

```python
# Phase: Scrape fund share counts
fund_results = {}
fund_errors = []

for ticker in KNOWN_TICKERS:  # VOO, IJH, IJR, IXUS
    try:
        shares = self._scrape_fund_shares(page, ticker)
        if shares is not None:
            fund_results[ticker] = shares
        else:
            fund_errors.append(ticker)
    except Exception as e:
        log.error("Failed to scrape %s: %s", ticker, e)
        fund_errors.append(ticker)

if fund_errors:
    log.error(
        "Partial scrape: %d/%d funds failed (%s). "
        "Discarding ALL fund data to prevent phantom deltas.",
        len(fund_errors),
        len(KNOWN_TICKERS),
        ", ".join(fund_errors),
    )
    # Do NOT write any fund data
    # DO still write portfolio total value as a balance snapshot
else:
    # All funds succeeded — proceed with delta-logging
    for ticker, shares in fund_results.items():
        self._process_fund_delta(ticker, shares, ...)
```

### 3. Logging

- On full success: `log.info("All %d funds scraped successfully", len(fund_results))`
- On partial failure: `log.error(...)` as shown above
- On total failure (no funds scraped): `log.error("Fund scraping failed completely — no fund data written")`

### 4. Important: Preserve Portfolio Value Write

Even when fund scraping fails, the portfolio total value (scraped from
the hero banner on the main page) is still valid and should be written
as a balance snapshot. This keeps the net worth calculation current
even if per-fund detail is temporarily unavailable.

## Files to Modify

1. `extractors/acorns_connector.py` — add all-or-nothing guard

## Files NOT to Modify

- `dal/investments.py` — the write functions are fine
- `dal/derived.py` — not relevant
- Any other connector files
- Any DAL files
- Any frontend files

## Constraints

- Read the existing connector thoroughly before making changes —
  understand the current flow before modifying it
- Do NOT change the login flow, portfolio value scraping, or any
  page navigation logic
- Do NOT change the delta-logging algorithm itself (how deltas are
  computed) — only gate WHEN it runs
- The fund page navigation and share extraction functions should remain
  as-is; only the orchestration logic around them changes
- Preserve all existing logging
- If the connector uses a different pattern than described above
  (e.g., different variable names, different control flow), adapt the
  all-or-nothing pattern to match the existing code style

## Done Checklist

- [ ] Fund scraping collects ALL results before writing ANY
- [ ] If any fund fails, NO fund data is written (delta-logging skipped)
- [ ] Portfolio total value is still written even when funds fail
- [ ] Error logging clearly identifies which funds failed
- [ ] Success logging confirms all funds scraped
- [ ] No changes to login, navigation, or delta computation logic
- [ ] Existing code style and patterns preserved

## Verification

After completion, Claude will:
1. Read the modified connector file
2. Trace the control flow to verify all-or-nothing behavior
3. Verify portfolio value is still written on partial failure
4. Verify no other connector behavior was changed
5. Check logging messages are clear and actionable
