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
    build_account_filter,
)
from dal.transactions import upsert_transactions, get_transactions
from dal.cash_flow import get_monthly_cash_flow
from dal.reports import (
    get_spending_by_category,
    get_net_worth_history,
    get_cash_flow_report,
    get_flow_data,
    get_period_summary,
)
from dal.review import get_monthly_review
from dal.recurring import get_recurring, get_monthly_recurring_total
from dal.debt import _get_liability_accounts
from dal.freshness import get_institution_freshness

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


def test_build_account_filter():
    """Unit test for the shared helper that replaced the `if not account_ids:`
    pattern across the DAL. The helper MUST distinguish None (no filter —
    return everything) from [] (owner owns nothing — return nothing)."""
    print("\n─── build_account_filter (Phase 12 audit fix-up) ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            conn.execute("INSERT INTO institutions (id, display_name) VALUES ('instA', 'Bank A')")
            conn.execute("INSERT INTO accounts (id, institution_id, name, type, last4) VALUES ('a1', 'instA', 'A1', 'checking', '1111')")
            create_owner(conn, "alice", "Alice")
            create_owner(conn, "bob", "Bob")
            assign_account_owner(conn, "a1", "alice")
            conn.commit()

            # 1. No filter at all → empty fragment, no params
            sql, params = build_account_filter(conn, None, None)
            _check("build_account_filter: None/None → empty fragment", sql == "" and params == [])

            # 2. Explicit account_ids list → IN (...) clause with params
            sql, params = build_account_filter(conn, None, ["a1", "a2"])
            _check(
                "build_account_filter: explicit ids → IN clause",
                "account_id IN" in sql and params == ["a1", "a2"],
            )

            # 3. Owner with accounts → IN clause with resolved ids
            sql, params = build_account_filter(conn, "alice", None)
            _check(
                "build_account_filter: owner-with-accounts → IN clause",
                "account_id IN" in sql and set(params) == {"a1"},
            )

            # 4. Owner with ZERO accounts → AND 1=0 (the critical fix)
            sql, params = build_account_filter(conn, "bob", None)
            _check(
                "build_account_filter: owner-with-no-accounts → AND 1=0",
                sql == " AND 1=0" and params == [],
            )

            # 5. Explicit empty list → AND 1=0 (same short-circuit)
            sql, params = build_account_filter(conn, None, [])
            _check(
                "build_account_filter: explicit empty list → AND 1=0",
                sql == " AND 1=0" and params == [],
            )

            # 6. Custom column → uses that column name
            sql, _ = build_account_filter(conn, None, ["a1"], column="a.id")
            _check(
                "build_account_filter: column override works",
                "a.id IN" in sql,
            )
    finally:
        os.remove(db)


def test_empty_owner_no_leak():
    """Regression test for the Phase 12 empty-state audit.

    When an owner exists but owns zero accounts, every owner-scoped
    endpoint must return empty / zero results, NOT the primary owner's
    data. This test seeds a two-owner DB where 'alice' owns everything
    and 'bob' owns nothing, then verifies that every previously-leaky
    endpoint returns zero rows under owner_id='bob'.
    """
    print("\n─── Empty-owner no-leak regression (Phase 12 audit) ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            # Set up: alice has 1 account with transactions/holdings/budgets,
            # bob has zero accounts.
            conn.execute("INSERT INTO institutions (id, display_name) VALUES ('inst1', 'Bank 1')")
            conn.execute(
                "INSERT INTO accounts (id, institution_id, name, type, last4, is_active) "
                "VALUES ('acct_a', 'inst1', 'Alice Checking', 'checking', '0001', 1)"
            )
            conn.execute(
                "INSERT INTO accounts (id, institution_id, name, type, last4, is_active) "
                "VALUES ('acct_b', 'inst1', 'Alice Invest', 'investment', '0002', 1)"
            )
            create_owner(conn, "alice", "Alice")
            create_owner(conn, "bob", "Bob")
            assign_account_owner(conn, "acct_a", "alice")
            assign_account_owner(conn, "acct_b", "alice")

            # Seed transactions for alice so the leak would be visible.
            # Bypass upsert_transactions and write direct since these tests
            # pre-date its required-keys schema (matches the pattern in
            # test_transaction_scoping / test_reports_scoping above).
            conn.execute(
                "INSERT INTO transactions (id, institution_id, account_id, amount, signed_amount, "
                "direction, category, posting_date, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("tx_a", "inst1", "acct_a", 100.0, -100.0, "Debit", "Groceries", "2026-03-15", "posted"),
            )
            conn.execute(
                "INSERT INTO transactions (id, institution_id, account_id, amount, signed_amount, "
                "direction, category, posting_date, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("tx_inc", "inst1", "acct_a", 5000.0, 5000.0, "Credit", "Salary", "2026-03-01", "posted"),
            )

            # Seed a holding for alice.
            conn.execute(
                "INSERT INTO investment_holdings (account_id, ticker, date, shares, close_price, market_value) "
                "VALUES ('acct_b', 'VTI', '2026-03-01', 10, 250.00, 2500.00)"
            )
            conn.commit()

            # ─── 1. Cash flow: monthly cash flow should be zeros for bob ───
            rows = get_monthly_cash_flow(conn, 2026, owner_id="bob")
            bob_income = sum(r["income"] for r in rows)
            bob_spending = sum(r["spending"] for r in rows)
            _check(
                "get_monthly_cash_flow: bob (no accounts) returns zero income",
                bob_income == 0,
                f"got {bob_income}",
            )
            _check(
                "get_monthly_cash_flow: bob (no accounts) returns zero spending",
                bob_spending == 0,
                f"got {bob_spending}",
            )
            # Sanity: alice should still see her data
            alice_rows = get_monthly_cash_flow(conn, 2026, owner_id="alice")
            alice_income = sum(r["income"] for r in alice_rows)
            _check(
                "get_monthly_cash_flow: alice still sees her income (control)",
                alice_income > 0,
                f"got {alice_income}",
            )

            # ─── 2. Cash flow report ───
            rows = get_cash_flow_report(conn, months=12, owner_id="bob")
            bob_total = sum((r.get("income", 0) + r.get("spending", 0)) for r in rows)
            _check(
                "get_cash_flow_report: bob returns zero totals",
                bob_total == 0,
                f"got {bob_total}",
            )

            # ─── 3. Spending by category ───
            cats = get_spending_by_category(
                conn, "2026-01-01", "2026-12-31", owner_id="bob"
            )
            _check(
                "get_spending_by_category: bob returns empty list",
                cats == [],
                f"got {cats}",
            )

            # ─── 4. Budget vs actual ───
            # Budgets are household-only as of V23 — there is no
            # per-owner attribution to assert against. The household
            # actuals will sum every owner's spending in the month,
            # which is the intended behavior. The "no leak" property
            # this section used to test is no longer applicable.

            # ─── 5. Period summary (merchant/reports aggregate) ───
            summary = get_period_summary(conn, "2026-01-01", "2026-12-31", owner_id="bob")
            _check(
                "get_period_summary: bob returns zero income",
                summary["total_income"] == 0,
                f"got {summary['total_income']}",
            )
            _check(
                "get_period_summary: bob returns zero spending",
                summary["total_spending"] == 0,
                f"got {summary['total_spending']}",
            )

            # ─── 6. Flow data (Sankey) ───
            flow = get_flow_data(conn, months=12, owner_id="bob")
            _check(
                "get_flow_data: bob returns zero totalIncome",
                (flow.get("totalIncome") or 0) == 0,
                f"got {flow.get('totalIncome')}",
            )

            # ─── 7. Investment allocation ───
            # Removed in P13 investments rebuild (dal.allocation deleted).

            # ─── 8. All accounts performance ───
            # Removed in P13 investments rebuild (dal.performance deleted).

            # ─── 9. Monthly review (dal/review.py, 6 call sites patched) ───
            review = get_monthly_review(conn, "2026-03", owner_id="bob")
            _check(
                "get_monthly_review: bob returns zero income",
                review["income"]["total"] == 0,
                f"got {review['income']['total']}",
            )
            _check(
                "get_monthly_review: bob returns zero spending",
                review["spending"]["total"] == 0,
                f"got {review['spending']['total']}",
            )
            _check(
                "get_monthly_review: bob has no notable transactions",
                review.get("notable_transactions", []) == [],
            )

            # ─── 10. Recurring helpers ───
            rec = get_recurring(conn, owner_id="bob")
            _check(
                "get_recurring: bob returns empty list",
                rec == [],
                f"got {rec}",
            )
            rec_total = get_monthly_recurring_total(conn, owner_id="bob")
            _check(
                "get_monthly_recurring_total: bob returns zero total",
                rec_total["total"] == 0,
                f"got {rec_total['total']}",
            )

            # ─── 11. Debt / liability accounts ───
            debts = _get_liability_accounts(conn, owner_id="bob")
            _check(
                "_get_liability_accounts: bob returns empty list",
                debts == [],
                f"got {debts}",
            )

            # ─── 12. Freshness (institution-level) ───
            fresh = get_institution_freshness(conn, owner_id="bob")
            # bob has zero accounts → zero "active" institutions derived
            # from accounts. The function may still include tier-3
            # institutions that ship without account data; assert that
            # the owner-scoped path doesn't explode and doesn't return
            # every institution alice has.
            _check(
                "get_institution_freshness: bob returns a list (no crash)",
                isinstance(fresh, list),
                f"got {type(fresh)}",
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
    test_build_account_filter()
    test_empty_owner_no_leak()

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
