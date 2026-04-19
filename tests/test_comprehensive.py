"""
tests/test_comprehensive.py — Comprehensive DAL unit test suite.

Covers mainline behavior AND edge cases across 7 module areas:
  1. Derived Metrics  — emergency fund, DTI ratio, interest cost, net worth
  2. Cash Flow        — monthly, quarterly, yearly, rolling, period detail
  3. Reports          — spending by category, flow data (Sankey), CSV export
  4. User Rules       — exact amount, amount range, description regex
  5. Freshness        — staleness tier, document drop nudge, no-data
  6. Reconciliation   — cross-institution, same-institution, date windows
  7. Investments      — decimal precision, upsert idempotency, portfolio total

All tests are self-contained (temp DB per test, no production data).
Run with:
    python tests/test_comprehensive.py
"""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db

# ── Counters ─────────────────────────────────────────────────────────────────
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


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


def _seed_base(conn, institutions=None, accounts=None):
    """Seed shared test data: institutions and accounts."""
    institutions = institutions or [("test", "Test Bank")]
    accounts = accounts or [
        ("test_chk", "test", "Checking", "1234", "checking"),
        ("test_sav", "test", "Savings", "5678", "savings"),
    ]
    for i_id, name in institutions:
        conn.execute(
            "INSERT OR IGNORE INTO institutions (id, display_name) VALUES (?, ?)",
            (i_id, name),
        )
    for a_id, i_id, name, last4, atype in accounts:
        conn.execute(
            "INSERT OR IGNORE INTO accounts "
            "(id, institution_id, name, last4, type, is_active) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (a_id, i_id, name, last4, atype),
        )
    conn.commit()


def _insert_txn(conn, txn_id, acct_id, inst_id, date, amount, desc,
                category="Uncategorized",  direction=None, status="posted",
                transfer_tag=None):
    """Helper to insert a test transaction."""
    signed = amount  # positive = credit, negative = debit
    if direction is None:
        direction = "Credit" if amount > 0 else "Debit"
    conn.execute(
        """INSERT INTO transactions
           (id, account_id, institution_id, posting_date, amount,
            signed_amount, direction, description, category, status,
            transfer_tag, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
        (txn_id, acct_id, inst_id, date, abs(amount), signed,
         direction, desc, category, status, transfer_tag),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DERIVED METRICS
# ═══════════════════════════════════════════════════════════════════════════════


def test_derived_emergency_fund():
    print("\n─── Derived: Emergency Fund ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            # Record checking+savings balances
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('test_chk', 5000.00, '2026-03-01T10:00:00')"
            )
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('test_sav', 10000.00, '2026-03-01T10:00:00')"
            )

            # Insert 6 months of spending ($2000/month average)
            for m in range(1, 7):
                _insert_txn(conn, f"sp_{m}", "test_chk", "test",
                            f"2025-{m+6:02d}-15" if m + 6 <= 12 else f"2026-{m+6-12:02d}-15",
                            -2000.00, "KROGER", "Groceries")
            conn.commit()

            from dal.derived import compute_emergency_fund_months
            result = compute_emergency_fund_months(conn)

            _check("EF liquid_balance = $15,000",
                   result["liquid_balance"] == 15000.00,
                   f"got {result['liquid_balance']}")
            _check("EF avg_monthly_spending > 0",
                   result["avg_monthly_spending"] > 0,
                   f"got {result['avg_monthly_spending']}")
            _check("EF months_of_runway is not None",
                   result["months_of_runway"] is not None)
    finally:
        os.unlink(db)


def test_derived_emergency_fund_zero_spending():
    """EDGE CASE: No spending → months_of_runway should be None (not division by zero)."""
    print("\n─── Derived: Emergency Fund — Zero Spending ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('test_chk', 5000.00, '2026-03-01T10:00:00')"
            )
            conn.commit()

            from dal.derived import compute_emergency_fund_months
            result = compute_emergency_fund_months(conn)

            _check("EF zero-spend: liquid_balance = $5,000",
                   result["liquid_balance"] == 5000.00)
            _check("EF zero-spend: avg_monthly_spending = 0",
                   result["avg_monthly_spending"] == 0)
            _check("EF zero-spend: months_of_runway is None (no crash)",
                   result["months_of_runway"] is None,
                   f"got {result['months_of_runway']}")
    finally:
        os.unlink(db)


def test_derived_dti_zero_income():
    """EDGE CASE: Month with zero income → DTI should be None (not crash)."""
    print("\n─── Derived: DTI Ratio — Zero Income ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            # Only debt payment, no income
            _insert_txn(conn, "debt_1", "test_chk", "test",
                        "2026-02-15", -500.00, "Mortgage Payment", "Mortgage")
            conn.commit()

            from dal.derived import compute_dti_ratio
            result = compute_dti_ratio(conn, months=2)

            if result:
                month_data = result[0]
                _check("DTI zero-income: dti_ratio is None",
                       month_data["dti_ratio"] is None,
                       f"got {month_data['dti_ratio']}")
                _check("DTI zero-income: status is None",
                       month_data["status"] is None)
            else:
                _check("DTI zero-income: empty result is acceptable", True)
    finally:
        os.unlink(db)


def test_derived_net_worth_negative():
    """EDGE CASE: Liabilities exceed assets → negative net worth."""
    print("\n─── Derived: Net Worth — Negative ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn, accounts=[
                ("test_chk", "test", "Checking", "1234", "checking"),
                ("test_loan", "test", "Car Loan", "5555", "loan"),
            ])
            # $500 in checking, $25,000 car loan
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('test_chk', 500.00, '2026-03-01T10:00:00')")
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('test_loan', 25000.00, '2026-03-01T10:00:00')")
            conn.commit()

            from dal.derived import recompute_net_worth
            nw = recompute_net_worth(conn)
            conn.commit()

            _check("Negative net worth computed correctly",
                   nw == 500.00 - 25000.00,
                   f"got {nw}")
            _check("Net worth is negative", nw < 0)
    finally:
        os.unlink(db)


def test_derived_net_worth_no_investments():
    """EDGE CASE: No investment accounts → net worth = banking - liabilities only."""
    print("\n─── Derived: Net Worth — No Investments ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('test_chk', 3000.00, '2026-03-01T10:00:00')")
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('test_sav', 7000.00, '2026-03-01T10:00:00')")
            conn.commit()

            from dal.derived import recompute_net_worth
            nw = recompute_net_worth(conn)
            conn.commit()

            _check("NW with banking only = $10,000",
                   nw == 10000.00, f"got {nw}")
    finally:
        os.unlink(db)


def test_derived_inactive_bnpl_excluded():
    """EDGE CASE: Paid-off BNPL (is_active=0) must NOT inflate liabilities."""
    print("\n─── Derived: Net Worth — Inactive BNPL Excluded ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn, accounts=[
                ("test_chk", "test", "Checking", "1234", "checking"),
                ("test_bnpl", "test", "Affirm BNPL", "9999", "bnpl"),
            ])
            # Mark BNPL as inactive (paid off)
            conn.execute("UPDATE accounts SET is_active = 0 WHERE id = 'test_bnpl'")
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('test_chk', 5000.00, '2026-03-01T10:00:00')")
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('test_bnpl', 200.00, '2026-03-01T10:00:00')")
            conn.commit()

            from dal.derived import recompute_net_worth
            nw = recompute_net_worth(conn)
            conn.commit()

            _check("Inactive BNPL excluded from liabilities",
                   nw == 5000.00,
                   f"got {nw}, expected 5000 (BNPL $200 should be excluded)")
    finally:
        os.unlink(db)


def test_derived_interest_cost_currency_parsing():
    """EDGE CASE: Interest from loan_details has $ and , formatting."""
    print("\n─── Derived: Interest Cost — Currency Parsing ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn, accounts=[
                ("test_loan", "test", "Mortgage", "NFAL", "loan"),
            ])
            current_year = datetime.now(timezone.utc).strftime("%Y")
            # Use 'ytd_interest' field name — matches the production code's
            # LOWER(field_name) IN ('ytd_interest', 'interest paid ytd', ...)
            conn.execute(
                "INSERT INTO loan_details (account_id, field_name, field_value, as_of) "
                "VALUES ('test_loan', 'ytd_interest', '$1,234.56', ?)",
                (f"{current_year}-03-01",))
            conn.commit()

            from dal.derived import compute_interest_cost
            result = compute_interest_cost(conn)

            _check("Interest cost parsed from $1,234.56",
                   result["ytd_total"] == 1234.56,
                   f"got {result['ytd_total']}")
    finally:
        os.unlink(db)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CASH FLOW
# ═══════════════════════════════════════════════════════════════════════════════


def test_cash_flow_monthly():
    """Mainline: monthly cash flow returns 12 months with correct sums."""
    print("\n─── Cash Flow: Monthly ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            # Insert income + spending for January 2026
            _insert_txn(conn, "inc_1", "test_chk", "test",
                        "2026-01-10", 5000.00, "DFAS Pension", "Military Pension")
            _insert_txn(conn, "exp_1", "test_chk", "test",
                        "2026-01-15", -300.00, "KROGER", "Groceries")
            _insert_txn(conn, "exp_2", "test_chk", "test",
                        "2026-01-20", -100.00, "SHELL", "Gasoline/Fuel")
            conn.commit()

            from dal.cash_flow import get_monthly_cash_flow
            result = get_monthly_cash_flow(conn, 2026)

            _check("Monthly returns 12 entries", len(result) == 12)

            jan = result[0]  # January is index 0
            _check("Jan income = $5,000", jan["income"] == 5000.00,
                   f"got {jan['income']}")
            _check("Jan spending = $400", jan["spending"] == 400.00,
                   f"got {jan['spending']}")
            _check("Jan net = $4,600", jan["net"] == 4600.00,
                   f"got {jan['net']}")
            _check("Jan savings_rate > 0", jan["savings_rate"] > 0)

            # Feb should be zeroed
            feb = result[1]
            _check("Feb has zero income (no data)", feb["income"] == 0)
    finally:
        os.unlink(db)


def test_cash_flow_zero_income_savings_rate():
    """EDGE CASE: savings_rate must be 0 when income is 0 (not crash)."""
    print("\n─── Cash Flow: Savings Rate — Zero Income ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            _insert_txn(conn, "exp_only", "test_chk", "test",
                        "2026-01-15", -200.00, "KROGER", "Groceries")
            conn.commit()

            from dal.cash_flow import get_monthly_cash_flow
            result = get_monthly_cash_flow(conn, 2026)
            jan = result[0]

            _check("Zero income → savings_rate = 0.0",
                   jan["savings_rate"] == 0.0,
                   f"got {jan['savings_rate']}")
    finally:
        os.unlink(db)


def test_cash_flow_transfers_excluded():
    """EDGE CASE: Transactions with transfer_tag must not appear in income/spending."""
    print("\n─── Cash Flow: Transfer Exclusion ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            # Real income
            _insert_txn(conn, "real_inc", "test_chk", "test",
                        "2026-01-10", 3000.00, "DFAS", "Military Pension")
            # Transfer OUT (should be excluded by transfer_tag)
            _insert_txn(conn, "xfer_out", "test_chk", "test",
                        "2026-01-12", -500.00, "Transfer to Fidelity", "Transfers",
                        transfer_tag="abc123")
            # Transfer IN (should be excluded)
            _insert_txn(conn, "xfer_in", "test_sav", "test",
                        "2026-01-12", 500.00, "Transfer from Checking", "Transfers",
                        transfer_tag="abc123")
            conn.commit()

            from dal.cash_flow import get_monthly_cash_flow
            result = get_monthly_cash_flow(conn, 2026)
            jan = result[0]

            _check("Transfers excluded from income",
                   jan["income"] == 3000.00,
                   f"got {jan['income']}")
            _check("Transfers excluded from spending",
                   jan["spending"] == 0.0,
                   f"got {jan['spending']}")
    finally:
        os.unlink(db)


def test_cash_flow_quarterly():
    """Mainline: quarterly aggregation."""
    print("\n─── Cash Flow: Quarterly ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            # Q1: Jan + Feb + Mar
            for m in range(1, 4):
                _insert_txn(conn, f"q1_inc_{m}", "test_chk", "test",
                            f"2026-{m:02d}-10", 1000.00, "Income", "Military Pension")
            conn.commit()

            from dal.cash_flow import get_quarterly_cash_flow
            result = get_quarterly_cash_flow(conn, 2026)

            _check("Quarterly returns 4 entries", len(result) == 4)
            _check("Q1 income = $3,000", result[0]["income"] == 3000.00,
                   f"got {result[0]['income']}")
            _check("Q2 income = $0 (no data)", result[1]["income"] == 0.0)
    finally:
        os.unlink(db)


def test_cash_flow_account_filter():
    """EDGE CASE: Account filter restricts results to specific accounts."""
    print("\n─── Cash Flow: Account Filter ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            _insert_txn(conn, "chk_inc", "test_chk", "test",
                        "2026-01-10", 1000.00, "Checking Income", "Military Pension")
            _insert_txn(conn, "sav_inc", "test_sav", "test",
                        "2026-01-10", 500.00, "Savings Interest", "Interest")
            conn.commit()

            from dal.cash_flow import get_monthly_cash_flow
            # Only checking account
            result = get_monthly_cash_flow(conn, 2026, account_ids=["test_chk"])
            jan = result[0]

            _check("Account filter: only checking income",
                   jan["income"] == 1000.00,
                   f"got {jan['income']} (expected 1000, not 1500)")
    finally:
        os.unlink(db)


def test_cash_flow_period_detail():
    """Mainline: period detail with category breakdowns."""
    print("\n─── Cash Flow: Period Detail ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            _insert_txn(conn, "pd_inc", "test_chk", "test",
                        "2026-01-10", 4000.00, "DFAS", "Military Pension")
            _insert_txn(conn, "pd_groc", "test_chk", "test",
                        "2026-01-15", -600.00, "KROGER", "Groceries")
            _insert_txn(conn, "pd_gas", "test_chk", "test",
                        "2026-01-20", -150.00, "SHELL", "Gasoline/Fuel")
            conn.commit()

            from dal.cash_flow import get_period_detail
            result = get_period_detail(conn, "2026-01-01", "2026-01-31")

            _check("Period detail has income", result["income"] > 0)
            _check("Period detail has spending", result["spending"] > 0)
            _check("Period detail net = income - spending",
                   result["net"] == result["income"] - result["spending"])
            _check("Period detail has income_categories",
                   len(result["income_categories"]) >= 1)
            _check("Period detail has spending_categories",
                   len(result["spending_categories"]) >= 1)
    finally:
        os.unlink(db)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. REPORTS
# ═══════════════════════════════════════════════════════════════════════════════


def test_reports_spending_by_category():
    """Mainline: spending breakdown ranks categories correctly."""
    print("\n─── Reports: Spending by Category ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            _insert_txn(conn, "r_groc1", "test_chk", "test",
                        "2026-01-05", -500.00, "KROGER", "Groceries")
            _insert_txn(conn, "r_groc2", "test_chk", "test",
                        "2026-01-12", -300.00, "WALMART", "Groceries")
            _insert_txn(conn, "r_gas", "test_chk", "test",
                        "2026-01-08", -100.00, "SHELL", "Gasoline/Fuel")
            conn.commit()

            from dal.reports import get_spending_by_category
            result = get_spending_by_category(conn, "2026-01-01", "2026-01-31")

            _check("Multiple categories returned", len(result) >= 2)

            # Groceries should be first (highest spend)
            _check("Groceries is top category",
                   result[0]["category"] == "Groceries",
                   f"got {result[0]['category']}")
            _check("Groceries total = $800",
                   result[0]["total_spent"] == 800.00,
                   f"got {result[0]['total_spent']}")
            _check("Percentages sum to 100%",
                   abs(sum(r["pct_of_total"] for r in result) - 100.0) < 0.5)
    finally:
        os.unlink(db)


def test_reports_flow_data_sankey():
    """Mainline: Sankey flow data returns income + spending categories."""
    print("\n─── Reports: Flow Data (Sankey) ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            _insert_txn(conn, "f_inc", "test_chk", "test",
                        "2026-03-10", 5000.00, "DFAS", "Military Pension")
            _insert_txn(conn, "f_exp", "test_chk", "test",
                        "2026-03-15", -400.00, "KROGER", "Groceries")
            conn.commit()

            from dal.reports import get_flow_data
            result = get_flow_data(conn, months=1)

            _check("Flow has income_categories", len(result["income_categories"]) >= 1)
            _check("Flow has spending_categories", len(result["spending_categories"]) >= 1)
            _check("Flow total_income > 0", result["total_income"] > 0)
            _check("Flow total_spending > 0", result["total_spending"] > 0)
            _check("Flow savings_rate computed",
                   result["savings_rate"] is not None)
    finally:
        os.unlink(db)


def test_reports_csv_export_null_description():
    """EDGE CASE: CSV export handles NULL descriptions gracefully."""
    print("\n─── Reports: CSV Export — NULL Description ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            # Insert transaction with NULL description
            conn.execute(
                "INSERT INTO transactions "
                "(id, account_id, institution_id, posting_date, amount, "
                "signed_amount, direction, description, category, status, "
                "created_at, updated_at) "
                "VALUES ('null_desc', 'test_chk', 'test', '2026-01-15', "
                "50.00, -50.00, 'Debit', NULL, 'Uncategorized', 'posted', "
                "datetime('now'), datetime('now'))")
            conn.commit()

            from dal.reports import export_transactions_csv
            csv_str = export_transactions_csv(conn, "2026-01-01", "2026-01-31")

            _check("CSV export succeeds with NULL desc", len(csv_str) > 0)
            _check("CSV has header row", "description" in csv_str)
    finally:
        os.unlink(db)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. USER RULES
# ═══════════════════════════════════════════════════════════════════════════════


def test_user_rules_exact_amount_match():
    """Mainline + EDGE: exact amount match with tolerance boundaries."""
    print("\n─── User Rules: Exact Amount Match ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)

            from dal.user_rules import create_user_rule, apply_user_rules

            # Create rule: $105 ± $2 tolerance
            create_user_rule(conn, "txn_src", "Officiating Income", "Game Fee",
                             "exact_amount", {"amount": 105.00, "tolerance": 2.00})
            conn.commit()

            # Exact match
            result = apply_user_rules(conn, {"amount": 105.00, "description": "CHECK"})
            _check("Exact amount matches", result == "Officiating Income",
                   f"got {result}")

            # Within tolerance (103.00 is exactly at boundary)
            result2 = apply_user_rules(conn, {"amount": 103.00, "description": "CHECK"})
            _check("$103 matches ($105±$2)", result2 == "Officiating Income",
                   f"got {result2}")

            # Just outside tolerance (102.99)
            result3 = apply_user_rules(conn, {"amount": 102.99, "description": "CHECK"})
            _check("$102.99 does NOT match ($105±$2)", result3 is None,
                   f"got {result3}")

            # Upper boundary ($107.00 is exactly at edge)
            result4 = apply_user_rules(conn, {"amount": 107.00, "description": "CHECK"})
            _check("$107 matches ($105±$2)", result4 == "Officiating Income",
                   f"got {result4}")

            # Just above upper boundary ($107.01)
            result5 = apply_user_rules(conn, {"amount": 107.01, "description": "CHECK"})
            _check("$107.01 does NOT match", result5 is None,
                   f"got {result5}")
    finally:
        os.unlink(db)


def test_user_rules_amount_range():
    """Mainline: amount range matching."""
    print("\n─── User Rules: Amount Range ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)

            from dal.user_rules import create_user_rule, apply_user_rules

            create_user_rule(conn, "txn_src", "Groceries", "Weekly Shop",
                             "amount_range", {"min_amount": 150.00, "max_amount": 250.00})
            conn.commit()

            # Within range
            result = apply_user_rules(conn, {"amount": 200.00, "description": "STORE"})
            _check("$200 in range [150,250]", result == "Groceries")

            # At min boundary
            result2 = apply_user_rules(conn, {"amount": 150.00, "description": "STORE"})
            _check("$150 at min boundary matches", result2 == "Groceries")

            # Below range
            result3 = apply_user_rules(conn, {"amount": 149.99, "description": "STORE"})
            _check("$149.99 below range doesn't match", result3 is None)
    finally:
        os.unlink(db)


def test_user_rules_invalid_regex():
    """EDGE CASE: Invalid regex pattern must not crash the categorizer."""
    print("\n─── User Rules: Invalid Regex ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)

            from dal.user_rules import create_user_rule, apply_user_rules

            create_user_rule(conn, "txn_src", "Test", "TestMerchant",
                             "description", {"pattern": "[invalid"})
            conn.commit()

            # Should not crash
            result = apply_user_rules(conn, {"amount": 50.00, "description": "anything"})
            _check("Invalid regex does not crash", True)
            _check("Invalid regex returns None", result is None)
    finally:
        os.unlink(db)


def test_user_rules_description_regex_match():
    """Mainline: description regex matching."""
    print("\n─── User Rules: Description Regex ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)

            from dal.user_rules import create_user_rule, apply_user_rules

            create_user_rule(conn, "txn_src", "Officiating Income", "Refs",
                             "description", {"pattern": "CHECK.*1[0-9]{3}"})
            conn.commit()

            result = apply_user_rules(conn, {"amount": 105.00, "description": "CHECK #1234"})
            _check("Regex matches CHECK #1234", result == "Officiating Income",
                   f"got {result}")

            result2 = apply_user_rules(conn, {"amount": 105.00, "description": "WIRE TRANSFER"})
            _check("Regex doesn't match unrelated desc", result2 is None)
    finally:
        os.unlink(db)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. FRESHNESS
# ═══════════════════════════════════════════════════════════════════════════════


def test_freshness_institution_no_data():
    """EDGE CASE: Institution with no balance/portfolio data → staleness = 'no_data'."""
    print("\n─── Freshness: No Data ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            # No balance/portfolio snapshots inserted
            conn.commit()

            from dal.freshness import get_institution_freshness
            result = get_institution_freshness(conn)

            test_inst = [f for f in result if f["institution_id"] == "test"]
            if test_inst:
                _check("No-data institution staleness = 'no_data'",
                       test_inst[0]["staleness"] == "no_data",
                       f"got {test_inst[0]['staleness']}")
                _check("No-data hours_since_update is None",
                       test_inst[0]["hours_since_update"] is None)
            else:
                _check("Test institution found in freshness", False)
    finally:
        os.unlink(db)


def test_freshness_fresh_data():
    """Mainline: Recent data → staleness = 'fresh'."""
    print("\n─── Freshness: Fresh Data ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)
            # Insert very recent balance
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('test_chk', 1000.00, ?)", (now_iso,))
            conn.commit()

            from dal.freshness import get_institution_freshness
            result = get_institution_freshness(conn)
            test_inst = [f for f in result if f["institution_id"] == "test"]

            if test_inst:
                _check("Recent data → staleness = 'fresh'",
                       test_inst[0]["staleness"] == "fresh",
                       f"got {test_inst[0]['staleness']}")
                _check("hours_since_update < 1",
                       test_inst[0]["hours_since_update"] is not None
                       and test_inst[0]["hours_since_update"] < 1)
            else:
                _check("Test institution in freshness", False)
    finally:
        os.unlink(db)


def test_freshness_net_worth_data_age():
    """Mainline: net worth data age identifies oldest institution."""
    print("\n─── Freshness: Net Worth Data Age ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn, institutions=[("bank_a", "Bank A"), ("bank_b", "Bank B")],
                       accounts=[
                           ("a_chk", "bank_a", "A Checking", "1111", "checking"),
                           ("b_chk", "bank_b", "B Checking", "2222", "checking"),
                       ])
            now = datetime.now(timezone.utc)
            # Bank A updated 1 hour ago
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('a_chk', 5000.00, ?)",
                ((now - timedelta(hours=1)).isoformat(),))
            # Bank B updated 48 hours ago (stale)
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) "
                "VALUES ('b_chk', 3000.00, ?)",
                ((now - timedelta(hours=48)).isoformat(),))
            conn.commit()

            from dal.freshness import get_net_worth_data_age
            result = get_net_worth_data_age(conn)

            _check("Oldest institution identified",
                   result["oldest_institution"] == "bank_b",
                   f"got {result['oldest_institution']}")
            _check("Not all fresh",
                   result["all_institutions_fresh"] is False)
    finally:
        os.unlink(db)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. RECONCILIATION
# ═══════════════════════════════════════════════════════════════════════════════


def test_reconciliation_cross_institution():
    """Mainline: Cross-institution transfer pair matched and tagged."""
    print("\n─── Reconciliation: Cross-Institution ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn, institutions=[("nfcu", "NFCU"), ("fidelity", "Fidelity")],
                       accounts=[
                           ("nfcu_chk", "nfcu", "Checking", "1111", "checking"),
                           ("fid_brok", "fidelity", "Brokerage", "2222", "investment"),
                       ])
            _insert_txn(conn, "r_out", "nfcu_chk", "nfcu",
                        "2026-03-01", -500.00, "Transfer to Fidelity", "Transfers")
            _insert_txn(conn, "r_in", "fid_brok", "fidelity",
                        "2026-03-01", 500.00, "Transfer from NFCU", "Transfers")
            conn.commit()

            from dal.reconciliation import reconcile_transfers
            stats = reconcile_transfers(conn, dry_run=False)

            _check("Cross-inst pair found", stats["pairs_found"] >= 1,
                   f"stats={stats}")
            _check("Cross-inst pair tagged", stats["newly_tagged"] >= 1)
    finally:
        os.unlink(db)


def test_reconciliation_date_boundary():
    """EDGE CASE: 3-day boundary for cross-institution, 1-day for same-institution."""
    print("\n─── Reconciliation: Date Boundary ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn, institutions=[("nfcu", "NFCU"), ("fidelity", "Fidelity")],
                       accounts=[
                           ("nfcu_chk", "nfcu", "Checking", "1111", "checking"),
                           ("fid_brok", "fidelity", "Brokerage", "2222", "investment"),
                       ])
            # Exactly 3 days apart → SHOULD match
            _insert_txn(conn, "d3_out", "nfcu_chk", "nfcu",
                        "2026-03-01", -1000.00, "Transfer", "Transfers")
            _insert_txn(conn, "d3_in", "fid_brok", "fidelity",
                        "2026-03-04", 1000.00, "Transfer", "Transfers")
            conn.commit()

            from dal.reconciliation import reconcile_transfers
            stats = reconcile_transfers(conn, dry_run=True)
            _check("3-day gap matches cross-institution",
                   stats["pairs_found"] >= 1, f"stats={stats}")

        # Now test 4-day gap → should NOT match
        db2 = _temp_db()
        init_db(db2)
        with get_db(db2) as conn2:
            _seed_base(conn2, institutions=[("nfcu", "NFCU"), ("fidelity", "Fidelity")],
                       accounts=[
                           ("nfcu_chk", "nfcu", "Checking", "1111", "checking"),
                           ("fid_brok", "fidelity", "Brokerage", "2222", "investment"),
                       ])
            _insert_txn(conn2, "d4_out", "nfcu_chk", "nfcu",
                        "2026-03-01", -1000.00, "Transfer", "Transfers")
            _insert_txn(conn2, "d4_in", "fid_brok", "fidelity",
                        "2026-03-05", 1000.00, "Transfer", "Transfers")
            conn2.commit()

            stats2 = reconcile_transfers(conn2, dry_run=True)
            _check("4-day gap does NOT match cross-institution",
                   stats2["pairs_found"] == 0, f"stats={stats2}")

        os.unlink(db2)
    finally:
        os.unlink(db)


def test_reconciliation_same_institution():
    """EDGE CASE: Same institution, different accounts, 1-day window."""
    print("\n─── Reconciliation: Same Institution ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn, accounts=[
                ("nfcu_chk", "test", "Checking", "1111", "checking"),
                ("nfcu_sav", "test", "Savings", "2222", "savings"),
            ])
            # Same institution, same day
            _insert_txn(conn, "si_out", "nfcu_chk", "test",
                        "2026-03-10", -200.00, "Transfer", "Transfers")
            _insert_txn(conn, "si_in", "nfcu_sav", "test",
                        "2026-03-10", 200.00, "Transfer", "Transfers")
            conn.commit()

            from dal.reconciliation import reconcile_transfers
            stats = reconcile_transfers(conn, dry_run=False)

            _check("Same-inst pair found",
                   stats["pairs_found"] >= 1, f"stats={stats}")
    finally:
        os.unlink(db)


def test_reconciliation_non_transfer_not_tagged():
    """EDGE CASE: Two unrelated purchases at different banks must NOT be tagged."""
    print("\n─── Reconciliation: Non-Transfer Not Tagged ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn, institutions=[("nfcu", "NFCU"), ("chase", "Chase")],
                       accounts=[
                           ("nfcu_chk", "nfcu", "Checking", "1111", "checking"),
                           ("chase_chk", "chase", "Checking", "3333", "checking"),
                       ])
            # Both debits, same amount, same day — NOT a transfer
            _insert_txn(conn, "nt1", "nfcu_chk", "nfcu",
                        "2026-03-10", -50.00, "RESTAURANT ONE", "Restaurants/Dining")
            _insert_txn(conn, "nt2", "chase_chk", "chase",
                        "2026-03-10", -50.00, "RESTAURANT TWO", "Restaurants/Dining")
            conn.commit()

            from dal.reconciliation import reconcile_transfers
            stats = reconcile_transfers(conn, dry_run=True)

            _check("Two debits same amount: NOT tagged as transfer",
                   stats["pairs_found"] == 0,
                   f"stats={stats}")
    finally:
        os.unlink(db)


def test_reconciliation_idempotent():
    """EDGE CASE: Running reconcile twice should not double-count."""
    print("\n─── Reconciliation: Idempotency ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn, institutions=[("nfcu", "NFCU"), ("fidelity", "Fidelity")],
                       accounts=[
                           ("nfcu_chk", "nfcu", "Checking", "1111", "checking"),
                           ("fid_brok", "fidelity", "Brokerage", "2222", "investment"),
                       ])
            _insert_txn(conn, "idem_out", "nfcu_chk", "nfcu",
                        "2026-03-01", -750.00, "Transfer to Fidelity", "Transfers")
            _insert_txn(conn, "idem_in", "fid_brok", "fidelity",
                        "2026-03-01", 750.00, "Transfer from NFCU", "Transfers")
            conn.commit()

            from dal.reconciliation import reconcile_transfers
            stats1 = reconcile_transfers(conn, dry_run=False)
            _check("First run tags pair", stats1["newly_tagged"] >= 1)

            stats2 = reconcile_transfers(conn, dry_run=False)
            _check("Second run: already_tagged (no new tags)",
                   stats2["newly_tagged"] == 0 and stats2["already_tagged"] >= 1,
                   f"stats2={stats2}")
    finally:
        os.unlink(db)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. INVESTMENTS — removed in P13 investments rebuild
# The four investments tests (decimal_precision, upsert_idempotency,
# portfolio_total_no_data, batch_upsert) exercised dal.investments which
# was deleted.  New tests will arrive alongside the rebuild.
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# RUN ALL
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  Sentry Finance Comprehensive Test Suite")
    print("=" * 60)

    # 1. Derived Metrics
    test_derived_emergency_fund()
    test_derived_emergency_fund_zero_spending()
    test_derived_dti_zero_income()
    test_derived_net_worth_negative()
    test_derived_net_worth_no_investments()
    test_derived_inactive_bnpl_excluded()
    test_derived_interest_cost_currency_parsing()

    # 2. Cash Flow
    test_cash_flow_monthly()
    test_cash_flow_zero_income_savings_rate()
    test_cash_flow_transfers_excluded()
    test_cash_flow_quarterly()
    test_cash_flow_account_filter()
    test_cash_flow_period_detail()

    # 3. Reports
    test_reports_spending_by_category()
    test_reports_flow_data_sankey()
    test_reports_csv_export_null_description()

    # 4. User Rules
    test_user_rules_exact_amount_match()
    test_user_rules_amount_range()
    test_user_rules_invalid_regex()
    test_user_rules_description_regex_match()

    # 5. Freshness
    test_freshness_institution_no_data()
    test_freshness_fresh_data()
    test_freshness_net_worth_data_age()

    # 6. Reconciliation
    test_reconciliation_cross_institution()
    test_reconciliation_date_boundary()
    test_reconciliation_same_institution()
    test_reconciliation_non_transfer_not_tagged()
    test_reconciliation_idempotent()

    # 7. Investments — removed in P13 investments rebuild

    print("\n" + "=" * 60)
    print(f"  Results: {_passed} passed, {_failed} failed")
    if _errors:
        print(f"  Failed: {', '.join(_errors)}")
    print("=" * 60)

    sys.exit(1 if _failed else 0)
