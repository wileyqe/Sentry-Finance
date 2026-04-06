"""
backend/routers/payroll.py — Payroll snapshot API endpoints (Phase 9).

Surfaces aggregates from `dal/payroll.py`, which reads the
`payroll_snapshots` table populated by the myPay RAS document-drop
parser.

Owner-scoping note
------------------
Both endpoints accept the standard `owner_id` query param for API
consistency, but it is currently a **no-op** at the DAL layer because
`payroll_snapshots` has no `owner_id` column.  See the docstring on
`dal/payroll.py` for the full rationale.  When/if a partner ever
acquires payroll data, this will require both a schema migration and
a refactor here — until then, every read returns the household's
primary-owner military pension data.
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
    owner_id: Optional[str] = Query(None),  # noqa: ARG001 — see module docstring
):
    """Return the year's gross/withholding totals plus effective tax rate.

    `owner_id` is accepted for API consistency but is a no-op until
    payroll_snapshots gains an owner column.
    """
    with get_db() as conn:
        gross = get_gross_income_for_year(conn, year)
        effective = get_effective_tax_rate(conn, year)
        return {
            "year": year,
            "gross": gross,
            "effective_tax": effective,
        }


@router.get("/monthly")
def get_monthly_payroll(
    month: str = Query(..., description="YYYY-MM month string, e.g. 2025-12"),
    owner_id: Optional[str] = Query(None),  # noqa: ARG001 — see module docstring
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
        snap = get_gross_income_for_month(conn, year, mo)
        return {"month": month, "snapshot": snap}
