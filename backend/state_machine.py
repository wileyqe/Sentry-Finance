"""
backend/state_machine.py — Refresh state definitions and transitions.

Defines the finite state machine that governs refresh sessions.
Every state transition is validated and durably persisted.
"""

import logging
from enum import Enum

log = logging.getLogger("sentry.backend.state_machine")


class RefreshState(str, Enum):
    """Top-level states for a refresh session."""

    IDLE = "IDLE"
    EVALUATING_STALENESS = "EVALUATING_STALENESS"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    FETCHING_CREDENTIALS = "FETCHING_CREDENTIALS"
    RUNNING = "RUNNING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    RETRY_BACKOFF = "RETRY_BACKOFF"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class InstitutionState(str, Enum):
    """Per-institution states within a refresh run."""

    QUEUED = "QUEUED"
    STARTED = "STARTED"
    LOGGING_IN = "LOGGING_IN"
    EXTRACTING = "EXTRACTING"
    WAITING_MFA = "WAITING_MFA"
    WAITING_MANUAL = "WAITING_MANUAL"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ErrorClass(str, Enum):
    """Classification of errors for retry decisions."""

    RETRYABLE = "retryable"
    FATAL = "fatal"
    TIMEOUT = "timeout"
    MFA_EXPIRED = "mfa_expired"
    NETWORK = "network"
    UNKNOWN = "unknown"


# ── Valid Transitions ────────────────────────────────────────────────────────

_VALID_TRANSITIONS: dict[RefreshState, set[RefreshState]] = {
    RefreshState.IDLE: {
        RefreshState.EVALUATING_STALENESS,
    },
    RefreshState.EVALUATING_STALENESS: {
        RefreshState.IDLE,  # nothing stale
        RefreshState.AUTH_REQUIRED,  # stale institutions found
    },
    RefreshState.AUTH_REQUIRED: {
        RefreshState.FETCHING_CREDENTIALS,  # user approved
        RefreshState.IDLE,  # user declined
    },
    RefreshState.FETCHING_CREDENTIALS: {
        RefreshState.RUNNING,  # credentials received
        RefreshState.FAILED,  # broker error
    },
    RefreshState.RUNNING: {
        RefreshState.WAITING_FOR_USER,  # MFA or manual click
        RefreshState.RETRY_BACKOFF,  # retryable error
        RefreshState.PARTIAL_SUCCESS,  # some institutions failed
        RefreshState.SUCCESS,  # all complete
        RefreshState.FAILED,  # fatal error
    },
    RefreshState.WAITING_FOR_USER: {
        RefreshState.RUNNING,  # user completed action
        RefreshState.FAILED,  # timeout waiting for user
    },
    RefreshState.RETRY_BACKOFF: {
        RefreshState.RUNNING,  # retry
        RefreshState.PARTIAL_SUCCESS,  # max retries exhausted
        RefreshState.FAILED,  # give up
    },
    RefreshState.PARTIAL_SUCCESS: {
        RefreshState.IDLE,
    },
    RefreshState.SUCCESS: {
        RefreshState.IDLE,
    },
    RefreshState.FAILED: {
        RefreshState.IDLE,
    },
}

_VALID_INST_TRANSITIONS: dict[InstitutionState, set[InstitutionState]] = {
    InstitutionState.QUEUED: {
        InstitutionState.STARTED,
        InstitutionState.SKIPPED,
    },
    InstitutionState.STARTED: {
        InstitutionState.LOGGING_IN,
        InstitutionState.FAILED,
    },
    InstitutionState.LOGGING_IN: {
        InstitutionState.EXTRACTING,
        InstitutionState.WAITING_MFA,
        InstitutionState.WAITING_MANUAL,
        InstitutionState.FAILED,
    },
    InstitutionState.EXTRACTING: {
        InstitutionState.COMPLETED,
        InstitutionState.FAILED,
    },
    InstitutionState.WAITING_MFA: {
        InstitutionState.LOGGING_IN,  # MFA completed, resume login
        InstitutionState.FAILED,  # timeout
    },
    InstitutionState.WAITING_MANUAL: {
        InstitutionState.LOGGING_IN,  # user filled creds
        InstitutionState.FAILED,  # timeout
    },
    InstitutionState.RETRYING: {
        InstitutionState.STARTED,
        InstitutionState.FAILED,
    },
    InstitutionState.COMPLETED: set(),
    InstitutionState.FAILED: {
        InstitutionState.RETRYING,  # retry decision
    },
    InstitutionState.SKIPPED: set(),
}


def validate_transition(current: RefreshState, target: RefreshState) -> bool:
    """Check if a state transition is valid."""
    valid = _VALID_TRANSITIONS.get(current, set())
    if target not in valid:
        log.error(
            "Invalid state transition: %s → %s (valid: %s)", current, target, valid
        )
        return False
    return True


def validate_inst_transition(
    current: InstitutionState, target: InstitutionState
) -> bool:
    """Check if an institution state transition is valid."""
    valid = _VALID_INST_TRANSITIONS.get(current, set())
    if target not in valid:
        log.error(
            "Invalid institution state transition: %s → %s (valid: %s)",
            current,
            target,
            valid,
        )
        return False
    return True


def classify_error(
    error_str: str,
    retryable_errors: list[str] | None = None,
    fatal_errors: list[str] | None = None,
) -> ErrorClass:
    """Classify an error string into an ErrorClass.

    Uses the institution's configured retryable/fatal error lists,
    with sensible defaults.
    """
    if not error_str:
        return ErrorClass.UNKNOWN

    err_lower = error_str.lower()

    # Check explicit fatal errors first
    defaults_fatal = ["credential_invalid", "account_locked", "institution_unavailable"]
    for pattern in fatal_errors or defaults_fatal:
        if pattern in err_lower:
            return ErrorClass.FATAL

    # Check timeout
    if "timeout" in err_lower or "timed out" in err_lower:
        return ErrorClass.TIMEOUT

    # Check network
    if any(x in err_lower for x in ["network", "connection", "dns", "refused"]):
        return ErrorClass.NETWORK

    # Check MFA
    if "mfa" in err_lower or "verification" in err_lower:
        return ErrorClass.MFA_EXPIRED

    # Check explicit retryable
    defaults_retry = ["session_expired", "element_not_found", "stale element"]
    for pattern in retryable_errors or defaults_retry:
        if pattern in err_lower:
            return ErrorClass.RETRYABLE

    return ErrorClass.UNKNOWN
