"""
tests/test_real_estate_details_endpoint.py — P15-T08 coverage.

The ``/api/real_estate/{property_id}/details`` handler returns the
property's latest valuation + 12-month history, joined with the linked
mortgage account's scraped fields. These tests cover:

* own fields + linked mortgage join
* own fields only (no linked loan)
* valuation history ordering (ascending)
* empty valuation history still returns a list
* 12-month window cap
* missing property → 404
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
from dal.connection import get_db as real_get_db  # noqa: E402
from dal.database import init_db  # noqa: E402
from dal.real_estate import record_real_estate_valuations  # noqa: E402


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
            "INSERT INTO institutions (id, display_name) VALUES ('summit','Summit')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, owner_id, is_active) "
            "VALUES ('summit_mtg','summit','Mortgage','MTG1','loan','quintin',1)"
        )
        conn.commit()

    monkeypatch.setattr(reports_router, "get_db", partial(real_get_db, p))
    yield p

    try:
        os.unlink(path)
    except OSError:
        pass


def _seed_re(path, *, name, estimated_value, as_of, linked_loan_id=None, source="estimate"):
    with real_get_db(path) as conn:
        record_real_estate_valuations(
            conn,
            [
                {
                    "name": name,
                    "estimated_value": estimated_value,
                    "as_of": as_of,
                    "linked_loan_id": linked_loan_id,
                    "source": source,
                    "owner_id": "quintin",
                }
            ],
        )
        conn.commit()


def _latest_id(path, name):
    with real_get_db(path) as conn:
        row = conn.execute(
            "SELECT id FROM real_estate WHERE name = ? ORDER BY as_of DESC, id DESC LIMIT 1",
            (name,),
        ).fetchone()
        return row["id"]


def _insert_loan_detail(path, account_id, field, value, as_of):
    with real_get_db(path) as conn:
        conn.execute(
            "INSERT INTO loan_details (account_id, field_name, field_value, as_of) "
            "VALUES (?, ?, ?, ?)",
            (account_id, field, value, as_of),
        )
        conn.commit()


def test_real_estate_details_merges_valuation_and_linked_mortgage(db):
    _seed_re(
        db,
        name="Primary Residence",
        estimated_value=400000.0,
        as_of="2026-03-15",
        linked_loan_id="summit_mtg",
    )
    pid = _latest_id(db, "Primary Residence")

    _insert_loan_detail(db, "summit_mtg", "interest_rate", "3.25%", "2026-04-20T10:00:00")
    _insert_loan_detail(db, "summit_mtg", "payoff_today", "$150,000", "2026-04-20T10:00:00")

    resp = reports_router.real_estate_details(pid)

    assert resp["property_id"] == pid
    assert resp["name"] == "Primary Residence"
    assert resp["latest_valuation"]["estimated_value"] == 400000.0
    assert resp["linked_loan_id"] == "summit_mtg"
    assert resp["details"]["interest_rate"]["value"] == "3.25%"
    assert resp["details"]["payoff_today"]["value"] == "$150,000"


def test_real_estate_details_without_linked_loan(db):
    _seed_re(
        db,
        name="Beach Cabin",
        estimated_value=125000.0,
        as_of="2026-03-15",
        linked_loan_id=None,
    )
    pid = _latest_id(db, "Beach Cabin")

    resp = reports_router.real_estate_details(pid)

    assert resp["linked_loan_id"] is None
    assert resp["details"] == {}
    assert resp["apy_latest"] is None
    assert resp["apy_history"] == []


def test_real_estate_valuation_history_is_ascending(db):
    for as_of, value in [
        ("2026-03-15", 410000.0),
        ("2026-01-15", 395000.0),
        ("2026-02-15", 402000.0),
    ]:
        _seed_re(db, name="Primary Residence", estimated_value=value, as_of=as_of)
    pid = _latest_id(db, "Primary Residence")

    resp = reports_router.real_estate_details(pid)

    assert [p["as_of"] for p in resp["valuation_history"]] == [
        "2026-01-15",
        "2026-02-15",
        "2026-03-15",
    ]
    assert [p["estimated_value"] for p in resp["valuation_history"]] == [
        395000.0,
        402000.0,
        410000.0,
    ]


def test_real_estate_empty_valuation_history_returns_list(db):
    # Insert a single row but make it the only entry (no history rows).
    _seed_re(db, name="Solo Lot", estimated_value=50000.0, as_of="2026-04-01")
    pid = _latest_id(db, "Solo Lot")

    resp = reports_router.real_estate_details(pid)

    assert isinstance(resp["valuation_history"], list)
    assert len(resp["valuation_history"]) == 1
    # Wire-minimal shape: only estimated_value + as_of on the history.
    assert set(resp["valuation_history"][0].keys()) == {"estimated_value", "as_of"}


def test_real_estate_history_respects_12_month_window(db):
    import datetime as _dt

    today = _dt.date.today()
    for i in range(15):
        d = today - _dt.timedelta(days=30 * i)
        _seed_re(db, name="Windowed House", estimated_value=300000.0 + i * 1000, as_of=d.isoformat())
    pid = _latest_id(db, "Windowed House")

    resp = reports_router.real_estate_details(pid)

    # Same bounded-range assertion used on the APY endpoint — SQLite's
    # `-12 months` arithmetic is boundary-squishy by calendar day.
    assert 11 <= len(resp["valuation_history"]) <= 13
    as_ofs = [p["as_of"] for p in resp["valuation_history"]]
    assert as_ofs == sorted(as_ofs)


def test_real_estate_unknown_id_returns_404(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        reports_router.real_estate_details(99999)
    assert excinfo.value.status_code == 404
