"""
dal/migrations/__init__.py — Schema migration runner for Sentry Finance.

Discovers versioned migration modules (v01_core, v02_portfolio, ...),
tracks the current version via PRAGMA user_version, and applies pending
migrations sequentially with per-step transaction safety.

Public API:
    init_db(db_path=None)  — ensure schema is current
    SCHEMA_VERSION         — latest version constant (int)
"""

import importlib
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from dal.connection import _connect, resolve_db_path

log = logging.getLogger("sentry.dal.migrations")

# ── Discover migration modules ────────────────────────────────────────────────

_MIGRATIONS_DIR = Path(__file__).resolve().parent

def _discover_migrations() -> list[tuple[int, str]]:
    """Return sorted (version, module_name) pairs from v*_*.py files."""
    found: list[tuple[int, str]] = []
    for path in sorted(_MIGRATIONS_DIR.glob("v[0-9]*_*.py")):
        mod_name = path.stem  # e.g. "v01_core"
        mod = importlib.import_module(f"dal.migrations.{mod_name}")
        version = getattr(mod, "VERSION", None)
        if version is None:
            log.warning("Migration %s has no VERSION — skipping", mod_name)
            continue
        found.append((version, mod_name))
    # Sort by version number
    found.sort(key=lambda t: t[0])
    return found


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if ``column`` exists on ``table``.

    Intended for use in **new** migrations that need to be idempotent against
    partial prior-version state (re-runs, repaired databases). Shipped
    migrations are immutable historical records — do not retrofit existing
    ``v*.py`` files to use this helper; their inline ``PRAGMA table_info``
    scans are part of the record.
    """
    return any(
        row[1] == column
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    )


_ALL_MIGRATIONS = _discover_migrations()

# The highest declared version across all migration files
SCHEMA_VERSION: int = _ALL_MIGRATIONS[-1][0] if _ALL_MIGRATIONS else 0


# ── Migration runner ──────────────────────────────────────────────────────────

def init_db(db_path: Optional[Path] = None) -> None:
    """Initialise or upgrade the database to the latest schema version.

    Args:
        db_path: Override database path (default: connection.DB_PATH).
                 Accepts Path or str for test convenience.

    Behaviour:
        1. Reads ``PRAGMA user_version`` to find current version.
        2. Runs each pending migration inside an **IMMEDIATE** transaction
           so only one writer can proceed (SQLite-level locking).
        3. Bumps ``user_version`` after each successful migration.
        4. On failure mid-migration the transaction is rolled back and the
           version stays at the last successful step.
    """
    path = resolve_db_path(db_path)
    conn = _connect(path)

    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]

        if current >= SCHEMA_VERSION:
            return  # already up to date

        log.info(
            "Database at v%d — applying migrations to v%d",
            current, SCHEMA_VERSION,
        )

        for version, mod_name in _ALL_MIGRATIONS:
            if version <= current:
                continue

            mod = importlib.import_module(f"dal.migrations.{mod_name}")
            run_fn = getattr(mod, "run", None)
            if run_fn is None:
                log.warning("Migration %s has no run() — skipping", mod_name)
                continue

            log.info("Applying migration %s (v%d → v%d)", mod_name, current, version)

            # BEGIN IMMEDIATE acquires a reserved lock immediately,
            # preventing concurrent writers from interleaving.
            conn.execute("BEGIN IMMEDIATE")
            try:
                run_fn(conn)
                # executescript() may have auto-committed, so only set
                # user_version if we're still in a transaction or start a new one.
                try:
                    conn.execute(f"PRAGMA user_version = {version}")
                    conn.commit()
                except sqlite3.OperationalError:
                    # If executescript() already committed, we're outside a txn.
                    # Start a brief txn just to bump the version.
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(f"PRAGMA user_version = {version}")
                    conn.commit()

                current = version
                log.info("Migration %s applied successfully (now v%d)", mod_name, version)

            except Exception:
                # Roll back if possible (may already be rolled back by executescript failure)
                try:
                    conn.rollback()
                except Exception:
                    pass
                log.exception("Migration %s FAILED — database left at v%d", mod_name, current)
                raise

    finally:
        conn.close()
