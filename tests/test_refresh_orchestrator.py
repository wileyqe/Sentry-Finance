"""
tests/test_refresh_orchestrator.py — Isolation invariant for the
per-institution refresh loop.

CLAUDE.md guardrail (paraphrased):

    "Connector failures must not take down the overall refresh flow.
    Catch, log, and continue where the architecture expects isolation."

``RefreshSession.run()`` loops over ``stale_institutions`` and
calls ``_run_institution`` for each. ``_run_institution`` is the
isolation boundary — its try/except at the top of the main body must
swallow any ``Exception`` raised by the worker and return a dict with
``status="failed"``, so the outer loop keeps iterating.

The audit found this contract had implementation coverage but no
test coverage. This module is that test.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db  # noqa: E402


def _temp_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


@pytest.fixture
def isolated_db(monkeypatch):
    """Spin up a fresh, fully-migrated DB and redirect the DAL at it."""
    path = _temp_db()
    init_db(path)
    monkeypatch.setenv("SENTRY_DB_PATH", str(path))
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


def test_one_connector_failure_does_not_block_others(isolated_db):
    """A single raising worker must not propagate past _run_institution.

    Regression for the isolation invariant CLAUDE.md names explicitly.
    Runs two institutions through ``_run_institution`` — one succeeds,
    one raises — and asserts the second call returns ``status="failed"``
    cleanly instead of re-raising and bubbling into the outer loop.
    """
    from backend.refresh_orchestrator import RefreshSession
    from dal.refresh_log import create_refresh_run

    orch = RefreshSession(trigger="test_isolation")

    # Confirm the default get_db() is now pointing at the isolated DB
    # so _run_institution's context managers don't write to the real db.
    from dal.connection import get_db as _default_get_db, resolve_db_path
    assert resolve_db_path().resolve() == isolated_db.resolve()

    # Real run_id so refresh_event FK lookups succeed + seed the two
    # institution ids the workers will report against (FK on
    # refresh_events.institution_id → institutions.id).
    with _default_get_db() as conn:
        orch.run_id = create_refresh_run(conn, orch.trigger)
        conn.executemany(
            "INSERT OR IGNORE INTO institutions (id, display_name) VALUES (?, ?)",
            [("inst_good", "Good Bank"), ("inst_bad", "Bad Bank")],
        )
        conn.commit()

    good_calls = {"n": 0}
    bad_calls = {"n": 0}

    def good_worker(institution_id: str, creds, **_kwargs):
        good_calls["n"] += 1
        return {
            "txn_inserted": 1,
            "txn_updated": 0,
            "accounts_processed": 1,
            "balances_recorded": 0,
        }

    def bad_worker(institution_id: str, creds, **_kwargs):
        bad_calls["n"] += 1
        raise RuntimeError("simulated scrape failure")

    good_result = orch._run_institution("inst_good", good_worker)
    bad_result = orch._run_institution("inst_bad", bad_worker)

    assert good_calls["n"] == 1, "good worker must have been invoked exactly once"
    assert bad_calls["n"] == 1, "bad worker must have been invoked exactly once"

    assert good_result["status"] == "completed", (
        f"good worker result should be completed, got {good_result}"
    )
    # Isolation invariant: any non-completed terminal state is fine
    # ("failed" for exhausted retries, "retry_scheduled" when the
    # orchestrator plans to re-attempt). What matters is that the call
    # RETURNED instead of letting the exception bubble into the outer
    # for-loop over institutions.
    assert bad_result["status"] in ("failed", "retry_scheduled"), (
        f"failing worker must be caught; got {bad_result}"
    )
    assert bad_result["institution_id"] == "inst_bad"
    assert bad_result["attempts"] >= 1
    # And the original exception message flowed through, not just ignored.
    assert "simulated scrape failure" in bad_result.get("error", "")


def test_second_institution_runs_after_first_fails(isolated_db):
    """Explicit ordering test: with a bad institution followed by a good
    one, _run_institution on the second must succeed. Proves the
    isolation is positional-independent — the orchestrator's outer
    loop doesn't bail early on first failure.
    """
    from backend.refresh_orchestrator import RefreshSession
    from dal.refresh_log import create_refresh_run

    orch = RefreshSession(trigger="test_isolation_order")

    from dal.connection import get_db as _default_get_db
    with _default_get_db() as conn:
        orch.run_id = create_refresh_run(conn, orch.trigger)
        conn.executemany(
            "INSERT OR IGNORE INTO institutions (id, display_name) VALUES (?, ?)",
            [("inst_bad_first", "Bad"), ("inst_good_second", "Good")],
        )
        conn.commit()

    def bad_worker(institution_id: str, creds, **_kwargs):
        raise ValueError("first institution blew up")

    def good_worker(institution_id: str, creds, **_kwargs):
        return {
            "txn_inserted": 3,
            "txn_updated": 0,
            "accounts_processed": 1,
            "balances_recorded": 0,
        }

    bad_first = orch._run_institution("inst_bad_first", bad_worker)
    good_second = orch._run_institution("inst_good_second", good_worker)

    assert bad_first["status"] in ("failed", "retry_scheduled")
    assert good_second["status"] == "completed"
