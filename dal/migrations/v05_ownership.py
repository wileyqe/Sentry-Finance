"""Schema V5 — Ownership / multi-user views (Yours/Ours/Mine toggle).

Adds an `owners` table and an `owner_id` FK on `accounts` to support
the household dashboard view toggle.  NULL owner_id = shared ("ours").
"""

VERSION = 5

_DDL = """
CREATE TABLE IF NOT EXISTS owners (
    id           TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at   TEXT DEFAULT (datetime('now'))
);
"""

_ALTER_OWNER = "ALTER TABLE accounts ADD COLUMN owner_id TEXT REFERENCES owners(id)"


def run(conn):
    conn.executescript(_DDL)
    acct_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()
    }
    if "owner_id" not in acct_cols:
        conn.execute(_ALTER_OWNER)
