"""Transaction query and categorization endpoints."""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from pydantic import BaseModel

from dal.database import get_db
from dal.transactions import (
    get_transactions,
    count_transactions,
    upsert_transactions,
    derive_signed_amount,
    compute_txn_id,
)
from dal.categorization import (
    list_categories as dal_list_categories,
    set_user_override,
    delete_user_override,
    backfill_uncategorized,
    reload_rules,
)

router = APIRouter(tags=["transactions"])


# Legacy directional aliases the frontend has historically sent (`outflow` /
# `inflow`). Mapped to canonical {`Credit`, `Debit`} so manual entries flow
# through `upsert_transactions`'s sign/direction invariant gate without
# requiring the caller to learn the canonical vocabulary.
_DIRECTION_ALIASES = {
    "credit": "Credit",
    "debit": "Debit",
    "Credit": "Credit",
    "Debit": "Debit",
    "inflow": "Credit",
    "outflow": "Debit",
}


class TransactionCreate(BaseModel):
    description: str
    amount: float
    signed_amount: Optional[float] = None
    category: str = "Uncategorized"
    account_id: str = ""
    posting_date: str = ""
    status: str = "posted"
    direction: str = "Debit"
    merchant: Optional[str] = None
    institution_id: Optional[str] = None


@router.post("/api/transactions")
def create_transaction(body: TransactionCreate):
    """Create a manual transaction.

    Routes through ``dal.transactions.upsert_transactions`` so the
    canonical sign/direction invariant fires the same way as connector
    and seeder writes.
    """
    direction = _DIRECTION_ALIASES.get(body.direction)
    if direction is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown direction {body.direction!r}; expected one of "
                "'Credit', 'Debit' (or legacy 'inflow' / 'outflow')."
            ),
        )

    inst_id = body.institution_id
    # infer institution from account_id
    if not inst_id and body.account_id:
        for prefix in ('chase', 'nfcu', 'amex', 'rocket', 'fidelity', 'acorns', 'affirm', 'tsp'):
            if body.account_id.startswith(prefix):
                inst_id = prefix
                break

    amount = abs(body.amount)
    signed_amount = derive_signed_amount(amount, direction)

    txn = {
        "account_id": body.account_id,
        "institution_id": inst_id or "",
        "posting_date": body.posting_date,
        "amount": amount,
        "signed_amount": signed_amount,
        "direction": direction,
        "description": body.description,
        "category": body.category,
        "status": body.status,
    }

    txn_id = compute_txn_id(
        institution_id=txn["institution_id"],
        account_id=txn["account_id"],
        posting_date=txn["posting_date"],
        amount=txn["amount"],
        description=txn["description"],
    )

    with get_db() as conn:
        stats = upsert_transactions(conn, [txn])
        # `upsert_transactions` doesn't write the ``merchant`` column;
        # preserve the legacy behavior of stamping it from the user-supplied
        # value (or falling back to the description).
        merchant_value = body.merchant or body.description
        if merchant_value:
            conn.execute(
                "UPDATE transactions SET merchant = ? WHERE id = ?",
                (merchant_value, txn_id),
            )
        conn.commit()

    return {"status": "created", "id": txn_id, "stats": stats}
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
    exclude_transfers: bool = Query(False),
):
    """Query transactions with optional filters."""
    # Prefer owner_id (new P7 pattern) over legacy view param
    effective_view = owner_id if owner_id else view

    # DAL's get_transactions resolves owner scoping itself (ours / mine / theirs
    # / specific owner_id) via resolve_account_ids_for_view, producing a single
    # ORDER BY posting_date DESC query. Do NOT loop per-account here — that
    # concatenates in account order and breaks date ordering when `limit`
    # slices mid-batch (e.g. dashboard's limit=8 returned 8 rows from one
    # account and clipped the rest).
    dal_owner = None if effective_view == "ours" else effective_view

    with get_db() as conn:
        txns = get_transactions(
            conn,
            account_id,
            institution_id,
            start_date,
            end_date,
            status,
            limit,
            offset,
            owner_id=dal_owner,
            exclude_transfers=exclude_transfers,
        )
        total = count_transactions(
            conn,
            account_id,
            institution_id,
            start_date,
            end_date,
            status,
            owner_id=dal_owner,
            exclude_transfers=exclude_transfers,
        )
    return {"transactions": txns, "total_count": total, "count": len(txns), "view": effective_view}


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
