import sqlite3
from datetime import datetime
from dal.reports import get_net_worth_history

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row

# create tables
conn.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY, type TEXT, is_active INTEGER)')
conn.execute('CREATE TABLE balance_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, as_of TEXT, balance REAL)')
conn.execute('CREATE TABLE portfolio_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, timestamp TEXT, total_account_value REAL, cash_balance REAL)')
conn.execute('CREATE TABLE real_estate (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, estimated_value REAL, as_of TEXT)')

# dummy data
conn.execute('INSERT INTO accounts VALUES ("acct1", "checking", 1)')
conn.execute('INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ("acct1", "2025-01-15", 1000)')
conn.execute('INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ("acct1", "2025-02-15", 2000)')
conn.execute('INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES ("acct1", "2025-03-15", 3000)')

# real estate dummy
conn.execute('INSERT INTO real_estate (name, estimated_value, as_of) VALUES ("123 Main St", 300000, "2025-01-10")')
conn.execute('INSERT INTO real_estate (name, estimated_value, as_of) VALUES ("123 Main St", 310000, "2025-02-10")')
conn.execute('INSERT INTO real_estate (name, estimated_value, as_of) VALUES ("123 Main St [zillow]", 320000, "2025-02-11")') # should be ignored
conn.execute('INSERT INTO real_estate (name, estimated_value, as_of) VALUES ("123 Main St", 330000, "2025-03-10")')

try:
    history = get_net_worth_history(conn, months=3)
    for h in history:
        print(f"Month: {h['month']}, RE: {h['real_estate_assets']}, Assets: {h['assets']}")
except Exception as e:
    print(f"Error: {e}")
