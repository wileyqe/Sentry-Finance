"""
dal/database.py — SQLite connection, WAL mode, schema management.

Single-file database at data/sentry.db with:
  - WAL mode for concurrent reads during writes
  - Schema versioning via PRAGMA user_version
  - Auto-migration on init
"""

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("sentry.dal")

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "sentry.db"

# Current schema version — bump when adding migrations
SCHEMA_VERSION = 2


# ── Schema DDL ───────────────────────────────────────────────────────────────

_SCHEMA_V1 = """
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

_SCHEMA_V2 = """
-- Portfolio Snapshots (Top-line tracking)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          TEXT NOT NULL REFERENCES accounts(id),
    timestamp           TEXT NOT NULL,
    total_account_value REAL,
    cash_balance        REAL,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_port_snap_account_date
    ON portfolio_snapshots(account_id, timestamp);

-- Positions Ledger (Delta-Logging transaction history)
CREATE TABLE IF NOT EXISTS positions_ledger (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id                  TEXT NOT NULL REFERENCES accounts(id),
    timestamp                   TEXT NOT NULL,
    ticker                      TEXT NOT NULL,
    transaction_type            TEXT NOT NULL,
    share_delta                 REAL NOT NULL,
    new_total_shares            REAL NOT NULL,
    yfinance_closing_price      REAL,
    estimated_transaction_value REAL,
    created_at                  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pos_ledger_account_ticker
    ON positions_ledger(account_id, ticker);
"""


# ── Connection Management ────────────────────────────────────────────────────


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Create a connection with WAL mode and foreign keys enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Initialize the database schema if needed."""
    conn = _connect(db_path)
    try:
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]

        if current_version < 1:
            log.info("Initializing database schema v1 at %s", db_path)
            conn.executescript(_SCHEMA_V1)
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
            log.info("Database schema v1 ready")
            current_version = 1

        if current_version < 2:
            log.info("Migrating database schema to v2 at %s", db_path)
            conn.executescript(_SCHEMA_V2)
            conn.execute("PRAGMA user_version = 2")
            conn.commit()
            log.info("Database schema v2 ready")
            current_version = 2

        if current_version == SCHEMA_VERSION:
            log.debug("Database schema v%d already current", current_version)

    finally:
        conn.close()


@contextmanager
def get_db(db_path: Path = DB_PATH):
    """Context manager yielding a database connection.

    Usage:
        with get_db() as conn:
            conn.execute("SELECT ...")
    """
    conn = _connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def seed_institutions(db_path: Path = DB_PATH) -> None:
    """Seed the institutions table from accounts.yaml if empty."""
    import yaml

    accounts_file = BASE_DIR / "accounts.yaml"
    if not accounts_file.exists():
        log.warning("accounts.yaml not found, skipping seed")
        return

    with open(accounts_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Institution metadata
    _INST_META = {
        "nfcu": {
            "display_name": "Navy Federal Credit Union",
            "login_url": "https://www.navyfederal.org/signin/",
            "refresh_interval_hours": 4,
            "mfa_expected": "sms",
            "extraction_method": "csv",
        },
        "chase": {
            "display_name": "Chase",
            "login_url": "https://www.chase.com/",
            "refresh_interval_hours": 4,
            "mfa_expected": "app",
            "extraction_method": "csv",
        },
        "acorns": {
            "display_name": "Acorns",
            "login_url": "https://app.acorns.com/login",
            "refresh_interval_hours": 24,  # Run daily after market close
            "mfa_expected": "sms",
            "extraction_method": "scrape",
        },
        "fidelity": {
            "display_name": "Fidelity",
            "login_url": "https://www.fidelity.com/",
            "refresh_interval_hours": 24,
            "mfa_expected": "totp",
            "extraction_method": "csv_import",
        },
    }

    with get_db(db_path) as conn:
        for inst_id, accounts in data.items():
            meta = _INST_META.get(inst_id, {})
            conn.execute(
                """
                INSERT OR IGNORE INTO institutions (id, display_name,
                    login_url, refresh_interval_hours, mfa_expected,
                    extraction_method)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    inst_id,
                    meta.get("display_name", inst_id),
                    meta.get("login_url"),
                    meta.get("refresh_interval_hours", 4),
                    meta.get("mfa_expected", "none"),
                    meta.get("extraction_method", "scrape"),
                ),
            )

            for acct in accounts:
                acct_id = f"{inst_id}_{acct['last4']}"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO accounts
                        (id, institution_id, name, last4, type)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        acct_id,
                        inst_id,
                        acct["name"],
                        acct["last4"],
                        acct.get("type", "unknown"),
                    ),
                )

            # Seed refresh status
            conn.execute(
                """
                INSERT OR IGNORE INTO institution_refresh_status
                    (institution_id)
                VALUES (?)
            """,
                (inst_id,),
            )

        conn.commit()
        log.info("Seeded %d institutions and their accounts", len(data))
