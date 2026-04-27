"""
tests/test_result_writer_investment.py — P15-T09 result-writer routing.

The writer accepts a connector ``result.investment_details`` payload of
shape ``{last4: {account_level: {...}, funds: {ticker: {...}}}}`` and
routes it through ``record_investment_details`` to the
``investment_details`` table — account-level rows with ``fund_ticker
NULL``, fund-level rows keyed by ticker. ``fund_name`` flows through
to the table; the composer is responsible for lifting it onto the
fund entry.

Refresh-run id propagates so future forensic queries can correlate a
row back to a specific run.
"""

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.result_writer import persist_connector_result  # noqa: E402
from dal.database import get_db, init_db  # noqa: E402


def _make_result(institution: str, investment_details: dict):
    """Build a duck-typed connector result with no balances / loans / files."""
    return SimpleNamespace(
        institution=institution,
        status="success",
        balances={},
        loan_details={},
        files=[],
        investment_details=investment_details,
    )


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
            "INSERT INTO institutions (id, display_name) VALUES ('acorns','Acorns')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, "
            "owner_id, is_active) "
            "VALUES ('tsp_TSP1','tsp','TSP','TSP1','retirement','quintin',1)"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, "
            "owner_id, is_active) "
            "VALUES ('acorns_ACRN','acorns','Acorns','ACRN','investment','quintin',1)"
        )
        conn.commit()
    yield p
    try:
        os.unlink(path)
    except OSError:
        pass


def test_writer_routes_account_level_and_funds(db):
    """End-to-end: writer persists both branches of the payload."""
    result = _make_result(
        "tsp",
        {
            "TSP1": {
                "account_level": {},
                "funds": {
                    "C": {"ytd_return": "+12.4%", "fund_name": "C Fund"},
                    "S": {"ytd_return": "+8.1%", "fund_name": "S Fund"},
                },
            }
        },
    )

    with get_db(db) as conn:
        summary = persist_connector_result(
            "tsp", result, conn=conn, refresh_run_id="run-1"
        )
        conn.commit()
        assert summary.get("investment_details_recorded") == 4
        rows = conn.execute(
            "SELECT fund_ticker, field_name, field_value, refresh_run_id "
            "FROM investment_details WHERE account_id = ? "
            "ORDER BY fund_ticker, field_name",
            ("tsp_TSP1",),
        ).fetchall()
    by_key = {(r["fund_ticker"], r["field_name"]): r for r in rows}
    assert by_key[("C", "ytd_return")]["field_value"] == "+12.4%"
    assert by_key[("C", "fund_name")]["field_value"] == "C Fund"
    assert by_key[("S", "ytd_return")]["field_value"] == "+8.1%"
    assert by_key[("C", "ytd_return")]["refresh_run_id"] == "run-1"


def test_writer_handles_account_level_only(db):
    """Acorns account-level (round-ups) without fund rows still persists."""
    result = _make_result(
        "acorns",
        {
            "ACRN": {
                "account_level": {
                    "round_up_ytd": "$48.20",
                    "round_up_lifetime": "$1,250.40",
                },
                "funds": {},
            }
        },
    )

    with get_db(db) as conn:
        persist_connector_result(
            "acorns", result, conn=conn, refresh_run_id="run-1"
        )
        conn.commit()
        rows = conn.execute(
            "SELECT fund_ticker, field_name, field_value "
            "FROM investment_details WHERE account_id = ?",
            ("acorns_ACRN",),
        ).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r["fund_ticker"] is None


def test_writer_skips_invalid_field_silently(db):
    """ValueErrors from the DAL guard surface as warnings, not crashes."""
    result = _make_result(
        "tsp",
        {
            "TSP1": {
                "account_level": {},
                "funds": {
                    # Lowercase ticker → DAL guard rejects.
                    "c": {"ytd_return": "+12.4%"},
                    # Valid sibling — should still land.
                    "S": {"ytd_return": "+8.1%"},
                },
            }
        },
    )

    with get_db(db) as conn:
        persist_connector_result(
            "tsp", result, conn=conn, refresh_run_id="run-1"
        )
        conn.commit()
        tickers = [
            r["fund_ticker"] for r in conn.execute(
                "SELECT fund_ticker FROM investment_details "
                "WHERE account_id = ?",
                ("tsp_TSP1",),
            )
        ]
    assert tickers == ["S"]


def test_writer_no_op_on_missing_attribute(db):
    """A connector result without ``investment_details`` doesn't crash.

    Ensures backward compatibility with connectors that don't populate
    the new field (Affirm / NFCU / Chase).
    """
    # No investment_details attribute — getattr fallback should fire.
    result = SimpleNamespace(
        institution="tsp", status="success",
        balances={}, loan_details={}, files=[],
    )
    with get_db(db) as conn:
        summary = persist_connector_result(
            "tsp", result, conn=conn, refresh_run_id="run-1"
        )
        conn.commit()
    assert "investment_details_recorded" not in summary
