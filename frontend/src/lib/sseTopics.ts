/**
 * SSE topic constants — frontend mirror of backend/sse_topics.py.
 *
 * Keep in lockstep with the backend file. When you add a topic on
 * the backend, add it here too. When you read SSE events from
 * /api/refresh/events, compare data.type against these constants
 * instead of inline string literals so a typo becomes a static
 * error in the IDE.
 */

export const SSE_TOPICS = {
  // Refresh orchestrator lifecycle
  STATE_CHANGE: "state_change",
  STALENESS_EVALUATED: "staleness_evaluated",
  AUTH_REQUIRED: "auth_required",
  SESSION_TIMEOUT: "session_timeout",

  // Per-institution lifecycle
  INSTITUTION_STARTED: "institution_started",
  INSTITUTION_COMPLETE: "institution_complete",
  INSTITUTION_RETRY: "institution_retry",
  INSTITUTION_FAILED: "institution_failed",

  // Session-level summaries
  REFRESH_COMPLETE: "refresh_complete",

  // Cross-cutting
  MFA_REQUIRED: "mfa_required",
  CREDENTIAL_ACTION_REQUIRED: "credential_action_required",
  NOTIFICATION: "notification",
  EVENTS_DROPPED: "events_dropped",
} as const;

export type SseTopic = typeof SSE_TOPICS[keyof typeof SSE_TOPICS];
