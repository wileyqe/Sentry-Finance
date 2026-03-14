"""Recurring transaction detection and bill tracking endpoints."""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from pydantic import BaseModel

from dal.database import get_db
from dal.recurring import (
    detect_recurring,
    get_recurring as dal_get_recurring,
    get_mutations,
    dismiss_recurring,
    reactivate_recurring,
    get_monthly_recurring_total,
)
from dal.bills import (
    get_upcoming_bills,
    get_overdue_bills,
    get_bills_summary,
)

router = APIRouter(tags=["recurring"])


class RecurringMark(BaseModel):
    merchant: str
    account_id: str
    category: str = "Uncategorized"
    amount: float = 0


# ── Recurring Transaction Endpoints ──────────────────────────────────────────


@router.get("/api/recurring")
def recurring_list(
    status: str = Query("active"),
    account_id: Optional[str] = Query(None),
):
    """List recurring transactions."""
    with get_db() as conn:
        items = dal_get_recurring(conn, status=status, account_id=account_id)
    return {"recurring": items, "count": len(items)}


@router.post("/api/recurring/mark")
def recurring_mark(body: RecurringMark):
    """Manually mark a merchant as recurring (create entry in recurring_transactions)."""
    rec_id = f"{body.account_id}__{body.merchant.lower().replace(' ', '_')}"
    with get_db() as conn:
        # Upsert — if already exists as dismissed, reactivate it
        existing = conn.execute(
            "SELECT id, status FROM recurring_transactions WHERE id = ?", (rec_id,)
        ).fetchone()
        if existing:
            if existing["status"] == "dismissed":
                conn.execute(
                    "UPDATE recurring_transactions SET status='active', updated_at=datetime('now') WHERE id = ?",
                    (rec_id,),
                )
                conn.commit()
            return {"status": "reactivated" if existing["status"] == "dismissed" else "already_active", "id": rec_id}
        conn.execute(
            """INSERT INTO recurring_transactions
               (id, account_id, merchant, category, frequency, avg_interval,
                expected_amount, last_amount, amount_stable, occurrence_count, status)
               VALUES (?, ?, ?, ?, 'monthly', 30, ?, ?, 1, 1, 'active')""",
            (rec_id, body.account_id, body.merchant, body.category, abs(body.amount), abs(body.amount)),
        )
        conn.commit()
    return {"status": "created", "id": rec_id}


@router.get("/api/recurring/{recurring_id}/mutations")
def recurring_mutations(recurring_id: str):
    """Get price change history for a recurring transaction."""
    with get_db() as conn:
        mutations = get_mutations(conn, recurring_id)
    return {"mutations": mutations}


@router.post("/api/recurring/scan")
def recurring_scan():
    """Trigger a full recurring transaction scan."""
    with get_db() as conn:
        stats = detect_recurring(conn)
    return {"status": "complete", **stats}


@router.patch("/api/recurring/{recurring_id}")
def recurring_update(recurring_id: str, action: str = Query(...)):
    """Dismiss or reactivate a recurring transaction.

    action: 'dismiss' or 'reactivate'
    """
    with get_db() as conn:
        if action == "dismiss":
            dismiss_recurring(conn, recurring_id)
        elif action == "reactivate":
            reactivate_recurring(conn, recurring_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
        conn.commit()
    return {"status": "updated", "recurring_id": recurring_id, "action": action}


@router.get("/api/recurring/summary")
def recurring_summary(account_id: Optional[str] = Query(None)):
    """Monthly recurring totals by category for budget baseline."""
    with get_db() as conn:
        totals = get_monthly_recurring_total(conn, account_id=account_id)
    return totals


# ── Bill Tracking Endpoints ─────────────────────────────────────────────


@router.get("/api/bills/upcoming")
def bills_upcoming(
    days: int = Query(30),
    account_id: Optional[str] = Query(None),
):
    """List upcoming bills within the next N days."""
    with get_db() as conn:
        bills = get_upcoming_bills(conn, days=days, account_id=account_id)
    return {"bills": bills, "count": len(bills)}


@router.get("/api/bills/overdue")
def bills_overdue(
    account_id: Optional[str] = Query(None),
):
    """List all overdue bills."""
    with get_db() as conn:
        bills = get_overdue_bills(conn, account_id=account_id)
    return {"bills": bills, "count": len(bills)}


@router.get("/api/bills/summary")
def bills_summary_endpoint(
    days: int = Query(30),
    account_id: Optional[str] = Query(None),
):
    """Dashboard bill summary: counts and next bill due."""
    with get_db() as conn:
        summary = get_bills_summary(conn, days=days, account_id=account_id)
    return summary
