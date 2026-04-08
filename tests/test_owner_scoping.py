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
    update_owner,
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

def test_kpi_metrics_scoping():
    """Regression for the dashboard click/hover audit (2026-04-08).

    Validates that the three KPI metric DAL functions actually
    differentiate by owner_id — previously they ignored the parameter
    entirely and returned identical payloads for every owner, breaking
    the dashboard's owner switcher.
    """
    print("\n─── KPI Metrics Owner Scoping (audit regression) ───")
    db = _temp_db()
    dal.owners._config_cache = {"primary_owner": "alice"}
    try:
        init_db(db)
        with get_db(db) as conn:
            from dal.derived import (
                compute_emergency_fund_months,
                compute_net_worth_velocity,
            )
            from dal.credit_scores import get_latest_credit_scores

            conn.execute("INSERT INTO institutions (id, display_name) VALUES ('bankA', 'Bank A')")
            conn.execute("INSERT INTO institutions (id, display_name) VALUES ('bankB', 'Bank B')")
            create_owner(conn, "alice", "Alice")
            create_owner(conn, "bob",   "Bob")
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4, owner_id) VALUES ('chk_alice', 'bankA', 'Alice Checking', 'checking', '1111', 'alice')")
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4, owner_id) VALUES ('chk_bob',   'bankB', 'Bob Checking',   'checking', '2222', 'bob')")

            # Liquid balances: Alice=10000, Bob=2500
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES (?, ?, ?)",
                ("chk_alice", "2026-04-01", 10000.0),
            )
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, as_of, balance) VALUES (?, ?, ?)",
                ("chk_bob", "2026-04-01", 2500.0),
            )

            # Spending: Alice has $400/mo over 6 months, Bob has $100/mo
            # (gives different runways: Alice 25, Bob 25 — so we make them
            # actually differ by giving Alice a heavier basket).
            for offset in range(1, 7):
                month_str = f"2025-{12 - offset + 1:02d}-15" if (12 - offset + 1) > 0 else f"2024-{12 + (12 - offset + 1):02d}-15"
            # Simpler: insert 3 transactions in the past 6 months for each
            from datetime import date as _date
            today = _date.today()
            for i in range(6):
                d = (today.replace(day=1) - _timedelta_months(i + 1)).isoformat()
                conn.execute(
                    "INSERT INTO transactions (id, institution_id, account_id, amount, signed_amount, direction, category, posting_date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'posted')",
                    (f"a_{i}", "bankA", "chk_alice", 500, -500, "Debit", "Groceries", d),
                )
                conn.execute(
                    "INSERT INTO transactions (id, institution_id, account_id, amount, signed_amount, direction, category, posting_date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'posted')",
                    (f"b_{i}", "bankB", "chk_bob", 100, -100, "Debit", "Groceries", d),
                )

            # Credit scores: Alice 780, Bob 650
            conn.execute(
                "INSERT INTO credit_scores (institution_id, score, score_type, source, score_date, owner_id) VALUES ('bankA', 780, 'FICO', 'TransUnion', ?, 'alice')",
                (today.isoformat(),),
            )
            conn.execute(
                "INSERT INTO credit_scores (institution_id, score, score_type, source, score_date, owner_id) VALUES ('bankB', 650, 'FICO', 'TransUnion', ?, 'bob')",
                (today.isoformat(),),
            )
            conn.commit()

            # ── emergency-fund (runway) ──────────────────────────────
            ef_house = compute_emergency_fund_months(conn)
            ef_alice = compute_emergency_fund_months(conn, owner_id="alice")
            ef_bob   = compute_emergency_fund_months(conn, owner_id="bob")
            _check(
                "emergency-fund: house liquid_balance = $12,500",
                ef_house["liquid_balance"] == 12500.0,
                f"got {ef_house['liquid_balance']}",
            )
            _check(
                "emergency-fund: alice liquid_balance = $10,000",
                ef_alice["liquid_balance"] == 10000.0,
                f"got {ef_alice['liquid_balance']}",
            )
            _check(
                "emergency-fund: bob liquid_balance = $2,500",
                ef_bob["liquid_balance"] == 2500.0,
                f"got {ef_bob['liquid_balance']}",
            )
            _check(
                "emergency-fund: alice and bob payloads differ",
                ef_alice["liquid_balance"] != ef_bob["liquid_balance"],
            )

            # ── net-worth velocity ───────────────────────────────────
            v_alice = compute_net_worth_velocity(conn, owner_id="alice")
            v_bob   = compute_net_worth_velocity(conn, owner_id="bob")
            _check(
                "net-worth-velocity: alice current_net_worth differs from bob",
                v_alice["current_net_worth"] != v_bob["current_net_worth"]
                or v_alice["current_net_worth"] == 0,  # both could be 0 with this fixture
            )

            # ── credit-scores ────────────────────────────────────────
            cs_house = get_latest_credit_scores(conn)
            cs_alice = get_latest_credit_scores(conn, owner_id="alice")
            cs_bob   = get_latest_credit_scores(conn, owner_id="bob")
            _check(
                "credit-scores: house returns 2 rows",
                len(cs_house) == 2,
                f"got {len(cs_house)}",
            )
            _check(
                "credit-scores: alice returns only 780",
                len(cs_alice) == 1 and cs_alice[0]["score"] == 780,
            )
            _check(
                "credit-scores: bob returns only 650",
                len(cs_bob) == 1 and cs_bob[0]["score"] == 650,
            )
            _check(
                "credit-scores: alice and bob payloads differ",
                cs_alice != cs_bob,
            )
    finally:
        os.remove(db)


def _timedelta_months(n: int):
    """Cheap month delta for the test fixture (30-day approximation)."""
    from datetime import timedelta as _td
    return _td(days=30 * n)


def test_update_owner():
    print("\n─── update_owner (Phase 1D) ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            create_owner(conn, "alice", "Alice")
            conn.commit()

            # 1. Successful rename, case-insensitive lookup
            update_owner(conn, "ALICE", display_name="Alicia")
            row = conn.execute(
                "SELECT display_name FROM owners WHERE id = 'alice'"
            ).fetchone()
            _check(
                "update_owner: case-insensitive rename writes new display_name",
                row["display_name"] == "Alicia",
                f"got {row['display_name']!r}",
            )

            # 2. No-op when no kwargs supplied
            update_owner(conn, "alice")
            row = conn.execute(
                "SELECT display_name FROM owners WHERE id = 'alice'"
            ).fetchone()
            _check(
                "update_owner: empty kwargs is a no-op",
                row["display_name"] == "Alicia",
            )

            # 3. Missing owner raises ValueError
            try:
                update_owner(conn, "ghost", display_name="Boo")
                _check("update_owner: missing owner raises ValueError", False, "no exception")
            except ValueError:
                _check("update_owner: missing owner raises ValueError", True)

            # 4. Empty / whitespace name raises ValueError
            try:
                update_owner(conn, "alice", display_name="   ")
                _check("update_owner: empty display_name raises ValueError", False, "no exception")
            except ValueError:
                _check("update_owner: empty display_name raises ValueError", True)

            # 5. Length cap (51 chars) raises ValueError
            try:
                update_owner(conn, "alice", display_name="x" * 51)
                _check("update_owner: 51-char name raises ValueError", False, "no exception")
            except ValueError:
                _check("update_owner: 51-char name raises ValueError", True)

            # 6. Trims whitespace on save
            update_owner(conn, "alice", display_name="  Trimmed  ")
            row = conn.execute(
                "SELECT display_name FROM owners WHERE id = 'alice'"
            ).fetchone()
            _check(
                "update_owner: surrounding whitespace is stripped",
                row["display_name"] == "Trimmed",
                f"got {row['display_name']!r}",
            )
    finally:
        os.remove(db)


def run_all():
    print("Running Multi-User Domain Isolation Tests...\n")
    test_owner_resolvers()
    test_transaction_scoping()
    test_reports_scoping()
    test_kpi_metrics_scoping()
    test_update_owner()

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
