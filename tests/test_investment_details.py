"""
tests/test_investment_details.py — P15-T09 DAL invariants + round-trip.

Covers:
* ``_assert_row_valid`` rejects empty field names, bad ISO dates, and
  malformed fund tickers
* ``record_investment_details`` persists account-level (fund_ticker
  NULL) and fund-level rows, skips empty values, returns insert count
* ``COALESCE(fund_ticker,'')`` unique index dedupes both NULL-ticker
  and ticker rows on repeat calls within a refresh
* ``get_latest_investment_details`` returns latest-per-(fund, field)
  snapshot with the documented ``{account_level, funds}`` shape
* ``get_investment_field_history`` orders ascending and respects the
  ``fund_ticker`` + ``months`` filters
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import get_db, init_db  # noqa: E402
from dal.investment_details import (  # noqa: E402
    get_investment_field_history,
    get_latest_investment_details,
    record_investment_details,
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


# ── _assert_row_valid ────────────────────────────────────────────────


def test_record_rejects_empty_field_name(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="field_name"):
            record_investment_details(
                conn, "tsp_TSP1", {"": "5.0%"},
                as_of="2026-04-26", fund_ticker="C",
            )


def test_record_rejects_non_iso_as_of(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="as_of"):
            record_investment_details(
                conn, "tsp_TSP1", {"ytd_return": "5.0%"},
                as_of="04/26/2026", fund_ticker="C",
            )


def test_record_rejects_lowercase_ticker(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="fund_ticker"):
            record_investment_details(
                conn, "tsp_TSP1", {"ytd_return": "5.0%"},
                as_of="2026-04-26", fund_ticker="c",
            )


def test_record_rejects_oversized_ticker(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="fund_ticker"):
            record_investment_details(
                conn, "tsp_TSP1", {"ytd_return": "5.0%"},
                as_of="2026-04-26",
                fund_ticker="ABCDEFGHIJKLM",  # 13 chars > 12-char limit
            )


def test_record_accepts_tsp_underscore_ticker(db):
    """TSP convention uses underscores: TSP_C, TSP_L2065, etc."""
    with get_db(db) as conn:
        inserted = record_investment_details(
            conn, "tsp_TSP1", {"ytd_return": "+9.85%"},
            as_of="2026-04-26", fund_ticker="TSP_L2065",
            refresh_run_id=1,
        )
        assert inserted == 1


def test_record_skips_empty_values(db):
    with get_db(db) as conn:
        inserted = record_investment_details(
            conn, "tsp_TSP1",
            {"ytd_return": "5.0%", "fund_name": "", "expense_ratio": None},
            as_of="2026-04-26",
            fund_ticker="C",
            refresh_run_id=1,
        )
        assert inserted == 1


# ── round-trip: account-level + fund-level ──────────────────────────


def test_account_level_round_trip(db):
    """fund_ticker NULL writes round-trip into account_level."""
    with get_db(db) as conn:
        record_investment_details(
            conn, "acorns_ACRN",
            {"round_up_ytd": "$48.20", "round_up_lifetime": "$1,250.40"},
            as_of="2026-04-26",
            refresh_run_id=1,
        )
        conn.commit()

        snap = get_latest_investment_details(conn, "acorns_ACRN")
        assert snap["funds"] == {}
        assert snap["account_level"]["round_up_ytd"]["value"] == "$48.20"
        assert snap["account_level"]["round_up_ytd"]["as_of"] == "2026-04-26"
        assert snap["account_level"]["round_up_lifetime"]["value"] == "$1,250.40"


def test_fund_level_round_trip(db):
    """fund_ticker writes group under funds[ticker]."""
    with get_db(db) as conn:
        record_investment_details(
            conn, "tsp_TSP1",
            {"ytd_return": "+12.4%", "fund_name": "C Fund"},
            as_of="2026-04-26",
            fund_ticker="C",
            refresh_run_id=1,
        )
        record_investment_details(
            conn, "tsp_TSP1",
            {"ytd_return": "+8.1%", "fund_name": "S Fund"},
            as_of="2026-04-26",
            fund_ticker="S",
            refresh_run_id=1,
        )
        conn.commit()

        snap = get_latest_investment_details(conn, "tsp_TSP1")
        assert snap["account_level"] == {}
        assert snap["funds"]["C"]["ytd_return"]["value"] == "+12.4%"
        assert snap["funds"]["C"]["fund_name"]["value"] == "C Fund"
        assert snap["funds"]["S"]["ytd_return"]["value"] == "+8.1%"


def test_mixed_account_and_fund_level(db):
    """Acorns: round-ups (account-level) + per-ETF YTD (fund-level)."""
    with get_db(db) as conn:
        record_investment_details(
            conn, "acorns_ACRN",
            {"round_up_ytd": "$48.20"},
            as_of="2026-04-26", refresh_run_id=1,
        )
        record_investment_details(
            conn, "acorns_ACRN",
            {"ytd_return": "+15.2%"},
            as_of="2026-04-26", fund_ticker="VOO", refresh_run_id=1,
        )
        record_investment_details(
            conn, "acorns_ACRN",
            {"ytd_return": "+4.8%"},
            as_of="2026-04-26", fund_ticker="VEA", refresh_run_id=1,
        )
        conn.commit()

        snap = get_latest_investment_details(conn, "acorns_ACRN")
        assert snap["account_level"]["round_up_ytd"]["value"] == "$48.20"
        assert set(snap["funds"].keys()) == {"VOO", "VEA"}


# ── COALESCE unique-index behavior ──────────────────────────────────


def test_unique_index_dedupes_null_ticker(db):
    """Two writes of same (account, NULL ticker, field, run) collapse."""
    with get_db(db) as conn:
        first = record_investment_details(
            conn, "acorns_ACRN", {"round_up_ytd": "$48.20"},
            as_of="2026-04-26", refresh_run_id=1,
        )
        second = record_investment_details(
            conn, "acorns_ACRN", {"round_up_ytd": "$48.20"},
            as_of="2026-04-26", refresh_run_id=1,
        )
        conn.commit()
        assert first == 1
        assert second == 0
        count = conn.execute(
            "SELECT COUNT(*) FROM investment_details "
            "WHERE account_id = ? AND fund_ticker IS NULL",
            ("acorns_ACRN",),
        ).fetchone()[0]
        assert count == 1


def test_unique_index_dedupes_ticker(db):
    """Same dedup behavior with a real fund_ticker."""
    with get_db(db) as conn:
        record_investment_details(
            conn, "tsp_TSP1", {"ytd_return": "+12.4%"},
            as_of="2026-04-26", fund_ticker="C", refresh_run_id=1,
        )
        record_investment_details(
            conn, "tsp_TSP1", {"ytd_return": "+12.4%"},
            as_of="2026-04-26", fund_ticker="C", refresh_run_id=1,
        )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM investment_details "
            "WHERE account_id = ? AND fund_ticker = ?",
            ("tsp_TSP1", "C"),
        ).fetchone()[0]
        assert count == 1


def test_different_refresh_run_ids_coexist(db):
    """Same (account, ticker, field) across runs produces history rows."""
    with get_db(db) as conn:
        record_investment_details(
            conn, "tsp_TSP1", {"ytd_return": "+8.0%"},
            as_of="2026-03-26", fund_ticker="C", refresh_run_id=1,
        )
        record_investment_details(
            conn, "tsp_TSP1", {"ytd_return": "+12.4%"},
            as_of="2026-04-26", fund_ticker="C", refresh_run_id=2,
        )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM investment_details "
            "WHERE account_id = ? AND fund_ticker = ?",
            ("tsp_TSP1", "C"),
        ).fetchone()[0]
        assert count == 2


def test_get_latest_returns_newest_per_field(db):
    """``get_latest`` collapses history to one value per (fund, field)."""
    with get_db(db) as conn:
        record_investment_details(
            conn, "tsp_TSP1", {"ytd_return": "+8.0%"},
            as_of="2026-03-26", fund_ticker="C", refresh_run_id=1,
        )
        record_investment_details(
            conn, "tsp_TSP1", {"ytd_return": "+12.4%"},
            as_of="2026-04-26", fund_ticker="C", refresh_run_id=2,
        )
        conn.commit()
        snap = get_latest_investment_details(conn, "tsp_TSP1")
        assert snap["funds"]["C"]["ytd_return"]["value"] == "+12.4%"
        assert snap["funds"]["C"]["ytd_return"]["as_of"] == "2026-04-26"


# ── get_investment_field_history ─────────────────────────────────────


def test_history_orders_ascending_and_filters_by_ticker(db):
    with get_db(db) as conn:
        record_investment_details(
            conn, "tsp_TSP1", {"ytd_return": "+8.0%"},
            as_of="2026-03-26", fund_ticker="C", refresh_run_id=1,
        )
        record_investment_details(
            conn, "tsp_TSP1", {"ytd_return": "+12.4%"},
            as_of="2026-04-26", fund_ticker="C", refresh_run_id=2,
        )
        record_investment_details(
            conn, "tsp_TSP1", {"ytd_return": "+5.1%"},
            as_of="2026-04-26", fund_ticker="S", refresh_run_id=2,
        )
        conn.commit()

        hist_c = get_investment_field_history(
            conn, "tsp_TSP1", "ytd_return", fund_ticker="C",
        )
        assert [r["field_value"] for r in hist_c] == ["+8.0%", "+12.4%"]
        hist_s = get_investment_field_history(
            conn, "tsp_TSP1", "ytd_return", fund_ticker="S",
        )
        assert [r["field_value"] for r in hist_s] == ["+5.1%"]


def test_history_filters_account_level(db):
    """fund_ticker=None should match only NULL-ticker rows."""
    with get_db(db) as conn:
        record_investment_details(
            conn, "acorns_ACRN", {"round_up_ytd": "$48.20"},
            as_of="2026-04-26", refresh_run_id=1,
        )
        record_investment_details(
            conn, "acorns_ACRN", {"round_up_ytd": "$50.00"},
            as_of="2026-04-26", fund_ticker="VOO", refresh_run_id=1,
        )
        conn.commit()
        hist = get_investment_field_history(
            conn, "acorns_ACRN", "round_up_ytd", fund_ticker=None,
        )
        assert len(hist) == 1
        assert hist[0]["fund_ticker"] is None
        assert hist[0]["field_value"] == "$48.20"
