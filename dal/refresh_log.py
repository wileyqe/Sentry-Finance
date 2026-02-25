"""
dal/refresh_log.py — Refresh run and event persistence.

Provides durable state for the refresh state machine.
Every state transition is recorded for diagnostics and recovery.
"""
import logging
import sqlite3
import uuid
from datetime import datetime

log = logging.getLogger("sentry")


def create_refresh_run(conn: sqlite3.Connection,
                       trigger: str = "manual_sync") -> str:
    """Create a new refresh run and return its ID.

    Args:
        trigger: 'auto_stale', 'manual_sync', 'startup'

    Returns:
        UUID string for the new run.
    """
    run_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO refresh_runs (id, state, started_at, trigger,
                                  created_at)
        VALUES (?, 'EVALUATING_STALENESS', ?, ?, ?)
    """, (run_id, now, trigger, now))
    return run_id


def update_run_state(conn: sqlite3.Connection,
                     run_id: str,
                     state: str,
                     error: str | None = None) -> None:
    """Update the state of a refresh run."""
    now = datetime.utcnow().isoformat()
    completed = now if state in (
        "SUCCESS", "PARTIAL_SUCCESS", "FAILED"
    ) else None

    conn.execute("""
        UPDATE refresh_runs
        SET state = ?, error = ?,
            completed_at = COALESCE(?, completed_at)
        WHERE id = ?
    """, (state, error, completed, run_id))


def create_refresh_event(conn: sqlite3.Connection,
                         run_id: str,
                         institution_id: str,
                         state: str = "STARTED") -> int:
    """Create a refresh event for an institution within a run.

    Returns the event row ID.
    """
    now = datetime.utcnow().isoformat()
    cursor = conn.execute("""
        INSERT INTO refresh_events
            (run_id, institution_id, state, started_at, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (run_id, institution_id, state, now, now))
    return cursor.lastrowid


def update_refresh_event(conn: sqlite3.Connection,
                         event_id: int,
                         state: str,
                         txn_inserted: int = 0,
                         txn_updated: int = 0,
                         txn_deleted: int = 0,
                         balance_delta: float | None = None,
                         error: str | None = None,
                         error_class: str | None = None,
                         retry_count: int = 0,
                         mfa_prompted: bool = False,
                         duration_seconds: float | None = None
                         ) -> None:
    """Update a refresh event with results."""
    now = datetime.utcnow().isoformat()
    completed = now if state in (
        "COMPLETED", "FAILED", "SKIPPED"
    ) else None

    conn.execute("""
        UPDATE refresh_events
        SET state = ?, completed_at = COALESCE(?, completed_at),
            txn_inserted = ?, txn_updated = ?, txn_deleted = ?,
            balance_delta = ?, error = ?, error_class = ?,
            retry_count = ?, mfa_prompted = ?,
            duration_seconds = ?
        WHERE id = ?
    """, (
        state, completed,
        txn_inserted, txn_updated, txn_deleted,
        balance_delta, error, error_class,
        retry_count, int(mfa_prompted),
        duration_seconds,
        event_id,
    ))


def update_institution_status(conn: sqlite3.Connection,
                              institution_id: str,
                              success: bool,
                              error: str | None = None,
                              cooldown_until: str | None = None
                              ) -> None:
    """Update the institution refresh status after a refresh attempt."""
    now = datetime.utcnow().isoformat()

    if success:
        conn.execute("""
            UPDATE institution_refresh_status
            SET last_success = ?, consecutive_failures = 0,
                next_eligible = NULL, updated_at = ?
            WHERE institution_id = ?
        """, (now, now, institution_id))
    else:
        conn.execute("""
            UPDATE institution_refresh_status
            SET last_failure = ?, last_failure_reason = ?,
                consecutive_failures = consecutive_failures + 1,
                next_eligible = ?, updated_at = ?
            WHERE institution_id = ?
        """, (now, error, cooldown_until, now, institution_id))


def get_current_run(conn: sqlite3.Connection) -> dict | None:
    """Get the most recent non-idle refresh run."""
    row = conn.execute(
        "SELECT * FROM refresh_runs "
        "WHERE state != 'IDLE' "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def get_run_events(conn: sqlite3.Connection,
                   run_id: str) -> list[dict]:
    """Get all events for a given refresh run."""
    rows = conn.execute(
        "SELECT * FROM refresh_events "
        "WHERE run_id = ? ORDER BY created_at ASC",
        (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_refresh_history(conn: sqlite3.Connection,
                        limit: int = 20) -> list[dict]:
    """Get recent refresh runs with summary stats."""
    rows = conn.execute("""
        SELECT r.*,
            COUNT(e.id) as institution_count,
            SUM(e.txn_inserted) as total_inserted,
            SUM(e.txn_updated) as total_updated
        FROM refresh_runs r
        LEFT JOIN refresh_events e ON e.run_id = r.id
        GROUP BY r.id
        ORDER BY r.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_institution_statuses(conn: sqlite3.Connection) -> list[dict]:
    """Get refresh status for all institutions."""
    rows = conn.execute("""
        SELECT irs.*, i.display_name, i.refresh_interval_hours
        FROM institution_refresh_status irs
        JOIN institutions i ON i.id = irs.institution_id
        ORDER BY i.display_name
    """).fetchall()
    return [dict(r) for r in rows]

