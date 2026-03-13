"""Spending alert management endpoints."""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from dal.database import get_db
from dal.alerts import (
    evaluate_alerts,
    get_rules as dal_get_alert_rules,
    get_recent_alerts,
    set_rule_enabled,
    update_rule_threshold,
)

router = APIRouter(tags=["alerts"])


@router.get("/api/alerts/rules")
def alert_rules_list():
    """List all configured alert rules."""
    with get_db() as conn:
        rules = dal_get_alert_rules(conn)
    return {"rules": rules}


@router.patch("/api/alerts/rules/{rule_id}")
def alert_rule_update(
    rule_id: str,
    enabled: Optional[bool] = Query(None),
    threshold: Optional[float] = Query(None),
):
    """Enable/disable an alert rule or update its threshold."""
    with get_db() as conn:
        rule = conn.execute(
            "SELECT id FROM alert_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        if not rule:
            raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
        if enabled is not None:
            set_rule_enabled(conn, rule_id, enabled)
        if threshold is not None:
            update_rule_threshold(conn, rule_id, threshold)
        conn.commit()
    return {"status": "updated", "rule_id": rule_id}


@router.get("/api/alerts/events")
def alert_events_list(
    limit: int = Query(50, le=200),
    rule_type: Optional[str] = Query(None),
):
    """List recently fired alert events."""
    with get_db() as conn:
        events = get_recent_alerts(conn, limit=limit, rule_type=rule_type)
    return {"events": events, "count": len(events)}


@router.post("/api/alerts/evaluate")
def alert_evaluate_now():
    """Manually trigger alert evaluation (normally runs after each refresh)."""
    with get_db() as conn:
        fired = evaluate_alerts(conn)
    return {"status": "complete", "fired": fired, "count": len(fired)}
