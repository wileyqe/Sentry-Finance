"""
backend/mfa_bridge.py — Thread-safe MFA code exchange.

Used by connectors that require interactive MFA codes during automation.
Only one MFA session can be active at a time (serial connector execution).
"""

import threading
import logging

log = logging.getLogger("sentry.backend.mfa_bridge")

_pending_event: threading.Event = threading.Event()
_pending_code: str | None = None
_pending_institution: str | None = None
_bridge_lock = threading.Lock()


def wait_for_code(institution: str, timeout_seconds: int = 300) -> str | None:
    """Block until a code is submitted for this institution, or timeout.

    Called from the connector thread. Returns the code or None on timeout.
    """
    global _pending_institution, _pending_code
    with _bridge_lock:
        _pending_institution = institution
        _pending_code = None
        _pending_event.clear()

    log.info("MFA bridge: waiting for code for %s (timeout=%ds)", institution, timeout_seconds)
    got_it = _pending_event.wait(timeout=timeout_seconds)

    with _bridge_lock:
        code = _pending_code
        _pending_institution = None
        _pending_code = None

    if not got_it:
        log.warning("MFA bridge: timeout waiting for %s code", institution)
        return None

    log.info("MFA bridge: code received for %s", institution)
    return code


def submit_code(institution: str, code: str) -> bool:
    """Submit a code from the API endpoint. Returns False if wrong institution."""
    global _pending_code
    with _bridge_lock:
        if _pending_institution != institution:
            log.warning(
                "MFA bridge: submitted code for %s but waiting for %s",
                institution, _pending_institution
            )
            return False
        _pending_code = code
        _pending_event.set()
    return True


def is_pending(institution: str | None = None) -> bool:
    """Return True if an MFA code is currently being awaited."""
    with _bridge_lock:
        if institution is None:
            return _pending_institution is not None
        return _pending_institution == institution
