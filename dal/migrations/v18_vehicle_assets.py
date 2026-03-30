"""Schema V18 — Vehicle assets and valuation history."""

VERSION = 18

_DDL = """
CREATE TABLE IF NOT EXISTS vehicle_assets (
    id                    TEXT PRIMARY KEY,  -- e.g. VIN or custom ID
    make                  TEXT NOT NULL,
    model                 TEXT NOT NULL,
    year                  INTEGER NOT NULL,
    purchase_date         TEXT,
    purchase_price        REAL,
    created_at            TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vehicle_valuations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id            TEXT NOT NULL REFERENCES vehicle_assets(id),
    valuation_date        TEXT NOT NULL,     -- YYYY-MM-DD
    estimated_value       REAL NOT NULL,
    source                TEXT,              -- e.g., 'KBB', 'Edmunds', 'Manual'
    source_url            TEXT,              -- Link to the valuation page
    as_of                 TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vehicle_val_date ON vehicle_valuations(vehicle_id, valuation_date DESC);
"""

def run(conn):
    conn.executescript(_DDL)
