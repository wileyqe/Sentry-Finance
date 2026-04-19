# P1-T03: Interest Cost Tracking

## Context

You are working on Sentry Finance, a local-first personal finance app.
The user wants to see the total interest paid across all liabilities —
the "anti-wealth" number. This aggregates interest from the auto loan,
mortgage, and any credit card interest into a single YTD metric with
monthly breakdown.

## Starting State

- `loan_details` table stores key-value snapshots per account:
  ```
  account_id TEXT, field_name TEXT, field_value TEXT, as_of TEXT
  ```
  Known field names include: `ytd_interest`, `interest_rate`, `apr`,
  `Interest Paid YTD`, and similar variations per connector
- `transactions` table may contain interest charges as line items
  (e.g., credit card interest charges categorized as "Interest" or
  "Fees & Interest")
- `dal/debt.py` has `_get_liability_accounts()` and `_get_loan_apr()`
- `derived_summaries` table caches metrics with `UNIQUE(scope, metric, period)`
- Existing `recompute_interest_earned()` in `dal/derived.py` already
  tracks Affirm HYSA interest earned (the positive side)

### Household Liabilities

- NFCU Mortgage (XXXX) — has `loan_details` entries from connector
- NFCU Auto Loan (XXXX) — has `loan_details` entries from connector
- NFCU Credit Card (XXXX) — typically no interest (paid in full)
- Chase Credit Card (XXXX) — typically no interest (paid in full)
- Affirm BNPL — episodic, may or may not have interest

## Task

### 1. New DAL Function

Add to `dal/derived.py`:

```python
def compute_interest_cost(conn: sqlite3.Connection) -> dict:
    """
    Aggregate total interest paid across all liabilities.

    Sources (checked in priority order per account):
    1. loan_details field: 'ytd_interest' or 'Interest Paid YTD'
       (latest as_of for the current year)
    2. Transaction-based: sum of interest-charge transactions
       for credit cards (category contains 'Interest' or 'Fee')

    Returns:
    {
        "ytd_total": float,          # Total interest paid YTD
        "by_account": [
            {
                "account_id": str,
                "account_name": str,
                "account_type": str,
                "ytd_interest": float,
                "source": "loan_details" | "transactions",
            }
        ],
        "monthly_breakdown": [
            {"month": "2026-01", "total_interest": float}
        ],
        "interest_earned": float,    # From savings (Affirm HYSA)
        "net_interest": float,       # earned - paid (usually negative)
    }
    """
```

**YTD interest from loan_details:**
- For each liability account (type in `credit_card`, `loan`, `bnpl`),
  query `loan_details` for field names matching interest:
  ```sql
  SELECT field_value FROM loan_details
  WHERE account_id = ? AND LOWER(field_name) LIKE '%interest%ytd%'
  ORDER BY as_of DESC LIMIT 1
  ```
- Also try: `LOWER(field_name) IN ('ytd_interest', 'interest paid ytd',
  'ytd interest paid')`
- Parse the value as float (strip `$`, `,`, `%`)
- Only use values where `as_of` is in the current year

**Interest from transactions (fallback for credit cards):**
- For credit card accounts without loan_details interest data:
  ```sql
  SELECT SUM(ABS(signed_amount)) FROM transactions
  WHERE account_id = ? AND status = 'posted'
    AND (LOWER(category) LIKE '%interest%' OR LOWER(category) LIKE '%finance charge%')
    AND strftime('%Y', posting_date) = ?
  ```

**Monthly breakdown:**
- Query transactions across all liability accounts for
  interest-related categories, grouped by month
- This provides the trend line for the frontend chart

**Interest earned:**
- Reuse the Affirm HYSA interest query from `recompute_interest_earned()`
  or compute inline: sum of positive `signed_amount` where description
  is 'Interest' for savings accounts

**Net interest:**
- `interest_earned - ytd_total` (will typically be negative)

### 2. Store in derived_summaries

```python
conn.execute("""
    INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
    VALUES ('global', 'ytd_interest_cost', ?, ?, datetime('now'))
    ON CONFLICT(scope, metric, period)
    DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
""", (current_year, ytd_total))
```

### 3. Wire into recompute pipeline

Add to `recompute_for_institution()` after the emergency fund call.

### 4. API Endpoint

Add to `backend/routers/reports.py`:

```python
@router.get("/api/metrics/interest-cost")
def get_interest_cost():
    with get_db() as conn:
        return compute_interest_cost(conn)
```

## Files to Modify

1. `dal/derived.py` — add `compute_interest_cost()`, wire into pipeline
2. `backend/routers/reports.py` — add endpoint

## Files NOT to Modify

- `dal/debt.py`
- `dal/balances.py`
- Any frontend files
- Any connector files
- Database migrations

## Constraints

- Prefer `loan_details` over transaction-based calculation (it's more
  accurate for loans with amortization schedules)
- Fall back to transaction-based for accounts without loan_details
- Handle missing data gracefully (return 0 for accounts with no interest data)
- Parse field_value strings carefully — they may contain `$`, `,`, `%`,
  or be plain numbers
- Current year = `strftime('%Y', 'now')` in SQL or `datetime.now().year` in Python
- Round all dollar values to 2 decimal places
- Follow existing function patterns in `dal/derived.py`

## Done Checklist

- [ ] `compute_interest_cost()` exists in `dal/derived.py`
- [ ] Checks `loan_details` for YTD interest (with flexible field name matching)
- [ ] Falls back to transaction-based interest for credit cards
- [ ] Monthly breakdown computed for trend display
- [ ] Interest earned included for net calculation
- [ ] Result stored in `derived_summaries`
- [ ] Function called in `recompute_for_institution()` pipeline
- [ ] API endpoint `GET /api/metrics/interest-cost` functional
- [ ] Handles accounts with no interest data gracefully

## Verification

After completion, Claude will:
1. Read modified files
2. Verify loan_details field name matching handles variations
3. Verify transaction fallback uses correct category filters
4. Verify net interest calculation is correct (earned - paid)
5. Run import check
6. Run functional test against temp DB
