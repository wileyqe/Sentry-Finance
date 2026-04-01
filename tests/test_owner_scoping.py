"""
tests/test_owner_scoping.py — Multi-user Data Isolation Tests (Phase 7).

Validates that the DAL layers correctly filter data when an `owner_id` or `view` is requested.
"""

import sys
import tempfile
import os
from pathlib import Path

# Add project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
import dal.owners
from dal.owners import (
    create_owner,
    assign_account_owner,
    resolve_account_ids_for_view,
    resolve_owner_account_ids,
)
from dal.transactions import upsert_transactions, get_transactions
from dal.cash_flow import get_monthly_cash_flow
from dal.reports import get_spending_by_category, get_net_worth_history

def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)

_passed = 0
_failed = 0
_errors = []

def _check(name: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✔  {name}")
    else:
        _failed += 1
        msg = f"  ✗  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        _errors.append(name)


def test_owner_resolvers():
    print("\n─── Owner Resolvers (Phase 7) ───")
    db = _temp_db()
    dal.owners._config_cache = {"primary_owner": "mine", "owners": [{"id": "mine"}, {"id": "theirs"}]}
    try:
        init_db(db)
        with get_db(db) as conn:
            conn.execute("INSERT INTO institutions (id, display_name) VALUES ('instA', 'Bank A')")
            # Create accounts
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4) VALUES ('acct_mine', 'instA', 'My Checking', 'checking', '1111')")
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4) VALUES ('acct_theirs', 'instA', 'Their Checking', 'checking', '2222')")
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4) VALUES ('acct_ours', 'instA', 'Joint Checking', 'checking', '3333')")
            
            # Create owners and assign
            create_owner(conn, "mine", "Alice")
            create_owner(conn, "theirs", "Bob")
            
            assign_account_owner(conn, "acct_mine", "mine")
            assign_account_owner(conn, "acct_theirs", "theirs")
            # acct_ours left unassigned (owner_id IS NULL)
            
            conn.commit()

            # Test resolve_account_ids_for_view (legacy view behavior)
            v_mine = resolve_account_ids_for_view(conn, "mine")
            v_theirs = resolve_account_ids_for_view(conn, "theirs")
            v_ours = resolve_account_ids_for_view(conn, "ours")

            _check("View 'mine' includes mine + theirs", set(v_mine) == {"acct_mine", "acct_ours"}, f"Got {v_mine}")
            _check("View 'theirs' includes theirs + ours", set(v_theirs) == {"acct_theirs", "acct_ours"}, f"Got {v_theirs}")
            _check("View 'ours' includes all (None)", v_ours is None)

            # Test resolve_owner_account_ids (new P7 helper behavior)
            r_mine = resolve_owner_account_ids(conn, "mine")
            r_theirs = resolve_owner_account_ids(conn, "theirs")
            r_ours = resolve_owner_account_ids(conn, "ours")

            _check("Owner 'mine' resolves to set(mine, shared)", set(r_mine) == {"acct_mine", "acct_ours"})
            _check("Owner 'theirs' resolves to set(theirs, shared)", set(r_theirs) == {"acct_theirs", "acct_ours"})
            _check("Owner 'ours' / None resolves to all", r_ours is None)

    finally:
        os.remove(db)


def test_transaction_scoping():
    print("\n─── Transaction Scoping ───")
    db = _temp_db()
    dal.owners._config_cache = {"primary_owner": "mine"}
    try:
        init_db(db)
        with get_db(db) as conn:
            conn.execute("INSERT INTO institutions (id, display_name) VALUES ('instA', 'Bank A')")
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4) VALUES ('acct_A', 'instA', 'A', 'checking', '1111')")
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4) VALUES ('acct_B', 'instA', 'B', 'checking', '2222')")
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4) VALUES ('acct_S', 'instA', 'S', 'checking', '3333')")
            create_owner(conn, "mine", "Alice")
            create_owner(conn, "theirs", "Bob")
            assign_account_owner(conn, "acct_A", "mine")
            assign_account_owner(conn, "acct_B", "theirs")
            
            txns = [
                {"id": "txn1", "account_id": "acct_A", "amount": 100, "date": "2024-01-01"},
                {"id": "txn2", "account_id": "acct_B", "amount": 200, "date": "2024-01-01"},
                {"id": "txn3", "account_id": "acct_S", "amount": 300, "date": "2024-01-01"},
            ]
            
            for t in txns:
                dir = "outflow" if t["amount"] < 0 else "inflow"
                conn.execute(
                    "INSERT INTO transactions (id, institution_id, account_id, amount, signed_amount, direction, posting_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (t["id"], "instA", t["account_id"], abs(t["amount"]), t["amount"], dir, t["date"])
                )
            conn.commit()

            # Testing direct get_transactions
            all_txns = get_transactions(conn)
            mine_txns = get_transactions(conn, owner_id="mine")
            theirs_txns = get_transactions(conn, owner_id="theirs")

            _check("House view sees all txns", len(all_txns) == 3)
            _check("Mine view sees A+S txns", len(mine_txns) == 2 and sum(t["amount"] for t in mine_txns) == 400)
            _check("Theirs view sees B+S txns", len(theirs_txns) == 2 and sum(t["amount"] for t in theirs_txns) == 500)
    finally:
        os.remove(db)

def test_reports_scoping():
    print("\n─── Reports & Cash Flow Scoping ───")
    db = _temp_db()
    dal.owners._config_cache = {"primary_owner": "mine"}
    try:
        init_db(db)
        with get_db(db) as conn:
            conn.execute("INSERT INTO institutions (id, display_name) VALUES ('instA', 'Bank A')")
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4) VALUES ('acct_A', 'instA', 'A', 'checking', '1111')")
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4) VALUES ('acct_B', 'instA', 'B', 'checking', '2222')")
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4) VALUES ('acct_S', 'instA', 'S', 'checking', '3333')")
            create_owner(conn, "mine", "Alice")
            create_owner(conn, "theirs", "Bob")
            assign_account_owner(conn, "acct_A", "mine")
            assign_account_owner(conn, "acct_B", "theirs")

            txns = [
                {"id": "t1", "account_id": "acct_A", "amount": -100, "category": "Food", "posting_date": "2024-01-05"},
                {"id": "t2", "account_id": "acct_B", "amount": -200, "category": "Food", "posting_date": "2024-01-10"},
                {"id": "t3", "account_id": "acct_S", "amount": 500,  "category": "Income", "posting_date": "2024-01-15"},
            ]
            for t in txns:
                dir = "outflow" if t["amount"] < 0 else "inflow"
                conn.execute(
                    "INSERT INTO transactions (id, institution_id, account_id, amount, signed_amount, direction, category, posting_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (t["id"], "instA", t["account_id"], abs(t["amount"]), t["amount"], dir, t["category"], t["posting_date"])
                )
            conn.commit()

            # spending
            h_spend = get_spending_by_category(conn, "2024-01-01", "2024-01-31")
            m_spend = get_spending_by_category(conn, "2024-01-01", "2024-01-31", owner_id="mine")
            t_spend = get_spending_by_category(conn, "2024-01-01", "2024-01-31", owner_id="theirs")

            _check("Household Food spend is $300", h_spend and h_spend[0]["total_spent"] == 300)
            _check("Mine Food spend is $100", m_spend and m_spend[0]["total_spent"] == 100)
            _check("Theirs Food spend is $200", t_spend and t_spend[0]["total_spent"] == 200)

            # cashflow
            h_cf = get_monthly_cash_flow(conn, 2024)
            m_cf = get_monthly_cash_flow(conn, 2024, owner_id="mine")
            
            h_jan = next((x for x in h_cf if x["month"] == 1), None)
            m_jan = next((x for x in m_cf if x["month"] == 1), None)
            
            _check("Household CF: Jan Income $500, Spending $300", h_jan and h_jan["income"] == 500 and h_jan["spending"] == 300)
            _check("Mine CF: Jan Income $500, Spending $100", m_jan and m_jan["income"] == 500 and m_jan["spending"] == 100)

    finally:
        os.remove(db)

def run_all():
    print("Running Multi-User Domain Isolation Tests...\n")
    test_owner_resolvers()
    test_transaction_scoping()
    test_reports_scoping()

    print("\n─── Summary ───")
    print(f"Passed: {_passed}")
    print(f"Failed: {_failed}")
    if _failed > 0:
        print("\nFailed Tests:")
        for err in _errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("\nAll tests passed successfully! ✨")
        sys.exit(0)

if __name__ == "__main__":
    run_all()
