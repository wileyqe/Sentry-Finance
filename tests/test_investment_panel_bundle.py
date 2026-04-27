"""
tests/test_investment_panel_bundle.py — P15-T09 composer tests.

Covers:
* Empty bundle shape (no rows in investment_details)
* Account-level + fund-level rows compose into the documented bundle
* fund_name is lifted onto the entry, not into ``fields``
* Funds list is sorted alphabetically by ticker
* Shared keys (apy_latest/apy_history/collateral) are always present
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.account_details_composer import get_investment_panel_bundle  # noqa: E402
from dal.database import get_db, init_db  # noqa: E402
from dal.investment_details import record_investment_details  # noqa: E402


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    p = Path(path)
    init_db(p)
    with get_db(p) as conn:
        conn.execute(
            "INSERT INTO owners (id, display_name) VALUES ('quintin','Quintin')"
        )
        conn.execute(
            "INSERT INTO institutions (id, display_name) VALUES ('tsp','TSP')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, "
            "owner_id, is_active) "
            "VALUES ('tsp_TSP1','tsp','TSP','TSP1','retirement','quintin',1)"
        )
        conn.commit()
    yield p
    try:
        os.unlink(path)
    except OSError:
        pass


def test_empty_bundle_shape(db):
    """No rows in investment_details → empty bundle but full shape."""
    with get_db(db) as conn:
        bundle = get_investment_panel_bundle(conn, "tsp_TSP1")
    assert bundle == {
        "account_id": "tsp_TSP1",
        "kind": "investment",
        "details": {},
        "funds": [],
        "apy_latest": None,
        "apy_history": [],
        "collateral": None,
    }


def test_account_level_rows_compose_into_details(db):
    with get_db(db) as conn:
        record_investment_details(
            conn, "tsp_TSP1",
            {"round_up_ytd": "$48.20", "round_up_lifetime": "$1,250.40"},
            as_of="2026-04-26", refresh_run_id=1,
        )
        conn.commit()
        bundle = get_investment_panel_bundle(conn, "tsp_TSP1")
    assert bundle["details"]["round_up_ytd"]["value"] == "$48.20"
    assert bundle["details"]["round_up_lifetime"]["value"] == "$1,250.40"
    assert bundle["funds"] == []


def test_fund_level_rows_become_alphabetical_list(db):
    """Per-fund rows compose into a sorted list of fund entries."""
    with get_db(db) as conn:
        # Insert in non-alphabetical order to verify sort.
        for ticker, ytd, name in [
            ("S", "+8.1%", "S Fund"),
            ("C", "+12.4%", "C Fund"),
            ("I", "+4.2%", "I Fund"),
        ]:
            record_investment_details(
                conn, "tsp_TSP1",
                {"ytd_return": ytd, "fund_name": name},
                as_of="2026-04-26", fund_ticker=ticker, refresh_run_id=1,
            )
        conn.commit()
        bundle = get_investment_panel_bundle(conn, "tsp_TSP1")
    tickers = [f["ticker"] for f in bundle["funds"]]
    assert tickers == ["C", "I", "S"]
    by_ticker = {f["ticker"]: f for f in bundle["funds"]}
    assert by_ticker["C"]["name"] == "C Fund"
    assert by_ticker["C"]["fields"]["ytd_return"]["value"] == "+12.4%"
    # fund_name is lifted onto the entry, not in fields.
    assert "fund_name" not in by_ticker["C"]["fields"]


def test_mixed_account_and_fund_level(db):
    with get_db(db) as conn:
        record_investment_details(
            conn, "tsp_TSP1", {"round_up_ytd": "$48.20"},
            as_of="2026-04-26", refresh_run_id=1,
        )
        record_investment_details(
            conn, "tsp_TSP1", {"ytd_return": "+12.4%"},
            as_of="2026-04-26", fund_ticker="C", refresh_run_id=1,
        )
        conn.commit()
        bundle = get_investment_panel_bundle(conn, "tsp_TSP1")
    assert bundle["details"]["round_up_ytd"]["value"] == "$48.20"
    assert len(bundle["funds"]) == 1
    assert bundle["funds"][0]["ticker"] == "C"


def test_shared_keys_present_for_frontend_compatibility(db):
    """``apy_latest``/``apy_history``/``collateral`` are always present.

    The frontend ``DetailsResponse`` interface treats these as
    non-optional reads. Even when investment accounts have no APY
    history they must be ``None`` / ``[]`` (not missing keys).
    """
    with get_db(db) as conn:
        bundle = get_investment_panel_bundle(conn, "tsp_TSP1")
    assert "apy_latest" in bundle
    assert "apy_history" in bundle
    assert "collateral" in bundle
    assert bundle["apy_latest"] is None
    assert bundle["apy_history"] == []
    assert bundle["collateral"] is None


def test_fund_with_only_name_no_other_fields(db):
    """Edge: a fund with only fund_name should still appear with empty fields."""
    with get_db(db) as conn:
        record_investment_details(
            conn, "tsp_TSP1", {"fund_name": "G Fund"},
            as_of="2026-04-26", fund_ticker="G", refresh_run_id=1,
        )
        conn.commit()
        bundle = get_investment_panel_bundle(conn, "tsp_TSP1")
    assert len(bundle["funds"]) == 1
    g = bundle["funds"][0]
    assert g["ticker"] == "G"
    assert g["name"] == "G Fund"
    assert g["fields"] == {}
