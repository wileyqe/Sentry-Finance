"""MFA bridge API endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.mfa_bridge import submit_code, is_pending

router = APIRouter(tags=["mfa"])


class MFASubmit(BaseModel):
    institution: str
    code: str


@router.post("/api/mfa/submit")
def submit_mfa_code(body: MFASubmit):
    """Submit an MFA code from the dashboard UI to the waiting connector."""
    if not is_pending(body.institution):
        raise HTTPException(
            status_code=409,
            detail=f"No MFA is currently pending for '{body.institution}'."
        )
    success = submit_code(body.institution, body.code)
    if not success:
        raise HTTPException(status_code=409, detail="Institution mismatch.")
    return {"status": "accepted"}


@router.get("/api/mfa/status")
def mfa_status():
    """Check whether an MFA code is currently being awaited."""
    return {"pending": is_pending(), "institution": None}
    # Note: intentionally doesn't expose which institution to keep it simple.
    # Frontend learns the institution from the SSE mfa_required event.
