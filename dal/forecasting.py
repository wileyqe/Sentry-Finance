"""
dal/forecasting.py — Cash flow forecasting engine.

Projects future monthly income, spending, and running balance N months
forward by combining two data sources:

  1. Known recurring transactions (baseline — high confidence)
     - Active recurring items from recurring_transactions table
     - Normalized to monthly amounts by frequency

  2. Discretionary rolling average (remaining spend — moderate confidence)
     - Last M months of actual spending per category
     - Subtract recurring baseline to avoid double-counting
     - Categories excluded from budgeting (Transfers, etc.) are excluded

Algorithm per month:
  projected_income   = avg monthly income (last M months, non-transfer credits)
  projected_spending = recurring_monthly_total + avg_discretionary_monthly
  projected_balance  = prev_balance + projected_income - projected_spending

Returns a list of monthly forecast dicts, one per projected month.
"""

import logging
import sqlite3
from datetime import datetime
from typing import Optional

log = logging.getLogger("sentry.dal.forecasting")

# Categories to exclude from spending forecast (not real expenditures)
_EXCLUDED_CATEGORIES = {
    "Transfers",
    "Credit Card Payments",
    "Deposits",
    "Tax Refund",
    "Refunds/Adjustments",
}

# Frequency → monthly multiplier
_MONTHLY_FACTORS = {
    "weekly": 4.33,
    "biweekly": 2.17,
    "monthly": 1.0,
    "bimonthly": 0.5,
    "quarterly": 0.333,
    "semiannual": 0.167,
    "annual": 0.083,
}


def _get_current_balance(
    conn: sqlite3.Connection,
    account_ids: Optional[list[str]] = None,
) -> float:
    """Sum of latest balances across liquid accounts (checking + savings)."""
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        rows = conn.execute(
            f"""
            SELECT bs.balance
            FROM balance_snapshots bs
            JOIN accounts a ON a.id = bs.account_id
            WHERE a.type IN ('checking', 'savings')
              AND a.id IN ({placeholders})
              AND bs.id = (
                  SELECT id FROM balance_snapshots b2
                  WHERE b2.account_id = bs.account_id
                  ORDER BY b2.as_of DESC LIMIT 1
              )
            """,
            account_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT bs.balance
            FROM balance_snapshots bs
            JOIN accounts a ON a.id = bs.account_id
            WHERE a.type IN ('checking', 'savings')
              AND bs.id = (
                  SELECT id FROM balance_snapshots b2
                  WHERE b2.account_id = bs.account_id
                  ORDER BY b2.as_of DESC LIMIT 1
              )
            """
        ).fetchall()

    return sum((r["balance"] or 0) for r in rows)


def _get_recurring_monthly_total(
    conn: sqlite3.Connection,
    account_ids: Optional[list[str]] = None,
) -> float:
    """Monthly total of active, stable-amount recurring expenses."""
    clauses = [
        "status = 'active'",
        "amount_stable = 1",
        "expected_amount IS NOT NULL",
    ]
    params: list = []

    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        clauses.append(f"account_id IN ({placeholders})")
        params.extend(account_ids)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT frequency, expected_amount, category FROM recurring_transactions WHERE {where}",
        params,
    ).fetchall()

    total = 0.0
    for r in rows:
        cat = r["category"] or "Uncategorized"
        if cat in _EXCLUDED_CATEGORIES:
            continue
        factor = _MONTHLY_FACTORS.get(r["frequency"], 1.0)
        total += (r["expected_amount"] or 0) * factor

    return round(total, 2)


def _get_rolling_averages(
    conn: sqlite3.Connection,
    months_back: int = 3,
    account_ids: Optional[list[str]] = None,
) -> tuple[float, float]:
    """
    Compute rolling average monthly income and discretionary spending.

    Returns:
        (avg_income, avg_discretionary_spending)  — both positive floats
    """
    excluded_list = list(_EXCLUDED_CATEGORIES)
    excl_placeholders = ", ".join("?" for _ in excluded_list)

    base_params: list = excluded_list
    acct_filter = ""
    if account_ids:
        acct_placeholders = ", ".join("?" for _ in account_ids)
        acct_filter = f" AND account_id IN ({acct_placeholders})"
        base_params = excluded_list + account_ids

    # Monthly spending (debits only, excluding excluded categories)
    spend_rows = conn.execute(
        f"""
        SELECT strftime('%Y-%m', posting_date) as month,
               SUM(amount) as total
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND posting_date >= date('now', '-{months_back} months')
          AND direction = 'Debit'
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
          {acct_filter}
        GROUP BY month
        """,
        base_params,
    ).fetchall()

    # Monthly income (credits only, excluding excluded categories)
    income_rows = conn.execute(
        f"""
        SELECT strftime('%Y-%m', posting_date) as month,
               SUM(signed_amount) as total
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND posting_date >= date('now', '-{months_back} months')
          AND direction = 'Credit'
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
          {acct_filter}
        GROUP BY month
        """,
        base_params,
    ).fetchall()

    spend_vals = [r["total"] or 0 for r in spend_rows if r["total"]]
    income_vals = [r["total"] or 0 for r in income_rows if r["total"]]

    avg_spending = sum(spend_vals) / len(spend_vals) if spend_vals else 0
    avg_income = sum(income_vals) / len(income_vals) if income_vals else 0

    return round(avg_income, 2), round(avg_spending, 2)


def get_cash_flow_forecast(
    conn: sqlite3.Connection,
    months: int = 6,
    history_months: int = 3,
    account_ids: Optional[list[str]] = None,
) -> dict:
    """
    Project cash flow for the next N months.

    Args:
        conn: Active database connection.
        months: Number of months to project forward (default 6).
        history_months: Months of history to use for rolling averages.
        account_ids: Restrict to specific accounts (None = all).

    Returns:
        {
          "current_balance": float,
          "recurring_monthly": float,
          "avg_income": float,
          "avg_discretionary": float,
          "months": [
            {
              "month": "YYYY-MM",
              "projected_income": float,
              "projected_spending": float,
              "projected_net": float,
              "projected_balance": float,
            }, ...
          ]
        }
    """
    current_balance = _get_current_balance(conn, account_ids)
    recurring_monthly = _get_recurring_monthly_total(conn, account_ids)
    avg_income, avg_total_spending = _get_rolling_averages(
        conn, history_months, account_ids
    )

    # Discretionary = total avg spending minus the recognized recurring portion
    # (prevents double-counting recurring bills that are already in avg_total_spending)
    discretionary = max(0.0, round(avg_total_spending - recurring_monthly, 2))
    projected_monthly_spending = round(recurring_monthly + discretionary, 2)

    log.info(
        "Forecast inputs: balance=%.2f recurring=%.2f avg_income=%.2f discretionary=%.2f",
        current_balance,
        recurring_monthly,
        avg_income,
        discretionary,
    )

    now = datetime.utcnow()
    running_balance = current_balance
    forecast = []

    for i in range(1, months + 1):
        # Advance month
        total_months = now.month + i - 1
        year = now.year + total_months // 12
        month = (total_months % 12) or 12
        if total_months % 12 == 0:
            year -= 1
        month_str = f"{year}-{month:02d}"

        net = round(avg_income - projected_monthly_spending, 2)
        running_balance = round(running_balance + net, 2)

        forecast.append({
            "month": month_str,
            "projected_income": round(avg_income, 2),
            "projected_spending": projected_monthly_spending,
            "projected_net": net,
            "projected_balance": running_balance,
        })

    return {
        "current_balance": round(current_balance, 2),
        "recurring_monthly": recurring_monthly,
        "avg_income": avg_income,
        "avg_discretionary": discretionary,
        "history_months_used": history_months,
        "months": forecast,
    }
