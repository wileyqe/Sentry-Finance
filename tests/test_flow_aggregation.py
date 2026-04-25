"""tests/test_flow_aggregation.py — compute_period_totals correctness.

Covers the load-bearing invariants for the unified headline aggregator
(`dal.flow_aggregation.compute_period_totals`) introduced in the
"Cash Flow ↔ Reports Alignment + Spending Semantics Overhaul" plan
(Stage 1):

  * Bucket invariant — drift_cents == 0 always (the residual model
    guarantees it mathematically; this test catches a future refactor
    that breaks the identity).
  * CC double-count — a household with $X CC merchant purchases AND
    $X CC payment in the same window must count $X (not $2X) toward
    spending, and surface the purchase as debt_accumulated and the
    payment as debt_paid_down.
  * Mortgage decomposition — a $1500 mortgage with split P/I/E of
    $300/$1000/$200 contributes $1200 to spending (interest+escrow)
    and $300 to stored_illiquid (principal); without a split, the
    full $1500 is consumed.
  * Owner scoping — an owner with no accounts returns zero across
    all metrics; an owner with all accounts equals the household.
  * Net debt change semantics — accumulated > paid_down → positive
    (added debt); paid_down > accumulated → negative (paid down).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import date

import pytest
from dateutil.relativedelta import relativedelta

from dal.migrations import init_db
from dal.flow_aggregation import compute_period_totals


# ── Fixtures and helpers ─────────────────────────────────────────────────────


def _months_back(n: int) -> date:
    return date.today().replace(day=1) - relativedelta(months=n)


def _month_window(n: int) -> tuple[str, str]:
    """Return (start_date, end_date) ISO strings for the month n months back."""
    d = _months_back(n)
    last_day = (d.replace(day=28) + relativedelta(days=4)).replace(day=1) - relativedelta(days=1)
    return d.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d")


def _date_str(n: int, day: int = 1) -> str:
    return _months_back(n).replace(day=day).strftime("%Y-%m-%d")


@pytest.fixture
def db():
    f = tempfile.NamedTemporaryFile(delete=False)
    path = f.name
    f.close()
    init_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
    try:
        os.remove(path)
    except OSError:
        pass


def ins_txn(conn, tid, acct, inst, dt, amount, signed, direction, desc, cat, tag=None):
    conn.execute(
        """INSERT INTO transactions
           (id, account_id, institution_id, posting_date, amount, signed_amount,
            direction, description, category, status, transfer_tag)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted', ?)""",
        (tid, acct, inst, dt, amount, signed, direction, desc, cat, tag),
    )


def make_household(conn, *, with_amy: bool = False):
    """Standard household fixture: one institution, checking + credit_card +
    mortgage loan accounts. Optionally adds an Amy owner with no accounts."""
    conn.execute("INSERT INTO institutions (id, display_name) VALUES ('nfcu', 'NFCU')")
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active, owner_id) "
        "VALUES ('chk', 'nfcu', 'Checking', 'CHK0', 'checking', 1, 'quintin')"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active, owner_id) "
        "VALUES ('cc', 'nfcu', 'Visa', 'CC00', 'credit_card', 1, 'quintin')"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active, owner_id) "
        "VALUES ('mort', 'nfcu', 'Mortgage', 'MR00', 'loan', 1, 'quintin')"
    )
    if with_amy:
        conn.execute(
            "INSERT INTO owners (id, display_name) VALUES ('amy', 'Amy')"
        )
    conn.commit()


# ── Tests ────────────────────────────────────────────────────────────────────


def test_drift_zero_for_empty_window(db):
    """Empty database returns zero everywhere with drift==0."""
    make_household(db)
    start, end = _month_window(1)
    r = compute_period_totals(db, start_date=start, end_date=end)
    assert r["drift_cents"] == 0
    assert r["income_cents"] == 0
    assert r["spending_cents"] == 0
    assert r["debt_service_cents"] == 0
    assert r["debt_accumulated_cents"] == 0
    assert r["debt_paid_down_cents"] == 0
    assert r["net_debt_change_cents"] == 0


def test_drift_zero_with_mixed_activity(db):
    """Realistic mixed flows — drift must remain zero."""
    make_household(db)
    start, end = _month_window(1)
    # Income deposit
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 1), 5000, 5000, "credit", "PAY", "Paychecks/Salary")
    # Ordinary spending on debit
    ins_txn(db, "t2", "chk", "nfcu", _date_str(1, 5), 200, -200, "debit", "GROC", "Groceries")
    # CC merchant purchase (creates liability — should be debt_accumulated, NOT spending)
    ins_txn(db, "t3", "cc", "nfcu", _date_str(1, 6), 100, -100, "debit", "GROC CC", "Groceries")
    # CC payment paired transfer (cash out — IS spending)
    ins_txn(db, "t4", "chk", "nfcu", _date_str(1, 25), 80, -80, "debit", "CC PMT", "Loan Payments", "tag-cc")
    ins_txn(db, "t5", "cc", "nfcu", _date_str(1, 25), 80, 80, "credit", "PAYMENT", "Credit Card Payments", "tag-cc")
    db.commit()
    r = compute_period_totals(db, start_date=start, end_date=end)
    assert r["drift_cents"] == 0


def test_cc_no_double_count_under_d1b(db):
    """Critical regression: a CC merchant purchase + later CC payment in
    the same window must not be double-counted as spending. Under D1=B
    (cash-out lens), only the cash-side outflow (CC payment) counts as
    spending. The CC purchase shows up under debt_accumulated."""
    make_household(db)
    start, end = _month_window(1)
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 1), 5000, 5000, "credit", "PAY", "Paychecks/Salary")
    # Merchant swipe on CC: $100. Creates a liability, not a cash event.
    ins_txn(db, "t2", "cc", "nfcu", _date_str(1, 5), 100, -100, "debit", "GROC CC", "Groceries")
    # CC payment from checking: $100. Cash event — counts as spending.
    ins_txn(db, "t3", "chk", "nfcu", _date_str(1, 25), 100, -100, "debit", "CC PMT", "Loan Payments", "tag-1")
    ins_txn(db, "t4", "cc", "nfcu", _date_str(1, 25), 100, 100, "credit", "PAY", "Credit Card Payments", "tag-1")
    db.commit()
    r = compute_period_totals(db, start_date=start, end_date=end)
    # Spending should be $100 (the CC payment), NOT $200 (purchase + payment).
    assert r["spending_cents"] == 10000, f"Expected $100 spending, got ${r['spending_cents']/100}"
    # The purchase shows up here:
    assert r["debt_accumulated_cents"] == 10000
    # The CC payment shows up here:
    assert r["debt_paid_down_cents"] == 10000
    # Net change: zero (purchased and paid off in same period)
    assert r["net_debt_change_cents"] == 0
    assert r["drift_cents"] == 0


def test_net_debt_accumulation_positive(db):
    """Charge $200 on CC, only pay $50 of prior balance → net debt up $150."""
    make_household(db)
    start, end = _month_window(1)
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 1), 5000, 5000, "credit", "PAY", "Paychecks/Salary")
    ins_txn(db, "t2", "cc", "nfcu", _date_str(1, 10), 200, -200, "debit", "SHOPPING", "Shopping")
    ins_txn(db, "t3", "chk", "nfcu", _date_str(1, 25), 50, -50, "debit", "CC PMT", "Loan Payments", "tag-1")
    ins_txn(db, "t4", "cc", "nfcu", _date_str(1, 25), 50, 50, "credit", "PAY", "Credit Card Payments", "tag-1")
    db.commit()
    r = compute_period_totals(db, start_date=start, end_date=end)
    assert r["debt_accumulated_cents"] == 20000
    assert r["debt_paid_down_cents"] == 5000
    assert r["net_debt_change_cents"] == 15000


def test_net_debt_paydown_negative(db):
    """Charge $50, pay $200 of prior balance → net debt down $150."""
    make_household(db)
    start, end = _month_window(1)
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 1), 5000, 5000, "credit", "PAY", "Paychecks/Salary")
    ins_txn(db, "t2", "cc", "nfcu", _date_str(1, 10), 50, -50, "debit", "GROC", "Groceries")
    ins_txn(db, "t3", "chk", "nfcu", _date_str(1, 25), 200, -200, "debit", "CC PMT", "Loan Payments", "tag-1")
    ins_txn(db, "t4", "cc", "nfcu", _date_str(1, 25), 200, 200, "credit", "PAY", "Credit Card Payments", "tag-1")
    db.commit()
    r = compute_period_totals(db, start_date=start, end_date=end)
    assert r["debt_accumulated_cents"] == 5000
    assert r["debt_paid_down_cents"] == 20000
    assert r["net_debt_change_cents"] == -15000


def test_mortgage_split_routes_principal_to_illiquid(db):
    """A $1500 mortgage with split P=300/I=1000/E=200 puts $1200 in
    spending (interest+escrow → CONSUMED) and $300 in stored_illiquid
    (principal → STORED_ILLIQUID). Spending breakdown shows the
    interest+escrow as 'Mortgage Interest & Escrow'."""
    make_household(db)
    start, end = _month_window(1)
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 1), 5000, 5000, "credit", "PAY", "Paychecks/Salary")
    ins_txn(db, "t2", "chk", "nfcu", _date_str(1, 5), 1500, -1500, "debit", "MORTGAGE", "Mortgages")
    db.execute(
        "INSERT INTO loan_payment_splits (transaction_id, principal_cents, interest_cents, escrow_cents, method) "
        "VALUES ('t2', 30000, 100000, 20000, 'amortization')"
    )
    db.commit()
    r = compute_period_totals(db, start_date=start, end_date=end)
    assert r["spending_cents"] == 120000, f"Expected $1200, got ${r['spending_cents']/100}"
    assert r["stored_illiquid_cents"] == 30000
    assert r["debt_service_cents"] == 120000  # interest+escrow = $1200
    assert r["debt_paid_down_cents"] == 30000  # principal counted as paid-down
    # Spending breakdown should have the synthesized Mortgage Interest & Escrow row
    cats = {c["category"]: c["total_cents"] for c in r["spending_breakdown"]}
    assert cats.get("Mortgage Interest & Escrow") == 120000
    # Mortgages itself should NOT be in the breakdown (avoids double-count)
    assert "Mortgages" not in cats and "Mortgage" not in cats
    assert r["drift_cents"] == 0


def test_mortgage_unsplit_full_payment_consumed(db):
    """Without a split row, the entire mortgage payment falls back to
    CONSUMED so the bucket invariant still holds. Principal-as-savings
    is not surfaced (we don't know the split)."""
    make_household(db)
    start, end = _month_window(1)
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 1), 5000, 5000, "credit", "PAY", "Paychecks/Salary")
    ins_txn(db, "t2", "chk", "nfcu", _date_str(1, 5), 1500, -1500, "debit", "MORTGAGE", "Mortgages")
    # No loan_payment_splits row inserted
    db.commit()
    r = compute_period_totals(db, start_date=start, end_date=end)
    assert r["spending_cents"] == 150000  # full $1500
    assert r["stored_illiquid_cents"] == 0
    # debt_service catches the unsplit case via the mortgage_splits fallback
    # path (interest_cents=total_cents in the unsplit fallback)
    assert r["debt_service_cents"] == 150000
    assert r["drift_cents"] == 0


def test_owner_scoping_amy_with_no_accounts(db):
    """Owner with no accounts returns zero across the board."""
    make_household(db, with_amy=True)
    start, end = _month_window(1)
    # Quintin's transactions
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 1), 5000, 5000, "credit", "PAY", "Paychecks/Salary")
    ins_txn(db, "t2", "chk", "nfcu", _date_str(1, 5), 200, -200, "debit", "GROC", "Groceries")
    db.commit()
    r_amy = compute_period_totals(db, start_date=start, end_date=end, owner_id="amy")
    assert r_amy["income_cents"] == 0
    assert r_amy["spending_cents"] == 0
    assert r_amy["debt_service_cents"] == 0
    assert r_amy["debt_accumulated_cents"] == 0
    assert r_amy["debt_paid_down_cents"] == 0
    assert r_amy["net_debt_change_cents"] == 0
    assert r_amy["drift_cents"] == 0


def test_owner_scoping_household_equals_sum_of_owners(db):
    """Household totals must equal the sum of per-owner totals (when
    owners don't share accounts)."""
    # Two separate owner households for true non-overlap
    db.execute("INSERT INTO institutions (id, display_name) VALUES ('nfcu', 'NFCU')")
    db.execute("INSERT INTO owners (id, display_name) VALUES ('alice', 'Alice')")
    db.execute("INSERT INTO owners (id, display_name) VALUES ('bob', 'Bob')")
    db.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active, owner_id) "
        "VALUES ('a_chk', 'nfcu', 'Alice Chk', 'A001', 'checking', 1, 'alice')"
    )
    db.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active, owner_id) "
        "VALUES ('b_chk', 'nfcu', 'Bob Chk', 'B001', 'checking', 1, 'bob')"
    )
    start, end = _month_window(1)
    ins_txn(db, "t1", "a_chk", "nfcu", _date_str(1, 1), 3000, 3000, "credit", "PAY", "Paychecks/Salary")
    ins_txn(db, "t2", "a_chk", "nfcu", _date_str(1, 5), 100, -100, "debit", "GROC", "Groceries")
    ins_txn(db, "t3", "b_chk", "nfcu", _date_str(1, 1), 2000, 2000, "credit", "PAY", "Paychecks/Salary")
    ins_txn(db, "t4", "b_chk", "nfcu", _date_str(1, 5), 50, -50, "debit", "GROC", "Groceries")
    db.commit()
    r_house = compute_period_totals(db, start_date=start, end_date=end)
    r_alice = compute_period_totals(db, start_date=start, end_date=end, owner_id="alice")
    r_bob = compute_period_totals(db, start_date=start, end_date=end, owner_id="bob")
    assert r_house["income_cents"] == r_alice["income_cents"] + r_bob["income_cents"]
    assert r_house["spending_cents"] == r_alice["spending_cents"] + r_bob["spending_cents"]
    assert r_house["net_cents"] == r_alice["net_cents"] + r_bob["net_cents"]
    assert r_house["drift_cents"] == 0


def test_savings_rate_none_when_zero_income(db):
    """savings_rate must be None (not 0 or NaN) when income == 0."""
    make_household(db)
    start, end = _month_window(1)
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 5), 200, -200, "debit", "GROC", "Groceries")
    db.commit()
    r = compute_period_totals(db, start_date=start, end_date=end)
    assert r["income_cents"] == 0
    assert r["savings_rate"] is None


def test_payroll_grossup_unmatched_adds_full_gross(db):
    """An unmatched payroll snapshot (no deposit transaction to tie to)
    contributes its full gross to income and its withholdings to spending.
    The implied net deposit lands as STORED_LIQUID residual."""
    make_household(db)
    start, end = _month_window(1)
    pay_period = _month_window(1)[0][:7]  # YYYY-MM
    # Schema: payroll_snapshots stores dollars (REAL), not cents.
    # Gross $5000, withholdings: federal $600 + state $200 + health $150 +
    # dental_vision $50 = $1000 total. Net = $4000.
    db.execute(
        """INSERT INTO payroll_snapshots
           (owner_id, pay_period, source, gross_pay, federal_tax, state_tax,
            sbp_premium, health_insurance, dental_vision, other_deductions, net_pay)
           VALUES ('quintin', ?, 'unmatchable_label',
                   5000.00, 600.00, 200.00, 0.00, 150.00, 50.00, 0.00, 4000.00)""",
        (pay_period,),
    )
    db.commit()
    r = compute_period_totals(db, start_date=start, end_date=end)
    # Income should reflect the full gross ($5000)
    assert r["income_cents"] == 500000, f"Expected $5000 income, got ${r['income_cents']/100}"
    # Withholdings ($600 + $200 + $150 + $50 = $1000) should be in spending
    assert r["spending_cents"] == 100000, f"Expected $1000 spending, got ${r['spending_cents']/100}"
    # Implied net deposit ($5000 - $1000 = $4000) lands as liquid residual
    assert r["stored_liquid_cents"] == 400000
    assert r["drift_cents"] == 0
