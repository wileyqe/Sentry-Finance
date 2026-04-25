"""
tests/test_notifications_dal.py — P16-T01 DAL invariants + round-trip.

Covers:
* ``_assert_valid`` rejects unknown type, bad severity, empty dedup_key,
  and non-JSON-serializable payload
* ``record_notification`` inserts and returns the new row id
* Duplicate ``dedup_key`` → ``INSERT OR IGNORE`` returns None
* ``list_notifications`` orders newest-first and respects include_dismissed
* ``get_unread_count`` counts only undismissed + unread rows
* ``mark_read`` with ids=None marks all; with a list marks only those rows
* ``dismiss`` hides rows from the default feed
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db  # noqa: E402
from dal.notifications import (  # noqa: E402
    dismiss,
    get_unread_count,
    list_notifications,
    mark_read,
    record_notification,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    p = Path(path)
    init_db(p)
    yield p
    try:
        os.unlink(path)
    except OSError:
        pass


# ── Invariants ────────────────────────────────────────────────────────────────


def test_invalid_type_raises(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="notifications.type"):
            record_notification(conn, type="unknown_type", title="x", dedup_key="k1")


def test_invalid_severity_raises(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="notifications.severity"):
            record_notification(
                conn, type="budget_alert", severity="low", title="x", dedup_key="k2"
            )


def test_empty_dedup_key_raises(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="dedup_key"):
            record_notification(conn, type="budget_alert", title="x", dedup_key="")


def test_non_serializable_payload_raises(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="JSON-serializable"):
            record_notification(
                conn,
                type="budget_alert",
                title="x",
                dedup_key="k3",
                payload={"fn": lambda: None},
            )


# ── Record + round-trip ───────────────────────────────────────────────────────


def test_record_returns_id(db):
    with get_db(db) as conn:
        row_id = record_notification(
            conn,
            type="budget_alert",
            severity="warning",
            title="Groceries 85% of budget",
            body="$170 of $200",
            payload={"category": "Groceries", "pct_used": 85.0},
            dedup_key="alert:budget_pct_warning:2026-04:Groceries",
            link="/budgets",
        )
        conn.commit()

    assert isinstance(row_id, int)
    assert row_id > 0


def test_dedup_returns_none(db):
    key = "alert:budget_pct_warning:2026-04:Rent"
    with get_db(db) as conn:
        id1 = record_notification(
            conn, type="budget_alert", title="Rent", dedup_key=key
        )
        conn.commit()
        id2 = record_notification(
            conn, type="budget_alert", title="Rent again", dedup_key=key
        )
        conn.commit()

    assert id1 is not None
    assert id2 is None


def test_payload_round_trips(db):
    payload = {"category": "Food", "pct_used": 90.5, "actual": 180.0}
    key = "alert:budget_pct_over:2026-04:Food"
    with get_db(db) as conn:
        record_notification(
            conn, type="budget_alert", title="Food over", dedup_key=key, payload=payload
        )
        conn.commit()
        rows = list_notifications(conn)

    assert rows[0]["payload"] == payload


# ── list_notifications ────────────────────────────────────────────────────────


def test_list_ordered_newest_first(db):
    with get_db(db) as conn:
        record_notification(conn, type="doc_drop_nudge", title="First", dedup_key="dd:1")
        conn.commit()
        record_notification(conn, type="doc_drop_nudge", title="Second", dedup_key="dd:2")
        conn.commit()
        rows = list_notifications(conn)

    assert rows[0]["title"] == "Second"
    assert rows[1]["title"] == "First"


def test_list_excludes_dismissed_by_default(db):
    with get_db(db) as conn:
        id1 = record_notification(
            conn, type="budget_alert", title="Visible", dedup_key="v:1"
        )
        id2 = record_notification(
            conn, type="budget_alert", title="Dismissed", dedup_key="v:2"
        )
        conn.commit()
        dismiss(conn, [id2])
        conn.commit()
        active = list_notifications(conn)
        all_rows = list_notifications(conn, include_dismissed=True)

    assert len(active) == 1
    assert active[0]["title"] == "Visible"
    assert len(all_rows) == 2


# ── get_unread_count ──────────────────────────────────────────────────────────


def test_unread_count_excludes_read_and_dismissed(db):
    with get_db(db) as conn:
        id1 = record_notification(conn, type="budget_alert", title="Unread", dedup_key="u:1")
        id2 = record_notification(conn, type="budget_alert", title="Read", dedup_key="u:2")
        id3 = record_notification(
            conn, type="budget_alert", title="Dismissed", dedup_key="u:3"
        )
        conn.commit()
        mark_read(conn, [id2])
        dismiss(conn, [id3])
        conn.commit()
        count = get_unread_count(conn)

    assert count == 1


# ── mark_read ─────────────────────────────────────────────────────────────────


def test_mark_read_specific_ids(db):
    with get_db(db) as conn:
        id1 = record_notification(conn, type="bill_overdue", title="A", dedup_key="r:1")
        id2 = record_notification(conn, type="bill_overdue", title="B", dedup_key="r:2")
        conn.commit()
        updated = mark_read(conn, [id1])
        conn.commit()
        rows = list_notifications(conn)

    assert updated == 1
    by_id = {r["id"]: r for r in rows}
    assert by_id[id1]["read_at"] is not None
    assert by_id[id2]["read_at"] is None


def test_mark_read_all(db):
    with get_db(db) as conn:
        record_notification(conn, type="refresh_failure", title="X", dedup_key="ra:1")
        record_notification(conn, type="refresh_failure", title="Y", dedup_key="ra:2")
        conn.commit()
        updated = mark_read(conn, ids=None)
        conn.commit()
        count = get_unread_count(conn)

    assert updated == 2
    assert count == 0


def test_mark_read_idempotent(db):
    with get_db(db) as conn:
        id1 = record_notification(
            conn, type="bill_due_soon", title="Rent", dedup_key="idem:1"
        )
        conn.commit()
        mark_read(conn, [id1])
        conn.commit()
        updated_again = mark_read(conn, [id1])
        conn.commit()

    assert updated_again == 0


# ── dismiss ───────────────────────────────────────────────────────────────────


def test_dismiss_hides_row(db):
    with get_db(db) as conn:
        id1 = record_notification(
            conn, type="doc_drop_nudge", title="TSP", dedup_key="dism:1"
        )
        conn.commit()
        dismiss(conn, [id1])
        conn.commit()
        active = list_notifications(conn)
        all_rows = list_notifications(conn, include_dismissed=True)

    assert len(active) == 0
    assert all_rows[0]["dismissed_at"] is not None


def test_dismiss_empty_list_noop(db):
    with get_db(db) as conn:
        updated = dismiss(conn, [])

    assert updated == 0
