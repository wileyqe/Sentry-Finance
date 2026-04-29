# P17-T11 Five-Page Number Registry Expansion

## Context

The number-trust proof needs a durable map of the visible numbers and data
points on Dashboard, Transactions, Cash Flow, Reports, and Accounts before
the oracle/API/DOM audit can be expanded safely.

## Starting State

- First-pass Dashboard and Cash Flow values are API/oracle audited across
  Household, Quintin, and Amy.
- The second-language Node oracle covers those first-pass values.
- Transactions, Reports, Accounts, and many secondary Dashboard/Cash Flow
  values are not yet registered.

## Task

- Expand `docs/audits/number-trust/ui-number-registry.yaml` across the five
  scoped pages.
- Preserve the distinction between proved values and registered-but-pending
  values.
- Add registry validation so every value declares route, owner/view state,
  API source, formatter, selector status, and audit stage.
- Update reports and docs so the proof claim does not overstate coverage.

## Verification

- `python -m pytest tests/test_audit_vocabulary.py -q`
- `node scripts/number_trust_oracle.mjs --db data/dummy.db`
- `python scripts/audit_number_trust.py --db data/dummy.db`
- Confirm the latest report shows `Diff count: 0`, 234 registered
  value/view contexts, 30 API/oracle-audited contexts, and 204 pending
  contexts.

## Outcome

The registry now covers value families on Dashboard, Transactions, Cash Flow,
Reports, and Accounts for Household, Quintin, and Amy. Most newly registered
values remain `registered_pending`; the next work is to move them into the
second-language oracle/API audited bucket, then add DOM selectors and browser
comparison.
