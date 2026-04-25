"""
v38: Add ``notifications`` table for the Phase 16 notification feed.

Stores all producer-emitted notifications (refresh failures, budget alerts,
upcoming/overdue bills, doc-drop nudges) in a single persistent surface the
header bell can query. Dismissal and read state are two separate timestamps
so the badge can zero independently of the user removing an entry.

Idempotent via ``CREATE TABLE IF NOT EXISTS``.
"""

VERSION = 38


def run(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id           INTEGER PRIMARY KEY,
            type         TEXT NOT NULL,
            severity     TEXT NOT NULL DEFAULT 'info',
            title        TEXT NOT NULL,
            body         TEXT,
            payload_json TEXT,
            link         TEXT,
            dedup_key    TEXT NOT NULL UNIQUE,
            created_at   TEXT NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            read_at      TEXT,
            dismissed_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notifications_active
            ON notifications(created_at DESC)
            WHERE dismissed_at IS NULL
        """
    )
