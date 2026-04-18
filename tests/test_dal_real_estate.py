"""
tests/test_dal_real_estate.py — Unit tests for ``dal/real_estate.py``.

Covers ``record_real_estate_valuations`` happy path, every invariant
failure mode, and the empty-list no-op.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db  # noqa: E402
from dal.real_estate import record_real_estate_valuations  # noqa: E402


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


def test_happy_path_single_row(db):
    with get_db(db) as conn:
        result = record_real_estate_valuations(
            conn,
            [{"name": "123 Main", "estimated_value": 450000.0, "as_of": "2026-01-15"}],
        )
        conn.commit()
        assert result == {"inserted": 1}
        row = conn.execute("SELECT * FROM real_estate").fetchone()
        assert row["name"] == "123 Main"
        assert row["estimated_value"] == 450000.0
        assert row["source"] == "manual"
        assert row["owner_id"] is None
        assert row["linked_loan_id"] is None


def test_happy_path_batch_with_optional_fields(db):
    with get_db(db) as conn:
        conn.execute("INSERT INTO owners (id, display_name) VALUES ('quintin','Quintin')")
        conn.execute("INSERT INTO institutions (id, display_name) VALUES ('nfcu','NFCU')")
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type) "
            "VALUES ('nfcu_9999','nfcu','Mortgage','9999','mortgage')"
        )
        conn.commit()

        rows = [
            {"name": "123 Main", "estimated_value": 450000.0, "as_of": "2026-01-15",
             "source": "zillow", "owner_id": "quintin", "linked_loan_id": "nfcu_9999"},
            {"name": "123 Main", "estimated_value": 460000.0, "as_of": "2026-02-15",
             "source": "redfin", "owner_id": "quintin"},
        ]
        result = record_real_estate_valuations(conn, rows)
        conn.commit()

    assert result == {"inserted": 2}
    with get_db(db) as conn:
        stored = conn.execute("SELECT name, estimated_value, source, owner_id, linked_loan_id "
                              "FROM real_estate ORDER BY as_of").fetchall()
    assert [dict(r) for r in stored] == [
        {"name": "123 Main", "estimated_value": 450000.0, "source": "zillow",
         "owner_id": "quintin", "linked_loan_id": "nfcu_9999"},
        {"name": "123 Main", "estimated_value": 460000.0, "source": "redfin",
         "owner_id": "quintin", "linked_loan_id": None},
    ]


def test_empty_list_is_noop(db):
    with get_db(db) as conn:
        result = record_real_estate_valuations(conn, [])
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM real_estate").fetchone()[0]
    assert result == {"inserted": 0}
    assert count == 0


def test_invariant_missing_required_key(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="missing required key"):
            record_real_estate_valuations(
                conn,
                [{"estimated_value": 400000.0, "as_of": "2026-01-15"}],  # missing name
            )


def test_invariant_rejects_zero_or_negative_value(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="estimated_value must be > 0"):
            record_real_estate_valuations(
                conn,
                [{"name": "A", "estimated_value": 0, "as_of": "2026-01-15"}],
            )
        with pytest.raises(ValueError, match="estimated_value must be > 0"):
            record_real_estate_valuations(
                conn,
                [{"name": "A", "estimated_value": -1.0, "as_of": "2026-01-15"}],
            )


def test_invariant_rejects_non_numeric_value(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="estimated_value must be > 0"):
            record_real_estate_valuations(
                conn,
                [{"name": "A", "estimated_value": "400000", "as_of": "2026-01-15"}],
            )


def test_invariant_rejects_malformed_as_of(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="is not a parseable ISO date"):
            record_real_estate_valuations(
                conn,
                [{"name": "A", "estimated_value": 400000.0, "as_of": "not-a-date"}],
            )


def test_invariant_accepts_iso_datetime(db):
    with get_db(db) as conn:
        record_real_estate_valuations(
            conn,
            [{"name": "A", "estimated_value": 400000.0,
              "as_of": "2026-01-15T12:00:00"}],
        )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM real_estate").fetchone()[0]
    assert count == 1


def test_failure_before_any_write(db):
    """A failing row anywhere in the batch prevents all writes."""
    with get_db(db) as conn:
        with pytest.raises(ValueError):
            record_real_estate_valuations(
                conn,
                [
                    {"name": "A", "estimated_value": 400000.0, "as_of": "2026-01-15"},
                    {"name": "B", "estimated_value": -5.0, "as_of": "2026-01-15"},
                ],
            )
        count = conn.execute("SELECT COUNT(*) FROM real_estate").fetchone()[0]
    assert count == 0
