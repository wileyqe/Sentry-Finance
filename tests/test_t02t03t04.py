"""Verification tests for P1-T02, P1-T03, P1-T04.

Date convention: all fixture dates are anchored to date.today() via the
_months_back() / _month_str() / _date_str() / _last_day_str() helpers below.
Tests stay green regardless of when they run — no calendar rot.
"""

import sqlite3
import tempfile
import os
from datetime import date

import pytest
from dateutil.relativedelta import relativedelta

from dal.category_classifications import month_range
from dal.migrations import init_db
from dal.derived import compute_dti_ratio, compute_interest_cost, compute_net_worth_velocity


def _months_back(n: int) -> date:
    """First day of the month n calendar months before today's month."""
    return date.today().replace(day=1) - relativedelta(months=n)


def _month_str(n: int) -> str:
    """YYYY-MM string for the month n months before today's month."""
    return _months_back(n).strftime("%Y-%m")


def _date_str(n: int, day: int = 1) -> str:
    """YYYY-MM-DD string for a specific day in the month n months back."""
    return _months_back(n).replace(day=day).strftime("%Y-%m-%d")


def _last_day_str(n: int) -> str:
    """YYYY-MM-DD for the LAST day of the month n months back."""
    d = _months_back(n)
    return month_range(d.year, d.month)[1]


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


def ins_txn(conn, tid, acct, inst, date, amount, signed, direction, desc, cat, tag=None):
    conn.execute(
        """INSERT INTO transactions
           (id,account_id,institution_id,posting_date,amount,signed_amount,
            direction,description,category,status,transfer_tag)
           VALUES (?,?,?,?,?,?,?,?,?,'posted',?)""",
        (tid, acct, inst, date, amount, signed, direction, desc, cat, tag),
    )


# ── T02 DTI ──────────────────────────────────────────────────────────────────

def test_dti_basic(db):
    """Debt payments sum correctly, loan-side credits excluded, DTI thresholds correct."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('chk','nfcu','Checking','NFCA','checking',1)")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('mort','nfcu','Mortgage','NFMR','loan',1)")

    # Last completed month: $4500 income, $1950 debt payments → 43.3% (critical)
    last_month = _month_str(1)
    ins_txn(db, 't1', 'chk', 'nfcu', _date_str(1, 1), 3000, 3000, 'credit', 'DFAS', 'Military Pension')
    ins_txn(db, 't2', 'chk', 'nfcu', _date_str(1, 1), 1500, 1500, 'credit', 'VA', 'VA Benefits')
    ins_txn(db, 't3', 'chk', 'nfcu', _date_str(1, 5), 1500, -1500, 'debit', 'MORTGAGE', 'Mortgages')
    ins_txn(db, 't4', 'chk', 'nfcu', _date_str(1, 10), 450, -450, 'debit', 'AUTO PMT', 'Loan Payments')
    # Loan-side credit — must NOT be double-counted (account-type filter excludes liability accounts)
    ins_txn(db, 't5', 'mort', 'nfcu', _date_str(1, 5), 1500, 1500, 'credit', 'PAYMENT', 'Mortgages')
    # Transfer — must NOT count as income
    ins_txn(db, 't6', 'chk', 'nfcu', _date_str(1, 15), 500, -500, 'debit', 'XFER', 'Transfers', 'tag-abc')
    db.commit()

    result = compute_dti_ratio(db, months=3)
    target = next((r for r in result if r['month'] == last_month), None)
    assert target is not None
    assert abs(target['debt_payments'] - 1950.0) < 0.01, f"Debt wrong: {target['debt_payments']}"
    assert abs(target['gross_income'] - 4500.0) < 0.01, f"Income wrong: {target['gross_income']}"
    assert target['dti_ratio'] == round(1950 / 4500 * 100, 1)  # 43.3
    assert target['status'] == 'critical'  # 43.3 > 43


def test_dti_includes_paired_transfer_payments(db):
    """Regression: CC and auto-loan payments recorded as paired transfers
    between checking and the liability account MUST count toward debt service.

    Bug history: pre-2026-04-25 the calculation excluded transfer-tagged rows
    entirely, which silently zeroed out CC payments (all paired transfers) and
    most auto-loan payments. Symptom was DTI rendering as 0% across the board.
    """
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('chk','nfcu','Checking','NFCA','checking',1)")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('cc','nfcu','Visa','NFCC','credit_card',1)")

    last_month = _month_str(1)
    ins_txn(db, 't1', 'chk', 'nfcu', _date_str(1, 1), 5000, 5000, 'credit', 'DFAS', 'Military Pension')
    # CC payment: paired transfer between checking and CC. The checking-side
    # debit carries category 'Loan Payments' in canonical seeded data.
    ins_txn(db, 't2', 'chk', 'nfcu', _date_str(1, 25), 1200, -1200, 'debit', 'CC PMT', 'Loan Payments', 'pair-1')
    ins_txn(db, 't3', 'cc',  'nfcu', _date_str(1, 25), 1200,  1200, 'credit', 'PAYMENT', 'Credit Card Payments', 'pair-1')
    db.commit()

    result = compute_dti_ratio(db, months=3)
    target = next((r for r in result if r['month'] == last_month), None)
    assert target is not None
    # Only the checking-side debit counts (account-type filter excludes the CC credit)
    assert abs(target['debt_payments'] - 1200.0) < 0.01, (
        f"Paired-transfer CC payment not counted: got {target['debt_payments']}"
    )
    assert abs(target['gross_income'] - 5000.0) < 0.01
    assert target['dti_ratio'] == 24.0
    assert target['status'] == 'healthy'  # 24% < 28


def test_dti_healthy(db):
    """Low debt → healthy status."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('chk','nfcu','Checking','NFCA','checking',1)")
    last_month = _month_str(1)
    ins_txn(db, 't1', 'chk', 'nfcu', _date_str(1, 1), 10000, 10000, 'credit', 'DFAS', 'Military Pension')
    ins_txn(db, 't2', 'chk', 'nfcu', _date_str(1, 5), 500, -500, 'debit', 'MORTGAGE', 'Mortgages')
    db.commit()
    result = compute_dti_ratio(db, months=3)
    target = next((r for r in result if r['month'] == last_month), None)
    assert target and target['status'] == 'healthy'  # 5% DTI


def test_dti_zero_income(db):
    """Zero income → None DTI and None status."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('a1','nfcu','Checking','NFCA','checking',1)")
    last_month = _month_str(1)
    ins_txn(db, 't1', 'a1', 'nfcu', _date_str(1, 5), 500, -500, 'debit', 'MORTGAGE', 'Mortgages')
    db.commit()
    result = compute_dti_ratio(db, months=3)
    target = next((r for r in result if r['month'] == last_month), None)
    assert target and target['dti_ratio'] is None
    assert target['status'] is None


def test_dti_derived_summaries(db):
    """DTI stored in derived_summaries per month."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('chk','nfcu','Checking','NFCA','checking',1)")
    last_month = _month_str(1)
    ins_txn(db, 't1', 'chk', 'nfcu', _date_str(1, 1), 4500, 4500, 'credit', 'DFAS', 'Military Pension')
    ins_txn(db, 't2', 'chk', 'nfcu', _date_str(1, 5), 1500, -1500, 'debit', 'MORTGAGE', 'Mortgages')
    db.commit()
    compute_dti_ratio(db, months=3)
    row = db.execute(
        "SELECT value FROM derived_summaries WHERE scope='global' AND metric='dti_ratio' AND period=?",
        (last_month,),
    ).fetchone()
    assert row is not None
    assert abs(row['value'] - round(1500 / 4500 * 100, 1)) < 0.01


# ── T03 Interest Cost ─────────────────────────────────────────────────────────

def test_interest_cost_loan_details(db):
    """Prefers loan_details over transactions for YTD interest."""
    y = date.today().year
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('affirm','Affirm')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('mort','nfcu','Mortgage','NFMR','loan',1)")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('auto','nfcu','Auto Loan','NFAL','loan',1)")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('hysa','affirm','HYSA','0001','savings',1)")
    # Mortgage from loan_details — anchored to January of current year (always inside YTD)
    db.execute(
        "INSERT INTO loan_details (account_id,field_name,field_value,as_of) VALUES ('mort','Interest Paid YTD','4200.00',?)",
        (f'{y}-01-18',),
    )
    # Auto from transactions — January of current year
    ins_txn(db, 't1', 'auto', 'nfcu', f'{y}-01-15', 85, -85, 'debit', 'INTEREST', 'Interest')
    ins_txn(db, 't2', 'auto', 'nfcu', f'{y}-01-16', 83, -83, 'debit', 'INTEREST', 'Interest')
    # Interest earned on HYSA
    ins_txn(db, 't3', 'hysa', 'affirm', f'{y}-01-17', 25, 25, 'credit', 'Interest', 'Interest')
    db.commit()

    result = compute_interest_cost(db)
    mort = next(a for a in result['by_account'] if 'Mortgage' in a['account_name'])
    auto = next(a for a in result['by_account'] if 'Auto' in a['account_name'])

    assert mort['ytd_interest'] == 4200.0
    assert mort['source'] == 'loan_details'
    assert abs(auto['ytd_interest'] - 168.0) < 0.01
    assert auto['source'] == 'transactions'
    assert abs(result['ytd_total'] - 4368.0) < 0.01
    assert abs(result['interest_earned'] - 25.0) < 0.01
    assert abs(result['net_interest'] - (25.0 - 4368.0)) < 0.01


def test_interest_cost_derived_summaries(db):
    """YTD total stored in derived_summaries."""
    y = date.today().year
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('mort','nfcu','Mortgage','NFMR','loan',1)")
    db.execute(
        "INSERT INTO loan_details (account_id,field_name,field_value,as_of) VALUES ('mort','ytd_interest','1000.00',?)",
        (f'{y}-01-15',),
    )
    db.commit()
    compute_interest_cost(db)
    row = db.execute(
        "SELECT value FROM derived_summaries WHERE scope='global' AND metric='ytd_interest_cost'"
    ).fetchone()
    assert row and abs(row['value'] - 1000.0) < 0.01


def test_interest_cost_no_data(db):
    """Empty DB returns zeros gracefully."""
    result = compute_interest_cost(db)
    assert result['ytd_total'] == 0.0
    assert result['interest_earned'] == 0.0
    assert result['by_account'] == []


# ── T03 Interest Cost — transactions-path edge cases (AI-009) ────────────────
#
# `compute_interest_cost` falls back to summing `transactions` rows when
# loan_details has no YTD KV. The seeder always populates the KV, so the
# transactions path was structurally untested by the synthetic dataset.
# These tests pin the four filters in the fallback SQL:
#   1. category match  — '%interest%' OR '%finance charge%'
#   2. year filter     — strftime('%Y', posting_date) = current year
#   3. status filter   — status = 'posted'
#   4. monthly_breakdown — derived from the same transactions path

def test_interest_cost_finance_charge_category_matches(db):
    """`Finance Charge` category counts toward the transactions-path total."""
    y = date.today().year
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('summit','Summit')")
    db.execute(
        "INSERT INTO accounts (id,institution_id,name,last4,type,is_active) "
        "VALUES ('cc','summit','Visa','SCAA','credit_card',1)"
    )
    # Two debits — one with category 'Interest', one with 'Finance Charge'
    ins_txn(db, 't1', 'cc', 'summit', f'{y}-02-12', 22.50, -22.50, 'Debit', 'INTEREST CHARGE', 'Interest')
    ins_txn(db, 't2', 'cc', 'summit', f'{y}-03-12', 18.30, -18.30, 'Debit', 'FINANCE CHARGE', 'Finance Charge')
    db.commit()

    result = compute_interest_cost(db)
    cc = next(a for a in result['by_account'] if a['account_id'] == 'cc')
    assert cc['source'] == 'transactions'
    assert abs(cc['ytd_interest'] - 40.80) < 0.01


def test_interest_cost_excludes_prior_year_transactions(db):
    """A row dated in the previous calendar year does NOT leak into YTD."""
    y = date.today().year
    prev = y - 1
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('summit','Summit')")
    db.execute(
        "INSERT INTO accounts (id,institution_id,name,last4,type,is_active) "
        "VALUES ('cc','summit','Visa','SCAA','credit_card',1)"
    )
    # Last year's interest — must NOT count
    ins_txn(db, 't0', 'cc', 'summit', f'{prev}-12-15', 99.00, -99.00, 'Debit', 'INTEREST', 'Interest')
    # Current-year row — must count
    ins_txn(db, 't1', 'cc', 'summit', f'{y}-01-15', 12.00, -12.00, 'Debit', 'INTEREST', 'Interest')
    db.commit()

    result = compute_interest_cost(db)
    cc = next(a for a in result['by_account'] if a['account_id'] == 'cc')
    assert cc['source'] == 'transactions'
    assert abs(cc['ytd_interest'] - 12.00) < 0.01


def test_interest_cost_excludes_pending_transactions(db):
    """`status='pending'` rows are excluded from the transactions path."""
    y = date.today().year
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('summit','Summit')")
    db.execute(
        "INSERT INTO accounts (id,institution_id,name,last4,type,is_active) "
        "VALUES ('cc','summit','Visa','SCAA','credit_card',1)"
    )
    # Posted row — counts
    ins_txn(db, 't1', 'cc', 'summit', f'{y}-02-10', 30.00, -30.00, 'Debit', 'INTEREST', 'Interest')
    # Pending row — must NOT count (ins_txn hardcodes 'posted', so write directly)
    db.execute(
        """INSERT INTO transactions
           (id,account_id,institution_id,posting_date,amount,signed_amount,
            direction,description,category,status)
           VALUES (?,?,?,?,?,?,?,?,?, 'pending')""",
        ('t2', 'cc', 'summit', f'{y}-03-10', 99.00, -99.00, 'Debit', 'INTEREST', 'Interest'),
    )
    db.commit()

    result = compute_interest_cost(db)
    cc = next(a for a in result['by_account'] if a['account_id'] == 'cc')
    assert cc['source'] == 'transactions'
    assert abs(cc['ytd_interest'] - 30.00) < 0.01


def test_interest_cost_monthly_breakdown_from_transactions(db):
    """`monthly_breakdown` populates from the transactions fallback path."""
    y = date.today().year
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('summit','Summit')")
    db.execute(
        "INSERT INTO accounts (id,institution_id,name,last4,type,is_active) "
        "VALUES ('cc','summit','Visa','SCAA','credit_card',1)"
    )
    # Three months of interest — Jan / Feb / Mar
    ins_txn(db, 't1', 'cc', 'summit', f'{y}-01-15', 10.00, -10.00, 'Debit', 'INTEREST', 'Interest')
    ins_txn(db, 't2', 'cc', 'summit', f'{y}-02-15', 20.00, -20.00, 'Debit', 'INTEREST', 'Interest')
    ins_txn(db, 't3', 'cc', 'summit', f'{y}-03-15', 30.00, -30.00, 'Debit', 'FINANCE CHARGE', 'Finance Charge')
    db.commit()

    result = compute_interest_cost(db)
    months = {row['month']: row['total_interest'] for row in result['monthly_breakdown']}
    assert months[f'{y}-01'] == 10.00
    assert months[f'{y}-02'] == 20.00
    assert months[f'{y}-03'] == 30.00


# ── T04 Net Worth Velocity ────────────────────────────────────────────────────

def test_velocity_steady_growth(db):
    """15 months of $1000/mo growth → steady trend, correct metrics."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('chk','nfcu','Checking','NFCB','checking',1)")
    base = 200000.0
    # Walk back from current month so the latest snapshot lands in month 0
    # (eliminates the carry-forward phantom that breaks mom_change).
    for i in range(15):
        months_offset = 14 - i  # i=0 → offset 14 (oldest); i=14 → offset 0 (current)
        db.execute(
            'INSERT INTO balance_snapshots (account_id,balance,as_of) VALUES (?,?,?)',
            ('chk', base + i * 1000, _last_day_str(months_offset)),
        )
    db.commit()

    result = compute_net_worth_velocity(db)
    assert result['mom_change'] == 1000.0
    assert result['rolling_3m_monthly_avg'] == 1000.0
    assert result['rolling_12m_monthly_avg'] == 1000.0
    assert result['trend'] == 'steady'
    assert len(result['history']) > 0


def test_velocity_insufficient_data(db):
    """Single month → no MoM, insufficient_data trend."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('a1','nfcu','Checking','NFCB','checking',1)")
    # Single snapshot in the current month → CTE returns 1 entry, no carry-forward.
    db.execute(
        "INSERT INTO balance_snapshots (account_id,balance,as_of) VALUES ('a1',10000,?)",
        (_date_str(0, 1),),
    )
    db.commit()
    result = compute_net_worth_velocity(db)
    assert result['mom_change'] is None
    assert result['rolling_3m_change'] is None
    assert result['trend'] == 'insufficient_data'


def test_velocity_declining(db):
    """Negative 3m avg → declining trend."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('a1','nfcu','Checking','NFCB','checking',1)")
    # Walk back from current month: i=0 → offset 5 (oldest); i=5 → offset 0 (current).
    # Balances decrease by 500/mo so the rolling 3m average is negative → declining.
    for i in range(6):
        months_offset = 5 - i
        db.execute(
            'INSERT INTO balance_snapshots (account_id,balance,as_of) VALUES (?,?,?)',
            ('a1', 200000 - i * 500, _date_str(months_offset, 1)),
        )
    db.commit()
    result = compute_net_worth_velocity(db)
    assert result['trend'] == 'declining'


def test_velocity_derived_summaries(db):
    """MoM change stored in derived_summaries."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('chk','nfcu','Checking','NFCB','checking',1)")
    base = 200000.0
    # Same walk-back pattern as test_velocity_steady_growth.
    for i in range(15):
        months_offset = 14 - i
        db.execute(
            'INSERT INTO balance_snapshots (account_id,balance,as_of) VALUES (?,?,?)',
            ('chk', base + i * 1000, _last_day_str(months_offset)),
        )
    db.commit()
    compute_net_worth_velocity(db)
    row = db.execute(
        "SELECT value FROM derived_summaries WHERE scope='global' AND metric='nw_mom_change'"
    ).fetchone()
    assert row and row['value'] == 1000.0
