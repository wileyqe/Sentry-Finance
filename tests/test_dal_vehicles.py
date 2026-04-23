"""
tests/test_dal_vehicles.py — Unit tests for ``dal/vehicles.py``.

Focused coverage of ``suggested_value()`` — the depreciation-based
pre-fill used by the Accounts-page manual valuation modal. No free
public API gives us KBB/Edmunds values as of 2026, so this heuristic
is load-bearing for the vehicle-asset UX.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db  # noqa: E402
from dal.vehicles import (  # noqa: E402
    add_valuation,
    add_vehicle,
    list_vehicles,
    suggested_value,
)


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(Path(path))
    yield Path(path)
    try:
        os.unlink(path)
    except OSError:
        pass


def _seed_vehicle(db, vid="test_car", price=30000.0, purchase_date="2024-01-01"):
    with get_db(db) as conn:
        add_vehicle(
            conn,
            vehicle_id=vid,
            make="Test",
            model="Car",
            year=2024,
            purchase_date=purchase_date,
            purchase_price=price,
            owner_id=None,  # FK-free for isolated test DB
        )
        conn.commit()


def test_suggested_value_brand_new_is_85pct(db):
    """Fresh-off-the-lot: 15% instantaneous hit, so value = 85% of purchase."""
    _seed_vehicle(db, price=30000.0, purchase_date="2026-04-23")
    with get_db(db) as conn:
        result = suggested_value(conn, "test_car", as_of="2026-04-23")
    assert result is not None
    # 30000 * 0.85 = 25500
    assert result["suggested_value"] == pytest.approx(25500.0, abs=1.0)
    assert result["basis"]["age_years"] == 0.0
    assert result["basis"]["purchase_price"] == 30000.0


def test_suggested_value_one_year_old_is_76pct(db):
    """At age 1y: 0.85 * 0.90^1 = 0.765 → 76.5% of purchase."""
    _seed_vehicle(db, price=30000.0, purchase_date="2025-04-23")
    with get_db(db) as conn:
        result = suggested_value(conn, "test_car", as_of="2026-04-23")
    assert result is not None
    assert result["suggested_value"] == pytest.approx(22950.0, abs=50.0)
    assert 0.99 <= result["basis"]["age_years"] <= 1.01


def test_suggested_value_five_years_old(db):
    """At age 5y: 0.85 * 0.90^5 ≈ 0.502 → ~50% of purchase."""
    _seed_vehicle(db, price=30000.0, purchase_date="2021-04-23")
    with get_db(db) as conn:
        result = suggested_value(conn, "test_car", as_of="2026-04-23")
    assert result is not None
    # 30000 * 0.85 * 0.9^5 = 15057.95
    assert result["suggested_value"] == pytest.approx(15057.95, abs=10.0)


def test_suggested_value_floors_at_15pct(db):
    """A 25-year-old vehicle bottoms out at the 15%-of-purchase floor."""
    _seed_vehicle(db, price=30000.0, purchase_date="2001-04-23")
    with get_db(db) as conn:
        result = suggested_value(conn, "test_car", as_of="2026-04-23")
    assert result is not None
    # Floor is 15% of purchase price — must not go below.
    assert result["suggested_value"] == pytest.approx(4500.0, abs=1.0)
    assert result["suggested_value"] <= 30000.0 * 0.15 + 1.0


def test_suggested_value_unknown_vehicle_returns_none(db):
    with get_db(db) as conn:
        result = suggested_value(conn, "nonexistent")
    assert result is None


def test_suggested_value_no_purchase_date_defaults_to_purchase_price(db):
    _seed_vehicle(db, price=20000.0, purchase_date=None)
    with get_db(db) as conn:
        result = suggested_value(conn, "test_car", as_of="2026-04-23")
    assert result is not None
    assert result["suggested_value"] == 20000.0
    assert "no purchase_date" in result["basis"]["depreciation_curve"]


def test_add_valuation_and_list_vehicles_roundtrip(db):
    """Exercise the write path the new POST /api/vehicles/{id}/valuations uses."""
    _seed_vehicle(db, vid="rav4", price=32500.0)
    with get_db(db) as conn:
        add_valuation(
            conn,
            vehicle_id="rav4",
            valuation_date="2026-04-23",
            estimated_value=19500.0,
            source="manual",
        )
        conn.commit()
        vehicles = list_vehicles(conn)
    assert len(vehicles) == 1
    assert vehicles[0]["id"] == "rav4"
