# P17-T30: Fidelity Cost-Basis Persistence

## Context

Fidelity live-shape readiness found that Positions CSV cost basis is available
per holding, but the current live connector sums it into `loan_details` instead
of writing the investment tables that downstream Investments readers use.

This slice should make cost-basis source authority explicit and readable:
per-position basis belongs with investment holdings; lot-forming basis belongs
with evidenced ledger rows; the legacy aggregate `loan_details.cost_basis`
path should be retired, bypassed, or documented only as a compatibility shim.

## Starting State

- `docs/audits/fidelity-live-shape/mismatch-ledger.md` marks `FID-LS-006` as
  a block: Positions CSV has `Cost Basis Total` / `Average Cost Basis`, but the
  connector stores only a summed basis in `loan_details`.
- `docs/audits/fidelity-live-shape/live-shape-contract.md` section 6 says
  current consumers read `investment_holdings.cost_basis` and
  `positions_ledger.cost_basis_dec`; a single summed `loan_details` value is
  not sufficient.
- `extractors/fidelity_connector.py::_ingest_positions_csv` currently writes
  `details={"cost_basis": ...}` through `record_loan_details`.
- `dal/account_details_composer.py` still merges `loan_details` into
  brokerage account panels for historical cash-side details, so naming and
  compatibility need care.
- P17-T27 should already have established the Fidelity live writer for
  holdings, snapshots, and position-state ledger rows. Do not take this task
  before that writer exists.

## Task

1. Read `CLAUDE.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, and the
   Fidelity live-shape audit files.
2. Parse Positions CSV cost-basis fields with Fidelity money-format coverage,
   including blank SPAXX/FDRXX basis fields and parenthesized negative
   gain/loss values where relevant.
3. Persist `Cost Basis Total` to `investment_holdings.cost_basis` for
   non-cash positions. Use `Average Cost Basis` only as a validation or
   fallback signal, not as the preferred source when total basis is present.
4. Populate `positions_ledger.cost_basis_dec` only when trade/reinvestment
   history provides enough evidence for the lot-forming row. Do not invent lot
   basis from aggregate holdings when the source row does not support it.
5. Remove, bypass, or explicitly quarantine the aggregate Fidelity
   `loan_details.cost_basis` write path. If keeping a compatibility bridge,
   document why it remains and ensure Investments readers do not depend on it
   for per-position truth.
6. Clean up misleading account-details naming touched by this path when doing
   so reduces confusion without broad churn. Prefer `investment_details`,
   `account_details`, or a narrowly named compatibility helper over implying
   Fidelity is debt-related.

## Non-Goals

- Do not decide tax-lot source authority for GainsKeeper, closed positions,
  statements, trade confirmations, or 1099-B reconciliation. That is P17-T32.
- Do not implement Fidelity EFT linking or dividend/capital-gain income
  transaction writing. Those are P17-T28 and P17-T29.
- Do not create cost basis for SPAXX/FDRXX cash-equivalent rows.
- Do not rewrite unrelated `loan_details` consumers for mortgages, auto loans,
  credit cards, APY history, or historical compatibility unless directly
  needed to retire the Fidelity aggregate basis path.

## Verification

- Add/extend tests for Fidelity Positions cost-basis parsing and persistence
  through the writer interface.
- Add a regression that proves live Fidelity per-position basis reaches
  `investment_holdings.cost_basis`.
- Add a regression that proves the aggregate `loan_details.cost_basis` path is
  no longer the Investments source of truth, or that any retained compatibility
  shim is ignored by investment holdings/lots.
- Run targeted tests:
  `pytest tests/test_fidelity_live_shape_contract.py tests/test_dal_investments_writes.py -x --tb=short`
- Run any affected investment details/panel and number-trust Investments tests
  surfaced by the graph context check.
- Run `python scripts/audit_reference_clock_usage.py`.

## Agent Shutdown

Create a branch named for the agent lane, for example
`codex/p17-t30-fidelity-cost-basis` or
`claude/p17-t30-fidelity-cost-basis`. Commit the work with a clear message. Do
not merge. Leave a summary with tests run, files changed, retired compatibility
paths, and any remaining naming cleanup that was intentionally deferred.
