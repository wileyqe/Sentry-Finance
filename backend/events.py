"""
backend/events.py — SSE event bus for real-time refresh progress.

Provides a simple pub/sub broadcast mechanism used by the refresh
orchestrator to push events to connected frontend clients.

Uses stdlib queue.Queue (thread-safe) so that broadcast_event() can
be called safely from background threads without corrupting asyncio
internals.
"""

import json
import logging
import queue
import threading
from datetime import datetime, timezone

from backend import sse_topics

log = logging.getLogger("sentry.backend.events")

_sse_subscribers: list[queue.Queue] = []
_sse_lock = threading.Lock()

# Module-level refresh lock — shared between the refresh router
# (which acquires/releases it) and aggregation endpoints (which
# check .locked() to surface a "refresh_in_progress" flag).
_refresh_lock = threading.Lock()


def is_refresh_active() -> bool:
    """Return True if a refresh session is currently running."""
    return _refresh_lock.locked()


def broadcast_event(event_type: str, data: dict):
    """Broadcast an event to all SSE subscribers (thread-safe)."""
    msg = {"type": event_type, "data": data, "timestamp": datetime.now(timezone.utc).isoformat()}
    with _sse_lock:
        for q in _sse_subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                log.warning(
                    "SSE subscriber queue full — dropping event %s "
                    "(client may be slow or disconnected)",
                    event_type,
                )
                # Drain oldest item and push a gap notification so the
                # client knows to poll /api/refresh/status for ground truth.
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(
                        {
                            "type": sse_topics.EVENTS_DROPPED,
                            "data": {
                                "reason": "subscriber_slow",
                                "hint": "Poll /api/refresh/status for current state.",
                            },
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                except queue.Full:
                    pass


def subscribe() -> queue.Queue:
    """Register a new SSE subscriber and return its queue."""
    q: queue.Queue = queue.Queue(maxsize=100)
    with _sse_lock:
        _sse_subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue):
    """Remove a subscriber queue."""
    with _sse_lock:
        try:
            _sse_subscribers.remove(q)
        except ValueError:
            pass
