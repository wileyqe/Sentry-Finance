# P4-T04: Fidelity Cost Basis (Positions CSV)

## Context

You are working on Sentry Finance, a local-first personal finance app.
The Fidelity connector (`extractors/fidelity_connector.py`) currently runs
a single-phase export:
1. Download the **Activity/History CSV** from the Activity & Orders page
2. Run the ingest pipeline (`scripts/ingest_fidelity_history.py`) which
   reconstructs a daily ledger from transaction deltas + baseline positions

The `investment_holdings` table already has a `cost_basis` column (added in V3),
but it is **never populated** because the Activity CSV contains only
transaction-level data (buy/sell amounts), not cumulative cost basis per holding.

Fidelity provides a second CSV download on the **Positions** page
(`https://digital.fidelity.com/ftgw/digital/portfolio/positions`).
This Positions CSV contains:
- Symbol, description, quantity (shares), last price, current value
- **Cost Basis Total** — the aggregate cost basis per holding

Downloading and parsing this CSV will enable:
- Populating `cost_basis` in `investment_holdings`
- Computing unrealized P&L per holding (market_value - cost_basis)
- Displaying gain/loss percentages on the Investments page

## Starting State

- `extractors/fidelity_connector.py` has `_trigger_export()` with Phase 1
  (history CSV) and Phase 2 (ingest). No positions CSV download.
- `_download_history_csv()` navigates to Activity & Orders and downloads
  via icon → "Download as CSV" dropdown flow
- The ingest pipeline writes to `investment_holdings` but leaves `cost_basis`
  as NULL
- `investment_holdings` schema (V3): `(id, account_id, date, ticker, shares,
  close_price, market_value, cost_basis, created_at)`
- V4 added `_dec` TEXT columns for arbitrary precision: `shares_dec`,
  `close_price_dec`, `market_value_dec`, `cost_basis_dec`
- `selector_registry.yaml` has `fidelity.activity.download_icon` selectors

## Task

### 1. Add Position CSV Download Phase

Add a Phase 1.5 (between history download and ingest) to `_trigger_export()`:

```python
# ── Phase 1.5: Download Positions CSV (for cost basis) ────────
print("\n  ── Phase 1.5: Positions CSV ──")
positions_path = self._download_positions_csv(page, reg)
```

Implement `_download_positions_csv()`:

```python
def _download_positions_csv(self, page: Page, reg: dict) -> Path | None:
    """Navigate to Positions page and download the positions CSV.

    The Positions page has a download icon similar to the Activity page.
    Flow: navigate → click download icon → select CSV → save file.
    """
    POSITIONS_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/positions"
    
    print("  📍  Navigating to Positions page...")
    page.goto(POSITIONS_URL, wait_until="domcontentloaded", timeout=30000)
    # ... (similar download flow to _download_history_csv)
```

The Positions page download flow mirrors the Activity page:
1. Navigate to the Positions URL
2. Wait for content to load
3. Click the download icon (may use same or similar selectors as Activity)
4. Select "Download as CSV" from the dropdown
5. Save the file to `raw_exports/fidelity/`

Add selectors to `selector_registry.yaml`:
```yaml
fidelity.positions.download_icon:
  selectors:
    - '[aria-label*="download" i]'
    - '[aria-label*="export" i]'
    - 'button:has-text("Download")'
```

### 2. Parse Positions CSV and Populate Cost Basis

Create `_ingest_positions_csv()` to parse the downloaded Positions CSV:

```python
def _ingest_positions_csv(self, positions_path: Path) -> None:
    """Parse Fidelity Positions CSV and update cost_basis in investment_holdings."""
```

Fidelity Positions CSV format (expected columns):
```
Account Name/Number  Symbol  Description  Quantity  Last Price  ...  Cost Basis Total  ...
```

For each row:
- Extract `Symbol` (ticker), `Quantity` (shares), `Cost Basis Total`
- Skip cash positions (SPAXX, "CASH", etc.) — these don't have cost basis
- Update the **most recent** `investment_holdings` row for that ticker with
  the cost basis value

```python
with get_db() as conn:
    for ticker, cost_basis in parsed_data.items():
        conn.execute("""
            UPDATE investment_holdings
            SET cost_basis = ?, cost_basis_dec = ?
            WHERE account_id = ? AND ticker = ?
              AND date = (
                  SELECT MAX(date) FROM investment_holdings
                  WHERE account_id = ? AND ticker = ?
              )
        """, (cost_basis, str(cost_basis), account_id, ticker, account_id, ticker))
    conn.commit()
```

### 3. Wire Into Export Pipeline

Update `_trigger_export()` to call the positions ingest after history:

```python
def _trigger_export(self, page, accounts):
    # Phase 1: Download History CSV
    history_path = self._download_history_csv(page, reg)
    
    # Phase 1.5: Download Positions CSV (cost basis)
    positions_path = self._download_positions_csv(page, reg)
    
    # Phase 2: Run history ingest
    if history_path:
        self._run_ingest([history_path])
    
    # Phase 3: Ingest positions (cost basis overlay)
    if positions_path:
        print("\n  ── Phase 3: Cost Basis Update ──")
        self._ingest_positions_csv(positions_path)
    
    return []
```

## Files to Modify

1. `extractors/fidelity_connector.py` — add positions download, CSV parsing, cost basis update
2. `extractors/selector_registry.yaml` — add positions page selectors

## Files NOT to Modify

- `dal/migrations/` — `cost_basis` column already exists in V3
- `scripts/ingest_fidelity_history.py` — the existing pipeline is unchanged
- Any frontend files
- Other connector files
- `dal/balances.py`

## Constraints

- Positions CSV download must NOT block history CSV download — if positions
  download fails, the history pipeline should still run
- Cost basis update is an **overlay** — it updates existing rows, it does not
  insert new ones. If a ticker exists in positions CSV but not in
  `investment_holdings`, skip it (don't create phantom holdings).
- Handle Fidelity's quirky CSV format: may have header rows, footer rows,
  or "Total" summary lines that need to be skipped
- Skip cash-equivalent tickers (SPAXX, FZFXX, etc.) — no cost basis needed
- Round cost basis to 2 decimal places
- The `cost_basis_dec` TEXT column should store the exact string representation
- If the Positions page requires different selectors than Activity, add
  them to the registry under a separate `fidelity.positions.*` group

## Done Checklist

- [ ] `_download_positions_csv()` navigates to Positions page and downloads CSV
- [ ] `_ingest_positions_csv()` parses CSV and extracts cost basis per ticker
- [ ] Cost basis written to both `cost_basis` (REAL) and `cost_basis_dec` (TEXT)
- [ ] Cash-equivalent tickers skipped
- [ ] Export pipeline phases updated (1 → 1.5 → 2 → 3)
- [ ] Positions download failure does NOT block history pipeline
- [ ] Selector registry updated for positions page
- [ ] Existing history download and ingest unchanged

## Verification

After completion, Claude will:
1. Read `fidelity_connector.py` and verify new phase organization
2. Verify positions CSV parsing handles header/footer rows
3. Verify cost basis update SQL targets most-recent date per ticker
4. Run import check: `python -c "from extractors.fidelity_connector import FidelityConnector"`
5. Verify selector_registry.yaml has `fidelity.positions.download_icon`
