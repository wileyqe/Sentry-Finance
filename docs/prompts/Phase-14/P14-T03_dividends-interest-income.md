# P14-T03 — Dividends and Interest as Real Income (Phase C)

## Context

After Phase B, the Sankey draws three terminal buckets but is still
missing a class of true cash income: **dividends** from investment
holdings and **interest** from deposit accounts. These are real
dollars hitting real accounts — the company or bank paid you — and
they should appear as income sources on the Sankey's left edge.

Market value changes on positions you already own (a stock going from
$100 to $110, or a home appraisal going up $20k) are a different
thing entirely. No cash leg. Those belong in the net-worth reconciliation
that Phase D builds. They do not appear on the Sankey at all, because:

1. There's no real source node for them — a pseudo-flow would
   require a synthetic left-edge node with no real-world counterpart.
2. Losses (downward moves) would require drawing negative flows,
   which Sankey visuals don't support cleanly.
3. The scorecard in Phase D handles both gains and losses symmetrically
   as part of the identity, without lying visually.

Phase C delivers: dividends and interest as first-class income
sources, reinvested dividends as two-leg visible flows, and the
contributions view that Phase D will depend on.

## Starting State

- `dal/reports.py` — `get_flow_data` post-Phase-B reads
  `payroll_snapshots` + `transactions` + the
  `income_sources` registry; classifies right-edge nodes into three
  buckets.
- `dal/investments.py:26-100+` — `get_holdings` reads
  `investment_holdings` with cost_basis and market_value.
- `dal/migrations/v02_portfolio.py` — `portfolio_snapshots` (total
  account value + cash balance per timestamp) and `positions_ledger`
  (per-transaction share_delta). `positions_ledger` does not
  distinguish user-deposit buys from dividend reinvestments today.
- Phase B shipped the `income_sources` registry with the
  `interest_dividend` enum already in the CHECK constraint.
- `transactions` already has `transfer_tag` linkage between cash legs
  of reconciled transfers.

## Task

### Task 1 — `v_investment_contributions` SQL view

Create a view (NOT a materialized table) that classifies each
`positions_ledger` row as either a user-driven contribution (there's
a matching cash-side transfer) or an intra-account event (dividend
reinvestment, employer match).

```sql
CREATE VIEW v_investment_contributions AS
SELECT
  pl.id             AS ledger_id,
  pl.account_id,
  pl.timestamp,
  pl.transaction_type,
  pl.share_delta,
  pl.new_total_shares,
  t.id              AS matched_tx_id,
  t.signed_amount   AS matched_tx_signed_amount,
  t.transfer_tag    AS matched_tx_transfer_tag,
  CASE
    WHEN pl.share_delta > 0 AND t.id IS NOT NULL THEN 'user_contribution'
    WHEN pl.share_delta > 0 AND t.id IS NULL     THEN 'intra_account_credit'
    WHEN pl.share_delta < 0                       THEN 'sale_or_transfer_out'
    ELSE 'unknown'
  END               AS classification
FROM positions_ledger pl
LEFT JOIN transactions t
  ON t.account_id = pl.account_id
 AND date(t.posting_date) = date(pl.timestamp)
 AND t.transfer_tag IS NOT NULL;
```

Why a view, not a table: contribution classification reflects the
current user categorization. Any recategorization or re-reconciliation
would silently stale a materialized table. Start with the view; if
perf becomes an issue (Phase D scorecard benchmarks >500ms), add a
recompute hook.

Migration `v34_investment_contributions_view.py` (DDL-only, no data
changes).

### Task 2 — Dividend and interest detection

The existing categorization engine tags dividend and interest
transactions to categories like "Dividend Income" and "Interest
Income". Phase C adds:

- Seeded `income_sources` rows (via a seeder helper, NOT hard-coded
  in migration) for `interest_dividend` archetypes.
- `match_rule_json` with `{"category": "Dividend Income"}` or
  `{"category": "Interest Income"}` so the classifier resolves the
  source.
- These income sources flow to the income left edge of the Sankey
  like any other income source. No special case in
  `get_flow_data`.

### Task 3 — Reinvested dividend two-leg rendering

When a dividend posts to an account that also has a same-day (within
N business days, N=2) buy of the same ticker for approximately the
same amount, emit the pair as a two-leg flow in `get_flow_data`:

- Leg 1: dividend income → account node (visible income flow)
- Leg 2: account node → `STORED_ILLIQUID` (the new share purchase)

Both legs draw. The account node serves as a brief routing hub.

Classification for the second leg uses the existing Phase B
brokerage cash-vs-position logic from `flow_classification.py` —
a buy makes it `STORED_ILLIQUID`.

Detection lives in `get_flow_data` (or a helper in a new
`dal/investment_flows.py` if the logic grows). Match rule:
same account, same ticker inferred from `positions_ledger`, within
2 business days, amounts within $1.

### Task 4 — Frontend rendering

Update the Sankey SVG renderer to:

- Group dividend and interest income source nodes under a
  collapsible "Investment income" header on the left edge, since
  there can be many tiny ones.
- Render reinvestment two-leg flows as a loop on the account node
  (or as two distinct edges if that's visually cleaner — validate in
  the mockup).
- Ensure no left-edge node exists for "Market gains/losses." The
  Sankey stays silent on those.

### Task 5 — HTML mockup

Demonstrate the target layout for a month with:
- At least one dividend that was NOT reinvested (simple income edge).
- At least one dividend that WAS reinvested (two-leg flow).
- At least one period-end position delta from pure market move (must
  be invisible on the Sankey).

User approves before Task 4 merges.

### Task 6 — Dummy data extension

Extend `scripts/dummy_data/generator.py`:

- Monthly HYSA interest deposits routed through the
  `interest_dividend` archetype.
- Quarterly dividends from one seeded ticker, NOT reinvested.
- Quarterly dividends from another seeded ticker WITH reinvestment
  (paired `positions_ledger` buy).
- Re-baseline `tests/test_golden_seed.py` fingerprint in the same
  commit.

## Verification

### Unit tests

New file `tests/test_investment_contributions_view.py`:

1. A `positions_ledger` row with a matching cash transfer
   classifies as `user_contribution`.
2. A `positions_ledger` row with no matching transaction classifies
   as `intra_account_credit`.
3. A negative `share_delta` classifies as `sale_or_transfer_out`.

New file `tests/test_dividend_interest_flows.py`:

1. A dividend transaction without reinvestment produces a single
   income edge to `income_categories` under the Investment income
   group.
2. A dividend transaction WITH reinvestment produces two edges:
   dividend → account node → `STORED_ILLIQUID`.
3. Interest income from HYSA renders identically to a dividend
   (no reinvestment leg).
4. A pure market appreciation with no cash leg produces NO Sankey
   flow of any kind.
5. A pure market depreciation (portfolio value drops) produces NO
   Sankey flow of any kind.

### Regression

- `pytest tests/test_comprehensive.py` passes (derived metrics).
- `pytest tests/test_phase6.py` passes (investment tab).
- Phase A + B test suites still pass.
- `pytest tests/ -x --tb=short` full pass.

### Manual UI check

- Sankey shows investment income sources grouped on the left edge.
- A reinvested dividend shows the two-leg flow clearly; hover tooltips
  explain both legs.
- A month where the market dropped significantly shows NO negative
  or "fake" flows on the Sankey — the Sankey looks identical in shape
  to a flat market month for any non-cash movement.

### Performance check

- `get_flow_data` runtime on 12 months of seeded data with the view
  is within 2× of pre-Phase-C baseline. If it's worse, note it for
  Phase D to potentially materialize.

## Post-Implementation Checklist

- [ ] `docs/ROADMAP.md` flip `P14-T03` to `[v]`.
- [ ] `scripts/pii_scan.py --all-tracked` clean.
- [ ] Migration v34 applies cleanly on fresh + upgrade paths.
- [ ] Mockup approved before Task 4 merges.

## Out of Scope

- Accountability scorecard reconciliation (Phase D).
- Materializing `v_investment_contributions` (only if perf demands
  it, and that's Phase D's problem).
- Rental property income classification (Phase E).
