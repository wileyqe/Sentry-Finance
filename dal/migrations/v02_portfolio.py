"""Schema V2 — Investment tracking: portfolio snapshots and positions ledger."""

VERSION = 2

_DDL = """
-- Portfolio Snapshots (Top-line tracking)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          TEXT NOT NULL REFERENCES accounts(id),
    timestamp           TEXT NOT NULL,
    total_account_value REAL,
    cash_balance        REAL,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_port_snap_account_date
    ON portfolio_snapshots(account_id, timestamp);

-- Positions Ledger (Delta-Logging transaction history)
CREATE TABLE IF NOT EXISTS positions_ledger (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id                  TEXT NOT NULL REFERENCES accounts(id),
    timestamp                   TEXT NOT NULL,
    ticker                      TEXT NOT NULL,
    transaction_type            TEXT NOT NULL,
    share_delta                 REAL NOT NULL,
    new_total_shares            REAL NOT NULL,
    yfinance_closing_price      REAL,
    estimated_transaction_value REAL,
    created_at                  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pos_ledger_account_ticker
    ON positions_ledger(account_id, ticker);
"""


def run(conn):
    conn.executescript(_DDL)
