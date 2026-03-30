"""Schema V17 — Credit score history table."""

VERSION = 17

_DDL = """
CREATE TABLE IF NOT EXISTS credit_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    score           INTEGER NOT NULL,
    score_type      TEXT NOT NULL,       -- 'FICO' or 'VantageScore'
    source          TEXT NOT NULL,       -- 'TransUnion', 'Experian', etc.
    institution_id  TEXT NOT NULL REFERENCES institutions(id),
    score_date      TEXT NOT NULL,       -- YYYY-MM-DD when score was computed
    factors         TEXT,                -- JSON array of key factors (optional)
    as_of           TEXT NOT NULL DEFAULT (datetime('now')),
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_credit_score_date
    ON credit_scores(score_date DESC);
CREATE INDEX IF NOT EXISTS idx_credit_score_institution
    ON credit_scores(institution_id, score_date DESC);
"""

def run(conn):
    conn.executescript(_DDL)
