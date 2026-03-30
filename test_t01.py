import sqlite3
from datetime import datetime
from dateutil.relativedelta import relativedelta
from dal.derived import compute_emergency_fund_months

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row

# create tables
conn.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY, name TEXT, type TEXT, is_active INTEGER)')
conn.execute('CREATE TABLE balance_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, as_of TEXT, balance REAL)')
conn.execute('CREATE TABLE transactions (id TEXT, account_id TEXT, status TEXT, posting_date TEXT, signed_amount REAL, category TEXT, transfer_tag TEXT)')
conn.execute('CREATE TABLE derived_summaries (scope TEXT, metric TEXT, period TEXT, value REAL, computed_at TEXT, UNIQUE(scope, metric, period))')

# dummy accounts
conn.execute('INSERT INTO accounts VALUES ("acct1", "Checking 123", "checking", 1)')
conn.execute('INSERT INTO accounts VALUES ("acct2", "Savings 456", "savings", 1)')
conn.execute('INSERT INTO accounts VALUES ("acct3", "Credit 789", "credit_card", 1)') # should be ignored
conn.execute('INSERT INTO accounts VALUES ("acct4", "Old Checking", "checking", 0)') # inactive, ignored

# dummy balances
conn.execute('INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ("acct1", "2026-03-25", 5000)')
conn.execute('INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ("acct2", "2026-03-20", 15000)')
conn.execute('INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ("acct3", "2026-03-20", 2000)') # ignored

# dummy spending for last 6 complete months
# Let's say today is 2026-03-29. Current partial month is 2026-03.
# Complete months are 2025-09 through 2026-02.
for m in range(1, 7):
    # m=1 -> 2026-02, m=6 -> 2025-09
    month_date = (datetime.utcnow().replace(day=1) - relativedelta(months=m)).strftime('%Y-%m-%d')
    # Valid spend: 2000
    conn.execute(f'INSERT INTO transactions VALUES ("t{m}a", "acct1", "posted", ?, -2000, "Groceries", NULL)', (month_date,))
    # Invalid spend (income category): -500
    conn.execute(f'INSERT INTO transactions VALUES ("t{m}b", "acct1", "posted", ?, -500, "Tax Refund", NULL)', (month_date,))
    # Invalid spend (transfer): -1000
    conn.execute(f'INSERT INTO transactions VALUES ("t{m}c", "acct1", "posted", ?, -1000, "Transfer", "tag")', (month_date,))

# add partial month spend (should be ignored)
current_month = datetime.utcnow().strftime('%Y-%m-%d')
conn.execute(f'INSERT INTO transactions VALUES ("t_curr", "acct1", "posted", ?, -5000, "Groceries", NULL)', (current_month,))

try:
    result = compute_emergency_fund_months(conn)
    print(f"Liquid Balance (expected 20000.0): {result['liquid_balance']}")
    print(f"Avg Monthly Spending (expected 2000.0): {result['avg_monthly_spending']}")
    print(f"Months of Runway (expected 10.0): {result['months_of_runway']}")
    print(f"Liquid Accounts: {len(result['liquid_accounts'])} found")
except Exception as e:
    print(f"Error: {e}")
