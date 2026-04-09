"""V23 — Budgets become a household-only concept.

P12-T01 attributed every budget row to ``owner_id="quintin"``, which
broke the household view (queried ``owner_id IS NULL`` → no rows → YAML
fallback) and the per-owner views (Amy → YAML fallback). The intended
design is that budgets belong to the household, not to any owner.

This migration:

1. Deduplicates rows that share ``(category, month)``, keeping the most
   recently inserted row, so the backfill won't violate any uniqueness.
2. Backfills every remaining row's ``owner_id`` to NULL.
3. Adds a partial unique index on ``(category, month) WHERE owner_id IS
   NULL`` so future writes can't create duplicate household rows. The
   original ``UNIQUE(category, month, owner_id)`` constraint treats
   multiple NULLs as distinct in SQLite, so a partial index is needed
   to enforce single-row-per-month semantics now that ``owner_id`` is
   always NULL.
"""

VERSION = 23


def run(conn):
    # ── 1. Dedupe — keep only the highest id per (category, month) ───
    conn.execute(
        """
        DELETE FROM budgets
        WHERE id NOT IN (
            SELECT MAX(id) FROM budgets GROUP BY category, month
        )
        """
    )

    # ── 2. Backfill all remaining rows to NULL owner ─────────────────
    conn.execute(
        "UPDATE budgets SET owner_id = NULL WHERE owner_id IS NOT NULL"
    )

    # ── 3. Defense-in-depth: enforce one row per (category, month)
    #    for the household. SQLite treats multiple NULLs as distinct
    #    in a normal UNIQUE constraint, so we need a partial unique
    #    index to actually catch duplicate household writes.
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_budgets_household_unique
        ON budgets(category, month)
        WHERE owner_id IS NULL
        """
    )
