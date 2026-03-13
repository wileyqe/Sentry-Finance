"""Schema V4 — Fractional-share precision columns (TEXT-based decimals).

SQLite's REAL (IEEE 754 double) loses precision at 6+ decimal places —
problematic for TSP/Acorns share counts.  Strategy: add TEXT columns that
store exact decimal strings; Python reads/writes via decimal.Decimal.
Old REAL columns kept for zero-downtime compatibility.
"""

VERSION = 4

_ALTERS = [
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


def run(conn):
    ih_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(investment_holdings)").fetchall()
    }
    pl_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(positions_ledger)").fetchall()
    }
    existing = ih_cols | pl_cols
    for stmt in _ALTERS:
        # Extract column name: "ALTER TABLE x ADD COLUMN y TEXT"
        col_name = stmt.split()[-2]
        if col_name not in existing:
            conn.execute(stmt)
