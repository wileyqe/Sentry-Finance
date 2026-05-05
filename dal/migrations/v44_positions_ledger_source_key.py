"""v44: Add stable source keys for idempotent live investment ledger writes."""

VERSION = 44


def run(conn):
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(positions_ledger)").fetchall()
    }
    if "source_key" not in existing:
        conn.execute("ALTER TABLE positions_ledger ADD COLUMN source_key TEXT")

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_ledger_source_key
            ON positions_ledger(account_id, source, source_key)
            WHERE source_key IS NOT NULL
        """
    )
