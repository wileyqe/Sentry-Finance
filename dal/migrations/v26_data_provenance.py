"""
v26: Add is_synthetic flag to institutions and accounts.

Provides a single, queryable field to distinguish real connector data
from synthetic/seeded data.  The institution-level column is the source
of truth; the accounts-level column is a denormalization so common
queries (transactions, balances, holdings) never need a JOIN back to
institutions just for provenance.

Backfill logic:
  - institutions.extraction_method = 'dummy' => is_synthetic = 1
  - accounts inherit from their parent institution
"""

VERSION = 26


def run(conn):
    cur = conn.cursor()

    # ── institutions ────────────────────────────────────────────────
    existing_inst = {
        row[1] for row in cur.execute("PRAGMA table_info(institutions)").fetchall()
    }
    if "is_synthetic" not in existing_inst:
        cur.execute(
            "ALTER TABLE institutions ADD COLUMN is_synthetic INTEGER DEFAULT 0"
        )

    # ── accounts ────────────────────────────────────────────────────
    existing_acct = {
        row[1] for row in cur.execute("PRAGMA table_info(accounts)").fetchall()
    }
    if "is_synthetic" not in existing_acct:
        cur.execute(
            "ALTER TABLE accounts ADD COLUMN is_synthetic INTEGER DEFAULT 0"
        )

    # ── backfill from existing extraction_method marker ─────────────
    cur.execute(
        "UPDATE institutions SET is_synthetic = 1 "
        "WHERE extraction_method = 'dummy'"
    )
    cur.execute(
        "UPDATE accounts SET is_synthetic = 1 "
        "WHERE institution_id IN ("
        "  SELECT id FROM institutions WHERE is_synthetic = 1"
        ")"
    )

    conn.commit()
