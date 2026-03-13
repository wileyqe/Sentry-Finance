"""Schema V1 — Core tables: institutions, accounts, transactions, balances, refresh tracking."""

VERSION = 1

_DDL = """
-- Institutions registry
CREATE TABLE IF NOT EXISTS institutions (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    login_url       TEXT,
    refresh_interval_hours INTEGER DEFAULT 4,
    max_retries     INTEGER DEFAULT 3,
    backoff_base_seconds INTEGER DEFAULT 60,
    mfa_expected    TEXT DEFAULT 'none',
    extraction_method TEXT DEFAULT 'scrape',
    health_score    REAL DEFAULT 1.0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Accounts
CREATE TABLE IF NOT EXISTS accounts (
    id              TEXT PRIMARY KEY,
    institution_id  TEXT NOT NULL REFERENCES institutions(id),
    name            TEXT NOT NULL,
    last4           TEXT NOT NULL,
    type            TEXT NOT NULL,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(institution_id, last4)
);

-- Transactions (source of truth)
CREATE TABLE IF NOT EXISTS transactions (
    id                  TEXT PRIMARY KEY,
    account_id          TEXT NOT NULL REFERENCES accounts(id),
    institution_id      TEXT NOT NULL REFERENCES institutions(id),
    posting_date        TEXT NOT NULL,
    transaction_date    TEXT,
    amount              REAL NOT NULL,
    signed_amount       REAL NOT NULL,
    direction           TEXT NOT NULL,
    description         TEXT,
    category            TEXT DEFAULT 'Uncategorized',
    status              TEXT DEFAULT 'posted',
    raw_description     TEXT,
    institution_txn_id  TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    refresh_run_id      TEXT
);
CREATE INDEX IF NOT EXISTS idx_txn_account_date
    ON transactions(account_id, posting_date);
CREATE INDEX IF NOT EXISTS idx_txn_institution
    ON transactions(institution_id);
CREATE INDEX IF NOT EXISTS idx_txn_status
    ON transactions(status);

-- Balance snapshots
CREATE TABLE IF NOT EXISTS balance_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    balance         REAL NOT NULL,
    as_of           TEXT NOT NULL,
    refresh_run_id  TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bal_account
    ON balance_snapshots(account_id, as_of);

-- Loan detail snapshots
CREATE TABLE IF NOT EXISTS loan_details (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    field_name      TEXT NOT NULL,
    field_value     TEXT,
    as_of           TEXT NOT NULL,
    refresh_run_id  TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Refresh runs (state machine durability)
CREATE TABLE IF NOT EXISTS refresh_runs (
    id              TEXT PRIMARY KEY,
    state           TEXT NOT NULL DEFAULT 'IDLE',
    started_at      TEXT,
    completed_at    TEXT,
    trigger         TEXT,
    error           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Per-institution refresh events within a run
CREATE TABLE IF NOT EXISTS refresh_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL REFERENCES refresh_runs(id),
    institution_id      TEXT NOT NULL REFERENCES institutions(id),
    state               TEXT NOT NULL,
    started_at          TEXT,
    completed_at        TEXT,
    txn_inserted        INTEGER DEFAULT 0,
    txn_updated         INTEGER DEFAULT 0,
    txn_deleted         INTEGER DEFAULT 0,
    balance_delta       REAL,
    error               TEXT,
    error_class         TEXT,
    retry_count         INTEGER DEFAULT 0,
    mfa_prompted        INTEGER DEFAULT 0,
    duration_seconds    REAL,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- Institution refresh status (latest view)
CREATE TABLE IF NOT EXISTS institution_refresh_status (
    institution_id      TEXT PRIMARY KEY REFERENCES institutions(id),
    last_success        TEXT,
    last_failure        TEXT,
    last_failure_reason TEXT,
    next_eligible       TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- Derived summaries (scoped recomputation)
CREATE TABLE IF NOT EXISTS derived_summaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope       TEXT NOT NULL,
    metric      TEXT NOT NULL,
    period      TEXT,
    value       REAL,
    computed_at TEXT DEFAULT (datetime('now')),
    UNIQUE(scope, metric, period)
);
"""


def run(conn):
    conn.executescript(_DDL)
