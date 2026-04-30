"""Dev-mode utilities exposed to the dashboard.

These endpoints exist to make local development with synthetic data
ergonomic. They are local-first and never reach the network, but they
should NOT be exposed in any deployed build.

Currently:
  POST /api/dev/reset-trusted-seed
    Re-runs the canonical trusted synthetic seeder.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend import sse_topics
from backend.events import broadcast_event
from dal.database import db_mode, get_db

log = logging.getLogger("sentry.backend.api.dev")

router = APIRouter(tags=["dev"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SEED_SCRIPT = _PROJECT_ROOT / "scripts" / "seed_dummy_data.py"
_MANIFEST = _PROJECT_ROOT / "data" / "trusted_seed_manifest.json"


def _load_manifest() -> dict | None:
    if _MANIFEST.exists():
        try:
            return json.loads(_MANIFEST.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = 'trusted_seed_manifest'"
            ).fetchone()
    except Exception:
        return None

    if not row:
        return None
    try:
        return json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return None


@router.post("/api/dev/reset-trusted-seed")
def reset_trusted_seed():
    """Rebuild the canonical trusted synthetic dataset."""
    if db_mode() not in {"dev", "trusted"}:
        raise HTTPException(
            status_code=403,
            detail="Trusted seed reset is only available in dev/trusted DB modes.",
        )

    if not _SEED_SCRIPT.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Seeder script not found at {_SEED_SCRIPT}",
        )

    log.info("Dev reset: re-seeding canonical trusted synthetic dataset")

    try:
        proc = subprocess.run(
            [sys.executable, str(_SEED_SCRIPT)],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        log.error("Dev reset seeder timed out\nSTDOUT:\n%s\nSTDERR:\n%s", exc.stdout, exc.stderr)
        raise HTTPException(status_code=500, detail="Seeder timed out") from exc
    if proc.returncode != 0:
        log.error(
            "Dev reset seeder failed (rc=%s)\nSTDOUT:\n%s\nSTDERR:\n%s",
            proc.returncode,
            proc.stdout[-2000:],
            proc.stderr[-2000:],
        )
        raise HTTPException(
            status_code=500,
            detail=f"Seeder failed with exit code {proc.returncode}",
        )

    manifest = _load_manifest() or {}
    payload = {
        "trigger": "dev_reset_trusted_seed",
        "seed_version": manifest.get("seed_version"),
        "end_date": manifest.get("end_date"),
        "reference_date": manifest.get("reference_date"),
        "database_fingerprint": manifest.get("database_fingerprint"),
    }
    broadcast_event(sse_topics.REFRESH_COMPLETE, payload)

    return {
        "ok": True,
        "seed_version": payload["seed_version"],
        "end_date": payload["end_date"],
        "reference_date": payload["reference_date"],
        "database_fingerprint": payload["database_fingerprint"],
    }
