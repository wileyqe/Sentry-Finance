# P1-T02: Debt-to-Income Ratio (Time Series)

## Context

You are working on Sentry Finance, a local-first personal finance app.
The user needs a debt-to-income (DTI) ratio computed monthly and stored
as a time series. DTI = total monthly debt obligations / monthly gross
income. This is a key health metric for the command center.

## Starting State

- `dal/debt.py` has `_get_liability_accounts()` which returns all active
  debts with balances, APRs, and minimum payments
- `dal/cash_flow.py` and `dal/reports.py` compute monthly income from
  transactions using `_INCOME_CATEGORIES`
- `derived_summaries` table stores scoped metrics: `UNIQUE(scope, metric, period)`
- `loan_details` table stores key-value loan metadata with `as_of` dates
  (fields like `monthly_payment`, `min_payment`, etc.)
- `recurring_transactions` table detects recurring payments with
  `avg_amount` and `frequency`

### Household Context

Monthly debt obligations for this household:
- Mortgage payment (NFCU 6167) — fixed, from loan_details or recurring
- Auto loan payment (NFCU 3533) — fixed, from loan_details or recurring
- Credit card minimum payments — typically $0 (paid in full)
- BNPL payments (Affirm) — episodic, from recurring or loan_details

Income streams: Military pension, VA disability, VA education benefits
(episodic), officiating income (seasonal Aug-Mar).

## Task

### 1. New DAL Function

Create a new function in `dal/derived.py`:

```python
def compute_dti_ratio(conn: sqlite3.Connection, months: int = 12) -> list[dict]:
    """
    Compute monthly DTI ratio for the last N months.

    DTI = monthly_debt_obligations / monthly_gross_income

    Debt obligations (numerator):
      - Sum of all debt-related transaction outflows per month
      - Categories: "Mortgage", "Auto Loan", plus any payment to
        a liability account (credit_card, loan, bnpl type)
      - Exclude transfers between own accounts (transfer_tag IS NULL)

    Gross income (denominator):
      - Sum of all income transactions per month
      - Uses _INCOME_CATEGORIES from dal/reports.py

    Returns oldest-first list:
    [
        {
            "month": "2026-01",
            "debt_payments": float,
            "gross_income": float,
            "dti_ratio": float | None,  # None if no income
            "status": "healthy" | "moderate" | "high" | "critical",
        }
    ]

    Status thresholds:
      healthy:  DTI <= 28%
      moderate: DTI <= 36%
      high:     DTI <= 43%
      critical: DTI > 43%
    """
```

**Debt payments (numerator):**
- Query transactions where `signed_amount < 0` (outflows)
- Filter to debt-payment categories: "Mortgage", "Auto Loan",
  "Credit Card Payments"
- ALSO include: any payment to an account whose type is
  `credit_card`, `loan`, or `bnpl` (catches payments that might
  be categorized differently)
- Exclude transfers: `transfer_tag IS NULL`
- Group by `strftime('%Y-%m', posting_date)`
- Use absolute values for the sum

**Gross income (denominator):**
- Query transactions where `signed_amount > 0`
- Filter to `_INCOME_CATEGORIES` (import from `dal/reports.py`)
- Exclude transfers: `transfer_tag IS NULL`
- Group by month

**Implementation approach:**
- Use a single query with CASE expressions (like `get_cash_flow_report`
  in `dal/reports.py`) to get both income and debt payments per month
- Compute DTI = debt_payments / gross_income per month
- Classify status using the thresholds above

### 2. Store in derived_summaries

Store the latest month's DTI ratio:

```python
conn.execute("""
    INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
    VALUES ('global', 'dti_ratio', ?, ?, datetime('now'))
    ON CONFLICT(scope, metric, period)
    DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
""", (latest_month, latest_dti))
```

Store each month's DTI so the time series is cached.

### 3. Wire into recompute pipeline

Add a call to `compute_dti_ratio(conn, months=1)` (just recompute current
+ previous month) inside `recompute_for_institution()` in `dal/derived.py`,
after the emergency fund computation.

### 4. API Endpoint

Add to `backend/routers/reports.py`:

```python
@router.get("/api/metrics/dti")
def get_dti_ratio(months: int = Query(12, ge=1, le=60)):
    with get_db() as conn:
        return compute_dti_ratio(conn, months=months)
```

## Files to Modify

1. `dal/derived.py` — add `compute_dti_ratio()`, wire into pipeline
2. `backend/routers/reports.py` — add endpoint

## Files NOT to Modify

- `dal/debt.py` — read only, don't change
- `dal/cash_flow.py`
- Any frontend files
- Any connector files
- Database migrations

## Constraints

- Debt payment categories: "Mortgage", "Auto Loan", "Credit Card Payments"
  — these are the categories assigned by the categorization engine
- Import `_INCOME_CATEGORIES` from `dal/reports.py` (already imported
  in `dal/derived.py`)
- Follow the same SQL patterns as `get_cash_flow_report()` in
  `dal/reports.py` for income/expense grouping by month
- Handle months with zero income gracefully (DTI = None, not division error)
- Round DTI ratio to 1 decimal place (as a percentage, e.g., 28.5)
- Round dollar values to 2 decimal places
- Exclude the current partial month from time series (use complete months only)

## Done Checklist

- [ ] `compute_dti_ratio()` exists in `dal/derived.py`
- [ ] Debt payments include Mortgage, Auto Loan, Credit Card Payments categories
- [ ] Income uses `_INCOME_CATEGORIES` from `dal/reports.py`
- [ ] Both exclude transfers (`transfer_tag IS NULL`)
- [ ] Status classification uses the 28/36/43% thresholds
- [ ] Results stored in `derived_summaries` per month
- [ ] Function called in `recompute_for_institution()` pipeline
- [ ] API endpoint `GET /api/metrics/dti` with `months` parameter
- [ ] Handles zero-income months without error

## Verification

After completion, Claude will:
1. Read modified files
2. Verify debt payment category filtering is correct
3. Verify income categories match existing patterns
4. Verify DTI thresholds match standard financial guidelines
5. Run import check
6. Run functional test against temp DB
