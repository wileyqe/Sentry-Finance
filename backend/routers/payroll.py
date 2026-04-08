"""
backend/routers/payroll.py — Payroll snapshot API endpoints (Phase 9).

Surfaces aggregates from `dal/payroll.py`, which reads the
`payroll_snapshots` table populated by the myPay RAS document-drop
parser.

Owner scoping
-------------
As of migration v22 ``payroll_snapshots`` has an ``owner_id`` column
populated by the parser. Both endpoints accept an optional ``owner_id``
query param and thread it through to the DAL — when set, results are
restricted to that owner; when omitted, the household-wide totals are
returned.
"""

import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from dal.database import get_db
from dal.payroll import (
    get_gross_income_for_month,
    get_gross_income_for_year,
    get_effective_tax_rate,
)

log = logging.getLogger("sentry.backend.routers.payroll")
router = APIRouter(prefix="/api/payroll", tags=["payroll"])


@router.get("/yearly")
def get_yearly_payroll(
    year: int = Query(..., description="Calendar year, e.g. 2025"),
    owner_id: Optional[str] = Query(None),
):
    """Return the year's gross/withholding totals plus effective tax rate.

    When ``owner_id`` is set, results are restricted to that owner's
    payroll snapshots; otherwise the household total is returned.
    """
    with get_db() as conn:
        gross = get_gross_income_for_year(conn, year, owner_id=owner_id)
        effective = get_effective_tax_rate(conn, year, owner_id=owner_id)
        return {
            "year": year,
            "gross": gross,
            "effective_tax": effective,
        }


@router.get("/monthly")
def get_monthly_payroll(
    month: str = Query(..., description="YYYY-MM month string, e.g. 2025-12"),
    owner_id: Optional[str] = Query(None),
):
    """Return one month's payroll snapshot, or `null` when no data exists."""
    try:
        year_str, month_str = month.split("-")
        year = int(year_str)
        mo = int(month_str)
        if not (1 <= mo <= 12):
            raise ValueError("month out of range")
    except Exception:
        raise HTTPException(status_code=400, detail="month must be 'YYYY-MM'")

    with get_db() as conn:
        snap = get_gross_income_for_month(conn, year, mo, owner_id=owner_id)
        return {"month": month, "snapshot": snap}
