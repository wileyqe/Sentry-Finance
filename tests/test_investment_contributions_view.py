"""
tests/test_investment_contributions_view.py — Phase 14 Phase C.

Covers the ``v_investment_contributions`` view shipped in migration v34.
The view classifies each positions_ledger row as one of:

    user_contribution       — share_delta > 0 AND a paired transfer-tagged
                              cash-side transaction exists on the same date
                              and account.
    intra_account_credit    — share_delta > 0 AND no such matching
                              transfer-tagged transaction (dividend
                              reinvestments, employer matches live here).
    sale_or_transfer_out    — share_delta < 0.
    unknown                 — catch-all (share_delta == 0, e.g. DIVIDEND
                              cash-only rows).

Test cases (per P14-T03 prompt Verification):

  1. test_view_user_contribution — positions_ledger BUY + paired
     transfer-tagged cash leg → 'user_contribution'.
  2. test_view_intra_account_credit — positions_ledger REINVESTMENT with
     no transfer-tagged counterparty → 'intra_account_credit'.
  3. test_view_sale_or_transfer_out — negative share_delta → 'sale_or_transfer_out'.
  4. test_view_zero_delta_is_unknown — share_delta=0 DIVIDEND row →
     'unknown' (view is share-delta-keyed; cash-only dividends handled
     elsewhere).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db


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
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


def _seed_account(conn: sqlite3.Connection, account_id: str, atype: str = "investment"):
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) "
        "VALUES (?, ?)",
        ("inst_test", "Test Brokerage"),
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, type, last4) "
        "VALUES (?, 'inst_test', ?, ?, '0000')",
        (account_id, account_id.upper(), atype),
    )


def _insert_ledger(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    ts: str,
    ticker: str,
    ttype: str,
    share_delta: float,
    new_total: float = 0.0,
):
    conn.execute(
        """
        INSERT INTO positions_ledger
        (account_id, timestamp, ticker, transaction_type,
         share_delta, new_total_shares)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (account_id, ts, ticker, ttype, share_delta, new_total),
    )


def _insert_txn(
    conn: sqlite3.Connection,
    *,
    txn_id: str,
    account_id: str,
    posting_date: str,
    amount: float,
    transfer_tag: str | None = None,
    category: str = "Transfers",
):
    direction = "Credit" if amount > 0 else "Debit"
    conn.execute(
        """
        INSERT INTO transactions
        (id, institution_id, account_id, amount, signed_amount, direction,
         posting_date, effective_month, category, status, transfer_tag)
        VALUES (?, 'inst_test', ?, ?, ?, ?, ?, ?, ?, 'posted', ?)
        """,
        (txn_id, account_id, abs(amount), amount, direction,
         posting_date, posting_date[:7], category, transfer_tag),
    )


# ── Tests ────────────────────────────────────────────────────────────────────


def test_view_user_contribution():
    print("\n─── P14-T03.1: view classifies paired buy as user_contribution ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_account(conn, "brokerage_a")
            # Paired transfer cash leg (transfer_tag is what distinguishes
            # a user-funded buy from a dividend reinvestment).
            _insert_txn(
                conn, txn_id="tx_xfer", account_id="brokerage_a",
                posting_date="2026-03-10", amount=-500.0,
                transfer_tag="invest:1",
            )
            _insert_ledger(
                conn, account_id="brokerage_a", ts="2026-03-10T09:00:00",
                ticker="VTI", ttype="BUY", share_delta=1.0, new_total=1.0,
            )
            conn.commit()

            row = conn.execute(
                "SELECT classification, matched_tx_id "
                "FROM v_investment_contributions WHERE account_id='brokerage_a'"
            ).fetchone()
            _check(
                "classification == 'user_contribution'",
                row["classification"] == "user_contribution",
                f"got {row['classification']!r}",
            )
            _check(
                "matched_tx_id == 'tx_xfer'",
                row["matched_tx_id"] == "tx_xfer",
                f"got {row['matched_tx_id']!r}",
            )
    finally:
        os.unlink(db)


def test_view_intra_account_credit():
    print("\n─── P14-T03.2: view classifies REINVESTMENT as intra_account_credit ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_account(conn, "brokerage_b")
            # A dividend cash transaction (no transfer_tag). Must NOT be
            # picked up by the view's left join on transfer_tag IS NOT NULL.
            _insert_txn(
                conn, txn_id="tx_div", account_id="brokerage_b",
                posting_date="2026-04-15", amount=3.50,
                transfer_tag=None, category="Investment Income",
            )
            _insert_ledger(
                conn, account_id="brokerage_b", ts="2026-04-15T08:05:00",
                ticker="SPG", ttype="REINVESTMENT",
                share_delta=0.03, new_total=0.03,
            )
            conn.commit()

            row = conn.execute(
                "SELECT classification, matched_tx_id "
                "FROM v_investment_contributions WHERE account_id='brokerage_b'"
            ).fetchone()
            _check(
                "classification == 'intra_account_credit'",
                row["classification"] == "intra_account_credit",
                f"got {row['classification']!r}",
            )
            _check(
                "matched_tx_id IS NULL (transfer_tag filter excludes div txn)",
                row["matched_tx_id"] is None,
                f"got {row['matched_tx_id']!r}",
            )
    finally:
        os.unlink(db)


def test_view_sale_or_transfer_out():
    print("\n─── P14-T03.3: negative share_delta classifies as sale_or_transfer_out ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_account(conn, "brokerage_c")
            _insert_ledger(
                conn, account_id="brokerage_c", ts="2026-05-20T11:00:00",
                ticker="AAPL", ttype="SELL", share_delta=-2.0, new_total=3.0,
            )
            conn.commit()

            row = conn.execute(
                "SELECT classification "
                "FROM v_investment_contributions WHERE account_id='brokerage_c'"
            ).fetchone()
            _check(
                "classification == 'sale_or_transfer_out'",
                row["classification"] == "sale_or_transfer_out",
                f"got {row['classification']!r}",
            )
    finally:
        os.unlink(db)


def test_view_zero_delta_is_unknown():
    print("\n─── P14-T03.4: share_delta=0 DIVIDEND row classifies as unknown ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_account(conn, "brokerage_d")
            _insert_ledger(
                conn, account_id="brokerage_d", ts="2026-06-18T08:00:00",
                ticker="MSFT", ttype="DIVIDEND",
                share_delta=0.0, new_total=5.0,
            )
            conn.commit()

            row = conn.execute(
                "SELECT classification "
                "FROM v_investment_contributions WHERE account_id='brokerage_d'"
            ).fetchone()
            _check(
                "classification == 'unknown' (cash-only dividend row)",
                row["classification"] == "unknown",
                f"got {row['classification']!r}",
            )
    finally:
        os.unlink(db)


# ── Main ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    test_view_user_contribution()
    test_view_intra_account_credit()
    test_view_sale_or_transfer_out()
    test_view_zero_delta_is_unknown()

    print(f"\n{'═' * 60}")
    print(f"  P14-T03 view tests: {_passed} passed, {_failed} failed")
    if _errors:
        print(f"  Failed: {', '.join(_errors)}")
    print(f"{'═' * 60}")
    sys.exit(1 if _failed else 0)
