"""
tests/test_transaction_invariants.py — Phase 10 sign-convention guardrail.

dal/transactions.upsert_transactions() is the single choke point for both
the synthetic seeder and live institution connectors.  After Phase 10 it
enforces the canonical sign convention with a runtime invariant check:

    signed_amount < 0  ⟺  direction == 'Debit'
    signed_amount > 0  ⟺  direction == 'Credit'

If a connector or fixture ever produces a row that violates this rule,
the upsert refuses it with a ValueError instead of silently inserting
inconsistent data.  These tests are the regression wall for that check.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.transactions import upsert_transactions


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


@pytest.fixture
def fresh_db():
    db = _temp_db()
    init_db(db)
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO institutions (id, display_name) VALUES ('testbank', 'Test Bank')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
            "VALUES ('acct_chk', 'testbank', 'Checking', '1234', 'checking', 1)"
        )
        conn.commit()
        yield conn
    try:
        os.unlink(db)
    except OSError:
        pass


# ── Bug #8: sign/direction drift must be rejected ──────────────────────────


def test_upsert_rejects_negative_signed_with_credit_direction(fresh_db):
    """A row that says 'Credit' but carries a negative signed_amount must
    be refused.  This catches connector bugs that copy `direction` from one
    field and `amount` from another and forget to negate."""
    bad_row = {
        "account_id": "acct_chk",
        "institution_id": "testbank",
        "posting_date": "2025-03-15",
        "amount": 100.0,
        "signed_amount": -100.0,  # Says spending …
        "direction": "Credit",     # … but direction says income
        "description": "Bogus credit",
        "category": "Other Income",
    }
    with pytest.raises(ValueError, match="Sign/direction mismatch"):
        upsert_transactions(fresh_db, [bad_row])


def test_upsert_rejects_positive_signed_with_debit_direction(fresh_db):
    """The mirror case: positive signed_amount with direction='Debit'."""
    bad_row = {
        "account_id": "acct_chk",
        "institution_id": "testbank",
        "posting_date": "2025-03-15",
        "amount": 50.0,
        "signed_amount": 50.0,    # Says income …
        "direction": "Debit",      # … but direction says spending
        "description": "Bogus debit",
        "category": "Groceries",
    }
    with pytest.raises(ValueError, match="Sign/direction mismatch"):
        upsert_transactions(fresh_db, [bad_row])


def test_upsert_accepts_canonical_debit(fresh_db):
    """Canonical Debit row (negative signed_amount, direction='Debit')
    must be accepted and stored verbatim."""
    good_row = {
        "account_id": "acct_chk",
        "institution_id": "testbank",
        "posting_date": "2025-03-16",
        "amount": 75.0,
        "signed_amount": -75.0,
        "direction": "Debit",
        "description": "Canonical debit",
        "category": "Groceries",
    }
    stats = upsert_transactions(fresh_db, [good_row])
    assert stats["inserted"] == 1
    row = fresh_db.execute(
        "SELECT signed_amount, direction, amount FROM transactions WHERE description = 'Canonical debit'"
    ).fetchone()
    assert row["signed_amount"] == -75.0
    assert row["direction"] == "Debit"
    assert row["amount"] == 75.0


def test_upsert_accepts_canonical_credit(fresh_db):
    """Canonical Credit row (positive signed_amount, direction='Credit')
    must be accepted and stored verbatim."""
    good_row = {
        "account_id": "acct_chk",
        "institution_id": "testbank",
        "posting_date": "2025-03-17",
        "amount": 250.0,
        "signed_amount": 250.0,
        "direction": "Credit",
        "description": "Canonical credit",
        "category": "Paychecks/Salary",
    }
    stats = upsert_transactions(fresh_db, [good_row])
    assert stats["inserted"] == 1
    row = fresh_db.execute(
        "SELECT signed_amount, direction, amount FROM transactions WHERE description = 'Canonical credit'"
    ).fetchone()
    assert row["signed_amount"] == 250.0
    assert row["direction"] == "Credit"
    assert row["amount"] == 250.0


def test_upsert_failfast_in_a_mixed_batch(fresh_db):
    """If a single bad row is mixed into an otherwise good batch, the
    invariant check fires BEFORE any rows are inserted (no partial state)."""
    rows = [
        {
            "account_id": "acct_chk",
            "institution_id": "testbank",
            "posting_date": "2025-03-18",
            "amount": 100.0,
            "signed_amount": -100.0,
            "direction": "Debit",
            "description": "Good 1",
            "category": "Groceries",
        },
        {
            "account_id": "acct_chk",
            "institution_id": "testbank",
            "posting_date": "2025-03-18",
            "amount": 200.0,
            "signed_amount": -200.0,
            "direction": "Credit",  # Wrong!
            "description": "Bad in middle",
            "category": "Groceries",
        },
        {
            "account_id": "acct_chk",
            "institution_id": "testbank",
            "posting_date": "2025-03-18",
            "amount": 300.0,
            "signed_amount": 300.0,
            "direction": "Credit",
            "description": "Good 2",
            "category": "Paychecks/Salary",
        },
    ]
    with pytest.raises(ValueError, match="Sign/direction mismatch"):
        upsert_transactions(fresh_db, rows)

    # NONE of the three rows should have been inserted, because the
    # invariant check runs over the whole batch BEFORE any INSERT.
    count = fresh_db.execute(
        "SELECT COUNT(*) AS c FROM transactions WHERE posting_date = '2025-03-18'"
    ).fetchone()["c"]
    assert count == 0, (
        f"Expected zero rows after fail-fast, found {count} — invariant "
        f"check is running too late"
    )
