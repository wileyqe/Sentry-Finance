"""
tests/test_dividend_interest_flows.py — Phase 14 Phase C unit tests.

Locks the Sankey contract for dividend and interest income, including the
reinvested-dividend two-leg flow (dividend income → account → STORED_ILLIQUID).

Test cases (per P14-T03 prompt Verification):

  1. test_dividend_without_reinvestment — dividend transaction with no
     same-day REINVESTMENT ledger row produces a single income-edge
     entry in ``income_categories``; reinvestment_flows is empty; the
     cash accumulates as residual STORED_LIQUID.
  2. test_dividend_with_reinvestment — dividend transaction paired with
     a same-day REINVESTMENT ledger row produces BOTH the income edge
     AND a reinvestment_flows entry; STORED_ILLIQUID bumps by the
     dividend amount; STORED_LIQUID residual unchanged.
  3. test_hysa_interest_renders_as_income — an "Interest" category
     transaction appears in income_categories identically to a dividend
     without reinvestment; no reinvestment leg.
  4. test_market_gain_produces_no_sankey_flow — an upward change in a
     portfolio_snapshots row with no cash transaction produces NO
     income-edge and no reinvestment_flows entry.
  5. test_market_loss_produces_no_sankey_flow — a downward change in
     a portfolio_snapshots row also produces NO Sankey flow (gains and
     losses are symmetric in their invisibility on the flow diagram).
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
from dal.owners import create_owner
from dal.reports import get_flow_data


_passed = 0
_failed = 0
_errors: list[str] = []


def _check(name: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f" -- {detail}"
        print(msg)
        _errors.append(name)


def _temp_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


def _seed_investment_account(
    conn: sqlite3.Connection,
    account_id: str,
    owner_id: str,
    *,
    atype: str = "investment",
):
    create_owner(conn, owner_id, owner_id.title())
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) "
        "VALUES (?, ?)",
        ("inst_test", "Test Brokerage"),
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, type, last4, owner_id) "
        "VALUES (?, 'inst_test', ?, ?, '0000', ?)",
        (account_id, account_id.upper(), atype, owner_id),
    )


def _seed_bank_account(
    conn: sqlite3.Connection,
    account_id: str,
    owner_id: str,
):
    create_owner(conn, owner_id, owner_id.title())
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) "
        "VALUES (?, ?)",
        ("bank_test", "Test Bank"),
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, type, last4, owner_id) "
        "VALUES (?, 'bank_test', ?, 'savings', '0001', ?)",
        (account_id, account_id.upper(), owner_id),
    )


def _insert_income_txn(
    conn: sqlite3.Connection,
    *,
    txn_id: str,
    account_id: str,
    posting_date: str,
    amount: float,
    description: str,
    category: str,
):
    """Insert a credit-direction income transaction (positive signed_amount)."""
    institution_id = conn.execute(
        "SELECT institution_id FROM accounts WHERE id = ?",
        (account_id,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO transactions
        (id, institution_id, account_id, amount, signed_amount, direction,
         posting_date, effective_month, description, merchant, category,
         status, transfer_tag)
        VALUES (?, ?, ?, ?, ?, 'Credit', ?, ?, ?, ?, ?, 'posted', NULL)
        """,
        (txn_id, institution_id, account_id, abs(amount), amount,
         posting_date, posting_date[:7], description,
         description.split()[0], category),
    )


def _insert_ledger(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    ts: str,
    ticker: str,
    ttype: str,
    share_delta: float,
    cost_basis: float | None = None,
):
    conn.execute(
        """
        INSERT INTO positions_ledger
        (account_id, timestamp, ticker, transaction_type,
         share_delta, new_total_shares, cost_basis_dec)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id, ts, ticker, ttype, share_delta, 0.0,
            str(cost_basis) if cost_basis is not None else None,
        ),
    )


# ── Tests ────────────────────────────────────────────────────────────────────


def test_dividend_without_reinvestment():
    print("\n--- P14-T03 flows.1: dividend without reinvestment ---")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_investment_account(conn, "brokerage_a", "quintin")
            _insert_income_txn(
                conn, txn_id="tx_div_aapl", account_id="brokerage_a",
                posting_date="2026-03-10", amount=12.50,
                description="AAPL DIVIDEND",
                category="Investment Income",
            )
            # Dividend ledger row (share_delta=0, intra-account cash-only).
            _insert_ledger(
                conn, account_id="brokerage_a",
                ts="2026-03-10T08:00:00", ticker="AAPL",
                ttype="DIVIDEND", share_delta=0.0, cost_basis=None,
            )
            conn.commit()

            data = get_flow_data(
                conn, start_date="2026-03-01", end_date="2026-03-31",
                owner_id="quintin",
            )
            cats = data["income_categories"]
            _check(
                "Investment Income category appears on income side",
                any(c["category"] == "Investment Income" for c in cats),
                f"got {[c['category'] for c in cats]}",
            )
            _check(
                "reinvestment_flows is empty",
                data["reinvestment_flows"] == [],
                f"got {data['reinvestment_flows']}",
            )
            _check(
                "STORED_ILLIQUID is $0.00 (no reinvestment)",
                data["bucket_totals"]["STORED_ILLIQUID"] == 0.0,
                f"got {data['bucket_totals']['STORED_ILLIQUID']}",
            )
            _check(
                "STORED_LIQUID picks up the $12.50 as residual",
                data["bucket_totals"]["STORED_LIQUID"] == 12.50,
                f"got {data['bucket_totals']['STORED_LIQUID']}",
            )
    finally:
        os.unlink(db)


def test_dividend_with_reinvestment():
    print("\n--- P14-T03 flows.2: dividend WITH reinvestment (two-leg) ---")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_investment_account(conn, "brokerage_b", "quintin")
            _insert_income_txn(
                conn, txn_id="tx_div_spg", account_id="brokerage_b",
                posting_date="2026-04-15", amount=7.65,
                description="SPG DIVIDEND",
                category="Investment Income",
            )
            # DIVIDEND cash marker + REINVESTMENT buy, same day,
            # cost_basis matches the dividend amount.
            _insert_ledger(
                conn, account_id="brokerage_b",
                ts="2026-04-15T08:00:00", ticker="SPG",
                ttype="DIVIDEND", share_delta=0.0, cost_basis=None,
            )
            _insert_ledger(
                conn, account_id="brokerage_b",
                ts="2026-04-15T08:05:00", ticker="SPG",
                ttype="REINVESTMENT", share_delta=0.05, cost_basis=7.65,
            )
            conn.commit()

            data = get_flow_data(
                conn, start_date="2026-04-01", end_date="2026-04-30",
                owner_id="quintin",
            )
            cats = data["income_categories"]
            _check(
                "Investment Income category still appears (leg 1)",
                any(c["category"] == "Investment Income" for c in cats),
                f"got {[c['category'] for c in cats]}",
            )
            rfs = data["reinvestment_flows"]
            _check(
                "reinvestment_flows has exactly 1 entry",
                len(rfs) == 1,
                f"got {rfs}",
            )
            if rfs:
                rf = rfs[0]
                _check(
                    "reinvestment entry ticker == 'SPG'",
                    rf["ticker"] == "SPG",
                    f"got {rf['ticker']!r}",
                )
                _check(
                    "reinvestment amount_cents == 765",
                    rf["amount_cents"] == 765,
                    f"got {rf['amount_cents']}",
                )
                _check(
                    "reinvestment bucket == STORED_ILLIQUID",
                    rf["bucket"] == "STORED_ILLIQUID",
                    f"got {rf['bucket']!r}",
                )
            _check(
                "STORED_ILLIQUID bumped by $7.65 (reinvested amount)",
                data["bucket_totals"]["STORED_ILLIQUID"] == 7.65,
                f"got {data['bucket_totals']['STORED_ILLIQUID']}",
            )
            _check(
                "STORED_LIQUID residual is $0.00 (cash was reinvested)",
                abs(data["bucket_totals"]["STORED_LIQUID"]) < 0.01,
                f"got {data['bucket_totals']['STORED_LIQUID']}",
            )
            _check(
                "bucket_invariant_drift_cents == 0",
                data["bucket_invariant_drift_cents"] == 0,
                f"got {data['bucket_invariant_drift_cents']}",
            )
    finally:
        os.unlink(db)


def test_hysa_interest_renders_as_income():
    print("\n--- P14-T03 flows.3: HYSA interest renders as income edge ---")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_bank_account(conn, "hysa_q", "quintin")
            _insert_income_txn(
                conn, txn_id="tx_interest", account_id="hysa_q",
                posting_date="2026-05-31", amount=45.00,
                description="HYSA INTEREST", category="Interest",
            )
            conn.commit()

            data = get_flow_data(
                conn, start_date="2026-05-01", end_date="2026-05-31",
                owner_id="quintin",
            )
            cats = data["income_categories"]
            _check(
                "Interest category appears on income side",
                any(c["category"] == "Interest" for c in cats),
                f"got {[c['category'] for c in cats]}",
            )
            _check(
                "reinvestment_flows is empty (interest never reinvests)",
                data["reinvestment_flows"] == [],
                f"got {data['reinvestment_flows']}",
            )
            _check(
                "STORED_ILLIQUID is $0",
                data["bucket_totals"]["STORED_ILLIQUID"] == 0.0,
            )
            _check(
                "STORED_LIQUID = $45 residual",
                data["bucket_totals"]["STORED_LIQUID"] == 45.00,
                f"got {data['bucket_totals']['STORED_LIQUID']}",
            )
    finally:
        os.unlink(db)


def test_market_gain_produces_no_sankey_flow():
    print("\n--- P14-T03 flows.4: market gain (no cash leg) is invisible ---")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_investment_account(conn, "brokerage_gain", "quintin")
            # Two portfolio snapshots showing a pure market appreciation
            # — no transactions, no ledger rows, no cash movement.
            conn.execute(
                "INSERT INTO portfolio_snapshots "
                "(account_id, timestamp, total_account_value, cash_balance) "
                "VALUES ('brokerage_gain', '2026-06-01T16:00:00', 10000.0, 0.0)"
            )
            conn.execute(
                "INSERT INTO portfolio_snapshots "
                "(account_id, timestamp, total_account_value, cash_balance) "
                "VALUES ('brokerage_gain', '2026-06-30T16:00:00', 10800.0, 0.0)"
            )
            conn.commit()

            data = get_flow_data(
                conn, start_date="2026-06-01", end_date="2026-06-30",
                owner_id="quintin",
            )
            _check(
                "total_income is $0 (no cash leg)",
                data["total_income"] == 0.0,
                f"got {data['total_income']}",
            )
            _check(
                "income_categories is empty",
                data["income_categories"] == [],
                f"got {data['income_categories']}",
            )
            _check(
                "reinvestment_flows is empty",
                data["reinvestment_flows"] == [],
            )
            _check(
                "bucket_totals sum == $0 (market moves invisible to Sankey)",
                sum(data["bucket_totals"].values()) == 0.0,
                f"got {data['bucket_totals']}",
            )
    finally:
        os.unlink(db)


def test_market_loss_produces_no_sankey_flow():
    print("\n--- P14-T03 flows.5: market loss (no cash leg) is invisible ---")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_investment_account(conn, "brokerage_loss", "quintin")
            conn.execute(
                "INSERT INTO portfolio_snapshots "
                "(account_id, timestamp, total_account_value, cash_balance) "
                "VALUES ('brokerage_loss', '2026-07-01T16:00:00', 10000.0, 0.0)"
            )
            conn.execute(
                "INSERT INTO portfolio_snapshots "
                "(account_id, timestamp, total_account_value, cash_balance) "
                "VALUES ('brokerage_loss', '2026-07-31T16:00:00', 8200.0, 0.0)"
            )
            conn.commit()

            data = get_flow_data(
                conn, start_date="2026-07-01", end_date="2026-07-31",
                owner_id="quintin",
            )
            _check(
                "total_income is $0 even on a loss month",
                data["total_income"] == 0.0,
                f"got {data['total_income']}",
            )
            _check(
                "bucket_totals sum == $0 (no negative flows drawn)",
                sum(data["bucket_totals"].values()) == 0.0,
                f"got {data['bucket_totals']}",
            )
    finally:
        os.unlink(db)


# ── Main ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    test_dividend_without_reinvestment()
    test_dividend_with_reinvestment()
    test_hysa_interest_renders_as_income()
    test_market_gain_produces_no_sankey_flow()
    test_market_loss_produces_no_sankey_flow()

    print(f"\n{'=' * 60}")
    print(f"  P14-T03 dividend/interest flow tests: "
          f"{_passed} passed, {_failed} failed")
    if _errors:
        print(f"  Failed: {', '.join(_errors)}")
    print(f"{'=' * 60}")
    sys.exit(1 if _failed else 0)
