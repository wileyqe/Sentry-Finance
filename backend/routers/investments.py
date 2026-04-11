"""Investment holdings, activity, performance, lots, and allocation endpoints."""

from typing import Optional

from fastapi import APIRouter, Query

from dal.database import get_db
from dal.investments import (
    get_holdings, get_activity, get_performance,
    get_lots, get_allocation,
)

router = APIRouter(tags=["investments"])


@router.get("/api/investments/holdings")
def holdings(owner_id: Optional[str] = Query(None)):
    """Current per-ticker positions for each investment account."""
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
def performance(
    account_id: Optional[str] = Query(None),
    timeframe: str = Query("All"),
    owner_id: Optional[str] = Query(None),
):
    """Portfolio value time-series with adaptive granularity.

    When account_id is omitted or "all", aggregates across all
    investment accounts (optionally filtered by owner_id).
    """
    with get_db() as conn:
        data = get_performance(
            conn, account_id=account_id, timeframe=timeframe,
            owner_id=owner_id,
        )
    return {"data": data}


@router.get("/api/investments/lots")
def lots(
    account_id: str = Query(...),
    ticker: str = Query(...),
):
    """Tax lot detail for a specific holding."""
    with get_db() as conn:
        lot_data = get_lots(conn, account_id, ticker)
    return {"lots": lot_data}


@router.get("/api/investments/allocation")
def allocation(
    owner_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
):
    """Aggregated allocation data across investment accounts."""
    with get_db() as conn:
        data = get_allocation(conn, owner_id=owner_id, account_id=account_id)
    return data
