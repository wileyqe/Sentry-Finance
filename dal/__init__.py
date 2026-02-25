"""
dal — Data Access Layer for Sentry Finance.

SQLite-backed storage with incremental upserts, deterministic
transaction identity, and scoped metric recomputation.
"""
from dal.database import get_db, init_db

__all__ = ["get_db", "init_db"]

