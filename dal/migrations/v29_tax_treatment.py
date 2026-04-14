"""
v29: Tax treatment tracking for investment accounts.

Adds account-level tax_status (taxable, traditional, roth, mixed, hsa)
and a tax_buckets table for accounts like TSP that hold multiple tax
categories within a single account.

The TSP statement shows three internal buckets (Traditional, Roth,
Tax-exempt).  Tax-exempt is lumped with Roth for display purposes since
both represent already-taxed money.
"""

VERSION = 29


def run(conn):
    cur = conn.cursor()

    # 1. Add tax_status to accounts
    cur.execute(
        "ALTER TABLE accounts ADD COLUMN tax_status TEXT DEFAULT NULL"
    )

    # 2. Create tax_buckets table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tax_buckets (
            id          INTEGER PRIMARY KEY,
            account_id  TEXT    NOT NULL REFERENCES accounts(id),
            bucket_type TEXT    NOT NULL,   -- 'traditional', 'roth'
            balance     INTEGER NOT NULL,   -- cents
            vested_pct  REAL    DEFAULT 1.0,
            as_of       TEXT    NOT NULL,
            created_at  TEXT    DEFAULT (datetime('now')),
            UNIQUE(account_id, bucket_type, as_of)
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_tax_buckets_acct_date "
        "ON tax_buckets(account_id, as_of DESC)"
    )

    # 3. Backfill tax_status for known accounts
    cur.execute(
        "UPDATE accounts SET tax_status = 'mixed' "
        "WHERE id = 'tsp_synthetic_7777'"
    )
    cur.execute(
        "UPDATE accounts SET tax_status = 'taxable' "
        "WHERE id IN ('fidelity_REDACTED', 'fidelity_brokerage_5555', "
        "             'acorns_synthetic_0000')"
    )

    conn.commit()
