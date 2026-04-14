# P13-T08: Investment Tax Treatment Tracking

## Starting State

The investment section tracked holdings, allocations, performance, and tax lots
but had zero awareness of tax treatment.  A $180k TSP account was displayed
identically to a $46k taxable brokerage, even though the after-tax purchasing
power differs significantly.  The real TSP statement (page 2) shows three
internal tax buckets: Traditional (33%), Roth (60%), and Tax-exempt (7%) --
a structure unique to government retirement plans.

## Goal

Surface tax treatment as a first-class dimension in the investment UI so the
user can answer: "How tax-diversified am I?" and "What are the tax implications
of each account?"

## Design Decisions

- **Tax-exempt lumped with Roth** -- both represent already-taxed money, treated
  identically on withdrawal.  No separate tax-exempt display.
- **No Roth contributions vs. earnings sub-breakdown** -- overkill for current
  needs; the schema supports adding it later.
- **No tax-adjusted net worth** on the dashboard -- requires marginal tax rate
  assumptions that are too opinionated for now.
- **Two-tier data model**: simple `tax_status` column on accounts for most
  accounts (taxable, traditional, roth); a `tax_buckets` table for mixed
  accounts like TSP that have internal sub-balances.

## What Was Built

### Schema (migration v29)

- `accounts.tax_status TEXT DEFAULT NULL` -- values: taxable, traditional, roth,
  mixed, hsa, NULL (non-investment accounts)
- `tax_buckets` table -- per-account, per-bucket-type balance snapshots in cents
  with vested_pct and as_of date

### Backend

- `dal/investments.py`: two new functions (`get_tax_buckets`, `get_tax_summary`),
  `get_holdings` now includes `tax_status`, `get_lots` now includes `is_long_term`
- `backend/routers/investments.py`: two new endpoints
  (`/api/investments/tax-buckets`, `/api/investments/tax-summary`)

### Seeder

- TSP generates weekly `tax_buckets` rows (Traditional ~33%, Roth ~67%) with
  Roth share drifting upward over the 3-year window
- Account records include `tax_status` (mixed, taxable, taxable)
- Fixed `institution_rows()` to pass through `tax_status` from ACCOUNTS list

### Frontend

1. **Holdings tab**: Tax badge per account row (Taxable/gray, Mixed/violet,
   Tax-Deferred/amber, Roth/green).  TSP expansion shows a collapsible bucket
   panel with stacked bar + legend.  Tax lots for taxable accounts show ST/LT
   badge (short-term amber, long-term green based on 365-day threshold).
   Tax-advantaged accounts show "Tax-deferred" or "Tax-free" text instead.

2. **Overview tab**: Tax Diversification card between the performance chart and
   the account bar chart.  Stacked bar showing Tax-Deferred / Tax-Free / Taxable
   with dollar amounts and percentages.

3. **Allocation tab**: Holdings mode centers the donut + legend (removed dead
   space).  X-Ray mode shows dual donuts -- asset allocation donut left-aligned,
   tax treatment donut right-aligned, with both legends stacked in the center.

## Verification

- `python scripts/seed_dummy_data.py` -- seeds tax_buckets (314 rows) and
  tax_status on 3 investment accounts
- `pytest tests/` -- 158 passed (2 pre-existing import failures unrelated)
- `cd frontend && npm run build` -- clean build, no TS errors
- Visual verification: all three tabs confirmed rendering correctly via browser

## Follow-ups

- When real TSP connector is built, parse the three-bucket balances from the
  statement PDF (the structure is already modeled in `tax_buckets`)
- Future Roth IRA or Traditional IRA accounts would use `tax_status = "roth"`
  or `tax_status = "traditional"` with no bucket table rows needed
- Tax Planning report (estimated tax on withdrawals, Roth conversion analysis)
  is a natural next feature but requires marginal tax rate configuration
