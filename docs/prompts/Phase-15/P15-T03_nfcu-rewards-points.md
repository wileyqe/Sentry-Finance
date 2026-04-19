# P15-T03: NFCU Rewards Points Tracking

## Context

Phase 15 ("Decision Support Features") opened on 2026-04-18 with T01
and T02 (mortgage simulator, TSP switch/stay) deferred. T03 is the
low-engineering-risk / high-signal piece: surface the NFCU
cashRewards points balance already accessible on the card detail
page so the user can answer "how many points am I sitting on that I
haven't redeemed?"

The pattern intentionally matches P4-T03 (Affirm APY): extend the
existing key-value `loan_details` table rather than add a new
time-series table. The user's clarifying answer on storage shape:
the generic key-value (latest-wins) path is enough for the question
this task answers. Trend visibility and redemption-gap alerts are
deferred to Phase 16.

## Starting State

- `extractors/nfcu_connector.py` (L940–970) already has
  `rewards_points` in its `field_patterns` dict and iterates over
  `acct.loan_details` to extract each configured field via
  `_extract_field_value`.
- `accounts.yaml` already lists `rewards_points` in the export
  config for the NFCU credit card (`0837`), so the extractor
  actually fires on every refresh.
- `backend/result_writer.py` (L204–210) already persists every
  `loan_details` key emitted by a connector through
  `dal.balances.record_loan_details`, so the storage path is
  already correct. No connector or DAL change was required.
- `backend/routers/accounts.py` (L95–108) already pivots
  `loan_details` into structured columns per account
  (`purchase_price`, `interest_rate`, `credit_limit`, etc.) but
  did not include `rewards_points` in the pivot SQL.
- The generic `GET /api/accounts/{id}/details` endpoint in
  `backend/routers/reports.py` (L87–108) already returns every
  `loan_details` field — no endpoint work needed either.
- `frontend/src/pages/AccountsPage.tsx` renders the account-card
  metadata row with `last4`, freshness dot, APR, and synthetic
  badge, but had no rewards surface.
- `scripts/seed_dummy_data.py` had no `rewards_points` seeding, so
  a freshly seeded clone would render no rewards chip even after
  the wiring was complete.

## Task

### 1. Backend pivot (accounts router)

Add `rewards_points` to the `loan_details` pivot SQL in
`backend/routers/accounts.py`:

```sql
MAX(CASE WHEN field_name='rewards_points' THEN field_value END) AS rewards_points
```

Use `field_value` (raw TEXT, not CAST) because the NFCU scrape can
return comma-formatted strings like `"12,400"`. Assign the pivoted
value onto each account dict in the enrichment loop:

```python
acct["rewards_points"] = ld.get("rewards_points")
```

### 2. Frontend chip (Accounts page)

On each credit-card account card in
`frontend/src/pages/AccountsPage.tsx`, after the APR chip and before
the `SyntheticBadge`, render an amber rewards chip when
`account.rewards_points` parses to a finite integer. Use
`parseInt(String(raw).replace(/,/g, ''), 10)` so both `"12,400"`
(NFCU format) and `"8450"` (seeder format) render as `12,400 pts` /
`8,450 pts`. Hide the chip entirely (don't render `0 pts`) when the
field is missing — a missing field means "never scraped," not
"zero."

### 3. Seeder

Add `seed_credit_card_rewards(conn, end_date)` to
`scripts/seed_dummy_data.py` and call it from `main()` right after
`seed_loan_details`. Stamp `summit_cc_3341` (the NFCU-proxy card)
with a single `rewards_points` row via `record_loan_details`. Skip
`coastal_cc_8847` (Chase proxy) so the seeded state mirrors the
real config where only NFCU scrapes rewards today (Chase card
detail scraping is tracked separately as P15-T05).

Wipe prior seeded rewards rows with
`DELETE FROM loan_details WHERE field_name='rewards_points' AND
refresh_run_id='dummy_seed'` so re-runs stay deterministic.

### 4. Tests

Create `tests/test_rewards_points.py` covering:

- `record_loan_details` persists a rewards row into `loan_details`.
- `get_latest_loan_details` surfaces `rewards_points` alongside
  `purchase_apr`.
- The accounts-router pivot SQL (copied into the test as a
  reference constant) exposes `rewards_points` as a real column
  when a row exists.
- The pivot returns `NULL` when no `rewards_points` row exists.
- Latest-row-wins semantics hold when two snapshots have different
  rewards values.

No new DAL module is added, so there is no invariant-test suite.
`test_golden_seed.py` does not need re-baselining — the seeder
change adds one static row outside the RNG-driven transaction
stream, so the fingerprint `a4ad2cd6f00f` stays stable.

## Verification

- `pytest tests/test_rewards_points.py -x --tb=short` — 5 / 5
  passing.
- `pytest tests/ -x --tb=short` — 251 / 251 passing (full backend
  suite required per CLAUDE.md connector-change rule).
- `python scripts/seed_dummy_data.py` completes cleanly, with
  `summit_cc_3341` holding one `rewards_points` row in
  `loan_details`.
- Accounts page renders an amber `🎁 8,450 pts` chip on the NFCU
  CC card in the seeded clone; Coastal / non-CC cards render
  nothing (no false zero).
- Live NFCU refresh writes the card's `rewards_points` value
  through the existing `record_loan_details` path (no connector
  change was needed — verified by tracing the config → extractor →
  `result_writer.persist_connector_result` path).

## Files Modified

- `backend/routers/accounts.py` — two lines added to the pivot SQL
  and enrichment loop.
- `frontend/src/pages/AccountsPage.tsx` — rewards chip inline in
  the account-card metadata row.
- `scripts/seed_dummy_data.py` — new `seed_credit_card_rewards`
  function + call site.
- `tests/test_rewards_points.py` — new, 5 tests.
- `docs/prompts/Phase-15/P15-T03_nfcu-rewards-points.md` — this
  file.
- `docs/ROADMAP.md` — T03 flipped to `[v]`.

## Out of Scope

- Chase credit-card detail scraping (T05) — the Chase card is not a
  rewards card per the user, but all other card detail fields (APR,
  credit limit, min payment, due date, statement balance) still
  need scraping scaffolding built. That is T05's job.
- Frontend "Account Details" subsection (T06) — surfaces every
  scraped detail in a consistent per-account panel. T03 only
  renders the compact rewards chip in the metadata row.
- Rewards redemption-gap alerts — belong to Phase 16 (notification
  feed producers) once that phase is active.
- Rewards trend charting — user chose key-value storage over a
  time-series table, which deliberately punts on trend. Revisit if
  the need surfaces later.
