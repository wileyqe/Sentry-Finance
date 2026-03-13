"""Schema V9 — Spending alerts (configurable rules + event log)."""

VERSION = 9

_DDL = """
CREATE TABLE IF NOT EXISTS alert_rules (
    id          TEXT PRIMARY KEY,
    rule_type   TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'all',
    threshold   REAL NOT NULL,
    label       TEXT,
    enabled     INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alert_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id     TEXT NOT NULL REFERENCES alert_rules(id),
    context     TEXT NOT NULL,
    payload     TEXT,
    dedup_key   TEXT NOT NULL,
    fired_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(dedup_key)
);
CREATE INDEX IF NOT EXISTS idx_alert_events_fired
    ON alert_events(fired_at DESC);
"""


def run(conn):
    conn.executescript(_DDL)
