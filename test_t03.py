import sqlite3
from datetime import datetime, timezone
from dal.derived import compute_interest_cost

current_year = datetime.now(timezone.utc).strftime("%Y")

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row

# create tables
conn.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY, name TEXT, type TEXT, is_active INTEGER)')
conn.execute('CREATE TABLE transactions (id TEXT, account_id TEXT, status TEXT, posting_date TEXT, signed_amount REAL, category TEXT, transfer_tag TEXT, description TEXT)')
conn.execute('CREATE TABLE loan_details (account_id TEXT, field_name TEXT, field_value TEXT, as_of TEXT)')
conn.execute('CREATE TABLE derived_summaries (scope TEXT, metric TEXT, period TEXT, value REAL, computed_at TEXT, UNIQUE(scope, metric, period))')

# dummy accounts
conn.execute('INSERT INTO accounts VALUES ("acct1", "Auto Loan", "loan", 1)')
conn.execute('INSERT INTO accounts VALUES ("acct2", "Mortgage", "loan", 1)')
conn.execute('INSERT INTO accounts VALUES ("acct3", "Credit Card", "credit_card", 1)')
conn.execute('INSERT INTO accounts VALUES ("affirm_HYSA", "Savings", "savings", 1)')

# loan_details setup
# Auto Loan: Use exact match 'ytd_interest', value with $
conn.execute('INSERT INTO loan_details VALUES ("acct1", "ytd_interest", "$150.50", ?)', (f"{current_year}-03-01",))
# Mortgage: Use LIKE match 'Interest Paid YTD', value with % removed for fun
conn.execute('INSERT INTO loan_details VALUES ("acct2", "Interest Paid YTD", "500.00", ?)', (f"{current_year}-03-01",))
# CC: NO loan_details, should fallback to transactions

# transactions setup
# CC Interest: -25.00
conn.execute('INSERT INTO transactions VALUES ("t1", "acct3", "posted", ?, -25.00, "Interest Charge", NULL, "Interest")', (f"{current_year}-02-15",))
# CC normal spend (should be ignored):
conn.execute('INSERT INTO transactions VALUES ("t2", "acct3", "posted", ?, -100.00, "Groceries", NULL, "Walmart")', (f"{current_year}-02-15",))
# HYSA earned interest: +10.00
conn.execute('INSERT INTO transactions VALUES ("t3", "affirm_HYSA", "posted", ?, 10.00, "Interest", NULL, "Interest")', (f"{current_year}-02-28",))

try:
    result = compute_interest_cost(conn)
    print(f"YTD Total Interest Paid (expected 675.50): {result['ytd_total']}")
    print(f"Interest Earned (expected 10.0): {result['interest_earned']}")
    print(f"Net Interest (expected -665.50): {result['net_interest']}")
    print("By Account Details:")
    for a in result['by_account']:
        print(f"  {a['account_name']}: {a['ytd_interest']} (Source: {a['source']})")
    print("Monthly Breakdown:")
    for m in result['monthly_breakdown']:
        print(f"  {m['month']}: {m['total_interest']}")
except Exception as e:
    print(f"Error: {e}")
