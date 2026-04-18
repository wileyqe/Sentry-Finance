"""
backend/routers/user_rules.py — API endpoints for user categorization rules.
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

from dal.database import get_db
from dal.user_rules import create_user_rule, get_user_rules, delete_user_rule
from dal.categorization import set_user_override

log = logging.getLogger("sentry.backend.routers.user_rules")
router = APIRouter(prefix="/api", tags=["user_rules"])

class CategorizeRequest(BaseModel):
    category: str
    merchant_name: str
    create_rule: bool = False
    match_type: Optional[str] = None
    match_value: Optional[Dict[str, Any]] = None
    mark_recurring: bool = False

@router.post("/transactions/{txn_id}/categorize")
def categorize_transaction(txn_id: str, request: CategorizeRequest):
    with get_db() as conn:
        txn = conn.execute(
            "SELECT account_id FROM transactions WHERE id = ?", (txn_id,)
        ).fetchone()
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")
            
        try:
            conn.execute("UPDATE transactions SET merchant = ? WHERE id = ?", (request.merchant_name, txn_id))
        except Exception:
            pass

        set_user_override(conn, txn_id, request.category)
        
        if request.create_rule and request.match_type and request.match_value:
            rule_id = create_user_rule(
                conn,
                txn_id,
                request.category,
                request.merchant_name,
                request.match_type,
                request.match_value
            )
            
            if request.mark_recurring:
                conn.execute(
                    "UPDATE user_categorization_rules SET is_recurring = 1 WHERE id = ?",
                    (rule_id,)
                )
                from dal.recurring import _make_recurring_id
                rec_id = _make_recurring_id(txn["account_id"], request.merchant_name.lower())
                freq = "monthly"
                amount_stable = 1 if request.match_type == "exact_amount" else 0
                
                existing = conn.execute(
                    "SELECT id FROM recurring_transactions WHERE id = ?", (rec_id,)
                ).fetchone()
                
                if existing:
                    conn.execute(
                        """
                        UPDATE recurring_transactions 
                        SET category = ?, expected_amount = ?, amount_stable = ?, updated_at = datetime('now')
                        WHERE id = ?
                        """,
                        (request.category, txn["amount"], amount_stable, rec_id)
                    )
                else:
                    avg_interval = 30.0 if freq == "monthly" else 90.0
                    conn.execute(
                        """
                        INSERT INTO recurring_transactions
                        (id, account_id, merchant, category, frequency, avg_interval, status, amount_stable, expected_amount)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (rec_id, txn["account_id"], request.merchant_name, request.category, freq, avg_interval, "active", amount_stable, txn["amount"])
                    )
        
        conn.commit()
    return {"status": "success"}

@router.get("/user-rules")
def list_user_rules():
    with get_db() as conn:
        rules = get_user_rules(conn)
    return rules

@router.delete("/user-rules/{rule_id}")
def delete_user_rule_endpoint(rule_id: int):
    with get_db() as conn:
        delete_user_rule(conn, rule_id)
        conn.commit()
    return {"status": "success"}
