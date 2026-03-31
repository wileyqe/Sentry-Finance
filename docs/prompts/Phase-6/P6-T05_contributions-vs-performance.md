# P6-T05: Contributions vs. Performance Decomposition

## Context

You are working on Sentry Finance, a local-first personal finance app.
The Investments page shows portfolio value and returns. But a key question
is unanswered: **"Of my portfolio's growth, how much did I put in, and
how much did the market generate?"**

This matters because:
- A portfolio that grew $20K looks great — but if $18K of that was new
  deposits, the market only returned $2K (modest performance).
- Conversely, $20K growth on $0 in new contributions means the market
  worked hard for the user.

### Data available

- **`positions_ledger`** — one row per account per refresh run per ticker:
  `(run_id, account_id, ticker, shares, close_price, market_value, timestamp)`
- **`balance_snapshots`** — one row per account per refresh:
  `(account_id, as_of, balance)`
- **`transactions`** — tagged with `transfer_tag` when money moves between
  accounts. Transfers INTO an investment account = contributions.
  Transfers OUT = withdrawals.

### Decomposition approach

```
Total Gain = End Value − Start Value

Net Contributions = sum of transfer-tagged transactions flowing INTO
                    the investment account during the period
                    (negative signed_amount FROM a checking account,
                    positive net into the investment account)

Performance Gain = Total Gain − Net Contributions
Performance Return % = Performance Gain / (Start Value + Weighted Contributions)
```

The **time-weighted return (TWR)** in `dal/performance.py` already computes
portfolio-level returns. This task adds the **contribution-adjusted
decomposition** per account per year.

## Starting State

- `dal/performance.py` — `get_portfolio_performance(conn, months)` returns
  period returns and TWR; does NOT decompose contributions
- `positions_ledger` table populated by connector runs
- `balance_snapshots` table populated by connector runs
- `transactions` table with `transfer_tag` and `signed_amount` columns
- `dal/yearly_wrapup.py` (P6-T02) calls
  `decompose_contributions_vs_performance(conn, year)` if available
- `InvestmentsPage.tsx` shows performance; no contributions breakdown yet
- No `decompose_contributions_vs_performance()` function exists

## Task

### 1. Extend `dal/performance.py`

Add `decompose_contributions_vs_performance()` to the existing module.

```python
def decompose_contributions_vs_performance(
    conn: sqlite3.Connection,
    year: int,
    account_ids: list[str] | None = None,
) -> list[dict]:
    """
    For each investment/retirement account, decompose the year's value
    change into contributions (money in) vs. market performance (market in).

    Args:
        conn: DB connection
        year: Calendar year to analyze (e.g., 2025)
        account_ids: Optional filter; if None, uses all investment/retirement
                     accounts from the accounts table.

    Returns: list of dicts, one per account:
    [
        {
            "account_id": str,
            "account_name": str,
            "institution": str,
            "start_value": float,        # closest snapshot to Jan 1
            "end_value": float,          # closest snapshot to Dec 31
            "total_gain": float,         # end - start
            "net_contributions": float,  # transfers in - transfers out
            "performance_gain": float,   # total_gain - net_contributions
            "performance_return_pct": float | None,  # see formula below
            "contribution_count": int,   # number of contribution transactions
            "has_sufficient_data": bool, # False if missing start or end snapshot
        }, ...
    ]
    """
```

**Implementation steps:**

1. **Determine account set**: query `accounts` where
   `type IN ('investment', 'retirement')` and `is_active = 1`.
   If `account_ids` provided, filter to that list.

2. **Start value** per account: query `balance_snapshots` for the
   **last** snapshot with `as_of <= '{year}-01-15'` (first two weeks
   of January, or last snapshot before the year). If none, mark
   `has_sufficient_data = False`.

3. **End value** per account: query `balance_snapshots` for the
   **last** snapshot with `as_of <= '{year}-12-31'`. If none,
   mark `has_sufficient_data = False`.

4. **Net contributions**: query `transactions` where:
   - `account_id = <investment_account_id>`
   - `strftime('%Y', posted_date) = '{year}'`
   - `transfer_tag IS NOT NULL`

   Sum `signed_amount`. Positive `signed_amount` = money INTO the account
   (contribution). Negative = money OUT (withdrawal).

   `net_contributions = sum(signed_amount)`

5. **Decomposition**:
   ```
   total_gain = end_value - start_value
   performance_gain = total_gain - net_contributions
   ```

6. **Performance return %** (simple Dietz method):
   ```
   denominator = start_value + (net_contributions * 0.5)
   performance_return_pct = (performance_gain / denominator) * 100
   ```
   If `denominator <= 0`, set `performance_return_pct = None`.

7. **`contribution_count`**: count of transfer-tagged transactions
   with `signed_amount > 0` for the period.

### 2. API Endpoint

Add to `backend/routers/investments.py`:

```python
@router.get("/api/investments/contributions-vs-performance")
def contributions_vs_performance(
    year: int | None = None,
    account_id: str | None = None,
):
    """
    Returns the contributions vs. performance decomposition.
    Defaults to the prior calendar year.
    """
    if year is None:
        year = date.today().year - 1
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        return decompose_contributions_vs_performance(conn, year, account_ids)
```

### 3. Frontend: Extend `InvestmentsPage.tsx`

Add a **"Contributions vs. Market Growth"** section to the Investments page
below the existing performance chart.

**Fetch**: `GET /api/investments/contributions-vs-performance?year=YYYY`

**Display** (for each account with `has_sufficient_data = True`):

Stacked horizontal bar:
```
[████████████████████░░░░░░░░░] $X,XXX total gain
 Market: $X,XXX (XX%)   |   You added: $X,XXX
```

- Dark teal segment = `performance_gain` (market)
- Lighter segment = `net_contributions` (your deposits)
- If `performance_gain < 0` (market loss), show red segment

Below the bar: `Start: $X,XXX → End: $X,XXX | Performance: +X.X%`

Show a year selector (`<select>`) that re-fetches with updated year param.

If `has_sufficient_data = False` for an account: show a muted "Insufficient
data for [year]" placeholder for that account.

## Files to Modify

1. `dal/performance.py` — add `decompose_contributions_vs_performance()`
2. `backend/routers/investments.py` — add endpoint
3. `frontend/src/pages/InvestmentsPage.tsx` — add contributions section

## Files NOT to Modify

- `dal/yearly_wrapup.py` — it already calls this function gracefully
  when available; no change needed once the function exists
- Any migration files — no schema changes required
- `dal/performance.py`'s existing functions — add to the module, don't change

## Constraints

- Contributions are identified **only** by `transfer_tag IS NOT NULL` on
  transactions posted to the investment account. Do NOT try to infer
  contributions from positions_ledger deltas or price movements —
  that logic is error-prone.
- Accounts with zero `balance_snapshots` in the target year must return
  `has_sufficient_data = False`, not raise.
- The simple Dietz method is an approximation (contribution timing
  assumed mid-year). This is acceptable — note it in the docstring.
  Do NOT implement full Modified Dietz unless the approximation
  produces clearly wrong results.
- Negative `performance_gain` (market loss) is valid and must be
  displayed as a loss, not hidden.
- `net_contributions = 0` for TSP (contributions come from payroll,
  which is not transfer-tagged in this system). TSP rows will show
  `total_gain = performance_gain` — which is correct, since we can't
  distinguish payroll contributions from market growth via the current
  data model. Note this limitation in the docstring.

## Done Checklist

- [ ] `decompose_contributions_vs_performance()` added to `dal/performance.py`
- [ ] Start/end values from `balance_snapshots` with correct date logic
- [ ] Net contributions from transfer-tagged transactions only
- [ ] Simple Dietz performance return % computed correctly
- [ ] `has_sufficient_data = False` when snapshots are missing
- [ ] `GET /api/investments/contributions-vs-performance` endpoint added
- [ ] `InvestmentsPage.tsx` shows stacked bar per account
- [ ] Negative performance gain displayed as loss (red segment)
- [ ] Year selector re-fetches data
- [ ] TSP limitation documented in function docstring

## Verification

After completion, Claude will:
1. Run `python -c "from dal.performance import decompose_contributions_vs_performance"` — no errors
2. Write pytest tests:
   a. Account with start=10000, end=12000, contributions=1500 →
      total_gain=2000, net_contributions=1500, performance_gain=500,
      return_pct ≈ 4.9% (500 / (10000 + 750) × 100)
   b. Account with no balance_snapshots → `has_sufficient_data = False`
   c. Account with start=10000, end=8000, contributions=0 →
      performance_gain = -2000 (negative, valid)
   d. `contribution_count` equals count of positive transfer transactions
3. All tests pass
