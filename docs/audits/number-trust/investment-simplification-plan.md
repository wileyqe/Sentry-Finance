# Canonical Investment Seed Simplification Plan

Date: 2026-04-29.
Branch: `codex-trusted-seed-audit`.

This plan implements the accepted Phase 17 number-trust decision: the
canonical synthetic seed should optimize for determinism, explainability,
and auditability before any live financial data is trusted.

The Investments page remains outside the current UI-number trust scope.
Investment-derived values on Dashboard, Transactions, Cash Flow, Reports,
and Accounts are in scope.

## Locked Decisions

- Use the canonical trusted seed, not a second fixture.
- Keep one seed version and one synthetic truth.
- Remove canonical-seed growth, losses, dividends, sells, roundups,
  account fees, and price-driven variance from audited investment
  balances.
- Keep investment tables populated so existing APIs and in-scope pages
  retain their expected shape.
- Use monthly transfers/contributions only, including a simplified TSP
  transfer path for the synthetic proof fixture.
- Treat the TSP monthly transfer as an audit-fixture simplification, not
  a live-data claim. Live TSP ingestion should still model the user's
  retired/no-new-contributions reality.

## Canonical Account Contract

All values are cents-first in implementation.

| Account | Starting balance | Monthly transfer | Suggested description | Suggested allocation |
|---|---:|---:|---|---|
| Acorns Synthetic | `$10,000` | `$500` | `ACORNS INVEST TRANSFER` | `VOO 55%`, `IJH 15%`, `IJR 15%`, `IXUS 15%` |
| Fidelity Brokerage | `$50,000` | `$1,000` | `FIDELITY EFT TRANSFER` | existing Fidelity ticker list, equal weight |
| TSP Uniformed Services | `$100,000` | `$1,500` | `TSP CONTRIBUTION TRANSFER` | `TSP_C 50%`, `TSP_S 30%`, `TSP_L2065 20%` |

Contribution dates should be deterministic monthly dates inside the
canonical seed window, from the first full month after seed start through
April 2026. The implementation should centralize the date helper and pin
the expected count in tests. With 36 monthly transfers, expected final
balances are:

| Account | Final balance |
|---|---:|
| Acorns Synthetic | `$28,000` |
| Fidelity Brokerage | `$86,000` |
| TSP Uniformed Services | `$154,000` |
| Combined | `$268,000` |

If implementation selects a different inclusive monthly count, the tests
must state the count and recompute the final balances from the same
central contract.

## Data Shape To Preserve

The simplification should remove financial ambiguity without breaking
existing consumers.

Keep populated:

- `transactions` bank-side transfer rows for each monthly contribution.
- `positions_ledger` rows with positive `share_delta` for contribution
  allocation and at least one `bank_txn_id` link per bank transfer.
- `investment_holdings` rows for each account/ticker snapshot.
- `portfolio_snapshots` rows for each investment/retirement account,
  including a final snapshot on canonical end date `2026-04-27`.
- `benchmark_prices` rows as deterministic flat fixture prices.
- `ticker_metadata` rows for every holding ticker.
- `investment_details` rows, normalized to zero-return/zero-yield style
  values where applicable.
- `tax_buckets` for TSP, using a fixed split whose balances sum exactly
  to the TSP total at each snapshot.

Remove from the canonical seed:

- Fidelity dividend/investment-income transaction rows.
- Fidelity sells.
- Fidelity reinvestments.
- Fidelity SPAXX interest income.
- Acorns roundups.
- Acorns monthly fees.
- Any price drift or market-return effect.

Do not remove production support for these live-data events. Only remove
them from the canonical audit fixture.

## Implementation Sequence

1. Add central seed constants in `scripts/dummy_data/generator.py`.
   Include account ids, starting cents, monthly cents, allocations,
   contribution descriptions, and the canonical fixed price.
2. Replace separate Acorns/Fidelity/TSP investment generation logic with
   a shared deterministic helper, or make the existing wrappers delegate
   to one helper.
3. Generate bank-side contribution transactions before investment tables
   are written, so balance snapshots and post-commit pipeline outputs see
   the same facts.
4. Write baseline `positions_ledger` rows on the seed start date.
5. Write monthly positive-share ledger rows for every contribution.
   Link exactly one ledger row per account/month to the bank transaction
   through `positions_ledger.bank_txn_id`; additional allocation rows may
   remain unlinked.
6. Write holdings and portfolio snapshots from the same formula:
   `starting_balance + sum(contributions through as_of)`.
7. Set fixed close prices, cost basis equal to market value, zero gain
   and loss, and zero cash balance unless a page explicitly requires an
   investment-cash example.
8. Write TSP tax buckets from a fixed split and assert the bucket sum
   equals the TSP portfolio total.
9. Regenerate the trusted manifest and canonical fingerprint.
10. Update API audit expectations and the latest promoted audit report.
11. Update docs and lineage in the same implementation pass.

## Tests And Proof Checks

Add or update trusted-seed tests for these invariants:

- Clean temp DB seed runs produce identical normalized fingerprints.
- No seed path attempts live market or network access.
- Latest investment balances equal the account contract.
- Monthly contribution counts match the pinned schedule.
- Every investment transfer transaction has a linked ledger row.
- No canonical rows exist for removed behaviors:
  - `DIVIDEND`,
  - `REINVESTMENT`,
  - `SELL`,
  - `DEPOSIT` if no longer needed,
  - investment-income transaction rows,
  - Acorns roundups,
  - Acorns monthly fees.
- Every benchmark price for canonical investment tickers is flat.
- Every holding has `market_value == cost_basis == shares * close_price`.
- Every investment/retirement account has latest holdings and a latest
  portfolio snapshot dated `2026-04-27`.
- TSP tax bucket balances sum exactly to TSP total and keep the fixed
  split.
- Dashboard net worth, Accounts balances, Reports totals, Cash Flow
  transfers, and Transactions visible transfer rows still pass the
  number-trust audit.

Expected verification commands:

```powershell
python scripts/seed_dummy_data.py
python -m pytest tests/test_trusted_seed.py -q
python scripts/audit_number_trust.py --db data/dummy.db
```

Then run the broader backend/frontend checks required by the files
touched in implementation.

## Docs And Lineage To Update

Update during implementation:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/DUMMY_DATA_GENERATION_SPEC.md`
- `docs/audits/number-trust/implementation-decisions.md`
- `docs/audits/number-trust/adversarial-review/round-5-final-synthesis.md`
- `docs/data-lineage/events.yaml`
- `docs/data-lineage/lineage/portfolio_snapshot.yaml`
- `docs/data-lineage/lineage/investment_holdings_snapshot.yaml`
- `docs/data-lineage/lineage/market_price_tick.yaml`
- `docs/data-lineage/lineage/investment_contribution.yaml`
- `docs/data-lineage/lineage/investment_buy.yaml`
- `docs/data-lineage/lineage/investment_implied_buy.yaml`
- `docs/data-lineage/lineage/investment_sell.yaml`
- `docs/data-lineage/lineage/equity_dividend.yaml`
- `docs/data-lineage/lineage/dividend_reinvestment.yaml`
- `docs/data-lineage/lineage/money_market_sweep_interest.yaml`
- `docs/data-lineage/lineage/tax_bucket_snapshot.yaml`
- `docs/data-lineage/lineage/tax_lot_initial.yaml`
- `docs/data-lineage/lineage/ticker_metadata_enrichment.yaml`

Regenerate lineage artifacts:

```powershell
python docs/data-lineage/build_inverse_index.py
python docs/data-lineage/build_diagrams.py
python docs/data-lineage/check_freshness.py
```

## Known Downsides

- The canonical seed becomes less market-realistic.
- Fidelity dividend and reinvestment flows will no longer be exercised
  by the canonical seed; they must remain covered by targeted unit tests
  or a future noncanonical fixture.
- TSP monthly transfers intentionally diverge from live user reality.
  The docs and tests must keep that distinction explicit.
- Fingerprints, manifest row counts, expected audit values, and any
  promoted reports will change.
- Existing charts may look more stepwise because value changes only on
  contribution dates.

These downsides are accepted for this phase because the goal is to prove
that controlled seed facts produce accurate visible numbers before live
financial data is introduced.
