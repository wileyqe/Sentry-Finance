"""
tests/test_apy_change_producer.py — P16-T02 APY rate-change detector.

Covers ``dal.apy_history.detect_apy_changes`` and the dedup path the
producer uses inside ``backend/result_writer.py::_notifications``.

Threshold contract (locked Phase 16 scope):
* Δ ≥ 0.05% (5 basis points) to fire at all
* |Δ| < 0.25% → severity ``info``
* |Δ| ≥ 0.25% → severity ``warning``
* Direction-agnostic — both rate cuts and rate increases fire
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
from dal.apy_history import detect_apy_changes, record_apy_history  # noqa: E402
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


def _seed_account(conn, account_id: str, name: str = "Test Account"):
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) VALUES ('summit', 'Summit FCU')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO accounts (id, institution_id, name, last4, type) "
        "VALUES (?, 'summit', ?, '0000', 'savings')",
        (account_id, name),
    )


def _seed_apy(conn, account_id: str, rate: float, as_of: str):
    record_apy_history(
        conn, account_id=account_id, apy_rate=rate, as_of=as_of, source="scrape"
    )


# ── detect_apy_changes contract ──────────────────────────────────────────────


def test_single_row_yields_no_change(db):
    with get_db(db) as conn:
        _seed_account(conn, "summit_chk")
        _seed_apy(conn, "summit_chk", 4.00, "2026-04-01")
        conn.commit()
        changes = detect_apy_changes(conn)
    assert changes == []


def test_unchanged_rate_yields_no_change(db):
    with get_db(db) as conn:
        _seed_account(conn, "summit_chk")
        _seed_apy(conn, "summit_chk", 4.00, "2026-04-01")
        _seed_apy(conn, "summit_chk", 4.00, "2026-04-15")
        conn.commit()
        changes = detect_apy_changes(conn)
    assert changes == []


def test_below_threshold_yields_no_change(db):
    """A 4 bp change (0.04%) is under the 5 bp floor — suppress."""
    with get_db(db) as conn:
        _seed_account(conn, "summit_chk")
        _seed_apy(conn, "summit_chk", 4.00, "2026-04-01")
        _seed_apy(conn, "summit_chk", 4.04, "2026-04-15")
        conn.commit()
        changes = detect_apy_changes(conn)
    assert changes == []


def test_info_severity_for_small_change(db):
    """A 10 bp change (0.10%) crosses the floor but stays under the warning split."""
    with get_db(db) as conn:
        _seed_account(conn, "summit_chk", name="Summit Checking")
        _seed_apy(conn, "summit_chk", 4.00, "2026-04-01")
        _seed_apy(conn, "summit_chk", 4.10, "2026-04-15")
        conn.commit()
        changes = detect_apy_changes(conn)
    assert len(changes) == 1
    c = changes[0]
    assert c["account_id"] == "summit_chk"
    assert c["account_name"] == "Summit Checking"
    assert c["old_rate"] == 4.00
    assert c["new_rate"] == 4.10
    assert c["severity"] == "info"
    assert round(c["delta"], 4) == 0.10


def test_warning_severity_for_large_change(db):
    """A 75 bp jump (0.75%) is a warning-tier event."""
    with get_db(db) as conn:
        _seed_account(conn, "summit_savings")
        _seed_apy(conn, "summit_savings", 3.50, "2026-03-01")
        _seed_apy(conn, "summit_savings", 4.25, "2026-04-15")
        conn.commit()
        changes = detect_apy_changes(conn)
    assert len(changes) == 1
    assert changes[0]["severity"] == "warning"


def test_rate_cut_fires_direction_agnostic(db):
    """Direction-agnostic: a cut crosses the floor and emits."""
    with get_db(db) as conn:
        _seed_account(conn, "affirm_hysa")
        _seed_apy(conn, "affirm_hysa", 4.50, "2026-03-01")
        _seed_apy(conn, "affirm_hysa", 4.00, "2026-04-15")
        conn.commit()
        changes = detect_apy_changes(conn)
    assert len(changes) == 1
    c = changes[0]
    assert c["delta"] < 0  # signed delta preserved
    assert c["severity"] == "warning"


def test_walks_past_intermediate_duplicates(db):
    """Latest is 4.25; 4.25 4.25 4.00 → prior found is 4.00 (the most recent *different*)."""
    with get_db(db) as conn:
        _seed_account(conn, "summit_chk")
        _seed_apy(conn, "summit_chk", 4.00, "2026-02-01")
        _seed_apy(conn, "summit_chk", 4.25, "2026-03-01")
        _seed_apy(conn, "summit_chk", 4.25, "2026-04-01")
        conn.commit()
        changes = detect_apy_changes(conn)
    assert len(changes) == 1
    assert changes[0]["old_rate"] == 4.00
    assert changes[0]["new_rate"] == 4.25


# ── Producer integration: dedup_key suppresses re-fires ──────────────────────


def test_producer_dedup_blocks_double_fire(db):
    """Re-running detect→record on the same data must not duplicate the row."""
    with get_db(db) as conn:
        _seed_account(conn, "summit_chk")
        _seed_apy(conn, "summit_chk", 4.00, "2026-04-01")
        _seed_apy(conn, "summit_chk", 4.50, "2026-04-15")
        conn.commit()

        # First "refresh" — records the change
        with patch("backend.events.broadcast_event"):
            for change in detect_apy_changes(conn):
                record_notification(
                    conn,
                    type="apy_rate_change",
                    severity=change["severity"],
                    title="ignored",
                    dedup_key=(
                        f"apy_change:{change['account_id']}"
                        f":{change['new_rate']:.4f}:{change['as_of']}"
                    ),
                )
            conn.commit()

        # Second "refresh" — same underlying data, dedup must block
        with patch("backend.events.broadcast_event"):
            for change in detect_apy_changes(conn):
                record_notification(
                    conn,
                    type="apy_rate_change",
                    severity=change["severity"],
                    title="ignored",
                    dedup_key=(
                        f"apy_change:{change['account_id']}"
                        f":{change['new_rate']:.4f}:{change['as_of']}"
                    ),
                )
            conn.commit()

        rows = list_notifications(conn)

    apy_rows = [r for r in rows if r["type"] == "apy_rate_change"]
    assert len(apy_rows) == 1
