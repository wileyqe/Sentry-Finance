"""Fidelity EFT cash-leg linker.

Links live Fidelity ``DEPOSIT`` / ``WITHDRAWAL`` marker rows in
``positions_ledger`` to existing imported bank-side transactions.
Sets the Acorns-compatible transfer shape:

  - ``transactions.transfer_tag = 'invest:{ledger_id}'``
  - ``transactions.investment_link = '{ledger_id}'``
  - ``positions_ledger.bank_txn_id = '{bank_txn_id}'``

Matching policy (hard contract):
  - Exact absolute amount to the cent.
  - Opposite cash-flow direction (DEPOSIT ↔ bank Debit, WITHDRAWAL ↔ bank Credit).
  - Bank ``posting_date`` within ±3 calendar days of the Fidelity EFT date.
  - Exactly one candidate — ambiguous matches leave both sides unmutated.
  - Bank row must be on a liquid account (checking / savings / money_market).
  - Bank row must not already have ``transfer_tag``, ``investment_link``,
    or be referenced by any ``positions_ledger.bank_txn_id``.

Caller commits. Designed for safe rerun (idempotent).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger("sentry.dal.fidelity_eft_linker")

LIQUID_ACCOUNT_TYPES = ("checking", "savings", "money_market")

# Fidelity DEPOSIT = money bank→Fidelity, so bank side is a Debit (negative signed_amount).
# Fidelity WITHDRAWAL = money Fidelity→bank, so bank side is a Credit (positive signed_amount).
_EFT_DIRECTION_MAP = {
    "DEPOSIT": "Debit",
    "WITHDRAWAL": "Credit",
}

_INBOUND_CATEGORY = "Investments"
_OUTBOUND_CATEGORY = "Transfers"


def _redact(account_id: str | None) -> str:
    if not account_id:
        return "<unknown>"
    if "_" not in account_id:
        return account_id
    institution, _, _ = account_id.rpartition("_")
    return f"{institution}_****"


def link_fidelity_efts(
    conn: sqlite3.Connection,
    fidelity_account_id: str,
) -> dict[str, Any]:
    """Match Fidelity EFT marker rows to bank-side transactions.

    Returns a structured summary with counts:
      linked, unmatched_fidelity_efts, ambiguous_matches,
      already_linked, skipped.
    """
    summary: dict[str, Any] = {
        "linked": 0,
        "unmatched_fidelity_efts": 0,
        "ambiguous_matches": 0,
        "already_linked": 0,
        "skipped": 0,
        "details": [],
    }

    # ── 1. Find unlinked Fidelity EFT marker rows ───────────────────────
    eft_markers = conn.execute(
        """
        SELECT id, timestamp, transaction_type, estimated_transaction_value
        FROM positions_ledger
        WHERE account_id = ?
          AND transaction_type IN ('DEPOSIT', 'WITHDRAWAL')
          AND share_delta = 0
          AND source = 'fidelity_live'
        ORDER BY timestamp
        """,
        (fidelity_account_id,),
    ).fetchall()

    if not eft_markers:
        return summary

    # ── 2. Pre-fetch bank txn IDs already referenced by any ledger row ──
    already_referenced_ids: set[str] = {
        row["bank_txn_id"]
        for row in conn.execute(
            "SELECT DISTINCT bank_txn_id FROM positions_ledger WHERE bank_txn_id IS NOT NULL"
        ).fetchall()
    }

    for marker in eft_markers:
        marker_id = marker["id"]
        eft_type = marker["transaction_type"]  # DEPOSIT or WITHDRAWAL
        eft_date = marker["timestamp"][:10]  # YYYY-MM-DD
        eft_amount = marker["estimated_transaction_value"]

        if eft_amount is None or eft_amount == 0:
            summary["skipped"] += 1
            continue

        # Check if this marker is already linked (has bank_txn_id set).
        existing_link = conn.execute(
            "SELECT bank_txn_id FROM positions_ledger WHERE id = ?",
            (marker_id,),
        ).fetchone()
        if existing_link and existing_link["bank_txn_id"] is not None:
            summary["already_linked"] += 1
            continue

        expected_direction = _EFT_DIRECTION_MAP.get(eft_type)
        if expected_direction is None:
            summary["skipped"] += 1
            continue

        abs_amount = abs(float(eft_amount))

        # ── 3. Find candidate bank-side transactions ────────────────────
        # Amount match to the cent, opposite direction, ±3 day window,
        # liquid account, not already tagged.
        candidates = conn.execute(
            """
            SELECT t.id, t.posting_date, t.amount, t.signed_amount,
                   t.direction, t.account_id, t.description
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.status = 'posted'
              AND a.type IN ('checking', 'savings', 'money_market')
              AND a.is_active = 1
              AND t.direction = ?
              AND ABS(t.amount - ?) < 0.005
              AND ABS(julianday(t.posting_date) - julianday(?)) <= 3
              AND (t.transfer_tag IS NULL OR t.transfer_tag = '')
              AND (t.investment_link IS NULL OR t.investment_link = '')
            """,
            (expected_direction, abs_amount, eft_date),
        ).fetchall()

        # Filter out candidates already referenced by any positions_ledger.bank_txn_id
        candidates = [
            c for c in candidates
            if c["id"] not in already_referenced_ids
        ]

        if len(candidates) == 0:
            summary["unmatched_fidelity_efts"] += 1
            summary["details"].append({
                "marker_id": marker_id,
                "eft_type": eft_type,
                "eft_date": eft_date,
                "amount": abs_amount,
                "status": "unmatched",
            })
            continue

        if len(candidates) > 1:
            summary["ambiguous_matches"] += 1
            summary["details"].append({
                "marker_id": marker_id,
                "eft_type": eft_type,
                "eft_date": eft_date,
                "amount": abs_amount,
                "candidate_count": len(candidates),
                "status": "ambiguous",
            })
            continue

        # ── 4. Exactly one candidate — link it ──────────────────────────
        bank_txn = candidates[0]
        bank_txn_id = bank_txn["id"]
        ledger_id_str = str(marker_id)

        # Determine category: Investments for inbound, Transfers for outbound.
        if eft_type == "DEPOSIT":
            target_category = _INBOUND_CATEGORY
        else:
            target_category = _OUTBOUND_CATEGORY

        # Respect manual category overrides.
        has_override = conn.execute(
            "SELECT 1 FROM category_overrides WHERE txn_id = ?",
            (bank_txn_id,),
        ).fetchone()

        # Write the Acorns-compatible link fields on the bank transaction.
        if has_override:
            conn.execute(
                """UPDATE transactions
                   SET transfer_tag = ?,
                       investment_link = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (f"invest:{ledger_id_str}", ledger_id_str, bank_txn_id),
            )
        else:
            conn.execute(
                """UPDATE transactions
                   SET transfer_tag = ?,
                       investment_link = ?,
                       category = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (f"invest:{ledger_id_str}", ledger_id_str, target_category, bank_txn_id),
            )

        # Stamp the marker row with bank_txn_id.
        conn.execute(
            "UPDATE positions_ledger SET bank_txn_id = ? WHERE id = ?",
            (bank_txn_id, marker_id),
        )

        # Track this bank_txn_id so later markers in the same run don't double-link.
        already_referenced_ids.add(bank_txn_id)

        summary["linked"] += 1
        summary["details"].append({
            "marker_id": marker_id,
            "eft_type": eft_type,
            "eft_date": eft_date,
            "amount": abs_amount,
            "bank_txn_id": bank_txn_id,
            "bank_account": _redact(bank_txn["account_id"]),
            "category_set": target_category if not has_override else "(override preserved)",
            "status": "linked",
        })

        log.info(
            "Linked Fidelity %s marker %d → bank txn %s (%s, $%.2f)",
            eft_type, marker_id, bank_txn_id,
            _redact(bank_txn["account_id"]), abs_amount,
        )

    log.info(
        "Fidelity EFT linker: %d linked, %d unmatched, %d ambiguous, "
        "%d already_linked, %d skipped",
        summary["linked"],
        summary["unmatched_fidelity_efts"],
        summary["ambiguous_matches"],
        summary["already_linked"],
        summary["skipped"],
    )

    return summary
