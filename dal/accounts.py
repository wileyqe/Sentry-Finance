"""
dal/accounts.py — Read helpers for the ``accounts`` table.

Lookups against ``accounts.id`` that need only a single column (e.g. the
``type`` dispatch used by ``/api/accounts/{id}/details``) live here so
routers don't carry inline SQL. Keep this file scoped tightly — multi-
column reads belong with the feature that owns them (e.g.
``dal.balances.get_all_latest_balances`` for balance pivots).
"""

import sqlite3
from typing import Optional


def get_account_type(conn: sqlite3.Connection, account_id: str) -> Optional[str]:
    """Return the ``type`` column for an account, or ``None`` if missing."""
    row = conn.execute(
        "SELECT type FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if row is None:
        return None
    return row["type"]
