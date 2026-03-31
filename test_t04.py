import sqlite3
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from dal.derived import compute_net_worth_velocity

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row

# create tables
conn.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY, name TEXT, type TEXT, is_active INTEGER, institution_id TEXT)')
conn.execute('CREATE TABLE balance_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, as_of TEXT, balance REAL)')
conn.execute('CREATE TABLE portfolio_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, timestamp TEXT, total_account_value REAL)')
conn.execute('CREATE TABLE real_estate (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, estimated_value REAL)')
conn.execute('CREATE TABLE derived_summaries (scope TEXT, metric TEXT, period TEXT, value REAL, computed_at TEXT, UNIQUE(scope, metric, period))')

# dummy accounts
conn.execute('INSERT INTO accounts VALUES ("a1", "Bank", "checking", 1, "test")')

# Make 24 months of synthetic net worth data
# We'll slowly increment the balance, so it's accelerating
# We'll need to mock records so get_net_worth_history can pull them
# Wait, get_net_worth_history relies on multiple tables. 
# actually, it's easier to mock the get_net_worth_history function entirely...
# but computation is what we're testing. Let's patch `dal.reports.get_net_worth_history`
import dal.reports

def mock_get_net_worth_history(conn, months=24):
    history = []
    # oldest first
    for i in range(24-1, -1, -1):
        month_str = (datetime.now(timezone.utc) - relativedelta(months=i)).strftime('%Y-%m')
        # make net worth start at 10000, grow
        # Month 0 (24 months ago): 10,000
        # Month 11 (13 months ago): 16,000, etc.
        # Let's just do: nw = 10000 + (24-i)*1000
        nw = 10000 + (24-i) * 500
        # To make it "accelerating", let the recent months grow faster
        if i < 4:
            nw += (4-i) * 800
            
        history.append({
            "month": month_str,
            "assets": nw,
            "liabilities": 0,
            "net_worth": nw
        })
    return history

import dal.derived
dal.derived.get_net_worth_history = mock_get_net_worth_history

try:
    res = compute_net_worth_velocity(conn)
    print(f"Current Net Worth: {res['current_net_worth']}")
    print(f"MoM Change: {res['mom_change']} ({res['mom_pct']}%)")
    print(f"Rolling 3m Change: {res['rolling_3m_change']}, Avg: {res['rolling_3m_monthly_avg']}")
    print(f"Rolling 12m Change: {res['rolling_12m_change']}, Avg: {res['rolling_12m_monthly_avg']}")
    print(f"Trend: {res['trend']}")
    
    print("\nRecent History Check:")
    for h in res['history'][-5:]:
        print(h)
except Exception as e:
    import traceback
    traceback.print_exc()
