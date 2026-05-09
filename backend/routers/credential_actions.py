"""Credential action endpoints.

These endpoints carry only decisions and process-launch requests. They must
never accept credential values from the dashboard.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.credential_broker import get_credential_metadata
from backend.credential_action_bridge import get_pending_action, submit_choice

log = logging.getLogger("sentry.backend.routers.credential_actions")

router = APIRouter(tags=["credential-actions"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BROKER_SCRIPT = PROJECT_ROOT / "backend" / "credential_broker.py"
INSTITUTION_RE = re.compile(r"^[a-z0-9_-]{1,64}$")

CredentialActionChoice = Literal["change_now", "remind_later"]


class CredentialActionResponse(BaseModel):
    action_id: str
    choice: CredentialActionChoice


class CredentialStoreLaunch(BaseModel):
    institution: str


def _normalize_institution(institution: str) -> str:
    normalized = institution.strip().lower()
    if not INSTITUTION_RE.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Invalid institution id.")
    return normalized


def _launch_credential_store_prompt(institution: str) -> int:
    """Open a local broker prompt for updating OS-stored credentials."""
    if not BROKER_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="Credential broker not found.")

    kwargs: dict = {
        "cwd": str(PROJECT_ROOT),
        "close_fds": True,
    }
    creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    if sys.platform == "win32" and creation_flags:
        kwargs["creationflags"] = creation_flags

    try:
        proc = subprocess.Popen(
            [sys.executable, str(BROKER_SCRIPT), "--store", institution],
            **kwargs,
        )
    except Exception as exc:
        log.exception("Failed to launch credential store prompt for %s", institution)
        raise HTTPException(
            status_code=500,
            detail=f"Credential broker launch failed: {exc}",
        ) from exc

    return int(proc.pid)


@router.post("/api/credential-actions/respond")
def respond_to_credential_action(body: CredentialActionResponse):
    """Submit a dashboard choice to the waiting connector."""
    if get_pending_action(body.action_id) is None:
        raise HTTPException(status_code=409, detail="Credential action expired.")

    if not submit_choice(body.action_id, body.choice):
        raise HTTPException(status_code=409, detail="Credential action expired.")

    return {"status": "accepted"}


@router.post("/api/credential-actions/launch-credential-store")
def launch_credential_store(body: CredentialStoreLaunch):
    """Launch the interactive broker store prompt without browser secrets."""
    institution = _normalize_institution(body.institution)
    launched_at = datetime.now(timezone.utc).isoformat()
    pid = _launch_credential_store_prompt(institution)
    return {
        "status": "launched",
        "institution": institution,
        "pid": pid,
        "launched_at": launched_at,
    }


@router.get("/api/credential-actions/store-status/{institution}")
def credential_store_status(institution: str):
    """Return non-secret Credential Manager metadata for an institution."""
    normalized = _normalize_institution(institution)
    try:
        metadata = get_credential_metadata(normalized)
    except Exception as exc:
        log.exception("Failed to read credential metadata for %s", normalized)
        raise HTTPException(
            status_code=500,
            detail=f"Credential metadata read failed: {exc}",
        ) from exc

    return {
        "institution": normalized,
        "exists": bool(metadata.get("exists")),
        "schema": metadata.get("schema"),
        "kind": metadata.get("kind"),
        "stored_at": metadata.get("stored_at"),
    }
