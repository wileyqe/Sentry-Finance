# P15-T07: APY History Sparkline on Account Details Panel

## Context

P15-T06 shipped the Account Details panel (`AccountDetailsPanel.tsx`)
with a single-line APY hero row — users see *what the rate is* but not
*whether it's moving*. The `apy_history` table (v30, P15-T04 Phase B)
already holds 36 months of deterministic drift across Summit
checking/savings, Affirm, and other eligible accounts, and
`dal.apy_history.get_apy_history(conn, account_id, months=12)` has been
in place the whole time. T07 surfaces that series as a small inline
sparkline + plain-language direction annotation, so one glance tells
the user whether the rate is rising, falling, flat, and roughly when
it last moved.

## Starting State

**Backend:**
- `/api/accounts/{account_id}/details` in
  [backend/routers/reports.py:96][reports.py] returned
  `{account_id, details, apy_latest}`. `apy_latest` came from
  `get_latest_apy`; `get_apy_history` was unused by the handler.
- DAL `get_apy_history` ([dal/apy_history.py:119][apy-history-dal])
  already returns rows ascending by `as_of` with an optional
  `months` window. No DAL changes required.

**Frontend:**
- `AccountDetailsPanel.tsx` rendered a hero row (APY label + rate
  value + `as_of · source` footer) at lines 190–202. No chart.
- No reusable sparkline component existed; the only inline-SVG
  sparkline precedent was the cumulative-spend chart on
  `DashboardPage.tsx:877` (a `<path>` inside a fixed viewBox).
- `recharts` is installed but oversized for a 32px-tall chart
  without axes/tooltip/legend; `@tremor/react` is used only by the
  dashboard.
- Frontend has **no** test runner configured (confirmed via
  `frontend/package.json`).

**Seeded data (deterministic, end_date=2026-01-15):**
- `generate_apy_history` produces ~36 rows per APY-eligible
  account over a rolling 3-year window with plausible drift.
- `summit_chk`, `summit_sav`, `affirm_bnpl`, `summit_mtg` — have
  enough history to render the sparkline.

## Task

1. **Backend: extend the handler.** Add one call to
   `get_apy_history(conn, account_id, months=12)` inside the
   existing `with get_db()` block, strip the DAL rows to
   `{apy_rate, as_of}`, and ship them on the response under a new
   `apy_history` key. Always return a list (never `null`).
2. **Backend tests.** Add three cases to
   `tests/test_accounts_details_endpoint.py`:
   - `test_account_details_includes_apy_history_ascending` —
     seeds rows out of order, asserts ascending response order and
     wire-minimal `{apy_rate, as_of}` shape.
   - `test_account_details_empty_apy_history_returns_list` —
     absence returns `[]`, not `null`, not missing key.
   - `test_account_details_apy_history_respects_12_month_window` —
     seeds 15 months, asserts the handler caps at ~12. (Bounded
     range asserted, not exact count — SQLite's `-12 months`
     arithmetic has a boundary-inclusive quirk that varies by the
     day of the month.)
3. **Frontend: `Sparkline` component** at
   `frontend/src/components/charts/Sparkline.tsx`. Inline SVG,
   fixed viewBox, `<path>`-based, trailing dot at the last point,
   normalized to `[2, height-2]` so a perfectly flat series still
   renders a visible mid-height line. Renders `null` if fewer than
   two finite values are supplied — the caller doesn't need a
   length guard.
4. **Frontend: `apyTrend` helper** at
   `frontend/src/lib/apyTrend.ts`. Pure functions:
   - `computeApyTrend(history)` → `{direction, delta,
     lastChangeAsOf, firstAsOf, latestRate}` or `null` for
     `< 2` points. `direction` is `"flat"` when
     `|delta| < 0.0005%` (half a basis point — guards against
     float-compare noise).
   - `directionSentiment(direction, accountType)` →
     `"good"|"bad"|"neutral"`. Maps up/down to sentiment based on
     whether the account is an asset (savings, checking) or a
     liability (credit cards, loans, mortgage, auto, BNPL).
   - `formatTrendAnnotation(trend, formatMonthYear)` → plain-language
     copy: `↑ Up 0.10% since April 2025`, `↓ Down 0.05% since …`,
     `Unchanged over the last 12 months`, or `Unchanged since
     March 2026` when the rate moved then stabilized.
5. **Frontend: wire the trend card** in
   `AccountDetailsPanel.tsx`. Same outer hero-card container;
   inside, keep the existing label + rate + footer on the first
   row, and add a second row with the sparkline + annotation only
   when `computeApyTrend(apy_history)` returns non-null. Color is
   driven by `directionSentiment`:
   - Asset + up → `var(--color-gain)`; asset + down →
     `var(--color-loss)`.
   - Liability + up → `var(--color-loss)`; liability + down →
     `var(--color-gain)`.
   - Flat → neutral muted foreground; no arrow glyph.

## Verification

- `pytest tests/test_accounts_details_endpoint.py -v` → 8/8 pass
  (5 from T06 + 3 new).
- `pytest tests/ -x --tb=short` → full suite green, no regression
  in the ~300-test baseline T06 left behind.
- `cd frontend && npm run build` → clean TypeScript build.
- `python scripts/pii_scan.py --all-tracked` → clean (no new PII
  surface; sparkline values are numeric rates already exposed by
  `apy_latest`).
- **Dev-server walkthrough** (seeded DB, Quintin view, Accounts
  page):
  - Expand `summit_sav` / `summit_chk` — trend card renders below
    the existing APY row; sparkline colored by asset sentiment;
    annotation reads "Up N.NN% since {Month Year}" or similar.
  - Expand `affirm_bnpl` — liability + rising APY ⇒ red up arrow.
  - Expand an account with `< 2` APY rows — card falls back to the
    original single-line hero; no sparkline, no annotation.
  - Amy view — still empty-state; no trend cards render.

## Out of Scope

- No new SSE events, no schema migrations, no DAL changes.
- **No relocation of the `/details` handler out of `reports.py`**
  — the backlog item "Move `/api/accounts/{id}/details` handler to
  `accounts.py` + route through DAL" (ROADMAP) explicitly says
  "do not bundle with unrelated feature work." The handler stays
  where it lives for now.
- No frontend unit tests — no runner is configured, and matching
  the T06 precedent keeps setup cost out of the task.
- No sparkline additions elsewhere in the app (credit-score
  history, budget burn-down) — T07 is scoped to the APY card.

## Outcomes

- **SQLite `-12 months` boundary is squishy.** The month-window
  test uses a bounded-range assertion (`11 ≤ len ≤ 13`) because
  SQLite's `date('now', '-12 months')` treats the boundary day
  inclusively and month-length varies. Exact-count assertions would
  flake by calendar day; the drop-oldest-three signal is what the
  test actually cares about.
- **Inline SVG over recharts.** recharts' `<ResponsiveContainer>`
  misbehaves at 32–40px heights, and the `<LineChart>` primitive
  drags in axis/legend machinery we explicitly don't want. A
  20-line `<path>`-based component matches the Dashboard spend
  sparkline precedent and has zero bundle cost.
- **Sentiment flip, not color fix.** Treating "up = good"
  universally would be actively misleading on credit cards and
  loans where a rising APR is bad. The sentiment helper puts the
  asset/liability split in one place so the rule lives in code,
  not in each caller.
- **Half-basis-point flat threshold.** `0.0005%` is the smallest
  change the UI rounds away to (APY is rendered as `N.NN%`). Any
  tighter and seeded floats wiggle into false "moved" states;
  looser and real 1bp changes get swallowed as "flat."

[reports.py]: /backend/routers/reports.py
[apy-history-dal]: /dal/apy_history.py
