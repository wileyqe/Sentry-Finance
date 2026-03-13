"""Account, balance, and loan-detail endpoints."""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from dal.database import get_db
from dal.balances import (
    get_all_latest_balances,
    get_balance_history,
    get_latest_loan_details,
)
from dal.owners import (
    list_owners as dal_list_owners,
    create_owner,
    assign_account_owner,
    resolve_account_ids_for_view,
)

router = APIRouter(tags=["accounts"])


# ── Account & Balance Endpoints ──────────────────────────────────────────────


@router.get("/api/accounts")
def list_accounts(view: str = Query("ours")):
    """List all accounts with their latest balances.

    Query params:
        view: "ours" (all), "mine" (my accounts), "theirs" (partner's)
    """
    with get_db() as conn:
        balances = get_all_latest_balances(conn)
        # Get account filter for view
        view_account_ids = resolve_account_ids_for_view(conn, view)

        if view_account_ids is not None:
            all_accounts = conn.execute(
                "SELECT id, institution_id, name, last4, type, owner_id "
                "FROM accounts WHERE is_active = 1 AND id IN ({})".format(
                    ",".join("?" for _ in view_account_ids)
                ),
                list(view_account_ids),
            ).fetchall()
        else:
            all_accounts = conn.execute(
                "SELECT id, institution_id, name, last4, type, owner_id "
                "FROM accounts WHERE is_active = 1"
            ).fetchall()
        all_accounts = [dict(r) for r in all_accounts]

        # Get total latest holdings value for each account
        holdings_rows = conn.execute(
            """
            SELECT ih.account_id, SUM(ih.market_value) as total_holdings
            FROM investment_holdings ih
            WHERE ih.date = (
                SELECT MAX(date) FROM investment_holdings ih2
                WHERE ih2.account_id = ih.account_id
            )
            GROUP BY ih.account_id
            """
        ).fetchall()
        holdings_map = {r["account_id"]: r["total_holdings"] for r in holdings_rows}

    # Merge balances into accounts
    bal_map = {b["account_id"]: b for b in balances}
    for acct in all_accounts:
        bal = bal_map.get(acct["id"])
        acct["balance"] = bal["balance"] if bal else None
        acct["balance_as_of"] = bal["as_of"] if bal else None
        acct["holdings_value"] = holdings_map.get(acct["id"])

    return {"accounts": all_accounts, "view": view}


@router.get("/api/balances/{account_id}/history")
def balance_history(
    account_id: str,
    start_date: str = Query(None),
    end_date: str = Query(None),
    limit: int = Query(365, le=1000),
):
    """Get balance history for an account."""
    with get_db() as conn:
        history = get_balance_history(conn, account_id, start_date, end_date, limit)
    return {"account_id": account_id, "history": history}


@router.get("/api/loan-details/{account_id}")
def loan_details(account_id: str):
    """Get latest loan details for an account."""
    with get_db() as conn:
        details = get_latest_loan_details(conn, account_id)
    return {"account_id": account_id, "details": details}


# ── Owner Endpoints ──────────────────────────────────────────────────────────


@router.get("/api/owners")
def owners_list():
    """List all configured owners."""
    with get_db() as conn:
        owners = dal_list_owners(conn)
    return {"owners": owners}


@router.post("/api/owners")
def owners_create(owner_id: str = Query(...), display_name: str = Query(...)):
    """Create a new owner."""
    with get_db() as conn:
        create_owner(conn, owner_id, display_name)
        conn.commit()
    return {"status": "created", "owner_id": owner_id}


@router.patch("/api/accounts/{account_id}/owner")
def account_set_owner(account_id: str, owner_id: str = Query(None)):
    """Assign or clear an account's owner.

    Pass owner_id=null to make the account shared ("ours").
    """
    with get_db() as conn:
        # Verify account exists
        acct = conn.execute(
            "SELECT id FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if not acct:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        # Verify owner exists (if setting one)
        if owner_id:
            owner = conn.execute(
                "SELECT id FROM owners WHERE id = ?", (owner_id,)
            ).fetchone()
            if not owner:
                raise HTTPException(status_code=404, detail=f"Owner {owner_id} not found")

        assign_account_owner(conn, account_id, owner_id)
        conn.commit()
    return {"status": "updated", "account_id": account_id, "owner_id": owner_id}
