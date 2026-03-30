"""
dal/user_rules.py — User-defined categorization rules.
"""

import logging
import sqlite3
import re
from typing import Optional

log = logging.getLogger("sentry.dal.user_rules")

def create_user_rule(
    conn: sqlite3.Connection,
    transaction_id: str,
    category: str,
    merchant_name: str,
    match_type: str,
    match_value: dict,
) -> int:
    """Create a user categorization rule.

    match_type + match_value:
      "exact_amount"  -> {"amount": 105.00, "tolerance": 2.00}
      "amount_range"  -> {"min_amount": 45.00, "max_amount": 65.00}
      "description"   -> {"pattern": "CHECK.*1234"}  (rare, for specific payors)

    Rules are stored in a new table and applied during categorization
    AFTER user overrides but BEFORE keyword rules.
    """
    match_amount = match_value.get("amount") if match_type == "exact_amount" else None
    match_tolerance = match_value.get("tolerance", 2.0) if match_type == "exact_amount" else 2.0
    match_min_amount = match_value.get("min_amount") if match_type == "amount_range" else None
    match_max_amount = match_value.get("max_amount") if match_type == "amount_range" else None
    match_pattern = match_value.get("pattern") if match_type == "description" else None

    source_account_id = None

    cursor = conn.execute(
        """
        INSERT INTO user_categorization_rules (
            category, merchant_name, match_type, match_amount, match_tolerance,
            match_min_amount, match_max_amount, match_pattern, source_account_id, created_from_txn_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            category, merchant_name, match_type, match_amount, match_tolerance,
            match_min_amount, match_max_amount, match_pattern, source_account_id, transaction_id
        )
    )
    rule_id = cursor.lastrowid
    log.info("Created user rule %d for category '%s'", rule_id, category)
    return rule_id


def apply_user_rules(conn: sqlite3.Connection, transaction: dict) -> Optional[str]:
    """Try to match a transaction against user-created rules.
    Returns the category if matched, None otherwise.
    """
    amount = transaction.get("amount") or 0.0
    abs_amount = abs(amount)
    description = transaction.get("description") or ""
    
    rules = get_user_rules(conn)
    for rule in rules:
        matches = False
        mt = rule["match_type"]
        
        if mt == "exact_amount":
            tgt = rule.get("match_amount")
            tol = rule.get("match_tolerance") or 2.0
            if tgt is not None and abs(abs_amount - tgt) <= tol:
                matches = True
                
        elif mt == "amount_range":
            mn = rule.get("match_min_amount")
            mx = rule.get("match_max_amount")
            if mn is not None and mx is not None and mn <= abs_amount <= mx:
                matches = True
                
        elif mt == "description":
            pat = rule.get("match_pattern")
            if pat:
                try:
                    if re.search(pat, description, re.IGNORECASE):
                        matches = True
                except re.error:
                    pass
        
        if matches:
            conn.execute(
                "UPDATE user_categorization_rules SET occurrence_count = occurrence_count + 1 WHERE id = ?",
                (rule["id"],)
            )
            txn_id = transaction.get("id")
            if txn_id:
                try:
                    conn.execute(
                        "UPDATE transactions SET merchant = ? WHERE id = ?",
                        (rule["merchant_name"], txn_id)
                    )
                except sqlite3.OperationalError:
                    pass
            
            log.debug("User rule %d matched: %s -> %s", rule["id"], description, rule["category"])
            return rule["category"]
            
    return None

def get_user_rules(conn: sqlite3.Connection) -> list[dict]:
    """List all user-created categorization rules."""
    try:
        rows = conn.execute("SELECT * FROM user_categorization_rules ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []

def delete_user_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    """Delete a user rule."""
    conn.execute("DELETE FROM user_categorization_rules WHERE id = ?", (rule_id,))
    log.info("Deleted user rule %d", rule_id)
