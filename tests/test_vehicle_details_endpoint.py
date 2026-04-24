"""
tests/test_vehicle_details_endpoint.py — P15-T08 coverage.

The ``/api/vehicles/{vehicle_id}/details`` handler returns the
vehicle's own fields, 12-month valuation history, today's depreciation
suggested value + curve label, and the linked auto-loan's scraped
fields. These tests cover:

* own fields + linked auto-loan join
* own fields only (no linked loan)
* valuation history ordering (ascending) + wire-minimal shape
* empty valuation history still returns a list and the suggested_value
  remains populated from the depreciation heuristic
* 12-month window cap
* missing vehicle → 404
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
from dal.vehicles import add_vehicle, add_valuation  # noqa: E402


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
            "VALUES ('summit_auto','summit','Auto Loan','AUTO','loan','quintin',1)"
        )
        conn.commit()

    monkeypatch.setattr(reports_router, "get_db", partial(real_get_db, p))
    yield p

    try:
        os.unlink(path)
    except OSError:
        pass


def _add_vehicle(path, **kwargs):
    with real_get_db(path) as conn:
        add_vehicle(
            conn,
            vehicle_id=kwargs["vehicle_id"],
            make=kwargs.get("make", "Toyota"),
            model=kwargs.get("model", "RAV4"),
            year=kwargs.get("year", 2021),
            purchase_date=kwargs.get("purchase_date", "2021-06-15"),
            purchase_price=kwargs.get("purchase_price", 32500.0),
            owner_id=kwargs.get("owner_id", "quintin"),
            linked_loan_id=kwargs.get("linked_loan_id"),
        )
        conn.commit()


def _add_valuations(path, vehicle_id, entries):
    with real_get_db(path) as conn:
        for valuation_date, value in entries:
            add_valuation(
                conn,
                vehicle_id=vehicle_id,
                valuation_date=valuation_date,
                estimated_value=value,
                source="KBB",
            )
        conn.commit()


def _insert_loan_detail(path, account_id, field, value, as_of):
    with real_get_db(path) as conn:
        conn.execute(
            "INSERT INTO loan_details (account_id, field_name, field_value, as_of) "
            "VALUES (?, ?, ?, ?)",
            (account_id, field, value, as_of),
        )
        conn.commit()


def test_vehicle_details_merges_valuation_and_linked_auto_loan(db):
    _add_vehicle(db, vehicle_id="rav4_2021", linked_loan_id="summit_auto")
    _add_valuations(db, "rav4_2021", [("2026-03-15", 22000.0)])

    _insert_loan_detail(db, "summit_auto", "interest_rate", "4.25%", "2026-04-20T10:00:00")
    _insert_loan_detail(db, "summit_auto", "payoff_today", "$18,500", "2026-04-20T10:00:00")
    _insert_loan_detail(db, "summit_auto", "collateral_type", "Auto", "2026-04-20T10:00:00")

    resp = reports_router.vehicle_details("rav4_2021")

    assert resp["vehicle_id"] == "rav4_2021"
    assert resp["make"] == "Toyota"
    assert resp["model"] == "RAV4"
    assert resp["year"] == 2021
    assert resp["linked_loan_id"] == "summit_auto"
    assert resp["latest_valuation"]["estimated_value"] == 22000.0
    assert resp["latest_valuation"]["as_of"] == "2026-03-15"
    assert resp["details"]["interest_rate"]["value"] == "4.25%"
    assert resp["details"]["collateral_type"]["value"] == "Auto"
    # suggested_value is the heuristic — some positive number for a 2021 car.
    assert isinstance(resp["suggested_value"], (int, float))
    assert resp["suggested_value"] > 0
    assert resp["depreciation_curve"] is not None


def test_vehicle_details_without_linked_loan_or_valuations(db):
    _add_vehicle(db, vehicle_id="bike_2024", make="Trek", model="Marlin", year=2024,
                 purchase_date="2024-05-01", purchase_price=800.0, linked_loan_id=None)

    resp = reports_router.vehicle_details("bike_2024")

    assert resp["linked_loan_id"] is None
    assert resp["details"] == {}
    assert resp["apy_history"] == []
    assert resp["valuation_history"] == []
    # No recorded valuations, but the depreciation heuristic still fires.
    assert resp["latest_valuation"] is None
    assert resp["suggested_value"] is not None
    assert resp["suggested_value"] > 0


def test_vehicle_valuation_history_is_ascending(db):
    _add_vehicle(db, vehicle_id="car_A")
    _add_valuations(db, "car_A", [
        ("2026-03-15", 20000.0),
        ("2026-01-15", 22000.0),
        ("2026-02-15", 21000.0),
    ])

    resp = reports_router.vehicle_details("car_A")

    assert [p["as_of"] for p in resp["valuation_history"]] == [
        "2026-01-15",
        "2026-02-15",
        "2026-03-15",
    ]
    assert [p["estimated_value"] for p in resp["valuation_history"]] == [
        22000.0,
        21000.0,
        20000.0,
    ]
    assert set(resp["valuation_history"][0].keys()) == {"estimated_value", "as_of"}


def test_vehicle_history_respects_12_month_window(db):
    import datetime as _dt

    _add_vehicle(db, vehicle_id="car_B")
    today = _dt.date.today()
    for i in range(15):
        d = today - _dt.timedelta(days=30 * i)
        _add_valuations(db, "car_B", [(d.isoformat(), 20000.0 + i * 100)])

    resp = reports_router.vehicle_details("car_B")

    assert 11 <= len(resp["valuation_history"]) <= 13
    as_ofs = [p["as_of"] for p in resp["valuation_history"]]
    assert as_ofs == sorted(as_ofs)


def test_vehicle_unknown_id_returns_404(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        reports_router.vehicle_details("nonexistent")
    assert excinfo.value.status_code == 404
