"""Schema V12 — Add closed_at column to accounts for inactive/paid-off tracking."""

VERSION = 12

_DDL = """
ALTER TABLE accounts ADD COLUMN closed_at TEXT;
"""


def run(conn):
    # ALTER TABLE ADD COLUMN is already idempotent-safe in SQLite (errors if exists)
    # Wrap in try/except for rerunnability
    try:
        conn.execute(_DDL.strip())
    except Exception:
        pass  # Column already exists
