"""Account, balance, and loan-detail endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field


from dal.database import get_db
from backend.events import is_refresh_active
from dal.balances import (
    get_all_latest_balances,
    get_balance_history,
    get_latest_loan_details,
)
from dal.owners import (
    list_owners as dal_list_owners,
    create_owner,
    update_owner,
    assign_account_owner,
    resolve_account_ids_for_view,
)

router = APIRouter(tags=["accounts"])


# ── Account & Balance Endpoints ──────────────────────────────────────────────


@router.get("/api/accounts")
def list_accounts(
    view: str = Query("ours"),
    owner_id: Optional[str] = Query(None),
):
    """List all accounts with their latest balances.

    Query params:
        view: "ours" (all), "mine" (my accounts), "theirs" (partner's),
              or an owner_id string.
        owner_id: Alias for view. Accepts any owner_id string; takes
            precedence over `view` when both are supplied. The frontend
            `InvestmentsPage` and other pages threading via
            `ownerParam` from `ViewContext` pass this param.

    Filters out accounts with no data (no balance snapshots AND no
    transactions).  These are institution stubs that ``seed_institutions``
    creates from ``accounts.yaml`` on every backend startup so live
    connectors have a target to write to — but they appear as
    "Pending $0.00" rows on the Accounts page until a connector
    populates them.  Hiding them at the API edge avoids false data
    rows in the UI without removing the underlying stubs (which the
    connector pipeline still needs).
    """
    # owner_id takes precedence over view when both are supplied
    effective_view = owner_id or view
    with get_db() as conn:
        balances = get_all_latest_balances(conn)
        # Get account filter for view
        view_account_ids = resolve_account_ids_for_view(conn, effective_view)

        # Only surface accounts that have at least one balance_snapshot
        # OR at least one transaction.  Empty institution stubs are
        # filtered out.
        data_filter = (
            "AND id IN ("
            "  SELECT DISTINCT account_id FROM balance_snapshots"
            "  UNION"
            "  SELECT DISTINCT account_id FROM transactions"
            ")"
        )

        if view_account_ids is not None:
            if not view_account_ids:
                # Resolved to zero accounts (e.g. Amy with no data) —
                # skip the query entirely. An empty IN () would be a
                # SQL syntax error.
                all_accounts = []
            else:
                all_accounts = conn.execute(
                    "SELECT id, institution_id, name, last4, type, owner_id, closed_at "
                    f"FROM accounts WHERE is_active = 1 {data_filter} "
                    "AND id IN ({})".format(",".join("?" for _ in view_account_ids)),
                    list(view_account_ids),
                ).fetchall()
        else:
            all_accounts = conn.execute(
                "SELECT id, institution_id, name, last4, type, owner_id, closed_at "
                f"FROM accounts WHERE is_active = 1 {data_filter}"
            ).fetchall()
        all_accounts = [dict(r) for r in all_accounts]

        # Pivot loan_details KV table into structured columns per account
        loan_detail_rows = conn.execute(
            """
            SELECT account_id,
                   MAX(CASE WHEN field_name='purchase_price'   THEN CAST(field_value AS REAL) END) AS purchase_price,
                   MAX(CASE WHEN field_name='interest_rate'    THEN CAST(field_value AS REAL) END) AS interest_rate,
                   MAX(CASE WHEN field_name='minimum_payment'  THEN CAST(field_value AS REAL) END) AS minimum_payment,
                   MAX(CASE WHEN field_name='term_months'      THEN CAST(field_value AS INTEGER) END) AS term_months,
                   MAX(CASE WHEN field_name='origination_date' THEN field_value END) AS origination_date,
                   MAX(CASE WHEN field_name='credit_limit'     THEN CAST(field_value AS REAL) END) AS credit_limit
            FROM loan_details
            GROUP BY account_id
            """
        ).fetchall()
        loan_detail_map = {r["account_id"]: dict(r) for r in loan_detail_rows}

        # Enrich investment/retirement accounts with portfolio value
        # from portfolio_snapshots (P13-T03 canonical source).
        inv_acct_ids = [a["id"] for a in all_accounts
                        if a["type"] in ("investment", "retirement")]
        holdings_map: dict[str, float] = {}
        for inv_id in inv_acct_ids:
            snap = conn.execute(
                """SELECT total_account_value
                   FROM portfolio_snapshots
                   WHERE account_id = ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (inv_id,),
            ).fetchone()
            if snap and snap["total_account_value"]:
                holdings_map[inv_id] = snap["total_account_value"]

    # Merge balances + loan details into accounts
    bal_map = {b["account_id"]: b for b in balances}

    for acct in all_accounts:
        bal = bal_map.get(acct["id"])
        acct["balance"] = bal["balance"] if bal else None
        acct["balance_as_of"] = bal["as_of"] if bal else None
        if acct["id"] in holdings_map:
            portfolio_val = holdings_map[acct["id"]]
            acct["holdings_value"] = portfolio_val
            if (acct["balance"] or 0) == 0:
                acct["balance"] = portfolio_val
        if acct["id"] in loan_detail_map:
            ld = loan_detail_map[acct["id"]]
            acct["purchase_price"]   = ld.get("purchase_price")
            acct["interest_rate"]    = ld.get("interest_rate")
            acct["minimum_payment"]  = ld.get("minimum_payment")
            acct["term_months"]      = ld.get("term_months")
            acct["origination_date"] = ld.get("origination_date")
            acct["credit_limit"]     = ld.get("credit_limit")

    # Classify account status
    # Revolving types (credit cards) are always "active" even at $0
    REVOLVING_TYPES = {"credit_card", "credit"}
    # Installment types auto-classify as "paid_off" when balance >= 0
    INSTALLMENT_TYPES = {"loan", "mortgage", "bnpl"}

    for acct in all_accounts:
        if acct.get("closed_at"):
            acct["status"] = "closed"
        elif acct["type"] in INSTALLMENT_TYPES:
            bal = acct.get("balance")
            # paid_off if balance is 0 or positive (sometimes small positive from overpay)
            if bal is not None and bal >= 0:
                acct["status"] = "paid_off"
            else:
                acct["status"] = "active"
        else:
            # Credit cards, checking, savings, investments — always active
            acct["status"] = "active"

    return {"accounts": all_accounts, "view": view, "refresh_in_progress": is_refresh_active()}


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


@router.patch("/api/accounts/{account_id}/close")
def account_close(account_id: str, reopen: bool = Query(False)):
    """Close or reopen an account.

    Pass reopen=true to reactivate a previously closed account.
    """
    with get_db() as conn:
        acct = conn.execute(
            "SELECT id, closed_at FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if not acct:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        if reopen:
            conn.execute(
                "UPDATE accounts SET closed_at = NULL WHERE id = ?",
                (account_id,),
            )
            conn.commit()
            return {"status": "reopened", "account_id": account_id}
        else:
            now = datetime.now().replace(microsecond=0).isoformat()
            conn.execute(
                "UPDATE accounts SET closed_at = ? WHERE id = ?",
                (now, account_id),
            )
            conn.commit()
            return {"status": "closed", "account_id": account_id, "closed_at": now}


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


class OwnerUpdate(BaseModel):
    """Body shape for PATCH /api/owners/{owner_id}.

    Only fields supplied in the request are written. Future cosmetic
    fields (avatar_emoji, color_hex, archived) slot in here without a
    schema redesign.
    """

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=50)


@router.patch("/api/owners/{owner_id}")
def owners_update(owner_id: str, body: OwnerUpdate):
    """Update an owner's mutable attributes (display name today)."""
    with get_db() as conn:
        try:
            update_owner(conn, owner_id, display_name=body.display_name)
        except ValueError as e:
            msg = str(e)
            status = 404 if "not found" in msg.lower() else 400
            raise HTTPException(status_code=status, detail=msg)
        conn.commit()
    return {"status": "updated", "owner_id": owner_id}


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
