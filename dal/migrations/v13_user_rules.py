"""
dal/migrations/v13_user_rules.py — Schema migration for user categorization rules.
"""

import sqlite3

VERSION = 13

def run(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_categorization_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            merchant_name TEXT NOT NULL,
            match_type TEXT NOT NULL,          -- "exact_amount", "amount_range", "description"
            match_amount REAL,                 -- for exact_amount matching
            match_tolerance REAL DEFAULT 2.0,  -- for exact_amount: +/- tolerance
            match_min_amount REAL,             -- for amount_range matching
            match_max_amount REAL,             -- for amount_range matching
            match_pattern TEXT,                -- for description matching (regex)
            source_account_id TEXT,            -- optional: only match in this account
            is_recurring INTEGER DEFAULT 0,    -- user marked this as recurring
            occurrence_count INTEGER DEFAULT 0,-- how many times this rule has matched
            created_from_txn_id TEXT,          -- the transaction that spawned this rule
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
