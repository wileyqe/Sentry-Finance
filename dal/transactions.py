"""
dal/transactions.py — Transaction upsert logic with deterministic identity.

Key principles:
  - Each transaction has a stable, deterministic unique ID
  - Prefer institution-provided IDs when available
  - Fall back to SHA-256 hash of (institution, account, date, amount, desc)
  - Upserts: INSERT new, UPDATE changed (pending→posted, description fixes)
  - Soft-delete: mark status='deleted' if removed upstream
"""

import hashlib
import logging
import re
import sqlite3
from datetime import datetime

log = logging.getLogger("sentry")


# ── Transaction Identity ─────────────────────────────────────────────────────


def _normalize_description(desc: str) -> str:
    """Normalize description for stable hashing.

    Strips whitespace, lowercases, removes common noise like
    check numbers and trailing reference IDs.
    """
    if not desc:
        return ""
    s = desc.strip().lower()
    s = re.sub(r"\s+", " ", s)  # collapse whitespace
    s = re.sub(r"#\d+$", "", s)  # trailing check/ref numbers
    s = re.sub(r"\bref\b.*$", "", s)  # trailing "ref..." suffixes
    return s.strip()


def compute_txn_id(
    institution_id: str,
    account_id: str,
    posting_date: str,
    amount: float,
    description: str,
    institution_txn_id: str | None = None,
    transaction_date: str | None = None,
) -> str:
    """Generate a stable unique key for a transaction.

    If the institution provides a transaction ID, we use it directly
    (prefixed with the institution). Otherwise, we generate a
    deterministic SHA-256 hash from the transaction's attributes.

    Args:
        institution_id: e.g. "nfcu"
        account_id: e.g. "nfcu_1167"
        posting_date: ISO date string "2026-02-15"
        amount: absolute amount
        description: raw description text
        institution_txn_id: bank-provided unique ID, if any
        transaction_date: actual transaction date, if available

    Returns:
        Stable string ID like "nfcu:BANK123" or "nfcu:h:a1b2c3d4..."
    """
    if institution_txn_id:
        return f"{institution_id}:{institution_txn_id}"

    # Expand identity key entropy to avoid collision on same-day/same-amount purchases
    # but still allow minor pending->posted description mutations to merge.
    normalized = _normalize_description(description)
    desc_fragment = normalized[:15] if normalized else ""
    t_date = transaction_date or posting_date

    raw = f"{institution_id}|{account_id}|{t_date}|{posting_date}|{abs(amount):.2f}|{desc_fragment}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{institution_id}:h:{h}"


# ── Upsert Operations ────────────────────────────────────────────────────────


def upsert_transactions(
    conn: sqlite3.Connection, txns: list[dict], refresh_run_id: str | None = None
) -> dict:
    """Upsert a batch of transactions.

    Each dict in `txns` must contain:
        account_id, institution_id, posting_date, amount,
        signed_amount, direction, description

    Optional fields:
        transaction_date, category, status, raw_description,
        institution_txn_id

    Returns:
        {"inserted": int, "updated": int, "unchanged": int}
    """
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}
    now = datetime.utcnow().isoformat()

    for txn in txns:
        txn_id = compute_txn_id(
            institution_id=txn["institution_id"],
            account_id=txn["account_id"],
            posting_date=txn["posting_date"],
            amount=txn["amount"],
            description=txn.get("description", ""),
            institution_txn_id=txn.get("institution_txn_id"),
            transaction_date=txn.get("transaction_date"),
        )

        existing = conn.execute(
            "SELECT id, status, description, category FROM transactions WHERE id = ?",
            (txn_id,),
        ).fetchone()

        if existing is None:
            # New transaction — INSERT
            conn.execute(
                """
                INSERT INTO transactions (
                    id, account_id, institution_id, posting_date,
                    transaction_date, amount, signed_amount, direction,
                    description, category, status, raw_description,
                    institution_txn_id, created_at, updated_at,
                    refresh_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    txn_id,
                    txn["account_id"],
                    txn["institution_id"],
                    txn["posting_date"],
                    txn.get("transaction_date"),
                    txn["amount"],
                    txn["signed_amount"],
                    txn["direction"],
                    txn.get("description", ""),
                    txn.get("category", "Uncategorized"),
                    txn.get("status", "posted"),
                    txn.get("raw_description"),
                    txn.get("institution_txn_id"),
                    now,
                    now,
                    refresh_run_id,
                ),
            )
            stats["inserted"] += 1

        else:
            # Existing transaction — check for updates
            new_status = txn.get("status", "posted")
            old_status = existing["status"]
            new_desc = txn.get("description", "")
            old_desc = existing["description"] or ""

            # Promote pending→posted, or update description
            changed = False
            updates = {}

            if old_status == "pending" and new_status == "posted":
                updates["status"] = "posted"
                changed = True

            if new_desc and new_desc != old_desc:
                updates["description"] = new_desc
                changed = True

            if changed:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                values = list(updates.values())
                values.extend([now, refresh_run_id, txn_id])
                conn.execute(
                    f"UPDATE transactions SET {set_clause}, "
                    f"updated_at = ?, refresh_run_id = ? "
                    f"WHERE id = ?",
                    values,
                )
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1

    return stats


def soft_delete_missing(
    conn: sqlite3.Connection,
    account_id: str,
    current_txn_ids: set[str],
    refresh_run_id: str | None = None,
) -> int:
    """Soft-delete transactions that are no longer present upstream.

    Marks status='deleted' for any posted transaction in the given
    account that is NOT in the current_txn_ids set.

    Returns the number of soft-deleted transactions.
    """
    now = datetime.utcnow().isoformat()
    rows = conn.execute(
        "SELECT id FROM transactions WHERE account_id = ? AND status = 'posted'",
        (account_id,),
    ).fetchall()

    deleted = 0
    for row in rows:
        if row["id"] not in current_txn_ids:
            conn.execute(
                "UPDATE transactions SET status = 'deleted', "
                "updated_at = ?, refresh_run_id = ? WHERE id = ?",
                (now, refresh_run_id, row["id"]),
            )
            deleted += 1

    return deleted


def get_transactions(
    conn: sqlite3.Connection,
    account_id: str | None = None,
    institution_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    status: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict]:
    """Query transactions with optional filters.

    Returns list of dicts with all transaction fields.
    """
    clauses = ["1=1"]
    params: list = []

    if account_id:
        clauses.append("account_id = ?")
        params.append(account_id)
    if institution_id:
        clauses.append("institution_id = ?")
        params.append(institution_id)
    if start_date:
        clauses.append("posting_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("posting_date <= ?")
        params.append(end_date)
    if status:
        clauses.append("status = ?")
        params.append(status)

    where = " AND ".join(clauses)
    params.extend([limit, offset])

    rows = conn.execute(
        f"SELECT * FROM transactions WHERE {where} "
        f"ORDER BY posting_date DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()

    return [dict(r) for r in rows]
