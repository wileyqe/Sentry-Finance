VERSION = 15


def run(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS payroll_snapshots (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            pay_period       TEXT NOT NULL,    -- YYYY-MM of the pay period
            source           TEXT NOT NULL,    -- 'mypay_ras', 'manual'
            gross_pay        REAL,
            federal_tax      REAL,
            state_tax        REAL,
            sbp_premium      REAL,
            health_insurance REAL,             -- TRICARE / health plan
            dental_vision    REAL,
            other_deductions REAL,             -- catch-all for other line items
            net_pay          REAL,
            raw_json         TEXT,             -- full extracted field dict as JSON
            created_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(pay_period, source)
                ON CONFLICT REPLACE
        );
    """)
