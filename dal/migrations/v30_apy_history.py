"""
v30: APY time-series table.

Before Phase 15 T04, Affirm's APY was stamped into ``loan_details`` as a
key-value row and overwritten on every refresh. Rate-shop decisions need
history, so APY now lives in its own narrow time-series table. NFCU
deposit-account APY scraping (also T04 Phase B) writes here too, as does
the future statement-import path.

Invariants (``apy_rate ∈ [0, 100]``, ``source`` in the three-value set,
ISO-8601 dates) are enforced in ``dal.apy_history.record_apy_history``
rather than at the schema layer — same convention as credit_scores and
real_estate.
"""

VERSION = 30


def run(conn):
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS apy_history (
            id         INTEGER PRIMARY KEY,
            account_id TEXT    NOT NULL REFERENCES accounts(id),
            apy_rate   REAL    NOT NULL,
            as_of      TEXT    NOT NULL,
            source     TEXT    NOT NULL,
            created_at TEXT    DEFAULT (datetime('now')),
            UNIQUE(account_id, as_of, source)
        )
    """)

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_apy_history_acct_date "
        "ON apy_history(account_id, as_of DESC)"
    )
