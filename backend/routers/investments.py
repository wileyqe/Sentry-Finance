"""Investment holdings, activity, and performance endpoints."""

from typing import Optional

from fastapi import APIRouter, Query

from dal.database import get_db
from dal.investments import get_holdings, get_activity, get_performance

router = APIRouter(tags=["investments"])


@router.get("/api/investments/holdings")
def holdings(owner_id: Optional[str] = Query(None)):
    """Current per-ETF positions for each investment account."""
    with get_db() as conn:
        accounts = get_holdings(conn, owner_id=owner_id)
    return {"accounts": accounts}


@router.get("/api/investments/activity")
def activity(
    account_id: str = Query(...),
    months: int = Query(6),
):
    """Recent investment activity (contributions, roundups, fees)."""
    with get_db() as conn:
        items = get_activity(conn, account_id, months=months)
    return {"activity": items}


@router.get("/api/investments/performance")
def performance(account_id: str = Query(...)):
    """Monthly portfolio value time-series for charting."""
    with get_db() as conn:
        monthly = get_performance(conn, account_id)
    return {"monthly_values": monthly}
