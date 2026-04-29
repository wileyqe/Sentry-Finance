"""
dal/database.py — Backward-compatible façade for Sentry Finance database layer.

This module re-exports all public symbols from the refactored sub-modules
so that existing ``from dal.database import ...`` statements continue to
work without any changes.

Internal structure:
  dal/connection.py          — DB_PATH, BASE_DIR, _connect(), get_db()
  dal/migrations/__init__.py — init_db(), SCHEMA_VERSION
  dal/migrations/v01..v10    — Individual schema version DDL
  dal/seed.py                — seed_institutions()
"""

# ── Re-exports (preserves the public API) ────────────────────────────────────

from dal.connection import (  # noqa: F401
    DB_PATH,
    BASE_DIR,
    db_mode,
    get_db,
    require_explicit_db_path,
    resolve_db_path,
    _connect,
)
from dal.migrations import init_db, SCHEMA_VERSION                      # noqa: F401
from dal.seed import seed_institutions                                   # noqa: F401

__all__ = [
    "DB_PATH",
    "BASE_DIR",
    "db_mode",
    "get_db",
    "require_explicit_db_path",
    "resolve_db_path",
    "init_db",
    "seed_institutions",
    "SCHEMA_VERSION",
]
