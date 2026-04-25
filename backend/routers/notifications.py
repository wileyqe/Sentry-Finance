"""Notification feed endpoints.

The notification feed is household-level (no owner scoping). All producers
write to the shared notifications table; the bell badge and popover consume
these endpoints via polling every 60 s.
"""

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from dal.database import get_db
from dal.notifications import (
    list_notifications,
    get_unread_count,
    mark_read,
    dismiss,
)

router = APIRouter(tags=["notifications"])


class IdsBody(BaseModel):
    ids: Optional[list[int]] = None


class DismissBody(BaseModel):
    ids: list[int]


@router.get("/api/notifications")
def get_notifications(
    include_dismissed: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
):
    """Return the notification feed, newest first.

    Excludes dismissed entries by default. Pass include_dismissed=true
    for a full history view.
    """
    with get_db() as conn:
        items = list_notifications(conn, include_dismissed=include_dismissed, limit=limit)
    return {"notifications": items}


@router.get("/api/notifications/unread-count")
def unread_count():
    """Return the count of undismissed, unread notifications for the badge."""
    with get_db() as conn:
        count = get_unread_count(conn)
    return {"count": count}


@router.post("/api/notifications/mark-read")
def mark_notifications_read(body: IdsBody = IdsBody()):
    """Mark notifications as read.

    Omit ``ids`` (or pass an empty list) to mark all unread notifications read.
    """
    ids = body.ids if body.ids else None
    with get_db() as conn:
        updated = mark_read(conn, ids)
        conn.commit()
    return {"updated": updated}


@router.post("/api/notifications/dismiss")
def dismiss_notifications(body: DismissBody):
    """Remove specific notifications from the active feed by id."""
    with get_db() as conn:
        updated = dismiss(conn, body.ids)
        conn.commit()
    return {"updated": updated}
