"""
v41: Investment-details key-value table for per-account scrape output.

Phase 15-T09 captures per-account investment metadata from Fidelity
(SPAXX 7-day SEC yield + per-ETF YTD return), TSP (per-fund YTD return
across G/F/C/S/I + every L-vintage), and Acorns (round-ups invested
plus per-ETF YTD return for the auto-allocated portfolio). The shape
mirrors ``loan_details`` — narrow KV time series, one row per
(account, fund, field, refresh_run_id) — with one extra dimension:
``fund_ticker``. ``fund_ticker IS NULL`` denotes an account-level row
(Acorns round-ups); a non-null ticker scopes the field to a specific
holding.

The unique index uses ``COALESCE(fund_ticker,'')`` because SQLite
treats ``NULL ≠ NULL`` and would otherwise let two account-level
writes for the same (account, field, refresh_run_id) coexist.

Invariants are enforced in ``dal.investment_details.record_investment_details``
rather than at the schema layer (same convention as apy_history).
"""

VERSION = 41


def run(conn):
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS investment_details (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id      TEXT    NOT NULL REFERENCES accounts(id)
                                    ON DELETE CASCADE,
            fund_ticker     TEXT,
            field_name      TEXT    NOT NULL,
            field_value     TEXT,
            as_of           TEXT    NOT NULL,
            refresh_run_id  INTEGER,
            created_at      TEXT    DEFAULT (datetime('now'))
        )
        """
    )

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_investment_details_account "
        "ON investment_details(account_id, as_of DESC)"
    )

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_investment_details_fund "
        "ON investment_details(account_id, fund_ticker, field_name, as_of DESC)"
    )

    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_investment_details_unique "
        "ON investment_details("
        "account_id, COALESCE(fund_ticker,''), field_name, refresh_run_id"
        ")"
    )
