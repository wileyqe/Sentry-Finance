"""
Seed a fresh dummy database from the JSON files in dummy_data/.
Uses transactions_dense.json (the comprehensive 3-year set) instead of
the sparse transactions.json.
"""
import json
import os
import sys
import hashlib
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

DATA_DIR = os.path.join(_PROJECT_ROOT, "dummy_data")
DB_PATH  = os.path.join(_PROJECT_ROOT, "data", "dummy.db")

# Set env var BEFORE importing dal (dal.connection reads it at import time)
os.environ["SENTRY_DB_PATH"] = DB_PATH

from dal.database import init_db, get_db  # noqa: E402
from dal.merchant_normalizer import backfill_merchant_column, rebuild_merchant_snapshots  # noqa: E402

# ---------- helpers ----------

def _load(filename):
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)

def _tx_hash(tx):
    """Deterministic hash for a transaction row."""
    raw = f"{tx['account_id']}|{tx['date']}|{tx['amount']}|{tx['merchant']}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

# ---------- seeders ----------

def seed_accounts(conn):
    """Seed institutions + accounts from Institutions.json"""
    accounts = _load("Institutions.json")
    # Ensure institution rows exist
    seen_inst = set()
    for a in accounts:
        iid = a["institution_id"]
        if iid not in seen_inst:
            conn.execute(
                "INSERT OR IGNORE INTO institutions (id, display_name) VALUES (?, ?)",
                (iid, iid.title())
            )
            seen_inst.add(iid)
    # Insert accounts — last4 must be unique per institution_id
    # Use the account_id suffix after the type prefix (e.g. chase_chk_001 → chk1)
    for a in accounts:
        # Extract a unique last4: use last segment after last underscore
        parts = a["account_id"].split("_")
        # e.g. "chase_chk_001" → "chk1", "chase_cc_001" → "cc01"
        if len(parts) >= 3:
            last4 = (parts[1][:2] + parts[2][-2:]).ljust(4, "0")[:4]
        else:
            last4 = a["account_id"][-4:]
        conn.execute("""
            INSERT OR REPLACE INTO accounts
                (id, institution_id, name, last4, type, owner_id, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (a["account_id"], a["institution_id"], a["name"],
              last4, a["type"], "chang"))
    conn.commit()
    print(f"  ✓ {len(accounts)} accounts seeded")

def seed_current_balances(conn):
    """Store current balances from Institutions.json as latest balance_snapshots."""
    accounts = _load("Institutions.json")
    from datetime import datetime
    now_iso = datetime.utcnow().isoformat()
    for a in accounts:
        conn.execute("""
            INSERT INTO balance_snapshots (account_id, balance, as_of)
            VALUES (?, ?, ?)
        """, (a["account_id"], a["balance"], now_iso))
    conn.commit()
    print(f"  ✓ {len(accounts)} current balances seeded")

def seed_balance_snapshots(conn):
    """Historical balance snapshots (bi-monthly)."""
    data = _load("balance_snapshots.json")
    for row in data:
        conn.execute("""
            INSERT OR REPLACE INTO balance_snapshots
                (account_id, balance, as_of)
            VALUES (?, ?, ?)
        """, (row["account_id"], row["balance_amount"], row["date"]))
    conn.commit()
    print(f"  ✓ {len(data)} balance snapshots seeded")

def seed_transactions(conn):
    """Use the dense transactions file for realistic UI testing."""
    data = _load("transactions_dense.json")
    for tx in data:
        direction = "inflow" if tx["amount"] > 0 else "outflow"
        inst_id = tx["account_id"].split("_")[0]
        txn_hash = _tx_hash(tx)
        conn.execute("""
            INSERT OR REPLACE INTO transactions
                (id, institution_id, account_id, posting_date, amount,
                 signed_amount, direction, description, category, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (txn_hash, inst_id, tx["account_id"], tx["date"],
              tx["amount"], tx["amount"], direction,
              tx["merchant"], tx["category"], "posted"))
    conn.commit()
    print(f"  ✓ {len(data)} transactions seeded")

def seed_investment_holdings(conn):
    data = _load("Investment_holdings.json")
    for row in data:
        conn.execute("""
            INSERT OR REPLACE INTO investment_holdings
                (account_id, date, ticker, shares, close_price, market_value)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (row["account_id"], row["date"], row["ticker"],
              row["shares"], row["close_price"], row["market_value"]))
    conn.commit()
    print(f"  ✓ {len(data)} investment holdings seeded")

def seed_portfolio_snapshots(conn):
    data = _load("portfolio_snapshots.json")
    for row in data:
        conn.execute("""
            INSERT OR REPLACE INTO portfolio_snapshots
                (account_id, timestamp, total_account_value, cash_balance)
            VALUES (?, ?, ?, ?)
        """, (row["account_id"], row["timestamp"],
              row["total_account_value"], row["cash_balance"]))
    conn.commit()
    print(f"  ✓ {len(data)} portfolio snapshots seeded")

def seed_loan_details(conn):
    """loan_details uses a key-value schema: account_id, field_name, field_value."""
    data = _load("loan_details.json")
    for row in data:
        for field in ["interest_rate", "minimum_payment", "origination_date",
                      "due_date_day", "purchase_price", "term_months"]:
            if field in row:
                conn.execute("""
                    INSERT OR REPLACE INTO loan_details
                        (account_id, field_name, field_value, as_of)
                    VALUES (?, ?, ?, datetime('now'))
                """, (row["account_id"], field, str(row[field])))
    conn.commit()
    print(f"  ✓ {len(data)} loan detail records seeded")

def seed_budgets(conn):
    data = _load("budgets.json")
    for row in data:
        conn.execute("""
            INSERT OR REPLACE INTO budgets
                (category, target_amount, month, owner_id)
            VALUES (?, ?, ?, 'chang')
        """, (row["category"], row["target_amount"], row["month"]))
    conn.commit()
    print(f"  ✓ {len(data)} budget entries seeded")

def seed_recurring_transactions(conn):
    data = _load("recurring_transactions.json")
    for i, row in enumerate(data):
        rec_id = f"rec_{i:03d}"
        conn.execute("""
            INSERT OR REPLACE INTO recurring_transactions
                (id, account_id, merchant, category, expected_amount,
                 frequency, avg_interval, amount_stable, last_amount,
                 last_date, next_expected, occurrence_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 12, 'active')
        """, (rec_id, row["account_id"], row["merchant"], row["category"],
              row["expected_amount"], row["frequency"],
              30.0,  # avg_interval default
              row["expected_amount"],  # last_amount
              row["last_date"], row["next_date"]))
    conn.commit()
    print(f"  ✓ {len(data)} recurring transactions seeded")

def seed_savings_goals(conn):
    data = _load("savings_goals.json")
    for row in data:
        conn.execute("""
            INSERT OR REPLACE INTO savings_goals
                (name, target_amount, current_amount,
                 deadline, linked_account_id, owner_id, status)
            VALUES (?, ?, ?, ?, ?, 'chang', 'active')
        """, (row["name"], row["target_amount"], row["current_amount"],
              row["target_date"], row.get("linked_account_id")))
    conn.commit()
    print(f"  ✓ {len(data)} savings goals seeded")

# ---------- main ----------

def seed_dummy_data():
    # env var was already set at module level before dal import

    # Delete old dummy DB if it exists
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed old {DB_PATH}")

    print(f"Creating fresh dummy database at {DB_PATH}")
    init_db()

    with get_db() as conn:
        # Owner record (FK dependency)
        conn.execute(
            "INSERT OR IGNORE INTO owners (id, display_name) VALUES (?, ?)",
            ("chang", "Chang"))
        conn.commit()

        print("Seeding data from dummy_data/ JSON files...")
        seed_accounts(conn)
        seed_current_balances(conn)
        seed_balance_snapshots(conn)
        seed_transactions(conn)
        seed_investment_holdings(conn)
        seed_portfolio_snapshots(conn)
        seed_loan_details(conn)
        seed_budgets(conn)
        seed_recurring_transactions(conn)
        seed_savings_goals(conn)

        print("Normalizing merchant names...")
        n = backfill_merchant_column(conn)
        print(f"  ✓ {n} transactions normalized")
        print("Rebuilding merchant snapshots...")
        s = rebuild_merchant_snapshots(conn)
        print(f"  ✓ {s} merchant-month snapshots built")

    print(f"\n✅ Dummy database ready: {DB_PATH}")
    print("   Start backend with: set SENTRY_DB_PATH=data\\dummy.db && python backend\\api_server.py")

if __name__ == "__main__":
    seed_dummy_data()
