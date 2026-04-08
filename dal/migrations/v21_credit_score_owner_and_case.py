"""V21 — Add owner_id to credit_scores; lowercase all owner_id values.

Two related changes bundled into one migration:

1. Adds an ``owner_id`` column to ``credit_scores`` so the per-owner
   dashboard view can filter scores. Existing rows retain NULL until
   the next seed/refresh writes the value.

2. Canonicalises every owner_id column in the database to lowercase
   so the case-sensitive SQLite text comparisons used by
   ``dal.owners.resolve_owner_account_ids`` produce consistent results
   regardless of where the data originated (config vs. seeder vs.
   manual entry).
"""

VERSION = 21


def run(conn):
    # ── 1. Add owner_id column to credit_scores ──────────────────────────
    cols = [r[1] for r in conn.execute("PRAGMA table_info(credit_scores)")]
    if "owner_id" not in cols:
        conn.execute(
            "ALTER TABLE credit_scores ADD COLUMN owner_id TEXT REFERENCES owners(id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_credit_score_owner "
            "ON credit_scores(owner_id, score_date DESC)"
        )

    # ── 2. Canonicalise all owner_id values to lowercase ─────────────────
    # Order matters only insofar as the FK chain stays consistent: we
    # update the owners table FIRST, then any rows that reference it.
    # SQLite ON UPDATE CASCADE is not declared on these FKs, so we update
    # both ends explicitly.
    conn.execute("UPDATE owners SET id = LOWER(id) WHERE id != LOWER(id)")

    for table, column in [
        ("accounts", "owner_id"),
        ("transactions", "owner_id"),
        ("budgets", "owner_id"),
        ("credit_scores", "owner_id"),
        ("recurring_patterns", "owner_id"),
    ]:
        try:
            conn.execute(
                f"UPDATE {table} SET {column} = LOWER({column}) "
                f"WHERE {column} IS NOT NULL AND {column} != LOWER({column})"
            )
        except Exception:
            # Tables/columns that don't exist yet (older DBs) — safe to skip;
            # later migrations will create them with the canonical case.
            pass
