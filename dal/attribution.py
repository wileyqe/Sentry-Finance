"""
dal/attribution.py — Income attribution engine.

Attributes income transactions to the month they financially "belong" to,
rather than the month they happen to post in.  Government payroll (DFAS,
VA) routinely pushes deposits 1-3 business days before the 1st, landing
them in the prior month's ledger.

This module:
  1. Reads `income_attribution_rules` (category-based, schedule-aware).
  2. For matching transactions, computes `effective_month` and stamps it.
  3. All reporting queries use COALESCE(effective_month, strftime('%Y-%m', posting_date))
     so non-attributed transactions are unaffected.

Key design choice: match on CATEGORY, not description.  Category is the
stable output of the categorization pipeline (user overrides → user rules →
keyword regex → bank label).  Descriptions change when DFAS or the bank
changes formatting; categories don't.
"""

import calendar
import logging
import sqlite3
from datetime import date, datetime
from typing import Optional

log = logging.getLogger("sentry.dal.attribution")


# ── Core Date Math ───────────────────────────────────────────────────────────


def _compute_effective_month(
    posting_date: date,
    target_day: int,
    lookahead_days: int,
) -> Optional[str]:
    """Determine if a transaction should be attributed to a different month.

    If the posting_date falls within `lookahead_days` calendar days before
    the target_day of the NEXT month, return 'YYYY-MM' of that next month.
    Otherwise return None (no shift — use posting month as-is).

    Examples (target_day=1, lookahead=5):
      - Feb 27 → March 1 is 2 days away → '2026-03'
      - Feb 22 → March 1 is 7 days away → None (stays Feb)
      - Dec 29 → Jan 1 is 3 days away  → '2027-01' (year rollover)
      - Mar 1  → already ON the target  → None (0 days, not shifted)
    """
    year, month = posting_date.year, posting_date.month

    # Build the target date in the NEXT month
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    # Clamp target_day to the max days in the next month
    max_day = calendar.monthrange(next_year, next_month)[1]
    clamped_day = min(target_day, max_day)
    next_target = date(next_year, next_month, clamped_day)

    days_until = (next_target - posting_date).days

    if 0 < days_until <= lookahead_days:
        return f"{next_year}-{next_month:02d}"

    return None


# ── Attribution Application ──────────────────────────────────────────────────


def apply_attribution(
    conn: sqlite3.Connection,
    transaction_ids: Optional[list[str]] = None,
) -> dict:
    """Apply attribution rules to transactions.

    If transaction_ids is provided, only process those specific transactions.
    Otherwise, process all un-attributed transactions that match active rules.

    Returns:
        {"attributed": int, "skipped": int, "rules_matched": int}
    """
    rules = _get_active_rules(conn)
    if not rules:
        return {"attributed": 0, "skipped": 0, "rules_matched": 0}

    # Build category → rule lookup
    cat_rules = {}
    for rule in rules:
        cat_rules[rule["match_category"]] = rule

    matched_categories = list(cat_rules.keys())
    cat_placeholders = ", ".join("?" for _ in matched_categories)

    # Find candidate transactions
    if transaction_ids:
        id_placeholders = ", ".join("?" for _ in transaction_ids)
        rows = conn.execute(
            f"""
            SELECT id, posting_date, category, direction
            FROM transactions
            WHERE id IN ({id_placeholders})
              AND status = 'posted'
              AND category IN ({cat_placeholders})
            """,
            transaction_ids + matched_categories,
        ).fetchall()
    else:
        # Process all matching transactions (for backfill or re-run)
        rows = conn.execute(
            f"""
            SELECT id, posting_date, category, direction
            FROM transactions
            WHERE status = 'posted'
              AND category IN ({cat_placeholders})
            """,
            matched_categories,
        ).fetchall()

    attributed = 0
    skipped = 0
    rules_used = set()

    for row in rows:
        rule = cat_rules.get(row["category"])
        if not rule:
            skipped += 1
            continue

        # Check direction match
        if rule["match_direction"] and row["direction"] != rule["match_direction"]:
            skipped += 1
            continue

        # Parse posting_date
        try:
            pd = datetime.strptime(row["posting_date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            skipped += 1
            continue

        effective = _compute_effective_month(
            pd, rule["target_day"], rule["lookahead_days"]
        )

        if effective:
            conn.execute(
                "UPDATE transactions SET effective_month = ? WHERE id = ?",
                (effective, row["id"]),
            )
            attributed += 1
            rules_used.add(rule["id"])
        else:
            # Explicitly clear: this transaction belongs to its posting month
            conn.execute(
                "UPDATE transactions SET effective_month = NULL WHERE id = ?",
                (row["id"],),
            )
            skipped += 1

    log.info(
        "Attribution: %d attributed, %d skipped, %d rules matched",
        attributed, skipped, len(rules_used),
    )

    return {
        "attributed": attributed,
        "skipped": skipped,
        "rules_matched": len(rules_used),
    }


def apply_attribution_single(
    conn: sqlite3.Connection,
    txn_id: str,
    category: str,
    posting_date: str,
    direction: str = "Credit",
) -> Optional[str]:
    """Lightweight attribution for a single transaction at ingestion time.

    Called inline during upsert_transactions() after categorization.
    Returns the effective_month string if attributed, None otherwise.
    """
    rules = _get_active_rules(conn)
    for rule in rules:
        if rule["match_category"] != category:
            continue
        if rule["match_direction"] and direction != rule["match_direction"]:
            continue

        try:
            pd = datetime.strptime(posting_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

        effective = _compute_effective_month(
            pd, rule["target_day"], rule["lookahead_days"]
        )
        if effective:
            conn.execute(
                "UPDATE transactions SET effective_month = ? WHERE id = ?",
                (effective, txn_id),
            )
            return effective
    return None


def backfill_attribution(conn: sqlite3.Connection) -> dict:
    """One-time backfill: stamp ALL historical transactions matching rules.

    Idempotent — safe to run multiple times.  Overwrites previous
    effective_month values to ensure consistency with current rules.

    Returns:
        {"attributed": int, "cleared": int, "total_scanned": int}
    """
    rules = _get_active_rules(conn)
    if not rules:
        return {"attributed": 0, "cleared": 0, "total_scanned": 0}

    cat_rules = {}
    for rule in rules:
        cat_rules[rule["match_category"]] = rule

    matched_categories = list(cat_rules.keys())
    cat_ph = ", ".join("?" for _ in matched_categories)

    rows = conn.execute(
        f"""
        SELECT id, posting_date, category, direction
        FROM transactions
        WHERE status = 'posted'
          AND category IN ({cat_ph})
        ORDER BY posting_date
        """,
        matched_categories,
    ).fetchall()

    attributed = 0
    cleared = 0

    for row in rows:
        rule = cat_rules.get(row["category"])
        if not rule:
            continue

        if rule["match_direction"] and row["direction"] != rule["match_direction"]:
            continue

        try:
            pd = datetime.strptime(row["posting_date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        effective = _compute_effective_month(
            pd, rule["target_day"], rule["lookahead_days"]
        )

        if effective:
            conn.execute(
                "UPDATE transactions SET effective_month = ? WHERE id = ?",
                (effective, row["id"]),
            )
            attributed += 1
        else:
            # Clear any stale attribution
            conn.execute(
                "UPDATE transactions SET effective_month = NULL WHERE id = ?",
                (row["id"],),
            )
            cleared += 1

    log.info(
        "Backfill: %d attributed, %d cleared, %d total scanned",
        attributed, cleared, len(rows),
    )

    return {
        "attributed": attributed,
        "cleared": cleared,
        "total_scanned": len(rows),
    }


# ── CRUD ─────────────────────────────────────────────────────────────────────


def _get_active_rules(conn: sqlite3.Connection) -> list[dict]:
    """Return all active attribution rules."""
    try:
        rows = conn.execute(
            """
            SELECT id, rule_name, match_category, match_direction,
                   schedule_type, target_day, lookahead_days, owner, is_active
            FROM income_attribution_rules
            WHERE is_active = 1
            """
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        # Table may not exist yet (pre-V19)
        return []


def get_attribution_rules(conn: sqlite3.Connection) -> list[dict]:
    """Return ALL attribution rules (active and inactive)."""
    try:
        rows = conn.execute(
            """
            SELECT id, rule_name, match_category, match_direction,
                   schedule_type, target_day, lookahead_days, owner,
                   is_active, created_at
            FROM income_attribution_rules
            ORDER BY created_at
            """
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def create_attribution_rule(
    conn: sqlite3.Connection,
    rule_name: str,
    match_category: str,
    schedule_type: str = "monthly_fixed",
    target_day: int = 1,
    lookahead_days: int = 5,
    match_direction: str = "Credit",
    owner: str = "self",
) -> int:
    """Create a new attribution rule.  Returns the new rule ID."""
    cursor = conn.execute(
        """
        INSERT INTO income_attribution_rules
            (rule_name, match_category, match_direction, schedule_type,
             target_day, lookahead_days, owner)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (rule_name, match_category, match_direction, schedule_type,
         target_day, lookahead_days, owner),
    )
    rule_id = cursor.lastrowid
    log.info("Created attribution rule #%d: %s → %s", rule_id, match_category, rule_name)
    return rule_id


def update_attribution_rule(
    conn: sqlite3.Connection,
    rule_id: int,
    **kwargs,
) -> bool:
    """Update fields on an existing rule.  Returns True if a row was updated."""
    allowed = {
        "rule_name", "match_category", "match_direction", "schedule_type",
        "target_day", "lookahead_days", "owner", "is_active",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [rule_id]
    affected = conn.execute(
        f"UPDATE income_attribution_rules SET {set_clause} WHERE id = ?",
        values,
    ).rowcount
    return affected > 0


def delete_attribution_rule(conn: sqlite3.Connection, rule_id: int) -> bool:
    """Delete an attribution rule.  Returns True if a row was deleted."""
    affected = conn.execute(
        "DELETE FROM income_attribution_rules WHERE id = ?", (rule_id,)
    ).rowcount
    if affected:
        log.info("Deleted attribution rule #%d", rule_id)
    return affected > 0


# ── Seed Defaults ────────────────────────────────────────────────────────────


def seed_default_rules(conn: sqlite3.Connection) -> int:
    """Insert the 3 default government income attribution rules.

    Idempotent — skips rules that already exist (by match_category).
    Returns the number of rules inserted.
    """
    defaults = [
        ("Military Pension (1st)", "Military Pension"),
        ("VA Disability (1st)", "VA Benefits"),
        ("VA Education (1st)", "VA Education Benefits"),
    ]
    inserted = 0
    for rule_name, category in defaults:
        existing = conn.execute(
            "SELECT id FROM income_attribution_rules WHERE match_category = ?",
            (category,),
        ).fetchone()
        if not existing:
            create_attribution_rule(
                conn,
                rule_name=rule_name,
                match_category=category,
                schedule_type="monthly_fixed",
                target_day=1,
                lookahead_days=5,
            )
            inserted += 1
    if inserted:
        log.info("Seeded %d default attribution rules", inserted)
    return inserted
