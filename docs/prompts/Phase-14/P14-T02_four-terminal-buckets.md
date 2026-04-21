# P14-T02 — Four Terminal Buckets (Phase B)

## Context

Phase A wired gross paycheck data into the Sankey. The Sankey's right
edge still has the single legacy "savings" bar. Phase B replaces that
with three labeled terminal buckets that together account for every
dollar in the period:

- **Spent** (consumed) — utilities, groceries, taxes, mortgage
  interest, insurance premiums.
- **Kept liquid** — checking/HYSA accumulation, uninvested brokerage
  cash.
- **Kept illiquid** — retirement contributions, HSA, mortgage
  principal paid, securities purchased.

A fourth enum value (`GROWN`) exists in the bucket type system but is
**not drawn** — market value moves on already-owned positions are
net-worth math, not cash flow. Phase C handles dividends and interest
as true cash income; Phase D handles market moves as part of the
reconciliation identity.

This phase introduces two new tables and a new classification module,
reworks the custom SVG renderer, and ships mortgage P&I decomposition.

## Starting State

- `dal/reports.py:556-663` — `get_flow_data` merges payroll
  decomposition (from P14-T01) with transaction-derived flows but
  does not classify right-edge nodes into buckets.
- `dal/reconciliation.py:58-140` — `transfer_tag` reconciliation
  logic that matches debit/credit pairs across institutions. Peer
  account type lookup exists and should be reused for terminal-fate
  classification of transfers.
- `dal/category_classifications.py` — TRANSFER_CATEGORIES,
  INCOME_EXCL_FROM_INC, spend-exclusion sets. To be referenced (not
  modified) by the new classifier.
- `dal/debt.py:168+` — existing `project_payoff()` runs amortization
  math for forward projection; the inverse (decompose a completed
  payment into P + I) does not yet exist.
- `dal/migrations/v31_account_id_opacify.py` — latest migration.
  `VERSION = 32` is next.
- `frontend/src/pages/ReportsPage.tsx:95-200+` — custom SVG Sankey
  renderer with a single right-edge savings bar.
- `backend/result_writer.py` — post-commit pipeline runs
  categorization → reconciliation → recurring → derived → alerts →
  goal-sync after transaction writes. New split step slots between
  reconciliation and derived-recompute.

## Task

### Task 1 — `dal/flow_classification.py` (new module)

Single home for the bucket rules.

```python
from enum import Enum

class BucketLabel(str, Enum):
    CONSUMED         = "CONSUMED"
    STORED_LIQUID    = "STORED_LIQUID"
    STORED_ILLIQUID  = "STORED_ILLIQUID"
    GROWN            = "GROWN"          # reserved; Phase B does not draw
    ROUTING          = "ROUTING"        # intermediate nodes


def classify(
    category: Optional[str],
    account_type: Optional[str],
    transfer_peer_account_type: Optional[str] = None,
    brokerage_buy_matched: bool = False,
) -> BucketLabel:
    """
    Returns the terminal bucket for a flow edge given its context.

    - For transactions with a transfer_tag: look at the peer account
      type. Peer = retirement/HSA/brokerage → STORED_ILLIQUID (when
      brokerage_buy_matched=True) or STORED_LIQUID (brokerage cash).
      Peer = checking/savings → STORED_LIQUID.
    - For regular debits: category → CONSUMED unless the category is
      in a short list of known-transfer categories.
    - For credits (non-transfer): these are income; classifier is not
      called on income flows (those use the income-source registry).
    """
```

Rule tables are small frozensets at module top with comments citing
the source (which migration, which category file) for each entry.
When a new category ships, this is the one file that knows about it.

### Task 2 — `income_sources` registry table (migration v32)

```sql
CREATE TABLE income_sources (
  id                          TEXT    PRIMARY KEY,
  display_label               TEXT    NOT NULL,
  owner_id                    INTEGER NOT NULL REFERENCES owners(id),
  tax_treatment               TEXT    NOT NULL CHECK (tax_treatment IN (
    'w2_withheld','pension_withheld','nontaxable',
    'contractor_no_withholding','interest_dividend',
    'employer_match_bypass','rental_income','other'
  )),
  default_category            TEXT,
  match_rule_json             TEXT    NOT NULL,
  estimated_tax_reserve_pct   REAL    NOT NULL DEFAULT 0.0,
  bypass_cash_routing         INTEGER NOT NULL DEFAULT 0
                                      CHECK (bypass_cash_routing IN (0,1)),
  active                      INTEGER NOT NULL DEFAULT 1
                                      CHECK (active IN (0,1)),
  created_at                  TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at                  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_income_sources_owner ON income_sources(owner_id);
CREATE INDEX idx_income_sources_active ON income_sources(active);
```

Semantics:
- `match_rule_json` is a small opaque blob — typically
  `{"counterparty_substring": "...", "category": "...",
  "owner_id": N}`. Interpreted by a matcher function in
  `dal/flow_classification.py`.
- `estimated_tax_reserve_pct` defaults to `0.0`. Phase B does not use
  it in any Sankey computation. Reserved for a future opt-in
  projection view. Present now so it's not a schema change later.
- `bypass_cash_routing = 1` means the source draws a pseudo-flow
  direct to `STORED_ILLIQUID` without a checking-account hop.
  Employer retirement matches use this.

DAL module `dal/income_sources.py` with thin CRUD: `get_by_id`,
`list_for_owner`, `create`, `update`, `deactivate`.

### Task 3 — `loan_payment_splits` table + decomposition (migration v33)

```sql
CREATE TABLE loan_payment_splits (
  transaction_id    INTEGER PRIMARY KEY REFERENCES transactions(id),
  principal_cents   INTEGER NOT NULL,
  interest_cents    INTEGER NOT NULL,
  escrow_cents      INTEGER NOT NULL DEFAULT 0,
  computed_at       TEXT    NOT NULL DEFAULT (datetime('now')),
  method            TEXT    NOT NULL CHECK (method IN
                              ('amortization','statement','manual'))
);
```

Invariant: `principal_cents + interest_cents + escrow_cents ==
abs(transactions.signed_amount)` for the referenced transaction.
Enforced in the writer (fail-fast).

New `dal/debt.decompose_payment(conn, account_id,
payment_amount_cents, posting_date)` returns
`{principal, interest, escrow, method}`. Logic:

1. If the account has a statement-parser attached and a line item for
   this payment is available, use `method='statement'` with the
   parsed values.
2. Otherwise, compute via amortization: fetch APR from
   `loan_details`; fetch outstanding balance as of `posting_date`
   from `balance_snapshots`; compute monthly interest as
   `balance * (apr / 12)`; principal is `payment − interest`;
   escrow defaults to `0` unless the payment amount exceeds the
   standard P+I (residual is assumed escrow).
3. `method='manual'` is reserved for a future UI override path.

Post-commit pipeline step (in `backend/result_writer.py`): when a
transaction posts to an account flagged as a mortgage account, call
`decompose_payment` and upsert into `loan_payment_splits`. Run
between reconciliation and derived-recompute.

### Task 4 — Brokerage cash-vs-position detection

A transfer into a brokerage account should classify as:
- `STORED_LIQUID` when the cash sits as a brokerage cash position.
- `STORED_ILLIQUID` when a buy trade consumes the cash within the
  window.

Detection: for each transfer with a brokerage-account destination,
look for a matching `positions_ledger` row with `share_delta > 0` on
the same account within N business days (N = 5 as first pass).
Match → illiquid. No match → liquid.

This logic lives in the classifier (Task 1) and reads
`positions_ledger` directly — no new table.

### Task 5 — Extend `get_flow_data`

- For every right-edge node in the returned payload, attach a
  `bucket` field from the classifier.
- Emit bucket totals: `bucket_totals: {CONSUMED, STORED_LIQUID,
  STORED_ILLIQUID}` at the top level.
- Invariant: `sum(bucket_totals) == total_inflow` within $1, where
  `total_inflow = sum of all income-side flows` from Phase A + C
  sources. Validate in the function; log a structured warning if
  drift exceeds the tolerance.

### Task 6 — Frontend Sankey rework

Update `frontend/src/pages/ReportsPage.tsx` custom SVG renderer:

- Right edge becomes three columns, color-coded:
  - Spent (muted red)
  - Kept liquid (muted blue)
  - Kept illiquid (muted green)
- Hover on each column shows the bucket total and an itemized list
  of contributors.
- Mortgage payment nodes in the middle split visibly into
  principal / interest / escrow sub-edges.
- Employer-match income sources (from the registry with
  `bypass_cash_routing=1`) draw a pseudo-edge from a synthetic
  source node straight to Kept illiquid, bypassing the middle.

### Task 7 — HTML mockup (prerequisite)

Same gate as P14-T01. Produce a static HTML file showing the
three-column Sankey on a known month of real data, with colors and
the mortgage P&I split. User approves before Task 6 merges.

Location: local scratch, NOT in repo.

### Task 8 — Dummy data seeder updates

Extend `scripts/dummy_data/generator.py`:

- Amy: one `payroll_snapshots` row per month of synthetic W-2 data.
  Use abstract labels ("Primary W-2 source").
- Employer-match pseudo-flow: one synthetic monthly row showing
  employer → retirement account with no cash leg. Registered in
  `income_sources` as `employer_match_bypass`, `bypass_cash_routing=1`.
- Contractor-style income: a handful of deposits spread across 4
  active-season months, with no associated withholding. Registered
  as `contractor_no_withholding` with `estimated_tax_reserve_pct=0`.
- Re-baseline the golden seed fingerprint (`tests/test_golden_seed.py`)
  in the same commit — year totals unchanged.

## Verification

### Unit tests

New file `tests/test_flow_classification.py`:

1. Transfer with peer retirement account → `STORED_ILLIQUID`.
2. Transfer with peer checking account → `STORED_LIQUID`.
3. Transfer to brokerage with matching same-day buy → `STORED_ILLIQUID`.
4. Transfer to brokerage with no matching buy → `STORED_LIQUID`.
5. Debit to groceries → `CONSUMED`.
6. Debit with transfer_tag but no peer found → log warning, default
   to `CONSUMED` (fail-loud not fail-silent).

New file `tests/test_loan_decomposition.py`:

1. A known payment on a seeded mortgage decomposes to principal +
   interest matching an external amortization calculator within $1.
2. The split row's sum equals the transaction amount.
3. `method='amortization'` when no statement source is registered.
4. `method='statement'` when statement parser returns a line item.

New file `tests/test_income_sources_registry.py`:

1. `get_by_id` + `list_for_owner` basics.
2. `active=0` rows excluded from `list_for_owner` default.
3. JSON schema of `match_rule_json` — at minimum
   `counterparty_substring` OR `category` must be present.

### Regression

- `pytest tests/test_reconciliation.py` passes.
- `pytest tests/test_owner_scoping.py` passes.
- `pytest tests/test_cashflow_invariants.py` passes (the canonical
  sign-convention test suite).
- `pytest tests/test_golden_seed.py` passes with re-baselined
  fingerprint.
- `pytest tests/ -x --tb=short` end-to-end passes.

### Manual UI check

- The three-bucket totals visually add up to the total inflow on a
  known month.
- A mortgage payment node shows three sub-edges with plausible P / I /
  E values.
- A brokerage transfer that sits as cash lands in Kept-liquid; the
  same transfer on a month with a subsequent buy lands in
  Kept-illiquid.
- An employer-match pseudo-flow renders directly into Kept-illiquid
  without passing through any checking node.

### End-to-end invariant

```
bucket_totals.CONSUMED
  + bucket_totals.STORED_LIQUID
  + bucket_totals.STORED_ILLIQUID
  = total_inflow ± $1
```

Asserted in `get_flow_data` at runtime with a structured-log warning
when it drifts, AND tested on seeded data.

## Post-Implementation Checklist

- [ ] `docs/ROADMAP.md` flip `P14-T02` to `[v]`.
- [ ] Update `docs/ARCHITECTURE.md` if bucket semantics need a new
      cross-reference. Probable target: §4.6.
- [ ] `scripts/pii_scan.py --all-tracked` clean.
- [ ] Fresh-init migration applies (`vNN` sequence) on an empty DB.
- [ ] Mockup approved before SVG rework merges.

## Out of Scope

- Dividend and interest income treatment (Phase C).
- Accountability scorecard reconciliation identity (Phase D).
- Rental property handling (Phase E).
- Any UI for populating the `income_sources` table. In Phase B the
  table is populated locally by the user via direct inserts or the
  seeder; a settings UI is backlog.
