"""Schema V3 — Investment holdings, real estate, and transfer tagging."""

VERSION = 3

_DDL = """
-- Investment Holdings (daily per-ticker positions)
CREATE TABLE IF NOT EXISTS investment_holdings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    date            TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    shares          REAL NOT NULL,
    close_price     REAL,
    market_value    REAL,
    cost_basis      REAL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(account_id, date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_inv_hold_account_date
    ON investment_holdings(account_id, date);
CREATE INDEX IF NOT EXISTS idx_inv_hold_ticker
    ON investment_holdings(account_id, ticker, date);

-- Real Estate (property valuations for net worth)
CREATE TABLE IF NOT EXISTS real_estate (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    estimated_value REAL NOT NULL,
    linked_loan_id  TEXT REFERENCES accounts(id),
    source          TEXT DEFAULT 'manual',
    as_of           TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""

_ALTER_TRANSFER_TAG = "ALTER TABLE transactions ADD COLUMN transfer_tag TEXT"


def run(conn):
    conn.executescript(_DDL)
    # ALTER TABLE can't use IF NOT EXISTS, so check first
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
    if "transfer_tag" not in cols:
        conn.execute(_ALTER_TRANSFER_TAG)
