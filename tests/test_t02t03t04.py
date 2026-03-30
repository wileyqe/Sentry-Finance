"""Verification tests for P1-T02, P1-T03, P1-T04."""

import sqlite3
import tempfile
import os
import calendar as cal

import pytest
from dal.migrations import init_db
from dal.derived import compute_dti_ratio, compute_interest_cost, compute_net_worth_velocity


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
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('chk','nfcu','Checking','0459','checking',1)")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('mort','nfcu','Mortgage','6167','loan',1)")

    # Feb 2026: $4500 income, $1950 debt payments → 43.3% (critical)
    ins_txn(db, 't1', 'chk', 'nfcu', '2026-02-01', 3000, 3000, 'credit', 'DFAS', 'Military Pension')
    ins_txn(db, 't2', 'chk', 'nfcu', '2026-02-01', 1500, 1500, 'credit', 'VA', 'VA Benefits')
    ins_txn(db, 't3', 'chk', 'nfcu', '2026-02-05', 1500, -1500, 'debit', 'MORTGAGE', 'Mortgage')
    ins_txn(db, 't4', 'chk', 'nfcu', '2026-02-10', 450, -450, 'debit', 'AUTO PMT', 'Auto Loan')
    # Loan-side credit — must NOT be double-counted
    ins_txn(db, 't5', 'mort', 'nfcu', '2026-02-05', 1500, 1500, 'credit', 'PAYMENT', 'Mortgage')
    # Transfer — must NOT count as income
    ins_txn(db, 't6', 'chk', 'nfcu', '2026-02-15', 500, -500, 'debit', 'XFER', 'Transfers', 'tag-abc')
    db.commit()

    result = compute_dti_ratio(db, months=3)
    feb = next((r for r in result if r['month'] == '2026-02'), None)
    assert feb is not None
    assert abs(feb['debt_payments'] - 1950.0) < 0.01, f"Debt wrong: {feb['debt_payments']}"
    assert abs(feb['gross_income'] - 4500.0) < 0.01, f"Income wrong: {feb['gross_income']}"
    assert feb['dti_ratio'] == round(1950 / 4500 * 100, 1)  # 43.3
    assert feb['status'] == 'critical'  # 43.3 > 43


def test_dti_healthy(db):
    """Low debt → healthy status."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('chk','nfcu','Checking','0459','checking',1)")
    ins_txn(db, 't1', 'chk', 'nfcu', '2026-02-01', 10000, 10000, 'credit', 'DFAS', 'Military Pension')
    ins_txn(db, 't2', 'chk', 'nfcu', '2026-02-05', 500, -500, 'debit', 'MORTGAGE', 'Mortgage')
    db.commit()
    result = compute_dti_ratio(db, months=3)
    feb = next((r for r in result if r['month'] == '2026-02'), None)
    assert feb and feb['status'] == 'healthy'  # 5% DTI


def test_dti_zero_income(db):
    """Zero income → None DTI and None status."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('a1','nfcu','Checking','0459','checking',1)")
    ins_txn(db, 't1', 'a1', 'nfcu', '2026-02-05', 500, -500, 'debit', 'MORTGAGE', 'Mortgage')
    db.commit()
    result = compute_dti_ratio(db, months=3)
    feb = next((r for r in result if r['month'] == '2026-02'), None)
    assert feb and feb['dti_ratio'] is None
    assert feb['status'] is None


def test_dti_derived_summaries(db):
    """DTI stored in derived_summaries per month."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('chk','nfcu','Checking','0459','checking',1)")
    ins_txn(db, 't1', 'chk', 'nfcu', '2026-02-01', 4500, 4500, 'credit', 'DFAS', 'Military Pension')
    ins_txn(db, 't2', 'chk', 'nfcu', '2026-02-05', 1500, -1500, 'debit', 'MORTGAGE', 'Mortgage')
    db.commit()
    compute_dti_ratio(db, months=3)
    row = db.execute(
        "SELECT value FROM derived_summaries WHERE scope='global' AND metric='dti_ratio' AND period='2026-02'"
    ).fetchone()
    assert row is not None
    assert abs(row['value'] - round(1500 / 4500 * 100, 1)) < 0.01


# ── T03 Interest Cost ─────────────────────────────────────────────────────────

def test_interest_cost_loan_details(db):
    """Prefers loan_details over transactions for YTD interest."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('affirm','Affirm')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('mort','nfcu','Mortgage','6167','loan',1)")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('auto','nfcu','Auto Loan','3533','loan',1)")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('hysa','affirm','HYSA','0001','savings',1)")
    # Mortgage from loan_details
    db.execute("INSERT INTO loan_details (account_id,field_name,field_value,as_of) VALUES ('mort','Interest Paid YTD','4200.00','2026-03-01')")
    # Auto from transactions
    ins_txn(db, 't1', 'auto', 'nfcu', '2026-01-15', 85, -85, 'debit', 'INTEREST', 'Interest')
    ins_txn(db, 't2', 'auto', 'nfcu', '2026-02-15', 83, -83, 'debit', 'INTEREST', 'Interest')
    # Interest earned on HYSA
    ins_txn(db, 't3', 'hysa', 'affirm', '2026-02-28', 25, 25, 'credit', 'Interest', 'Interest')
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
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('mort','nfcu','Mortgage','6167','loan',1)")
    db.execute("INSERT INTO loan_details (account_id,field_name,field_value,as_of) VALUES ('mort','ytd_interest','1000.00','2026-03-01')")
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


# ── T04 Net Worth Velocity ────────────────────────────────────────────────────

def test_velocity_steady_growth(db):
    """15 months of $1000/mo growth → steady trend, correct metrics."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('chk','nfcu','Checking','1167','checking',1)")
    base = 200000.0
    for i in range(15):
        y = 2025 if i < 12 else 2026
        m = (i % 12) + 1
        ld = cal.monthrange(y, m)[1]
        db.execute(
            'INSERT INTO balance_snapshots (account_id,balance,as_of) VALUES (?,?,?)',
            ('chk', base + i * 1000, f'{y}-{m:02d}-{ld:02d}'),
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
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('a1','nfcu','Checking','1167','checking',1)")
    db.execute("INSERT INTO balance_snapshots (account_id,balance,as_of) VALUES ('a1',10000,'2026-03-01')")
    db.commit()
    result = compute_net_worth_velocity(db)
    assert result['mom_change'] is None
    assert result['rolling_3m_change'] is None
    assert result['trend'] == 'insufficient_data'


def test_velocity_declining(db):
    """Negative 3m avg → declining trend."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('a1','nfcu','Checking','1167','checking',1)")
    for i in range(6):
        m = 10 + i
        y = 2025 if m <= 12 else 2026
        m = m if m <= 12 else m - 12
        db.execute(
            'INSERT INTO balance_snapshots (account_id,balance,as_of) VALUES (?,?,?)',
            ('a1', 200000 - i * 500, f'{y}-{m:02d}-01'),
        )
    db.commit()
    result = compute_net_worth_velocity(db)
    assert result['trend'] == 'declining'


def test_velocity_derived_summaries(db):
    """MoM change stored in derived_summaries."""
    db.execute("INSERT INTO institutions (id,display_name) VALUES ('nfcu','NFCU')")
    db.execute("INSERT INTO accounts (id,institution_id,name,last4,type,is_active) VALUES ('chk','nfcu','Checking','1167','checking',1)")
    base = 200000.0
    for i in range(15):
        y = 2025 if i < 12 else 2026
        m = (i % 12) + 1
        ld = cal.monthrange(y, m)[1]
        db.execute(
            'INSERT INTO balance_snapshots (account_id,balance,as_of) VALUES (?,?,?)',
            ('chk', base + i * 1000, f'{y}-{m:02d}-{ld:02d}'),
        )
    db.commit()
    compute_net_worth_velocity(db)
    row = db.execute(
        "SELECT value FROM derived_summaries WHERE scope='global' AND metric='nw_mom_change'"
    ).fetchone()
    assert row and row['value'] == 1000.0
