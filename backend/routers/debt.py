"""Debt payoff endpoints.

Previously this file was ``backend/routers/investments.py`` and hosted
both the investment and the debt endpoints. Investments has been
stripped to a shell as part of the P13 investments rebuild; the debt
routes live here now, unchanged.
"""

from fastapi import APIRouter, Query
from typing import Optional

from dal.database import get_db
from backend.events import is_refresh_active
from dal.debt import get_debt_summary, get_payoff_plan

router = APIRouter(tags=["debt"])


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
