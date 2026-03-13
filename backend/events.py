"""
backend/events.py — SSE event bus for real-time refresh progress.

Provides a simple pub/sub broadcast mechanism used by the refresh
orchestrator to push events to connected frontend clients.
"""

import asyncio
import json
import logging
import threading
from datetime import datetime

log = logging.getLogger("sentry.backend.events")

_sse_subscribers: list[asyncio.Queue] = []
_sse_lock = threading.Lock()


def broadcast_event(event_type: str, data: dict):
    """Broadcast an event to all SSE subscribers."""
    msg = {"type": event_type, "data": data, "timestamp": datetime.utcnow().isoformat()}
    with _sse_lock:
        for q in _sse_subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # Drop if subscriber is slow


def subscribe() -> asyncio.Queue:
    """Register a new SSE subscriber and return its queue."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _sse_lock:
        _sse_subscribers.append(queue)
    return queue


def unsubscribe(queue: asyncio.Queue):
    """Remove a subscriber queue."""
    with _sse_lock:
        try:
            _sse_subscribers.remove(queue)
        except ValueError:
            pass
