"""Shared clock helpers for UI-facing calculations.

Live databases keep using real current time.  Trusted synthetic databases opt
into a fixed reference date by storing ``trusted_seed_manifest`` in
app_settings, which makes reports and freshness labels deterministic.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, time, timezone
from typing import Any

_ENV_REFERENCE_DATE = "SENTRY_REFERENCE_DATE"
_ENV_REFERENCE_DATETIME = "SENTRY_REFERENCE_DATETIME"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _trusted_manifest(conn: sqlite3.Connection | None) -> dict | None:
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'trusted_seed_manifest'"
        ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        return json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return None


def reference_date(conn: sqlite3.Connection | None = None) -> date:
    env_date = _parse_date(os.environ.get(_ENV_REFERENCE_DATE))
    if env_date:
        return env_date

    manifest = _trusted_manifest(conn)
    manifest_date = _parse_date((manifest or {}).get("reference_date"))
    if manifest_date:
        return manifest_date

    return date.today()


def reference_datetime(conn: sqlite3.Connection | None = None) -> datetime:
    env_dt = _parse_datetime(os.environ.get(_ENV_REFERENCE_DATETIME))
    if env_dt:
        return env_dt

    env_date = _parse_date(os.environ.get(_ENV_REFERENCE_DATE))
    if env_date:
        return datetime.combine(env_date, time.min, tzinfo=timezone.utc)

    manifest = _trusted_manifest(conn)
    manifest_dt = _parse_datetime((manifest or {}).get("reference_datetime"))
    if manifest_dt:
        return manifest_dt

    manifest_date = _parse_date((manifest or {}).get("reference_date"))
    if manifest_date:
        return datetime.combine(manifest_date, time.min, tzinfo=timezone.utc)

    return datetime.now(timezone.utc)


def reference_datetime_iso(conn: sqlite3.Connection | None = None) -> str:
    return reference_datetime(conn).replace(microsecond=0).isoformat()


def reference_clock_context(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Return the effective backend reference clock and why it was selected."""
    env_dt = _parse_datetime(os.environ.get(_ENV_REFERENCE_DATETIME))
    if env_dt:
        return _clock_payload("env_reference_datetime", env_dt, fixed=True)

    env_date = _parse_date(os.environ.get(_ENV_REFERENCE_DATE))
    if env_date:
        dt = datetime.combine(env_date, time.min, tzinfo=timezone.utc)
        return _clock_payload("env_reference_date", dt, fixed=True)

    manifest = _trusted_manifest(conn)
    manifest_dt = _parse_datetime((manifest or {}).get("reference_datetime"))
    if manifest_dt:
        return _clock_payload("trusted_seed_manifest", manifest_dt, fixed=True)

    manifest_date = _parse_date((manifest or {}).get("reference_date"))
    if manifest_date:
        dt = datetime.combine(manifest_date, time.min, tzinfo=timezone.utc)
        return _clock_payload("trusted_seed_manifest", dt, fixed=True)

    return _clock_payload("system_clock", datetime.now(timezone.utc), fixed=False)


def _clock_payload(source: str, dt: datetime, *, fixed: bool) -> dict[str, Any]:
    normalized = dt.astimezone(timezone.utc).replace(microsecond=0)
    return {
        "source": source,
        "reference_date": normalized.date().isoformat(),
        "reference_datetime": normalized.isoformat(),
        "fixed": fixed,
    }

