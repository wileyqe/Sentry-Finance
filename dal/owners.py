"""
dal/owners.py — Ownership management for multi-user dashboard views.

Supports the Yours / Ours / Mine dashboard toggle by partitioning
accounts by owner.  NULL owner_id is treated as "ours" (visible in
all views).

Views:
  ours   → all active accounts (default)
  mine   → owner_id = primary_owner OR owner_id IS NULL
  theirs → owner_id != primary_owner AND owner_id IS NOT NULL
"""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("sentry.dal.owners")

BASE_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = BASE_DIR / "config" / "owner_config.yaml"

# ── Config Loading ───────────────────────────────────────────────────────────

_config_cache: Optional[dict] = None


def _load_config() -> dict:
    """Load and cache owner_config.yaml."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    if not _CONFIG_PATH.exists():
        log.warning("owner_config.yaml not found — ownership features disabled")
        _config_cache = {"primary_owner": None, "owners": []}
        return _config_cache

    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        _config_cache = yaml.safe_load(f) or {}
    return _config_cache


def get_primary_owner() -> Optional[str]:
    """Return the primary owner ID from config."""
    return _load_config().get("primary_owner")


def get_configured_owners() -> list[dict]:
    """Return the list of configured owners from owner_config.yaml."""
    return _load_config().get("owners", [])


# ── CRUD Operations ─────────────────────────────────────────────────────────


def create_owner(conn: sqlite3.Connection, owner_id: str, display_name: str) -> None:
    """Insert a new owner record (idempotent via INSERT OR IGNORE)."""
    conn.execute(
        """
        INSERT OR IGNORE INTO owners (id, display_name)
        VALUES (?, ?)
    """,
        (owner_id, display_name),
    )
    log.debug("Created owner: %s (%s)", owner_id, display_name)


def list_owners(conn: sqlite3.Connection) -> list[dict]:
    """Return all owner records."""
    rows = conn.execute(
        "SELECT id, display_name, created_at FROM owners ORDER BY display_name"
    ).fetchall()
    return [dict(r) for r in rows]


def assign_account_owner(
    conn: sqlite3.Connection, account_id: str, owner_id: Optional[str]
) -> None:
    """Set the owner_id on an account.  Pass None to make it shared (ours)."""
    conn.execute(
        "UPDATE accounts SET owner_id = ? WHERE id = ?",
        (owner_id, account_id),
    )
    log.info("Assigned account %s → owner %s", account_id, owner_id or "(shared)")


def get_account_owner(conn: sqlite3.Connection, account_id: str) -> Optional[str]:
    """Return the owner_id for a given account, or None if shared."""
    row = conn.execute(
        "SELECT owner_id FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    return row["owner_id"] if row else None


# ── View Resolution ─────────────────────────────────────────────────────────


def resolve_account_ids_for_view(
    conn: sqlite3.Connection, view: str = "ours"
) -> Optional[set[str]]:
    """Resolve a dashboard view to a set of account IDs.

    Args:
        conn: Active SQLite connection.
        view: One of "ours", "mine", "theirs".

    Returns:
        A set of account IDs matching the view, or None if view
        is "ours" (meaning no filtering — return everything).
    """
    view = view.lower().strip()

    if view == "ours":
        # No filtering — caller should use all accounts
        return None

    primary = get_primary_owner()
    if not primary:
        log.warning("No primary_owner configured — falling back to 'ours' view")
        return None

    if view == "mine":
        # My accounts + shared (NULL owner_id)
        rows = conn.execute(
            """
            SELECT id FROM accounts
            WHERE is_active = 1
              AND (owner_id = ? OR owner_id IS NULL)
        """,
            (primary,),
        ).fetchall()
    elif view == "theirs":
        # Partner's accounts + shared (NULL owner_id)
        rows = conn.execute(
            """
            SELECT id FROM accounts
            WHERE is_active = 1
              AND (owner_id IS NOT NULL AND owner_id != ?)
              OR owner_id IS NULL
        """,
            (primary,),
        ).fetchall()
    else:
        log.warning("Unknown view '%s' — falling back to 'ours'", view)
        return None

    return {r["id"] for r in rows}


def seed_owners(conn: sqlite3.Connection) -> None:
    """Seed the owners table from owner_config.yaml.

    Called during database initialization alongside seed_institutions().
    Idempotent via INSERT OR IGNORE.
    """
    owners = get_configured_owners()
    for owner in owners:
        create_owner(conn, owner["id"], owner["display_name"])

    if owners:
        conn.commit()
        log.info("Seeded %d owners from owner_config.yaml", len(owners))
