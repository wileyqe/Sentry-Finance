"""
backend/sse_topics.py — Single source of truth for SSE event topic names.

Every `broadcast_event(topic, ...)` call and every orchestrator `_emit(topic, ...)`
call must reference a constant from this module. The frontend mirror lives at
`frontend/src/lib/sseTopics.ts` — keep the two files in lockstep.

Why a registry: before this file, topic strings were hardcoded inline across
5 backend files and 2 frontend files (12 distinct names). One renamed string
silently broke the producer/consumer pair. Centralizing the names makes
mismatches a static error instead of a runtime no-op.
"""

from __future__ import annotations

from typing import Final


# ── Refresh orchestrator lifecycle ────────────────────────────────────────────

STATE_CHANGE: Final[str] = "state_change"
"""RefreshSession transitioned. Payload: {state, previous}."""

STALENESS_EVALUATED: Final[str] = "staleness_evaluated"
"""Staleness check finished. Payload: {stale: list[str]}."""

AUTH_REQUIRED: Final[str] = "auth_required"
"""One or more institutions need re-auth. Payload: {institutions: list[str]}."""

SESSION_TIMEOUT: Final[str] = "session_timeout"
"""Session exceeded its timeout. Payload: {timeout: int}."""


# ── Per-institution lifecycle ─────────────────────────────────────────────────

INSTITUTION_STARTED: Final[str] = "institution_started"
"""Institution attempt began. Payload: {institution, attempt}."""

INSTITUTION_COMPLETE: Final[str] = "institution_complete"
"""Institution finished successfully. Payload: {institution, ...worker_result}."""

INSTITUTION_RETRY: Final[str] = "institution_retry"
"""Institution scheduled for retry. Payload: {institution, delay, attempt}."""

INSTITUTION_FAILED: Final[str] = "institution_failed"
"""Institution gave up after retries. Payload: {institution, error}."""


# ── Session-level summaries ───────────────────────────────────────────────────

REFRESH_COMPLETE: Final[str] = "refresh_complete"
"""Refresh session finished. Payload: {status, trigger, institutions, ...summary}."""


# ── Cross-cutting events ──────────────────────────────────────────────────────

MFA_REQUIRED: Final[str] = "mfa_required"
"""Connector is blocked on an MFA code. Payload: {institution, prompt}."""

CREDENTIAL_ACTION_REQUIRED: Final[str] = "credential_action_required"
"""Connector needs a non-secret user decision. Payload:
{action_id, institution, action, title, prompt, default_choice,
timeout_seconds}."""

NOTIFICATION: Final[str] = "notification"
"""A new row landed in the notifications table. Payload:
{id, type, severity, title, dedup_key}. Frontend bell uses this to live-update
the badge instead of polling /api/notifications/unread-count."""

EVENTS_DROPPED: Final[str] = "events_dropped"
"""A subscriber's queue overflowed and lost messages. Payload:
{reason, hint}. Sentinel only — emitted by events.py itself."""


# ── Frozen registry (introspection / tests) ──────────────────────────────────

ALL_TOPICS: Final[frozenset[str]] = frozenset(
    {
        STATE_CHANGE,
        STALENESS_EVALUATED,
        AUTH_REQUIRED,
        SESSION_TIMEOUT,
        INSTITUTION_STARTED,
        INSTITUTION_COMPLETE,
        INSTITUTION_RETRY,
        INSTITUTION_FAILED,
        REFRESH_COMPLETE,
        MFA_REQUIRED,
        CREDENTIAL_ACTION_REQUIRED,
        NOTIFICATION,
        EVENTS_DROPPED,
    }
)
