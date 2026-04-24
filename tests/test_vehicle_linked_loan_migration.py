"""
tests/test_vehicle_linked_loan_migration.py — v35 smoke.

Verifies the new ``linked_loan_id`` column lands on ``vehicle_assets``
when the migration runner applies v35, and that re-running the runner
on an already-migrated DB is a no-op (idempotence via ``column_exists``).
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.connection import get_db as real_get_db  # noqa: E402
from dal.database import init_db  # noqa: E402
from dal.migrations import column_exists  # noqa: E402


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield Path(path)
    try:
        os.unlink(path)
    except OSError:
        pass


def test_v35_adds_linked_loan_id_column(db_path):
    init_db(db_path)
    with real_get_db(db_path) as conn:
        assert column_exists(conn, "vehicle_assets", "linked_loan_id")


def test_v35_is_idempotent_on_replay(db_path):
    # Apply full migrations once, then re-run — the column_exists guard
    # should short-circuit the ALTER so no duplicate-column error surfaces.
    init_db(db_path)
    init_db(db_path)

    with real_get_db(db_path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(vehicle_assets)")]
        assert cols.count("linked_loan_id") == 1
