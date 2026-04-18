"""
tests/test_dal_investments_writes.py — Unit tests for
``dal/investments_writes.py``.

Covers happy paths, every invariant failure mode, the UNIQUE-index
upsert behavior on ``investment_holdings``, and the cash-vs-total
portfolio_snapshot invariant.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db  # noqa: E402
from dal.investments_writes import (  # noqa: E402
    record_investment_holdings,
    record_portfolio_snapshots,
    record_portfolio_snapshot,
)


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    p = Path(path)
    init_db(p)
    with get_db(p) as conn:
        conn.execute("INSERT INTO institutions (id, display_name) VALUES ('fid','Fidelity')")
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type) "
            "VALUES ('fid_1234','fid','Fidelity','1234','investment')"
        )
        conn.commit()
    yield p
    try:
        os.unlink(path)
    except OSError:
        pass


# ── investment_holdings ─────────────────────────────────────────────────────


def test_holdings_happy_path(db):
    with get_db(db) as conn:
        result = record_investment_holdings(
            conn,
            [
                {"account_id": "fid_1234", "date": "2026-01-15", "ticker": "AAPL",
                 "shares": 10.0, "close_price": 150.0, "market_value": 1500.0,
                 "cost_basis": 1200.0},
                {"account_id": "fid_1234", "date": "2026-01-15", "ticker": "MSFT",
                 "shares": 5.0, "close_price": 400.0, "market_value": 2000.0},
            ],
        )
        conn.commit()
        rows = conn.execute(
            "SELECT account_id, date, ticker, shares, close_price, market_value, cost_basis "
            "FROM investment_holdings ORDER BY ticker"
        ).fetchall()
    assert result == {"inserted_or_replaced": 2}
    assert [dict(r) for r in rows] == [
        {"account_id": "fid_1234", "date": "2026-01-15", "ticker": "AAPL",
         "shares": 10.0, "close_price": 150.0, "market_value": 1500.0, "cost_basis": 1200.0},
        {"account_id": "fid_1234", "date": "2026-01-15", "ticker": "MSFT",
         "shares": 5.0, "close_price": 400.0, "market_value": 2000.0, "cost_basis": None},
    ]


def test_holdings_insert_or_replace_on_unique_key(db):
    with get_db(db) as conn:
        record_investment_holdings(
            conn,
            [{"account_id": "fid_1234", "date": "2026-01-15", "ticker": "AAPL",
              "shares": 10.0, "close_price": 150.0, "market_value": 1500.0}],
        )
        conn.commit()
        # Re-insert with same (account_id, date, ticker) should replace.
        record_investment_holdings(
            conn,
            [{"account_id": "fid_1234", "date": "2026-01-15", "ticker": "AAPL",
              "shares": 12.0, "close_price": 150.0, "market_value": 1800.0}],
        )
        conn.commit()
        rows = conn.execute(
            "SELECT shares, market_value FROM investment_holdings "
            "WHERE account_id='fid_1234' AND date='2026-01-15' AND ticker='AAPL'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["shares"] == 12.0
    assert rows[0]["market_value"] == 1800.0


def test_holdings_empty_list_noop(db):
    with get_db(db) as conn:
        result = record_investment_holdings(conn, [])
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM investment_holdings").fetchone()[0]
    assert result == {"inserted_or_replaced": 0}
    assert count == 0


def test_holdings_invariant_missing_key(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="missing required key"):
            record_investment_holdings(
                conn,
                [{"account_id": "fid_1234", "date": "2026-01-15", "ticker": "AAPL"}],
            )


def test_holdings_invariant_negative_shares(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="shares must be >= 0"):
            record_investment_holdings(
                conn,
                [{"account_id": "fid_1234", "date": "2026-01-15", "ticker": "AAPL",
                  "shares": -1.0}],
            )


def test_holdings_invariant_negative_price(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="close_price must be >= 0"):
            record_investment_holdings(
                conn,
                [{"account_id": "fid_1234", "date": "2026-01-15", "ticker": "AAPL",
                  "shares": 10.0, "close_price": -5.0}],
            )


def test_holdings_invariant_market_value_drift(db):
    with get_db(db) as conn:
        # 10 * 150 = 1500, storing 2000 is clearly wrong (way outside 0.1% tolerance)
        with pytest.raises(ValueError, match="disagrees with shares\\*close_price"):
            record_investment_holdings(
                conn,
                [{"account_id": "fid_1234", "date": "2026-01-15", "ticker": "AAPL",
                  "shares": 10.0, "close_price": 150.0, "market_value": 2000.0}],
            )


def test_holdings_invariant_tolerates_rounding(db):
    with get_db(db) as conn:
        # Common generator pattern: shares=0.347, price=88.46 → 30.6944..., stored 30.69
        record_investment_holdings(
            conn,
            [{"account_id": "fid_1234", "date": "2026-01-15", "ticker": "VTI",
              "shares": 0.347, "close_price": 88.46, "market_value": 30.69}],
        )
        conn.commit()


def test_holdings_invariant_tolerates_none_optional_fields(db):
    """TSP holdings have no cost_basis; pure shares+price should validate."""
    with get_db(db) as conn:
        record_investment_holdings(
            conn,
            [{"account_id": "fid_1234", "date": "2026-01-15", "ticker": "TSP_C",
              "shares": 800.0, "close_price": 72.50, "market_value": 58000.0,
              "cost_basis": None}],
        )
        conn.commit()


# ── portfolio_snapshots ────────────────────────────────────────────────────


def test_snapshots_happy_path(db):
    with get_db(db) as conn:
        result = record_portfolio_snapshots(
            conn,
            [
                {"account_id": "fid_1234", "timestamp": "2026-01-15T16:00:00",
                 "total_account_value": 10000.0, "cash_balance": 500.0},
                {"account_id": "fid_1234", "timestamp": "2026-01-22T16:00:00",
                 "total_account_value": 10500.0},  # no cash_balance → 0.0
            ],
        )
        conn.commit()
        rows = conn.execute(
            "SELECT timestamp, total_account_value, cash_balance "
            "FROM portfolio_snapshots ORDER BY timestamp"
        ).fetchall()
    assert result == {"inserted": 2}
    assert [dict(r) for r in rows] == [
        {"timestamp": "2026-01-15T16:00:00", "total_account_value": 10000.0,
         "cash_balance": 500.0},
        {"timestamp": "2026-01-22T16:00:00", "total_account_value": 10500.0,
         "cash_balance": 0.0},
    ]


def test_snapshots_empty_list_noop(db):
    with get_db(db) as conn:
        result = record_portfolio_snapshots(conn, [])
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]
    assert result == {"inserted": 0}
    assert count == 0


def test_snapshots_invariant_negative_total(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="total_account_value must be >= 0"):
            record_portfolio_snapshots(
                conn,
                [{"account_id": "fid_1234", "timestamp": "2026-01-15T16:00:00",
                  "total_account_value": -1.0}],
            )


def test_snapshots_invariant_negative_cash(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="cash_balance must be >= 0"):
            record_portfolio_snapshots(
                conn,
                [{"account_id": "fid_1234", "timestamp": "2026-01-15T16:00:00",
                  "total_account_value": 1000.0, "cash_balance": -5.0}],
            )


def test_snapshots_invariant_cash_exceeds_total(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="exceeds total_account_value"):
            record_portfolio_snapshots(
                conn,
                [{"account_id": "fid_1234", "timestamp": "2026-01-15T16:00:00",
                  "total_account_value": 500.0, "cash_balance": 1000.0}],
            )


def test_snapshots_allows_all_cash(db):
    """When total == cash (e.g. idle account), the invariant allows equality."""
    with get_db(db) as conn:
        record_portfolio_snapshots(
            conn,
            [{"account_id": "fid_1234", "timestamp": "2026-01-15T16:00:00",
              "total_account_value": 500.0, "cash_balance": 500.0}],
        )
        conn.commit()


def test_single_row_convenience_wrapper(db):
    with get_db(db) as conn:
        record_portfolio_snapshot(conn, "fid_1234", "2026-01-15T16:00:00", 1234.5)
        conn.commit()
        row = conn.execute(
            "SELECT total_account_value, cash_balance FROM portfolio_snapshots"
        ).fetchone()
    assert dict(row) == {"total_account_value": 1234.5, "cash_balance": 0.0}


def test_failure_before_any_write(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError):
            record_portfolio_snapshots(
                conn,
                [
                    {"account_id": "fid_1234", "timestamp": "2026-01-15T16:00:00",
                     "total_account_value": 1000.0},
                    {"account_id": "fid_1234", "timestamp": "2026-01-22T16:00:00",
                     "total_account_value": -5.0},
                ],
            )
        count = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]
    assert count == 0
