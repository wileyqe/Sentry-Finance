"""
dal — Data Access Layer for Sentry Finance.

SQLite-backed storage with incremental upserts, deterministic
transaction identity, and scoped metric recomputation.
"""
from dal.connection import get_db
from dal.migrations import init_db

__all__ = ["get_db", "init_db"]
