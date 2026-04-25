"""tests/test_cashflow_reports_parity.py — Cash Flow ↔ Reports parity.

The user's pain point #2 in the spending-semantics overhaul plan:

    "With a 'marginally close' comparison (last 30 day-reports) &
    (April so far-cash flow), the income and expenses are wildly
    different. Something is being tallied poorly or conveyed poorly.
    Make them consistent."

PR2 fixes this by routing both pages through the unified
``compute_period_totals`` aggregator. This test wall enforces the
contract: for any window, the headline numbers returned by
``dal.cash_flow.get_period_detail`` and ``dal.reports.get_flow_data``
MUST agree to the cent on income, spending, net, savings_rate, and the
four debt-* fields.

Without this wall, a future drift between the two callers would re-open
the divergence the user complained about.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import date

import pytest
from dateutil.relativedelta import relativedelta

from dal.migrations import init_db
from dal.cash_flow import get_period_detail
from dal.reports import get_flow_data


# ── Fixture ──────────────────────────────────────────────────────────────────


def _months_back(n: int) -> date:
    return date.today().replace(day=1) - relativedelta(months=n)


def _month_window(n: int) -> tuple[str, str]:
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
        conn.execute("INSERT INTO owners (id, display_name) VALUES ('amy', 'Amy')")
    conn.commit()


def _assert_parity(detail: dict, flow: dict, *, label: str = ""):
    """Assert headline numbers match between get_period_detail and get_flow_data."""
    prefix = f"[{label}] " if label else ""
    # Cash flow page returns "income"/"spending"; reports page returns
    # "total_income"/"total_spending" — same number, different key. Map.
    pairs = [
        ("income", "total_income"),
        ("spending", "total_spending"),
        ("net", "net"),
        ("savings_rate", "savings_rate"),
        ("debt_service", "debt_service"),
        ("debt_accumulated", "debt_accumulated"),
        ("debt_paid_down", "debt_paid_down"),
        ("net_debt_change", "net_debt_change"),
    ]
    for cf_key, rp_key in pairs:
        cf_val = detail[cf_key]
        rp_val = flow[rp_key]
        assert cf_val == rp_val, (
            f"{prefix}field divergence: cash_flow.{cf_key}={cf_val} != "
            f"reports.{rp_key}={rp_val}"
        )


# ── Tests ────────────────────────────────────────────────────────────────────


def test_parity_empty_window(db):
    make_household(db)
    start, end = _month_window(1)
    detail = get_period_detail(db, start, end)
    flow = get_flow_data(db, start_date=start, end_date=end)
    _assert_parity(detail, flow, label="empty")


def test_parity_with_ordinary_spending(db):
    make_household(db)
    start, end = _month_window(1)
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 1), 5000, 5000, "credit", "PAY", "Paychecks/Salary")
    ins_txn(db, "t2", "chk", "nfcu", _date_str(1, 5), 200, -200, "debit", "GROC", "Groceries")
    ins_txn(db, "t3", "chk", "nfcu", _date_str(1, 6), 80, -80, "debit", "DINING", "Restaurants/Dining")
    db.commit()
    detail = get_period_detail(db, start, end)
    flow = get_flow_data(db, start_date=start, end_date=end)
    _assert_parity(detail, flow, label="ordinary")


def test_parity_with_cc_purchase_and_payment(db):
    """The hardest case for divergence — paired transfers + CC merchant
    purchases, all the moving parts of the cash-out lens."""
    make_household(db)
    start, end = _month_window(1)
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 1), 5000, 5000, "credit", "PAY", "Paychecks/Salary")
    ins_txn(db, "t2", "cc",  "nfcu", _date_str(1, 5), 100, -100, "debit", "GROC CC", "Groceries")
    ins_txn(db, "t3", "chk", "nfcu", _date_str(1, 25), 100, -100, "debit", "CC PMT", "Loan Payments", "tag-1")
    ins_txn(db, "t4", "cc",  "nfcu", _date_str(1, 25), 100, 100, "credit", "PAY", "Credit Card Payments", "tag-1")
    db.commit()
    detail = get_period_detail(db, start, end)
    flow = get_flow_data(db, start_date=start, end_date=end)
    _assert_parity(detail, flow, label="cc-cycle")


def test_parity_with_mortgage_split(db):
    """Mortgage with loan_payment_splits: principal→illiquid, interest+escrow→spending."""
    make_household(db)
    start, end = _month_window(1)
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 1), 5000, 5000, "credit", "PAY", "Paychecks/Salary")
    ins_txn(db, "t2", "chk", "nfcu", _date_str(1, 5), 1500, -1500, "debit", "MORTGAGE", "Mortgages")
    db.execute(
        "INSERT INTO loan_payment_splits (transaction_id, principal_cents, interest_cents, escrow_cents, method) "
        "VALUES ('t2', 30000, 100000, 20000, 'amortization')"
    )
    db.commit()
    detail = get_period_detail(db, start, end)
    flow = get_flow_data(db, start_date=start, end_date=end)
    _assert_parity(detail, flow, label="mortgage-split")


def test_parity_owner_scoped(db):
    """Per-owner scoping must agree across both pages."""
    make_household(db, with_amy=True)
    start, end = _month_window(1)
    ins_txn(db, "t1", "chk", "nfcu", _date_str(1, 1), 5000, 5000, "credit", "PAY", "Paychecks/Salary")
    ins_txn(db, "t2", "chk", "nfcu", _date_str(1, 5), 200, -200, "debit", "GROC", "Groceries")
    db.commit()
    for owner in (None, "quintin", "amy"):
        detail = get_period_detail(db, start, end, owner_id=owner)
        flow = get_flow_data(db, start_date=start, end_date=end, owner_id=owner)
        _assert_parity(detail, flow, label=f"owner={owner}")


def test_parity_with_payroll_grossup(db):
    """Payroll snapshot drives gross-up on income; both pages must reflect it."""
    make_household(db)
    start, end = _month_window(1)
    pay_period = _month_window(1)[0][:7]
    db.execute(
        """INSERT INTO payroll_snapshots
           (owner_id, pay_period, source, gross_pay, federal_tax, state_tax,
            sbp_premium, health_insurance, dental_vision, other_deductions, net_pay)
           VALUES ('quintin', ?, 'unmatchable', 5000, 600, 200, 0, 150, 50, 0, 4000)""",
        (pay_period,),
    )
    db.commit()
    detail = get_period_detail(db, start, end)
    flow = get_flow_data(db, start_date=start, end_date=end)
    _assert_parity(detail, flow, label="grossup")
