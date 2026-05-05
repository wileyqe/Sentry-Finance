"""
tests/test_fidelity_dividend_income.py — P17-T29 Fidelity dividend income writer tests.

Covers:
  - DIVIDEND RECEIVED and SHORT/LONG-TERM CAP GAIN rows become posted
    positive Investment Income transactions.
  - Ticker-first descriptions, source action in raw_description, and
    deterministic institution_txn_id.
  - Rerun idempotency.
  - Missing Run Date / non-positive amount rows write nothing.
  - SPAXX/FDRXX dividend income stays cash-equivalent / liquid.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.fidelity_dividend_income import write_fidelity_dividend_income
from dal.owners import create_owner


def _temp_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


def _seed_fidelity_account(conn: sqlite3.Connection, account_id: str, owner_id: str):
    create_owner(conn, owner_id, owner_id.title())
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) "
        "VALUES ('fidelity', 'Fidelity')"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, type, last4, owner_id) "
        "VALUES (?, 'fidelity', 'Fidelity Brokerage', 'investment', '0000', ?)",
        (account_id, owner_id),
    )


def _make_history_df(rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame matching the parsed Fidelity history shape."""
    defaults = {
        "Symbol": "",
        "Description": "",
        "Type": "Cash",
        "Price ($)": None,
        "Quantity": 0.0,
        "Commission ($)": None,
        "Fees ($)": None,
        "Accrued Interest ($)": None,
        "Cash Balance ($)": 0.0,
        "Settlement Date": None,
        "Action_Type": "DIVIDEND",
    }
    full_rows = []
    for r in rows:
        row = {**defaults, **r}
        full_rows.append(row)
    df = pd.DataFrame(full_rows)
    if "Run Date" in df.columns:
        df["Run Date"] = pd.to_datetime(df["Run Date"], format="%m/%d/%Y", errors="coerce")
    return df


# ── Test: DIVIDEND RECEIVED becomes Investment Income ──────────────────────


def test_dividend_received_creates_investment_income():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_fidelity_account(conn, "fid_brok", "quintin")
            history = _make_history_df([
                {
                    "Run Date": "03/31/2025",
                    "Action": 'DIVIDEND RECEIVED DUMMY INDEX ETF (VOO) (Cash)',
                    "Symbol": "VOO",
                    "Amount ($)": 3.50,
                    "Action_Type": "DIVIDEND",
                },
            ])
            result = write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()

            assert result["written"] == 1
            assert result["skipped_missing_date"] == 0
            assert result["skipped_non_positive_amount"] == 0

            txn = conn.execute(
                "SELECT * FROM transactions WHERE category = 'Investment Income'"
            ).fetchone()
            assert txn is not None
            assert txn["signed_amount"] == 3.50
            assert txn["direction"] == "Credit"
            assert txn["amount"] == 3.50
            assert txn["posting_date"] == "2025-03-31"
            assert txn["transaction_date"] == "2025-03-31"
            assert txn["description"] == "VOO DIVIDEND"
            assert "DIVIDEND RECEIVED" in txn["raw_description"]
            assert txn["institution_id"] == "fidelity"
            assert txn["status"] == "posted"
            # No transfer_tag
            assert txn["transfer_tag"] is None
    finally:
        os.unlink(db)


# ── Test: SHORT-TERM CAP GAIN ─────────────────────────────────────────────


def test_short_term_cap_gain_creates_investment_income():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_fidelity_account(conn, "fid_brok", "quintin")
            history = _make_history_df([
                {
                    "Run Date": "12/19/2025",
                    "Action": 'SHORT-TERM CAP GAIN DISTRIBUTION DUMMY FUND (QQQM) (Cash)',
                    "Symbol": "QQQM",
                    "Amount ($)": 1.75,
                    "Action_Type": "DIVIDEND",
                },
            ])
            result = write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()

            assert result["written"] == 1
            txn = conn.execute(
                "SELECT * FROM transactions WHERE category = 'Investment Income'"
            ).fetchone()
            assert txn is not None
            assert txn["description"] == "QQQM SHORT-TERM CAP GAIN"
            assert txn["signed_amount"] == 1.75
            assert "SHORT-TERM CAP GAIN" in txn["raw_description"]
    finally:
        os.unlink(db)


# ── Test: LONG-TERM CAP GAIN ──────────────────────────────────────────────


def test_long_term_cap_gain_creates_investment_income():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_fidelity_account(conn, "fid_brok", "quintin")
            history = _make_history_df([
                {
                    "Run Date": "12/20/2025",
                    "Action": 'LONG-TERM CAP GAIN DISTRIBUTION DUMMY ETF (VOO) (Cash)',
                    "Symbol": "VOO",
                    "Amount ($)": 5.25,
                    "Action_Type": "DIVIDEND",
                },
            ])
            result = write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()

            assert result["written"] == 1
            txn = conn.execute(
                "SELECT * FROM transactions WHERE category = 'Investment Income'"
            ).fetchone()
            assert txn is not None
            assert txn["description"] == "VOO LONG-TERM CAP GAIN"
    finally:
        os.unlink(db)


# ── Test: Idempotent reruns ────────────────────────────────────────────────


def test_rerun_is_idempotent():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_fidelity_account(conn, "fid_brok", "quintin")
            history = _make_history_df([
                {
                    "Run Date": "03/31/2025",
                    "Action": 'DIVIDEND RECEIVED DUMMY INDEX ETF (VOO) (Cash)',
                    "Symbol": "VOO",
                    "Amount ($)": 3.50,
                    "Action_Type": "DIVIDEND",
                },
            ])
            r1 = write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()
            assert r1["written"] == 1

            r2 = write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()
            assert r2["written"] == 0
            assert r2["unchanged"] == 1

            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM transactions WHERE category = 'Investment Income'"
            ).fetchone()["cnt"]
            assert count == 1, f"Expected 1 transaction after rerun, got {count}"
    finally:
        os.unlink(db)


# ── Test: Missing Run Date skips ───────────────────────────────────────────


def test_missing_run_date_skips():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_fidelity_account(conn, "fid_brok", "quintin")
            history = _make_history_df([
                {
                    "Run Date": None,
                    "Action": 'DIVIDEND RECEIVED DUMMY INDEX ETF (VOO) (Cash)',
                    "Symbol": "VOO",
                    "Amount ($)": 3.50,
                    "Action_Type": "DIVIDEND",
                },
            ])
            # Fix: when Run Date is None, pd.to_datetime will fail
            history["Run Date"] = pd.NaT
            result = write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()

            assert result["written"] == 0
            assert result["skipped_missing_date"] == 1
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM transactions WHERE category = 'Investment Income'"
            ).fetchone()["cnt"]
            assert count == 0
    finally:
        os.unlink(db)


# ── Test: Non-positive amount skips ────────────────────────────────────────


def test_non_positive_amount_skips():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_fidelity_account(conn, "fid_brok", "quintin")
            history = _make_history_df([
                {
                    "Run Date": "03/31/2025",
                    "Action": 'DIVIDEND RECEIVED DUMMY INDEX ETF (VOO) (Cash)',
                    "Symbol": "VOO",
                    "Amount ($)": 0.0,
                    "Action_Type": "DIVIDEND",
                },
                {
                    "Run Date": "03/31/2025",
                    "Action": 'DIVIDEND RECEIVED DUMMY INDEX ETF (VOO) (Cash)',
                    "Symbol": "VOO",
                    "Amount ($)": -1.00,
                    "Action_Type": "DIVIDEND",
                },
            ])
            result = write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()

            assert result["written"] == 0
            assert result["skipped_non_positive_amount"] == 2
    finally:
        os.unlink(db)


# ── Test: SPAXX dividend is cash-equivalent income ────────────────────────


def test_spaxx_dividend_is_cash_equivalent_income():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_fidelity_account(conn, "fid_brok", "quintin")
            history = _make_history_df([
                {
                    "Run Date": "06/30/2025",
                    "Action": 'DIVIDEND RECEIVED FIDELITY GOVERNMENT MONEY MARKET (SPAXX) (Cash)',
                    "Symbol": "SPAXX",
                    "Amount ($)": 3.00,
                    "Action_Type": "DIVIDEND",
                },
            ])
            result = write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()

            assert result["written"] == 1
            txn = conn.execute(
                "SELECT * FROM transactions WHERE category = 'Investment Income'"
            ).fetchone()
            assert txn is not None
            assert txn["description"] == "SPAXX DIVIDEND"
            assert txn["signed_amount"] == 3.00
            assert txn["transfer_tag"] is None
    finally:
        os.unlink(db)


# ── Test: Non-dividend rows are ignored ────────────────────────────────────


def test_non_dividend_rows_ignored():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_fidelity_account(conn, "fid_brok", "quintin")
            history = _make_history_df([
                {
                    "Run Date": "01/06/2025",
                    "Action": 'YOU BOUGHT DUMMY INDEX ETF (VOO) (Cash)',
                    "Symbol": "VOO",
                    "Amount ($)": 94.38,
                    "Action_Type": "BOUGHT",
                },
                {
                    "Run Date": "01/03/2025",
                    "Action": 'Electronic Funds Transfer Received (Cash)',
                    "Symbol": "",
                    "Amount ($)": 100.00,
                    "Action_Type": "DEPOSIT",
                },
            ])
            result = write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()

            assert result["written"] == 0
            assert result["unchanged"] == 0
    finally:
        os.unlink(db)


# ── Test: Multiple dividends on same day with different tickers ────────────


def test_multiple_same_day_dividends():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_fidelity_account(conn, "fid_brok", "quintin")
            history = _make_history_df([
                {
                    "Run Date": "03/31/2025",
                    "Action": 'DIVIDEND RECEIVED DUMMY INDEX ETF (VOO) (Cash)',
                    "Symbol": "VOO",
                    "Amount ($)": 3.50,
                    "Action_Type": "DIVIDEND",
                },
                {
                    "Run Date": "03/31/2025",
                    "Action": 'DIVIDEND RECEIVED DUMMY NASDAQ ETF (QQQM) (Cash)',
                    "Symbol": "QQQM",
                    "Amount ($)": 2.00,
                    "Action_Type": "DIVIDEND",
                },
            ])
            result = write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()

            assert result["written"] == 2
            txns = conn.execute(
                "SELECT description FROM transactions "
                "WHERE category = 'Investment Income' ORDER BY description"
            ).fetchall()
            descs = [t["description"] for t in txns]
            assert "QQQM DIVIDEND" in descs
            assert "VOO DIVIDEND" in descs
    finally:
        os.unlink(db)


# ── Test: Deterministic institution_txn_id shape ──────────────────────────


def test_institution_txn_id_is_deterministic():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_fidelity_account(conn, "fid_brok", "quintin")
            history = _make_history_df([
                {
                    "Run Date": "03/31/2025",
                    "Action": 'DIVIDEND RECEIVED DUMMY INDEX ETF (VOO) (Cash)',
                    "Symbol": "VOO",
                    "Amount ($)": 3.50,
                    "Action_Type": "DIVIDEND",
                },
            ])
            write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()

            txn = conn.execute(
                "SELECT id FROM transactions WHERE category = 'Investment Income'"
            ).fetchone()
            # The ID is computed from institution_txn_id by compute_txn_id
            # which uses "fidelity:{institution_txn_id}" format
            assert txn["id"].startswith("fidelity:fidelity-income:")
    finally:
        os.unlink(db)


# ── Test: SPAXX dividend with flow test (no illiquid reinvestment) ────────


def test_spaxx_dividend_stays_liquid_in_flow():
    """SPAXX dividend income should not create an illiquid reinvestment flow."""
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_fidelity_account(conn, "fid_brok", "quintin")
            history = _make_history_df([
                {
                    "Run Date": "06/30/2025",
                    "Action": 'DIVIDEND RECEIVED FIDELITY GOVERNMENT MONEY MARKET (SPAXX) (Cash)',
                    "Symbol": "SPAXX",
                    "Amount ($)": 3.00,
                    "Action_Type": "DIVIDEND",
                },
            ])
            write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=history,
            )
            conn.commit()

            from dal.reports import get_flow_data
            data = get_flow_data(
                conn, start_date="2025-06-01", end_date="2025-06-30",
                owner_id="quintin",
            )
            cats = data["income_categories"]
            assert any(c["category"] == "Investment Income" for c in cats), \
                f"Investment Income not in income_categories: {cats}"
            # No illiquid reinvestment flow for SPAXX
            assert data["reinvestment_flows"] == [], \
                f"SPAXX should not create reinvestment flows: {data['reinvestment_flows']}"
            assert data["bucket_totals"]["STORED_ILLIQUID"] == 0.0, \
                f"SPAXX dividend should not be STORED_ILLIQUID: {data['bucket_totals']}"
    finally:
        os.unlink(db)


# ── Main (for standalone execution) ───────────────────────────────────────


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
