"""Savings goals endpoints."""

from fastapi import APIRouter, Query, HTTPException, Request
from typing import Optional

from dal.database import get_db
from dal.goals import (
    create_goal,
    get_goal,
    list_goals,
    update_goal_amount,
    delete_goal,
    sync_goal_balances,
    get_goals_summary,
)

router = APIRouter(tags=["goals"])


@router.get("/api/goals")
def goals_list(
    owner_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """List savings goals with computed progress fields."""
    with get_db() as conn:
        goals = list_goals(conn, owner_id=owner_id, status=status)
    return {"goals": goals, "count": len(goals)}


@router.get("/api/goals/summary")
def goals_summary(
    owner_id: Optional[str] = Query(None),
):
    """Dashboard summary: total saved vs. target, trajectory counts."""
    with get_db() as conn:
        summary = get_goals_summary(conn, owner_id=owner_id)
    return summary


@router.get("/api/goals/{goal_id}")
def goal_detail(goal_id: int):
    """Get a single savings goal by ID."""
    with get_db() as conn:
        goal = get_goal(conn, goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    return goal


@router.post("/api/goals", status_code=201)
async def goal_create(request: Request):
    """Create a new savings goal."""
    body = await request.json()

    name = body.get("name")
    target_amount = body.get("target_amount")
    if not name or not target_amount:
        raise HTTPException(status_code=422, detail="name and target_amount are required")

    with get_db() as conn:
        goal_id = create_goal(
            conn,
            name=name,
            target_amount=float(target_amount),
            owner_id=body.get("owner_id"),
            current_amount=float(body.get("current_amount", 0)),
            deadline=body.get("deadline"),
            linked_account_id=body.get("linked_account_id"),
            notes=body.get("notes"),
        )
        goal = get_goal(conn, goal_id)
    return goal


@router.patch("/api/goals/{goal_id}/amount")
def goal_update_amount(
    goal_id: int,
    amount: float = Query(..., description="New current amount for the goal"),
):
    """Manually update the current saved amount for a goal."""
    with get_db() as conn:
        goal = get_goal(conn, goal_id)
        if not goal:
            raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
        result = update_goal_amount(conn, goal_id, amount)
    return result


@router.post("/api/goals/sync")
def goal_sync():
    """Sync all active goals with linked accounts from latest balance snapshots."""
    with get_db() as conn:
        updated = sync_goal_balances(conn)
    return {"status": "synced", "goals_updated": updated}


@router.delete("/api/goals/{goal_id}", status_code=204)
def goal_delete(goal_id: int):
    """Cancel (soft-delete) a savings goal."""
    with get_db() as conn:
        goal = get_goal(conn, goal_id)
        if not goal:
            raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
        delete_goal(conn, goal_id)
