"""
backend/refresh_orchestrator.py — Refresh session coordination.

Responsibilities:
  - Evaluate which institutions are stale
  - Manage the refresh state machine lifecycle
  - Coordinate credential retrieval and worker execution
  - Handle retry logic and backoff scheduling
  - Emit events for the API/UI layer
"""
import logging
import time
import yaml
from datetime import datetime, timedelta
from pathlib import Path

from backend.state_machine import (
    RefreshState, InstitutionState, ErrorClass,
    classify_error, validate_transition,
)
from backend.ipc import request_credentials, clear_credentials
from dal.database import get_db, DB_PATH, init_db, seed_institutions
from dal.refresh_log import (
    create_refresh_run, update_run_state,
    create_refresh_event, update_refresh_event,
    update_institution_status, get_institution_statuses,
)
from dal.derived import recompute_for_institution

log = logging.getLogger("sentry")

BASE_DIR = Path(__file__).resolve().parent.parent
POLICY_FILE = BASE_DIR / "config" / "refresh_policy.yaml"


# ── Policy Loading ───────────────────────────────────────────────────────────

def _load_policies() -> dict:
    """Load refresh policies from config/refresh_policy.yaml."""
    if not POLICY_FILE.exists():
        log.warning("refresh_policy.yaml not found, using defaults")
        return {}
    with open(POLICY_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_policy(institution_id: str) -> dict:
    """Get refresh policy for a specific institution."""
    policies = _load_policies()
    defaults = {
        "refresh_interval_hours": 4,
        "max_retries": 3,
        "backoff_schedule": [60, 300, 900],
        "mfa_expected": "none",
        "extraction_method": "scrape",
        "retryable_errors": ["timeout", "network", "session_expired"],
        "fatal_errors": ["credential_invalid", "account_locked"],
    }
    policy = policies.get(institution_id, {})
    return {**defaults, **policy}


# ── Staleness Evaluation ─────────────────────────────────────────────────────

def evaluate_staleness() -> list[str]:
    """Determine which institutions need a refresh.

    Returns list of institution_ids that are stale based on their
    refresh interval and last success time.
    """
    stale = []
    now = datetime.utcnow()

    with get_db() as conn:
        statuses = get_institution_statuses(conn)

    for status in statuses:
        inst_id = status["institution_id"]
        policy = get_policy(inst_id)
        interval_hours = policy["refresh_interval_hours"]

        # Check cooldown (from previous failure backoff)
        if status.get("next_eligible"):
            try:
                eligible = datetime.fromisoformat(
                    status["next_eligible"])
                if now < eligible:
                    log.debug("%s: still in cooldown until %s",
                              inst_id, status["next_eligible"])
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
            last_dt = datetime.fromisoformat(last_success)
            age_hours = (now - last_dt).total_seconds() / 3600
            if age_hours >= interval_hours:
                log.info("%s: stale (%.1fh since last refresh, "
                         "threshold: %dh)",
                         inst_id, age_hours, interval_hours)
                stale.append(inst_id)
            else:
                log.debug("%s: fresh (%.1fh since last refresh)",
                          inst_id, age_hours)
        except (ValueError, TypeError):
            stale.append(inst_id)

    return stale


# ── Refresh Session ──────────────────────────────────────────────────────────

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

    def _transition(self, new_state: RefreshState,
                    error: str | None = None):
        """Transition to a new state with validation and persistence."""
        if not validate_transition(self.state, new_state):
            raise ValueError(
                f"Invalid transition: {self.state} → {new_state}"
            )

        old_state = self.state
        self.state = new_state

        with get_db() as conn:
            if self.run_id:
                update_run_state(conn, self.run_id, new_state.value,
                                 error)
                conn.commit()

        log.info("Refresh state: %s → %s", old_state, new_state)
        self._emit("state_change", state=new_state.value,
                   previous=old_state.value)

    def run(self, worker_fn=None) -> dict:
        """Execute a full refresh session.

        Args:
            worker_fn: Callable(institution_id, credentials, conn)
                       that performs the actual automation.
                       Returns dict with results or raises on failure.

        Returns:
            Summary dict with status, institutions refreshed, etc.
        """
        summary = {
            "status": "failed",
            "trigger": self.trigger,
            "institutions": {},
            "started_at": datetime.utcnow().isoformat(),
        }

        try:
            return self._run_inner(worker_fn, summary)
        except Exception as e:
            log.error("Refresh session failed: %s", e)
            summary["error"] = str(e)
            return summary
        finally:
            # Always clean up credentials
            if self.credentials:
                clear_credentials(self.credentials)
                self.credentials = None

            summary["completed_at"] = datetime.utcnow().isoformat()

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
        self._emit("staleness_evaluated",
                   stale=self.stale_institutions)

        # ── Step 2: Get credentials ────────────────────────────
        self._transition(RefreshState.AUTH_REQUIRED)
        self._emit("auth_required",
                   institutions=self.stale_institutions)

        self._transition(RefreshState.FETCHING_CREDENTIALS)

        self.credentials = request_credentials(
            self.stale_institutions
        )

        if not self.credentials:
            log.warning("No credentials received — proceeding "
                        "with manual fallback")
            self.credentials = {}

        # ── Step 3: Run each institution sequentially ──────────
        self._transition(RefreshState.RUNNING)

        successes = 0
        failures = 0

        for inst_id in self.stale_institutions:
            inst_result = self._run_institution(
                inst_id, worker_fn
            )
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

    def _run_institution(self, institution_id: str,
                         worker_fn=None) -> dict:
        """Run refresh for a single institution with retries."""
        policy = get_policy(institution_id)
        max_retries = policy["max_retries"]
        backoff = policy["backoff_schedule"]
        inst_creds = (self.credentials or {}).get(institution_id)

        result = {
            "institution_id": institution_id,
            "status": "failed",
            "attempts": 0,
        }

        with get_db() as conn:
            event_id = create_refresh_event(
                conn, self.run_id, institution_id
            )
            conn.commit()

        start_time = time.time()

        for attempt in range(max_retries + 1):
            result["attempts"] = attempt + 1
            log.info("%s: attempt %d/%d",
                     institution_id, attempt + 1, max_retries + 1)

            self._emit("institution_started",
                       institution=institution_id,
                       attempt=attempt + 1)

            try:
                if worker_fn is None:
                    log.warning("%s: no worker function provided, "
                                "skipping", institution_id)
                    result["status"] = "skipped"
                    break

                worker_result = worker_fn(
                    institution_id, inst_creds
                )

                # Success
                duration = time.time() - start_time
                result["status"] = "completed"
                result["duration"] = duration
                result["data"] = worker_result

                with get_db() as conn:
                    update_refresh_event(
                        conn, event_id,
                        state="COMPLETED",
                        txn_inserted=worker_result.get(
                            "txn_inserted", 0),
                        txn_updated=worker_result.get(
                            "txn_updated", 0),
                        duration_seconds=duration,
                    )
                    update_institution_status(
                        conn, institution_id, success=True
                    )
                    # Recompute derived metrics
                    recompute_for_institution(conn, institution_id)
                    conn.commit()

                self._emit("institution_complete",
                           institution=institution_id,
                           **worker_result)

                log.info("%s: completed in %.1fs",
                         institution_id, duration)
                return result

            except Exception as e:
                err_str = str(e)
                err_class = classify_error(
                    err_str,
                    policy.get("retryable_errors"),
                    policy.get("fatal_errors"),
                )

                log.warning("%s: attempt %d failed (%s): %s",
                            institution_id, attempt + 1,
                            err_class.value, err_str)

                # Fatal — don't retry
                if err_class == ErrorClass.FATAL:
                    result["error"] = err_str
                    result["error_class"] = err_class.value
                    break

                # Retryable — backoff and try again
                if attempt < max_retries:
                    delay = (backoff[attempt]
                             if attempt < len(backoff)
                             else backoff[-1])
                    log.info("%s: retrying in %ds...",
                             institution_id, delay)
                    self._emit("institution_retry",
                               institution=institution_id,
                               delay=delay,
                               attempt=attempt + 1)
                    time.sleep(delay)
                else:
                    result["error"] = err_str
                    result["error_class"] = err_class.value

        # Failed after all retries
        duration = time.time() - start_time
        cooldown = datetime.utcnow() + timedelta(
            seconds=backoff[-1] * 2 if backoff else 1800
        )

        with get_db() as conn:
            update_refresh_event(
                conn, event_id,
                state="FAILED",
                error=result.get("error"),
                error_class=result.get("error_class"),
                retry_count=result["attempts"],
                duration_seconds=duration,
            )
            update_institution_status(
                conn, institution_id, success=False,
                error=result.get("error"),
                cooldown_until=cooldown.isoformat(),
            )
            conn.commit()

        self._emit("institution_failed",
                   institution=institution_id,
                   error=result.get("error"))

        return result


# ── Convenience Entry Points ─────────────────────────────────────────────────

def run_refresh(trigger: str = "manual_sync",
                worker_fn=None) -> dict:
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
        result.append({
            "institution_id": s["institution_id"],
            "display_name": s.get("display_name", s["institution_id"]),
            "is_stale": s["institution_id"] in stale_ids,
            "last_success": s.get("last_success"),
            "last_failure": s.get("last_failure"),
            "consecutive_failures": s.get("consecutive_failures", 0),
        })
    return result

