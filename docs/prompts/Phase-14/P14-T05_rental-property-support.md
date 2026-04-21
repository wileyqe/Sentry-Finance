# P14-T05 — Rental Property Support (Phase E, deferred)

## Context

Phases A–D deliver dollar accountability for a household whose
properties are all primary residences. When an owned property
transitions to rental use — and especially when the owning household
itself becomes a tenant elsewhere — three new flow archetypes enter
the picture:

1. **Rental income** — a tenant's rent lands in an account
   designated for that rental property.
2. **Rental expenses** — mortgage interest on the rental, property
   management fees, repairs. These offset rental income on the
   tax-modeled side. On the Sankey they're `CONSUMED` with a rental
   sub-label. Principal on the rental mortgage remains
   `STORED_ILLIQUID` (builds equity in the rental property).
3. **Personal rent paid by the household** — the place the household
   actually lives in. Treated as an ordinary monthly housing expense
   — no special category, no special handling, no partner-to-partner
   rent flow.

This phase is **deferred** — it opens when the actual transition
begins, not on a calendar. The trigger events are listed below.

Account structure preparation is happening now. Each owned property
gets its own dedicated checking account, seeded with roughly one
month's rent before the first tenant. Security deposits, tenant rent,
maintenance expenses, and (eventually) mortgage payments all route
through that account. Think of each rental as its own small business.

## Starting State

(Will be accurate at trigger time — Phases A–D have shipped.)

- `income_sources` registry has the `rental_income` enum slot
  already reserved (from Phase B migration v32).
- `real_estate` table has a nullable `type` column (or an equivalent
  flag) that can mark a property as a rental. Verify at Phase E
  kickoff; if it doesn't exist, add it via a new migration.
- Per-property checking accounts exist in `accounts` and are owned
  by the appropriate `owners.id`.
- Phase D's accountability identity includes a `real_estate_delta`
  term. Extension to track rental-specific sub-deltas (vacancy,
  depreciation expense) is out of scope for the first pass of this
  phase.

## Task

### Task 1 — Trigger verification

Do not start implementation until ONE of these is true:

- A row is added to `income_sources` with
  `tax_treatment='rental_income'` and a live `match_rule_json`.
- A `real_estate` row is flagged with a rental type.
- A dedicated per-property checking account starts receiving a
  recurring rent-shaped deposit.

Having all three is ideal. Missing all three = too early; defer.

### Task 2 — Rental income classification

- Rental income sources register in `income_sources` with
  `tax_treatment='rental_income'`.
- `match_rule_json` typically combines account-id targeting (the
  dedicated rental checking account) with an optional counterparty
  substring. Example shape:
  ```json
  {"account_id": "<rental_account_slug>",
   "counterparty_substring": "RENT"}
  ```
- `get_flow_data` treats rental income identically to any other
  income source on the Sankey — left edge, grouped under a
  "Rental income" header if multiple rentals exist.

### Task 3 — Rental expense classification

- Maintenance, property management fees, and repairs tagged to a
  rental property (via category or account attribution) render as
  `CONSUMED` with a "Rental" sub-label group.
- Mortgage payments on rental properties decompose via the existing
  Phase B `loan_payment_splits` logic — principal to `STORED_ILLIQUID`
  (equity in rental), interest to `CONSUMED` (with rental sub-label),
  escrow to `CONSUMED`.
- Introduce a `rental_net_cents` computed field on the
  `get_flow_data` response for the period:
  `rental_income − rental_expenses`. Displayed as a summary line,
  not drawn as a Sankey edge.

### Task 4 — Personal rent (household tenant side)

No schema or classifier change required. The monthly rent paid by
the household to a third-party landlord is categorized as
Housing/Rent (add to category classifier if not present) and flows
to `CONSUMED` like any ordinary housing expense. No per-owner
partitioning, no internal wash — just an expense.

### Task 5 — Per-property account hygiene

- Each owned rental account should have enough metadata on
  `accounts` to associate it to its property (foreign key to
  `real_estate.id` is cleanest). If the column doesn't exist, add
  via a new migration.
- The initial seeding transfer (~one month's rent from savings to
  the new rental account) is a regular transfer with a
  `transfer_tag`. It classifies as `STORED_LIQUID` on the
  accountability identity (money moved between owner accounts, no
  cash leg out of the household). Verify this works without any
  special-case logic.

### Task 6 — Security deposits

**First pass: treat as a liability held by the landlord.** A security
deposit that lands in the rental account is NOT rental income — it's
money we're holding on behalf of the tenant and may be required to
return. Options:

- **Simplest first pass:** tag as a known category ("Security Deposit
  Held"), classify as `STORED_LIQUID` (we still have the dollars),
  but surface a warning in the scorecard drilldown noting that X
  dollars of the rental account balance is restricted.
- **Fuller treatment (backlog):** introduce a restricted-balance
  concept with a new `restricted_balances` table. Out of scope for
  first pass.

### Task 7 — Depreciation handling (documentation only)

Depreciation on rental property is tax math, not cash. It does not
appear on the Sankey. A separate "Tax-adjusted rental income"
callout that subtracts depreciation expense from rental_net is a
nice-to-have; defer to backlog or a Phase 15 decision-support task.

### Task 8 — Mockup + frontend

- Mockup showing:
  - One or more rental income sources on the left edge.
  - Rental-grouped expenses in the middle.
  - `rental_net` summary line (not a Sankey edge).
  - Household rent expense just showing up as regular housing.
- Frontend updates `ReportsPage.tsx` Sankey renderer for the grouped
  rental nodes.
- User approves mockup before code merges.

### Task 9 — Dummy data extension

When this phase actually opens, extend `scripts/dummy_data/generator.py`:

- A seeded rental property (abstract label, e.g. "Rental property A").
- A dedicated rental checking account.
- Monthly tenant rent deposit.
- Monthly rental expenses (mortgage payment, property management
  fee, one repair every 3 months).
- Optional: household rent paid out for the shared residence.

Re-baseline the golden seed fingerprint.

## Verification

### Unit tests

New file `tests/test_rental_flows.py` (created at phase open):

1. Rental income lands in `income_categories` under a "Rental"
   group.
2. Rental mortgage payment decomposes correctly with the rental
   sub-label preserved on the interest / escrow legs.
3. A month's rental_net matches `rental_income − rental_expenses`
   exactly.
4. Household personal rent flows to `CONSUMED` under Housing.
5. Initial seeding transfer (savings → new rental account) lands
   in `STORED_LIQUID` and does not double-count.
6. Security deposit transaction classifies as `STORED_LIQUID` with
   a drift/warning flag for the scorecard.

### Regression

- Phase A–D test suites all green.
- Full suite green.
- `scripts/pii_scan.py --all-tracked` clean.

### Manual UI check

- Sankey correctly shows rental income grouped separately from
  personal income.
- Rental mortgage payments visibly decompose with principal to
  `STORED_ILLIQUID` and interest to `CONSUMED`.
- Accountability scorecard remains ≥ 95% on a seeded month with all
  rental activity present.

## Post-Implementation Checklist

- [ ] Trigger verified — at least one of the three triggers in Task 1
      is live.
- [ ] Mockup approved.
- [ ] `docs/ROADMAP.md` flip `P14-T05` to `[v]`.
- [ ] Document whether the first-pass security-deposit handling is
      working well enough or whether a `restricted_balances` follow-up
      should be filed.

## Out of Scope

- Restricted-balance tracking table (backlog).
- Tax-adjusted rental income view with depreciation (backlog or
  Phase 15 decision-support task).
- Partner-to-partner rent flow (does not apply — both households
  become tenants of a shared third-party rental).
- Multi-tenant-per-property modeling (not needed for this
  household).
