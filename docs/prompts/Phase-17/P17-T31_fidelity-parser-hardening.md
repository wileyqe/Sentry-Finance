# P17-T31: Fidelity Live-Shape Parser Hardening And Source Capture

## Context

The Fidelity live-shape readiness audit (P17-T26) confirmed that the existing
CSV parser tolerates much of the observed live shape but leaves several
edge-case gaps that must close before single-user live trust. The mismatch
ledger captures the specific receipts: action-verb coverage that has not been
proved by tests, positions-currency formatting (parenthesized negatives, dollar
prefixes, comma grouping, trailing whitespace) that `_clean_number` does not
parse correctly, multi-account scoping that the parser does not enforce, a
missing redacted SELL/closed-position fixture, and the header/footer/encoding
shape that the parser handles today but that has no contract guard against
regressions.

This task is parser-and-fixture hardening only. It does not touch live writers
(P17-T27/T28/T29/T30) or tax-lot source authority (P17-T32). The bar is: every
live-shape mismatch with a parser or source-capture root cause is provably
covered by a redacted fixture and a regression test, so future writers can
trust their inputs.

## Starting State

- `docs/audits/fidelity-live-shape/mismatch-ledger.md` carries the relevant
  receipts:
  - `FID-LS-002` (gap): live verb diversity (`YOU BOUGHT`, `REINVESTMENT`,
    `DIVIDEND RECEIVED`, `CAP GAIN`, EFT in/out, `EXPIRED`) is not fully
    covered by parser tests; unobserved verbs may silently fall to `OTHER`.
  - `FID-LS-008` (cosmetic): live history fractional quantities go to at
    least three decimal places; precision must not narrow in future writers.
  - `FID-LS-010` (cosmetic): two blank pre-header lines plus footer
    disclaimer rows are tolerated by `find Run Date` parsing today but have
    no regression guard; replacing the parser with a naive
    `pd.read_csv(filepath)` would silently regress.
  - `FID-LS-011` (gap): positions currency includes dollar prefixes, comma
    grouping, trailing spaces, and parenthesized negative gain/loss values.
    `_clean_number` does not parse parenthesized negatives, so negative
    gain/loss collapses to zero.
  - `FID-LS-012` (gap): positions CSV includes `Account Number`, but the
    parser does not scope rows by account number. Multiple Fidelity
    accounts in one export could merge into one app account. History CSV
    has no account column in observed exports, so the contract is one
    account per history file or a separately captured account source.
  - `FID-LS-013` (gap): live samples have no `YOU SOLD` rows; sell handling
    exists in the classifier and `get_lots`, but is not exercised by any
    fixture. Until a redacted SELL/closed-position sample exists, sold-out
    lots, realized gains, and closed-position behavior remain unproved.
- `docs/audits/fidelity-live-shape/live-shape-contract.md` sections 1, 2, and
  3 are the canonical description of the live history schema, positions
  schema, and currency/numeric formatting. Section 1's verb table names every
  action substring that must classify correctly.
- `scripts/ingest_fidelity_history.py` is the current parser surface:
  - `_clean_number()` (lines around 56) strips `$`, commas, quotes, and
    whitespace but does not understand `(123.45)` parenthesized negatives.
  - `_classify_action()` (lines around 70-87) maps verb substrings to
    canonical categories.
  - `parse_history_csv()` (lines around 90-147) finds the `Run Date` header,
    drops invalid dates, and cleans numeric columns.
  - `parse_positions_csv()` (lines around 150-173) cleans the same numeric
    columns and drops symbol-less rows but does not scope by account number.
- `tests/test_fidelity_live_shape_contract.py` is the regression gauntlet
  for live-shape claims. Use it as the home for new contract tests unless a
  case clearly belongs in a parser-unit test file.
- `tests/fixtures/fidelity/` holds the existing redacted history and
  positions fixtures. New redacted fixtures go here; keep account numbers
  replaced with `X<redacted>`, descriptions deterministic, and dollar
  amounts scrubbed to dummy values while preserving header/footer noise,
  SPAXX shape, decimal precision, settlement-date presence/absence, and
  currency formatting.
- `raw_exports/fidelity/` is gitignored. The redacted-fixture pipeline used
  in P17-T26 is the only path for converting raw samples into tracked test
  data; do not commit any raw export.

## Task

1. Read `CLAUDE.md`, `docs/ROADMAP.md` (P17-T31 entry), the three audit
   docs under `docs/audits/fidelity-live-shape/`, and the parser surface
   in `scripts/ingest_fidelity_history.py`.
2. **Action-verb coverage (`FID-LS-002`).** Add a parser test matrix that
   asserts the canonical classification for every verb substring named in
   the live-shape contract section 1: `YOU BOUGHT`, `YOU SOLD`,
   `REINVESTMENT`, `DIVIDEND RECEIVED`, `CAP GAIN` (short-term and
   long-term where the live row distinguishes), `Electronic Funds Transfer
   Received (Cash)`, `Electronic Funds Transfer Paid (Cash)`, and
   `EXPIRED`. Add explicit assertions that an unrecognized verb falls to
   `OTHER` and is surfaced in a structured "unknown action" log/counter so
   silent fallthrough cannot hide future Fidelity changes. Do not broaden
   the canonical category vocabulary in this slice.
3. **Money/numeric formatting hardening (`FID-LS-011`).** Either harden
   `_clean_number` to parse parenthesized negatives (`(123.45)` →
   `-123.45`) or introduce a positions-specific money parser that does so.
   Cover: dollar prefixes, comma grouping, trailing whitespace, blank cells,
   integer values, decimal values with three or more decimal places,
   scientific notation if observed. Add unit tests for each format and a
   contract test that proves a parenthesized negative gain/loss in a
   positions fixture round-trips to a negative number rather than zero.
   Preserve existing behavior: blank/`processing` cells return zero, not
   raise.
4. **Decimal precision contract (`FID-LS-008`).** Add a contract test that
   asserts at least three-decimal fractional quantities (existing fixtures
   preserve `0.196` and `0.755`) survive the parser without truncation.
   This is a regression guard for future writers, not a behavior change.
5. **Header/footer/encoding contract (`FID-LS-010`).** Add a contract test
   that asserts the parser correctly handles: two blank pre-header lines,
   a UTF-8-with-BOM encoding (the live exports are read with
   `utf-8-sig`), and footer/disclaimer rows where `Run Date` does not
   parse as `MM/DD/YYYY`. Pin the behavior so a future replacement with a
   naive `pd.read_csv(filepath)` fails the test.
6. **Multi-account scoping (`FID-LS-012`).** Add an `Account Number`-aware
   scoping check to `parse_positions_csv()` (and to any positions consumer
   in this slice's blast radius) so that positions from multiple Fidelity
   accounts in a single export cannot merge into one app account. The
   parser should either: (a) refuse to merge rows from different
   `Account Number` values into the same downstream account record, or
   (b) emit a structured error/warning that names the conflicting
   accounts. History CSV does not include an account column in observed
   samples; the contract is one account per history file. Document that
   contract in the parser docstring and add a test that proves a
   two-account positions fixture does not silently collapse.
7. **SELL/closed-position source capture (`FID-LS-013`).** If a redacted
   SELL/closed-position sample is available (HItL capture from a real
   live export), commit it as a fixture under `tests/fixtures/fidelity/`
   following the same redaction rules as P17-T26 (dummy ticker,
   `X<redacted>` account number, scrubbed amount preserving sign and
   decimal precision), and add a regression that proves `YOU SOLD` parses
   correctly and the `Action_Type` is `SOLD`. If no sample is available,
   keep the gap explicit: leave `FID-LS-013` open in the ledger, add a
   `pytest.mark.skip` (or xfail-with-strict-true on absence) test that
   names the missing fixture and the redaction expectations, and update
   the audit `README.md` "What This Audit Does Not Cover" section to
   point at the still-missing capture.
8. **Source-row capture (cross-cutting on `FID-LS-002`/`FID-LS-011`).**
   Make sure that every parser path preserves enough source evidence
   (raw action text, raw amount text, `Run Date`, optional
   `Settlement Date`, account number when present) to feed downstream
   writers' `raw_description` / `institution_txn_id` fields. Do not
   collapse raw text into the canonical category or normalized amount in
   the parser output; the writers (P17-T29 already shipped, P17-T27/T28
   later) are the layer that decides what to persist.

## Non-Goals

- Do not write or modify any live Fidelity writer. P17-T27 (live writer),
  P17-T28 (EFT linker), P17-T29 (dividend/income writer, already merged),
  and P17-T30 (cost-basis persistence) own their own slices.
- Do not decide tax-lot source authority. That is P17-T32. This task does
  not consult GainsKeeper, in-page lot detail, Closed Positions, monthly
  statements, or 1099-B.
- Do not modify the synthetic Fidelity seed in `scripts/dummy_data/`.
- Do not log into the live Fidelity site, scrape DOM, or use credentials.
  All work uses redacted local fixtures.
- Do not introduce new canonical action categories beyond those named in
  the live-shape contract. New categories belong with a future
  audit-and-writer slice once a real live row drives them.
- Do not add a tax-distribution subtype or any new schema column. That is
  P17-T32 territory.

## Verification

- `pytest tests/test_fidelity_live_shape_contract.py -x --tb=short`
  passes, with new contract tests covering action verbs, money
  formatting, decimal precision, header/footer/encoding, and multi-account
  scoping.
- Targeted parser-unit tests added in this slice pass.
- Confirm no live writer test regresses:
  `pytest tests/test_fidelity_dividend_income.py -x --tb=short` (P17-T29
  coverage) and any other tests that import the parser surface.
- `python scripts/audit_reference_clock_usage.py` passes (the parser
  must not introduce ad-hoc `date.today()` calls outside the
  reference-clock contract; existing module-level `TODAY = date.today()`
  uses for yfinance windowing are out of scope but should not grow).
- `docs/audits/fidelity-live-shape/mismatch-ledger.md` is updated for any
  receipts whose status changes: `FID-LS-002`, `FID-LS-008`,
  `FID-LS-010`, `FID-LS-011`, `FID-LS-012` should move toward closed once
  their regression covers the gap; `FID-LS-013` either closes (sample
  captured) or is documented as still-open with the missing-fixture
  contract.
- `docs/audits/fidelity-live-shape/README.md` "What This Audit Does Not
  Cover" reflects the new state of SELL/closed-position capture.
- The doc-coupling pre-commit hook passes.

## Agent Shutdown

Use a branch named for the agent lane, for example
`codex/p17-t31-fidelity-parser-hardening` or
`claude/p17-t31-fidelity-parser-hardening`. Commit the work with a clear
message. Do not merge. Leave a summary with: tests added, fixtures added
or refused (and why), each `FID-LS-*` receipt's resulting state, and any
parser behavior intentionally deferred to a follow-up.
