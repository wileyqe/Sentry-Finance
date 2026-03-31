import sqlite3
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from dal.derived import compute_dti_ratio

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row

# create tables
conn.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY, name TEXT, type TEXT, is_active INTEGER)')
conn.execute('CREATE TABLE transactions (id TEXT, account_id TEXT, status TEXT, posting_date TEXT, signed_amount REAL, category TEXT, transfer_tag TEXT)')
conn.execute('CREATE TABLE derived_summaries (scope TEXT, metric TEXT, period TEXT, value REAL, computed_at TEXT, UNIQUE(scope, metric, period))')

# dummy accounts
conn.execute('INSERT INTO accounts VALUES ("acct1", "Checking 123", "checking", 1)')
conn.execute('INSERT INTO accounts VALUES ("acct2", "Savings 456", "savings", 1)')
conn.execute('INSERT INTO accounts VALUES ("acct3", "Credit 789", "credit_card", 1)')
conn.execute('INSERT INTO accounts VALUES ("acct4", "Affirm Loan", "loan", 1)')

# Income testing setup
# Let's say today is 2026-03-29. Current partial month is 2026-03.
months_dates = [
    (datetime.now(timezone.utc).replace(day=1) - relativedelta(months=1)).strftime('%Y-%m-%d'), # m1 = 2026-02
    (datetime.now(timezone.utc).replace(day=1) - relativedelta(months=2)).strftime('%Y-%m-%d')  # m2 = 2026-01
]

# Month 2: 2026-01
m2 = months_dates[1]
# Income: 10000 
conn.execute(f'INSERT INTO transactions VALUES ("t2_i", "acct1", "posted", ?, 10000, "Income", NULL)', (m2,))
# Mortgage: -2000
conn.execute(f'INSERT INTO transactions VALUES ("t2_m", "acct1", "posted", ?, -2000, "Mortgage", NULL)', (m2,))
# Auto Loan: -500
conn.execute(f'INSERT INTO transactions VALUES ("t2_a", "acct1", "posted", ?, -500, "Auto Loan", NULL)', (m2,))

# Month 1: 2026-02
m1 = months_dates[0]
# Income: 8000
conn.execute(f'INSERT INTO transactions VALUES ("t1_i", "acct1", "posted", ?, 8000, "Income", NULL)', (m1,))
# Mortgage: -2000
conn.execute(f'INSERT INTO transactions VALUES ("t1_m", "acct1", "posted", ?, -2000, "Mortgage", NULL)', (m1,))
# Auto Loan: -500
conn.execute(f'INSERT INTO transactions VALUES ("t1_a", "acct1", "posted", ?, -500, "Auto Loan", NULL)', (m1,))
# CC Payment (External): -100
conn.execute(f'INSERT INTO transactions VALUES ("t1_c", "acct1", "posted", ?, -100, "Credit Card Payments", NULL)', (m1,))
# Payment to external loan (positive on loan account type)
conn.execute(f'INSERT INTO transactions VALUES ("t1_l", "acct4", "posted", ?, 200, "Payment", NULL)', (m1,))
# Internal transfer (should be ignored due to transfer_tag)
conn.execute(f'INSERT INTO transactions VALUES ("t1_tr", "acct1", "posted", ?, -1000, "Transfer", "tag1")', (m1,))

try:
    results = compute_dti_ratio(conn, months=2)
    for r in results:
        print(f"Month: {r['month']}, Income: {r['gross_income']}, Debt: {r['debt_payments']}, DTI: {r['dti_ratio']}, Status: {r['status']}")
except Exception as e:
    print(f"Error: {e}")
