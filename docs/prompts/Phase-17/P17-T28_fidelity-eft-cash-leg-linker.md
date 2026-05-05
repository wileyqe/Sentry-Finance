# P17-T28: Fidelity EFT Cash-Leg Linker

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/41

## Context

Shape B investment transfers require a bank-side transaction linked to one
primary brokerage ledger row through `positions_ledger.bank_txn_id`.
Synthetic Acorns and Fidelity prove this path. Live Fidelity history has
`Electronic Funds Transfer Received/Paid (Cash)` rows, but no live linker
currently stamps `transfer_tag`, `investment_link`, or `bank_txn_id`.

This slice is about evidence from both ends. A bank-import row by itself is
only a candidate; a Fidelity EFT marker row by itself is only a candidate.
The app should call the transfer confirmed only when both rows exist and the
match is unique.

This is an AFK overnight slice for Codex or Claude after P17-T27 lands.
Use only local fixtures/tests.

## Starting State

- P17-T27 should provide Fidelity `positions_ledger` rows.
- P17-T27 should create zero-share Fidelity EFT marker rows:
  `DEPOSIT` for `Electronic Funds Transfer Received (Cash)` and
  `WITHDRAWAL` for `Electronic Funds Transfer Paid (Cash)`. These rows are
  the Fidelity-side anchor for this issue.
- `docs/audits/fidelity-live-shape/mismatch-ledger.md` tracks
  `FID-LS-004` and AI-010.
- `dal/reports/flow.py` and migration v43 consume
  `positions_ledger.bank_txn_id` for Shape B transfer reporting.
- `tests/test_flow_shape_b_brokerage.py` and
  `tests/test_investment_contributions_view.py` define the expected shape.

## Design Decisions

- This is **link-only**. Do not synthesize missing bank transactions from
  Fidelity rows. If the imported bank-side row is absent, leave the Fidelity
  marker unlinked and report it as unmatched.
- Match only when there is exactly one safe candidate:
  exact absolute amount to the cent, opposite cash-flow direction, and a
  `posting_date` within plus/minus 3 calendar days of the Fidelity EFT date.
- Direction mapping:
  Fidelity `DEPOSIT` / EFT received means money moved bank -> Fidelity, so the
  bank-side match must be a debit / negative `signed_amount`.
  Fidelity `WITHDRAWAL` / EFT paid means money moved Fidelity -> bank, so the
  bank-side match must be a credit / positive `signed_amount`.
- Eligible bank-side transactions are posted liquid-account rows only:
  checking, savings, money-market, or other existing cash-like account types.
  Do not match investment, brokerage, retirement, HSA, debt, or inactive rows.
- Do not match a bank transaction that already has a `transfer_tag`, already
  has `investment_link`, or is already referenced by any
  `positions_ledger.bank_txn_id`.
- Description matching is supportive only. Bank descriptions vary; amount,
  direction, date window, account type, and uniqueness are the hard contract.
- Link to the existing Fidelity EFT marker row, not a later `BUY` or
  `REINVESTMENT`. Bank -> Fidelity/SPAXX is the lane movement; SPAXX ->
  security is internal investment-lane redeployment.
- Write the same Acorns-compatible shape:
  `transactions.transfer_tag = 'invest:{primary_ledger_id}'`,
  `transactions.investment_link = '{primary_ledger_id}'`, and
  `positions_ledger.bank_txn_id = '{bank_transaction_id}'` on exactly one
  marker row.
- Inbound bank -> Fidelity matches should set the bank transaction category to
  `Investments` unless a `category_overrides` row exists for that transaction.
  Outbound Fidelity -> bank matches should set the bank transaction category to
  `Transfers` unless a manual override exists. The link fields remain the
  accounting truth; category is the human-readable lane label.
- Inbound linked `DEPOSIT` markers count as investment-lane contributions even
  though `share_delta = 0`. Outbound linked `WITHDRAWAL` markers are
  investment-lane outflows, not negative contributions.
- Guard against double-counting. Existing Shape B cash-flow/accountability
  paths already count inbound linked bank debits through
  `positions_ledger.bank_txn_id`; do not add a second inbound counting path.
- Unmatched or ambiguous candidates must not mutate data. Return a structured
  summary with at least `linked`, `unmatched_fidelity_efts`,
  `ambiguous_matches`, `already_linked`, and `skipped`.
- Logs/summaries may include redacted marker ids, dates, amounts, directions,
  and candidate transaction ids. Do not log raw account numbers or credentials.
- Place the Fidelity matching rules in a narrow Fidelity module, for example
  `dal/fidelity_eft_linker.py` or
  `dal/investment_sources/fidelity_eft_linker.py`. Do not grow another
  institution-specific branch inside `backend/result_writer.py` unless it is
  only orchestration glue.
- Required invocation is after Fidelity ingest writes the P17-T27 marker rows.
  Design the callable to be safely rerunnable and usable by a future bank-side
  refresh hook, but do not broadly wire every bank refresh unless tests prove
  the search is bounded.

## Task

1. Read P17-T27 output before starting. If P17-T27 is absent, stop and
   report blocked. If P17-T27 does not create zero-share `DEPOSIT` /
   `WITHDRAWAL` marker rows, stop and report blocked rather than linking to
   later security buys.
2. Add a narrow Fidelity EFT linker that matches existing Fidelity EFT marker
   rows to existing imported bank-side transactions using the design-decision
   policy above.
3. On confirmed matches, set the Acorns-compatible transfer/link fields and
   stamp exactly one Fidelity marker row with `bank_txn_id`.
4. Preserve the signed-amount invariant. Do not create bank-side transactions.
5. Update the `v_investment_contributions` / reporting semantics only as much
   as needed so linked zero-share Fidelity `DEPOSIT` rows count as
   `user_contribution`, and linked `WITHDRAWAL` rows can surface as a distinct
   investment-lane outflow without subtracting from inbound contributions.
6. Make reruns idempotent and observable.

## Non-Goals

- Do not implement holdings/snapshots. That is P17-T27.
- Do not implement dividend/capital-gain income. That is P17-T29.
- Do not replace the reconciliation engine with a generic matcher.
- Do not create bank-side transaction rows from Fidelity evidence.
- Do not link Fidelity EFT rows to later `BUY`, `REINVESTMENT`, sale, or
  SPAXX dividend rows.
- Do not overwrite manual category overrides.
- Do not log into live institutions, use credentials, or read raw exports
  outside the local fixture/test paths.

## Verification

- Add tests for inbound `DEPOSIT` and outbound `WITHDRAWAL` marker linking.
- Add tests for exact amount, opposite direction, plus/minus 3 day matching.
- Add tests proving ambiguous same-amount candidates and missing bank rows
  remain unlinked and appear in the structured summary.
- Add tests proving already-linked rows are idempotent and not relinked.
- Add tests proving inbound linked rows become category `Investments` and
  outbound linked rows become category `Transfers`, while manual
  `category_overrides` are preserved.
- Add tests proving inbound zero-share `DEPOSIT` markers count once as
  investment-lane contributions and do not double-count in
  `STORED_ILLIQUID`, accountability user contributions, or
  `v_investment_contributions`.
- Add tests proving outbound `WITHDRAWAL` markers are excluded from income /
  spending and are represented as investment-lane outflows where supported,
  not negative user contributions.
- Run:
  `pytest tests/test_flow_shape_b_brokerage.py tests/test_investment_contributions_view.py -x --tb=short`
- Run targeted Fidelity writer/linker tests.
- Run `python scripts/audit_reference_clock_usage.py`.

## Agent Shutdown

Use branch `codex/p17-t28-fidelity-eft-linker` or
`claude/p17-t28-fidelity-eft-linker`. Commit and stop. Do not merge.
