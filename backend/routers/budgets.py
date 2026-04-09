"""Budget management endpoints.

Budgets are a household-level concept (V23 migration) — these endpoints
intentionally do **not** accept an ``owner_id`` query parameter. FastAPI
silently ignores unknown query params, so any stale frontend code that
still passes ``&owner_id=...`` is tolerated as a no-op.
"""

from fastapi import APIRouter, Query

from dal.database import get_db
from dal.budgets import (
    get_budget_vs_actual,
    get_budget_summary,
    set_budget_target,
    initialize_month as budget_initialize_month,
    delete_budget,
    suggest_budget_targets,
)

router = APIRouter(tags=["budgets"])


@router.get("/api/budgets")
def budgets_vs_actual(
    month: str = Query(..., description="YYYY-MM"),
):
    """Household budget vs. actual spending for a month."""
    with get_db() as conn:
        details = get_budget_vs_actual(conn, month)
    return {"month": month, "categories": details}


@router.get("/api/budgets/summary")
def budgets_summary(
    month: str = Query(..., description="YYYY-MM"),
):
    """High-level household budget summary for a month."""
    with get_db() as conn:
        summary = get_budget_summary(conn, month)
    return summary


@router.put("/api/budgets/{category}")
def budgets_set_target(
    category: str,
    month: str = Query(..., description="YYYY-MM"),
    target: float = Query(...),
):
    """Set or update a household budget target for a category/month."""
    with get_db() as conn:
        set_budget_target(conn, category, month, target)
        conn.commit()
    return {"status": "updated", "category": category, "month": month, "target": target}


@router.post("/api/budgets/initialize")
def budgets_init_month(
    month: str = Query(..., description="YYYY-MM"),
):
    """Initialize household budget entries for a month from defaults."""
    with get_db() as conn:
        created = budget_initialize_month(conn, month)
        conn.commit()
    return {"status": "initialized", "month": month, "created": created}


@router.delete("/api/budgets/{category}")
def budgets_delete(
    category: str,
    month: str = Query(..., description="YYYY-MM"),
):
    """Delete a household budget entry."""
    with get_db() as conn:
        delete_budget(conn, category, month)
        conn.commit()
    return {"status": "deleted", "category": category, "month": month}


@router.get("/api/budgets/suggest")
def budgets_suggest(
    months_back: int = Query(3),
):
    """Suggest budget targets based on historical spending.

    Returns per-category suggestions with:
      avg_monthly, suggested_target (rounded to $25 with 10% buffer),
      recurring_baseline, has_recurring, months_with_data
    """
    with get_db() as conn:
        suggestions = suggest_budget_targets(conn, months_back=months_back)
    return {"suggestions": suggestions, "months_analyzed": months_back}
