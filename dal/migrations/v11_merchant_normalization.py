"""Schema V10 — Merchant normalization: add merchant column to transactions + merchant_snapshots table."""

VERSION = 10

_DDL = """
-- Normalized merchant name on transactions (backfilled by merchant_normalizer)
ALTER TABLE transactions ADD COLUMN merchant TEXT;

-- Pre-aggregated merchant spend by month for fast reads
CREATE TABLE IF NOT EXISTS merchant_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant     TEXT    NOT NULL,
    month        TEXT    NOT NULL,     -- YYYY-MM
    category     TEXT,                -- dominant category for this merchant/month
    total_amount REAL    NOT NULL DEFAULT 0,
    tx_count     INTEGER NOT NULL DEFAULT 0,
    computed_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(merchant, month)
);
CREATE INDEX IF NOT EXISTS idx_merch_snap_merchant ON merchant_snapshots(merchant);
CREATE INDEX IF NOT EXISTS idx_merch_snap_month    ON merchant_snapshots(month);
"""


def run(conn):
    # ALTER TABLE can't be in executescript when column already exists — guard it
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN merchant TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists — OK

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS merchant_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant     TEXT    NOT NULL,
            month        TEXT    NOT NULL,
            category     TEXT,
            total_amount REAL    NOT NULL DEFAULT 0,
            tx_count     INTEGER NOT NULL DEFAULT 0,
            computed_at  TEXT    DEFAULT (datetime('now')),
            UNIQUE(merchant, month)
        );
        CREATE INDEX IF NOT EXISTS idx_merch_snap_merchant ON merchant_snapshots(merchant);
        CREATE INDEX IF NOT EXISTS idx_merch_snap_month    ON merchant_snapshots(month);
    """)
