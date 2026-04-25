"""
tests/test_notifications_sse.py — P16-T03 SSE broadcast hook.

Verifies the broadcast contract added to ``record_notification``:
* Successful insert publishes a ``notification`` SSE event with the
  expected payload shape.
* Dedup collision (INSERT OR IGNORE returns None) does NOT publish.
* The published topic name comes from the registry, not a string
  literal — protects against silent rename drift.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db  # noqa: E402
from dal.notifications import record_notification  # noqa: E402
from backend import sse_topics  # noqa: E402


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


def test_successful_insert_broadcasts_notification(db):
    with patch("backend.events.broadcast_event") as mock_broadcast:
        with get_db(db) as conn:
            new_id = record_notification(
                conn,
                type="budget_alert",
                severity="warning",
                title="Groceries 90% of budget",
                body="$180 of $200",
                dedup_key="alert:budget:2026-04:Groceries",
            )
            conn.commit()

    assert isinstance(new_id, int)
    mock_broadcast.assert_called_once()
    args, _ = mock_broadcast.call_args
    topic, payload = args
    assert topic == sse_topics.NOTIFICATION
    assert payload == {
        "id": new_id,
        "type": "budget_alert",
        "severity": "warning",
        "title": "Groceries 90% of budget",
        "dedup_key": "alert:budget:2026-04:Groceries",
    }


def test_dedup_collision_does_not_broadcast(db):
    key = "alert:budget:2026-04:Rent"
    with patch("backend.events.broadcast_event") as mock_broadcast:
        with get_db(db) as conn:
            id1 = record_notification(
                conn, type="budget_alert", title="Rent", dedup_key=key
            )
            conn.commit()
            id2 = record_notification(
                conn, type="budget_alert", title="Rent dup", dedup_key=key
            )
            conn.commit()

    assert id1 is not None
    assert id2 is None
    # Only the first insert should have broadcast.
    assert mock_broadcast.call_count == 1


def test_broadcast_uses_registry_constant(db):
    """The topic published must be sse_topics.NOTIFICATION, not a string literal."""
    with patch("backend.events.broadcast_event") as mock_broadcast:
        with get_db(db) as conn:
            record_notification(
                conn,
                type="doc_drop_nudge",
                title="TSP statement available",
                dedup_key="doc:tsp:2026-04",
            )
            conn.commit()

    args, _ = mock_broadcast.call_args
    assert args[0] == "notification"
    assert args[0] == sse_topics.NOTIFICATION
