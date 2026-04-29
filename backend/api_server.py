"""
backend/api_server.py — FastAPI application serving the finance dashboard.

This is the application entrypoint. All endpoint logic lives in the
backend/routers/ sub-package; this file handles:
  - App creation, lifespan, and CORS
  - Router registration
  - Health check

Design:
  - Binds to 127.0.0.1 only (local-first)
  - SQLite with WAL mode for concurrent reads
  - SSE for real-time refresh progress (see routers/refresh.py)
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path when running as script
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dal.database import (
    db_mode,
    get_db,
    init_db,
    require_explicit_db_path,
    resolve_db_path,
    seed_institutions,
)
from dal.alerts import seed_default_rules
from dal.trusted_seed_manifest import live_seed_fingerprint, load_manifest
from backend.refresh_orchestrator import recover_orphaned_runs

# ── Router imports ───────────────────────────────────────────────────────────
from backend.routers import (
    accounts,
    transactions,
    refresh,
    budgets,
    recurring,
    alerts,
    reports,
    goals,
    debt,
    cash_flow,
    user_rules,
    freshness,
    documents,
    mfa,
    settings,
    payroll,
    investments,
    notifications,
    dev,
)

log = logging.getLogger("sentry.backend.api")


# ── App Setup ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup."""
    db_path = require_explicit_db_path()
    log.info("API runtime using DB path: %s", db_path)
    init_db()
    with get_db() as conn:
        manifest = load_manifest(conn)
    if manifest:
        log.info(
            "Trusted seed manifest detected; skipping startup fixture seeding"
        )
    else:
        seed_institutions()
        with get_db() as conn:
            seed_default_rules(conn)
            conn.commit()
    recovered = recover_orphaned_runs()
    if recovered:
        log.warning("Recovered %d orphaned refresh run(s) from prior crash", recovered)
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
        "http://localhost:1420",
        "http://127.0.0.1:1420",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Register Routers ────────────────────────────────────────────────────────

app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(refresh.router)
app.include_router(budgets.router)
app.include_router(recurring.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(goals.router)
app.include_router(debt.router)
app.include_router(cash_flow.router)
app.include_router(user_rules.router)
app.include_router(freshness.router)
app.include_router(documents.router)
app.include_router(mfa.router)
app.include_router(settings.router)
app.include_router(payroll.router)
app.include_router(investments.router)
app.include_router(notifications.router)
app.include_router(dev.router)

# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/api/health")
def health():
    """Health check endpoint."""
    with get_db() as conn:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
    return {
        "status": "ok",
        "schema_version": ver,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/runtime/identity")
def runtime_identity():
    """Return the backend's active DB identity and trusted-seed state."""
    resolved_path = resolve_db_path(require_explicit=True).resolve()
    with get_db(resolved_path) as conn:
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        manifest = load_manifest(conn)
        live = live_seed_fingerprint(conn)

    manifest_fingerprint = (manifest or {}).get("database_fingerprint")
    live_fingerprint = live["database_fingerprint"]
    return {
        "db_mode": db_mode(),
        "db_path": str(resolved_path),
        "process_id": os.getpid(),
        "schema_version": schema_version,
        "seed_version": (manifest or {}).get("seed_version"),
        "reference_date": (manifest or {}).get("reference_date"),
        "manifest_fingerprint": manifest_fingerprint,
        "live_fingerprint": live_fingerprint,
        "fingerprint_match": bool(
            manifest_fingerprint and manifest_fingerprint == live_fingerprint
        ),
    }


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    from config.logging_config import setup_logging

    setup_logging()

    print("\n  Sentry Finance API")
    print("  http://127.0.0.1:8000/docs")
    print()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
