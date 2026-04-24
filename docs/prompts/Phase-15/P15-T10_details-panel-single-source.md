# P15-T10: Account/Asset Details Panel — Single Source of Truth

## Context

The Apr 2026 PII scrub (PR0, commit 7e77822 after history rewrite)
fixed an immediate leak — a real Kia VIN and "2022 KIA NIRO" collateral
description that had been hardcoded into `seed_dummy_data.py` and
matched the household's actual vehicle. But the leak was the symptom;
the disease was the architecture that made the leak possible:

> The auto-loan Details panel rendered "2022 KIA NIRO" as collateral
> while the linked vehicle row was a Toyota RAV4. Two surfaces, two
> sources, both true at the same time. The user's framing: bandaids
> won't work; it needs to be impossible to fail.

A four-domain audit (loan/vehicle, mortgage/real-estate, credit-card,
deposit/investment) found the same disease in different stages:

- **Auto + vehicle:** loan KV carried `vin` / `collateral_description`
  / `gap_flag` / `date_opened` / `purchase_price` hardcoded to a Kia,
  while `vehicle_assets` carried a Toyota. Three sources, no
  reconciliation.
- **Mortgage + home:** loan KV carried `collateral_description = "123
  Demo Lane"` and `date_opened = "04/02/2023"` while the actual
  origination was 2020-09-15 — a 2.5-year gap on the same panel.
  Address had no schema home at all.
- **Credit card:** `14_day_payoff` / `payment_due_date` / `ytd_interest`
  pinned to calendar strings that drift the moment `end_date` rolls.
- **Deposits:** mostly clean already; `direct_deposit_enrolled` was a
  stub for one account with no anchor.

T10 is the structural fix: every fact gets exactly one canonical home,
the schema enforces it, and a composer module guarantees the loan-side
and asset-side panels for the same loan/asset pair return the same
data.

## Starting State

- PR0 (commit 7e77822 after history rewrite) replaced the leaked Kia
  identity with synthetic Honda Civic values; rounded mortgage and
  auto loan numbers; standardized `date_opened` strings; extended
  `pii_scan.py` with a VIN-shape detector + allowlist; rewrote git
  history to scrub leaked strings from public commits.
- DB at v35 with `vehicle_assets.linked_loan_id` (v35) but no `vin`
  or `gap_insurance` columns; `real_estate` had only `name` /
  `estimated_value` / `linked_loan_id` / `source` / `as_of` / `owner_id`.
- `record_loan_details` accepted any `field_name` — no denylist.
- Loan and asset panels each composed their own bundle from
  `loan_details` KV + asset row + APY history; the `_linked_loan_bundle`
  helper in `backend/routers/reports.py` was the only shared join,
  and only on the asset side.
- Frontend rendered `vin` / `collateral_description` / `purchase_price`
  / `date_opened` from `details` (loan KV) on both the loan-side and
  the asset-side panels.

## Task

Three sequential PRs. PR0 (PII scrub) and PR1 (schema + DAL composer)
are shipped — see commits 7e77822 (PR0) and ac95db9 (PR1). PR2 is the
seeder + invariant work documented here. PR3 swaps the routers and
frontend to consume the composer shape.

### PR1 — Schema + DAL composer + denylist (DONE, commit ac95db9)

1. **Migrations.**
   - `v36_vehicle_identity`: `vehicle_assets.vin TEXT` (UNIQUE WHERE
     NOT NULL) + `gap_insurance INTEGER`.
   - `v37_real_estate_address`: `real_estate.address TEXT` +
     `purchase_price REAL` + `purchase_date TEXT`. Append-only table;
     latest non-null per column wins.

2. **DAL surface.**
   - `add_vehicle(..., vin=None, gap_insurance=None)` with COALESCE
     preservation.
   - `record_real_estate_valuations` accepts `address` /
     `purchase_price` / `purchase_date` per row.
   - `get_vehicle_details` surfaces `vin` + `gap_insurance`.
   - `get_real_estate_details` surfaces address/purchase_price/purchase_date
     via latest-non-null subquery so quarterly valuations that omit
     identity columns don't shadow the canonical values.

3. **Denylist.** `record_loan_details` raises `ValueError` if the caller
   passes any of `{vin, collateral_description, purchase_price,
   gap_flag, date_opened}` AND the account has a linked
   `vehicle_assets` or `real_estate` row. BNPL keeps `purchase_price`
   because it has no linked asset.

4. **Composer.** `dal/account_details_composer.py`:
   - `get_loan_panel_bundle(conn, account_id) -> dict`
   - `get_vehicle_panel_bundle(conn, vehicle_id) -> dict | None`
   - `get_real_estate_panel_bundle(conn, property_id) -> dict | None`
   All three share `_resolve_collateral_for_loan`, so the loan-side and
   asset-side panels for a given pair return identical `collateral`
   slots by construction.

5. **Tests.** `tests/test_details_panel_invariants.py` — 16 tests
   covering the denylist (5 fields × secured vehicle + property loans,
   plus the BNPL allow-path) and composer convergence (loan and asset
   panels resolve same collateral; identity carries across appended
   rows; 404 paths).

### PR2 — Seeder refactor + post-seed asserts (THIS PR)

1. **Reorder.** Move `seed_real_estate` and `seed_vehicle_assets` BEFORE
   `seed_loan_details*` in `main()` so `linked_loan_id` is populated
   when the denylist's "does this account have a linked asset?" check
   runs. Without the reorder the denylist would be a no-op during
   early seeding.

2. **Route identity to canonical sources.**
   - `dummy_data/vehicle_assets.json` carries `vin` and `gap_insurance`;
     `seed_vehicle_assets` passes them through `add_vehicle`.
   - `dummy_data/real_estate.json` carries `address` /
     `purchase_price` / `purchase_date` on every quarterly row;
     `seed_real_estate` passes them through.
   - `dummy_data/loan_details.json` no longer carries `purchase_price`
     for the secured loans (`summit_mtg`, `summit_auto`). Stays for
     `payflex_bnpl` (unsecured).
   - `auto_stretch` in `seed_loan_details_stretch` keeps only
     `collateral_type` (categorical loan-type label) + balance-derived
     fields. Drops `vin`, `collateral_description`, `gap_flag`,
     `date_opened`.
   - `mtg_stretch` keeps only `escrow_balance` (identity-only stub
     until escrow accrual derivation is built) + balance-derived fields.
     Drops `collateral_description` and `date_opened`.

3. **Credit-card derivations.** New `_credit_card_stretch(acct, apr,
   statement_day)` helper inside `seed_loan_details_stretch`:
   - `14_day_payoff` from `abs(latest_balance) + 14 * (balance × APR / 365)`.
   - `payment_due_date` from `_next_payment_due_date(statement_day)`
     — next occurrence of statement_day relative to `end_date`,
     advancing to next month if past.
   - `ytd_interest` from `SUM(amount)` of `category='Interest'`
     transactions on the account in the current year.
   Identity-only fields (`cash_advance_limit`, `cash_advance_available`,
   `date_opened`) stay as static stubs and are tagged with comments.

4. **Coastal_cc coverage.** Extend the same derivation pattern to
   `coastal_cc` so the Chase-shaped card no longer renders an empty
   panel.

5. **Post-seed integrity asserts** — extend the existing block in
   `main()`:
   - No collateral-identity field exists in `loan_details` for any
     account with a linked `vehicle_assets` or `real_estate` row.
   - Every secured loan (type in {loan, mortgage}) with `loan_details`
     has at least one linked asset OR is in the unsecured-loan
     allowlist (`payflex_bnpl`).
   - Every credit-card `payment_due_date` is parseable as MM/DD/YYYY
     AND is on or after the seed `end_date` (no "Past Due" panels).

### PR3 — Frontend swap to composer shape (TBD)

Re-route `backend/routers/reports.py` `account_details`,
`vehicle_details`, `real_estate_details` to call the composer functions
directly. Frontend reads `collateral.{kind, vin, address, ...}`
instead of pulling those fields from `details`. `LOAN_ORDER` in
`AccountDetailsPanel.tsx` drops `vin` / `collateral_description` /
`purchase_price` / `date_opened` (auto + cc) — those become hero-card
content from `collateral`. `orderForType` returns a sentinel for
`investment`/`retirement` types so investment accounts render an
explicit empty-state instead of an alphabetical fallback.

## Verification

PR0 (already verified):
- `python scripts/pii_scan.py --all-tracked` — clean.
- `gh api /search/code?q=<leaked-vin>+repo:wileyqe/Sentry-Finance` — 0 hits.
  (The literal VIN that was leaked is redacted in this prompt to keep
  the file pii_scan-clean. See git history of commit b4d57fe before
  the rewrite if you need it for audit purposes.)
- All Kia / VIN strings absent from rewritten history.

PR1 (verified, commit ac95db9):
- `pytest tests/` 391/391 pass.
- New `tests/test_details_panel_invariants.py` 16/16 pass.
- Migrations apply cleanly: PRAGMA user_version = 37.

PR2 (this PR):
- `python scripts/seed_dummy_data.py --end-date 2026-04-24` completes;
  integrity block reports "Integrity checks passed (snapshots unique,
  liabilities non-positive, no collateral drift, no orphaned secured
  loans, no stale due dates)".
- Smoke: with the seeded DB, `get_loan_panel_bundle('summit_auto')`
  and `get_vehicle_panel_bundle('civic_2020')` return identical
  `collateral` slots; same for `summit_mtg` ↔ Primary Residence.
- `summit_cc` `14_day_payoff` reflects the actual seeded balance
  (was hardcoded 2451.33; now ~$4685 derived from real balance + APR).
- `summit_cc` `payment_due_date` is in the future relative to
  `end_date` (was pinned 05/08/2026; now derived from end_date offset).
- `coastal_cc` panel no longer empty (gets matching derivation set).
- `pytest tests/` 391/391 still green.
- `python scripts/pii_scan.py --all-tracked` still clean.

## Outcomes / Surprises

- **Reordering ripple:** moving `seed_vehicle_assets` /
  `seed_real_estate` ahead of the loan stretch had no other side
  effects — those tables are independent of the post-commit pipeline
  and the loan_details/balance writes that follow.
- **Composer-side drift discovered:** the original
  `get_real_estate_details` returned only the columns from the
  matching `real_estate` row. With v37's append-only identity columns,
  a quarterly valuation row that omits address would have shadowed
  the row that set it. The "latest non-null per column" subquery
  fixes this and is documented in the composer + DAL function.
- **Second Kia leak in the connector:** the audit found a second real
  Kia VIN (Sorento WMI, redacted here for pii_scan cleanliness) embedded
  as a `"VIN: ..."` example comment in `extractors/nfcu_connector.py:1029`.
  PR0 stripped it and the regex pattern still works without the inline
  example.
- **GAP integer encoding:** `vehicle_assets.gap_insurance` is INTEGER
  0/1 at the schema level but exposed as Python bool in
  `get_vehicle_details` and the composer for ergonomic consumer code.
  `add_vehicle` accepts `bool | None` and converts.
