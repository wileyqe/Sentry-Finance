"""
v25: Extend positions_ledger with cost-basis and trade-detail columns.

Supports Fidelity-style individual equity tracking:
  - cost_basis_dec: what was paid for shares in a BUY (qty × price + fees)
  - realized_gain_dec: gain/loss on SELL entries (proceeds − FIFO cost basis)
  - settlement_date: T+1 settlement, relevant for wash-sale tracking
  - commission_dec, fees_dec: part of IRS cost basis calculation
"""

VERSION = 25


def run(conn):
    cur = conn.cursor()

    # Check which columns already exist (idempotent)
    existing = {
        row[1]
        for row in cur.execute("PRAGMA table_info(positions_ledger)").fetchall()
    }

    new_cols = [
        ("cost_basis_dec", "TEXT"),
        ("realized_gain_dec", "TEXT"),
        ("settlement_date", "TEXT"),
        ("commission_dec", "TEXT"),
        ("fees_dec", "TEXT"),
    ]

    for col_name, col_type in new_cols:
        if col_name not in existing:
            cur.execute(
                f"ALTER TABLE positions_ledger ADD COLUMN {col_name} {col_type}"
            )

    conn.commit()
