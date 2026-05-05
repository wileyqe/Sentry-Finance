# P17-T29: Fidelity Dividend And Capital-Gain Income Writer

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/40

## Context

Live Fidelity parser output classifies dividend and capital-gain actions,
but those rows do not become cash transactions. Cash-flow and reinvestment
truth require positive transactions with `category='Investment Income'`
and no `transfer_tag`, plus enough structure for reinvestment pairing.

This is an AFK overnight slice for Codex or Claude after P17-T27 lands.
Use only local fixtures/tests.

## Starting State

- `tests/test_fidelity_live_shape_contract.py` has an expected xfail for
  dividend rows emitting `Investment Income`.
- `tests/test_dividend_interest_flows.py` defines dividend/reinvestment
  reporting behavior.
- `docs/data-lineage/ACTION_ITEMS.md` AI-016 records the canonical
  category requirement.
- `docs/ROADMAP.md` tracks `FID-LS-005` and `FID-LS-014`.
- Fidelity History CSV rows expose factual `Run Date`, optional
  `Settlement Date`, action text, symbol, amount, and cash balance. Do not
  invent dates when those fields are absent.

## Design Decisions

- Do not add a dedicated dividend/capital-gain subtype schema in this slice.
  Preserve subtype/source evidence by keeping the original Fidelity action in
  `transactions.raw_description` and by using a clear normalized description.
  P17-T32 owns tax-source authority and any future tax-subtype schema.
- Use `Run Date` as the factual `transactions.posting_date` and
  `transaction_date` for dividend and capital-gain cash transactions. Fidelity
  defines run date as the transaction date, while settlement date is a separate
  trade-settlement fact. Preserve settlement dates on trade/ledger rows where
  P17-T27/#36 has source evidence, but do not month-shift income from `Run Date`
  to an inferred settlement date.
- If a dividend/capital-gain row lacks a parseable `Run Date` or a positive
  amount, skip it, write nothing, and report it in the writer summary. Missing
  factual date/amount evidence must not be guessed.
- Use transaction descriptions that start with the ticker so the existing
  reinvestment matcher can pair to `positions_ledger` rows. Examples:
  `VOO DIVIDEND`, `QQQM SHORT-TERM CAP GAIN`, `VOO LONG-TERM CAP GAIN`,
  `SPAXX DIVIDEND`. Set `merchant` to the ticker where the write path supports
  it.
- Make rows idempotent with a deterministic Fidelity source id, passed through
  `institution_txn_id`, scoped by account and source facts. Example shape:
  `fidelity-income:{account_id}:{posting_date}:{symbol}:{amount_cents}:{normalized_action}:{same_day_sequence}`.
  The sequence only distinguishes truly duplicate same-day rows with the same
  ticker/action/amount.
- SPAXX/FDRXX are cash equivalents. Emit the positive `Investment Income` cash
  transaction when Fidelity reports SPAXX/FDRXX dividend income, but do not
  create or require an illiquid reinvestment flow for cash-equivalent tickers.
  SPAXX/FDRXX sweep "reinvestment" remains brokerage cash / `STORED_LIQUID`,
  not `STORED_ILLIQUID`.
- Keep the implementation in a narrow Fidelity income writer/helper called from
  the live Fidelity writer after P17-T27/#36. Route cash transactions through
  `dal.transactions.upsert_transactions()`. Do not add Fidelity-specific
  dividend rules to shared reporting modules except tests proving existing flow
  behavior.

## Task

1. Read P17-T27 output. If the live writer is absent, stop and report
   blocked.
2. Convert live `DIVIDEND RECEIVED` and `CAP GAIN` Fidelity rows into
   posted cash transactions with positive `signed_amount`,
   `direction='Credit'`, no `transfer_tag`, and
   `category='Investment Income'`.
3. Preserve distribution subtype as source evidence, not as a new schema:
   original Fidelity action in `raw_description`, normalized ticker-first
   description in `description`, and ticker in `merchant` when practical.
4. Pair same-day reinvestment evidence to the relevant ledger shape for
   non-cash-equivalent tickers without inventing tax-lot authority. Do not
   classify SPAXX/FDRXX sweep reinvestment as illiquid.
5. Make reruns idempotent via deterministic `institution_txn_id` values.
6. Return or log a structured summary with at least written, unchanged,
   skipped_missing_date, skipped_non_positive_amount, skipped_cash_equivalent_reinvestment,
   and blocked/unsupported counts as applicable. Redact account numbers.

## Non-Goals

- Do not implement EFT linking. That is P17-T28.
- Do not decide tax-lot source authority. That is P17-T32.
- Do not add a dividend/capital-gain subtype table or column in this slice.
- Do not broaden category vocabulary unless tests prove existing vocabulary
  is insufficient.
- Do not synthesize missing dates, settlement dates, amounts, or tax-lot facts.
- Do not log into live institutions or use credentials.

## Verification

- Promote or replace the Fidelity dividend xfail with passing coverage.
- Add targeted writer tests for:
  - `DIVIDEND RECEIVED` and short/long-term `CAP GAIN` rows becoming posted
    positive `Investment Income` transactions.
  - ticker-first descriptions, source action in `raw_description`, and
    deterministic `institution_txn_id`.
  - rerun idempotency.
  - missing `Run Date` / missing or non-positive amount rows writing nothing.
  - SPAXX/FDRXX dividend income staying cash-equivalent / liquid and not
    creating an illiquid reinvestment flow.
  - equity/fund same-day reinvestment still pairing in flow tests.
- Run:
  `pytest tests/test_fidelity_live_shape_contract.py tests/test_dividend_interest_flows.py -x --tb=short`
- Run relevant cash-flow invariant tests:
  `pytest tests/test_cashflow_invariants.py -x --tb=short`
- Run any targeted Fidelity income-writer tests added in this slice.

## Agent Shutdown

Use branch `codex/p17-t29-fidelity-dividend-income` or
`claude/p17-t29-fidelity-dividend-income`. Commit and stop. Do not merge.

## Outcomes (post-merge, 2026-05-05)

**Status:** `[v]` complete. Merged via PR [#46](https://github.com/wileyqe/Sentry-Finance/pull/46) (`8e087a2`). Issue #40 closed.

**What was built (autonomous Claude scheduled run, 15:25 EDT):**
- `bdddb51` ("feat(fidelity): add dividend and capital-gain income writer (P17-T29)") — new `dal/fidelity_dividend_income.py` converts `DIVIDEND RECEIVED`, `SHORT-TERM CAP GAIN`, and `LONG-TERM CAP GAIN` rows to posted `Investment Income` cash transactions. Positive `signed_amount`, `direction='Credit'`, no `transfer_tag`, ticker-first descriptions, deterministic `institution_txn_id` for idempotent reruns. SPAXX/FDRXX dividends written cash-equivalent.
- 11 targeted tests in `tests/test_fidelity_dividend_income.py`; FID-LS-005 xfail replaced with passing writer-level coverage; integrated into `scripts/ingest_fidelity_history.py persist_to_db()`; lineage updated.
- Review-driven fix: `d8b608f` ("fix(fidelity): stabilize dividend-income txn ids across reruns") — additional id determinism.
- Merge resolution: `6f1e011` ("merge main into pr46 and resolve fidelity ingest integration").

**Follow-ups:** None known.

**Note:** Outcomes section added retroactively during the 2026-05-05 multi-PR loop-closure pass.
