"""
backend/refresh_orchestrator.py — Refresh session coordination.

Responsibilities:
  - Evaluate which institutions are stale
  - Manage the refresh state machine lifecycle
  - Coordinate credential retrieval and worker execution
  - Handle retry logic and backoff scheduling
  - Emit events for the API/UI layer
  - Recover from orphaned runs on startup
"""

import functools
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.state_machine import (
    RefreshState,
    InstitutionState,
    ErrorClass,
    CancellationToken,
    CancelledError,
    InstitutionTracker,
    classify_error,
    validate_transition,
)
from backend.ipc import request_credentials, clear_credentials
from backend import sse_topics
from dal.database import get_db, init_db, seed_institutions
from dal.refresh_log import (
    create_refresh_run,
    update_run_state,
    create_refresh_event,
    update_refresh_event,
    update_institution_status,
    get_institution_status,
    get_institution_statuses,
)
from dal.derived import recompute_for_institution

log = logging.getLogger("sentry.backend.orchestrator")

BASE_DIR = Path(__file__).resolve().parent.parent
POLICY_FILE = BASE_DIR / "config" / "refresh_policy.yaml"


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime:
    """Parse an ISO timestamp, normalising naive values to UTC.

    Handles both aware (``+00:00``) and naive (no tz) strings that
    are assumed to be UTC.
    """
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Policy Loading ───────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _load_policies() -> dict:
    """Load refresh policies from config/refresh_policy.yaml.

    Cached at module level — the file doesn't change between app
    restarts. Tests that mutate the YAML should call
    :func:`reload_policies` to invalidate the cache.
    """
    import yaml
    if not POLICY_FILE.exists():
        log.warning("refresh_policy.yaml not found, using defaults")
        return {}
    with open(POLICY_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def reload_policies() -> None:
    """Drop the cached refresh-policy YAML so the next lookup re-reads it."""
    _load_policies.cache_clear()


_DEFAULT_INSTITUTION_TIMEOUT = 10 * 60  # 10 minutes per institution


def get_policy(institution_id: str) -> dict:
    """Get refresh policy for a specific institution."""
    policies = _load_policies()
    defaults = {
        "refresh_interval_hours": 4,
        "max_retries": 3,
        "backoff_schedule": [60, 300, 900],
        "institution_timeout_seconds": _DEFAULT_INSTITUTION_TIMEOUT,
        "mfa_expected": "none",
        "extraction_method": "scrape",
        "retryable_errors": ["timeout", "network", "session_expired"],
        "fatal_errors": ["credential_invalid", "account_locked"],
    }
    policy = policies.get(institution_id, {})
    merged = {**defaults, **policy}
    # Guard: backoff_schedule must be non-empty
    if not merged.get("backoff_schedule"):
        merged["backoff_schedule"] = [60]
    return merged


# ── Staleness Evaluation ─────────────────────────────────────────────────────


def evaluate_staleness() -> list[str]:
    """Determine which institutions need a refresh.

    Returns list of institution_ids that are stale based on their
    refresh interval and last success time.
    """
    stale = []
    now = _utcnow()

    with get_db() as conn:
        statuses = get_institution_statuses(conn)

    for status in statuses:
        inst_id = status["institution_id"]
        policy = get_policy(inst_id)
        interval_hours = policy["refresh_interval_hours"]

        # Check cooldown (from previous failure backoff)
        if status.get("next_eligible"):
            try:
                eligible = _parse_iso(status["next_eligible"])
                if now < eligible:
                    log.debug(
                        "%s: still in cooldown until %s",
                        inst_id,
                        status["next_eligible"],
                    )
                    continue
            except (ValueError, TypeError):
                pass

        # Check staleness
        last_success = status.get("last_success")
        if not last_success:
            log.info("%s: never refreshed, marking stale", inst_id)
            stale.append(inst_id)
            continue

        try:
            last_dt = _parse_iso(last_success)
            age_hours = (now - last_dt).total_seconds() / 3600
            if age_hours < 0:
                # Clock skew: last_success is in the future — treat as stale
                log.warning(
                    "%s: last_success (%s) is in the future — clock skew? "
                    "Marking stale.",
                    inst_id,
                    last_success,
                )
                stale.append(inst_id)
            elif age_hours >= interval_hours:
                log.info(
                    "%s: stale (%.1fh since last refresh, threshold: %dh)",
                    inst_id,
                    age_hours,
                    interval_hours,
                )
                stale.append(inst_id)
            else:
                log.debug("%s: fresh (%.1fh since last refresh)", inst_id, age_hours)
        except (ValueError, TypeError):
            stale.append(inst_id)

    return stale


# ── Orphaned Run Recovery ────────────────────────────────────────────────────


def recover_orphaned_runs(db_path=None) -> int:
    """Mark any RUNNING refresh runs as FAILED on startup.

    If the process was killed mid-session the DB will have a run stuck
    in RUNNING (or EVALUATING_STALENESS, AUTH_REQUIRED, etc.).  This
    function cleans those up so they don't confuse the UI or block
    future sessions.

    Returns the number of runs recovered.
    """
    non_terminal = [
        RefreshState.EVALUATING_STALENESS.value,
        RefreshState.AUTH_REQUIRED.value,
        RefreshState.FETCHING_CREDENTIALS.value,
        RefreshState.RUNNING.value,
        RefreshState.WAITING_FOR_USER.value,
        RefreshState.RETRY_BACKOFF.value,
    ]
    placeholders = ",".join("?" for _ in non_terminal)

    with get_db(db_path) as conn:
        rows = conn.execute(
            f"SELECT id, state FROM refresh_runs WHERE state IN ({placeholders})",
            non_terminal,
        ).fetchall()

        if not rows:
            return 0

        now = _utcnow().isoformat()
        for row in rows:
            log.warning(
                "Recovering orphaned run %s (was %s → FAILED)",
                row["id"],
                row["state"],
            )
            conn.execute(
                """
                UPDATE refresh_runs
                SET state = 'FAILED',
                    error = 'Recovered: process exited while run was active',
                    completed_at = COALESCE(completed_at, ?)
                WHERE id = ?
                """,
                (now, row["id"]),
            )
        conn.commit()

    return len(rows)


# ── Refresh Session ──────────────────────────────────────────────────────────


# Maximum wall-clock time for an entire refresh session (seconds).
# Prevents the session from blocking indefinitely if Chrome hangs
# or a connector never returns.
SESSION_TIMEOUT_SECONDS = 30 * 60  # 30 minutes


class RefreshSession:
    """Manages a single refresh session lifecycle.

    Coordinates the state machine, credential retrieval, worker
    execution, and result persistence.
    """

    def __init__(self, trigger: str = "manual_sync"):
        self.trigger = trigger
        self.run_id: str | None = None
        self.state = RefreshState.IDLE
        self.stale_institutions: list[str] = []
        self.credentials: dict | None = None
        self._callbacks: list = []
        self._cancel = CancellationToken()

    def on_event(self, callback):
        """Register a callback for state change events.

        Callback receives (event_type, data_dict).
        """
        self._callbacks.append(callback)

    def _emit(self, event_type: str, **data):
        """Emit an event to all registered callbacks."""
        for cb in self._callbacks:
            try:
                cb(event_type, data)
            except Exception as e:
                log.debug("Event callback error: %s", e)

    def _transition(self, new_state: RefreshState, error: str | None = None):
        """Transition to a new state with validation and persistence."""
        if not validate_transition(self.state, new_state):
            raise ValueError(f"Invalid transition: {self.state} → {new_state}")

        old_state = self.state
        self.state = new_state

        with get_db() as conn:
            if self.run_id:
                update_run_state(conn, self.run_id, new_state.value, error)
                conn.commit()

        log.info("Refresh state: %s → %s", old_state, new_state)
        self._emit(sse_topics.STATE_CHANGE, state=new_state.value, previous=old_state.value)

    def _force_fail(self, error: str):
        """Force the session into FAILED → IDLE from any active state.

        Used after a session timeout or unrecoverable crash where the
        normal transition path is unavailable.
        """
        log.warning("Force-failing session from %s: %s", self.state, error)

        # Persist directly — skip validate_transition since we may be
        # in a state that doesn't have FAILED as a valid target.
        with get_db() as conn:
            if self.run_id:
                now = _utcnow().isoformat()
                conn.execute(
                    """
                    UPDATE refresh_runs
                    SET state = 'FAILED', error = ?,
                        completed_at = COALESCE(completed_at, ?)
                    WHERE id = ?
                    """,
                    (error, now, self.run_id),
                )
                conn.commit()

        self.state = RefreshState.FAILED
        self._emit(sse_topics.STATE_CHANGE, state="FAILED", previous="RUNNING")

        # Now legally transition FAILED → IDLE
        self._transition(RefreshState.IDLE)

    def run(self, worker_fn=None, timeout: int = SESSION_TIMEOUT_SECONDS) -> dict:
        """Execute a full refresh session.

        Args:
            worker_fn: Callable(institution_id, credentials)
                       that performs the actual automation.
                       Returns dict with results or raises on failure.
            timeout: Maximum wall-clock seconds for the entire session.
                     Defaults to SESSION_TIMEOUT_SECONDS (30 min).

        Returns:
            Summary dict with status, institutions refreshed, etc.
        """
        summary = {
            "status": "failed",
            "trigger": self.trigger,
            "institutions": {},
            "started_at": _utcnow().isoformat(),
        }

        # Run in a child thread so we can enforce a hard wall-clock timeout.
        result_box: list[dict] = []
        error_box: list[Exception] = []

        def _target():
            try:
                result_box.append(self._run_inner(worker_fn, summary))
            except CancelledError:
                error_box.append(CancelledError("Session cancelled by timeout"))
            except Exception as e:
                error_box.append(e)

        worker_thread = threading.Thread(target=_target, daemon=True)
        worker_thread.start()
        worker_thread.join(timeout=timeout)

        if worker_thread.is_alive():
            log.error(
                "Refresh session exceeded %ds wall-clock timeout — aborting",
                timeout,
            )
            # Signal the worker thread to stop cooperatively
            self._cancel.cancel()

            summary["status"] = "timeout"
            summary["error"] = (
                f"Session exceeded {timeout}s wall-clock limit. "
                "Chrome or a connector may be hung."
            )
            self._emit(sse_topics.SESSION_TIMEOUT, timeout=timeout)

            # Try to kill Chrome so the hung connector doesn't linger
            try:
                from extractors.chrome_cdp import close_chrome
                close_chrome()
            except Exception:
                pass

            # Force state machine to FAILED → IDLE so the DB isn't stuck
            self._force_fail(summary["error"])

            # Wait briefly for cooperative shutdown before clearing creds
            worker_thread.join(timeout=5)
        elif error_box:
            log.error("Refresh session failed: %s", error_box[0])
            summary["error"] = str(error_box[0])
        elif result_box:
            summary = result_box[0]

        # Clean up credentials only after worker has stopped (or timed out)
        if self.credentials:
            clear_credentials(self.credentials)
            self.credentials = None

        summary["completed_at"] = _utcnow().isoformat()
        return summary

    def _run_inner(self, worker_fn, summary: dict) -> dict:
        """Inner refresh loop with state machine management."""

        # ── Step 1: Evaluate staleness ─────────────────────────
        with get_db() as conn:
            self.run_id = create_refresh_run(conn, self.trigger)
            conn.commit()

        self._transition(RefreshState.EVALUATING_STALENESS)

        self.stale_institutions = evaluate_staleness()
        if not self.stale_institutions:
            log.info("Nothing to refresh — all institutions fresh")
            self._transition(RefreshState.IDLE)
            summary["status"] = "nothing_stale"
            return summary

        log.info("Stale institutions: %s", self.stale_institutions)
        self._emit(sse_topics.STALENESS_EVALUATED, stale=self.stale_institutions)

        # ── Step 2: Get credentials ────────────────────────────
        self._transition(RefreshState.AUTH_REQUIRED)
        self._emit(sse_topics.AUTH_REQUIRED, institutions=self.stale_institutions)

        self._cancel.raise_if_cancelled()

        self._transition(RefreshState.FETCHING_CREDENTIALS)

        self.credentials = request_credentials(self.stale_institutions)

        if not self.credentials:
            log.warning("No credentials received — proceeding with manual fallback")
            self.credentials = {}

        # ── Step 3: Run each institution sequentially ──────────
        self._transition(RefreshState.RUNNING)

        successes = 0
        failures = 0

        for inst_id in self.stale_institutions:
            self._cancel.raise_if_cancelled()

            inst_result = self._run_institution(inst_id, worker_fn)
            summary["institutions"][inst_id] = inst_result

            if inst_result.get("status") == "completed":
                successes += 1
            else:
                failures += 1

        # ── Step 3.5: Close Chrome automation window ───────────
        try:
            from extractors.chrome_cdp import close_chrome

            close_chrome()
        except Exception as e:
            log.debug("Chrome cleanup: %s", e)

        # ── Step 4: Determine final state ──────────────────────
        if failures == 0:
            self._transition(RefreshState.SUCCESS)
            summary["status"] = "success"
        elif successes > 0:
            self._transition(RefreshState.PARTIAL_SUCCESS)
            summary["status"] = "partial_success"
        else:
            self._transition(RefreshState.FAILED)
            summary["status"] = "failed"

        # Return to idle
        if self.state != RefreshState.IDLE:
            self._transition(RefreshState.IDLE)

        return summary

    def _run_institution(self, institution_id: str, worker_fn=None) -> dict:
        """Run refresh for a single institution with state tracking.

        Performs one attempt with a per-institution timeout. If a retry
        is needed, sets next_eligible backoff and returns, allowing the
        scheduler to pick it up later without blocking the thread.
        """
        policy = get_policy(institution_id)
        max_retries = policy["max_retries"]
        backoff = policy["backoff_schedule"]  # guaranteed non-empty by get_policy
        inst_timeout = policy["institution_timeout_seconds"]
        inst_creds = (self.credentials or {}).get(institution_id)

        tracker = InstitutionTracker(institution_id)

        # Get current failures to determine attempt number
        with get_db() as conn:
            status = get_institution_status(conn, institution_id)
            consecutive_failures = status.get("consecutive_failures", 0)

        attempt = consecutive_failures + 1

        result = {
            "institution_id": institution_id,
            "status": "failed",
            "attempts": attempt,
        }

        with get_db() as conn:
            event_id = create_refresh_event(conn, self.run_id, institution_id)
            conn.commit()

        start_time = time.time()

        log.info("%s: attempt %d/%d", institution_id, attempt, max_retries + 1)

        tracker.transition(InstitutionState.STARTED)
        self._emit(sse_topics.INSTITUTION_STARTED, institution=institution_id, attempt=attempt)

        try:
            if worker_fn is None:
                log.warning("%s: no worker function provided, skipping", institution_id)
                tracker.transition(InstitutionState.SKIPPED)
                result["status"] = "skipped"
                return result

            self._cancel.raise_if_cancelled()

            # Run with per-institution timeout
            tracker.transition(InstitutionState.LOGGING_IN)
            worker_result = self._run_with_timeout(
                worker_fn, institution_id, inst_creds, inst_timeout
            )

            # Success
            tracker.transition(InstitutionState.EXTRACTING)
            tracker.transition(InstitutionState.COMPLETED)

            duration = time.time() - start_time
            result["status"] = "completed"
            result["duration"] = duration
            result["data"] = worker_result

            with get_db() as conn:
                update_refresh_event(
                    conn,
                    event_id,
                    state=InstitutionState.COMPLETED.value,
                    txn_inserted=worker_result.get("txn_inserted", 0),
                    txn_updated=worker_result.get("txn_updated", 0),
                    mfa_prompted=bool(worker_result.get("mfa_prompted", False)),
                    duration_seconds=duration,
                )
                update_institution_status(conn, institution_id, success=True)
                recompute_for_institution(conn, institution_id)
                conn.commit()

            self._emit(
                sse_topics.INSTITUTION_COMPLETE, institution=institution_id, **worker_result
            )

            log.info("%s: completed in %.1fs", institution_id, duration)
            return result

        except CancelledError:
            raise  # propagate session cancellation upward

        except Exception as e:
            err_str = str(e)
            err_class = classify_error(
                err_str,
                policy.get("retryable_errors"),
                policy.get("fatal_errors"),
            )

            # Transition institution to FAILED
            if not tracker.is_terminal:
                tracker.transition(InstitutionState.FAILED)

            log.warning(
                "%s: attempt %d failed (%s): %s",
                institution_id,
                attempt,
                err_class.value,
                err_str,
            )

            duration = time.time() - start_time

            # Fatal or max retries exceeded
            if err_class == ErrorClass.FATAL or attempt > max_retries:
                cooldown_sec = backoff[-1] * 2 if backoff else 1800
                cooldown = _utcnow() + timedelta(seconds=cooldown_sec)
                final_state = InstitutionState.FAILED.value
                result["status"] = "failed"
            else:
                # Retryable
                delay = (
                    backoff[attempt - 1] if attempt - 1 < len(backoff) else backoff[-1]
                )
                cooldown = _utcnow() + timedelta(seconds=delay)
                final_state = "RETRY_BACKOFF"
                result["status"] = "retry_scheduled"
                log.info(
                    "%s: scheduling retry for %s", institution_id, cooldown.isoformat()
                )
                self._emit(
                    sse_topics.INSTITUTION_RETRY,
                    institution=institution_id,
                    delay=delay,
                    attempt=attempt + 1,
                )

            result["error"] = err_str
            result["error_class"] = err_class.value

            with get_db() as conn:
                update_refresh_event(
                    conn,
                    event_id,
                    state=final_state,
                    error=err_str,
                    error_class=err_class.value,
                    retry_count=attempt,
                    duration_seconds=duration,
                )
                update_institution_status(
                    conn,
                    institution_id,
                    success=False,
                    error=err_str,
                    cooldown_until=cooldown.isoformat(),
                )
                if final_state == InstitutionState.FAILED.value:
                    try:
                        from dal.notifications import record_notification
                        short_err = err_str[:120] if err_str else "Unknown error"
                        record_notification(
                            conn,
                            type="refresh_failure",
                            severity="critical",
                            title=f"{institution_id.upper()} refresh failed",
                            body=f"{err_class.value}: {short_err}",
                            payload={
                                "institution": institution_id,
                                "error_class": err_class.value,
                                "event_id": event_id,
                            },
                            dedup_key=f"refresh_failure:{institution_id}:{event_id}",
                            link="/settings",
                        )
                    except Exception as _notif_exc:
                        log.debug("Notification emit failed (non-fatal): %s", _notif_exc)
                conn.commit()

            if final_state == InstitutionState.FAILED.value:
                self._emit(
                    sse_topics.INSTITUTION_FAILED, institution=institution_id, error=err_str
                )

            return result

    def _run_with_timeout(
        self, worker_fn, institution_id: str, creds, timeout: int
    ) -> dict:
        """Run a worker function with a per-institution timeout.

        Raises TimeoutError if the worker exceeds the allowed time.

        ``refresh_run_id=self.run_id`` is passed as a keyword argument so
        the live worker (``backend.automation_worker.run_institution``)
        can thread it down to ``persist_connector_result`` and the
        ``balance_snapshots`` / ``loan_details`` writers (AI-034). Test
        workers that only accept ``(institution_id, creds)`` should
        absorb the kwarg via ``**_kwargs``.
        """
        result_box: list = []
        error_box: list = []

        def _target():
            try:
                result_box.append(
                    worker_fn(
                        institution_id,
                        creds,
                        refresh_run_id=self.run_id,
                    )
                )
            except Exception as e:
                error_box.append(e)

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            log.error(
                "%s: institution timeout (%ds) exceeded", institution_id, timeout
            )
            raise TimeoutError(
                f"{institution_id}: worker exceeded {timeout}s institution timeout"
            )

        if error_box:
            raise error_box[0]

        return result_box[0] if result_box else {}


# ── Convenience Entry Points ─────────────────────────────────────────────────


def run_refresh(trigger: str = "manual_sync", worker_fn=None) -> dict:
    """Run a complete refresh session.

    This is the main entry point called by the API server
    or manual scripts.

    Args:
        trigger: What initiated this refresh
        worker_fn: The automation function to call per institution

    Returns:
        Summary dict
    """
    # Ensure DB is ready
    init_db()
    seed_institutions()

    # Recover any orphaned runs from prior crashes
    recovered = recover_orphaned_runs()
    if recovered:
        log.info("Recovered %d orphaned refresh run(s)", recovered)

    session = RefreshSession(trigger=trigger)
    return session.run(worker_fn=worker_fn)


def check_staleness() -> list[dict]:
    """Check which institutions are stale without triggering refresh.

    Returns list of dicts with institution info and staleness status.
    """
    init_db()
    seed_institutions()

    stale_ids = set(evaluate_staleness())

    with get_db() as conn:
        statuses = get_institution_statuses(conn)

    result = []
    for s in statuses:
        result.append(
            {
                "institution_id": s["institution_id"],
                "display_name": s.get("display_name", s["institution_id"]),
                "is_stale": s["institution_id"] in stale_ids,
                "last_success": s.get("last_success"),
                "last_failure": s.get("last_failure"),
                "consecutive_failures": s.get("consecutive_failures", 0),
            }
        )
    return result
