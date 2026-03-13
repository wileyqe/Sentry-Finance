"""Transaction query and categorization endpoints."""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from dal.database import get_db
from dal.transactions import get_transactions
from dal.owners import resolve_account_ids_for_view
from dal.categorization import (
    list_categories as dal_list_categories,
    set_user_override,
    delete_user_override,
    backfill_uncategorized,
)

router = APIRouter(tags=["transactions"])


@router.get("/api/transactions")
def list_transactions(
    account_id: str = Query(None),
    institution_id: str = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    status: str = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    view: str = Query("ours"),
):
    """Query transactions with optional filters."""
    with get_db() as conn:
        # Apply view filter: if a specific view is set and no explicit
        # account_id was requested, restrict to matching accounts
        effective_account_id = account_id
        if not account_id and view != "ours":
            view_ids = resolve_account_ids_for_view(conn, view)
            if view_ids is not None and len(view_ids) > 0:
                # Fetch transactions for all matching accounts
                all_txns = []
                for vid in view_ids:
                    txns = get_transactions(
                        conn, vid, institution_id, start_date,
                        end_date, status, limit, offset,
                    )
                    all_txns.extend(txns)
                return {"transactions": all_txns[:limit], "count": min(len(all_txns), limit), "view": view}

        txns = get_transactions(
            conn,
            effective_account_id,
            institution_id,
            start_date,
            end_date,
            status,
            limit,
            offset,
        )
    return {"transactions": txns, "count": len(txns), "view": view}


# ── Categorization Endpoints ───────────────────────────────────────────────


@router.get("/api/categories")
def categories_list():
    """List all categories in use with transaction counts."""
    with get_db() as conn:
        cats = dal_list_categories(conn)
    return {"categories": cats}


@router.patch("/api/transactions/{txn_id}/category")
def transaction_set_category(txn_id: str, category: str = Query(...)):
    """Set a user override for a transaction's category."""
    with get_db() as conn:
        txn = conn.execute(
            "SELECT id FROM transactions WHERE id = ?", (txn_id,)
        ).fetchone()
        if not txn:
            raise HTTPException(status_code=404, detail=f"Transaction {txn_id} not found")
        set_user_override(conn, txn_id, category)
        conn.commit()
    return {"status": "updated", "txn_id": txn_id, "category": category}


@router.delete("/api/transactions/{txn_id}/category")
def transaction_clear_category(txn_id: str):
    """Remove a user override, reverting to rule-based categorization."""
    with get_db() as conn:
        delete_user_override(conn, txn_id)
        conn.commit()
    return {"status": "deleted", "txn_id": txn_id}


@router.post("/api/categorize/backfill")
def categorize_backfill():
    """Trigger backfill of all uncategorized transactions."""
    with get_db() as conn:
        stats = backfill_uncategorized(conn)
    return {"status": "complete", **stats}
