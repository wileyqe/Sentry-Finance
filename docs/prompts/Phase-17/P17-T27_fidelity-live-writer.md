# P17-T27: Fidelity Live Writer

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/36

## Context

Fidelity live-shape readiness found that the live ingest parses Fidelity
history and positions but persists only a SPAXX cash balance. Synthetic
Fidelity, TSP, and Acorns flows already prove the app expects investment
data in `positions_ledger`, `investment_holdings`, and
`portfolio_snapshots`. This slice should make Fidelity fill the existing
investment write module instead of inventing a broad connector framework.

This is an AFK overnight slice suitable for Codex or Claude. Use only
local fixtures/tests; do not log into Fidelity, scrape live data, or touch
credentials.

## Starting State

- `scripts/ingest_fidelity_history.py::persist_to_db` records only the
  latest SPAXX cash balance via `dal.balances.record_balance`.
- `extractors/fidelity_connector.py::_run_ingest` calls that same path.
- `dal/investments_writes.py` already owns holding and portfolio snapshot
  invariants through `record_investment_holdings` and
  `record_portfolio_snapshots`.
- `docs/audits/fidelity-live-shape/mismatch-ledger.md` marks
  `FID-LS-001`, `FID-LS-003`, and `FID-LS-009` as the relevant receipts.
- `tests/test_fidelity_live_shape_contract.py` protects parser shape and
  has xfails for separate follow-up concerns.

## Design Decisions

- Scope is **position-state only**. This slice persists investment state
  rows; it does not create bank-side EFT transactions, dividend/capital-gain
  income transactions, tax-lot source authority, or cost-basis truth.
- Use account identity, not owner identity. Resolve the configured Fidelity
  investment `account_id` before writing; do not use `owner_id` as a
  substitute for account identity. Idempotency must be scoped by
  `account_id`.
- Keep raw Fidelity account numbers outside tracked code. For now this is a
  single-account writer: fail loudly if the parsed Positions CSV contains more
  than one `Account Number`. Structure the writer API so a future
  account-context object can pass the internal `account_id` and source-account
  metadata in before persistence.
- Put Fidelity-specific mapping in a narrow writer module, for example
  `dal/fidelity_investment_writes.py` or `dal/investment_sources/fidelity.py`.
  Keep `dal/investments_writes.py` source-agnostic and use it for validated
  holdings/snapshot writes.
- Persist the full reconstructed daily history produced by the existing
  pipeline, bounded by the parsed history window / current `START_DATE`, not
  only the latest day.
- Create idempotent `positions_ledger` rows. A small schema addition such as
  nullable `positions_ledger.source_key` plus a unique index on
  `(account_id, source, source_key)` for non-null keys is acceptable. Stable
  source keys should be derived from normalized Fidelity row facts and scoped
  to the account. If an existing row is updated, preserve `bank_txn_id`.
- For `portfolio_snapshots`, replace exact `(account_id, timestamp)` rows that
  this writer owns before reinserting. `investment_holdings` already has
  upsert semantics through `record_investment_holdings`.
- Emit canonical ledger transaction types:
  `BOUGHT` parser rows become `BUY`; `REINVESTMENT` stays
  `REINVESTMENT`; `SOLD` becomes `SELL`; reconstructed starting shares become
  `INITIAL_BASELINE`; `EXPIRED` stays `EXPIRED`;
  `Electronic Funds Transfer Received (Cash)` becomes `DEPOSIT`;
  `Electronic Funds Transfer Paid (Cash)` becomes `WITHDRAWAL`.
- Create zero-share Fidelity EFT marker rows for `DEPOSIT` and `WITHDRAWAL`
  actions. These rows are the Fidelity-side evidence that cash moved into or
  out of the investment lane. They must not create bank-side transactions,
  infer a security buy/sale, or set `bank_txn_id`; P17-T28 links them to
  imported bank transactions when both ends of the evidence exist.
- Treat `EXPIRED` as non-cash position removal only. It can represent rights,
  warrants, options, temporary corporate-action securities, or cancelled /
  worthless positions. It reduces shares, does not move SPAXX/cash, does not
  imply sell proceeds, and does not decide tax treatment.
- SPAXX/FDRXX are cash equivalents. They should flow into
  `portfolio_snapshots.cash_balance`, not non-cash `investment_holdings` rows
  or equity `positions_ledger` rows.
- Do not populate `investment_holdings.cost_basis` or
  `positions_ledger.cost_basis_dec` in this slice. Leave the existing
  aggregate `loan_details.cost_basis` side path alone unless it blocks this
  writer. P17-T30 owns per-position basis and retirement of that legacy path.

## Task

1. Read `CLAUDE.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md` sections
   3.4, 4.2, 4.6, and 4.7, plus the Fidelity live-shape audit files.
2. Add a narrow Fidelity live writer interface that takes parsed history,
   parsed positions, reconstructed daily snapshots, and resolved account
   context, then persists:
   `positions_ledger`, `investment_holdings`, and `portfolio_snapshots`.
3. Use `dal/investments_writes.py` for holdings and snapshots. Extend DAL
   write helpers only if a Fidelity-backed invariant truly belongs there.
4. Materialize `INITIAL_BASELINE` rows for reconstructed starting shares and
   position-state ledger rows for supported Fidelity actions.
5. Write one `investment_holdings` row per non-cash ticker per reconstructed
   day and one `portfolio_snapshots` row per reconstructed day.
6. Write zero-share `DEPOSIT` / `WITHDRAWAL` marker rows for Fidelity EFT cash
   actions so P17-T28 can link the bank-side cash leg without pretending a
   later security purchase is the transfer event.
7. Preserve SPAXX/FDRXX as cash-equivalent handling for this slice.
8. Preserve settlement dates where the parsed history provides them; blanks are
   acceptable for cash-only or source-blank rows.
9. Keep connector failures isolated and consistent with existing refresh
   behavior.

## Non-Goals

- Do not implement Fidelity EFT cash-leg linking. That is P17-T28.
  This slice creates the unlinked Fidelity-side `DEPOSIT` / `WITHDRAWAL`
  marker rows that P17-T28 consumes.
- Do not emit dividend or capital-gain income transactions. That is
  P17-T29.
- Do not populate per-position or lot-forming cost basis. That is P17-T30.
- Do not decide tax-lot source authority. That is P17-T32.
- Do not build a generic connector investment result framework yet.
- Do not support multiple Fidelity accounts in one export yet. Fail clearly
  instead of merging account histories.
- Do not log into Fidelity, scrape live data, or touch credentials.
- Do not infer realized loss, tax treatment, or sell proceeds for `EXPIRED`
  rows.

## Verification

- Add/extend tests around the new writer using redacted Fidelity fixtures.
- Add an idempotency regression showing reruns do not duplicate
  `positions_ledger` or `portfolio_snapshots` rows.
- Add tests for account-scoped identity: single configured account succeeds;
  multiple Positions CSV account numbers fail loudly.
- Add tests for canonical transaction-type mapping, including
  `BOUGHT -> BUY`, `INITIAL_BASELINE`, `DEPOSIT`, `WITHDRAWAL`, and non-cash
  `EXPIRED` share removal.
- Add tests proving Fidelity EFT marker rows are zero-share,
  account-scoped, idempotent, and leave `bank_txn_id` unset for P17-T28.
- Add tests proving SPAXX/FDRXX remain cash equivalents and are not persisted
  as non-cash holdings.
- Add tests proving this slice leaves cost-basis fields unset / unclaimed.
- Run targeted tests:
  `pytest tests/test_fidelity_live_shape_contract.py tests/test_dal_investments_writes.py -x --tb=short`
- Run any affected investment/flow/accountability tests identified by the
  graph context check.
- Run `python scripts/audit_reference_clock_usage.py`.

## Agent Shutdown

Create a branch named `codex/p17-t27-fidelity-live-writer` or
`claude/p17-t27-fidelity-live-writer` depending on the agent. Commit the
work with a clear message. Do not merge. Leave a summary with tests run,
files changed, and remaining follow-ups.
