# P3-T02: Recurring-to-Loan Linking

## Context

You are working on Sentry Finance, a local-first personal finance app.
The recurring transaction engine (`dal/recurring.py`) detects repeating
payments like the mortgage, car loan, and credit card payments. The debt
module (`dal/debt.py`) knows about liability accounts, their APR, and
balance. But these two systems don't talk to each other.

The user's mortgage payment is detected as a recurring transaction, but
the forecasting engine projects it forever. In reality, the mortgage has
a `maturity_date` stored in `loan_details`. When the loan pays off, that
recurring payment stops — freeing up cash flow. The same applies to the
car loan and any BNPL installment plan with a known end date.

This task links recurring payments to their source loan accounts so the
forecaster can project when payments will stop and how much cash flow
will be freed.

## Starting State

- `recurring_transactions` table has: `id`, `account_id`, `merchant`,
  `category`, `frequency`, `expected_amount`, `status`, etc.
  - No column currently links to a loan/liability account
- `loan_details` table: `account_id`, `field_name`, `field_value`, `as_of`
  - Stores key-value pairs like `maturity_date`, `interest_rate`, `apr`,
    `original_amount`, `remaining_term`
- `accounts` table: `id`, `name`, `type` (checking, savings, loan,
  credit_card, bnpl), `institution_id`, `is_active`
- `dal/recurring.py` — detection and query functions
- `dal/debt.py` — `_get_liability_accounts()`, `get_debt_summary()`,
  `get_payoff_plan()`
- `dal/forecasting.py` — `get_cash_flow_forecast()` uses
  `_get_recurring_monthly_total()` which sums all active recurring

## Task

### 1. Add `linked_account_id` column (V16 migration)

Create `dal/migrations/v16_recurring_loan_link.py`:

```python
VERSION = 16

def run(conn):
    conn.executescript("""
        ALTER TABLE recurring_transactions
            ADD COLUMN linked_account_id TEXT;

        -- Index for fast lookup
        CREATE INDEX IF NOT EXISTS idx_recurring_linked
            ON recurring_transactions(linked_account_id);
    """)
```

### 2. New Function: `link_recurring_to_loans()`

Add to `dal/recurring.py`:

```python
def link_recurring_to_loans(conn: sqlite3.Connection) -> dict:
    """
    Auto-link recurring payments to their source loan/liability accounts.

    Uses a matching heuristic:
      1. Same institution: recurring.account_id shares institution_id
         with a liability account
      2. Category match: category is in loan-related categories
         (Mortgage, Auto Loan, Credit Card Payments)
      3. Amount proximity: recurring expected_amount is within 20% of
         the loan's estimated minimum payment

    Returns:
        {"linked": int, "already_linked": int, "unlinked": int}
    """
```

**Matching strategy (precedence order):**

1. **Exact institution + category match:** The most reliable signal.
   If a recurring payment with category "Mortgage" originates from an
   account at institution X, and institution X also has a `loan` account,
   that's an automatic match.

2. **Cross-institution category + amount match:** For payments that
   cross institutions (e.g., NFCU checking pays the auto loan at a
   different bank), match by category + amount proximity to the loan's
   known payment amount (from `loan_details` field `monthly_payment` or
   derived from balance/rate/term).

3. **Manual override preservation:** If `linked_account_id` is already
   set (user manually linked, or previously auto-linked and later
   edited), do NOT overwrite it.

**Loan-related categories:**
```python
_LOAN_CATEGORIES = {"Mortgage", "Auto Loan", "Student Loan",
                    "Credit Card Payments", "Loan Payment"}
```

### 3. New Function: `get_recurring_with_payoff()`

Add to `dal/recurring.py`:

```python
def get_recurring_with_payoff(conn: sqlite3.Connection) -> list[dict]:
    """
    Return active recurring transactions enriched with payoff dates.

    For linked recurring items:
      - If the linked account has a maturity_date in loan_details,
        include it as "ends_at" in the result
      - Include the linked account's current balance and APR

    Returns list of dicts, each like:
    {
        # ... all recurring_transactions columns ...
        "linked_account_name": str | None,
        "linked_balance": float | None,
        "linked_apr": float | None,
        "ends_at": str | None,  # YYYY-MM-DD maturity date
        "months_remaining": int | None,  # months until payoff
        "total_remaining": float | None,  # estimated remaining payments
    }
    """
```

### 4. Update Forecasting: Stop Payments at Payoff

Modify `_get_recurring_monthly_total()` in `dal/forecasting.py`:

Currently, this function sums ALL active recurring expenses. Enhance it
to accept a `target_month` parameter so it can exclude recurring payments
whose linked loan will be paid off by that month:

```python
def _get_recurring_monthly_total(
    conn: sqlite3.Connection,
    account_ids: Optional[list[str]] = None,
    target_month: Optional[str] = None,   # NEW: "YYYY-MM"
) -> float:
```

When `target_month` is set:
- For each recurring item that has a `linked_account_id` with a
  `maturity_date`, check if `target_month >= maturity_date`
- If yes, exclude that recurring item from the sum (it's paid off)
- If no maturity_date or no linked account, include as before

Then update `get_cash_flow_forecast()` to pass `target_month` for each
projected month, so the forecast reflects freed cash flow after payoffs.

### 5. Wire into pipeline

Call `link_recurring_to_loans()` inside `detect_recurring()` at the end
(after the detection sweep), so links stay current as payments evolve.

### 6. API Endpoint

Add to `backend/routers/recurring.py` (or `reports.py`):

```python
@router.get("/api/recurring/with-payoff")
def recurring_with_payoff():
    with get_db() as conn:
        return {"items": get_recurring_with_payoff(conn)}
```

## Files to Create

1. `dal/migrations/v16_recurring_loan_link.py`

## Files to Modify

2. `dal/recurring.py` — add `link_recurring_to_loans()`, `get_recurring_with_payoff()`
3. `dal/forecasting.py` — modify `_get_recurring_monthly_total()` and
   `get_cash_flow_forecast()` to respect payoff dates
4. `backend/routers/recurring.py` — add endpoint

## Files NOT to Modify

- `dal/debt.py` — use `_get_loan_apr()` as reference but don't modify
- Any frontend files
- Any connector files

## Constraints

- The linking algorithm must be re-runnable (idempotent) — running it
  twice should not create duplicate links or corrupt existing ones
- Manual overrides (where user has already set `linked_account_id`)
  must NEVER be overwritten by auto-linking
- The `maturity_date` in `loan_details` may be stored in various formats:
  "YYYY-MM-DD", "MM/DD/YYYY", "YYYY-MM". Normalize to YYYY-MM-DD for
  comparison. Handle missing maturity_date gracefully (treat as infinite)
- The existing `_get_recurring_monthly_total()` signature has
  `(conn, account_ids=None)`. Adding `target_month=None` as a keyword
  argument preserves backward compatibility
- All existing callers of `_get_recurring_monthly_total()` that don't
  pass `target_month` must continue to work exactly as before
- Round all dollar values to 2 decimal places

## Done Checklist

- [ ] V16 migration adds `linked_account_id` to `recurring_transactions`
- [ ] `link_recurring_to_loans()` exists in `dal/recurring.py`
- [ ] Auto-linking uses institution + category + amount heuristics
- [ ] Manual overrides are preserved (never overwritten)
- [ ] `get_recurring_with_payoff()` enriches results with loan data
- [ ] `ends_at` and `months_remaining` populated when maturity_date exists
- [ ] `_get_recurring_monthly_total()` excludes paid-off loans when `target_month` is set
- [ ] `get_cash_flow_forecast()` passes `target_month` per projected month
- [ ] Forecast shows freed cash flow after loan payoff
- [ ] Linking wired into `detect_recurring()` pipeline
- [ ] API endpoint `GET /api/recurring/with-payoff` functional
- [ ] Backward compatibility preserved for all existing callers

## Verification

After completion, Claude will:
1. Read modified files, verify no breaking changes to existing signatures
2. Verify linking heuristics are sound and idempotent
3. Run V16 migration against current DB
4. Run import checks
5. Write pytest tests:
   a. Auto-linking matches mortgage payment to mortgage loan account
   b. Already-linked items are not overwritten
   c. `get_recurring_with_payoff()` includes maturity data
   d. Forecast correctly drops a payment after its payoff month
6. All tests pass
