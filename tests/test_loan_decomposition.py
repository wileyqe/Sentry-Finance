"""
tests/test_loan_decomposition.py — Phase 14 Phase B amortization tests.

Covers ``dal.debt.decompose_payment`` and ``upsert_loan_payment_split``:

  1. Known payment decomposes to principal + interest matching an external
     amortization calculator within $1.
  2. The split row's components sum exactly to the transaction amount.
  3. ``method='amortization'`` when no statement source is registered.
  4. Missing APR or balance falls back to all-interest with the invariant
     still holding.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.debt import decompose_payment, upsert_loan_payment_split


@pytest.fixture
def tiny_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(Path(path))
        yield Path(path)
    finally:
        os.unlink(path)


def _seed_mortgage(conn: sqlite3.Connection, *, apr: float, balance: float,
                   as_of: str):
    """Seed a single mortgage account with an APR + balance snapshot."""
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) VALUES ('inst_l', 'Lender')"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, type, last4) "
        "VALUES ('mtg_1', 'inst_l', 'Test Mortgage', 'loan', '0000')"
    )
    conn.execute(
        "INSERT INTO loan_details (account_id, field_name, field_value, as_of) "
        "VALUES ('mtg_1', 'interest_rate', ?, ?)",
        (str(apr), as_of),
    )
    conn.execute(
        "INSERT INTO balance_snapshots (account_id, balance, as_of) "
        "VALUES ('mtg_1', ?, ?)",
        (-abs(balance), as_of),  # liabilities negative
    )
    conn.commit()


def test_amortization_matches_external_calc(tiny_db):
    """
    External check: balance $200,000 @ 6.00% APR (monthly rate 0.005) →
    monthly interest = 200000 * 0.005 = $1,000.00.
    Payment $1,200.00 → interest $1,000, principal $200.
    """
    with get_db(tiny_db) as conn:
        _seed_mortgage(conn, apr=6.00, balance=200_000.00, as_of="2026-03-01")

        split = decompose_payment(
            conn, account_id="mtg_1",
            payment_amount_cents=120_000,
            posting_date="2026-03-15",
        )
    assert split["method"] == "amortization"
    assert abs(split["interest_cents"] - 100_000) <= 100, (
        f"Expected ~$1,000 interest, got {split['interest_cents']}"
    )
    assert abs(split["principal_cents"] - 20_000) <= 100, (
        f"Expected ~$200 principal, got {split['principal_cents']}"
    )
    assert split["escrow_cents"] == 0


def test_split_sums_to_payment_amount(tiny_db):
    """Invariant: principal + interest + escrow == payment (exactly)."""
    with get_db(tiny_db) as conn:
        _seed_mortgage(conn, apr=4.75, balance=318_750.00, as_of="2026-01-01")

        split = decompose_payment(
            conn, account_id="mtg_1",
            payment_amount_cents=145_000,  # $1,450.00
            posting_date="2026-01-10",
        )

    total = split["principal_cents"] + split["interest_cents"] + split["escrow_cents"]
    assert total == 145_000, (
        f"Split sum {total} != payment 145000 (broken invariant)"
    )


def test_method_amortization_when_no_statement(tiny_db):
    """Phase B does not ship a statement parser; method should be
    ``amortization`` for every decomposition."""
    with get_db(tiny_db) as conn:
        _seed_mortgage(conn, apr=3.5, balance=100_000.00, as_of="2026-02-01")

        split = decompose_payment(
            conn, account_id="mtg_1",
            payment_amount_cents=75_000,
            posting_date="2026-02-10",
        )
    assert split["method"] == "amortization"


def test_missing_apr_or_balance_falls_back_all_interest(tiny_db):
    """When APR can't be read, treat the full payment as interest so the
    invariant holds. Principal is 0 in this fallback; the row is still
    valid and downstream code can display it as CONSUMED until the
    data catches up."""
    with get_db(tiny_db) as conn:
        # Account exists but no loan_details row → APR unknown
        conn.execute(
            "INSERT OR IGNORE INTO institutions (id, display_name) VALUES ('inst_l', 'Lender')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, type, last4) "
            "VALUES ('mtg_unknown', 'inst_l', 'Unknown', 'loan', '0001')"
        )
        conn.execute(
            "INSERT INTO balance_snapshots (account_id, balance, as_of) "
            "VALUES ('mtg_unknown', -50000, '2026-02-01')"
        )
        conn.commit()

        split = decompose_payment(
            conn, account_id="mtg_unknown",
            payment_amount_cents=200_000,
            posting_date="2026-02-10",
        )

    assert split["principal_cents"] == 0
    assert split["interest_cents"] == 200_000
    assert split["escrow_cents"] == 0
    assert split["method"] == "amortization"


def test_upsert_writes_row_with_correct_method(tiny_db):
    """upsert_loan_payment_split persists the computed decomposition
    and the row is idempotent on re-runs."""
    with get_db(tiny_db) as conn:
        _seed_mortgage(conn, apr=6.00, balance=200_000.00, as_of="2026-03-01")
        # Seed a matching posted transaction
        conn.execute(
            """
            INSERT INTO transactions
            (id, institution_id, account_id, posting_date, effective_month,
             amount, signed_amount, direction, description, category, status)
            VALUES ('t_mtg', 'inst_l', 'mtg_1', '2026-03-15', '2026-03',
                    1200.00, -1200.00, 'Debit', 'Mortgage pmt', 'Mortgage', 'posted')
            """
        )
        conn.commit()

        first = upsert_loan_payment_split(
            conn, transaction_id="t_mtg", account_id="mtg_1",
            signed_amount=-1200.00, posting_date="2026-03-15",
        )
        conn.commit()

        row = conn.execute(
            "SELECT principal_cents, interest_cents, escrow_cents, method "
            "FROM loan_payment_splits WHERE transaction_id = 't_mtg'"
        ).fetchone()
        assert row is not None
        assert row["method"] == "amortization"
        assert row["principal_cents"] == first["principal_cents"]
        assert row["interest_cents"] == first["interest_cents"]
        assert row["escrow_cents"] == first["escrow_cents"]

        # Re-run is idempotent (same values, same row)
        second = upsert_loan_payment_split(
            conn, transaction_id="t_mtg", account_id="mtg_1",
            signed_amount=-1200.00, posting_date="2026-03-15",
        )
        assert second == first

        count = conn.execute(
            "SELECT COUNT(*) FROM loan_payment_splits WHERE transaction_id = 't_mtg'"
        ).fetchone()[0]
        assert count == 1, "upsert should not create duplicate rows"
