"""Schema V10 — Savings goals, benchmark prices, and ticker metadata."""

VERSION = 10

_DDL = """
CREATE TABLE IF NOT EXISTS savings_goals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    target_amount       REAL NOT NULL,
    current_amount      REAL DEFAULT 0.0,
    deadline            TEXT,
    linked_account_id   TEXT REFERENCES accounts(id),
    owner_id            TEXT REFERENCES owners(id),
    status              TEXT DEFAULT 'active',
    notes               TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS benchmark_prices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    price_date  TEXT NOT NULL,
    close_price REAL NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, price_date)
);
CREATE INDEX IF NOT EXISTS idx_benchmark_ticker_date
    ON benchmark_prices(ticker, price_date);

CREATE TABLE IF NOT EXISTS ticker_metadata (
    ticker       TEXT PRIMARY KEY,
    sector       TEXT,
    industry     TEXT,
    asset_class  TEXT,
    last_updated TEXT DEFAULT (date('now'))
);
"""


def run(conn):
    conn.executescript(_DDL)
