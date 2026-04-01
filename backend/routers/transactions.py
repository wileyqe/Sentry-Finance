"""Transaction query and categorization endpoints."""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from pydantic import BaseModel
import uuid

from dal.database import get_db
from dal.transactions import get_transactions
from dal.owners import resolve_account_ids_for_view
from dal.categorization import (
    list_categories as dal_list_categories,
    set_user_override,
    delete_user_override,
    backfill_uncategorized,
    reload_rules,
)

router = APIRouter(tags=["transactions"])


class TransactionCreate(BaseModel):
    description: str
    amount: float
    signed_amount: Optional[float] = None
    category: str = "Uncategorized"
    account_id: str = ""
    posting_date: str = ""
    status: str = "posted"
    direction: str = "outflow"
    merchant: Optional[str] = None
    institution_id: Optional[str] = None


@router.post("/api/transactions")
def create_transaction(body: TransactionCreate):
    """Create a manual transaction."""
    txn_id = f"manual_{uuid.uuid4().hex[:12]}"
    signed = body.signed_amount if body.signed_amount is not None else body.amount
    inst_id = body.institution_id
    # infer institution from account_id
    if not inst_id and body.account_id:
        for prefix in ('chase', 'nfcu', 'amex', 'rocket', 'fidelity', 'acorns', 'affirm', 'tsp'):
            if body.account_id.startswith(prefix):
                inst_id = prefix
                break
    with get_db() as conn:
        conn.execute(
            """INSERT INTO transactions
               (id, account_id, institution_id, posting_date, description, merchant,
                amount, signed_amount, direction, category, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (txn_id, body.account_id, inst_id or '', body.posting_date,
             body.description, body.merchant or body.description,
             abs(body.amount), signed, body.direction, body.category, body.status),
        )
        conn.commit()
    return {"status": "created", "id": txn_id}
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
    owner_id: str = Query(None),
):
    """Query transactions with optional filters."""
    with get_db() as conn:
        # Prefer owner_id (new P7 pattern) over legacy view param
        effective_view = owner_id if owner_id else view

        effective_account_id = account_id
        if not account_id and effective_view != "ours":
            view_ids = resolve_account_ids_for_view(conn, effective_view)
            if view_ids is not None and len(view_ids) > 0:
                all_txns = []
                for vid in view_ids:
                    txns = get_transactions(
                        conn, vid, institution_id, start_date,
                        end_date, status, limit, offset,
                    )
                    all_txns.extend(txns)
                return {"transactions": all_txns[:limit], "count": min(len(all_txns), limit), "view": effective_view}

        txns = get_transactions(
            conn,
            effective_account_id,
            institution_id,
            start_date,
            end_date,
            status,
            limit,
            offset,
            owner_id=owner_id,
        )
    return {"transactions": txns, "count": len(txns), "view": effective_view}


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


@router.post("/api/categorize/reload-rules")
def categorize_reload_rules():
    """Hot-reload categorization rules from categories.yaml without restart."""
    count = reload_rules()
    return {"status": "reloaded", "rules_loaded": count}


@router.post("/api/categorize/backfill")
def categorize_backfill():
    """Trigger backfill of all uncategorized transactions.

    Automatically reloads rules from disk first so edits to
    categories.yaml take effect without a server restart.
    """
    reload_rules()
    with get_db() as conn:
        stats = backfill_uncategorized(conn)
    return {"status": "complete", **stats}
