"""
dal/categorization.py — Rule-based transaction categorization engine.

Three-layer priority:
  1. User override (category_overrides table) — always wins
  2. Keyword rules (config/categories.yaml) — regex match on description
  3. Bank-provided category (e.g. NFCU sends one from scraping)
  4. Fallback: "Uncategorized"
"""

import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("sentry.dal.categorization")

BASE_DIR = Path(__file__).resolve().parent.parent
_RULES_PATH = BASE_DIR / "config" / "categories.yaml"

# ── Rule Loading ─────────────────────────────────────────────────────────────

_compiled_rules: Optional[list[tuple[re.Pattern, str]]] = None


def _load_rules() -> list[tuple[re.Pattern, str]]:
    """Load and compile regex rules from categories.yaml (cached)."""
    global _compiled_rules
    if _compiled_rules is not None:
        return _compiled_rules

    if not _RULES_PATH.exists():
        log.warning("categories.yaml not found — keyword categorization disabled")
        _compiled_rules = []
        return _compiled_rules

    with open(_RULES_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    rules = config.get("rules", [])
    _compiled_rules = []
    for rule in rules:
        try:
            pattern = re.compile(rule["pattern"], re.IGNORECASE)
            _compiled_rules.append((pattern, rule["category"]))
        except (re.error, KeyError) as e:
            log.warning("Skipping invalid rule %r: %s", rule, e)

    log.info("Loaded %d categorization rules from categories.yaml", len(_compiled_rules))
    return _compiled_rules


def reload_rules() -> int:
    """Force-reload rules from disk.  Returns count of loaded rules."""
    global _compiled_rules
    _compiled_rules = None
    return len(_load_rules())


# ── Categorization Logic ─────────────────────────────────────────────────────


def categorize(
    description: str,
    bank_category: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    txn_id: Optional[str] = None,
) -> str:
    """Categorize a transaction using the layered strategy.

    Args:
        description: Transaction description text.
        bank_category: Category provided by the bank/institution (e.g. NFCU).
        conn: Optional DB connection (needed for user override lookup).
        txn_id: Optional transaction ID (needed for user override lookup).

    Returns:
        The resolved category string.
    """
    # Layer 1: User override (highest priority)
    if conn is not None and txn_id is not None:
        override = get_user_override(conn, txn_id)
        if override:
            return override

    # Layer 2: Keyword rules
    if description:
        rules = _load_rules()
        for pattern, category in rules:
            if pattern.search(description):
                return category

    # Layer 3: Bank-provided category
    if bank_category and bank_category not in ("Uncategorized", "nan", ""):
        return bank_category

    # Layer 4: Fallback
    return "Uncategorized"


# ── User Overrides ───────────────────────────────────────────────────────────


def get_user_override(conn: sqlite3.Connection, txn_id: str) -> Optional[str]:
    """Check if the user has manually overridden this transaction's category."""
    try:
        row = conn.execute(
            "SELECT category FROM category_overrides WHERE txn_id = ?",
            (txn_id,),
        ).fetchone()
        return row["category"] if row else None
    except sqlite3.OperationalError:
        # Table may not exist yet (pre-V6 schema)
        return None


def set_user_override(
    conn: sqlite3.Connection, txn_id: str, category: str
) -> None:
    """Store a user category correction.  Also updates the transaction row."""
    conn.execute(
        """
        INSERT INTO category_overrides (txn_id, category)
        VALUES (?, ?)
        ON CONFLICT(txn_id) DO UPDATE SET category = excluded.category,
            created_at = datetime('now')
    """,
        (txn_id, category),
    )
    conn.execute(
        "UPDATE transactions SET category = ?, updated_at = datetime('now') "
        "WHERE id = ?",
        (category, txn_id),
    )
    log.info("User override: txn %s → %s", txn_id, category)


def delete_user_override(conn: sqlite3.Connection, txn_id: str) -> None:
    """Remove a user override, reverting to rule-based categorization."""
    conn.execute("DELETE FROM category_overrides WHERE txn_id = ?", (txn_id,))
    log.info("Removed user override for txn %s", txn_id)


# ── Backfill ─────────────────────────────────────────────────────────────────


def backfill_uncategorized(conn: sqlite3.Connection) -> dict:
    """Apply keyword rules to all uncategorized transactions.

    Returns:
        {"matched": int, "still_uncategorized": int, "cleaned_nan": int}
    """
    stats = {"matched": 0, "still_uncategorized": 0, "cleaned_nan": 0}

    # First: clean up 'nan' values
    nan_count = conn.execute(
        "UPDATE transactions SET category = 'Uncategorized' "
        "WHERE category = 'nan'"
    ).rowcount
    stats["cleaned_nan"] = nan_count
    if nan_count:
        log.info("Cleaned %d 'nan' category values → 'Uncategorized'", nan_count)

    # Fetch all uncategorized
    rows = conn.execute(
        """
        SELECT id, description, category
        FROM transactions
        WHERE (category = 'Uncategorized' OR category IS NULL)
          AND status != 'deleted'
    """
    ).fetchall()

    for row in rows:
        # Check for user override first
        override = get_user_override(conn, row["id"])
        if override:
            conn.execute(
                "UPDATE transactions SET category = ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (override, row["id"]),
            )
            stats["matched"] += 1
            continue

        # Apply keyword rules (skip bank category since it's already Uncategorized)
        new_cat = categorize(row["description"] or "", bank_category=None)
        if new_cat != "Uncategorized":
            conn.execute(
                "UPDATE transactions SET category = ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (new_cat, row["id"]),
            )
            stats["matched"] += 1
        else:
            stats["still_uncategorized"] += 1

    conn.commit()
    log.info(
        "Backfill complete: %d matched, %d still uncategorized, %d nan cleaned",
        stats["matched"],
        stats["still_uncategorized"],
        stats["cleaned_nan"],
    )
    return stats


# ── Utilities ────────────────────────────────────────────────────────────────


def list_categories(conn: sqlite3.Connection) -> list[dict]:
    """Return all categories currently in use with their transaction counts."""
    rows = conn.execute(
        """
        SELECT category, COUNT(*) as count
        FROM transactions
        WHERE status != 'deleted'
        GROUP BY category
        ORDER BY count DESC
    """
    ).fetchall()
    return [dict(r) for r in rows]
