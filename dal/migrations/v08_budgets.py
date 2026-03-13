"""Schema V8 — Monthly budgets per category (ownership-aware)."""

VERSION = 8

_DDL = """
CREATE TABLE IF NOT EXISTS budgets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category        TEXT NOT NULL,
    month           TEXT NOT NULL,
    target_amount   REAL NOT NULL,
    owner_id        TEXT REFERENCES owners(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(category, month, owner_id)
);
"""


def run(conn):
    conn.executescript(_DDL)
