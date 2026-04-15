"""
backend/routers/settings.py — App settings endpoints.

GET  /api/settings               — All settings
PATCH /api/settings/{key}        — Update single setting
GET  /api/settings/refresh-policy — YAML base + overrides merge
GET  /api/settings/multi-user-enabled — Convenience boolean
"""

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException

from dal.database import get_db
from dal.settings import get_all_settings, get_setting, set_setting

log = logging.getLogger("sentry.backend.settings")
router = APIRouter()

VALID_KEYS = {
    "multi_user_enabled",
    "refresh_intervals",
    "notification_preferences",
    "expected_monthly_docs",
    "expected_annual_docs",
    "archival_months",
    "show_synthetic_data",
}

_REFRESH_POLICY_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "refresh_policy.yaml"


@router.get("/api/settings")
def get_settings():
    """Return all app settings."""
    with get_db() as conn:
        return get_all_settings(conn)


@router.patch("/api/settings/{key}")
def update_setting(key: str, body: dict):
    """
    Update a single setting.

    Body: {"value": <new_value>}
    """
    if key not in VALID_KEYS:
        raise HTTPException(400, f"Unknown setting: {key}")
    if "value" not in body:
        raise HTTPException(422, "Body must contain 'value' field")

    with get_db() as conn:
        set_setting(conn, key, body["value"])
    return {"status": "updated", "key": key}


@router.get("/api/settings/refresh-policy")
def get_refresh_policy():
    """
    Return the effective refresh policy: base YAML config merged with
    any per-institution overrides from app_settings.
    """
    base_policy = {}
    try:
        if _REFRESH_POLICY_PATH.exists():
            with open(_REFRESH_POLICY_PATH, "r") as f:
                base_policy = yaml.safe_load(f) or {}
    except Exception:
        log.exception("Failed to load refresh_policy.yaml")

    with get_db() as conn:
        overrides = get_setting(conn, "refresh_intervals") or {}

    for inst_id, hours in overrides.items():
        if inst_id in base_policy:
            base_policy[inst_id]["refresh_interval_hours"] = hours

    return base_policy


@router.get("/api/settings/multi-user-enabled")
def get_multi_user_enabled():
    """Convenience endpoint returning just the boolean."""
    with get_db() as conn:
        enabled = get_setting(conn, "multi_user_enabled")
    return {"enabled": enabled is True}
