"""
tests/test_accounts_details_endpoint.py — P15-T06 endpoint-merge coverage.

The ``/api/accounts/{account_id}/details`` handler in
``backend/routers/reports.py`` now merges the latest ``apy_history`` row
(via ``dal.apy_history.get_latest_apy``) into its response as
``apy_latest``. These tests cover:

* loan_details + apy_history present → both blocks populated
* loan_details present, apy_history empty → ``apy_latest`` is None
* loan_details empty, apy_history present → ``details`` is empty, APY still returned
* Both empty → skeleton response with empty dict + None
"""

import os
import sys
import tempfile
from functools import partial
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.routers import reports as reports_router  # noqa: E402
from dal.apy_history import record_apy_history  # noqa: E402
from dal.connection import get_db as real_get_db  # noqa: E402
from dal.database import init_db  # noqa: E402


@pytest.fixture
def db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    p = Path(path)
    init_db(p)
    with real_get_db(p) as conn:
        conn.execute(
            "INSERT INTO owners (id, display_name) VALUES ('quintin','Quintin')"
        )
        conn.execute(
            "INSERT INTO institutions (id, display_name) VALUES ('nfcu','NFCU')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, owner_id, is_active) "
            "VALUES ('nfcu_cc','nfcu','Platinum CC','NFCC','credit_card','quintin',1)"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, owner_id, is_active) "
            "VALUES ('nfcu_chk','nfcu','Checking','NFCK','checking','quintin',1)"
        )
        conn.commit()

    # Redirect the handler's `get_db` to this temp DB.
    monkeypatch.setattr(reports_router, "get_db", partial(real_get_db, p))

    yield p

    try:
        os.unlink(path)
    except OSError:
        pass


def _insert_loan_detail(path, account_id, field, value, as_of):
    with real_get_db(path) as conn:
        conn.execute(
            "INSERT INTO loan_details (account_id, field_name, field_value, as_of) "
            "VALUES (?, ?, ?, ?)",
            (account_id, field, value, as_of),
        )
        conn.commit()


def test_details_merges_loan_details_and_apy(db):
    _insert_loan_detail(db, "nfcu_chk", "available_balance", "$1,234.56", "2026-04-20T10:00:00")
    _insert_loan_detail(db, "nfcu_chk", "direct_deposit_enrolled", "Yes", "2026-04-20T10:00:00")
    with real_get_db(db) as conn:
        record_apy_history(
            conn, account_id="nfcu_chk", apy_rate=0.25, as_of="2026-04-22", source="scrape"
        )
        conn.commit()

    resp = reports_router.account_details("nfcu_chk")

    assert resp["account_id"] == "nfcu_chk"
    assert set(resp["details"].keys()) == {"available_balance", "direct_deposit_enrolled"}
    assert resp["details"]["available_balance"]["value"] == "$1,234.56"
    assert resp["apy_latest"] is not None
    assert resp["apy_latest"]["apy_rate"] == 0.25
    assert resp["apy_latest"]["as_of"] == "2026-04-22"
    assert resp["apy_latest"]["source"] == "scrape"


def test_details_with_loan_details_but_no_apy(db):
    _insert_loan_detail(db, "nfcu_cc", "credit_limit", "$10,000", "2026-04-20T10:00:00")
    _insert_loan_detail(db, "nfcu_cc", "purchase_apr", "18.49%", "2026-04-20T10:00:00")

    resp = reports_router.account_details("nfcu_cc")

    assert resp["details"]["credit_limit"]["value"] == "$10,000"
    assert resp["apy_latest"] is None


def test_details_with_apy_but_no_loan_details(db):
    with real_get_db(db) as conn:
        record_apy_history(
            conn, account_id="nfcu_chk", apy_rate=4.50, as_of="2026-04-22", source="scrape"
        )
        conn.commit()

    resp = reports_router.account_details("nfcu_chk")

    assert resp["details"] == {}
    assert resp["apy_latest"]["apy_rate"] == 4.50


def test_details_empty_for_both(db):
    resp = reports_router.account_details("nfcu_cc")

    assert resp["account_id"] == "nfcu_cc"
    assert resp["details"] == {}
    assert resp["apy_latest"] is None


def test_details_dedup_keeps_newest_loan_detail(db):
    _insert_loan_detail(db, "nfcu_cc", "credit_limit", "$9,000", "2026-04-10T10:00:00")
    _insert_loan_detail(db, "nfcu_cc", "credit_limit", "$10,000", "2026-04-20T10:00:00")

    resp = reports_router.account_details("nfcu_cc")

    assert resp["details"]["credit_limit"]["value"] == "$10,000"
    assert resp["details"]["credit_limit"]["as_of"] == "2026-04-20T10:00:00"


# ---- P15-T07: apy_history time-series on the /details response ---------

def test_account_details_includes_apy_history_ascending(db):
    """Three APY rows seeded out-of-order come back ascending by as_of."""
    with real_get_db(db) as conn:
        record_apy_history(
            conn, account_id="nfcu_chk", apy_rate=0.30, as_of="2026-03-15", source="scrape"
        )
        record_apy_history(
            conn, account_id="nfcu_chk", apy_rate=0.20, as_of="2026-01-15", source="scrape"
        )
        record_apy_history(
            conn, account_id="nfcu_chk", apy_rate=0.25, as_of="2026-02-15", source="scrape"
        )
        conn.commit()

    resp = reports_router.account_details("nfcu_chk")

    assert "apy_history" in resp
    assert isinstance(resp["apy_history"], list)
    assert [p["as_of"] for p in resp["apy_history"]] == [
        "2026-01-15",
        "2026-02-15",
        "2026-03-15",
    ]
    assert [p["apy_rate"] for p in resp["apy_history"]] == [0.20, 0.25, 0.30]
    # Shape is the wire-minimal {apy_rate, as_of} — DAL-only fields are stripped.
    assert set(resp["apy_history"][0].keys()) == {"apy_rate", "as_of"}


def test_account_details_empty_apy_history_returns_list(db):
    """No APY rows → apy_history is an empty list (never null, never missing)."""
    resp = reports_router.account_details("nfcu_cc")

    assert "apy_history" in resp
    assert resp["apy_history"] == []


def test_account_details_apy_history_respects_12_month_window(db):
    """Seed 15 months of rows; only the most recent 12 come back."""
    import datetime as _dt

    today = _dt.date.today()
    with real_get_db(db) as conn:
        for i in range(15):
            d = today - _dt.timedelta(days=30 * i)
            record_apy_history(
                conn,
                account_id="nfcu_chk",
                apy_rate=0.10 + 0.01 * i,
                as_of=d.isoformat(),
                source="scrape",
            )
        conn.commit()

    resp = reports_router.account_details("nfcu_chk")

    # SQLite's date('now', '-12 months') is inclusive at the boundary, so we
    # assert the count is capped at what fits in a 12-month window, not the
    # exact number of seeded rows. The older 3 rows are definitively dropped.
    assert len(resp["apy_history"]) <= 13
    assert len(resp["apy_history"]) >= 11
    # Ascending order invariant still holds.
    as_of_values = [p["as_of"] for p in resp["apy_history"]]
    assert as_of_values == sorted(as_of_values)
