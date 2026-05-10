# P17-T47: TSP Statement Parser Hardening

## Context

P17-T45 found the TSP statement parser is close to the live-shape contract, but
it still needs trust-bar guards around reconciliation, partial per-fund parses,
tax-bucket placeholders, and connector partial-persistence behavior.

## Starting State

- `dal/parsers/tsp_statement.py` recognizes TSP PDFs, parses statement date,
  top-line balance, fund units, NAV, and per-fund balances.
- The parser blocks a recognized positive-balance statement when no per-fund
  detail is found.
- It does not enforce top-line vs per-fund sum agreement.
- It writes a 100% traditional placeholder `tax_buckets` row because statements
  do not expose the live Roth/traditional split.
- `extractors/tsp_connector.py` catches holdings persistence failures as
  non-fatal, which can leave a fresh balance with stale holdings.

## Task

1. Add top-line vs per-fund reconciliation with a documented tolerance.
2. Harden partial fund-row handling so missing units/NAV/balance does not
   silently drop a held fund.
3. Make placeholder tax-bucket semantics explicit in parser preview and
   downstream docs/tests.
4. Decide whether statement commits need source-keyed `positions_ledger`
   evidence for unit-change auditability.
5. Ensure future connector runs cannot record a trusted fresh TSP balance while
   holdings persistence fails.

## Non-Goals

- Do not scrape live TSP or use credentials.
- Do not infer a real tax-bucket split from the statement.
- Do not change Fidelity parser/audit/cost-basis paths.

## Verification

- Add parser fixture tests for reconciled, unreconciled, and partial-fund PDFs
  or text fixtures.
- Run touched parser/document-ingest tests.
- If timeframe or reference-date behavior changes, run
  `python scripts/audit_reference_clock_usage.py`.
