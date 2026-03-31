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
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("sentry.dal.scenarios")

# Default investment growth rate (7% annual) if no TWR data
_DEFAULT_ANNUAL_RETURN = 0.07


def project_scenario(
    conn: sqlite3.Connection,
    events: list[dict],
    months: int = 60,
    use_seasonal: bool = True,
) -> dict:
    """
    Project a multi-year financial scenario.

    Args:
        conn: DB connection (read-only usage for baseline)
        events: List of future event dicts (see Event Types)
        months: Number of months to project forward (max 120 = 10 years)
        use_seasonal: Use seasonal income model if available

    Returns:
    {
        "months": int,
        "baseline": [{month, income, spending, net_cash_flow, liquid_balance, net_worth}],
        "scenario": [{..., events_applied: [str]}],
        "summary": {baseline_end_net_worth, scenario_end_net_worth, net_worth_delta, ...},
        "events_applied": [{month, description, impact}],
    }
    """
    # Validate
    months = min(months, 120)
    events = (events or [])[:20]  # Cap at 20 events

    # ── Gather baseline data ─────────────────────────────────────────
    from dal.forecasting import (
        _get_current_balance,
        _get_rolling_averages,
        _get_recurring_monthly_total,
        build_seasonal_income_model,
    )
    from dal.derived import recompute_net_worth

    current_liquid = _get_current_balance(conn)
    avg_income, avg_spending = _get_rolling_averages(conn, months_back=6)

    # Seasonal income model
    seasonal_model = None
    if use_seasonal:
        seasonal_model = build_seasonal_income_model(conn)
        if seasonal_model.get("income_model") not in ("seasonal",):
            seasonal_model = None  # Fall back to flat

    # Current net worth
    try:
        current_net_worth = recompute_net_worth(conn)
    except Exception:
        current_net_worth = current_liquid

    # Investment value (for growth projection)
    invest_value = _get_total_investment_value(conn)

    # Real estate value
    re_value = _get_real_estate_value(conn)

    # Liability total
    liability_total = _get_liability_total(conn)

    # Investment annual return (try to compute from performance)
    investment_annual_return = _get_historical_return(conn)

    # Recurring with payoff data (for baseline recurring stops)
    recurring_monthly = _get_recurring_monthly_total(conn)

    # ── Build event index for quick lookup ────────────────────────────
    events_by_month: dict[str, list[dict]] = defaultdict(list)
    ongoing_income_changes: list[dict] = []
    ongoing_expense_changes: list[dict] = []
    investment_rate_override: Optional[float] = None
    loan_payoffs: dict[str, dict] = {}  # month -> event info

    for evt in events:
        etype = evt.get("type", "")
        if etype == "one_time":
            m = evt.get("month", "")
            if m:
                events_by_month[m].append(evt)
        elif etype == "loan_payoff":
            m = evt.get("month", "")
            if m:
                events_by_month[m].append(evt)
        elif etype == "income_change":
            ongoing_income_changes.append(evt)
        elif etype == "expense_change":
            ongoing_expense_changes.append(evt)
        elif etype == "investment_return":
            rate = evt.get("annual_rate")
            if rate is not None:
                investment_rate_override = rate

    if investment_rate_override is not None:
        investment_annual_return = investment_rate_override

    monthly_invest_rate = (1 + investment_annual_return) ** (1 / 12) - 1

    # ── Project baseline and scenario month-by-month ─────────────────
    now = datetime.now(timezone.utc)

    baseline: list[dict] = []
    scenario: list[dict] = []
    events_applied_log: list[dict] = []

    # Baseline state
    bl_liquid = current_liquid
    bl_invest = invest_value
    bl_liabilities = liability_total

    # Scenario state
    sc_liquid = current_liquid
    sc_invest = invest_value
    sc_liabilities = liability_total
    sc_freed_payments: float = 0.0  # Monthly cash freed by paid-off loans

    for i in range(1, months + 1):
        total_months = now.month + i - 1
        year = now.year + total_months // 12
        month = (total_months % 12) or 12
        if total_months % 12 == 0:
            year -= 1
        month_str = f"{year}-{month:02d}"

        # ── Determine monthly income ─────────────────────────────────
        if seasonal_model:
            base_income = seasonal_model["composite_monthly"].get(month, avg_income)
        else:
            base_income = avg_income

        # Recurring spending (may vary by month as loans pay off)
        base_spending = _get_recurring_monthly_total(conn, target_month=month_str)
        discretionary = max(0.0, avg_spending - recurring_monthly)
        base_total_spending = base_spending + discretionary

        # ── BASELINE projection ──────────────────────────────────────
        bl_income = round(base_income, 2)
        bl_spend = round(base_total_spending, 2)
        bl_net = round(bl_income - bl_spend, 2)
        bl_liquid = round(bl_liquid + bl_net, 2)
        bl_invest = round(bl_invest * (1 + monthly_invest_rate), 2)
        bl_nw = round(bl_liquid + bl_invest + re_value + bl_liabilities, 2)

        baseline.append({
            "month": month_str,
            "income": bl_income,
            "spending": bl_spend,
            "net_cash_flow": bl_net,
            "liquid_balance": bl_liquid,
            "net_worth": bl_nw,
        })

        # ── SCENARIO projection ──────────────────────────────────────
        sc_income = base_income
        sc_spend = base_total_spending
        month_events_applied: list[str] = []

        # Apply ongoing income changes
        for ic in ongoing_income_changes:
            start = ic.get("start_month", "")
            end = ic.get("end_month")
            if start and month_str >= start:
                if end is None or month_str <= end:
                    sc_income += ic.get("amount", 0)
                    month_events_applied.append(ic.get("description", "Income change"))

        # Apply ongoing expense changes
        for ec in ongoing_expense_changes:
            start = ec.get("start_month", "")
            end = ec.get("end_month")
            if start and month_str >= start:
                if end is None or month_str <= end:
                    sc_spend += ec.get("amount", 0)
                    month_events_applied.append(ec.get("description", "Expense change"))

        # Add freed payments from previously paid-off loans
        sc_spend = max(0.0, sc_spend - sc_freed_payments)

        # Process one-time events and loan payoffs for this month
        for evt in events_by_month.get(month_str, []):
            etype = evt.get("type", "")

            if etype == "one_time":
                amount = evt.get("amount", 0)
                affects = evt.get("affects", "liquid_balance")
                desc = evt.get("description", "One-time event")

                if affects == "net_worth":
                    # Adds an asset (e.g., rental property value)
                    # but also deducts from liquid
                    sc_liquid += amount  # negative = outflow
                    # Net worth impact is neutral if buying an asset of equal value
                else:
                    sc_liquid += amount  # negative = outflow

                month_events_applied.append(desc)
                events_applied_log.append({
                    "month": month_str,
                    "description": desc,
                    "impact": round(amount, 2),
                })

            elif etype == "loan_payoff":
                acct_id = evt.get("account_id", "")
                desc = evt.get("description", "Loan payoff")

                # Look up remaining balance and monthly payment
                payoff_amount, monthly_payment = _get_loan_payoff_info(conn, acct_id)
                if payoff_amount > 0:
                    sc_liquid -= payoff_amount  # Deduct lump sum
                    sc_liabilities += payoff_amount  # Reduce liabilities (they're negative)
                    sc_freed_payments += monthly_payment  # Free monthly payment

                    month_events_applied.append(desc)
                    events_applied_log.append({
                        "month": month_str,
                        "description": desc,
                        "impact": round(-payoff_amount, 2),
                    })

        sc_income = round(sc_income, 2)
        sc_spend = round(sc_spend, 2)
        sc_net = round(sc_income - sc_spend, 2)
        sc_liquid = round(sc_liquid + sc_net, 2)
        sc_invest = round(sc_invest * (1 + monthly_invest_rate), 2)
        sc_nw = round(sc_liquid + sc_invest + re_value + sc_liabilities, 2)

        scenario.append({
            "month": month_str,
            "income": sc_income,
            "spending": sc_spend,
            "net_cash_flow": sc_net,
            "liquid_balance": sc_liquid,
            "net_worth": sc_nw,
            "events_applied": month_events_applied,
        })

    # ── Summary ──────────────────────────────────────────────────────
    baseline_end_nw = baseline[-1]["net_worth"] if baseline else current_net_worth
    scenario_end_nw = scenario[-1]["net_worth"] if scenario else current_net_worth
    nw_delta = round(scenario_end_nw - baseline_end_nw, 2)

    total_events_impact = round(sum(e["impact"] for e in events_applied_log), 2)

    return {
        "months": months,
        "baseline": baseline,
        "scenario": scenario,
        "summary": {
            "baseline_end_net_worth": round(baseline_end_nw, 2),
            "scenario_end_net_worth": round(scenario_end_nw, 2),
            "net_worth_delta": nw_delta,
            "total_events_impact": total_events_impact,
            "freed_cash_flow_monthly": round(sc_freed_payments, 2),
        },
        "events_applied": events_applied_log,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_total_investment_value(conn: sqlite3.Connection) -> float:
    """Sum of latest portfolio values across all investment/retirement accounts."""
    rows = conn.execute("""
        SELECT a.id,
               COALESCE(
                   (SELECT ps.total_account_value FROM portfolio_snapshots ps
                    WHERE ps.account_id = a.id ORDER BY ps.timestamp DESC LIMIT 1),
                   (SELECT bs.balance FROM balance_snapshots bs
                    WHERE bs.account_id = a.id ORDER BY bs.as_of DESC LIMIT 1)
               ) as value
        FROM accounts a
        WHERE a.type IN ('investment', 'retirement') AND a.is_active = 1
    """).fetchall()
    return round(sum((r["value"] or 0) for r in rows), 2)


def _get_real_estate_value(conn: sqlite3.Connection) -> float:
    """Total current real estate value."""
    row = conn.execute("""
        SELECT SUM(estimated_value) as total FROM real_estate
        WHERE name NOT LIKE '%[%'
          AND id IN (
              SELECT MAX(id) FROM real_estate
              WHERE name NOT LIKE '%[%'
              GROUP BY name
          )
    """).fetchone()
    return round((row["total"] or 0), 2) if row else 0.0


def _get_liability_total(conn: sqlite3.Connection) -> float:
    """Sum of current liabilities (negative number)."""
    rows = conn.execute("""
        SELECT bs.balance
        FROM balance_snapshots bs
        JOIN accounts a ON a.id = bs.account_id
        WHERE a.type IN ('credit_card', 'loan', 'bnpl')
          AND a.is_active = 1
          AND bs.id = (
              SELECT id FROM balance_snapshots b2
              WHERE b2.account_id = bs.account_id
              ORDER BY b2.as_of DESC LIMIT 1
          )
    """).fetchall()
    # Liabilities are typically negative balances
    return round(sum((r["balance"] or 0) for r in rows), 2)


def _get_historical_return(conn: sqlite3.Connection) -> float:
    """Get a blended historical annual return across investment accounts."""
    try:
        from dal.performance import get_all_accounts_performance
        all_perf = get_all_accounts_performance(conn, period="1y")
        twrs = [p["portfolio_twr"] for p in all_perf if p.get("portfolio_twr") is not None]
        if twrs:
            return sum(twrs) / len(twrs)
    except Exception:
        pass
    return _DEFAULT_ANNUAL_RETURN


def _get_loan_payoff_info(conn: sqlite3.Connection, account_id: str) -> tuple[float, float]:
    """Get remaining balance and monthly payment for a loan.

    Returns (remaining_balance, monthly_payment).
    """
    # Balance
    row = conn.execute("""
        SELECT ABS(bs.balance) as balance
        FROM balance_snapshots bs
        WHERE bs.account_id = ?
        ORDER BY bs.as_of DESC LIMIT 1
    """, (account_id,)).fetchone()
    balance = (row["balance"] or 0) if row else 0

    # Monthly payment from recurring
    rec_row = conn.execute("""
        SELECT expected_amount, frequency FROM recurring_transactions
        WHERE linked_account_id = ? AND status = 'active'
        LIMIT 1
    """, (account_id,)).fetchone()

    monthly_payment = 0.0
    if rec_row and rec_row["expected_amount"]:
        factors = {
            "weekly": 4.33, "biweekly": 2.17, "monthly": 1.0,
            "bimonthly": 0.5, "quarterly": 0.333,
            "semiannual": 0.167, "annual": 0.083,
        }
        monthly_payment = rec_row["expected_amount"] * factors.get(rec_row["frequency"], 1.0)
    else:
        # Fallback: estimate as 2% of balance or $25
        monthly_payment = max(25.0, balance * 0.02)

    return round(balance, 2), round(monthly_payment, 2)
