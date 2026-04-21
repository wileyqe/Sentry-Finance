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

- [ ] `docs/ROADMAP.md` flip `P14-T04` to `[v]`.
- [ ] Scorecard accurate on real household data (≥95% on a 3-month
      window before long-lived branch merges to main).
- [ ] Drift source fix actions all wired to a real target page.
- [ ] Mockup approved before Task 4 merges.

## Out of Scope

- Rental property accounting (Phase E).
- Effective-tax-rate computation as a decision-support feature
  (Phase 15 backlog — natural follow-up given the contractor-season
  drift source).
- Materialized contributions table (only if the Task 7 benchmark
  reveals a hard perf problem).
