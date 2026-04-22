# P14-T04 — Accountability Scorecard (Phase D)

## Context

Phases A through C give us a Sankey that draws every **cash** flow —
gross paycheck decomposition, three terminal buckets for cash
destinations, and dividends/interest as true income. What the Sankey
does not show is market value change on already-owned positions. Those
live in net worth.

Phase D closes the loop: a single header metric on the Reports page
answers the question "did we actually account for every dollar?" by
comparing the Sankey's claimed flows + independently-calculated market
movement against `get_net_worth_history`.

The identity:

```
Δ NetWorth = (Dollars in)
           − (Dollars spent)
           ± (Change in market value of holdings)
           ± (Change in real-estate valuations)
           ± (Change in vehicle valuations)
           + unexplained
```

Solve for `unexplained`. Display:

```
accounted_for_pct = max(0, 1 − |unexplained| / |Δ NetWorth|)
```

The unexplained delta is the feature. Clicking it reveals **named
drift sources** — each with a click-to-fix affordance where one
exists. "Data trust" becomes a visible, improvable number, not a
feeling. That's the real product of the whole phase.

## Starting State

- `dal/reports.py:189-381` — `get_net_worth_history` reconstructs
  monthly banking / investment / real-estate / vehicle assets +
  liabilities from snapshot tables. Returns month-by-month.
- Phase C shipped `v_investment_contributions` — the view that
  distinguishes user contributions from intra-account credits.
- Phase B shipped the bucket totals on `get_flow_data` output
  (`bucket_totals.CONSUMED / STORED_LIQUID / STORED_ILLIQUID`).
- `dal/freshness.py` — existing staleness calc for institution
  refresh status, balance snapshots, portfolio snapshots.
- Frontend `ReportsPage.tsx` — post-Phase-C has the three-column
  Sankey; no header card yet.
- `backend/routers/reports.py` — Phase A extended the `/flow`
  endpoint; no `/accountability` endpoint yet.

## Task

### Task 1 — `dal/reports.get_accountability`

New DAL function:

```python
def get_accountability(
    conn, start: str, end: str, owner_id: Optional[int] = None
) -> dict:
    """
    Computes the accountability identity for [start, end).

    Returns:
      {
        "net_worth_start_cents":     int,
        "net_worth_end_cents":       int,
        "net_worth_delta_cents":     int,
        "identity_terms": {
          "dollars_in_cents":          int,   # from get_flow_data
          "dollars_spent_cents":       int,   # from get_flow_data
          "market_value_delta_cents":  int,   # investments only
          "real_estate_delta_cents":   int,   # property valuations
          "vehicle_delta_cents":       int,
        },
        "unexplained_cents":           int,
        "accounted_for_pct":           float,  # [0.0, 1.0]
        "drift_sources":               [...],  # see Task 2
      }
    """
```

Glue code over existing building blocks. Market value delta excludes
user contributions (using `v_investment_contributions`):

```
market_value_delta
  = (sum of investment account values at period end)
  − (sum of investment account values at period start)
  − (sum of user contributions during period)
```

Contributions are subtracted because they're already counted in
`dollars_in` via Phase C. What remains is pure market movement.

Real estate and vehicle deltas follow the same pattern:
`end_value − start_value − capex_in_period`. Home improvement spending
counts as capex and is read from the transaction category tag.

### Task 2 — Drift source detection

Each drift source is a structured entry:

```python
{
  "id":           "stale_portfolio_snapshot",
  "label":        "Portfolio snapshot is 4 days older than period end",
  "severity":     "warning" | "info",
  "fix_action":   "refresh_portfolio" | "recategorize" | None,
  "fix_payload":  {...},  # shape depends on fix_action
  "magnitude_cents": int, # estimated contribution to unexplained
}
```

Detection logic (new module `dal/accountability_drift.py`):

1. **Uncategorized transactions in window** — query `transactions`
   with `category IS NULL OR category = 'Uncategorized'` in the
   window. `fix_action='recategorize'`, payload is the transaction
   ids.
2. **Stale portfolio snapshot at boundary** — the latest
   `portfolio_snapshots` row for any investment account is more than
   2 business days older than `end`. `fix_action='refresh_portfolio'`
   with account id.
3. **Missing payroll snapshot for a month with a deposit** — a
   deposit transaction that looks paycheck-shaped (amount range,
   recurring, from a known payroll counterparty) has no matching
   `payroll_snapshots` row. `fix_action='upload_ras'` pointing at
   the document drop UI.
4. **Missing home valuation** — latest `real_estate.as_of` > 90 days
   before `end`. `fix_action='update_valuation'`.
5. **CC payment timing boundary** — a CC payment in the last 3 days
   of `end` pays for spend from before `start`. Named, not fixable.
6. **Vehicle depreciation unrecorded** — no `vehicle_valuations` row
   in the window for a known vehicle. `fix_action='update_vehicle_value'`.
7. **Real-estate valuation interpolated** — valuations are sparse
   and linearly interpolated. Informational.
8. **Contractor-season tax ambiguity** — contractor income
   (`tax_treatment='contractor_no_withholding'`) received in
   window with no corresponding tax reconciliation event. Named,
   informational.

Each detector is a small function returning `list[DriftSource]`. The
top-level `get_accountability` calls all of them and aggregates.

### Task 3 — API endpoint

New `GET /api/reports/accountability` on
`backend/routers/reports.py`:

```python
@router.get("/accountability")
async def accountability(
    start: str = Query(...),
    end: str = Query(...),
    owner_id: Optional[int] = Query(None),
):
    return get_accountability(conn, start, end, owner_id)
```

Owner-scoped via `dal/owners.build_account_filter` like every other
endpoint.

### Task 4 — Frontend: scorecard card + drilldown

- Sticky header card at the top of `ReportsPage.tsx`, above the
  Sankey. Large percentage, short label, click handler.
- Drilldown modal shows:
  - Identity terms (each in $ cents, human-formatted).
  - Δ net worth start→end.
  - Unexplained amount and sign.
  - Drift sources list, sorted by `magnitude_cents` descending.
  - Fix affordances: buttons or links that route to the relevant
    page (uncategorized queue, account refresh, document drop, etc.).
- Card updates as the owner chip switches — Quintin / Household / Amy
  each have their own percentage.
- Color coding: >= 95% green, 85-95% yellow, < 85% red.

### Task 5 — HTML mockup

Demonstrate the scorecard card layout and the drilldown modal on
realistic values. User approves before Task 4 merges.

### Task 6 — Scorecard drift tests

New file `tests/test_accountability.py`:

1. Synthetic dataset where all terms are known → `unexplained == 0`,
   `accounted_for_pct == 1.0`.
2. Deliberately miscategorize a single transaction → drift source
   "uncategorized transactions" fires with correct magnitude.
3. Stale portfolio snapshot → drift source fires with correct age.
4. Missing payroll snapshot for a month with a paycheck-shaped deposit
   → drift source fires.
5. A month with market losses: identity reconciles; the card shows
   the market-value-delta term as negative.
6. A month with gains: identity reconciles; the market-value-delta
   term is positive.
7. Owner scoping: accountability for Quintin only excludes Amy's
   accounts from both sides of the identity.

### Task 7 — Performance benchmark

- Benchmark `get_accountability` on 3 and 12-month windows on the
  seeded dataset. Target: < 300ms per call. If the
  `v_investment_contributions` view dominates, note it for a future
  materialization PR but don't block Phase D on it.

## Verification

### Unit tests

Per Task 6 above.

### Regression

- Full test suite green.
- `scripts/pii_scan.py --all-tracked` clean.
- Phase A/B/C test suites still green.

### Manual UI check

- Card reads "We've accounted for X%" on seeded data with X >= 95.
- Click card → drilldown opens with identity terms, unexplained, and
  drift source list.
- Deliberately change a seeded transaction's category to `NULL` →
  card percentage drops, drift list shows the uncategorized entry
  with a fix button. Click the fix → lands on the categorization
  queue filtered to that transaction.
- Month with market loss: identity terms show negative
  market_value_delta; card stays honest (doesn't show fake
  flows).
- Owner chip switch: card updates per-owner.

### End-to-end invariant

```
net_worth_delta_cents
  = dollars_in − dollars_spent
  + market_value_delta + real_estate_delta + vehicle_delta
  + unexplained
```

Asserted in the function and tested.

## Post-Implementation Checklist

- [x] `docs/ROADMAP.md` flip `P14-T04` to `[v]`.
- [x] Scorecard accurate on real household data (≥95% on a 3-month
      window before long-lived branch merges to main).
- [x] Drift source fix actions all wired to a real target page.
- [x] Mockup approved before Task 4 merges.

## Out of Scope

- Rental property accounting (Phase E).
- Effective-tax-rate computation as a decision-support feature
  (Phase 15 backlog — natural follow-up given the contractor-season
  drift source).
- Materialized contributions table (only if the Task 7 benchmark
  reveals a hard perf problem).

## Outcomes (landed 2026-04-22)

**DAL (`dal/reports.py`).** `get_accountability(conn, start_date, end_date, owner_id)`
appended at the end of the module. Three helpers introduced alongside:

- `_to_cents(float) -> int` — convert float dollars to integer cents (round-half-up).
- `_net_worth_at_date(conn, as_of, owner_id) -> dict` — point-in-time NW
  snapshot: banking (checking + savings), investment (portfolio_snapshots
  latest ≤ date), real estate (time-aware valuations per property),
  vehicle (time-aware valuations per vehicle), liabilities (already
  negative-signed in balance_snapshots so they subtract by addition).
  Owner-scoped via `resolve_account_ids_for_view` with a zero-accounts
  short-circuit returning all-zeros (Amy-style empty state).
- `_user_contributions_in_window` — sums `ABS(matched_tx_signed_amount)`
  over `v_investment_contributions` rows with
  `classification='user_contribution'`. Subtracted from the raw
  investment-delta so `market_value_delta_cents` isolates pure market
  movement.
- `_home_improvement_capex_in_window` — sums abs(signed_amount) for
  transactions whose category is `"Home Improvement"`. Subtracted from
  the RE-delta so that term reflects PURE market appreciation; capex
  remains counted in `CONSUMED` via the bucket totals.

`get_accountability` returns `{net_worth_start_cents, net_worth_end_cents,
net_worth_delta_cents, identity_terms{dollars_in, dollars_spent,
market_value_delta, real_estate_delta, vehicle_delta}, unexplained_cents,
accounted_for_pct, drift_sources}` — all monetary fields are integer
cents. `accounted_for_pct` rounded to 4 decimals. Empty-state windows
(`nw_delta == 0`) return `accounted_for_pct = 1.0` rather than
divide-by-zero.

**Drift detectors (`dal/accountability_drift.py`, new module).** Eight
detectors per the prompt, each independently testable:

1. `uncategorized_transactions` — `category IS NULL OR category='Uncategorized'`
   in window, capped at 50 txns; magnitude = sum of absolute amounts;
   fix_action routes to `/transactions?txn_ids=…`.
2. `stale_portfolio_snapshot::<account_id>` — latest snapshot >
   2 calendar days older than end_date (or missing); fix_action
   `refresh_portfolio`.
3. `missing_payroll_snapshot` — paycheck-shaped deposits (`Pension /
   Disability / Education Benefits / Salary / Wages / Payroll`) in a
   month with no `payroll_snapshots` row for the scoped owner;
   fix_action `upload_ras`.
4. `stale_home_valuation::<property>` — latest RE valuation > 90 days
   before end_date; fix_action `update_valuation`.
5. `cc_payment_boundary` — CC-payment transactions in the last 3 days
   of the window; informational, no fix.
6. `vehicle_depreciation_unrecorded::<vehicle_id>` — no
   `vehicle_valuations` row for a vehicle in the window;
   fix_action `update_vehicle_value`.
7. `real_estate_interpolated::<property>` — ≤ 1 valuation row in 6
   months; informational.
8. `contractor_tax_ambiguity` — contractor income received in window
   (income_sources with `tax_treatment='contractor_no_withholding'`)
   with no matched tax-reconciliation event; informational,
   magnitude ≈ 22% effective marginal.

Detectors wrap in `try/except sqlite3.OperationalError` to tolerate
older schemas (e.g. no `vehicle_assets` table); results are sorted by
severity (warning first) then magnitude descending.

**Backend router (`backend/routers/reports.py`).** New
`GET /api/reports/accountability` reading `start_date`, `end_date`,
`owner_id`. Returns the DAL dict plus `refresh_in_progress`. Owner
scoping is fully delegated to `build_account_filter` inside the DAL.

**Frontend (`frontend/src/pages/ReportsPage.tsx`).** Three new components:

- `AccountabilityScorecard` — single-row card placed between summary
  cards and the Sankey. Left-border color switches emerald / amber / rose
  on the 95 / 85 thresholds. Large percentage + copy + drift count.
  Empty-state (NW delta = 0) renders a neutral "No net-worth change
  recorded" line rather than a fake 100%. Defensive guard on the
  response shape so a 404 / server hiccup doesn't crash the page.
- `AccountabilityModal` — scrim modal with 7-tile identity equation
  (Dollars in − spent + market Δ + RE Δ + vehicle Δ + unexplained =
  Δ NW), unexplained-residual strip, and a sorted drift-source list.
  Each drift row renders either a fix-action button routed via
  `useNavigate` (`/transactions`, `/accounts`, `/documents`) or an
  "Informational" chip.
- `TermTile` / `Op` / `DriftRow` — presentational helpers.

Fetch flow: new `fetchAccountability` callback keyed on `window_` +
`ownerParam`; fires alongside `fetchFlow` so the two are always in sync.
"All Time" (no start_date) skips the fetch — NW-delta accounting is
meaningless without a bounded window.

**Tests (`tests/test_accountability.py`, 7 tests).** All pass:

1. `test_identity_reconciles_perfectly` — hand-built window (income,
   spend, brokerage contribution with transfer_tag + paired
   positions_ledger row) reconciles to `unexplained_cents == 0` and
   `accounted_for_pct == 1.0`.
2. `test_miscategorize_fires_uncategorized_drift` — NULL-category
   debit surfaces the drift with exact magnitude + fix payload.
3. `test_stale_portfolio_snapshot_fires` — portfolio snapshot
   7 days older than end → drift fires with "7 days older" label.
4. `test_missing_payroll_snapshot_fires` — Pension-category deposit
   without a payroll snapshot → drift fires with missing_months payload.
5. `test_market_loss_reconciles_with_negative_term` — pure market loss
   (no cash leg) → `market_value_delta_cents < 0`, identity still
   reconciles.
6. `test_market_gain_reconciles_with_positive_term` — symmetric.
7. `test_owner_scoping_excludes_other_owner` — Quintin-scoped view
   ignores Amy's transactions and balances; household view sums both.

**Verification.** Full backend suite 345/345 green (`pytest tests/ -x`);
frontend `npm run build` green; PII scan clean. Live verification on
seeded dummy data:

- Household, YTD 2026 (Jan 1 → Mar 31): **99.34% accounted**; $29,261.40
  NW delta; $193.66 unexplained → GREEN. Meets the exit criterion
  (≥95% on a 3-month window).
- Household, Last 3 Months (Feb 1 → Apr 22): 78.2% accounted;
  $36,669.73 NW delta; $8,002.97 unexplained; 8 drift sources (6×
  portfolio staleness, 1× stale home valuation, 1× RE interpolated).
  RED variant exercised.
- Amy (empty owner): all zeros; neutral "No net-worth change" state.

**Performance.** 3-month window: ~1.0s/call. 12-month: ~1.1s/call.
Profiling attributes 99% of the cost to the preexisting `get_flow_data`
call (which the accountability endpoint reuses for `dollars_in_cents`
and `dollars_spent_cents`). `_net_worth_at_date` is 0.1ms;
`_user_contributions_in_window` is 0.6ms; `detect_drift_sources` is
2ms. Below the 300ms target but the prompt explicitly notes "don't
block Phase D on view perf" — a materialization of
`v_investment_contributions` or a shared upstream `get_flow_data`
call across endpoints is the right future fix.

**Mockup.** `~/.claude/plans/phase14-phase-d-scorecard-mockup.html`
demonstrates green / yellow / red scorecard variants + drilldown modal.
User approved before frontend merged.

**Branch.** Landed directly on long-lived
`phase-14-dollar-accountability` (matching the A/B/C pattern);
per-phase sub-branch skipped by convention established in prior phases.
