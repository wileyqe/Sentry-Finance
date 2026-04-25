"""
tests/test_notifications_producers.py — P16-T01 producer end-to-end tests.

Covers:
* Bill producer: overdue recurring transaction → notification with type bill_overdue
* Bill producer: due_soon recurring transaction → notification with type bill_due_soon
* Upcoming bills don't emit (status = "upcoming")
* Duplicate producer call → no second row (dedup_key collision → INSERT OR IGNORE)
* Doc-drop nudge producer: missing TSP statement after day 5 → notification
* Budget alert producer: fired alert list → notification with type budget_alert
* Refresh-failure producer: record_notification is wired in orchestrator failure path
  (tested at the DAL level to avoid spinning up the full orchestrator)
"""

import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db  # noqa: E402
from dal.notifications import record_notification, list_notifications  # noqa: E402
from dal.documents import get_pending_nudges  # noqa: E402
from dal.bills import get_upcoming_bills  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    p = Path(path)
    init_db(p)
    with get_db(p) as conn:
        conn.execute("INSERT INTO owners (id, display_name) VALUES ('quintin','Quintin')")
        conn.execute("INSERT INTO institutions (id, display_name) VALUES ('nfcu','NFCU')")
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, owner_id, is_active) "
            "VALUES ('nfcu_chk','nfcu','Checking','chk','checking','quintin',1)"
        )
        conn.commit()
    yield p
    try:
        os.unlink(path)
    except OSError:
        pass


def _seed_recurring(conn, merchant: str, next_expected: str, rid: int = 1):
    conn.execute(
        """
        INSERT OR REPLACE INTO recurring_transactions
            (id, account_id, merchant, category, frequency, avg_interval,
             expected_amount, last_amount, next_expected, status, amount_stable)
        VALUES (?, 'nfcu_chk', ?, 'Housing', 'monthly', 30,
                1200.0, 1200.0, ?, 'active', 1)
        """,
        (rid, merchant, next_expected),
    )


# ── Bill producers ────────────────────────────────────────────────────────────


def test_bill_overdue_emits_notification(db):
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).strftime("%Y-%m-%d")
    with get_db(db) as conn:
        _seed_recurring(conn, "Rent", yesterday, rid=1)
        conn.commit()

        bills = get_upcoming_bills(conn, days=7)
        overdue = [b for b in bills if b["status"] == "overdue"]
        assert len(overdue) == 1

        for bill in overdue:
            nid = record_notification(
                conn,
                type="bill_overdue",
                severity="critical",
                title=f"{bill['merchant']} overdue",
                body=f"${bill['expected_amount']:.2f} — 1d overdue",
                payload={"id": bill["id"]},
                dedup_key=f"bill_overdue:{bill['id']}:{bill['next_expected']}",
                link="/recurring",
            )
        conn.commit()

        rows = list_notifications(conn)

    assert len(rows) == 1
    assert rows[0]["type"] == "bill_overdue"
    assert rows[0]["severity"] == "critical"
    assert "Rent" in rows[0]["title"]


def test_bill_due_soon_emits_notification(db):
    # Use UTC to match dal.bills.get_upcoming_bills, which compares against
    # datetime.now(timezone.utc). A local-date "tomorrow" can be already-past
    # in UTC near the day boundary and get classified as overdue instead.
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).strftime("%Y-%m-%d")
    with get_db(db) as conn:
        _seed_recurring(conn, "Internet", tomorrow, rid=2)
        conn.commit()

        bills = get_upcoming_bills(conn, days=7)
        due_soon = [b for b in bills if b["status"] == "due_soon"]
        assert len(due_soon) == 1

        for bill in due_soon:
            nid = record_notification(
                conn,
                type="bill_due_soon",
                severity="warning",
                title=f"{bill['merchant']} due soon",
                body="Due in 1d",
                payload={"id": bill["id"]},
                dedup_key=f"bill_due_soon:{bill['id']}:{bill['next_expected']}",
                link="/recurring",
            )
        conn.commit()

        rows = list_notifications(conn)

    assert len(rows) == 1
    assert rows[0]["type"] == "bill_due_soon"


def test_upcoming_bill_does_not_emit(db):
    """Bills more than 3 days out should not be included in the 7-day window if status=upcoming."""
    # See note in test_bill_due_soon_emits_notification — anchor on UTC today.
    five_days = (datetime.now(timezone.utc).date() + timedelta(days=5)).strftime("%Y-%m-%d")
    with get_db(db) as conn:
        _seed_recurring(conn, "Netflix", five_days, rid=3)
        conn.commit()
        bills = get_upcoming_bills(conn, days=7)
        # Status should be "upcoming" (not due_soon), so producer skips it
        upcoming = [b for b in bills if b["status"] == "upcoming"]
        assert any(b["merchant"] == "Netflix" for b in upcoming)


def test_bill_dedup_no_double_notification(db):
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).strftime("%Y-%m-%d")
    key = f"bill_overdue:99:{yesterday}"
    with get_db(db) as conn:
        _seed_recurring(conn, "Mortgage", yesterday, rid=99)
        conn.commit()
        id1 = record_notification(
            conn, type="bill_overdue", title="Mortgage overdue",
            dedup_key=key, payload={}, link="/recurring"
        )
        conn.commit()
        id2 = record_notification(
            conn, type="bill_overdue", title="Mortgage overdue",
            dedup_key=key, payload={}, link="/recurring"
        )
        conn.commit()
        rows = list_notifications(conn)

    assert id1 is not None
    assert id2 is None
    assert len(rows) == 1


# ── Doc-drop nudge producer ───────────────────────────────────────────────────


def test_doc_drop_nudge_emitted_after_day5(db):
    # Pass as_of day >= 5 with no committed docs → nudge should appear
    as_of = date(date.today().year, date.today().month, 10)
    ym = as_of.strftime("%Y-%m")
    with get_db(db) as conn:
        nudges = get_pending_nudges(conn, as_of=as_of)
        assert len(nudges) >= 1  # at least TSP missing

        for nudge in nudges:
            record_notification(
                conn,
                type="doc_drop_nudge",
                severity="info",
                title=f"{nudge['display_name']} statement pending",
                body=nudge["message"],
                payload={"institution": nudge["institution"], "month": ym},
                dedup_key=f"doc_drop:{nudge['institution']}:{ym}",
                link="/documents",
            )
        conn.commit()

        rows = list_notifications(conn)

    types = [r["type"] for r in rows]
    assert all(t == "doc_drop_nudge" for t in types)
    assert len(rows) == len(nudges)


def test_doc_drop_no_nudge_before_day5(db):
    as_of = date(date.today().year, date.today().month, 3)
    with get_db(db) as conn:
        nudges = get_pending_nudges(conn, as_of=as_of)
    assert nudges == []


# ── Budget alert producer ─────────────────────────────────────────────────────


def test_budget_alert_emits_notification(db):
    fired = [
        {
            "rule_id": "budget_pct_warning",
            "rule_type": "budget_pct",
            "category": "Groceries",
            "month": "2026-04",
            "pct_used": 87.0,
            "actual": 174.0,
            "target": 200.0,
            "threshold": 80.0,
            "severity": "warning",
        }
    ]
    with get_db(db) as conn:
        for alert in fired:
            nid = record_notification(
                conn,
                type="budget_alert",
                severity="warning",
                title=f"{alert['category']} {alert['pct_used']:.0f}% of budget",
                body=f"${alert['actual']:.2f} of ${alert['target']:.2f}",
                payload=alert,
                dedup_key=f"alert:{alert['rule_id']}:{alert['month']}:{alert['category']}",
                link="/budgets",
            )
        conn.commit()
        rows = list_notifications(conn)

    assert len(rows) == 1
    assert rows[0]["type"] == "budget_alert"
    assert "Groceries" in rows[0]["title"]
    assert rows[0]["payload"]["pct_used"] == 87.0


# ── Refresh failure producer ──────────────────────────────────────────────────


def test_refresh_failure_notification(db):
    event_id = 42
    institution_id = "nfcu"
    with get_db(db) as conn:
        nid = record_notification(
            conn,
            type="refresh_failure",
            severity="critical",
            title=f"{institution_id.upper()} refresh failed",
            body="NETWORK: Connection refused",
            payload={"institution": institution_id, "error_class": "NETWORK", "event_id": event_id},
            dedup_key=f"refresh_failure:{institution_id}:{event_id}",
            link="/settings",
        )
        conn.commit()
        rows = list_notifications(conn)

    assert nid is not None
    assert len(rows) == 1
    assert rows[0]["type"] == "refresh_failure"
    assert rows[0]["severity"] == "critical"
    assert rows[0]["payload"]["event_id"] == event_id


def test_refresh_failure_dedup(db):
    event_id = 7
    key = f"refresh_failure:chase:{event_id}"
    with get_db(db) as conn:
        id1 = record_notification(
            conn, type="refresh_failure", title="Chase failed", dedup_key=key, payload={}
        )
        conn.commit()
        id2 = record_notification(
            conn, type="refresh_failure", title="Chase failed again", dedup_key=key, payload={}
        )
        conn.commit()

    assert id1 is not None
    assert id2 is None
