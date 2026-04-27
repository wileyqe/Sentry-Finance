"""Investment holdings, activity, performance, lots, and allocation endpoints."""

from typing import Optional

from fastapi import APIRouter, Query

from dal.database import get_db
from dal.investments import (
    get_holdings, get_activity, get_performance,
    get_lots, get_allocation, get_tax_buckets, get_tax_summary,
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
    asset_class: Optional[str] = Query(None),
    lookthrough: bool = Query(False),
):
    """Portfolio value time-series with adaptive granularity.

    When account_id is omitted or "all", aggregates across all
    investment accounts (optionally filtered by owner_id).

    Optional asset_class filters the series to that class only.  Pass
    lookthrough=true to decompose fund holdings via fund_composition so
    the filtered series matches what the look-through allocation donut
    displays.
    """
    with get_db() as conn:
        data = get_performance(
            conn, account_id=account_id, timeframe=timeframe,
            owner_id=owner_id, asset_class=asset_class,
            lookthrough=lookthrough,
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
    lookthrough: bool = Query(False),
):
    """Aggregated allocation data across investment accounts.

    When lookthrough=true, decomposes funds/ETFs into underlying asset-class
    exposures via fund_composition.  Returns additional keys: sunburst,
    treemap_lookthrough, stacked_bars.
    """
    with get_db() as conn:
        data = get_allocation(
            conn, owner_id=owner_id, account_id=account_id,
            lookthrough=lookthrough,
        )
    return data


@router.get("/api/investments/tax-buckets")
def tax_buckets(account_id: str = Query(...)):
    """Tax bucket balances for a mixed-tax account (e.g. TSP)."""
    with get_db() as conn:
        buckets = get_tax_buckets(conn, account_id)
    return {"buckets": buckets}


@router.get("/api/investments/tax-summary")
def tax_summary(
    owner_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
):
    """Portfolio-wide tax treatment breakdown."""
    with get_db() as conn:
        data = get_tax_summary(conn, owner_id=owner_id, account_id=account_id)
    return data
