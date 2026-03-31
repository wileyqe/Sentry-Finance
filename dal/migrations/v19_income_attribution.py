"""Schema V19 — Income attribution: effective_month column + attribution rules table.

Adds an `effective_month` column to transactions so that government income
(Military Pension, VA Disability, VA Education Benefits) that posts early
(1-3 business days before the 1st) can be attributed to the correct month.

Also creates the `income_attribution_rules` table for category-based,
schedule-aware attribution rules.
"""

VERSION = 19

_DDL = """
-- New column: which month this transaction's financial impact belongs to.
-- NULL = use posting_date month (default for all existing transactions).
-- Non-NULL = 'YYYY-MM' string overriding month grouping in reports.
ALTER TABLE transactions ADD COLUMN effective_month TEXT;

CREATE INDEX IF NOT EXISTS idx_txn_effective_month
    ON transactions(effective_month);

-- Attribution rules: category-based matching + schedule-aware date shift.
CREATE TABLE IF NOT EXISTS income_attribution_rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name       TEXT NOT NULL,
    match_category  TEXT NOT NULL,
    match_direction TEXT DEFAULT 'Credit',
    schedule_type   TEXT NOT NULL DEFAULT 'monthly_fixed',
    target_day      INTEGER NOT NULL DEFAULT 1,
    lookahead_days  INTEGER NOT NULL DEFAULT 5,
    owner           TEXT DEFAULT 'self',
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""


def run(conn):
    # ALTER TABLE can fail if column already exists; handle gracefully
    for stmt in _DDL.strip().split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            conn.execute(stmt)
        except Exception as e:
            if "duplicate column" in str(e).lower():
                continue
            raise
