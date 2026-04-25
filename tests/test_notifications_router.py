"""
tests/test_notifications_router.py — P16-T01 router smoke tests.

Uses monkeypatch to redirect the router's get_db to a temp DB, then
calls handler functions directly (same pattern as test_accounts_details_endpoint.py).

Covers:
* GET  /api/notifications returns feed + respects include_dismissed param
* GET  /api/notifications/unread-count returns badge count
* POST /api/notifications/mark-read with ids marks specific rows; no body marks all
* POST /api/notifications/dismiss hides rows from active feed
"""

import os
import sys
import tempfile
from functools import partial
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.routers import notifications as notifications_router  # noqa: E402
from dal.connection import get_db as real_get_db  # noqa: E402
from dal.database import init_db  # noqa: E402
from dal.notifications import record_notification  # noqa: E402
from backend.routers.notifications import IdsBody, DismissBody  # noqa: E402


@pytest.fixture
def db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    p = Path(path)
    init_db(p)
    with real_get_db(p) as conn:
        conn.execute("INSERT INTO owners (id, display_name) VALUES ('quintin','Quintin')")
        conn.commit()
        id1 = record_notification(
            conn,
            type="budget_alert",
            title="Groceries 90%",
            dedup_key="a:1",
        )
        id2 = record_notification(
            conn,
            type="refresh_failure",
            title="NFCU failed",
            dedup_key="a:2",
            severity="critical",
        )
        conn.commit()

    monkeypatch.setattr(notifications_router, "get_db", partial(real_get_db, p))

    yield p, id1, id2

    try:
        os.unlink(path)
    except OSError:
        pass


# ── GET /api/notifications ────────────────────────────────────────────────────


def test_get_notifications_returns_feed(db):
    _, _, _ = db
    result = notifications_router.get_notifications(include_dismissed=False, limit=50)
    assert len(result["notifications"]) == 2


def test_get_notifications_excludes_dismissed(db):
    p, id1, _ = db
    notifications_router.dismiss_notifications(DismissBody(ids=[id1]))
    result = notifications_router.get_notifications(include_dismissed=False, limit=50)
    assert len(result["notifications"]) == 1


def test_get_notifications_include_dismissed(db):
    p, id1, _ = db
    notifications_router.dismiss_notifications(DismissBody(ids=[id1]))
    result = notifications_router.get_notifications(include_dismissed=True, limit=50)
    assert len(result["notifications"]) == 2


# ── GET /api/notifications/unread-count ──────────────────────────────────────


def test_unread_count(db):
    result = notifications_router.unread_count()
    assert result["count"] == 2


def test_unread_count_drops_after_mark_read(db):
    notifications_router.mark_notifications_read(IdsBody(ids=None))
    result = notifications_router.unread_count()
    assert result["count"] == 0


# ── POST /api/notifications/mark-read ────────────────────────────────────────


def test_mark_read_specific_ids(db):
    _, id1, id2 = db
    result = notifications_router.mark_notifications_read(IdsBody(ids=[id1]))
    assert result["updated"] == 1
    # id2 still unread
    assert notifications_router.unread_count()["count"] == 1


def test_mark_read_no_body_marks_all(db):
    result = notifications_router.mark_notifications_read(IdsBody(ids=None))
    assert result["updated"] == 2
    assert notifications_router.unread_count()["count"] == 0


# ── POST /api/notifications/dismiss ──────────────────────────────────────────


def test_dismiss_removes_from_active_feed(db):
    _, id1, id2 = db
    result = notifications_router.dismiss_notifications(DismissBody(ids=[id1, id2]))
    assert result["updated"] == 2
    assert notifications_router.get_notifications(include_dismissed=False, limit=50)["notifications"] == []
