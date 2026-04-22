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

## Outcomes — 2026-04-22

Phase C landed on `phase-14-dollar-accountability` in a single
session. Nine tasks in the original prompt collapsed to six
mergeable chunks:

### 1. Migration v34 — `v_investment_contributions` view

`dal/migrations/v34_investment_contributions_view.py`. DDL-only
`CREATE VIEW` exactly as specified, with `DROP VIEW IF EXISTS`
first so re-running on an upgraded DB is idempotent. `PRAGMA
user_version` bumped to 34 on `init_db` pass. `PRAGMA
foreign_key_check` not needed (no FK changes).

### 2. Categorizer YAML reorder

`config/categories.yaml` ships with a generic `"Dividend"`
keyword that routes every dividend to `Interest` — which would
have silently dragged the new Fidelity dividend transactions
into the HYSA-interest income bar. Fix landed inline: replaced
the `"Interest Paid|INTEREST PAYMENT|Dividend"` rule with a
specific `"Investment Income|Acorns Grow Investment|DIVIDEND|
CASH DIV"` pattern **above** a narrowed `"Interest Paid|
INTEREST PAYMENT|SHARE DIVIDEND|SHARES DIVIDEND"` rule. Credit
union share yields (NFCU's "SHARE DIVIDEND" lines) still route
to `Interest`; brokerage ticker-prefixed dividends route to
`Investment Income`. First-match-wins is preserved.

### 3. Generator — Fidelity dividend cash transactions

`scripts/dummy_data/generator.py::generate_fidelity_investment_history`
now collects a `dividend_txns` list during the month walk and
upserts them through `dal.transactions.upsert_transactions` so
the sign/direction invariant enforces. Stamped fields:
`category='Investment Income'`, `description='{TICKER}
DIVIDEND'`, `merchant={TICKER}` (the merchant backfill
normalizes this to `'Spg Dividend'` etc. post-upsert; the match
helper keys on `description` for robustness). Return dict gains
`dividend_txns` count. Golden seed fingerprint unchanged —
`test_golden_seed.py` pins `generate_transactions` only, not
the investment-history writer. **55 dividend transactions**
emitted for a 3-year seeded dataset (5 tickers × ~quarterly).

### 4. `income_sources` seeder additions

Two new rows in `generate_income_source_registry()`:

- `seed_quintin_bank_interest` — `tax_treatment=interest_dividend`,
  `match_rule: {"category": "Interest", "owner_id": "quintin"}`,
  `bypass_cash_routing=0`.
- `seed_quintin_fidelity_dividends` — same treatment, category
  `Investment Income`.

Registry now has 5 seeded rows (up from 3). No bypass pseudo-flows
— dividends and interest have real cash legs.

### 5. `get_flow_data` reinvestment detection

`dal/reports.py::_compute_reinvestment_flows` pairs dividend
cash transactions to positions_ledger `REINVESTMENT`/`BUY` rows
via:

- `pl.account_id = t.account_id`
- `UPPER(t.description) LIKE UPPER(pl.ticker) || ' %'` — robust
  against merchant-column normalization, works for any
  `"{TICKER} DIVIDEND"` shape.
- `pl.share_delta > 0` AND `pl.transaction_type IN ('REINVESTMENT', 'BUY')`
- `date(pl.timestamp)` within ±2 calendar days of `t.posting_date`
- amount tolerance: `ABS(pl.cost_basis_dec - t.signed_amount) ≤ 100 cents`
- dividend txn constraints: `status='posted' AND signed_amount > 0
  AND transfer_tag IS NULL AND category = 'Investment Income'`

Matched amounts bump `illiquid_cents` in `_compute_bucket_totals`
(identity-preserving: STORED_LIQUID stays as residual, so drift
remains 0). Per-match entries are returned in
`reinvestment_flows`. First-match-wins dedup at the ledger level
handles the edge case where both a REINVEST and a nearby BUY
match.

### 6. Frontend — reinvestment mid-nodes on the Sankey

`frontend/src/pages/ReportsPage.tsx`:

- New `ReinvestmentAgg` interface + `reinvestmentAggs` in
  `sankeyData` memo — API entries collapsed by ticker to one bar.
- `SankeyChart` accepts a `reinvestmentAggs` prop; mid-column
  `reinvestmentLayout` stacks below illiquid transfer aggregators.
- Hub → reinvestment mid-node → STORED_ILLIQUID pair-of-links
  added to the standard link machinery.
- Mid-node renders with illiquid green fill + dashed blue stroke
  as a visual hint that the flow originated from the
  `Investment Income` source on the left edge.
- `STORED_ILLIQUID` bucket tooltip contributor list extended.

No design for a separate collapsible "Investment income" group
on the left edge — with only two income sources in scope
(Interest + Investment Income), standalone nodes are clearer
than a collapsed group. Revisit if/when dividends from 3+
brokers land.

### Verification

- Backend: `pytest tests/ -x --tb=short` → **338 passed**
  (+9 from Phase B's 329). New test files:
  `tests/test_investment_contributions_view.py` (4 tests) and
  `tests/test_dividend_interest_flows.py` (5 tests — each of the
  five cases in the prompt).
- PII scan: `python scripts/pii_scan.py --all-tracked` → clean.
- Frontend build: `npm run build` → green, 2.03MB bundle.
- Live browser preview on YTD 2026 (`data/dummy.db`, end-date
  2026-04-22): Sankey shows `Interest ($135)` and `Investment
  Income ($105.99)` on the left edge; `Reinvest · SPG ($29.96)`
  and `Reinvest · TGT ($17.65)` as mid-nodes flowing to
  `Kept illiquid`. `bucket_invariant_drift_cents = 0`. No
  console errors.
- Migration v34: verified on both fresh-init and upgrade-from-v33
  paths via `init_db()` smoke.
- Static mockup (`~/.claude/plans/phase14-phase-c-sankey-mockup.html`)
  approved by the user before frontend work merged.

### Surprises & follow-ups

- **Categorizer rule order matters more than expected.** The
  single generic `"Dividend"` pattern in categories.yaml almost
  silently merged 55 transactions into the wrong category. The
  fix is minor (two lines swapped), but it emphasizes that
  adding new transaction archetypes needs a round-trip through
  the categorizer before it can be considered integrated. Might
  be worth a "categorization audit" test that asserts every
  known description archetype lands in its expected category.
- **Merchant backfill rewrites stamped values.** The merchant
  column I populated (`merchant={TICKER}`) got rewritten to a
  title-cased `"Spg Dividend"` by the merchant backfill pipeline.
  The reinvestment matcher initially keyed off `merchant` and
  fell through to 0 matches; switched to `description LIKE`. No
  code path should assume `merchant` survives verbatim.
- **Market-gains-are-invisible** is easy to assert negatively
  (no Sankey flow) but the test coverage is thin — tests 4 and
  5 in `test_dividend_interest_flows.py` only check that
  `total_income == 0` and `sum(bucket_totals) == 0` on a
  portfolio_snapshots-only window. Phase D will exercise the
  actual reconciliation math; that's where the invariant
  earns its keep.
- **`v_investment_contributions` is currently informational.**
  No DAL function queries it yet. Phase D's scorecard
  reconciliation is the first real consumer.
- **SPAXX sweep interest** is called out in the generator
  docstring (Phase C addition) but not actually implemented —
  only the existing HYSA interest + new Fidelity dividends
  ship. If real Fidelity SPAXX interest lands in a future
  statement parser, the same income_sources row pattern
  will catch it with no code change.
