"""
dal/reconciliation.py — Transfer reconciliation across institutions.

Identifies matching debit/credit pairs across different institutions
(e.g. NFCU checking → Fidelity brokerage) and tags them with a shared
transfer_tag UUID to prevent double-counting in income/spending metrics.
"""

import logging
import sqlite3
import uuid

log = logging.getLogger("sentry.dal.reconciliation")

# Keywords that indicate a transaction is an internal transfer
_TRANSFER_KEYWORDS = [
    "transfer",
    "ach",
    "xfer",
    "fidelity",
    "acorns",
    "tsp",
    "affirm",
    "chase",
    "navy federal",
    "nfcu",
    "direct deposit",
    "payroll",
]

# Categories that are almost always transfers
_TRANSFER_CATEGORIES = {
    "Transfers",
    "Credit Card Payments",
    "Savings",
}


def reconcile_transfers(
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> dict:
    """Scan transactions for matching pairs and tag them.

    Match criteria:
      1. Same absolute amount
      2. Opposite directions (one debit, one credit)
      3. Different institutions
      4. Posting dates within 3 days of each other
      5. At least one has a transfer-like keyword or category

    Returns stats: {pairs_found, already_tagged, newly_tagged}
    """
    stats = {"pairs_found": 0, "already_tagged": 0, "newly_tagged": 0}

    # Get all untagged transactions
    untagged = conn.execute("""
        SELECT t.id, t.account_id, t.institution_id, t.posting_date,
               t.amount, t.signed_amount, t.direction,
               t.description, t.category, t.transfer_tag
        FROM transactions t
        WHERE t.status = 'posted'
        ORDER BY t.posting_date, t.amount
    """).fetchall()

    # Build lookup by amount for efficient matching
    by_amount: dict[float, list] = {}
    for row in untagged:
        amt = round(abs(row["amount"]), 2)
        by_amount.setdefault(amt, []).append(dict(row))

    processed_ids = set()

    for amt, txns in by_amount.items():
        if len(txns) < 2:
            continue

        for i, t1 in enumerate(txns):
            if t1["id"] in processed_ids:
                continue

            for t2 in txns[i + 1 :]:
                if t2["id"] in processed_ids:
                    continue
                if t1["institution_id"] == t2["institution_id"]:
                    continue  # Same institution — not a transfer
                if t1["direction"] == t2["direction"]:
                    continue  # Same direction — not a pair

                # Check date proximity (within 3 days)
                try:
                    from datetime import datetime

                    d1 = datetime.strptime(t1["posting_date"][:10], "%Y-%m-%d")
                    d2 = datetime.strptime(t2["posting_date"][:10], "%Y-%m-%d")
                    if abs((d1 - d2).days) > 3:
                        continue
                except (ValueError, TypeError):
                    continue

                # Check if at least one is transfer-like
                is_transfer = False
                for t in (t1, t2):
                    if t.get("category") in _TRANSFER_CATEGORIES:
                        is_transfer = True
                        break
                    desc = (t.get("description") or "").lower()
                    if any(kw in desc for kw in _TRANSFER_KEYWORDS):
                        is_transfer = True
                        break

                if not is_transfer:
                    continue

                stats["pairs_found"] += 1

                # Both already tagged?
                if t1.get("transfer_tag") and t2.get("transfer_tag"):
                    stats["already_tagged"] += 1
                    processed_ids.update([t1["id"], t2["id"]])
                    continue

                if not dry_run:
                    tag = str(uuid.uuid4())[:8]
                    conn.execute(
                        "UPDATE transactions SET transfer_tag = ? WHERE id = ?",
                        (tag, t1["id"]),
                    )
                    conn.execute(
                        "UPDATE transactions SET transfer_tag = ? WHERE id = ?",
                        (tag, t2["id"]),
                    )
                    stats["newly_tagged"] += 1
                    log.debug(
                        "Tagged transfer pair: %s ↔ %s ($%.2f, tag=%s)",
                        t1["account_id"],
                        t2["account_id"],
                        amt,
                        tag,
                    )
                else:
                    stats["newly_tagged"] += 1
                    log.debug(
                        "[DRY RUN] Would tag: %s ↔ %s ($%.2f)",
                        t1["account_id"],
                        t2["account_id"],
                        amt,
                    )

                processed_ids.update([t1["id"], t2["id"]])
                break  # One match per source txn

    if not dry_run:
        conn.commit()

    log.info(
        "Transfer reconciliation: %d pairs found, %d newly tagged, %d already tagged",
        stats["pairs_found"],
        stats["newly_tagged"],
        stats["already_tagged"],
    )
    return stats


def get_transfer_pairs(conn: sqlite3.Connection) -> list[dict]:
    """Return all tagged transfer pairs for display."""
    rows = conn.execute("""
        SELECT transfer_tag, account_id, institution_id, posting_date,
               amount, direction, description
        FROM transactions
        WHERE transfer_tag IS NOT NULL
        ORDER BY transfer_tag, posting_date
    """).fetchall()
    return [dict(r) for r in rows]
