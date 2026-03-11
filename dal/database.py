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
SCHEMA_VERSION = 10


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

_SCHEMA_V3 = """
-- Investment Holdings (daily per-ticker positions)
CREATE TABLE IF NOT EXISTS investment_holdings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    date            TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    shares          REAL NOT NULL,
    close_price     REAL,
    market_value    REAL,
    cost_basis      REAL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(account_id, date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_inv_hold_account_date
    ON investment_holdings(account_id, date);
CREATE INDEX IF NOT EXISTS idx_inv_hold_ticker
    ON investment_holdings(account_id, ticker, date);

-- Real Estate (property valuations for net worth)
CREATE TABLE IF NOT EXISTS real_estate (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    estimated_value REAL NOT NULL,
    linked_loan_id  TEXT REFERENCES accounts(id),
    source          TEXT DEFAULT 'manual',
    as_of           TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""

# V3 ALTER — add transfer_tag to transactions (cannot be in executescript)
_SCHEMA_V3_ALTER = "ALTER TABLE transactions ADD COLUMN transfer_tag TEXT"

# ── Schema V4: Fractional-Share Precision Columns ──────────────────────────
# SQLite's REAL (IEEE 754 double) is exact for whole-dollar amounts but loses
# precision at 6+ decimal places — problematic for TSP/Acorns share counts.
# Strategy: add TEXT columns that store exact decimal strings and use
# decimal.Decimal in Python. The old REAL columns are kept for zero-downtime
# compatibility; the DAL reads/writes the _dec columns going forward.

_SCHEMA_V4_ALTERS = [
    # investment_holdings
    "ALTER TABLE investment_holdings ADD COLUMN shares_dec      TEXT",
    "ALTER TABLE investment_holdings ADD COLUMN close_price_dec TEXT",
    "ALTER TABLE investment_holdings ADD COLUMN market_value_dec TEXT",
    "ALTER TABLE investment_holdings ADD COLUMN cost_basis_dec  TEXT",
    # positions_ledger
    "ALTER TABLE positions_ledger ADD COLUMN share_delta_dec       TEXT",
    "ALTER TABLE positions_ledger ADD COLUMN new_total_shares_dec  TEXT",
    "ALTER TABLE positions_ledger ADD COLUMN close_price_dec       TEXT",
    "ALTER TABLE positions_ledger ADD COLUMN txn_value_dec         TEXT",
]

# ── Schema V5: Ownership / Multi-User Views ────────────────────────────────
# Adds an `owners` table and an `owner_id` FK on `accounts` to support
# the Yours / Ours / Mine dashboard toggle.  NULL owner_id = shared ("ours").

_SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS owners (
    id           TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at   TEXT DEFAULT (datetime('now'))
);
"""

_SCHEMA_V5_ALTER = "ALTER TABLE accounts ADD COLUMN owner_id TEXT REFERENCES owners(id)"

# ── Schema V6: Category Overrides ──────────────────────────────────────
# Stores user correction overrides for transaction categories.
# Overrides take highest priority in the categorization engine.

_SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS category_overrides (
    txn_id       TEXT PRIMARY KEY REFERENCES transactions(id),
    category     TEXT NOT NULL,
    created_at   TEXT DEFAULT (datetime('now'))
);
"""

# ── Schema V7: Recurring Transaction Detection ─────────────────────
# Tracks detected recurring patterns (subscriptions, bills, income)
# and logs price mutations over time.

_SCHEMA_V7 = """
CREATE TABLE IF NOT EXISTS recurring_transactions (
    id              TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    merchant        TEXT NOT NULL,
    category        TEXT,
    frequency       TEXT NOT NULL,
    avg_interval    REAL NOT NULL,
    expected_amount REAL,
    amount_stable   INTEGER DEFAULT 0,
    last_amount     REAL,
    last_date       TEXT,
    next_expected   TEXT,
    occurrence_count INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'active',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recurring_mutations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recurring_id    TEXT NOT NULL REFERENCES recurring_transactions(id),
    old_amount      REAL,
    new_amount      REAL,
    detected_at     TEXT DEFAULT (datetime('now')),
    description     TEXT
);
"""

# ── Schema V8: Budgets ──────────────────────────────────────────────────
# Monthly spending targets per category. Ownership-aware.

_SCHEMA_V8 = """
CREATE TABLE IF NOT EXISTS budgets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category        TEXT NOT NULL,
    month           TEXT NOT NULL,
    target_amount   REAL NOT NULL,
    owner_id        TEXT REFERENCES owners(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(category, month, owner_id)
);
"""

# ── Schema V9: Spending Alerts ───────────────────────────────────────────────
# alert_rules: configurable threshold rules (budget_pct, large_txn, balance_low)
# alert_events: log of fired alerts with deduplication keys

_SCHEMA_V9 = """
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

# ── Schema V10: Goals, Benchmark Prices, Ticker Metadata ───────────────────────
# savings_goals   : Named financial goals with deadlines and linked accounts
# benchmark_prices: Daily close prices for market benchmarks (^GSPC, VTI, BND)
# ticker_metadata : Cached sector/industry/asset_class per ticker from yfinance

_SCHEMA_V10 = """
CREATE TABLE IF NOT EXISTS savings_goals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    target_amount       REAL NOT NULL,
    current_amount      REAL DEFAULT 0.0,
    deadline            TEXT,
    linked_account_id   TEXT REFERENCES accounts(id),
    owner_id            TEXT REFERENCES owners(id),
    status              TEXT DEFAULT 'active',
    notes               TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS benchmark_prices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    price_date  TEXT NOT NULL,
    close_price REAL NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, price_date)
);
CREATE INDEX IF NOT EXISTS idx_benchmark_ticker_date
    ON benchmark_prices(ticker, price_date);

CREATE TABLE IF NOT EXISTS ticker_metadata (
    ticker       TEXT PRIMARY KEY,
    sector       TEXT,
    industry     TEXT,
    asset_class  TEXT,
    last_updated TEXT DEFAULT (date('now'))
);
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

        if current_version < 3:
            log.info("Migrating database schema to v3 at %s", db_path)
            conn.executescript(_SCHEMA_V3)
            # ALTER TABLE can't be in executescript with IF NOT EXISTS,
            # so check if column already exists first
            cols = [
                r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()
            ]
            if "transfer_tag" not in cols:
                conn.execute(_SCHEMA_V3_ALTER)
            conn.execute("PRAGMA user_version = 3")
            conn.commit()
            log.info("Database schema v3 ready")
            current_version = 3

        if current_version < 4:
            log.info(
                "Migrating database schema to v4 (fractional-share precision) at %s",
                db_path,
            )
            # Add TEXT precision columns for fractional share data.
            # Check each column before adding — safe to re-run.
            ih_cols = {
                r[1]
                for r in conn.execute(
                    "PRAGMA table_info(investment_holdings)"
                ).fetchall()
            }
            pl_cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(positions_ledger)").fetchall()
            }
            existing = ih_cols | pl_cols
            for stmt in _SCHEMA_V4_ALTERS:
                # Extract column name from "ALTER TABLE x ADD COLUMN y TEXT"
                col_name = stmt.split()[-2]
                if col_name not in existing:
                    conn.execute(stmt)
            conn.execute("PRAGMA user_version = 4")
            conn.commit()
            log.info("Database schema v4 ready")
            current_version = 4

        if current_version < 5:
            log.info(
                "Migrating database schema to v5 (ownership) at %s",
                db_path,
            )
            conn.executescript(_SCHEMA_V5)
            # Add owner_id column to accounts if not present
            acct_cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(accounts)").fetchall()
            }
            if "owner_id" not in acct_cols:
                conn.execute(_SCHEMA_V5_ALTER)
            conn.execute("PRAGMA user_version = 5")
            conn.commit()
            log.info("Database schema v5 ready")
            current_version = 5

        if current_version < 6:
            log.info(
                "Migrating database schema to v6 (category overrides) at %s",
                db_path,
            )
            conn.executescript(_SCHEMA_V6)
            conn.execute("PRAGMA user_version = 6")
            conn.commit()
            log.info("Database schema v6 ready")
            current_version = 6

        if current_version < 7:
            log.info(
                "Migrating database schema to v7 (recurring transactions) at %s",
                db_path,
            )
            conn.executescript(_SCHEMA_V7)
            conn.execute("PRAGMA user_version = 7")
            conn.commit()
            log.info("Database schema v7 ready")
            current_version = 7

        if current_version < 8:
            log.info(
                "Migrating database schema to v8 (budgets) at %s",
                db_path,
            )
            conn.executescript(_SCHEMA_V8)
            conn.execute("PRAGMA user_version = 8")
            conn.commit()
            log.info("Database schema v8 ready")
            current_version = 8

        if current_version < 9:
            log.info(
                "Migrating database schema to v9 (spending alerts) at %s",
                db_path,
            )
            conn.executescript(_SCHEMA_V9)
            conn.execute("PRAGMA user_version = 9")
            conn.commit()
            log.info("Database schema v9 ready")
            current_version = 9

        if current_version < 10:
            log.info(
                "Migrating database schema to v10 (goals, benchmarks, ticker metadata) at %s",
                db_path,
            )
            conn.executescript(_SCHEMA_V10)
            conn.execute("PRAGMA user_version = 10")
            conn.commit()
            log.info("Database schema v10 ready")
            current_version = 10

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


def seed_institutions(db_path: Path = DB_PATH) -> None:  # noqa: C901
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
        "tsp": {
            "display_name": "Thrift Savings Plan",
            "login_url": "https://www.tsp.gov/",
            "refresh_interval_hours": 24,
            "mfa_expected": "none",
            "extraction_method": "statement_api",
        },
        "affirm": {
            "display_name": "Affirm",
            "login_url": "https://www.affirm.com/user/signin",
            "refresh_interval_hours": 48,
            "mfa_expected": "sms",
            "extraction_method": "scrape",
        },
    }

    with get_db(db_path) as conn:
        # Seed owners first (FK target for accounts.owner_id)
        try:
            from dal.owners import seed_owners
            seed_owners(conn)
        except Exception as e:
            log.warning("Could not seed owners: %s", e)

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
                owner_id = acct.get("owner", None)
                conn.execute(
                    """
                    INSERT INTO accounts
                        (id, institution_id, name, last4, type, owner_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(institution_id, last4) DO UPDATE
                        SET owner_id = COALESCE(excluded.owner_id, accounts.owner_id)
                """,
                    (
                        acct_id,
                        inst_id,
                        acct["name"],
                        acct["last4"],
                        acct.get("type", "unknown"),
                        owner_id,
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

