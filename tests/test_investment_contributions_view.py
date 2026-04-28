"""
tests/test_investment_contributions_view.py — Phase 14 Phase C
                                              (v43 — bank_txn_id rewrite).

Covers the ``v_investment_contributions`` view shipped in migration v34
and rewritten in v43 (AI-020 / AI-021 closeout). The view classifies
each positions_ledger row as one of:

    user_contribution       — share_delta > 0 AND positions_ledger.bank_txn_id
                              points to a real transactions row (the bank-side
                              cash leg that funded this lot).
    intra_account_credit    — share_delta > 0 AND bank_txn_id IS NULL
                              (dividend reinvestments, employer matches, AND
                              downstream Acorns ETF allocation rows that share
                              a cash leg with the primary ledger row).
    sale_or_transfer_out    — share_delta < 0.
    unknown                 — catch-all (share_delta == 0, e.g. DIVIDEND
                              cash-only rows).

The v34 view joined on ``(account_id, date, transfer_tag IS NOT NULL)`` —
a workaround that broke for every Shape-B money flow into an investment
account because the cash leg sits on a checking account while the ledger
rows sit on the brokerage account. v43 joins on
``transactions.id = positions_ledger.bank_txn_id`` directly, which is
the canonical link the post-commit linker
(``backend/result_writer.py:_link_acorns_bank_debits``) and AI-010's
seeder pass already populate.

Test cases:

  1. test_view_user_contribution — positions_ledger BUY with bank_txn_id
     pointing to a paired transactions row → 'user_contribution'.
  2. test_view_intra_account_credit — positions_ledger REINVESTMENT with
     bank_txn_id NULL → 'intra_account_credit'.
  3. test_view_sale_or_transfer_out — negative share_delta → 'sale_or_transfer_out'.
  4. test_view_zero_delta_is_unknown — share_delta=0 DIVIDEND row →
     'unknown' (view is share-delta-keyed; cash-only dividends handled
     elsewhere).
  5. test_view_acorns_multi_ledger_per_debit — one $350 cash leg + four
     IMPLIED_BUY ledger rows (one per ETF) → exactly ONE
     'user_contribution' (the row with bank_txn_id) and three
     'intra_account_credit' (the downstream allocation rows).
     Regression guard for the cardinality bug the v34 view's date+account
     join would have produced (4× overcount on Acorns contributions).
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
    # Per-account last4 keeps the (institution_id, last4) unique
    # constraint happy when a single test seeds multiple accounts
    # under inst_test.
    last4 = f"{abs(hash(account_id)) % 10000:04d}"
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, type, last4) "
        "VALUES (?, 'inst_test', ?, ?, ?)",
        (account_id, account_id.upper(), atype, last4),
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
    bank_txn_id: str | None = None,
):
    conn.execute(
        """
        INSERT INTO positions_ledger
        (account_id, timestamp, ticker, transaction_type,
         share_delta, new_total_shares, bank_txn_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (account_id, ts, ticker, ttype, share_delta, new_total, bank_txn_id),
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
            _seed_account(conn, "summit_chk", atype="checking")
            _seed_account(conn, "brokerage_a")
            # Bank-side cash leg sits on the checking account (Shape B).
            _insert_txn(
                conn, txn_id="tx_xfer", account_id="summit_chk",
                posting_date="2026-03-10", amount=-500.0,
                transfer_tag="invest:1",
            )
            # Brokerage-side ledger row points back via bank_txn_id —
            # the canonical link the post-commit linker establishes.
            _insert_ledger(
                conn, account_id="brokerage_a", ts="2026-03-10T09:00:00",
                ticker="VTI", ttype="BUY", share_delta=1.0, new_total=1.0,
                bank_txn_id="tx_xfer",
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
            # A dividend cash transaction (no transfer_tag, no
            # bank_txn_id linkage to the REINVESTMENT ledger row).
            # The reinvestment is intra-account by definition — no
            # outside cash funded it.
            _insert_txn(
                conn, txn_id="tx_div", account_id="brokerage_b",
                posting_date="2026-04-15", amount=3.50,
                transfer_tag=None, category="Investment Income",
            )
            _insert_ledger(
                conn, account_id="brokerage_b", ts="2026-04-15T08:05:00",
                ticker="SPG", ttype="REINVESTMENT",
                share_delta=0.03, new_total=0.03,
                bank_txn_id=None,
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
                "matched_tx_id IS NULL (no bank_txn_id linkage)",
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


def test_view_acorns_multi_ledger_per_debit():
    """Regression guard for the cardinality wrinkle the v34 view's
    date+account join would have produced.

    One $350 Acorns cash leg fans out into 4 IMPLIED_BUY ledger rows
    (one per ETF: VOO, IJH, IJR, IXUS). The post-commit linker sets
    ``bank_txn_id`` on exactly ONE primary ledger row per cash leg
    (the first one in id order); the other three carry NULL. The new
    view therefore classifies exactly ONE row as ``user_contribution``
    and the other THREE as ``intra_account_credit`` — semantically
    truthful (the three are downstream allocation, not new user
    money). ``SUM(ABS(matched_tx_signed_amount))`` over the
    user_contribution slice returns $350, not 4 × $350 = $1400 (which
    is what the v34 view's date+account join would have produced).
    """
    print("\n─── v43 regression: Acorns 4-ETF cardinality ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_account(conn, "summit_chk", atype="checking")
            _seed_account(conn, "acorns_synthetic")
            # One bank-side cash leg.
            _insert_txn(
                conn, txn_id="tx_acorns_350", account_id="summit_chk",
                posting_date="2026-03-04", amount=-350.0,
                transfer_tag="invest:1",
            )
            # Four IMPLIED_BUY rows on the Acorns brokerage account —
            # the per-ETF allocation. Only the FIRST has bank_txn_id
            # set (mirrors what `_link_acorns_bank_debits` does today).
            tickers = [
                ("VOO", "tx_acorns_350"),
                ("IJH", None),
                ("IJR", None),
                ("IXUS", None),
            ]
            for i, (ticker, btx) in enumerate(tickers):
                _insert_ledger(
                    conn, account_id="acorns_synthetic",
                    ts=f"2026-03-04T12:00:0{i}",
                    ticker=ticker, ttype="IMPLIED_BUY",
                    share_delta=1.0, new_total=1.0,
                    bank_txn_id=btx,
                )
            conn.commit()

            rows = conn.execute(
                "SELECT classification, matched_tx_id, ticker "
                "FROM v_investment_contributions "
                "WHERE account_id='acorns_synthetic' "
                "ORDER BY timestamp"
            ).fetchall()

            user_contrib_rows = [r for r in rows if r["classification"] == "user_contribution"]
            intra_rows = [r for r in rows if r["classification"] == "intra_account_credit"]

            _check(
                "exactly 1 user_contribution row",
                len(user_contrib_rows) == 1,
                f"got {len(user_contrib_rows)}",
            )
            _check(
                "exactly 3 intra_account_credit rows (downstream allocation)",
                len(intra_rows) == 3,
                f"got {len(intra_rows)}",
            )
            _check(
                "user_contribution row's ticker is the bank_txn_id-linked one (VOO)",
                len(user_contrib_rows) == 1
                    and user_contrib_rows[0]["ticker"] == "VOO",
                f"got {user_contrib_rows[0]['ticker'] if user_contrib_rows else 'none'!r}",
            )

            # The accountability scorecard's user-contribution sum.
            total = conn.execute(
                "SELECT SUM(ABS(matched_tx_signed_amount)) AS s "
                "FROM v_investment_contributions "
                "WHERE classification='user_contribution' "
                "  AND account_id='acorns_synthetic'"
            ).fetchone()["s"]
            _check(
                "user_contribution sum == $350 (not 4× = $1400)",
                total == 350.0,
                f"got {total!r}",
            )
    finally:
        os.unlink(db)


# ── Main ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    test_view_user_contribution()
    test_view_intra_account_credit()
    test_view_sale_or_transfer_out()
    test_view_zero_delta_is_unknown()
    test_view_acorns_multi_ledger_per_debit()

    print(f"\n{'═' * 60}")
    print(f"  P14-T03 view tests: {_passed} passed, {_failed} failed")
    if _errors:
        print(f"  Failed: {', '.join(_errors)}")
    print(f"{'═' * 60}")
    sys.exit(1 if _failed else 0)
