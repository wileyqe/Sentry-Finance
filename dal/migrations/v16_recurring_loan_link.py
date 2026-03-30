"""
V16 — Add linked_account_id to recurring_transactions for loan linking.

Links recurring payments to their source loan/liability accounts so the
forecaster can project when payments will stop (maturity date) and how
much cash flow will be freed.
"""

VERSION = 16


def run(conn):
    conn.executescript("""
        ALTER TABLE recurring_transactions
            ADD COLUMN linked_account_id TEXT;

        -- Index for fast lookup
        CREATE INDEX IF NOT EXISTS idx_recurring_linked
            ON recurring_transactions(linked_account_id);
    """)
