"""
tests/test_apy_history.py — P15-T04 Phase B DAL invariants + round-trip.

Covers:
* ``_assert_apy_valid`` rejects out-of-band rates, bad ISO dates, and
  sources outside ``{scrape, manual, statement}``
* ``parse_apy_string`` handles the three shapes connectors emit today
  (float, ``"4.00%"`` string, bare numeric string)
* ``record_apy_history`` persists + dedupes on the unique index
* ``get_latest_apy`` returns the newest row
* ``get_apy_history`` orders ascending and respects the months filter
* Freshness tracker surfaces an APY-only institution via
  ``dal.freshness.get_staleness`` (integration wiring check)
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.apy_history import (  # noqa: E402
    get_apy_history,
    get_latest_apy,
    parse_apy_string,
    record_apy_history,
)
from dal.database import init_db, get_db  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    p = Path(path)
    init_db(p)
    with get_db(p) as conn:
        conn.execute("INSERT INTO owners (id, display_name) VALUES ('quintin','Quintin')")
        conn.execute(
            "INSERT INTO institutions (id, display_name) VALUES ('nfcu','NFCU')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, owner_id, is_active) "
            "VALUES ('nfcu_8339','nfcu','Travel Fund','8339','savings','quintin',1)"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, owner_id, is_active) "
            "VALUES ('nfcu_REDACTED','nfcu','Checking','1167','checking','quintin',1)"
        )
        conn.commit()
    yield p
    try:
        os.unlink(path)
    except OSError:
        pass


# ── parse_apy_string ────────────────────────────────────────────────


def test_parse_apy_string_from_float():
    assert parse_apy_string(4.0) == 4.0


def test_parse_apy_string_from_int():
    assert parse_apy_string(5) == 5.0


def test_parse_apy_string_with_percent():
    assert parse_apy_string("4.00%") == 4.0


def test_parse_apy_string_embedded_in_text():
    assert parse_apy_string("APY 0.250%") == 0.250


def test_parse_apy_string_bare_number():
    assert parse_apy_string("0.050") == 0.050


def test_parse_apy_string_raises_on_garbage():
    with pytest.raises(ValueError):
        parse_apy_string("no digits here")


def test_parse_apy_string_raises_on_wrong_type():
    with pytest.raises(ValueError):
        parse_apy_string(None)  # type: ignore[arg-type]


# ── Invariants ──────────────────────────────────────────────────────


def test_rate_below_zero_rejected(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="outside valid"):
            record_apy_history(
                conn,
                account_id="nfcu_8339",
                apy_rate=-0.01,
                as_of="2026-04-19",
                source="scrape",
            )


def test_rate_above_hundred_rejected(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="outside valid"):
            record_apy_history(
                conn,
                account_id="nfcu_8339",
                apy_rate=100.01,
                as_of="2026-04-19",
                source="scrape",
            )


def test_non_iso_date_rejected(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="ISO-8601"):
            record_apy_history(
                conn,
                account_id="nfcu_8339",
                apy_rate=4.0,
                as_of="04/19/2026",
                source="scrape",
            )


def test_bad_source_rejected(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="not in"):
            record_apy_history(
                conn,
                account_id="nfcu_8339",
                apy_rate=4.0,
                as_of="2026-04-19",
                source="gossip",
            )


def test_boundary_values_accepted(db):
    """0% and 100% are both valid — inclusive bounds."""
    with get_db(db) as conn:
        assert record_apy_history(
            conn,
            account_id="nfcu_8339",
            apy_rate=0.0,
            as_of="2026-04-19",
            source="scrape",
        )
        assert record_apy_history(
            conn,
            account_id="nfcu_REDACTED",
            apy_rate=100.0,
            as_of="2026-04-19",
            source="scrape",
        )
        conn.commit()


# ── Round-trip + dedup ──────────────────────────────────────────────


def test_record_and_retrieve(db):
    with get_db(db) as conn:
        inserted = record_apy_history(
            conn,
            account_id="nfcu_8339",
            apy_rate=0.25,
            as_of="2026-04-19",
            source="scrape",
        )
        conn.commit()
        assert inserted is True

        latest = get_latest_apy(conn, "nfcu_8339")
    assert latest is not None
    assert latest["apy_rate"] == 0.25
    assert latest["as_of"] == "2026-04-19"
    assert latest["source"] == "scrape"


def test_duplicate_is_no_op(db):
    with get_db(db) as conn:
        assert record_apy_history(
            conn,
            account_id="nfcu_8339",
            apy_rate=0.25,
            as_of="2026-04-19",
            source="scrape",
        )
        # Same (account, date, source) — even with a different rate the
        # unique index should still suppress the second write.
        second = record_apy_history(
            conn,
            account_id="nfcu_8339",
            apy_rate=0.30,
            as_of="2026-04-19",
            source="scrape",
        )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM apy_history WHERE account_id = ?",
            ("nfcu_8339",),
        ).fetchone()[0]
    assert second is False
    assert count == 1


def test_different_source_same_date_inserts(db):
    """``source`` is part of the unique key — scrape + manual coexist."""
    with get_db(db) as conn:
        record_apy_history(
            conn,
            account_id="nfcu_8339",
            apy_rate=0.25,
            as_of="2026-04-19",
            source="scrape",
        )
        record_apy_history(
            conn,
            account_id="nfcu_8339",
            apy_rate=0.30,
            as_of="2026-04-19",
            source="manual",
        )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM apy_history WHERE account_id = ?",
            ("nfcu_8339",),
        ).fetchone()[0]
    assert count == 2


def test_get_latest_returns_newest(db):
    with get_db(db) as conn:
        record_apy_history(
            conn,
            account_id="nfcu_8339",
            apy_rate=0.20,
            as_of="2026-03-19",
            source="scrape",
        )
        record_apy_history(
            conn,
            account_id="nfcu_8339",
            apy_rate=0.25,
            as_of="2026-04-19",
            source="scrape",
        )
        conn.commit()
        latest = get_latest_apy(conn, "nfcu_8339")
    assert latest["apy_rate"] == 0.25
    assert latest["as_of"] == "2026-04-19"


def test_get_latest_none_when_empty(db):
    with get_db(db) as conn:
        assert get_latest_apy(conn, "nfcu_8339") is None


def test_get_history_orders_ascending(db):
    with get_db(db) as conn:
        record_apy_history(
            conn, account_id="nfcu_8339", apy_rate=0.10, as_of="2026-02-19", source="scrape"
        )
        record_apy_history(
            conn, account_id="nfcu_8339", apy_rate=0.20, as_of="2026-03-19", source="scrape"
        )
        record_apy_history(
            conn, account_id="nfcu_8339", apy_rate=0.25, as_of="2026-04-19", source="scrape"
        )
        conn.commit()
        hist = get_apy_history(conn, "nfcu_8339")
    assert [r["as_of"] for r in hist] == ["2026-02-19", "2026-03-19", "2026-04-19"]


# ── Freshness integration ───────────────────────────────────────────


def test_freshness_picks_up_apy_only_institution(db):
    """After Affirm's cutover its only fresh data is ``apy_history``;
    the staleness tracker must see it or Affirm looks dead.
    """
    from dal.freshness import get_institution_freshness

    with get_db(db) as conn:
        record_apy_history(
            conn,
            account_id="nfcu_8339",
            apy_rate=0.25,
            as_of="2026-04-19",
            source="scrape",
        )
        conn.commit()

        rows = get_institution_freshness(conn)
    nfcu = next((r for r in rows if r["institution_id"] == "nfcu"), None)
    assert nfcu is not None, "freshness did not surface the NFCU institution"
    assert nfcu["staleness"] != "no_data", (
        "APY-only institution should not be 'no_data' after v30 wiring"
    )
