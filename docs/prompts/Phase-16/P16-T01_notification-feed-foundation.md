# P16-T01: Notification Feed Foundation

## Context

The header bell at `frontend/src/components/layout/Header.tsx` was a dead
placeholder pointing to this phase. The producer pipeline was largely already
in place — `dal/alerts.py` evaluated budget/large-txn/balance-low alerts after
every refresh, `dal/bills.py::get_upcoming_bills` returned overdue/due-soon
rows, and `backend/routers/documents.py::pending_nudges` queried doc-drop
state — but all three wrote to different tables or localStorage with no unified
surface the bell could read. Goal: ship a working notification feed with
persistent dismissal and 4 wired producers in a single session.

User decisions locked at planning: foundation + 4 producers (APY rate-change
and recurring price-mutations deferred to T02), household-only scoping for v1,
two-state read+dismissed semantics, polling (no SSE push until T03).

## Starting State

- `dal/alerts.py` — full `budget_pct` / `large_txn` / `balance_low` engine,
  fired from `result_writer.py::_alerts()`, persisted in `alert_events` (v9).
  SSE broadcast was documented but never wired.
- `dal/bills.py::get_upcoming_bills` — returns `overdue` / `due_soon` / `upcoming`
  rows, never consumed by a notification producer.
- `backend/routers/documents.py::pending_nudges` — inline SQL evaluated at
  request time (no DAL layer), polled by `DocumentNudge.tsx`; dismissal in
  `localStorage` only.
- `backend/refresh_orchestrator.py` — captures per-institution failures into
  `institution_refresh_status` but never emits a persistent notification.
- `Header.tsx:145-164` — empty popover stub with a TODO comment.
- No `notifications` table, no persistent dismissal model.

## Task

### 1. Schema — `dal/migrations/v38_notifications.py`

`notifications` table: `id`, `type` (5-enum), `severity` (3-enum), `title`,
`body`, `payload_json`, `link`, `dedup_key UNIQUE`, `created_at`, `read_at`,
`dismissed_at`. Partial index `idx_notifications_active` on
`(created_at DESC, id DESC) WHERE dismissed_at IS NULL`.

`CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` — fully idempotent.

### 2. DAL — `dal/notifications.py`

- `record_notification(conn, *, type, title, dedup_key, ...)` → `int | None`
  — `INSERT OR IGNORE`; returns row id or None on dedup collision.
- `list_notifications(conn, *, include_dismissed, limit)` → ordered
  `created_at DESC, id DESC`, `payload_json` decoded inline to `payload`.
- `get_unread_count(conn)` — counts `dismissed_at IS NULL AND read_at IS NULL`.
- `mark_read(conn, ids=None)` — `ids=None` marks all unread; specific list marks
  only those. Returns rowcount. Caller commits.
- `dismiss(conn, ids)` — sets `dismissed_at`. Caller commits.

Invariants via private `_assert_valid`: `type` ∈ `VALID_TYPES`, `severity` ∈
`VALID_SEVERITIES`, non-empty `dedup_key`, JSON-serializable `payload`.

### 3. DAL helper — `dal/documents.py`

`get_pending_nudges(conn, as_of=None)` — moves the inline SQL from
`backend/routers/documents.py::pending_nudges` into the DAL so both the router
and the notification producer can call it. Accepts `as_of: date` for testability
(avoids patching `date.today()`).

### 4. Router — `backend/routers/notifications.py`

```
GET  /api/notifications?include_dismissed=false&limit=50
GET  /api/notifications/unread-count
POST /api/notifications/mark-read  body: {ids?: int[]}   # omit = all
POST /api/notifications/dismiss     body: {ids: int[]}
```

Mounted in `backend/api_server.py` alongside the other routers. `IdsBody` and
`DismissBody` Pydantic models. Thin handlers, `with get_db() as conn:`,
explicit `conn.commit()` after mutations.

### 5. Producers

**Successful-refresh path** — new `_notifications()` step added at the tail of
`result_writer.py::run_post_commit_pipeline` (after `_goals`). Captures the
`fired` list from the prior `_alerts()` step via closure. Emits:
- Budget/large-txn/balance-low alerts from `fired` (type `budget_alert`, dedup
  `alert:{rule_id}:{context-fields}`).
- Overdue + due-soon bills from `dal.bills.get_upcoming_bills(conn, days=7)`
  (types `bill_overdue` / `bill_due_soon`, dedup `{type}:{id}:{next_expected}`).
- Doc-drop nudges from `dal.documents.get_pending_nudges(conn)` (type
  `doc_drop_nudge`, dedup `doc_drop:{institution}:{ym}`).
- `conn.commit()` only if `count > 0`.

**Failed-refresh path** — added inside the `with get_db() as conn:` block in
`refresh_orchestrator.py::RefreshSession._run_institution`, after
`update_institution_status(success=False, ...)`, guarded by
`if final_state == InstitutionState.FAILED.value`. Wrapped in `try/except` so a
notification failure can't break the orchestrator. Dedup on
`refresh_failure:{institution}:{event_id}`.

### 6. Frontend — `NotificationPopover.tsx`

`frontend/src/components/Notifications/NotificationPopover.tsx` — standalone
component rendered from `Header.tsx` replacing the inline stub.

Props: `open: boolean`, `onToggle: () => void`, `onClose: () => void`.

- `useUnreadCount()` internal hook: polls `/api/notifications/unread-count`
  every 60 s, updates badge on the bell.
- Feed: `useApi('/api/notifications', { skip: !open })`.
- On open: fire-and-forget `POST /api/notifications/mark-read` (no ids = mark
  all); zeros badge locally.
- Per-row dismiss: optimistic splice + `POST /api/notifications/dismiss`.
- Severity color: `text-muted-foreground` / `text-warning` / `text-loss`.
- Type icon (material-symbols): `sync_problem` / `pie_chart` / `schedule` /
  `alarm` / `description`.
- Unread rows: `bg-primary/5` highlight; bold title.
- Empty state: existing `notifications_off` icon + "No notifications".
- Dismiss button: per-row, opacity-0 → group-hover:opacity-100.
- All Ember tokens; no emerald.

`Header.tsx` strips the inline 20-line stub and imports `NotificationPopover`,
passing `open={showNotifications}`, `onToggle`, `onClose`.

## Verification

1. `pytest tests/ -x --tb=short` → 423 passed (32 new tests).
2. `npm run build` → green.
3. `python scripts/pii_scan.py --all-tracked` → clean.
4. Migration smoke: v38 applies cleanly on fresh DB (table + index land) and
   on the end_date=2026-04-24 dummy DB.
5. Dev-server walkthrough:
   - Bell opens: "Notifications" heading + "No notifications" empty state (DB
     starts empty in demo mode).
   - `GET /api/notifications` → `{"notifications": []}`.
   - After a dummy-data advance: `_notifications()` step populates the table
     if any bills are overdue or doc-drop nudges are pending; bell shows rows.
   - Popover snapshot: heading at [1870], empty-state at [1878] → confirmed.
6. No console errors.

## Outcomes (2026-04-24)

Shipped as described above. One pre-existing test was updated alongside:
`test_t02_document_drop.py::test_pending_nudges_suppressed_before_5th` patched
`backend.routers.documents.date` which no longer exists after the DAL
extraction. Updated to call `get_pending_nudges(conn, as_of=date(2026,3,3))`
directly — simpler and avoids import coupling.

Deferred to T02: APY rate-change detector (`dal/apy_history.py` has no
"changed since last snapshot" function); recurring price-mutation surfacing
(`recurring_mutations` table exists but no notification producer).

Deferred to T03: SSE push on notification insert (would need a formal SSE topic
registry; polling at 60 s is acceptable for v1).
