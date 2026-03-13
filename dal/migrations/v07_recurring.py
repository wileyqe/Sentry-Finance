"""Schema V7 — Recurring transaction detection and price mutation tracking."""

VERSION = 7

_DDL = """
CREATE TABLE IF NOT EXISTS recurring_transactions (
    id              TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    merchant        TEXT NOT NULL,
    category        TEXT,
    frequency       TEXT NOT NULL,
    avg_interval    REAL NOT NULL,
    expected_amount REAL,
    amount_stable   INTEGER DEFAULT 0,
    last_amount     REAL,
    last_date       TEXT,
    next_expected   TEXT,
    occurrence_count INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'active',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recurring_mutations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recurring_id    TEXT NOT NULL REFERENCES recurring_transactions(id),
    old_amount      REAL,
    new_amount      REAL,
    detected_at     TEXT DEFAULT (datetime('now')),
    description     TEXT
);
"""


def run(conn):
    conn.executescript(_DDL)
