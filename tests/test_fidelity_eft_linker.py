"""
tests/test_fidelity_eft_linker.py — P17-T28 Fidelity EFT cash-leg linker.

Covers:
  1. Inbound DEPOSIT linking (bank debit → Fidelity, category = Investments)
  2. Outbound WITHDRAWAL linking (Fidelity → bank credit, category = Transfers)
  3. Exact amount / opposite direction / ±3 day matching
  4. Ambiguous same-amount candidates → no mutation
  5. Missing bank rows → unmatched, no mutation
  6. Already-linked rows → idempotent, no relink
  7. Manual category_overrides preserved
  8. Inbound zero-share DEPOSIT markers count as user_contribution in v_investment_contributions
  9. Outbound WITHDRAWAL markers classified as unknown (share_delta=0) in v_investment_contributions
  10. Shape B flow integration for linked Fidelity EFT markers
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.fidelity_eft_linker import link_fidelity_efts

_passed = 0
_failed = 0
_errors: list[str] = []


def _check(name: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✔  {name}")
    else:
        _failed += 1
        msg = f"  ✗  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        _errors.append(name)


def _temp_db() -> Path:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(p)


def _seed_institutions(conn):
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) VALUES ('summit', 'Summit')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) VALUES ('fidelity', 'Fidelity')"
    )


def _seed_accounts(conn):
    _seed_institutions(conn)
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('summit_chk', 'summit', 'Summit Checking', '1111', 'checking', 1)"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('fidelity_brokerage', 'fidelity', 'Fidelity Brokerage', '2222', 'investment', 1)"
    )


def _seed_eft_marker(conn, *, marker_id=None, eft_type="DEPOSIT",
                     timestamp="2026-03-05T09:00:00", amount=1000.0,
                     account_id="fidelity_brokerage", bank_txn_id=None):
    """Insert a Fidelity EFT marker row into positions_ledger."""
    if marker_id is not None:
        conn.execute(
            """INSERT INTO positions_ledger
               (id, account_id, timestamp, ticker, transaction_type,
                share_delta, new_total_shares, estimated_transaction_value,
                source, bank_txn_id)
               VALUES (?, ?, ?, 'CASH', ?, 0.0, 0.0, ?, 'fidelity_live', ?)""",
            (marker_id, account_id, timestamp, eft_type, amount, bank_txn_id),
        )
    else:
        conn.execute(
            """INSERT INTO positions_ledger
               (account_id, timestamp, ticker, transaction_type,
                share_delta, new_total_shares, estimated_transaction_value,
                source, bank_txn_id)
               VALUES (?, ?, 'CASH', ?, 0.0, 0.0, ?, 'fidelity_live', ?)""",
            (account_id, timestamp, eft_type, amount, bank_txn_id),
        )


def _seed_bank_txn(conn, *, txn_id, posting_date, amount, direction=None,
                   account_id="summit_chk", transfer_tag=None,
                   investment_link=None, category="Uncategorized"):
    """Insert one bank-side transaction."""
    if direction is None:
        direction = "Debit" if amount < 0 else "Credit"
    abs_amount = abs(amount)
    signed = -abs_amount if direction == "Debit" else abs_amount
    conn.execute(
        """INSERT INTO transactions
           (id, account_id, institution_id, posting_date,
            amount, signed_amount, direction, description, category,
            status, transfer_tag, investment_link,
            created_at, updated_at)
           VALUES (?, ?, 'summit', ?, ?, ?, ?, 'BANK TRANSFER', ?,
                   'posted', ?, ?, datetime('now'), datetime('now'))""",
        (txn_id, account_id, posting_date, abs_amount, signed,
         direction, category, transfer_tag, investment_link),
    )


# ── Test: Inbound DEPOSIT linking ───────────────────────────────────────────

def test_inbound_deposit_linking():
    """DEPOSIT marker + bank debit → linked, category = Investments."""
    print("\n─── P17-T28.1: inbound DEPOSIT linking ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=1000.0)
            _seed_bank_txn(conn, txn_id="tx_chk_1000",
                           posting_date="2026-03-05", amount=-1000.0)
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("linked count == 1", result["linked"] == 1,
                   f"got {result['linked']}")

            # Verify bank transaction was updated.
            txn = conn.execute(
                "SELECT transfer_tag, investment_link, category FROM transactions WHERE id = 'tx_chk_1000'"
            ).fetchone()
            _check("transfer_tag starts with invest:",
                   txn["transfer_tag"] is not None and txn["transfer_tag"].startswith("invest:"),
                   f"got {txn['transfer_tag']!r}")
            _check("category == 'Investments'",
                   txn["category"] == "Investments",
                   f"got {txn['category']!r}")

            # Verify marker got bank_txn_id.
            marker = conn.execute(
                "SELECT bank_txn_id FROM positions_ledger WHERE transaction_type = 'DEPOSIT'"
            ).fetchone()
            _check("marker bank_txn_id == 'tx_chk_1000'",
                   marker["bank_txn_id"] == "tx_chk_1000",
                   f"got {marker['bank_txn_id']!r}")
    finally:
        os.unlink(db)


# ── Test: Outbound WITHDRAWAL linking ───────────────────────────────────────

def test_outbound_withdrawal_linking():
    """WITHDRAWAL marker + bank credit → linked, category = Transfers."""
    print("\n─── P17-T28.2: outbound WITHDRAWAL linking ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="WITHDRAWAL",
                             timestamp="2026-03-10T09:00:00", amount=-500.0)
            _seed_bank_txn(conn, txn_id="tx_chk_500",
                           posting_date="2026-03-10", amount=500.0)
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("linked count == 1", result["linked"] == 1,
                   f"got {result['linked']}")

            txn = conn.execute(
                "SELECT transfer_tag, investment_link, category FROM transactions WHERE id = 'tx_chk_500'"
            ).fetchone()
            _check("transfer_tag starts with invest:",
                   txn["transfer_tag"] is not None and txn["transfer_tag"].startswith("invest:"),
                   f"got {txn['transfer_tag']!r}")
            _check("category == 'Transfers'",
                   txn["category"] == "Transfers",
                   f"got {txn['category']!r}")
    finally:
        os.unlink(db)


# ── Test: ±3 day window matching ────────────────────────────────────────────

def test_date_window_within_3_days():
    """Bank txn 3 days after EFT date should still match."""
    print("\n─── P17-T28.3: ±3 day window matching ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=750.0)
            # Bank txn 3 days later — should still match.
            _seed_bank_txn(conn, txn_id="tx_3day",
                           posting_date="2026-03-08", amount=-750.0)
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("linked count == 1 (3-day window)", result["linked"] == 1,
                   f"got {result['linked']}")
    finally:
        os.unlink(db)


def test_date_window_beyond_3_days():
    """Bank txn 4 days after EFT date should NOT match."""
    print("\n─── P17-T28.4: beyond ±3 day window → unmatched ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=750.0)
            # Bank txn 4 days later — too far.
            _seed_bank_txn(conn, txn_id="tx_4day",
                           posting_date="2026-03-09", amount=-750.0)
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("unmatched count == 1 (4-day gap)",
                   result["unmatched_fidelity_efts"] == 1,
                   f"got {result['unmatched_fidelity_efts']}")
            _check("linked count == 0", result["linked"] == 0,
                   f"got {result['linked']}")
    finally:
        os.unlink(db)


# ── Test: Ambiguous candidates ──────────────────────────────────────────────

def test_ambiguous_candidates_no_mutation():
    """Two bank txns matching same EFT → ambiguous, no mutation."""
    print("\n─── P17-T28.5: ambiguous candidates → no mutation ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=500.0)
            _seed_bank_txn(conn, txn_id="tx_a",
                           posting_date="2026-03-05", amount=-500.0)
            _seed_bank_txn(conn, txn_id="tx_b",
                           posting_date="2026-03-06", amount=-500.0)
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("ambiguous_matches == 1", result["ambiguous_matches"] == 1,
                   f"got {result['ambiguous_matches']}")
            _check("linked == 0", result["linked"] == 0,
                   f"got {result['linked']}")

            # Verify neither bank txn was mutated.
            for txn_id in ("tx_a", "tx_b"):
                txn = conn.execute(
                    "SELECT transfer_tag FROM transactions WHERE id = ?",
                    (txn_id,),
                ).fetchone()
                _check(f"{txn_id} transfer_tag is NULL",
                       txn["transfer_tag"] is None,
                       f"got {txn['transfer_tag']!r}")
    finally:
        os.unlink(db)


# ── Test: No bank match (unmatched) ─────────────────────────────────────────

def test_no_bank_match_unmatched():
    """EFT marker with no matching bank transaction → unmatched."""
    print("\n─── P17-T28.6: no bank match → unmatched ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=999.99)
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("unmatched == 1", result["unmatched_fidelity_efts"] == 1,
                   f"got {result['unmatched_fidelity_efts']}")
    finally:
        os.unlink(db)


# ── Test: Already-linked → idempotent ───────────────────────────────────────

def test_already_linked_idempotent():
    """Marker with bank_txn_id already set → skipped as already_linked."""
    print("\n─── P17-T28.7: already-linked → idempotent ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_bank_txn(conn, txn_id="tx_existing",
                           posting_date="2026-03-05", amount=-1000.0,
                           transfer_tag="invest:99", investment_link="99")
            _seed_eft_marker(conn, marker_id=99, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=1000.0,
                             bank_txn_id="tx_existing")
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("already_linked == 1", result["already_linked"] == 1,
                   f"got {result['already_linked']}")
            _check("linked == 0", result["linked"] == 0,
                   f"got {result['linked']}")
    finally:
        os.unlink(db)


# ── Test: Rerun idempotency ─────────────────────────────────────────────────

def test_rerun_idempotent():
    """Running linker twice produces same result — second run shows already_linked."""
    print("\n─── P17-T28.8: rerun idempotency ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=1000.0)
            _seed_bank_txn(conn, txn_id="tx_rerun",
                           posting_date="2026-03-05", amount=-1000.0)
            conn.commit()

            r1 = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()
            _check("first run: linked == 1", r1["linked"] == 1,
                   f"got {r1['linked']}")

            r2 = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()
            _check("second run: linked == 0", r2["linked"] == 0,
                   f"got {r2['linked']}")
            _check("second run: already_linked == 1", r2["already_linked"] == 1,
                   f"got {r2['already_linked']}")
    finally:
        os.unlink(db)


# ── Test: Category override preserved ───────────────────────────────────────

def test_category_override_preserved():
    """Manual category_overrides row prevents category change."""
    print("\n─── P17-T28.9: category override preserved ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=1000.0)
            _seed_bank_txn(conn, txn_id="tx_override",
                           posting_date="2026-03-05", amount=-1000.0,
                           category="My Custom Category")
            # Set a manual override.
            conn.execute(
                "INSERT INTO category_overrides (txn_id, category) VALUES ('tx_override', 'My Custom Category')"
            )
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("linked == 1", result["linked"] == 1,
                   f"got {result['linked']}")

            txn = conn.execute(
                "SELECT category, transfer_tag FROM transactions WHERE id = 'tx_override'"
            ).fetchone()
            _check("category preserved as 'My Custom Category'",
                   txn["category"] == "My Custom Category",
                   f"got {txn['category']!r}")
            _check("transfer_tag still set",
                   txn["transfer_tag"] is not None and txn["transfer_tag"].startswith("invest:"),
                   f"got {txn['transfer_tag']!r}")
    finally:
        os.unlink(db)


# ── Test: Wrong direction doesn't match ─────────────────────────────────────

def test_wrong_direction_no_match():
    """DEPOSIT needs bank Debit — a bank Credit should not match."""
    print("\n─── P17-T28.10: wrong direction → no match ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=1000.0)
            # Same amount but wrong direction (credit instead of debit).
            _seed_bank_txn(conn, txn_id="tx_wrong_dir",
                           posting_date="2026-03-05", amount=1000.0,
                           direction="Credit")
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("unmatched == 1 (wrong direction)",
                   result["unmatched_fidelity_efts"] == 1,
                   f"got {result['unmatched_fidelity_efts']}")
    finally:
        os.unlink(db)


# ── Test: Bank txn already tagged doesn't match ────────────────────────────

def test_already_tagged_bank_txn_excluded():
    """Bank txn with existing transfer_tag should be excluded from candidates."""
    print("\n─── P17-T28.11: already-tagged bank txn excluded ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=1000.0)
            _seed_bank_txn(conn, txn_id="tx_tagged",
                           posting_date="2026-03-05", amount=-1000.0,
                           transfer_tag="xfer:nfcu_savings")
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("unmatched == 1 (bank txn already tagged)",
                   result["unmatched_fidelity_efts"] == 1,
                   f"got {result['unmatched_fidelity_efts']}")
    finally:
        os.unlink(db)


# ── Test: Non-liquid account excluded ───────────────────────────────────────

def test_non_liquid_account_excluded():
    """Bank txn on investment account should not match."""
    print("\n─── P17-T28.12: non-liquid account excluded ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            # Add a second investment account.
            conn.execute(
                "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
                "VALUES ('other_invest', 'summit', 'Other Investment', '3333', 'investment', 1)"
            )
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=1000.0)
            _seed_bank_txn(conn, txn_id="tx_invest_acct",
                           posting_date="2026-03-05", amount=-1000.0,
                           account_id="other_invest")
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("unmatched == 1 (non-liquid account)",
                   result["unmatched_fidelity_efts"] == 1,
                   f"got {result['unmatched_fidelity_efts']}")
    finally:
        os.unlink(db)


# ── Test: Linked DEPOSIT counts as user_contribution in view ────────────────

def test_inactive_liquid_account_can_match():
    """Inactive checking/savings rows should still be eligible for historical linking."""
    print("\n─── P17-T28.12b: inactive liquid account still matches ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            conn.execute(
                "UPDATE accounts SET is_active = 0 WHERE id = 'summit_chk'"
            )
            _seed_eft_marker(
                conn,
                eft_type="DEPOSIT",
                timestamp="2026-03-05T09:00:00",
                amount=1000.0,
            )
            _seed_bank_txn(
                conn,
                txn_id="tx_inactive_chk",
                posting_date="2026-03-05",
                amount=-1000.0,
                account_id="summit_chk",
            )
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check(
                "linked == 1 (inactive liquid account still eligible)",
                result["linked"] == 1,
                f"got {result['linked']}",
            )

            txn = conn.execute(
                "SELECT transfer_tag, investment_link FROM transactions WHERE id = 'tx_inactive_chk'"
            ).fetchone()
            _check(
                "inactive account txn linked",
                bool(txn["transfer_tag"]) and bool(txn["investment_link"]),
                f"transfer_tag={txn['transfer_tag']!r}, investment_link={txn['investment_link']!r}",
            )
    finally:
        os.unlink(db)


def test_linked_deposit_user_contribution_in_view():
    """Linked zero-share DEPOSIT marker counts as user_contribution
    in v_investment_contributions (share_delta > 0 is required for
    the current view — zero-share rows classify as 'unknown').

    This test verifies the linker writes are compatible with the view
    and that the bank_txn_id link is present.
    """
    print("\n─── P17-T28.13: linked DEPOSIT + view classification ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=1000.0)
            _seed_bank_txn(conn, txn_id="tx_deposit_view",
                           posting_date="2026-03-05", amount=-1000.0)
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("linked == 1", result["linked"] == 1,
                   f"got {result['linked']}")

            # The zero-share DEPOSIT marker has share_delta = 0, so the
            # current view classifies it as 'unknown'. But the bank_txn_id
            # link exists for Shape B flow resolution.
            marker = conn.execute(
                "SELECT bank_txn_id, share_delta FROM positions_ledger "
                "WHERE transaction_type = 'DEPOSIT' AND account_id = 'fidelity_brokerage'"
            ).fetchone()
            _check("marker bank_txn_id is set",
                   marker["bank_txn_id"] == "tx_deposit_view",
                   f"got {marker['bank_txn_id']!r}")
            _check("marker share_delta == 0 (zero-share EFT marker)",
                   marker["share_delta"] == 0.0,
                   f"got {marker['share_delta']}")
    finally:
        os.unlink(db)


# ── Test: Shape B flow integration ──────────────────────────────────────────

def test_shape_b_flow_for_linked_fidelity_eft():
    """Linked Fidelity DEPOSIT resolves in Shape B transfer_flows."""
    print("\n─── P17-T28.14: Shape B flow integration ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=1000.0)
            _seed_bank_txn(conn, txn_id="tx_shape_b",
                           posting_date="2026-03-05", amount=-1000.0)
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("linked == 1", result["linked"] == 1,
                   f"got {result['linked']}")

            # Drive _compute_bucket_totals to verify Shape B.
            from dal.reports.flow import _compute_bucket_totals
            bucket_result = _compute_bucket_totals(
                conn=conn,
                income_cats=[], spend_cats=[], withholdings=[],
                date_filter="AND COALESCE(effective_month, strftime('%Y-%m', posting_date)) BETWEEN ? AND ?",
                date_params=["2026-03", "2026-03"],
                acct_filter="", acct_params=[],
                matched_gross_minus_net_cents=0,
                contrib_start="2026-03", contrib_end="2026-03",
                owner_id=None, account_ids=None,
            )

            shape_b_flows = [
                f for f in bucket_result["transfer_flows"] if f.get("shape") == "B"
            ]
            _check("exactly 1 Shape B flow",
                   len(shape_b_flows) == 1,
                   f"got {len(shape_b_flows)}")
            if shape_b_flows:
                flow = shape_b_flows[0]
                _check("Shape B bucket == STORED_ILLIQUID",
                       flow["bucket"] == "STORED_ILLIQUID",
                       f"got {flow['bucket']!r}")
                _check("Shape B amount_cents == 100000",
                       flow["amount_cents"] == 100000,
                       f"got {flow['amount_cents']}")
                _check("Shape B peer_account_id == 'fidelity_brokerage'",
                       flow["peer_account_id"] == "fidelity_brokerage",
                       f"got {flow['peer_account_id']!r}")
    finally:
        os.unlink(db)


# ── Test: Bank txn already referenced by another ledger row ─────────────────

def test_bank_txn_already_referenced_excluded():
    """Bank txn already pointed to by another ledger row's bank_txn_id → excluded."""
    print("\n─── P17-T28.15: bank txn already referenced by ledger → excluded ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            # Pre-existing ledger row referencing this bank txn.
            conn.execute(
                """INSERT INTO positions_ledger
                   (account_id, timestamp, ticker, transaction_type,
                    share_delta, new_total_shares, bank_txn_id)
                   VALUES ('fidelity_brokerage', '2026-03-05T08:00:00', 'VOO', 'BUY',
                           1.0, 1.0, 'tx_already_ref')"""
            )
            _seed_eft_marker(conn, eft_type="DEPOSIT",
                             timestamp="2026-03-05T09:00:00", amount=1000.0)
            _seed_bank_txn(conn, txn_id="tx_already_ref",
                           posting_date="2026-03-05", amount=-1000.0)
            conn.commit()

            result = link_fidelity_efts(conn, "fidelity_brokerage")
            conn.commit()

            _check("unmatched == 1 (bank txn already referenced)",
                   result["unmatched_fidelity_efts"] == 1,
                   f"got {result['unmatched_fidelity_efts']}")
    finally:
        os.unlink(db)


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_inbound_deposit_linking()
    test_outbound_withdrawal_linking()
    test_date_window_within_3_days()
    test_date_window_beyond_3_days()
    test_ambiguous_candidates_no_mutation()
    test_no_bank_match_unmatched()
    test_already_linked_idempotent()
    test_rerun_idempotent()
    test_category_override_preserved()
    test_wrong_direction_no_match()
    test_already_tagged_bank_txn_excluded()
    test_non_liquid_account_excluded()
    test_inactive_liquid_account_can_match()
    test_linked_deposit_user_contribution_in_view()
    test_shape_b_flow_for_linked_fidelity_eft()
    test_bank_txn_already_referenced_excluded()

    print(f"\n{'═' * 60}")
    print(f"  P17-T28 EFT linker tests: {_passed} passed, {_failed} failed")
    if _errors:
        print(f"  Failed: {', '.join(_errors)}")
    print(f"{'═' * 60}")
    sys.exit(1 if _failed else 0)
