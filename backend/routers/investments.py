"""Investment performance, allocation, and debt payoff endpoints."""

from fastapi import APIRouter, Query
from typing import Optional

from dal.database import get_db
from dal.performance import (
    get_portfolio_performance,
    get_all_accounts_performance,
)
from dal.allocation import get_allocation
from dal.debt import get_debt_summary, get_payoff_plan
from dal.investments import get_latest_holdings

router = APIRouter(tags=["investments"])


# ── Investment Performance Endpoints ────────────────────────────────────────────


@router.get("/api/investments/performance")
def investment_performance(
    account_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    months: Optional[int] = Query(None),
    benchmark: str = Query("sp500"),
):
    """Portfolio time-weighted return vs. benchmark.

    Accepts either `period` (1m, 3m, 6m, ...) or `months` (integer).
    If account_id is omitted, returns combined performance for all investment accounts.
    """
    # Convert months param to period string if period not explicitly given
    MONTHS_TO_PERIOD = {1: "1m", 3: "3m", 6: "6m", 12: "1y", 24: "2y", 36: "3y", 60: "5y"}
    if period is None:
        if months is not None:
            period = MONTHS_TO_PERIOD.get(months, f"{months}m")
            # Map non-standard month counts to nearest period
            if period not in ("1m", "3m", "6m", "1y", "2y", "3y", "ytd", "all"):
                period = "1y"
        else:
            period = "1y"

    with get_db() as conn:
        if account_id:
            result = get_portfolio_performance(
                conn, account_id=account_id, period=period, benchmark=benchmark
            )
        else:
            # Get per-account breakdown
            accounts_perf = get_all_accounts_performance(conn, period=period, benchmark=benchmark)

            # Also compute combined monthly_returns from portfolio_snapshots
            from datetime import datetime, timedelta
            today = datetime.utcnow()
            period_days = {"1m": 31, "3m": 92, "6m": 183, "1y": 366, "2y": 731, "3y": 1096, "5y": 1826}
            start = today - timedelta(days=period_days.get(period, 366))
            start_date = start.strftime("%Y-%m-%d")

            # Aggregate portfolio monthly values across all investment accounts
            rows = conn.execute(
                """
                SELECT strftime('%Y-%m', timestamp) as month,
                       SUM(total_account_value) as total_value
                FROM portfolio_snapshots ps
                JOIN accounts a ON a.id = ps.account_id
                WHERE a.type IN ('investment', 'retirement')
                  AND ps.timestamp >= ?
                GROUP BY month
                ORDER BY month ASC
                """,
                (start_date,),
            ).fetchall()

            monthly_returns = []
            prev_val = None
            for r in rows:
                val = r["total_value"]
                if prev_val is not None and prev_val > 0:
                    ret_pct = ((val - prev_val) / prev_val) * 100
                    monthly_returns.append({
                        "month": r["month"],
                        "return_pct": round(ret_pct, 2),
                        "total_value": round(val, 2),
                    })
                prev_val = val

            result = {
                "accounts": accounts_perf,
                "monthly_returns": monthly_returns,
                "period": period,
            }
    return result


# ── Investment Allocation Endpoint ────────────────────────────────────────────────


@router.get("/api/investments/allocation")
def investment_allocation(
    account_id: Optional[str] = Query(None),
):
    """Sector, asset class, and account allocation for investment holdings."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        result = get_allocation(conn, account_ids=account_ids)
    return result

# ── Investment Holdings Endpoint ──────────────────────────────────────────────────

@router.get("/api/investments/holdings")
def investment_holdings(
    account_id: Optional[str] = Query(None),
):
    """Current holdings for an account or across all accounts."""
    with get_db() as conn:
        if account_id:
            raw_holdings = get_latest_holdings(conn, account_id)
        else:
            accounts = conn.execute("SELECT id FROM accounts WHERE type IN ('investment', 'retirement')").fetchall()
            raw_holdings = []
            for acct in accounts:
                acct_holdings = get_latest_holdings(conn, acct["id"])
                for h in acct_holdings:
                    h["account_id"] = acct["id"]
                    raw_holdings.append(h)
    
    # Sort by market value descending 
    raw_holdings.sort(key=lambda x: float(x.get("market_value") or 0), reverse=True)
    return {"holdings": raw_holdings}

# ── Debt Payoff Endpoints ──────────────────────────────────────────────────────────


@router.get("/api/debt/summary")
def debt_summary():
    """Current liability snapshot: all debts, total owed, weighted average APR."""
    with get_db() as conn:
        summary = get_debt_summary(conn)
    return summary


@router.get("/api/debt/payoff")
def debt_payoff(
    extra_payment: float = Query(0.0, ge=0, description="Extra monthly payment above minimums"),
    strategy: str = Query("avalanche", enum=["avalanche", "snowball"]),
):
    """Debt payoff plan with avalanche vs. snowball comparison.

    Returns the requested strategy's schedule plus a side-by-side comparison
    showing interest and time savings.
    """
    with get_db() as conn:
        plan = get_payoff_plan(conn, extra_payment=extra_payment, strategy=strategy)
    return plan
