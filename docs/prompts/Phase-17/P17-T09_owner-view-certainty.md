# P17-T09 Owner/View Certainty

## Context

The number-trust audit must prove not only that a visible number is correct,
but also that it is correct for the active UI view. Dashboard, Transactions,
Cash Flow, Reports, and Accounts all rely on the Household / owner selector.
The first audit foundation covered selected Dashboard and Cash Flow API values
without making owner/view identity part of the registered number identity.

## Starting State

- The canonical trusted seed is fixed at `trusted-2026-04-27-v1`.
- Runtime context and frontend reference-date consumption are complete.
- The audit registry covers selected Dashboard and Cash Flow values.
- The audit runner compares raw oracle values to API responses, but it needs
  an explicit owner/view matrix.
- The trusted seed has Household and Quintin account data. Amy has payroll
  snapshots but no account balances in the canonical fixture, so her cash-flow
  values are payroll-only while account-balance values are empty/zero.

## Task

- Add owner/view state declarations to
  `docs/audits/number-trust/ui-number-registry.yaml`.
- Extend `scripts/audit_number_trust.py` so each registered first-pass value is
  audited for Household, Quintin, and Amy.
- Keep oracle calculations independent of production DAL report helpers.
- Include owner/view context in audit JSON and Markdown reports.
- Add tests that fail if registry values omit owner/view state.
- Update roadmap and number-trust decision docs with the new certainty
  boundary.

## Verification

- `python -m pytest tests/test_audit_vocabulary.py -q`
- `python scripts/audit_number_trust.py --db data/dummy.db`
- Confirm the latest report has `Diff count: 0`.

## Outcome

The API-level number-trust baseline should prove selected Dashboard and Cash
Flow values across the first explicit owner/view matrix. Remaining proof work
then moves to the second-language oracle, broader registry coverage, DOM
selectors, and one-command proof gate.
