"""Refresh orchestration, staleness checks, and SSE event stream."""

import asyncio
import json
import logging
import queue
import threading

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse

from dal.database import get_db
from dal.refresh_log import (
    get_institution_statuses,
    get_refresh_history,
    get_current_run,
    get_run_events,
)
from backend.events import (
    broadcast_event,
    subscribe,
    unsubscribe,
    _refresh_lock,
)
from backend.refresh_orchestrator import (
    check_staleness,
    RefreshSession,
)
from backend.automation_worker import run_institution

log = logging.getLogger("sentry.backend.api.refresh")

router = APIRouter(tags=["refresh"])


@router.get("/api/staleness")
def staleness_check():
    """Check which institutions are stale."""
    return {"institutions": check_staleness()}


@router.get("/api/refresh/status")
def refresh_status():
    """Get current refresh state and per-institution progress."""
    with get_db() as conn:
        current = get_current_run(conn)
        statuses = get_institution_statuses(conn)
        events = []
        if current:
            events = get_run_events(conn, current["id"])

    return {
        "current_run": current,
        "institution_statuses": statuses,
        "events": events,
    }


@router.post("/api/refresh/start")
def start_refresh(trigger: str = "manual_sync"):
    """Trigger a new refresh session.

    Runs asynchronously in a background thread so the API
    remains responsive. Prevents concurrent executions.
    """
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="A refresh session is already in progress."
        )

    def _run_in_thread():
        try:
            session = RefreshSession(trigger=trigger)
            session.on_event(broadcast_event)
            result = session.run(worker_fn=run_institution)
            broadcast_event("refresh_complete", result)
        finally:
            _refresh_lock.release()

    thread = threading.Thread(target=_run_in_thread, daemon=True)
    thread.start()

    return {"status": "started", "trigger": trigger}


@router.get("/api/refresh/history")
def refresh_history(limit: int = Query(20, le=100)):
    """Get past refresh runs with summary stats."""
    with get_db() as conn:
        history = get_refresh_history(conn, limit)
    return {"runs": history}


# ── SSE Stream ───────────────────────────────────────────────────────────────


@router.get("/api/refresh/events")
async def refresh_event_stream():
    """Server-Sent Events stream for real-time refresh progress.

    Connect from frontend:
        const es = new EventSource('/api/refresh/events');
        es.onmessage = (e) => console.log(JSON.parse(e.data));
    """
    q = subscribe()

    async def event_generator():
        loop = asyncio.get_event_loop()
        try:
            while True:
                try:
                    # Block in a thread-pool executor so we don't hold
                    # the event loop while waiting on the stdlib Queue.
                    msg = await asyncio.wait_for(
                        loop.run_in_executor(None, q.get, True, 30),
                        timeout=35,
                    )
                    yield f"event: {msg['type']}\ndata: {json.dumps(msg)}\n\n"
                except (asyncio.TimeoutError, queue.Empty):
                    # Send keepalive comment to prevent proxy/browser timeout
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
