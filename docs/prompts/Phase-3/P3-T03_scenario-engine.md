# P3-T03: Scenario Projection Engine

## Context

You are working on Sentry Finance, a local-first personal finance app.
The existing forecasting engine (`dal/forecasting.py`) projects future
months using averages from the past. But it can't answer "what if"
questions:

- **"What happens to my net worth if I pay off the car loan early?"**
- **"How does taking a pay cut affect my 5-year trajectory?"**
- **"What if I make a $30K down payment on a rental property in October?"**

The user needs a **scenario projection engine** that takes the current
trajectory as a baseline and overlays user-defined future events on top.
This produces a multi-year cash flow and net worth projection.

### Important: Baseline income is lump-sum-clean

The `build_seasonal_income_model()` (P3-T01) already excludes non-recurring
income from the historical record before building the income model. This means:

- VA disability back-pay ($20–30K lump sums in "VA Benefits") are excluded
- Insurance settlements ("Non-Recurring Income" category) are excluded
- Federal/state tax refunds ("Tax Refund" category) are excluded

**The baseline projection will therefore NOT match raw historical cash flow
in months where these events occurred.** This is intentional — the baseline
represents sustainable recurring income, not one-time windfalls. If the user
wants to model a future potential lump sum (e.g., "what if I receive another
insurance settlement"), they use the `one_time` event type in their scenario.

## Starting State

- `dal/forecasting.py` — `get_cash_flow_forecast()` produces flat monthly projections
- `dal/forecasting.py` — `build_seasonal_income_model()` (P3-T01) provides seasonal income
- `dal/recurring.py` — `get_recurring_with_payoff()` (P3-T02) knows when recurring payments end
- `dal/debt.py` — `get_debt_summary()`, `get_payoff_plan()` for liability modeling
- `dal/derived.py` — `compute_net_worth_velocity()` for current trajectory
- `dal/reports.py` — `get_net_worth_history()` for historical net worth
- No scenario storage or projection module exists yet

## Task

### 1. Create `dal/scenarios.py`

New module with the scenario projection engine:

```python
"""
dal/scenarios.py — What-if scenario projection engine.

Accepts a list of future events and overlays them on the current financial
trajectory. Produces a multi-year month-by-month cash flow and net worth
projection.

Event types:
  - income_change:     Permanent or temporary income adjustment
  - expense_change:    New recurring expense or expense removal
  - one_time:          Single large transaction (purchase, windfall)
  - loan_payoff:       Accelerated loan payoff (lump sum)
  - investment_return: Override investment growth rate assumption

Events are applied chronologically. Each month's projection builds on
the previous.
"""

import logging
import sqlite3
from datetime import datetime
from typing import Optional

log = logging.getLogger("sentry.dal.scenarios")


def project_scenario(
    conn: sqlite3.Connection,
    events: list[dict],
    months: int = 60,      # 5-year default
    use_seasonal: bool = True,
) -> dict:
    """
    Project a multi-year financial scenario.

    Args:
        conn: DB connection (read-only usage for baseline)
        events: List of future event dicts (see Event Types below)
        months: Number of months to project forward (max 120 = 10 years)
        use_seasonal: Use seasonal income model if available

    Returns:
    {
        "months": int,
        "baseline": [
            {
                "month": "YYYY-MM",
                "income": float,
                "spending": float,
                "net_cash_flow": float,
                "liquid_balance": float,
                "net_worth": float,
            }, ...
        ],
        "scenario": [
            {
                "month": "YYYY-MM",
                "income": float,
                "spending": float,
                "net_cash_flow": float,
                "liquid_balance": float,
                "net_worth": float,
                "events_applied": [str],   # event descriptions active this month
            }, ...
        ],
        "summary": {
            "baseline_end_net_worth": float,
            "scenario_end_net_worth": float,
            "net_worth_delta": float,        # scenario - baseline
            "total_events_impact": float,    # aggregate $ impact of all events
            "freed_cash_flow_monthly": float, # if loan payoffs freed cash
        },
        "events_applied": [
            {"month": "YYYY-MM", "description": str, "impact": float}, ...
        ],
    }
    """
```

**Event types (the `events` list):**

```python
# Income change
{
    "type": "income_change",
    "start_month": "2026-09",         # when the change takes effect
    "end_month": "2027-06" | None,    # None = permanent
    "amount": -500.0,                 # negative = income reduction
    "description": "Teaching stipend ends",
}

# Expense change (new or removed recurring)
{
    "type": "expense_change",
    "start_month": "2026-10",
    "end_month": None,
    "amount": 200.0,                  # positive = new expense
    "description": "New gym membership",
}

# One-time transaction
{
    "type": "one_time",
    "month": "2026-10",
    "amount": -30000.0,               # negative = outflow (purchase)
    "description": "Rental property down payment",
    "affects": "liquid_balance",       # or "net_worth" (e.g., adds an asset)
}

# Loan payoff (accelerated)
{
    "type": "loan_payoff",
    "month": "2026-08",
    "account_id": "nfcu_1234",        # the loan account to pay off
    "description": "Pay off car loan early",
    # Engine auto-calculates: lump sum from current balance,
    # freed monthly payment, and reduced interest
}

# Investment growth rate override
{
    "type": "investment_return",
    "annual_rate": 0.08,              # 8% annual return assumption
    "description": "Conservative growth estimate",
}
```

**Baseline projection algorithm:**
1. Start with current `liquid_balance` (from `_get_current_balance()`)
   and current `net_worth` (from `recompute_net_worth()`)
2. For each month:
   - Income: from seasonal model (P3-T01) or flat average
   - Spending: from recurring + discretionary (existing logic)
   - Recurring payments stop at maturity dates (P3-T02)
   - Investment accounts grow at historical TWR (from `dal/performance.py`)
     or a default 7% annual rate
   - `liquid_balance += income - spending`
   - `net_worth = liquid_balance + investment_values + real_estate - liabilities`

**Scenario projection algorithm:**
1. Start from the same initial state as baseline
2. Apply all events chronologically:
   - `income_change`: adjust monthly income for the duration
   - `expense_change`: adjust monthly spending for the duration
   - `one_time`: apply in the specified month (deduct from liquid_balance)
   - `loan_payoff`: deduct remaining balance from liquid_balance, stop
     the recurring payment, stop interest accumulation
   - `investment_return`: override the growth rate for investments

### 2. API Endpoints

Add to `backend/routers/reports.py`:

```python
from pydantic import BaseModel

class ScenarioEvent(BaseModel):
    type: str          # income_change, expense_change, one_time, loan_payoff, investment_return
    month: str | None = None
    start_month: str | None = None
    end_month: str | None = None
    amount: float | None = None
    annual_rate: float | None = None
    account_id: str | None = None
    affects: str | None = None
    description: str = ""

class ScenarioRequest(BaseModel):
    events: list[ScenarioEvent]
    months: int = 60
    use_seasonal: bool = True

@router.post("/api/scenarios/project")
def project_scenario_endpoint(body: ScenarioRequest):
    with get_db() as conn:
        return project_scenario(
            conn,
            events=[e.model_dump() for e in body.events],
            months=min(body.months, 120),
            use_seasonal=body.use_seasonal,
        )
```

## Files to Create

1. `dal/scenarios.py`

## Files to Modify

2. `backend/routers/reports.py` — add scenario endpoint

## Files NOT to Modify

- `dal/forecasting.py` — call its functions, don't modify
- `dal/recurring.py` — call `get_recurring_with_payoff()`, don't modify
- `dal/debt.py` — call `get_debt_summary()`, don't modify
- Any frontend files
- Database migrations (no schema changes — scenarios are computed, not stored)

## Constraints

- Scenarios are **stateless computed projections** — they are NOT stored
  in the database. The engine runs on demand and returns results
- The baseline projection must use the SAME logic as `get_cash_flow_forecast()`
  for the first N months, extended further. Do NOT duplicate the rolling
  average or recurring logic — call the existing functions
- Investment growth: use TWR from `dal/performance.py` for accounts that
  have enough history; default to 7% annual for accounts without data
- The `loan_payoff` event must be consistent with `dal/debt.py` data:
  look up the actual remaining balance and monthly payment, don't guess
- Maximum projection length: 120 months (10 years). Reject longer requests
- Cap events list at 20 events per request
- All dollar values rounded to 2 decimal places
- Month strings must be "YYYY-MM" format
- The response MUST include both `baseline` (no events) and `scenario`
  (with events) arrays so the frontend can overlay them on the same chart

## Done Checklist

- [ ] `dal/scenarios.py` created with `project_scenario()` function
- [ ] Baseline projection uses existing forecasting + debt + recurring data
- [ ] `income_change` events adjust monthly income correctly
- [ ] `expense_change` events adjust monthly spending correctly
- [ ] `one_time` events apply in the specified month
- [ ] `loan_payoff` events deduct balance, free recurring payment, stop interest
- [ ] `investment_return` events override growth rate
- [ ] Response includes both `baseline` and `scenario` arrays
- [ ] Summary computes `net_worth_delta` and `freed_cash_flow_monthly`
- [ ] API endpoint `POST /api/scenarios/project` with Pydantic validation
- [ ] Events list capped at 20, months capped at 120
- [ ] Handles edge cases: no events (baseline = scenario), no loans, no investments

## Verification

After completion, Claude will:
1. Read `dal/scenarios.py`, verify it calls (not duplicates) existing functions
2. Verify event types are all handled
3. Run import check
4. Write pytest tests:
   a. Baseline with no events matches existing forecast
   b. Income change increases net worth over projection period
   c. One-time purchase reduces liquid balance in the correct month
   d. Loan payoff frees monthly cash flow from the correct month forward
   e. Summary delta equals scenario end NW minus baseline end NW
5. All tests pass
