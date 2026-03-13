"""Schema V6 — Category overrides (user correction table)."""

VERSION = 6

_DDL = """
CREATE TABLE IF NOT EXISTS category_overrides (
    txn_id       TEXT PRIMARY KEY REFERENCES transactions(id),
    category     TEXT NOT NULL,
    created_at   TEXT DEFAULT (datetime('now'))
);
"""


def run(conn):
    conn.executescript(_DDL)
