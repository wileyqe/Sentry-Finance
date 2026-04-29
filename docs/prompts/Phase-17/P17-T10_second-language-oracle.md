# P17-T10 Second-Language Oracle Foundation

## Context

The accepted number-trust plan requires a stronger independent oracle before
the project claims high confidence in UI numbers. The Python audit is useful,
but it runs in the same language and process family as the backend.

## Starting State

- The Python audit checks selected Dashboard and Cash Flow API values across
  Household, Quintin, and Amy.
- The registry has explicit owner/view state for first-pass values.
- No second-language expected-value layer exists.

## Task

- Add a Node/JavaScript oracle that reads the canonical SQLite database
  directly with `sql.js`.
- Do not import Python DAL helpers, backend routers, frontend code, or Python
  audit formulas.
- Add a neutral oracle vocabulary artifact for shared category semantics.
- Wire the Python audit to run the Node oracle and fail on any expected-value
  mismatch.
- Record the Node oracle status in the JSON and Markdown audit reports.

## Verification

- `node scripts/number_trust_oracle.mjs --db data/dummy.db`
- `python -m pytest tests/test_audit_vocabulary.py -q`
- `python scripts/audit_number_trust.py --db data/dummy.db`
- Confirm the latest report has `Second-language oracle:
  node-sqljs-oracle-v1` and `Diff count: 0`.

## Outcome

The first-pass API audit now has a second-language raw-fact oracle layer for
the current registered Dashboard and Cash Flow values. Remaining work is
broader registry coverage, DOM selectors/browser comparison, and the
one-command proof gate.
