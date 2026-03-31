import sqlite3
from datetime import datetime, timezone
from dal.derived import recompute_account_metrics

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row
conn.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY)')
conn.execute('CREATE TABLE transactions (id TEXT, account_id TEXT, status TEXT, posting_date TEXT, signed_amount REAL, category TEXT, transfer_tag TEXT)')
conn.execute('CREATE TABLE derived_summaries (scope TEXT, metric TEXT, period TEXT, value REAL, computed_at TEXT, UNIQUE(scope, metric, period))')

conn.execute('INSERT INTO accounts VALUES ("test_acct")')

now = datetime.now(timezone.utc)
current_month = now.strftime('%Y-%m')
current_date = now.strftime('%Y-%m-%d')

# Spending 1: Valid spend
conn.execute('INSERT INTO transactions VALUES ("1", "test_acct", "posted", ?, -100.0, "Groceries", NULL)', (current_date,))
# Spending 2: Transfer (should be ignored)
conn.execute('INSERT INTO transactions VALUES ("2", "test_acct", "posted", ?, -50.0, "Transfer", "some_tag")', (current_date,))
# Spending 3: Income category (should be ignored for spend)
conn.execute('INSERT INTO transactions VALUES ("3", "test_acct", "posted", ?, -20.0, "Paycheck", NULL)', (current_date,))

# Income 1: Valid income
conn.execute('INSERT INTO transactions VALUES ("4", "test_acct", "posted", ?, 200.0, "Paycheck", NULL)', (current_date,))
# Income 2: Positive refund (should be ignored because category isn''t income)
conn.execute('INSERT INTO transactions VALUES ("5", "test_acct", "posted", ?, 10.0, "Shopping", NULL)', (current_date,))

recompute_account_metrics(conn, 'test_acct')

spend = conn.execute('SELECT value FROM derived_summaries WHERE metric="monthly_spending" AND period=?', (current_month,)).fetchone()
income = conn.execute('SELECT value FROM derived_summaries WHERE metric="monthly_income" AND period=?', (current_month,)).fetchone()

print(f"Spend (expected 100.0): {spend['value']}")
print(f"Income (expected 200.0): {income['value']}")
