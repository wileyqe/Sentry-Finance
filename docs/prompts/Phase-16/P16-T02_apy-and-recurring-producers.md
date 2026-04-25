# P16-T02 — APY rate-change + recurring price-mutation producers

**Status:** `[v]` Shipped 2026-04-25 on `feat/p16-t02-t03-producers-and-sse`.

## Goal

Fill the two missing notification producers called out in the Phase 16
charter: surface APY rate changes (so a HYSA going 3.50% → 4.25% lands in
the bell), and surface recurring-subscription price drift (so a Netflix
$15.49 → $17.99 jump lands too). Both data sources already existed —
`apy_history` (v30) and `recurring_mutations` (v07) — but nothing read
from them with the intent of telling the user.

## Locked scope decisions

Confirmed with user during the planning conversation that produced this
PR:

- **APY threshold:** ≥5 basis points (0.05% absolute Δ) to fire at all.
  Severity `info` when |Δ| < 0.25%, `warning` when |Δ| ≥ 0.25%.
  Direction-agnostic — both rate cuts and rate increases fire.
- **Recurring mutation severity:** always `warning`. Price changes always
  matter; `recurring_mutations` is already noise-floor-gated by
  `detect_recurring`'s 2% delta requirement at the *write* layer
  (`dal/recurring.py:220`), so any row that exists is already
  user-relevant.
- **No new "seen" flag** on `recurring_mutations`. The notification
  `dedup_key` (`recurring_mutation:{mutation_id}`) does the work via
  `INSERT OR IGNORE`, matching the established producer pattern.
- **No new migration.** Both source tables exist; only `VALID_TYPES`
  expands.

## What landed

### Backend

- **`dal/apy_history.detect_apy_changes(conn, threshold_pct=0.05,
  warning_threshold_pct=0.25)`** — new helper. One SELECT joins
  `apy_history` with `accounts` for the friendly name, ordered
  `account_id ASC, as_of DESC, id DESC`. The detector groups in Python
  (history per account is bounded — at most one APY scrape per day
  per account), then per account walks `history[1:]` to find the first
  row whose `apy_rate` differs from the latest. Skips accounts with
  fewer than two rows or where every prior row matches the latest rate.
  Returns one record per qualifying account with `account_id`,
  `account_name`, `old_rate`, `new_rate`, `as_of`, signed `delta`,
  and pre-classified `severity`.
- **`dal/recurring.list_all_mutations(conn)`** — joins
  `recurring_mutations` with parent `recurring_transactions` so the
  producer has merchant + category in one read. Newest-first order.
- **`backend/result_writer._notifications()`** — two new producer
  steps appended after the existing four (alerts → bills → doc-drop
  nudges → APY → mutations). APY emits with title
  `"{acct} APY ↑/↓ {old}% → {new}%"` (arrow follows signed delta) and
  body `"↑/↓ {bp} bp change as of {as_of}"`; dedup keyed
  `apy_change:{account_id}:{new_rate:.4f}:{as_of}`. Mutation emits
  with title `"{merchant} price ↑/↓ ${old} → ${new}"`; dedup keyed
  `recurring_mutation:{mutation_id}`.
- **`dal/notifications.VALID_TYPES`** — extended with
  `apy_rate_change` and `recurring_price_mutation`.

### Frontend

- **`NotificationPopover.tsx`** — `NotifType` union extended with the
  two new types; `TYPE_ICON` map gained `percent` (apy_rate_change)
  and `price_change` (recurring_price_mutation). Severity coloring
  inherits the existing map (info=muted, warning=text-warning,
  critical=text-loss).

### Tests (11 new, all green)

- `tests/test_apy_change_producer.py` — 8 cases:
  - single APY row → no change emitted
  - all rows same rate → no change emitted
  - 4 bp change (below 5 bp floor) → no change emitted
  - 10 bp change → severity `info`
  - 75 bp change → severity `warning`
  - rate cut → fires direction-agnostic
  - history with intermediate duplicates → walks past to find the
    first *different* prior rate
  - producer dedup: re-running detect→record on the same data does not
    duplicate the notification row
- `tests/test_recurring_mutation_producer.py` — 3 cases:
  - `list_all_mutations` joins parent merchant correctly
  - producer emits one notification per mutation
  - dedup_key blocks double-fire on second pipeline run

## Verification evidence

- Full backend suite: 435 passed, 2 failed. The two failures
  (`test_bill_due_soon_emits_notification`,
  `test_upcoming_bill_does_not_emit`) are pre-existing date-arithmetic
  flakes on `main` — confirmed by stashing changes and re-running.
  Unrelated to P16-T02 / T03.
- `python scripts/pii_scan.py --all-tracked` → clean.
- `cd frontend && npm run build` → green (1,319 kB main bundle, no
  new type errors).
- Dev-server walkthrough: hand-injected an APY change row
  (`apy_change:summit_savings:4.2500:2026-04-24`,
  3.50 → 4.25, severity warning), reloaded bell — badge updated 22 →
  23, popover rendered the row with the new `percent` icon, title
  `"Summit Savings APY ↑ 3.50% → 4.25%"`, body `"↑ 75 bp change as of
  2026-04-24"`. Click navigated to `/accounts`. (The DAL-side
  broadcast fired in the script's process, not the running uvicorn
  process — that part of the path is covered by P16-T03 unit tests
  and a separate dev-server pass with an in-process trigger.)

## Surprises / follow-ups

- The seeder produces 72 deterministic APY rows over 36 months but
  the rates oscillate by design — `detect_apy_changes` will pick up
  every transition once it runs against the seeded data. That's
  desirable for showing the bell in dev, but means the first refresh
  after this lands will emit a burst of `apy_rate_change`
  notifications. Acceptable: each is a one-time event that
  dedup_key suppresses on subsequent runs.
- The `dedup_key` for APY uses `f"{new_rate:.4f}:{as_of}"`. Two
  different deltas landing on the same date with the same new rate
  (improbable in practice — APY history is single-source-per-day)
  would dedup to one notification. Documented here in case a future
  multi-source scrape revives the question.
- `list_all_mutations` returns the full table on every refresh. Cheap
  today (mutation rows are rare), but if the table grows large
  consider gating on `detected_at` since the previous run.
