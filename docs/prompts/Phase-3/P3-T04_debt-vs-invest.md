# P3-T04: Debt Payoff vs. Invest Comparison

## Context

You are working on Sentry Finance, a local-first personal finance app.
The user frequently faces a classic personal finance question: **"Should
I pay extra on my car loan (5.49% APR) or put that money in Fidelity
(historically ~10% TWR)?"**

The math isn't trivial because:
- Debt payoff provides a guaranteed "return" equal to the APR
- Investing provides a variable return with compounding
- The loan has a fixed term — paying it off early frees the monthly payment
- Tax implications may apply (mortgage interest is deductible)
- Opportunity cost cuts both ways

This task builds a comparison calculator that uses the user's actual loan
data and actual investment returns to produce a concrete, personalized
recommendation.

## Starting State

- `dal/debt.py` — `_get_liability_accounts()` returns loans with APR,
  balance, minimum payment. `_get_loan_apr()` reads from `loan_details`.
  `_simulate_payoff()` runs month-by-month debt simulation
- `dal/performance.py` — `get_portfolio_performance()` computes TWR for
  investment accounts. `get_all_accounts_performance()` returns all
- `loan_details` table — key-value store per account (`interest_rate`,
  `maturity_date`, `original_amount`, `remaining_term`)
- `accounts` table — types include `loan`, `credit_card`, `bnpl`,
  `investment`, `retirement`

## Task

### 1. New Function: `compare_debt_payoff_vs_invest()`

Add to `dal/debt.py`:

```python
def compare_debt_payoff_vs_invest(
    conn: sqlite3.Connection,
    loan_account_id: str,
    invest_account_id: str,
    extra_monthly: float,
    projection_months: int = 60,   # 5 years
) -> dict:
    """
    Compare two strategies for an extra $X/month:
      A) Pay extra on a specific loan (guaranteed APR savings)
      B) Invest in a specific investment account (variable return)

    Uses the loan's actual APR and the investment account's historical
    TWR as the expected investment return.

    Args:
        conn: DB connection
        loan_account_id: ID of the loan to pay down
        invest_account_id: ID of the investment account to compare
        extra_monthly: Dollar amount of extra monthly payment to allocate
        projection_months: How far to project (default 60 = 5 years)

    Returns:
    {
        "loan": {
            "account_id": str,
            "name": str,
            "current_balance": float,
            "apr": float,
            "min_payment": float,
            "original_payoff_months": int,     # without extra payments
            "original_total_interest": float,
            "accelerated_payoff_months": int,  # with extra payments
            "accelerated_total_interest": float,
            "interest_saved": float,           # original - accelerated
            "months_saved": int,
            "total_cost_strategy_a": float,    # total money spent on loan
        },
        "investment": {
            "account_id": str,
            "name": str,
            "historical_twr_annual": float | None,   # from dal/performance.py
            "assumed_annual_return": float,           # TWR or fallback 7%
            "projected_value": float,  # value of extra $X/month after N months
            "total_contributions": float,   # extra_monthly × months
            "total_growth": float,          # projected_value - total_contributions
            "effective_annual_return": float,
        },
        "comparison": {
            "extra_monthly": float,
            "projection_months": int,
            "strategy_a_net_benefit": float,   # interest saved by paying loan
            "strategy_b_net_benefit": float,   # investment growth
            "better_strategy": "pay_debt" | "invest",
            "net_advantage": float,            # |B - A| — how much better
            "break_even_rate": float,          # investment return needed to match debt APR
            "recommendation": str,             # Human-readable recommendation
        },
    }
    """
```

**Strategy A: Pay extra on loan**
- Take the loan's current balance, APR, and minimum payment
- Simulate payoff with minimum payment only → `original_payoff_months`,
  `original_total_interest`
- Simulate payoff with minimum + extra → `accelerated_payoff_months`,
  `accelerated_total_interest`
- `interest_saved = original_total_interest - accelerated_total_interest`
- After the loan is paid off, the freed payment (min + extra) compounds
  in a hypothetical investment at the same rate for the remaining months.
  This prevents Strategy A from being unfairly penalized for locking up
  cash in debt payoff

**Strategy B: Invest the extra**
- Use historical TWR from `get_portfolio_performance()` for the investment
  account. If TWR is available, annualize it. If not, use 7% as a default
- Monthly return = `(1 + annual_return) ^ (1/12) - 1`
- Each month: `balance = balance × (1 + monthly_return) + extra_monthly`
- After `projection_months`, report the projected value

**Comparison:**
- `strategy_a_net_benefit = interest_saved + (freed payment invested for remaining months)`
- `strategy_b_net_benefit = total_growth` (investment gains)
- `better_strategy`: whichever net benefit is higher
- `break_even_rate`: the investment annual return at which both strategies
  produce equal outcomes. This is approximately the loan's APR, but
  adjusted for the compounding effect and freed-payment reinvestment
- `recommendation`: Plain English string like:
  - "Investing the extra $200/month in Fidelity is projected to earn $3,400 more than paying off the car loan early, assuming an 8.2% annual return continues."
  - "Paying off the car loan early saves $1,200 in guaranteed interest — a better deal than the projected 5.1% investment return."

### 2. API Endpoint

Add to `backend/routers/reports.py`:

```python
class DebtVsInvestRequest(BaseModel):
    loan_account_id: str
    invest_account_id: str
    extra_monthly: float
    projection_months: int = 60

@router.post("/api/analysis/debt-vs-invest")
def debt_vs_invest(body: DebtVsInvestRequest):
    with get_db() as conn:
        return compare_debt_payoff_vs_invest(
            conn,
            body.loan_account_id,
            body.invest_account_id,
            body.extra_monthly,
            min(body.projection_months, 120),
        )
```

### 3. Convenience: Per-loan summary

Add a helper endpoint that lists eligible comparisons:

```python
@router.get("/api/analysis/debt-vs-invest/options")
def debt_vs_invest_options():
    """List all active loans and investment accounts available for comparison."""
    with get_db() as conn:
        loans = conn.execute("""
            SELECT a.id, a.name, a.type, ABS(bs.balance) as balance
            FROM accounts a
            JOIN balance_snapshots bs ON bs.account_id = a.id
            WHERE a.type IN ('loan', 'credit_card', 'bnpl')
              AND a.is_active = 1
              AND bs.id = (SELECT id FROM balance_snapshots b2
                           WHERE b2.account_id = a.id ORDER BY b2.as_of DESC LIMIT 1)
              AND bs.balance != 0
        """).fetchall()

        investments = conn.execute("""
            SELECT a.id, a.name, a.type
            FROM accounts a
            WHERE a.type IN ('investment', 'retirement')
              AND a.is_active = 1
        """).fetchall()

    return {
        "loans": [dict(r) for r in loans],
        "investments": [dict(r) for r in investments],
    }
```

## Files to Modify

1. `dal/debt.py` — add `compare_debt_payoff_vs_invest()`
2. `backend/routers/reports.py` — add endpoints

## Files NOT to Modify

- `dal/performance.py` — call `get_portfolio_performance()`, don't modify
- `dal/forecasting.py` — no changes needed
- Any frontend files
- Database migrations (no schema changes)

## Constraints

- The comparison must use the user's **actual** APR from `loan_details`,
  not a hardcoded rate. Fall back to `_DEFAULT_APR` only if loan_details
  is empty
- The investment return assumption must prefer the account's **actual**
  historical TWR. Fall back to 7% only when TWR data is unavailable
- The `_simulate_payoff()` function already exists in `dal/debt.py` —
  reuse it, do NOT write a new payoff simulator
- Strategy A (pay debt) must account for freed cash flow being reinvested
  after the loan is paid off, to make the comparison fair
- Cap `extra_monthly` at $10,000 and `projection_months` at 120
- Reject invalid inputs: non-existent account IDs (HTTP 404), negative
  extra_monthly (HTTP 422), zero-balance loan (HTTP 422)
- Round all dollar values to 2 decimal places
- Round percentages to 2 decimal places
- Round rates to 4 decimal places
- The recommendation string must include specific dollar amounts and
  the assumed investment return rate — not vague advice

## Done Checklist

- [ ] `compare_debt_payoff_vs_invest()` exists in `dal/debt.py`
- [ ] Uses `_simulate_payoff()` for payoff simulation (not duplicated)
- [ ] Uses `get_portfolio_performance()` for historical TWR
- [ ] Strategy A accounts for freed payment reinvestment after payoff
- [ ] Strategy B uses compound growth with monthly contributions
- [ ] `break_even_rate` computed correctly
- [ ] `recommendation` is a concrete, readable sentence with dollar amounts
- [ ] API endpoint `POST /api/analysis/debt-vs-invest` validates input
- [ ] API endpoint `GET /api/analysis/debt-vs-invest/options` lists eligible accounts
- [ ] Handles edge cases: no TWR data, zero balance loan, loan already in payoff
- [ ] Rejects invalid accounts with proper HTTP status codes

## Verification

After completion, Claude will:
1. Read `dal/debt.py` and verify `_simulate_payoff()` is reused
2. Verify the freed-payment reinvestment logic in Strategy A
3. Verify the compound growth formula in Strategy B
4. Run import check
5. Write pytest tests:
   a. Loan with 5% APR vs. 10% investment → invest wins
   b. Loan with 20% APR vs. 7% investment → pay debt wins
   c. Break-even rate is approximately the loan APR
   d. Recommendation string contains dollar amounts
   e. Invalid account ID returns 404
   f. Zero balance loan returns 422
6. All tests pass
