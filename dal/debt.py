"""
dal/debt.py — Debt payoff planning and liability analysis.

Aggregates all liability accounts (credit cards, loans, BNPL) and models
payoff strategies to show time-to-zero and total interest cost.

Supported strategies:
  - avalanche : Highest interest rate first (mathematically optimal — minimizes total interest)
  - snowball  : Lowest balance first (psychologically motivating — fastest wins)

The calculator:
  1. Distributes minimum payments to all debts each month
  2. Applies any extra payment to the target debt (avalanche or snowball ordering)
  3. When a debt is paid off, its minimum payment rolls forward to the next debt
  4. Iterates month by month until all debts reach $0 or max_months is exceeded

Interest rates:
  - Read from `loan_details` table (field_name = 'interest_rate' or 'apr')
  - Fallback: credit cards default to 24.99%, BNPL defaults to 29.99%

Data sources for current balances:
  - Latest `balance_snapshots` entry per liability account
  - Only includes active accounts
"""

import logging
import sqlite3
from typing import Optional

log = logging.getLogger("sentry.dal.debt")

# Fallback APRs when no rate is stored
_DEFAULT_APR = {
    "credit_card": 24.99,
    "bnpl": 29.99,
    "loan": 6.5,
}

# Monthly cap on iterations (20 years)
_MAX_MONTHS = 240


# ── Data Fetching ─────────────────────────────────────────────────────────────


def _get_liability_accounts(conn: sqlite3.Connection, owner_id: str | None = None) -> list[dict]:
    """Fetch all active liability accounts with current balances and rates."""
    acct_filter = ""
    params = []
    if owner_id:
        from dal.owners import resolve_owner_account_ids
        acct_ids = resolve_owner_account_ids(conn, owner_id)
        if acct_ids:
            placeholders = ", ".join("?" for _ in acct_ids)
            acct_filter = f" AND a.id IN ({placeholders})"
            params.extend(acct_ids)

    query = f"""
        SELECT a.id, a.name, a.type,
               ABS(bs.balance) as balance
        FROM accounts a
        JOIN balance_snapshots bs ON bs.account_id = a.id
        WHERE a.type IN ('credit_card', 'loan', 'bnpl')
          AND a.is_active = 1
          {acct_filter}
          AND bs.id = (
              SELECT id FROM balance_snapshots b2
              WHERE b2.account_id = a.id
              ORDER BY b2.as_of DESC LIMIT 1
          )
          AND bs.balance != 0
        ORDER BY ABS(bs.balance) DESC
    """
    rows = conn.execute(query, params).fetchall()

    debts = []
    for r in rows:
        acct_id = r["id"]
        balance = r["balance"] or 0

        # Look up APR from loan_details
        apr = _get_loan_apr(conn, acct_id)
        if apr is None:
            apr = _DEFAULT_APR.get(r["type"], 18.0)

        # Minimum payment: 2% of balance or $25, whichever is greater
        min_payment = max(25.0, round(balance * 0.02, 2))

        debts.append({
            "account_id": acct_id,
            "name": r["name"],
            "account_type": r["type"],
            "balance": round(balance, 2),
            "apr": apr,
            "monthly_rate": apr / 100 / 12,
            "min_payment": round(min_payment, 2),
        })

    return debts


def _get_loan_apr(conn: sqlite3.Connection, account_id: str) -> Optional[float]:
    """Read APR from loan_details table. Tries both 'interest_rate' and 'apr'."""
    for field in ("interest_rate", "apr", "Interest Rate", "APR"):
        row = conn.execute(
            """
            SELECT field_value FROM loan_details
            WHERE account_id = ? AND LOWER(field_name) = LOWER(?)
            ORDER BY as_of DESC LIMIT 1
            """,
            (account_id, field),
        ).fetchone()
        if row and row["field_value"]:
            try:
                val = float(str(row["field_value"]).replace("%", "").strip())
                if 0 < val < 100:  # sanity gate
                    return val
            except (ValueError, TypeError):
                pass
    return None


# ── Payoff Calculator ──────────────────────────────────────────────────────────


def _simulate_payoff(
    debts: list[dict],
    extra_payment: float,
    strategy: str,
) -> dict:
    """
    Run a month-by-month debt payoff simulation.

    Args:
        debts: List of debt dicts with balance, monthly_rate, min_payment
        extra_payment: Additional monthly payment above minimums
        strategy: "avalanche" (high rate first) or "snowball" (low balance first)

    Returns:
        {
          total_months, total_paid, total_interest,
          payoff_schedule: [{month, balances: {account_id: balance}, total_remaining}]
          debt_payoff_order: [{account_id, name, paid_off_month, interest_paid}]
        }
    """
    import copy

    active_debts = copy.deepcopy(debts)
    for d in active_debts:
        d["interest_paid"] = 0.0
        d["paid_off_month"] = None

    total_paid = 0.0
    total_interest = 0.0
    schedule = []
    payoff_order = []

    for month in range(1, _MAX_MONTHS + 1):
        if not any(d["balance"] > 0.01 for d in active_debts):
            break

        # Sort remaining debts by strategy
        remaining = [d for d in active_debts if d["balance"] > 0.01]
        if strategy == "avalanche":
            remaining.sort(key=lambda x: x["apr"], reverse=True)
        else:  # snowball
            remaining.sort(key=lambda x: x["balance"])

        # 1. Apply interest to all debts
        for d in active_debts:
            if d["balance"] > 0.01:
                interest = round(d["balance"] * d["monthly_rate"], 2)
                d["balance"] = round(d["balance"] + interest, 2)
                d["interest_paid"] = round(d["interest_paid"] + interest, 2)
                total_interest += interest

        # 2. Pay minimums on all debts
        month_paid = 0
        for d in active_debts:
            if d["balance"] > 0.01:
                payment = min(d["min_payment"], d["balance"])
                d["balance"] = round(d["balance"] - payment, 2)
                month_paid += payment

        # 3. Apply extra payment to primary target
        extra_left = extra_payment
        for target in remaining:
            if target["balance"] <= 0.01:
                continue
            payment = min(extra_left, target["balance"])
            target["balance"] = round(target["balance"] - payment, 2)
            month_paid += payment
            extra_left -= payment
            if extra_left <= 0:
                break

        total_paid += month_paid

        # 4. Check for newly paid-off debts
        for d in active_debts:
            if d["balance"] <= 0.01 and d["paid_off_month"] is None:
                d["balance"] = 0.0
                d["paid_off_month"] = month
                payoff_order.append({
                    "account_id": d["account_id"],
                    "name": d["name"],
                    "paid_off_month": month,
                    "interest_paid": round(d["interest_paid"], 2),
                })
                # Freed-up minimum rolls into extra_payment for next month
                extra_payment += d["min_payment"]

        total_remaining = round(sum(d["balance"] for d in active_debts), 2)
        schedule.append({
            "month": month,
            "total_remaining": total_remaining,
            "month_paid": round(month_paid, 2),
        })

        if total_remaining <= 0:
            break

    return {
        "total_months": month,
        "total_paid": round(total_paid, 2),
        "total_interest": round(total_interest, 2),
        "payoff_schedule": schedule,
        "debt_payoff_order": payoff_order,
    }


# ── Main API ───────────────────────────────────────────────────────────────────


def get_debt_summary(conn: sqlite3.Connection, owner_id: str | None = None) -> dict:
    """
    Current liability snapshot: all debts, total owed, weighted average APR.
    """
    debts = _get_liability_accounts(conn, owner_id=owner_id)
    total_balance = sum(d["balance"] for d in debts)

    # Weighted average APR
    if total_balance > 0:
        weighted_apr = sum(d["balance"] * d["apr"] for d in debts) / total_balance
    else:
        weighted_apr = 0.0

    total_min_payments = sum(d["min_payment"] for d in debts)

    return {
        "total_debt": round(total_balance, 2),
        "account_count": len(debts),
        "weighted_avg_apr": round(weighted_apr, 2),
        "total_min_payments": round(total_min_payments, 2),
        "debts": debts,
    }


def get_payoff_plan(
    conn: sqlite3.Connection,
    extra_payment: float = 0.0,
    strategy: str = "avalanche",
    owner_id: str | None = None,
) -> dict:
    """
    Generate a debt payoff plan.

    Args:
        conn: DB connection
        extra_payment: Extra monthly dollars above minimums (default 0)
        strategy: "avalanche" or "snowball" (default "avalanche")

    Returns:
        {
          strategy, extra_payment,
          debts: [current debt list with apr, min_payment],
          avalanche: {...simulation...},
          snowball: {...simulation...},
          interest_savings: float  (avalanche vs snowball savings, or vs current)
        }
    """
    if strategy not in ("avalanche", "snowball"):
        raise ValueError("strategy must be 'avalanche' or 'snowball'")

    debts = _get_liability_accounts(conn, owner_id=owner_id)
    if not debts:
        return {
            "strategy": strategy,
            "extra_payment": extra_payment,
            "debts": [],
            "result": None,
            "comparison": None,
        }

    # Run both strategies for comparison
    avalanche_result = _simulate_payoff(debts, extra_payment, "avalanche")
    snowball_result = _simulate_payoff(debts, extra_payment, "snowball")

    interest_savings = round(
        snowball_result["total_interest"] - avalanche_result["total_interest"], 2
    )
    time_savings_months = snowball_result["total_months"] - avalanche_result["total_months"]

    primary = avalanche_result if strategy == "avalanche" else snowball_result

    return {
        "strategy": strategy,
        "extra_payment": extra_payment,
        "debts": debts,
        "result": {
            "strategy": strategy,
            "total_months": primary["total_months"],
            "total_paid": primary["total_paid"],
            "total_interest": primary["total_interest"],
            "payoff_schedule": primary["payoff_schedule"],
            "debt_payoff_order": primary["debt_payoff_order"],
        },
        "comparison": {
            "avalanche_months": avalanche_result["total_months"],
            "avalanche_interest": avalanche_result["total_interest"],
            "snowball_months": snowball_result["total_months"],
            "snowball_interest": snowball_result["total_interest"],
            "avalanche_saves_interest": interest_savings,
            "avalanche_saves_months": time_savings_months,
        },
    }


# ── Debt vs. Invest Comparison ─────────────────────────────────────────────────


def compare_debt_payoff_vs_invest(
    conn: sqlite3.Connection,
    loan_account_id: str,
    invest_account_id: str,
    extra_monthly: float,
    projection_months: int = 60,
) -> dict:
    """
    Compare two strategies for an extra $X/month:
      A) Pay extra on a specific loan (guaranteed APR savings)
      B) Invest in a specific investment account (variable return)

    Uses the loan's actual APR and the investment account's historical
    TWR as the expected investment return.
    """
    import copy

    # ── Validate inputs ──────────────────────────────────────────────
    if extra_monthly <= 0:
        raise ValueError("extra_monthly must be positive")
    extra_monthly = min(extra_monthly, 10000.0)
    projection_months = min(projection_months, 120)

    # ── Loan data ────────────────────────────────────────────────────
    loan_row = conn.execute(
        """
        SELECT a.id, a.name, a.type, ABS(bs.balance) as balance
        FROM accounts a
        JOIN balance_snapshots bs ON bs.account_id = a.id
        WHERE a.id = ?
          AND a.type IN ('loan', 'credit_card', 'bnpl')
          AND bs.id = (
              SELECT id FROM balance_snapshots b2
              WHERE b2.account_id = a.id
              ORDER BY b2.as_of DESC LIMIT 1
          )
        """,
        (loan_account_id,),
    ).fetchone()

    if not loan_row:
        raise LookupError(f"Loan account not found: {loan_account_id}")

    balance = loan_row["balance"] or 0
    if balance <= 0:
        raise ValueError(f"Loan {loan_account_id} has zero balance")

    apr = _get_loan_apr(conn, loan_account_id)
    if apr is None:
        apr = _DEFAULT_APR.get(loan_row["type"], 6.5)

    min_payment = max(25.0, round(balance * 0.02, 2))

    # ── Investment data ──────────────────────────────────────────────
    invest_row = conn.execute(
        """
        SELECT a.id, a.name, a.type
        FROM accounts a
        WHERE a.id = ? AND a.type IN ('investment', 'retirement')
          AND a.is_active = 1
        """,
        (invest_account_id,),
    ).fetchone()

    if not invest_row:
        raise LookupError(f"Investment account not found: {invest_account_id}")

    # Get historical TWR
    historical_twr_annual = None
    assumed_annual_return = 0.07  # 7% default
    try:
        from dal.performance import get_portfolio_performance
        perf = get_portfolio_performance(conn, invest_account_id, period="1y")
        if perf.get("portfolio_twr") is not None and perf["months_of_data"] >= 6:
            historical_twr_annual = perf["portfolio_twr"]
            assumed_annual_return = historical_twr_annual
    except Exception as e:
        log.warning("Could not get TWR for %s: %s", invest_account_id, e)

    # Ensure positive return assumption
    if assumed_annual_return <= 0:
        assumed_annual_return = 0.07

    # ── Strategy A: Pay extra on loan ────────────────────────────────
    loan_debt = {
        "account_id": loan_account_id,
        "name": loan_row["name"],
        "account_type": loan_row["type"],
        "balance": round(balance, 2),
        "apr": apr,
        "monthly_rate": apr / 100 / 12,
        "min_payment": min_payment,
    }

    # Simulate original payoff (minimum only)
    original_result = _simulate_payoff([copy.deepcopy(loan_debt)], 0.0, "avalanche")
    original_payoff_months = original_result["total_months"]
    original_total_interest = original_result["total_interest"]

    # Simulate accelerated payoff (minimum + extra)
    accel_result = _simulate_payoff([copy.deepcopy(loan_debt)], extra_monthly, "avalanche")
    accelerated_payoff_months = accel_result["total_months"]
    accelerated_total_interest = accel_result["total_interest"]

    interest_saved = round(original_total_interest - accelerated_total_interest, 2)
    months_saved = original_payoff_months - accelerated_payoff_months

    # After loan payoff, freed payment (min + extra) invested for remaining months
    monthly_invest_rate = (1 + assumed_annual_return) ** (1 / 12) - 1
    freed_monthly = min_payment + extra_monthly
    remaining_months = max(0, projection_months - accelerated_payoff_months)

    # Compound freed payment for remaining months
    freed_investment_value = 0.0
    for _ in range(remaining_months):
        freed_investment_value = freed_investment_value * (1 + monthly_invest_rate) + freed_monthly

    total_cost_strategy_a = round(
        (min_payment + extra_monthly) * min(accelerated_payoff_months, projection_months),
        2,
    )

    strategy_a_net_benefit = round(interest_saved + freed_investment_value, 2)

    # ── Strategy B: Invest the extra ─────────────────────────────────
    invest_balance = 0.0
    total_contributions = 0.0
    for _ in range(projection_months):
        invest_balance = invest_balance * (1 + monthly_invest_rate) + extra_monthly
        total_contributions += extra_monthly

    projected_value = round(invest_balance, 2)
    total_contributions = round(total_contributions, 2)
    total_growth = round(projected_value - total_contributions, 2)

    # Effective annual return
    if total_contributions > 0 and projected_value > 0 and projection_months > 0:
        effective_annual = round(
            ((projected_value / total_contributions) ** (12 / projection_months) - 1), 4
        )
    else:
        effective_annual = 0.0

    strategy_b_net_benefit = total_growth

    # ── Comparison ───────────────────────────────────────────────────
    if strategy_a_net_benefit >= strategy_b_net_benefit:
        better_strategy = "pay_debt"
        net_advantage = round(strategy_a_net_benefit - strategy_b_net_benefit, 2)
    else:
        better_strategy = "invest"
        net_advantage = round(strategy_b_net_benefit - strategy_a_net_benefit, 2)

    # Break-even rate: the APR is the baseline; adjusted for reinvestment
    break_even_rate = round(apr / 100, 4)

    # Build recommendation string
    if better_strategy == "invest":
        recommendation = (
            f"Investing the extra ${extra_monthly:,.0f}/month in {invest_row['name']} "
            f"is projected to earn ${net_advantage:,.2f} more than paying off "
            f"{loan_row['name']} early, assuming a "
            f"{assumed_annual_return * 100:.1f}% annual return continues."
        )
    else:
        recommendation = (
            f"Paying off {loan_row['name']} early saves "
            f"${interest_saved:,.2f} in guaranteed interest — "
            f"a better deal than the projected "
            f"{assumed_annual_return * 100:.1f}% investment return "
            f"(net advantage: ${net_advantage:,.2f})."
        )

    return {
        "loan": {
            "account_id": loan_account_id,
            "name": loan_row["name"],
            "current_balance": round(balance, 2),
            "apr": apr,
            "min_payment": min_payment,
            "original_payoff_months": original_payoff_months,
            "original_total_interest": round(original_total_interest, 2),
            "accelerated_payoff_months": accelerated_payoff_months,
            "accelerated_total_interest": round(accelerated_total_interest, 2),
            "interest_saved": interest_saved,
            "months_saved": months_saved,
            "total_cost_strategy_a": total_cost_strategy_a,
        },
        "investment": {
            "account_id": invest_account_id,
            "name": invest_row["name"],
            "historical_twr_annual": round(historical_twr_annual, 4) if historical_twr_annual else None,
            "assumed_annual_return": round(assumed_annual_return, 4),
            "projected_value": projected_value,
            "total_contributions": total_contributions,
            "total_growth": total_growth,
            "effective_annual_return": effective_annual,
        },
        "comparison": {
            "extra_monthly": round(extra_monthly, 2),
            "projection_months": projection_months,
            "strategy_a_net_benefit": strategy_a_net_benefit,
            "strategy_b_net_benefit": round(strategy_b_net_benefit, 2),
            "better_strategy": better_strategy,
            "net_advantage": net_advantage,
            "break_even_rate": break_even_rate,
            "recommendation": recommendation,
        },
    }

