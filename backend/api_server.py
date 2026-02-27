"""
backend/api_server.py — FastAPI application serving the finance dashboard.

Endpoints:
  - /api/accounts           — list accounts with latest balances
  - /api/transactions       — query transactions (filtered)
  - /api/balances/{id}/history — balance time series
  - /api/loan-details/{id}  — latest loan snapshot
  - /api/refresh/status     — current refresh state
  - /api/refresh/start      — trigger sync
  - /api/refresh/history    — past runs
  - /api/refresh/events     — SSE stream
  - /api/metrics/summary    — derived metrics
  - /api/staleness          — check what's stale

Design:
  - Binds to 127.0.0.1 only (local-first)
  - SQLite with WAL mode for concurrent reads
  - SSE for real-time refresh progress
"""

import asyncio
import json
import logging
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path when running as script
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from dal.database import init_db, get_db, seed_institutions
from dal.transactions import get_transactions
from dal.balances import (
    get_all_latest_balances,
    get_balance_history,
    get_latest_loan_details,
)
from dal.refresh_log import (
    get_institution_statuses,
    get_refresh_history,
    get_current_run,
    get_run_events,
)
from dal.derived import get_summary_metrics
from backend.refresh_orchestrator import (
    check_staleness,
    run_refresh,
    RefreshSession,
)
from backend.automation_worker import run_institution

log = logging.getLogger("sentry")

# ── SSE Event Bus ────────────────────────────────────────────────────────────

_sse_subscribers: list[asyncio.Queue] = []
_sse_lock = threading.Lock()


def _broadcast_event(event_type: str, data: dict):
    """Broadcast an event to all SSE subscribers."""
    msg = {"type": event_type, "data": data, "timestamp": datetime.utcnow().isoformat()}
    with _sse_lock:
        for q in _sse_subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # Drop if subscriber is slow


# ── App Setup ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup."""
    init_db()
    seed_institutions()
    log.info("API server ready — database initialized")
    yield


app = FastAPI(
    title="Sentry Finance API",
    version="1.0.0",
    description="Local-first personal finance dashboard backend",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Account & Balance Endpoints ──────────────────────────────────────────────


@app.get("/api/accounts")
def list_accounts():
    """List all accounts with their latest balances."""
    with get_db() as conn:
        balances = get_all_latest_balances(conn)
        # Also get accounts without balance snapshots
        all_accounts = conn.execute(
            "SELECT id, institution_id, name, last4, type "
            "FROM accounts WHERE is_active = 1"
        ).fetchall()
        all_accounts = [dict(r) for r in all_accounts]

    # Merge balances into accounts
    bal_map = {b["account_id"]: b for b in balances}
    for acct in all_accounts:
        bal = bal_map.get(acct["id"])
        acct["balance"] = bal["balance"] if bal else None
        acct["balance_as_of"] = bal["as_of"] if bal else None

    return {"accounts": all_accounts}


@app.get("/api/balances/{account_id}/history")
def balance_history(
    account_id: str,
    start_date: str = Query(None),
    end_date: str = Query(None),
    limit: int = Query(365, le=1000),
):
    """Get balance history for an account."""
    with get_db() as conn:
        history = get_balance_history(conn, account_id, start_date, end_date, limit)
    return {"account_id": account_id, "history": history}


@app.get("/api/loan-details/{account_id}")
def loan_details(account_id: str):
    """Get latest loan details for an account."""
    with get_db() as conn:
        details = get_latest_loan_details(conn, account_id)
    return {"account_id": account_id, "details": details}


# ── Transaction Endpoints ────────────────────────────────────────────────────


@app.get("/api/transactions")
def list_transactions(
    account_id: str = Query(None),
    institution_id: str = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    status: str = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
):
    """Query transactions with optional filters."""
    with get_db() as conn:
        txns = get_transactions(
            conn,
            account_id,
            institution_id,
            start_date,
            end_date,
            status,
            limit,
            offset,
        )
    return {"transactions": txns, "count": len(txns)}


# ── Refresh Endpoints ────────────────────────────────────────────────────────


@app.get("/api/staleness")
def staleness_check():
    """Check which institutions are stale."""
    return {"institutions": check_staleness()}


@app.get("/api/refresh/status")
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


_refresh_lock = threading.Lock()


@app.post("/api/refresh/start")
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
            session.on_event(_broadcast_event)
            result = session.run(worker_fn=run_institution)
            _broadcast_event("refresh_complete", result)
        finally:
            _refresh_lock.release()

    thread = threading.Thread(target=_run_in_thread, daemon=True)
    thread.start()

    return {"status": "started", "trigger": trigger}


@app.get("/api/refresh/history")
def refresh_history(limit: int = Query(20, le=100)):
    """Get past refresh runs with summary stats."""
    with get_db() as conn:
        history = get_refresh_history(conn, limit)
    return {"runs": history}


# ── SSE Stream ───────────────────────────────────────────────────────────────


@app.get("/api/refresh/events")
async def refresh_event_stream():
    """Server-Sent Events stream for real-time refresh progress.

    Connect from frontend:
        const es = new EventSource('/api/refresh/events');
        es.onmessage = (e) => console.log(JSON.parse(e.data));
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    with _sse_lock:
        _sse_subscribers.append(queue)

    async def event_generator():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield (f"event: {msg['type']}\ndata: {json.dumps(msg)}\n\n")
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
        finally:
            with _sse_lock:
                _sse_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ── Metrics Endpoint ─────────────────────────────────────────────────────────


@app.get("/api/metrics/summary")
def metrics_summary():
    """Get derived summary metrics."""
    with get_db() as conn:
        metrics = get_summary_metrics(conn)
    return {"metrics": metrics}


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/api/health")
def health():
    """Health check endpoint."""
    with get_db() as conn:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
    return {
        "status": "ok",
        "schema_version": ver,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%H:%M:%S",
    )

    print("\n  🌐  Sentry Finance API")
    print("  📡  http://127.0.0.1:8000/docs")
    print()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
