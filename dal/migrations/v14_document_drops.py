VERSION = 14

def run(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS document_drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name    TEXT NOT NULL,
            parser_type  TEXT NOT NULL,    -- 'tsp_statement', 'mypay_ras', 'unknown', etc.
            file_size    INTEGER,
            dropped_at   TEXT DEFAULT (datetime('now')),
            committed_at TEXT,             -- NULL until user confirms
            summary_json TEXT              -- JSON blob of what was parsed/committed
        );
    """)
