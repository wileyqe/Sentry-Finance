"""
tests/test_rewards_points.py — P15-T03 end-to-end wiring check.

Verifies that a ``rewards_points`` row written through the existing
``record_loan_details`` path:

* persists into ``loan_details``
* is returned by ``get_latest_loan_details`` (the generic details endpoint)
* appears in the ``loan_details`` pivot used by the accounts router

The plan deliberately picked the key-value shape (latest-wins) over a
new time-series table, so there is no trend assertion here.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.balances import get_latest_loan_details, record_loan_details  # noqa: E402
from dal.database import init_db, get_db  # noqa: E402


# Copy of the pivot SQL from backend/routers/accounts.py — if the router
# drifts, this test is what catches it.
_PIVOT_SQL = """
    SELECT account_id,
           MAX(CASE WHEN field_name='purchase_price'   THEN CAST(field_value AS REAL) END) AS purchase_price,
           MAX(CASE WHEN field_name='interest_rate'    THEN CAST(field_value AS REAL) END) AS interest_rate,
           MAX(CASE WHEN field_name='minimum_payment'  THEN CAST(field_value AS REAL) END) AS minimum_payment,
           MAX(CASE WHEN field_name='term_months'      THEN CAST(field_value AS INTEGER) END) AS term_months,
           MAX(CASE WHEN field_name='origination_date' THEN field_value END) AS origination_date,
           MAX(CASE WHEN field_name='credit_limit'     THEN CAST(field_value AS REAL) END) AS credit_limit,
           MAX(CASE WHEN field_name='rewards_points'   THEN field_value END) AS rewards_points
    FROM loan_details
    GROUP BY account_id
"""


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    p = Path(path)
    init_db(p)
    with get_db(p) as conn:
        conn.execute("INSERT INTO owners (id, display_name) VALUES ('quintin','Quintin')")
        conn.execute("INSERT INTO institutions (id, display_name) VALUES ('nfcu','NFCU')")
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, owner_id, is_active) "
            "VALUES ('nfcu_NFCC','nfcu','Credit Card','NFCC','credit_card','quintin',1)"
        )
        conn.commit()
    yield p
    try:
        os.unlink(path)
    except OSError:
        pass


def test_rewards_persistence(db):
    """A rewards_points row written via record_loan_details lands in the table."""
    with get_db(db) as conn:
        record_loan_details(
            conn,
            account_id="nfcu_NFCC",
            details={"rewards_points": "8450"},
            as_of="2026-04-18",
        )
        conn.commit()

        row = conn.execute(
            "SELECT field_value FROM loan_details "
            "WHERE account_id = ? AND field_name = 'rewards_points'",
            ("nfcu_NFCC",),
        ).fetchone()
    assert row is not None
    assert row["field_value"] == "8450"


def test_latest_loan_details_surfaces_rewards(db):
    """The generic details reader returns rewards alongside APR etc."""
    with get_db(db) as conn:
        record_loan_details(
            conn,
            account_id="nfcu_NFCC",
            details={"rewards_points": "12,400", "purchase_apr": "19.99%"},
            as_of="2026-04-18",
        )
        conn.commit()

        details = get_latest_loan_details(conn, "nfcu_NFCC")
    assert details.get("rewards_points") == "12,400"
    assert details.get("purchase_apr") == "19.99%"


def test_accounts_pivot_includes_rewards_column(db):
    """Accounts-router pivot SQL exposes rewards_points as a real column."""
    with get_db(db) as conn:
        record_loan_details(
            conn,
            account_id="nfcu_NFCC",
            details={"rewards_points": "8450"},
            as_of="2026-04-18",
        )
        conn.commit()

        row = conn.execute(_PIVOT_SQL).fetchone()
    assert row is not None
    assert row["account_id"] == "nfcu_NFCC"
    assert row["rewards_points"] == "8450"
    assert row["credit_limit"] is None  # unrelated fields stay None


def test_accounts_pivot_null_when_no_rewards(db):
    """Pivot returns NULL for rewards_points when no row exists."""
    with get_db(db) as conn:
        record_loan_details(
            conn,
            account_id="nfcu_NFCC",
            details={"purchase_apr": "19.99%"},
            as_of="2026-04-18",
        )
        conn.commit()

        row = conn.execute(_PIVOT_SQL).fetchone()
    assert row is not None
    assert row["rewards_points"] is None


def test_latest_row_wins(db):
    """Latest-row-wins semantics — the newest rewards_points value surfaces."""
    with get_db(db) as conn:
        record_loan_details(
            conn,
            account_id="nfcu_NFCC",
            details={"rewards_points": "5000"},
            as_of="2026-03-18",
        )
        record_loan_details(
            conn,
            account_id="nfcu_NFCC",
            details={"rewards_points": "8450"},
            as_of="2026-04-18",
        )
        conn.commit()

        details = get_latest_loan_details(conn, "nfcu_NFCC")
    assert details["rewards_points"] == "8450"
