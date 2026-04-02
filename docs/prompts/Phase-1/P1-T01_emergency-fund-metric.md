# P1-T01: Emergency Fund Metric

## Context

You are working on Sentry Finance, a local-first personal finance app.
The user needs an "emergency fund" KPI: how many months of spending
could they cover from liquid accounts alone? This is a core command
center metric — it answers "how long could I survive with no income?"

This task creates the DAL function and API endpoint.

## Starting State

- `balance_snapshots` table stores per-account balances with `as_of` timestamps
- `accounts` table has `type` (checking, savings, credit_card, loan, etc.) and `is_active`
- `transactions` table has `signed_amount`, `category`, `transfer_tag`, `posting_date`
- `derived_summaries` table caches scoped metrics with `UNIQUE(scope, metric, period)`
- `dal/derived.py` contains `recompute_net_worth()` and `recompute_account_metrics()`
- `dal/reports.py` defines `_EXCLUDED_FROM_SPEND` and `_INCOME_CATEGORIES` sets
- `backend/routers/reports.py` handles `/api/metrics/summary` and other report endpoints

## Household Context

Liquid accounts for this household:
- NFCU Checking (0459) — mortgage funding account
- NFCU Savings (1167)
- Chase Checking (8115)
- Affirm HYSA

These are all account types `checking` or `savings`. The implementation
should use account type, not hardcoded account IDs, so it works when
partner accounts are added later.

## Task

### 1. New DAL Function

Add to `dal/derived.py`:

```python
def compute_emergency_fund_months(conn: sqlite3.Connection) -> dict:
    """
    Compute emergency fund runway: liquid_balance / avg_monthly_spending.

    Liquid balance = sum of latest balance_snapshots for all active
    checking + savings accounts.

    Avg monthly spending = average of the last 6 complete calendar months
    of non-transfer, non-income spending (same exclusion logic as
    existing spending calculations).

    Returns:
    {
        "liquid_balance": float,
        "avg_monthly_spending": float,
        "months_of_runway": float | None,  # None if no spending data
        "liquid_accounts": [
            {"account_id": str, "name": str, "balance": float}
        ],
    }
    """
```

**Liquid balance calculation:**
- Query `balance_snapshots` joined with `accounts`
- Filter: `accounts.type IN ('checking', 'savings')` AND `accounts.is_active = 1`
- For each account, use the most recent `balance_snapshots` entry
- Sum all balances

**Average monthly spending calculation:**
- Use the last 6 **complete** calendar months (exclude the current partial month)
- Sum spending per month: `SUM(-signed_amount)` where `signed_amount < 0`
- Exclude transfers: `transfer_tag IS NULL`
- Exclude non-spending categories: use `_EXCLUDED_FROM_SPEND | _INCOME_CATEGORIES`
  from `dal/reports.py` (import them)
- Average the 6 monthly totals
- If fewer than 6 months have data, average what's available (minimum 1 month)

**Runway:**
- `months_of_runway = liquid_balance / avg_monthly_spending`
- If `avg_monthly_spending` is 0 or no data, return `None`

### 2. Store in derived_summaries

After computing, store the result:

```python
conn.execute("""
    INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
    VALUES ('global', 'emergency_fund_months', NULL, ?, datetime('now'))
    ON CONFLICT(scope, metric, period)
    DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
""", (months_of_runway,))
```

### 3. Wire into recompute pipeline

Add a call to `compute_emergency_fund_months(conn)` inside
`recompute_for_institution()` so it updates after every refresh.
Place it after the `recompute_net_worth(conn)` call.

### 4. API Endpoint

Add to `backend/routers/reports.py`:

```python
@router.get("/api/metrics/emergency-fund")
def get_emergency_fund():
    with get_db() as conn:
        return compute_emergency_fund_months(conn)
```

Import `compute_emergency_fund_months` from `dal.derived`.

## Files to Modify

1. `dal/derived.py` — add `compute_emergency_fund_months()`, wire into `recompute_for_institution()`
2. `backend/routers/reports.py` — add endpoint

## Files NOT to Modify

- `dal/reports.py`
- `dal/cash_flow.py`
- Any frontend files
- Any connector files
- Database migrations (no schema changes needed)

## Constraints

- Use account type (`checking`, `savings`), not hardcoded account IDs
- Import `_EXCLUDED_FROM_SPEND` and `_INCOME_CATEGORIES` from `dal/reports.py`
  (already imported at the top of `dal/derived.py`)
- Use 6 complete months for the average — exclude the current partial month
- Follow existing patterns in `dal/derived.py` for the function structure
- Follow existing patterns in `backend/routers/reports.py` for the endpoint
- Read-only queries only (except the derived_summaries upsert)
- Round all financial values to 2 decimal places
- Round months_of_runway to 1 decimal place

## Done Checklist

- [ ] `compute_emergency_fund_months()` exists in `dal/derived.py`
- [ ] Liquid balance sums latest snapshots for active checking + savings accounts
- [ ] Average monthly spending uses last 6 complete months with proper exclusions
- [ ] Result includes `liquid_accounts` list for frontend display
- [ ] Result stored in `derived_summaries` with scope='global', metric='emergency_fund_months'
- [ ] Function called in `recompute_for_institution()` pipeline
- [ ] API endpoint `GET /api/metrics/emergency-fund` returns the full result
- [ ] Handles edge cases: no spending data, no liquid accounts, zero spending

## Verification

After completion, Claude will:
1. Read `dal/derived.py` and `backend/routers/reports.py`
2. Verify spending exclusion logic matches existing patterns
3. Verify liquid balance uses account type, not hardcoded IDs
4. Verify the function is wired into the recompute pipeline
5. Run `python -c "from dal.derived import compute_emergency_fund_months"`
6. Run a functional test against a temp DB
