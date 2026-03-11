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


def _get_liability_accounts(conn: sqlite3.Connection) -> list[dict]:
    """Fetch all active liability accounts with current balances and rates."""
    rows = conn.execute(
        """
        SELECT a.id, a.name, a.type,
               ABS(bs.balance) as balance
        FROM accounts a
        JOIN balance_snapshots bs ON bs.account_id = a.id
        WHERE a.type IN ('credit_card', 'loan', 'bnpl')
          AND a.is_active = 1
          AND bs.id = (
              SELECT id FROM balance_snapshots b2
              WHERE b2.account_id = a.id
              ORDER BY b2.as_of DESC LIMIT 1
          )
          AND bs.balance != 0
        ORDER BY ABS(bs.balance) DESC
        """
    ).fetchall()

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


def get_debt_summary(conn: sqlite3.Connection) -> dict:
    """
    Current liability snapshot: all debts, total owed, weighted average APR.
    """
    debts = _get_liability_accounts(conn)
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

    debts = _get_liability_accounts(conn)
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
