"""
tests/test_t05.py — Verify P1-T05: time-aware real estate in get_net_worth_history()

Tests that each historical month uses the most recent real estate valuation
known at that point in time, not a static latest value.

Date notes: today = 2026-03-29. months=15 covers 2025-01 → 2026-03.
Test data is anchored in 2025 to stay within that window.
"""
import sqlite3
import pytest
from dal.reports import get_net_worth_history


@pytest.fixture
def conn():
    """In-memory DB with accounts, balance_snapshots, portfolio_snapshots, real_estate."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY,
            type TEXT,
            is_active INTEGER DEFAULT 1,
            institution_id TEXT
        );
        CREATE TABLE balance_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT,
            as_of TEXT,
            balance REAL
        );
        CREATE TABLE portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT,
            timestamp TEXT,
            total_account_value REAL,
            cash_balance REAL
        );
        CREATE TABLE real_estate (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            estimated_value REAL NOT NULL,
            linked_loan_id TEXT,
            source TEXT DEFAULT 'manual',
            as_of TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    yield db
    db.close()


# ── T05-1: Single property, three sequential valuations ──────────────────────

def test_re_uses_valuation_current_at_each_month(conn):
    """Each month should pick up the most recent RE valuation at or before that month."""
    conn.execute("INSERT INTO accounts VALUES ('chk1', 'checking', 1, 'bank')")
    # Snapshot early in 2024 so it carries forward into all 2025 months
    conn.execute(
        "INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ('chk1', '2024-12-01', 5000)"
    )
    # Three RE valuations for the same property at different 2025 months
    conn.execute(
        "INSERT INTO real_estate (name, estimated_value, as_of) VALUES ('Main St', 300000, '2025-02-01')"
    )
    conn.execute(
        "INSERT INTO real_estate (name, estimated_value, as_of) VALUES ('Main St', 310000, '2025-03-01')"
    )
    conn.execute(
        "INSERT INTO real_estate (name, estimated_value, as_of) VALUES ('Main St', 320000, '2025-04-01')"
    )
    conn.commit()

    history = get_net_worth_history(conn, months=15)
    month_map = {r["month"]: r for r in history}

    # 2025-01: no RE valuation yet (first is 2025-02) → 0
    assert month_map["2025-01"]["real_estate_assets"] == 0.0

    # 2025-02: first valuation → 300000
    assert month_map["2025-02"]["real_estate_assets"] == 300000.0

    # 2025-03: second valuation → 310000
    assert month_map["2025-03"]["real_estate_assets"] == 310000.0

    # 2025-04 and later: third valuation → 320000
    assert month_map["2025-04"]["real_estate_assets"] == 320000.0
    assert month_map["2025-06"]["real_estate_assets"] == 320000.0  # still holds months later


# ── T05-2: Month before any valuation exists → RE should be 0 ────────────────

def test_re_zero_before_first_valuation(conn):
    """Months before the first RE entry was recorded should have 0 real estate."""
    conn.execute("INSERT INTO accounts VALUES ('chk1', 'checking', 1, 'bank')")
    conn.execute(
        "INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ('chk1', '2024-12-01', 5000)"
    )
    # RE valuation only starts 2025-04
    conn.execute(
        "INSERT INTO real_estate (name, estimated_value, as_of) VALUES ('Home', 400000, '2025-04-05')"
    )
    conn.commit()

    history = get_net_worth_history(conn, months=15)
    month_map = {r["month"]: r for r in history}

    # Before the valuation: 0
    assert month_map["2025-01"]["real_estate_assets"] == 0.0
    assert month_map["2025-02"]["real_estate_assets"] == 0.0
    assert month_map["2025-03"]["real_estate_assets"] == 0.0

    # Month of valuation: 400000
    assert month_map["2025-04"]["real_estate_assets"] == 400000.0

    # Subsequent months carry the last known value
    assert month_map["2025-06"]["real_estate_assets"] == 400000.0


# ── T05-3: Source audit rows (name with '[') are excluded ────────────────────

def test_source_audit_rows_excluded(conn):
    """Rows with '[' in the name are source-audit rows and must not be counted."""
    conn.execute("INSERT INTO accounts VALUES ('chk1', 'checking', 1, 'bank')")
    conn.execute(
        "INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ('chk1', '2024-12-01', 5000)"
    )
    # Primary valuation
    conn.execute(
        "INSERT INTO real_estate (name, estimated_value, as_of) VALUES ('Main St', 300000, '2025-02-01')"
    )
    # Zillow/source audit row — must be excluded
    conn.execute(
        "INSERT INTO real_estate (name, estimated_value, as_of) VALUES ('Main St [zillow]', 999999, '2025-02-02')"
    )
    conn.commit()

    history = get_net_worth_history(conn, months=15)
    month_map = {r["month"]: r for r in history}

    # Should be 300000 only — zillow row not counted
    assert month_map["2025-02"]["real_estate_assets"] == 300000.0


# ── T05-4: Multiple properties summed per month ──────────────────────────────

def test_multiple_properties_summed(conn):
    """Multiple properties should be summed for each month."""
    conn.execute("INSERT INTO accounts VALUES ('chk1', 'checking', 1, 'bank')")
    conn.execute(
        "INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ('chk1', '2024-12-01', 5000)"
    )
    conn.execute(
        "INSERT INTO real_estate (name, estimated_value, as_of) VALUES ('Home A', 200000, '2025-02-01')"
    )
    conn.execute(
        "INSERT INTO real_estate (name, estimated_value, as_of) VALUES ('Home B', 150000, '2025-02-01')"
    )
    conn.commit()

    history = get_net_worth_history(conn, months=15)
    month_map = {r["month"]: r for r in history}

    assert month_map["2025-02"]["real_estate_assets"] == 350000.0


# ── T05-5: Return shape unchanged ────────────────────────────────────────────

def test_return_shape_unchanged(conn):
    """Each result dict must have exactly the expected keys."""
    conn.execute("INSERT INTO accounts VALUES ('chk1', 'checking', 1, 'bank')")
    conn.execute(
        "INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ('chk1', '2024-12-01', 5000)"
    )
    conn.commit()

    history = get_net_worth_history(conn, months=3)
    assert len(history) > 0
    expected_keys = {"month", "banking_assets", "investment_assets", "real_estate_assets",
                     "vehicle_assets", "assets", "liabilities", "net_worth"}
    for row in history:
        assert expected_keys == set(row.keys())


# ── T05-6: Two valuations in same month — later one wins ─────────────────────

def test_same_month_valuation_uses_latest(conn):
    """Two valuations in the same YYYY-MM should use the one with the higher as_of date."""
    conn.execute("INSERT INTO accounts VALUES ('chk1', 'checking', 1, 'bank')")
    conn.execute(
        "INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ('chk1', '2024-12-01', 5000)"
    )
    # Both are in 2025-02; second should win (ASC order → last iteration wins)
    conn.execute(
        "INSERT INTO real_estate (name, estimated_value, as_of) VALUES ('Home', 300000, '2025-02-01')"
    )
    conn.execute(
        "INSERT INTO real_estate (name, estimated_value, as_of) VALUES ('Home', 305000, '2025-02-20')"
    )
    conn.commit()

    history = get_net_worth_history(conn, months=15)
    month_map = {r["month"]: r for r in history}

    # Both as_of[:7] == "2025-02", sorted ASC → last item seen is 305000
    assert month_map["2025-02"]["real_estate_assets"] == 305000.0


# ── T05-7: RE values feed into assets and net_worth correctly ────────────────

def test_re_included_in_assets_and_net_worth(conn):
    """real_estate_assets must be included in assets, and assets - liabilities = net_worth."""
    conn.execute("INSERT INTO accounts VALUES ('chk1', 'checking', 1, 'bank')")
    conn.execute(
        "INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ('chk1', '2024-12-01', 10000)"
    )
    conn.execute(
        "INSERT INTO real_estate (name, estimated_value, as_of) VALUES ('Home', 250000, '2025-02-01')"
    )
    conn.commit()

    history = get_net_worth_history(conn, months=15)
    month_map = {r["month"]: r for r in history}

    feb = month_map["2025-02"]
    # banking=10000, portfolio=0, re=250000 → assets=260000
    assert feb["real_estate_assets"] == 250000.0
    assert feb["assets"] == round(feb["banking_assets"] + feb["investment_assets"] + feb["real_estate_assets"] + feb["vehicle_assets"], 2)
    assert feb["net_worth"] == round(feb["assets"] - feb["liabilities"], 2)
