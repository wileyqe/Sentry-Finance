"""
backend/credential_action_bridge.py - HITL credential action prompts.

Small in-memory bridge for connector moments that need a human choice but
should not carry secrets through the web app. The connector broadcasts an
action request over SSE, waits briefly for a UI response, then follows a safe
default if nobody answers.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from backend import sse_topics
from backend.events import broadcast_event, subscriber_count

log = logging.getLogger("sentry.backend.credential_action_bridge")

CredentialActionChoice = Literal["change_now", "remind_later"]
DEFAULT_CHOICE: CredentialActionChoice = "remind_later"


@dataclass
class PendingCredentialAction:
    action_id: str
    institution: str
    action: str
    title: str
    prompt: str
    default_choice: CredentialActionChoice = DEFAULT_CHOICE
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    choice: CredentialActionChoice | None = None
    event: threading.Event = field(default_factory=threading.Event)


_pending: dict[str, PendingCredentialAction] = {}
_lock = threading.Lock()


def request_action(
    *,
    institution: str,
    action: str,
    title: str,
    prompt: str,
    timeout_seconds: int = 45,
    default_choice: CredentialActionChoice = DEFAULT_CHOICE,
) -> CredentialActionChoice:
    """Ask the frontend for a credential-related decision.

    Returns the user's choice, or ``default_choice`` on timeout. No credential
    values are accepted or transported by this bridge.
    """
    if subscriber_count() == 0:
        log.info(
            "No frontend subscribers for credential action %s/%s; using %s",
            institution,
            action,
            default_choice,
        )
        return default_choice

    action_id = uuid.uuid4().hex
    pending = PendingCredentialAction(
        action_id=action_id,
        institution=institution,
        action=action,
        title=title,
        prompt=prompt,
        default_choice=default_choice,
    )
    with _lock:
        _pending[action_id] = pending

    broadcast_event(
        sse_topics.CREDENTIAL_ACTION_REQUIRED,
        {
            "action_id": action_id,
            "institution": institution,
            "action": action,
            "title": title,
            "prompt": prompt,
            "default_choice": default_choice,
            "timeout_seconds": timeout_seconds,
        },
    )
    log.info(
        "Credential action requested: %s/%s (timeout=%ds)",
        institution,
        action,
        timeout_seconds,
    )

    try:
        if pending.event.wait(timeout=max(0, timeout_seconds)):
            return pending.choice or default_choice
        log.info("Credential action timed out: %s/%s", institution, action)
        return default_choice
    finally:
        with _lock:
            _pending.pop(action_id, None)


def submit_choice(action_id: str, choice: CredentialActionChoice) -> bool:
    """Submit a frontend choice for a pending action."""
    if choice not in ("change_now", "remind_later"):
        return False
    with _lock:
        pending = _pending.get(action_id)
        if pending is None:
            return False
        pending.choice = choice
        pending.event.set()
    return True


def get_pending_action(action_id: str) -> dict | None:
    """Return safe metadata for one pending action."""
    with _lock:
        pending = _pending.get(action_id)
        if pending is None:
            return None
        return {
            "action_id": pending.action_id,
            "institution": pending.institution,
            "action": pending.action,
            "title": pending.title,
            "prompt": pending.prompt,
            "default_choice": pending.default_choice,
            "created_at": pending.created_at,
        }
