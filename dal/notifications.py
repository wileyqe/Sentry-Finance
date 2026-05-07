"""
dal/notifications.py — Unified notification feed persistence.

Single write path for all notification producers (refresh failures, budget
alerts, upcoming/overdue bills, doc-drop nudges). Caller commits — this
module never calls conn.commit() so producers can batch multiple inserts
in one transaction.

Schema lives in dal/migrations/v38_notifications.py.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("sentry.dal.notifications")

VALID_TYPES = frozenset(
    {
        "refresh_failure",
        "budget_alert",
        "bill_due_soon",
        "bill_overdue",
        "doc_drop_nudge",
        "apy_rate_change",
        "recurring_price_mutation",
        # AI-033: surfaced when persist_connector_result records a
        # balance whose ratio to the previous snapshot exceeds 10× / 0.1×.
        "balance_anomaly",
        # AI-036: surfaced when at least one CSV in a connector result
        # fails to parse / upsert.
        "csv_parse_failure",
        # Live connector surfaced an action the user should handle
        # manually, such as a deferred institution password rotation.
        "credential_action_needed",
    }
)
VALID_SEVERITIES = frozenset({"info", "warning", "critical"})


# ── Invariant guards ──────────────────────────────────────────────────────────


def _assert_valid(
    type: str,
    severity: str,
    dedup_key: str,
    payload: object,
) -> None:
    if type not in VALID_TYPES:
        raise ValueError(
            f"notifications.type {type!r} not in {sorted(VALID_TYPES)!r}"
        )
    if severity not in VALID_SEVERITIES:
        raise ValueError(
            f"notifications.severity {severity!r} not in {sorted(VALID_SEVERITIES)!r}"
        )
    if not dedup_key or not dedup_key.strip():
        raise ValueError("notifications.dedup_key must be a non-empty string")
    if payload is not None:
        try:
            json.dumps(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"notifications.payload is not JSON-serializable: {exc}") from exc


# ── Write ─────────────────────────────────────────────────────────────────────


def record_notification(
    conn: sqlite3.Connection,
    *,
    type: str,
    title: str,
    dedup_key: str,
    body: Optional[str] = None,
    payload: Optional[dict] = None,
    severity: str = "info",
    link: Optional[str] = None,
) -> Optional[int]:
    """Insert a notification row.

    Returns the new row id, or None when dedup_key already exists
    (INSERT OR IGNORE silently drops the duplicate).

    On successful insert (not a dedup collision), broadcasts an SSE
    `notification` event so the frontend bell can live-update without
    polling. Broadcast failure does not affect insert success.

    Caller commits.
    """
    _assert_valid(type, severity, dedup_key, payload)

    payload_json = json.dumps(payload) if payload is not None else None

    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO notifications
            (type, severity, title, body, payload_json, link, dedup_key)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (type, severity, title, body, payload_json, link, dedup_key),
    )
    if cursor.lastrowid and cursor.rowcount > 0:
        new_id = cursor.lastrowid
        try:
            from backend.events import broadcast_event
            from backend import sse_topics
            broadcast_event(
                sse_topics.NOTIFICATION,
                {
                    "id": new_id,
                    "type": type,
                    "severity": severity,
                    "title": title,
                    "dedup_key": dedup_key,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("Notification SSE broadcast failed: %s", exc)
        return new_id
    return None


# ── Read ──────────────────────────────────────────────────────────────────────


def list_notifications(
    conn: sqlite3.Connection,
    *,
    include_dismissed: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Return notifications ordered by most recent first.

    By default excludes dismissed entries. Pass include_dismissed=True to
    include them (e.g. for an "all notifications" history view).
    """
    if include_dismissed:
        rows = conn.execute(
            "SELECT * FROM notifications ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM notifications
            WHERE dismissed_at IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        if d.get("payload_json"):
            try:
                d["payload"] = json.loads(d["payload_json"])
            except (json.JSONDecodeError, TypeError):
                d["payload"] = None
        else:
            d["payload"] = None
        del d["payload_json"]
        result.append(d)
    return result


def get_unread_count(conn: sqlite3.Connection) -> int:
    """Count notifications that are undismissed and not yet read."""
    row = conn.execute(
        """
        SELECT COUNT(*) FROM notifications
        WHERE dismissed_at IS NULL
          AND read_at IS NULL
        """
    ).fetchone()
    return row[0] if row else 0


# ── State transitions ─────────────────────────────────────────────────────────


def mark_read(
    conn: sqlite3.Connection,
    ids: Optional[list[int]] = None,
) -> int:
    """Set read_at on unread notifications.

    Pass ids=None to mark all unread notifications read.
    Returns the number of rows updated.

    Caller commits.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if ids is None:
        cursor = conn.execute(
            "UPDATE notifications SET read_at = ? WHERE read_at IS NULL",
            (now,),
        )
    else:
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        cursor = conn.execute(
            f"UPDATE notifications SET read_at = ? WHERE id IN ({placeholders}) AND read_at IS NULL",
            [now, *ids],
        )
    return cursor.rowcount


def dismiss(
    conn: sqlite3.Connection,
    ids: list[int],
) -> int:
    """Set dismissed_at on the given notification ids.

    Dismissed notifications are excluded from list_notifications by default.
    Returns the number of rows updated.

    Caller commits.
    """
    if not ids:
        return 0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    placeholders = ",".join("?" * len(ids))
    cursor = conn.execute(
        f"UPDATE notifications SET dismissed_at = ? WHERE id IN ({placeholders})",
        [now, *ids],
    )
    return cursor.rowcount
