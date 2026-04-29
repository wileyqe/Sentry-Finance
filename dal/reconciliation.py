"""
dal/reconciliation.py — Transfer reconciliation across institutions.

Identifies matching debit/credit pairs across different institutions
(e.g. NFCU checking → Fidelity brokerage) and tags them with a shared
transfer_tag UUID to prevent double-counting in income/spending metrics.
"""

import logging
import sqlite3
import hashlib

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
    "moneyline",
    "mobilepay",
    "real time payment",
    "ach credit",
    "ach debit",
    "ach payment",
    "electronic deposit",
    "online transfer",
    "internal transfer",
    "autopay",
    "auto pay",
]

# Categories that are almost always transfers — from canonical source of truth
from dal.category_classifications import TRANSFER_CATEGORIES as _TRANSFER_CATEGORIES
from dal.category_classifications import LOAN_CATEGORIES as _LOAN_CATEGORIES

_LIABILITY_ACCOUNT_TYPES = {"credit_card", "credit", "loan", "mortgage", "bnpl"}


def _stable_transfer_tag(left_id: str, right_id: str) -> str:
    ordered = sorted([str(left_id), str(right_id)])
    digest = hashlib.sha256("|".join(ordered).encode("utf-8")).hexdigest()[:12]
    return f"xfer_{digest}"


def _is_transfer_like(txn: dict) -> bool:
    category = txn.get("category")
    if category in _TRANSFER_CATEGORIES or category in _LOAN_CATEGORIES:
        return True
    desc = (txn.get("description") or "").lower()
    return any(kw in desc for kw in _TRANSFER_KEYWORDS)


def _pair_allowed(t1: dict, t2: dict) -> bool:
    """Reject high-risk false positives before assigning a transfer tag."""
    s1 = float(t1["signed_amount"] or 0)
    s2 = float(t2["signed_amount"] or 0)
    if not ((s1 < 0 < s2) or (s2 < 0 < s1)):
        return False

    debit = t1 if s1 < 0 else t2
    credit = t2 if debit is t1 else t1
    debit_type = (debit.get("account_type") or "").strip().lower()
    credit_type = (credit.get("account_type") or "").strip().lower()

    if not (_is_transfer_like(debit) or _is_transfer_like(credit)):
        return False

    # A liability-account debit with a merchant category is usually a credit
    # card purchase, not cash moving between accounts. Never pair two
    # liability-side legs; the real cash payment should originate from a cash
    # account when both sides are visible.
    if debit_type in _LIABILITY_ACCOUNT_TYPES and credit_type in _LIABILITY_ACCOUNT_TYPES:
        return False
    if debit_type in _LIABILITY_ACCOUNT_TYPES and not _is_transfer_like(debit):
        return False

    return True

# ── Known Patterns ──────────────────────────────────────────────────
# Mortgage overfunding: Owner transfers more than the mortgage payment
# to NFCU XXXX (dedicated mortgage funding account). The transfer is
# correctly tagged. The mortgage payment debit from XXXX is also
# correctly tagged. The excess balance in XXXX is visible in balance
# snapshots and represents earmarked savings, not spending.
#
# No special reconciliation logic needed — the existing same-institution
# transfer matching (added in P0-T03) handles the transfer-in, and the
# mortgage payment is a separate transaction that categorizes as
# "Mortgage" (excluded from spending by _EXCLUDED_FROM_SPEND).


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
               t.description, t.category, t.transfer_tag,
               a.type AS account_type
        FROM transactions t
        LEFT JOIN accounts a ON a.id = t.account_id
        WHERE t.status = 'posted'
        ORDER BY t.posting_date, t.amount
    """).fetchall()

    # Build lookup by amount for efficient matching.
    # Key in INTEGER CENTS (round to 2dp then ×100 → int) — never float.
    # Float keys are unsafe: two transactions that differ by an IEEE 754
    # representation epsilon would hash to different buckets and the match
    # would silently miss. Integer cents are exact.
    by_amount: dict[int, list] = {}
    for row in untagged:
        # Normalise to cents: $1,234.56 → 123456
        cents = int(round(abs(row["amount"]) * 100))
        by_amount.setdefault(cents, []).append(dict(row))

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
                if not _pair_allowed(t1, t2):
                    continue

                # Check date proximity (within 3 days)
                try:
                    from datetime import datetime

                    d1 = datetime.strptime(t1["posting_date"][:10], "%Y-%m-%d")
                    d2 = datetime.strptime(t2["posting_date"][:10], "%Y-%m-%d")
                    if abs((d1 - d2).days) > 3:
                        continue
                except (ValueError, TypeError):
                    continue

                stats["pairs_found"] += 1

                # Both already tagged?
                if t1.get("transfer_tag") and t2.get("transfer_tag"):
                    stats["already_tagged"] += 1
                    processed_ids.update([t1["id"], t2["id"]])
                    continue

                if not dry_run:
                    tag = _stable_transfer_tag(t1["id"], t2["id"])
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
                        amt / 100.0,
                        tag,
                    )
                else:
                    stats["newly_tagged"] += 1
                    log.debug(
                        "[DRY RUN] Would tag: %s ↔ %s ($%.2f)",
                        t1["account_id"],
                        t2["account_id"],
                        amt / 100.0,
                    )

                processed_ids.update([t1["id"], t2["id"]])
                break  # One match per source txn

        # SECOND PASS: Same-institution, different account (1-day window)
        for i, t1 in enumerate(txns):
            if t1["id"] in processed_ids:
                continue

            for t2 in txns[i + 1 :]:
                if t2["id"] in processed_ids:
                    continue
                if t1["institution_id"] != t2["institution_id"]:
                    continue  # We only want same institution here
                if t1["account_id"] == t2["account_id"]:
                    continue  # Must be different accounts
                if not _pair_allowed(t1, t2):
                    continue

                # Check date proximity (within 1 day for same-inst)
                try:
                    from datetime import datetime

                    d1 = datetime.strptime(t1["posting_date"][:10], "%Y-%m-%d")
                    d2 = datetime.strptime(t2["posting_date"][:10], "%Y-%m-%d")
                    if abs((d1 - d2).days) > 1:
                        continue
                except (ValueError, TypeError):
                    continue

                stats["pairs_found"] += 1

                # Both already tagged?
                if t1.get("transfer_tag") and t2.get("transfer_tag"):
                    stats["already_tagged"] += 1
                    processed_ids.update([t1["id"], t2["id"]])
                    continue

                if not dry_run:
                    tag = _stable_transfer_tag(t1["id"], t2["id"])
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
                        "Tagged same-inst transfer pair: %s ↔ %s ($%.2f, tag=%s)",
                        t1["account_id"],
                        t2["account_id"],
                        amt / 100.0,
                        tag,
                    )
                else:
                    stats["newly_tagged"] += 1
                    log.debug(
                        "[DRY RUN] Would tag same-inst: %s ↔ %s ($%.2f)",
                        t1["account_id"],
                        t2["account_id"],
                        amt / 100.0,
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
