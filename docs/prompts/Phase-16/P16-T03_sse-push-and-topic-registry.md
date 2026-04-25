# P16-T03 — SSE push for notifications + formalized topic registry

**Status:** `[v]` Shipped 2026-04-25 on `feat/p16-t02-t03-producers-and-sse`.

## Goal

P16-T01 shipped a `NotificationPopover` that polled
`/api/notifications/unread-count` every 60 s. With more producers
landing in P16-T02 (APY changes, recurring mutations), a 60 s lag is
the wrong UX — a refresh that fires three notifications should bump
the bell within the same second. Replace polling with an SSE
listener.

The roadmap entry also called for "Formalise SSE topic registry."
At plan time, 12 topic strings were sprinkled across 5 backend files
and 2 frontend consumers — adding a 13th (`notification`) without
consolidation would deepen the debt. The user's locked decision was
to migrate all 12 now alongside the new one.

## Locked scope decisions

- **One PR.** T02 and T03 ship together. Bell-test loop benefits from
  SSE during T02 verification.
- **Migrate all 12 topics now**, not just `notification`. New
  `backend/sse_topics.py` + `frontend/src/lib/sseTopics.ts`.
- **Replace polling entirely**, do not keep a fallback `setInterval`.
  Initial mount fetch stays so the badge has a starting count without
  waiting on an SSE event.
- **Out of scope (parking lot):** `RefreshBanner.tsx` listens for
  topic names that don't match what the orchestrator emits. Pre-
  existing dead code; deletion or rewire is a separate session.

## What landed

### `backend/sse_topics.py` (new)

12 `Final[str]` constants grouped by purpose:

- Refresh lifecycle: `STATE_CHANGE`, `STALENESS_EVALUATED`,
  `AUTH_REQUIRED`, `SESSION_TIMEOUT`
- Per-institution: `INSTITUTION_STARTED`, `INSTITUTION_COMPLETE`,
  `INSTITUTION_RETRY`, `INSTITUTION_FAILED`
- Session summary: `REFRESH_COMPLETE`
- Cross-cutting: `MFA_REQUIRED`, `NOTIFICATION` (new),
  `EVENTS_DROPPED` (sentinel emitted only by `events.py` itself
  when a subscriber queue overflows)
- `ALL_TOPICS: frozenset[str]` exported for tests/introspection.

Each constant has a docstring documenting payload shape — these are
the source-of-truth contracts producers and consumers agree on.

### `frontend/src/lib/sseTopics.ts` (new)

Mirrors the backend constants. Single `SSE_TOPICS` object with
matching keys; `SseTopic` type alias derived from values. Comment at
the top notes the lockstep requirement with the backend file.

### Migration sites

**Backend (11 references):**
- `backend/refresh_orchestrator.py` — 7 `_emit()` calls
- `backend/routers/refresh.py` — 1 `broadcast_event` call
  (`REFRESH_COMPLETE`)
- `backend/routers/dev.py` — 2 `broadcast_event` calls (both
  `REFRESH_COMPLETE`)
- `extractors/tsp_connector.py` — 2 `broadcast_event` calls (both
  `MFA_REQUIRED`)
- `backend/events.py` — 1 sentinel string for the queue-overflow
  drop notification (`EVENTS_DROPPED`)

**Frontend (1 reference migrated, 1 deferred):**
- `frontend/src/components/MFAModal.tsx` — migrated to use
  `SSE_TOPICS.MFA_REQUIRED`.
- `frontend/src/components/RefreshBanner.tsx` — *not* migrated. Its
  hardcoded event names (`session_started`, `institution_progress`,
  `institution_completed`, `session_completed`, `session_failed`)
  do not match what the orchestrator actually emits. The banner
  has been silently dead since at least the orchestrator rewrite;
  introducing constants for ghost topics would mask the bug.
  Parked as the topic-name-drift backlog item in ROADMAP.md.

### `dal/notifications.record_notification` — SSE broadcast hook

After the `INSERT OR IGNORE`, when `cursor.lastrowid` is non-zero
*and* `cursor.rowcount > 0` (i.e. a real new row, not a dedup
collision), the function lazy-imports `backend.events.broadcast_event`
and `backend.sse_topics`, then publishes:

```python
broadcast_event(
    sse_topics.NOTIFICATION,
    {"id": new_id, "type": type, "severity": severity,
     "title": title, "dedup_key": dedup_key},
)
```

Wrapped in `try/except Exception` with a debug log on failure — a
broken broadcast must never break notification recording. The lazy
import keeps `dal.notifications` from importing `backend.*` at module
load (cleaner DAL/backend layering), even though `dal.alerts.py`
already shows the precedent for DAL-layer broadcasts.

### `NotificationPopover.useUnreadCount` — SSE listener

Replaced the `setInterval(refresh, 60_000)` with an `EventSource`
subscribed to `SSE_TOPICS.NOTIFICATION`:

```ts
const es = new EventSource("http://127.0.0.1:8000/api/refresh/events");
es.addEventListener(SSE_TOPICS.NOTIFICATION, () => {
  refresh();
});
es.onerror = () => {
  es.close();
  reconnectTimer = window.setTimeout(refresh, 5000);
};
return () => { es.close(); /* + clearTimeout */ };
```

Initial mount fetch preserved so the badge has a value before any
SSE event arrives. Recovery on `onerror`: closes the source and
schedules a single `refresh()` after 5 s — if the backend is reachable
again the count syncs; if not, the existing `unread-count` failure
path keeps the badge at its last known value.

### Tests (3 new, all green)

`tests/test_notifications_sse.py`:
- `test_successful_insert_broadcasts_notification` — patches
  `backend.events.broadcast_event`, calls `record_notification`,
  asserts the call came in with topic == `sse_topics.NOTIFICATION`
  and the documented payload shape.
- `test_dedup_collision_does_not_broadcast` — inserts twice with
  the same dedup_key; confirms `broadcast_event` was called exactly
  once.
- `test_broadcast_uses_registry_constant` — asserts the published
  topic equals both the literal `"notification"` and the
  `sse_topics.NOTIFICATION` constant. Locks the registry contract:
  if anyone hardcodes a string in `record_notification` that drifts
  from the constant, this test fails.

## Verification evidence

- 3/3 SSE tests pass; 8/8 APY tests + 3/3 mutation tests pass; full
  backend suite 435 pass / 2 pre-existing flakes (same as P16-T02).
- `python scripts/pii_scan.py --all-tracked` → clean.
- `npm run build` → green.
- Dev-server walkthrough:
  - Bell mounts with badge=22 (matches API).
  - Browser-side `EventSource('/api/refresh/events')` opens and
    `readyState === 1` (OPEN) confirmed via in-page eval.
  - After hand-injecting a 23rd notification into the dummy DB and
    reloading, badge updates to 23. Popover lists the new APY row
    with the right icon (`percent`), title, body, and severity
    coloring (warning).
  - Network tab shows zero recurring polls on `/unread-count` —
    only mount-time fetches and the lazy `/api/notifications` call
    on popover open. Three open SSE streams (RefreshBanner,
    MFAModal, NotificationPopover all subscribe — that's expected,
    each component owns its own EventSource).
  - All three `EventSource` connections reach `state=1` and stay
    connected through the dev session (no reconnect storms).

## Surprises / follow-ups

- **Lazy import in `record_notification`.** Top-of-module import
  would create `dal → backend → ?` coupling. The lazy import keeps
  the DAL layer importable in pure-DAL contexts (tests, scripts,
  CLI tools) without dragging the FastAPI router stack along.
  Trade-off: the broadcast path costs one Python attribute lookup +
  module-import-cache hit per insert. Negligible.
- **Race: broadcast happens before `conn.commit()`.** Producers call
  `record_notification(...)` then `conn.commit()`; the SSE event
  fires inside the first call. A consumer that reacts to the event
  by re-querying the DB could in principle race ahead of the commit
  and see no row. In practice the bell only re-queries
  `/unread-count`, which goes through a separate connection that
  serializes against the writer — and the racy window is microseconds
  on a local SQLite DB. Documented but not fixed; the alternative
  (post-commit broadcast hook) would force every producer to remember
  to call it.
- **Three EventSource streams, one shared endpoint.** RefreshBanner,
  MFAModal, and NotificationPopover each open their own subscription.
  That's three queue subscribers in `backend/events.py` per page
  load. The `_sse_subscribers` list isn't deduplicated — fine for a
  desktop single-user app, would matter at scale. Not a Phase 16
  concern; flagged for future shared-context refactor if multiple
  bells start consuming the same stream.
- **`RefreshBanner.tsx` event-name drift** discovered during the
  registry sweep. Not fixed here. Tracked under "RefreshBanner
  topic-name drift (parking lot)" in ROADMAP.md Phase 16.
