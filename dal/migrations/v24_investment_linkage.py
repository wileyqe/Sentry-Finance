"""V24 — Investment linkage columns.

Adds provenance and cross-reference columns so the pipeline can track
where each positions_ledger entry came from (scraper / statement / seeder)
and link bank-side Acorns debits to the share purchases they funded.

New columns:
  positions_ledger.source       — 'scraper', 'statement', or 'seeder'
  positions_ledger.bank_txn_id  — FK to transactions.id (nullable)
  transactions.investment_link  — reverse pointer to positions_ledger (nullable)
"""

VERSION = 24


def run(conn):
    # ── positions_ledger: provenance tracking ────────────────────────
    conn.execute(
        "ALTER TABLE positions_ledger ADD COLUMN source TEXT DEFAULT 'scraper'"
    )

    # ── positions_ledger: link to the bank transaction that funded this buy
    conn.execute(
        "ALTER TABLE positions_ledger ADD COLUMN bank_txn_id TEXT"
    )

    # ── transactions: reverse pointer to positions_ledger entries
    conn.execute(
        "ALTER TABLE transactions ADD COLUMN investment_link TEXT"
    )
