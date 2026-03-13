import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Ensure project root is on sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Set the DB path to a dummy database
os.environ["SENTRY_DB_PATH"] = str(Path(_PROJECT_ROOT) / "data" / "dummy.db")

from dal.database import init_db, get_db, seed_institutions
from dal.alerts import seed_default_rules
from dal.transactions import upsert_transactions
from dal.balances import record_balance

def seed_dummy_data():
    print("Initializing dummy database...")
    init_db()
    
    with get_db() as conn:
        # Create dummy owner to resolve FK constraints
        conn.execute("INSERT OR IGNORE INTO owners (id, display_name) VALUES (?, ?)", ("chang", "Chang"))
        conn.commit()

    seed_institutions()
    
    with get_db() as conn:
        seed_default_rules(conn)
        conn.commit()

    print("Seeding dummy balances...")
    now_iso = datetime.utcnow().isoformat()
    balances = {
        "nfcu_REDACTED": 2500.00,
        "nfcu_REDACTED": 850.50,
        "nfcu_REDACTED": -450.25,
        "nfcu_REDACTED": -18500.00,
        "nfcu_REDACTED": -350000.00,
        "chase_REDACTED": 12400.75,
        "chase_REDACTED": -120.00,
        "acorns_0000": 3450.80,
        "fidelity_REDACTED": 45000.00,
        "tsp_7777": 125000.00,
        "affirm_HYSA": 5000.00,
        "affirm_BNPL": -150.00
    }
    
    with get_db() as conn:
        for acct_id, amt in balances.items():
            record_balance(conn, acct_id, amt, as_of=now_iso)
        conn.commit()

    print("Seeding dummy transactions...")
    now = datetime.utcnow()
    
    dummy_txns = [
        {
            "institution_id": "chase",
            "account_id": "chase_REDACTED",
            "posting_date": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
            "amount": -5.45,
            "signed_amount": -5.45,
            "direction": "outflow",
            "description": "Starbucks Store #1234",
            "category": "Coffee",
            "status": "posted"
        },
        {
            "institution_id": "chase",
            "account_id": "chase_REDACTED",
            "posting_date": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
            "amount": -1800.00,
            "signed_amount": -1800.00,
            "direction": "outflow",
            "description": "Landlord Properties LLC",
            "category": "Rent",
            "status": "posted"
        },
        {
            "institution_id": "nfcu",
            "account_id": "nfcu_REDACTED",
            "posting_date": (now - timedelta(days=3)).strftime("%Y-%m-%d"),
            "amount": -1299.00,
            "signed_amount": -1299.00,
            "direction": "outflow",
            "description": "Apple Store #567",
            "category": "Tech",
            "status": "posted"
        },
        {
            "institution_id": "chase",
            "account_id": "chase_REDACTED",
            "posting_date": (now - timedelta(days=4)).strftime("%Y-%m-%d"),
            "amount": -82.30,
            "signed_amount": -82.30,
            "direction": "outflow",
            "description": "Whole Foods Market",
            "category": "Groceries",
            "status": "posted"
        },
        {
            "institution_id": "nfcu",
            "account_id": "nfcu_REDACTED",
            "posting_date": (now - timedelta(days=5)).strftime("%Y-%m-%d"),
            "amount": -45.00,
            "signed_amount": -45.00,
            "direction": "outflow",
            "description": "Shell Gas Station",
            "category": "Fuel",
            "status": "posted"
        },
        {
            "institution_id": "chase",
            "account_id": "chase_REDACTED",
            "posting_date": (now - timedelta(days=6)).strftime("%Y-%m-%d"),
            "amount": -15.99,
            "signed_amount": -15.99,
            "direction": "outflow",
            "description": "Netflix.com",
            "category": "Entertainment",
            "status": "posted"
        },
        {
            "institution_id": "chase",
            "account_id": "chase_REDACTED",
            "posting_date": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
            "amount": 3500.00,
            "signed_amount": 3500.00,
            "direction": "inflow",
            "description": "Acme Corp Payroll",
            "category": "Income",
            "status": "posted"
        }
    ]

    with get_db() as conn:
        upsert_transactions(conn, dummy_txns)
        conn.commit()
        
    print(f"Database seeded successfully at {os.environ['SENTRY_DB_PATH']}")

if __name__ == "__main__":
    seed_dummy_data()
