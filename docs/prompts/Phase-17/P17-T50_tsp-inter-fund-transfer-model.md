# P17-T50: TSP Inter-Fund Transfer Model

## Context

P17-T45 defined future TSP inter-fund transfers as intra-account reallocations,
not income, spending, bank transfers, or user contributions.

## Starting State

- `positions_ledger` can represent share deltas and source provenance.
- `v_investment_contributions` classifies positive share-delta rows with
  `bank_txn_id IS NULL` as `intra_account_credit`, which is safer than
  `user_contribution` for future IFT destination legs.
- No TSP-specific inter-fund-transfer writer or parser contract exists.

## Task

1. Choose the canonical IFT representation: explicit
   `INTER_FUND_TRANSFER` rows or paired TSP-only `SELL`/`BUY` rows with
   contribution exclusions.
2. Add tests proving IFT rows do not affect income, spending, transfer flows,
   or user-contribution totals.
3. Add source-key/idempotency guidance for statement and future connector
   evidence.
4. Ensure holdings and portfolio snapshots reflect post-transfer units without
   changing top-line value except for market movement and rounding.
5. Update lineage docs for the new event shape.

## Non-Goals

- Do not create bank-side transactions for IFTs.
- Do not model withdrawals, loans, rollovers, or new payroll contributions in
  this slice.
- Do not touch Fidelity work in issues #77/#78/#69.

## Verification

- Add focused tests for contribution exclusion and cash-flow/accountability
  neutrality.
- Run touched DAL/report tests.
- Run `python scripts/audit_reference_clock_usage.py` if date semantics change.
