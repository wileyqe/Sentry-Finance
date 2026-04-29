"""
dal/connection.py — SQLite connection management for Sentry Finance.

Provides:
  - DB_PATH: canonical trusted-seed fixture path constant (data/dummy.db)
  - resolve_db_path(): runtime database path resolver
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
DB_PATH = BASE_DIR / "data" / "dummy.db"

_ENV_DB_PATH = "SENTRY_DB_PATH"
_ENV_DB_MODE = "SENTRY_DB_MODE"


def db_mode() -> str:
    """Return the active DB mode label for runtime identity/proof checks."""
    return os.environ.get(_ENV_DB_MODE, "dev").strip().lower() or "dev"


def resolve_db_path(
    db_path: Path | str | None = None,
    *,
    require_explicit: bool = True,
) -> Path:
    """Resolve the active database path at call time.

    A caller-provided ``db_path`` and ``SENTRY_DB_PATH`` are the only runtime
    authorities. ``DB_PATH`` remains a canonical fixture path constant for
    explicit test/script use, but is not an implicit fallback.

    ``require_explicit`` is retained for older call sites. Missing
    ``SENTRY_DB_PATH`` now fails loudly regardless of that flag.
    """
    if db_path is not None:
        return Path(db_path)

    env_path = os.environ.get(_ENV_DB_PATH)
    if env_path:
        return Path(env_path)

    raise RuntimeError(
        f"{_ENV_DB_PATH} is required for database access. "
        "Set it to the single active DB path or pass an explicit db_path."
    )


def require_explicit_db_path() -> Path:
    return resolve_db_path()


def _connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create a connection with WAL mode and foreign keys enabled."""
    path = resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_db(db_path: Path | str | None = None):
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
