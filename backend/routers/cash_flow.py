"""backend/routers/cash_flow.py — Cash Flow page endpoints."""

from fastapi import APIRouter, Query
from typing import Optional
from datetime import date, timedelta
import calendar

from dal.database import get_db
from dal.cash_flow import (
    get_monthly_cash_flow,
    get_quarterly_cash_flow,
    get_yearly_cash_flow,
    get_period_detail,
    get_available_years,
    get_monthly_rolling_cash_flow,
    get_quarterly_rolling_cash_flow,
)

router = APIRouter(tags=["cash_flow"])


@router.get("/api/cash-flow/monthly")
def cash_flow_monthly(
    year: int = Query(default=None, description="4-digit year, defaults to current year"),
    account_id: Optional[str] = Query(None),
):
    """Month-by-month income/expense/net for a given year."""
    if year is None:
        year = date.today().year
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_monthly_cash_flow(conn, year=year, account_ids=account_ids)
    return {"year": year, "months": data}


@router.get("/api/cash-flow/quarterly")
def cash_flow_quarterly(
    year: int = Query(default=None, description="4-digit year, defaults to current year"),
    account_id: Optional[str] = Query(None),
):
    """Quarter-by-quarter income/expense/net for a given year."""
    if year is None:
        year = date.today().year
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_quarterly_cash_flow(conn, year=year, account_ids=account_ids)
    return {"year": year, "quarters": data}


@router.get("/api/cash-flow/monthly-rolling")
def cash_flow_monthly_rolling(
    account_id: Optional[str] = Query(None),
):
    """Rolling 18-month window ending at the current month."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_monthly_rolling_cash_flow(conn, months=18, account_ids=account_ids)
    return {"months": data}


@router.get("/api/cash-flow/quarterly-rolling")
def cash_flow_quarterly_rolling(
    account_id: Optional[str] = Query(None),
):
    """Rolling 9-quarter window ending at the current quarter."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_quarterly_rolling_cash_flow(conn, quarters=9, account_ids=account_ids)
    return {"quarters": data}


@router.get("/api/cash-flow/yearly")
def cash_flow_yearly(
    account_id: Optional[str] = Query(None),
):
    """All-years income/expense/net summary."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_yearly_cash_flow(conn, account_ids=account_ids)
        years = get_available_years(conn)
    return {"years": data, "available_years": years}


@router.get("/api/cash-flow/period")
def cash_flow_period(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    account_id: Optional[str] = Query(None),
):
    """KPIs + category breakdown for a specific date range."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_period_detail(conn, start_date=start, end_date=end, account_ids=account_ids)
    return data


@router.get("/api/cash-flow/available-years")
def cash_flow_available_years():
    """List of years that have transaction data."""
    with get_db() as conn:
        years = get_available_years(conn)
    return {"years": years}
