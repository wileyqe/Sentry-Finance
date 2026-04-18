"""
extractors/_retry.py — Shared polling and retry helpers for connectors.

Consolidates the ad-hoc ``time.sleep`` loops that had grown across
``chrome_cdp.py``, ``sms_otp.py``, and the per-institution connectors.
Kept intentionally tiny: no logging, no metrics, no async variants —
connectors that need richer resilience still use ``ai_backstop``.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def poll_with_timeout(
    predicate: Callable[[], T | None],
    timeout_s: float,
    interval_s: float = 0.5,
) -> T | None:
    """Poll ``predicate()`` until it returns a truthy value or the timeout elapses.

    Swallows predicate exceptions (treated as "not ready yet") so callers
    don't have to re-wrap every probe. Returns the first truthy value, or
    ``None`` on timeout.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            result = predicate()
        except Exception:
            result = None
        if result:
            return result
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval_s)


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay_s: float = 1.0,
) -> T:
    """Call ``fn()`` up to ``attempts`` times with exponential backoff between tries.

    Delay schedule: ``base_delay_s * 2**i`` before the (i+1)th retry. Re-raises
    the final exception if every attempt fails.
    """
    last_exc: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if i < attempts - 1:
                time.sleep(base_delay_s * (2**i))
    assert last_exc is not None  # unreachable when attempts >= 1
    raise last_exc
