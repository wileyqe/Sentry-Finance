"""Investment performance, allocation, and debt payoff endpoints."""

from fastapi import APIRouter, Query
from typing import Optional

from dal.database import get_db
from backend.events import is_refresh_active
from dal.performance import (
    get_portfolio_performance,
    get_all_accounts_performance,
    force_refresh_benchmarks,
)
from dal.allocation import get_allocation
from dal.debt import get_debt_summary, get_payoff_plan
from dal.investments import get_latest_holdings

router = APIRouter(tags=["investments"])


# ── Investment Performance Endpoints ────────────────────────────────────────────


@router.get("/api/investments/performance")
def investment_performance(
    account_id: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
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
            accounts_perf = get_all_accounts_performance(conn, period=period, benchmark=benchmark, owner_id=owner_id)

            # Also compute combined monthly_returns from portfolio_snapshots
            from datetime import datetime, timedelta, timezone
            today = datetime.now(timezone.utc)
            period_days = {"1m": 31, "3m": 92, "6m": 183, "1y": 366, "2y": 731, "3y": 1096, "5y": 1826}
            start = today - timedelta(days=period_days.get(period, 366))
            start_date = start.strftime("%Y-%m-%d")

            from dal.owners import build_account_filter
            acct_filter, acct_params = build_account_filter(
                conn, owner_id, None, column="a.id"
            )
            params = [start_date] + list(acct_params)

            # Aggregate portfolio monthly values across all investment accounts
            rows = conn.execute(
                f"""
                SELECT strftime('%Y-%m', timestamp) as month,
                       SUM(total_account_value) as total_value
                FROM portfolio_snapshots ps
                JOIN accounts a ON a.id = ps.account_id
                WHERE a.type IN ('investment', 'retirement')
                  AND ps.timestamp >= ?
                  {acct_filter}
                GROUP BY month
                ORDER BY month ASC
                """,
                params,
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

            # Hoist the benchmark TWR to the top-level response so the
            # frontend doesn't have to dig into the per-account array.
            # Every account computes the benchmark over the same time
            # window, so the values agree — use the first account as the
            # source of truth. (get_all_accounts_performance only
            # includes the TWR pct, not the monthly series or ticker,
            # so only the scalar is hoisted here.)
            top_benchmark_twr_pct = (
                accounts_perf[0].get("benchmark_twr_pct") if accounts_perf else None
            )

            result = {
                "accounts": accounts_perf,
                "monthly_returns": monthly_returns,
                "period": period,
                "benchmark_twr_pct": top_benchmark_twr_pct,
                "benchmark_ticker": benchmark,
            }
    result["refresh_in_progress"] = is_refresh_active()
    return result


# ── Investment Allocation Endpoint ────────────────────────────────────────────────


@router.get("/api/investments/allocation")
def investment_allocation(
    account_id: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
):
    """Sector, asset class, and account allocation for investment holdings."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        result = get_allocation(conn, account_ids=account_ids, owner_id=owner_id)
    result["refresh_in_progress"] = is_refresh_active()
    return result


@router.post("/api/investments/refresh-benchmarks")
def investment_refresh_benchmarks():
    """Force-refresh the cached benchmark prices from yfinance.

    Called by the "Refresh benchmarks" button on the Investments page.
    Wipes the existing cache for the default benchmark set (S&P 500,
    VTI, BND) and re-downloads the last ~2 years. Returns a summary
    dict the UI uses to show confirmation / error state.
    """
    with get_db() as conn:
        summary = force_refresh_benchmarks(conn)
    return summary

# ── Investment Holdings Endpoint ──────────────────────────────────────────────────

@router.get("/api/investments/holdings")
def investment_holdings(
    account_id: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
):
    """Current holdings for an account or across all accounts."""
    with get_db() as conn:
        if account_id:
            raw_holdings = get_latest_holdings(conn, account_id)
        else:
            from dal.owners import build_account_filter
            acct_filter, acct_params = build_account_filter(
                conn, owner_id, None, column="id"
            )
            params = list(acct_params)
            accounts = conn.execute(f"SELECT id FROM accounts WHERE type IN ('investment', 'retirement') {acct_filter}", params).fetchall()
            raw_holdings = []
            for acct in accounts:
                acct_holdings = get_latest_holdings(conn, acct["id"])
                for h in acct_holdings:
                    h["account_id"] = acct["id"]
                    raw_holdings.append(h)
    
    # Sort by market value descending 
    raw_holdings.sort(key=lambda x: float(x.get("market_value") or 0), reverse=True)
    return {"holdings": raw_holdings, "refresh_in_progress": is_refresh_active()}

# ── Debt Payoff Endpoints ──────────────────────────────────────────────────────────


@router.get("/api/debt/summary")
def debt_summary(
    owner_id: Optional[str] = Query(None),
):
    """Current liability snapshot: all debts, total owed, weighted average APR."""
    with get_db() as conn:
        summary = get_debt_summary(conn, owner_id=owner_id)
    summary["refresh_in_progress"] = is_refresh_active()
    return summary


@router.get("/api/debt/payoff")
def debt_payoff(
    extra_payment: float = Query(0.0, ge=0, description="Extra monthly payment above minimums"),
    strategy: str = Query("avalanche", enum=["avalanche", "snowball"]),
    owner_id: Optional[str] = Query(None),
):
    """Debt payoff plan with avalanche vs. snowball comparison.

    Returns the requested strategy's schedule plus a side-by-side comparison
    showing interest and time savings.
    """
    with get_db() as conn:
        plan = get_payoff_plan(
            conn, extra_payment=extra_payment, strategy=strategy, owner_id=owner_id
        )
    plan["refresh_in_progress"] = is_refresh_active()
    return plan


# ── Contributions vs. Performance (P6-T05) ───────────────────────────────────


@router.get("/api/investments/contributions-vs-performance")
def contributions_vs_performance(
    year: int | None = None,
    account_id: str | None = None,
    owner_id: Optional[str] = Query(None),
):
    """
    Returns the contributions vs. performance decomposition.
    Defaults to the prior calendar year.
    """
    from datetime import date as _date
    from dal.performance import decompose_contributions_vs_performance

    if year is None:
        year = _date.today().year - 1
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = decompose_contributions_vs_performance(
            conn, year, account_ids=account_ids, owner_id=owner_id
        )
    return {"year": year, "accounts": data, "refresh_in_progress": is_refresh_active()}
