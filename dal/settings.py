"""
dal/settings.py — App settings read/write.

Settings are stored as JSON strings in a key-value table.
"""

import json
import sqlite3
import logging

log = logging.getLogger("sentry.dal.settings")


def get_setting(conn: sqlite3.Connection, key: str):
    """Get a single setting value, JSON-decoded. Returns None if not found."""
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = ?", (key,)
    ).fetchone()
    if row:
        return json.loads(row["value"])
    return None


def set_setting(conn: sqlite3.Connection, key: str, value) -> None:
    """Set a single setting value, JSON-encoded."""
    conn.execute(
        """INSERT INTO app_settings (key, value, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(key) DO UPDATE SET value = excluded.value,
           updated_at = excluded.updated_at""",
        (key, json.dumps(value)),
    )
    conn.commit()


def get_all_settings(conn: sqlite3.Connection) -> dict:
    """Get all settings as a dict of {key: decoded_value}."""
    rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    return {r["key"]: json.loads(r["value"]) for r in rows}
