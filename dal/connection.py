"""
dal/connection.py — SQLite connection management for Sentry Finance.

Provides:
  - DB_PATH: default database location (data/sentry.db)
  - get_db(): context manager yielding a WAL-mode connection
  - _connect(): low-level connection factory (internal use)

All connections are configured with:
  - WAL journal mode  (concurrent reads during writes)
  - Foreign keys ON
  - 5 s busy timeout
  - Row-factory dict access
"""

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import os

log = logging.getLogger("sentry.dal")

BASE_DIR = Path(__file__).resolve().parent.parent
_env_path = os.environ.get("SENTRY_DB_PATH")
DB_PATH = Path(_env_path) if _env_path else BASE_DIR / "data" / "sentry.db"


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Create a connection with WAL mode and foreign keys enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_db(db_path: Path = DB_PATH):
    """Context manager yielding a database connection.

    Usage:
        with get_db() as conn:
            conn.execute("SELECT ...")
    """
    conn = _connect(db_path)
    try:
        yield conn
    finally:
        conn.close()
