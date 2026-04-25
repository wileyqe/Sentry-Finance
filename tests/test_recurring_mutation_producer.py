"""
tests/test_recurring_mutation_producer.py — P16-T02 recurring price mutations.

Covers ``dal.recurring.list_all_mutations`` and the dedup contract the
producer step uses inside ``backend/result_writer.py::_notifications``.

The detection logic that *writes* to ``recurring_mutations`` lives in
``dal/recurring.py::detect_recurring`` and is already tested elsewhere;
these tests focus on the surfacing path.
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
from dal.recurring import list_all_mutations  # noqa: E402
from dal.notifications import list_notifications, record_notification  # noqa: E402


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


def _seed_recurring_with_mutation(
    conn,
    *,
    rid: str,
    merchant: str,
    old: float,
    new: float,
    desc: str = "Price changed",
):
    """Seed a recurring_transactions parent + a recurring_mutations row."""
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) VALUES ('chase', 'Chase')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO accounts (id, institution_id, name, last4, type) "
        "VALUES ('chase_chk', 'chase', 'Chase Checking', '0000', 'checking')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO recurring_transactions "
        "(id, account_id, merchant, category, frequency, avg_interval, "
        " expected_amount, amount_stable, last_amount, last_date, next_expected) "
        "VALUES (?, 'chase_chk', ?, 'Subscriptions', 'monthly', 30, ?, 1, ?, "
        "'2026-04-01', '2026-05-01')",
        (rid, merchant, new, new),
    )
    conn.execute(
        "INSERT INTO recurring_mutations "
        "(recurring_id, old_amount, new_amount, description) "
        "VALUES (?, ?, ?, ?)",
        (rid, old, new, desc),
    )


def test_list_all_mutations_joins_merchant(db):
    with get_db(db) as conn:
        _seed_recurring_with_mutation(
            conn, rid="r1", merchant="Netflix", old=15.49, new=17.99
        )
        conn.commit()
        rows = list_all_mutations(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r["merchant"] == "Netflix"
    assert r["old_amount"] == 15.49
    assert r["new_amount"] == 17.99
    assert r["recurring_id"] == "r1"


def test_producer_emits_one_notification_per_mutation(db):
    with get_db(db) as conn:
        _seed_recurring_with_mutation(
            conn, rid="r1", merchant="Netflix", old=15.49, new=17.99
        )
        _seed_recurring_with_mutation(
            conn, rid="r2", merchant="Spotify", old=9.99, new=11.99
        )
        conn.commit()

        with patch("backend.events.broadcast_event"):
            for mut in list_all_mutations(conn):
                record_notification(
                    conn,
                    type="recurring_price_mutation",
                    severity="warning",
                    title=f"{mut['merchant']} price changed",
                    dedup_key=f"recurring_mutation:{mut['id']}",
                )
            conn.commit()

        rows = [n for n in list_notifications(conn)
                if n["type"] == "recurring_price_mutation"]
    assert len(rows) == 2
    titles = sorted(r["title"] for r in rows)
    assert titles == ["Netflix price changed", "Spotify price changed"]


def test_producer_dedup_blocks_double_fire(db):
    """Re-running the producer on the same mutation row must not duplicate."""
    with get_db(db) as conn:
        _seed_recurring_with_mutation(
            conn, rid="r1", merchant="Netflix", old=15.49, new=17.99
        )
        conn.commit()

        # Two passes simulating two consecutive refreshes
        for _ in range(2):
            with patch("backend.events.broadcast_event"):
                for mut in list_all_mutations(conn):
                    record_notification(
                        conn,
                        type="recurring_price_mutation",
                        severity="warning",
                        title="ignored",
                        dedup_key=f"recurring_mutation:{mut['id']}",
                    )
                conn.commit()

        rows = [n for n in list_notifications(conn)
                if n["type"] == "recurring_price_mutation"]
    assert len(rows) == 1
