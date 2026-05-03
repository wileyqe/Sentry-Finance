# P17-T26: Fidelity Live-Shape, Cost-Basis, And Tax-Lot Readiness Audit

## Context

The trust bar requires the synthetic Fidelity model and the live Fidelity
ingest path to agree on shape *before* the user affirms the app is
production-trustworthy. We already have a working `FidelityConnector` and
real Fidelity CSV exports on disk; what we lack is an explicit, evidence-
backed comparison of the live data shape against the synthetic seed,
ingest pipeline assumptions, schema, and downstream UI/aggregate
contracts.

This prompt is an **audit, not a fix**. The deliverable is a written
mismatch ledger with receipts, a typed live-shape contract, a regression
test gauntlet, and follow-up task drafts. Implementation of fixes happens
in subsequent prompts that Claude or Codex will write after the user
reviews the findings.

This task is assigned to **Codex**.

## Workflow And Handoff

Codex owns implementation on a dedicated branch. Claude owns validation
and merge back to clean `main`.

### Codex workflow

1. Start from clean, up-to-date `main`. Verify with `git status` /
   `git log -1`.
2. Create a dedicated branch:
   `codex/p17-fidelity-live-shape-readiness`.
3. Run the Graph Context Check before edits:
   ```
   python tools/graphify/query_local.py impact "Fidelity live data shape connector synthetic investments cost basis tax lots dividends"
   ```
4. Execute the Task and Verification sections of this prompt.
5. Update this prompt's `## Outcome` and `## Follow-Up Drafts` sections
   with what was found, what was verified, and the recommended follow-up
   roadmap entries. Drafts only — Codex does **not** edit `ROADMAP.md`.
6. Commit the work to the Codex branch. Do **not** merge.

### Codex commit hygiene

- Do not work directly on `main`.
- Do not use `--no-verify`. If the doc-coupling gate blocks a commit,
  fix the underlying drift instead of bypassing it.
- Avoid `[v]` or `Verified` in commit messages; Claude handles roadmap
  completion status during validation/merge.
- Do not edit `docs/ROADMAP.md` or `docs/ROADMAP_ARCHIVE.md`. Capture
  follow-up task drafts inside this prompt's `## Follow-Up Drafts`
  section so Claude can transcribe them into the roadmap during the
  merge pass.
- Do not delete branches, rewrite unrelated history, or touch user
  changes outside the responsibility set.
- Do **not** commit raw Fidelity CSVs, account numbers, balances,
  PDFs, screenshots, or any PII from `raw_exports/`. Quote a redacted
  snippet (last4 → `XXXX`, account number → `X<redacted>`) in the
  audit report when receipts are needed.

### Claude validation/merge workflow

After Codex finishes:

1. Review Codex's branch diff against current clean `main`.
2. Run the verification commands from this prompt.
3. Inspect the audit report and tests for credential / account-number
   / balance / holding-detail leakage.
4. Confirm `## Outcome` and `## Follow-Up Drafts` are populated.
5. Merge only after the branch is clean and verification is acceptable.
6. Transcribe `## Follow-Up Drafts` into `docs/ROADMAP.md` as new
   `[ ]` tasks under the appropriate section, then update P17-T26 to
   `[v]` in the roadmap during the merge pass.

## Multi-Agent Coordination

Codex owns only this responsibility/write set unless the user redirects:

- `docs/audits/fidelity-live-shape/README.md` (new audit report root)
- `docs/audits/fidelity-live-shape/live-shape-contract.md` (new typed
  live-shape contract)
- `docs/audits/fidelity-live-shape/mismatch-ledger.md` (new mismatch
  table with receipts)
- `tests/test_fidelity_live_shape_contract.py` (new regression gauntlet)
- A small fixture file under `tests/fixtures/fidelity/` containing
  *redacted* snippets of the live CSV shape used by the contract test
  (account numbers stripped, balances scrubbed)
- `docs/prompts/Phase-17/P17-T26_fidelity-live-shape-readiness.md`
  (this file's `## Outcome` and `## Follow-Up Drafts` sections only)

Codex **may read** but **must not edit**:

- `extractors/fidelity_connector.py`
- `extractors/fidelity_investment_details.py`
- `scripts/ingest_fidelity_history.py`
- `scripts/dummy_data/generator.py`
- `scripts/seed_dummy_data.py`
- `dal/parsers/fidelity_1099.py`
- `dal/migrations/v25_positions_ledger_cost_basis.py`
- `dal/migrations/v41_investment_details.py`
- `dal/investments.py`
- `docs/ARCHITECTURE.md`
- All files under `data-lineage/`
- All number-trust proof scripts

Codex must **not** edit:

- `docs/ROADMAP.md`
- `docs/ROADMAP_ARCHIVE.md`
- `docs/CLAUDE.md` or `CLAUDE.md`
- Any connector other than Fidelity (no Acorns, TSP, Chase, NFCU,
  myPay, Affirm changes)
- Frontend files (this is a backend/data audit)
- Production seeders, migrations, DAL writers, or ingest scripts

If Codex finds the audit cannot be completed without editing a
read-only file (for example, the live CSV reveals a parser silent-
failure bug), stop and write a short note in `## Outcome` describing
the blocker. Do not widen the branch.

## Starting State

### What exists today

- `extractors/fidelity_connector.py` (`FidelityConnector`) — playwright-
  driven login + manual TOTP MFA, downloads two CSVs from
  `digital.fidelity.com`:
  - **Activity history**: `History_for_Account_<YYYY>.csv` from the
    Activity & Orders → History page.
  - **Positions snapshot**: `Portfolio_Positions_<MMM-DD-YYYY>.csv`
    from the Positions page.
  - Plus an in-page detail scrape (`_scrape_investment_details`) that
    captures SPAXX SEC yield and per-ETF YTD return via DOM clicks.
- `scripts/ingest_fidelity_history.py` — parses the two CSVs,
  reconstructs a daily ledger, fetches yfinance closing prices, and
  persists `positions_ledger` / `investment_holdings` rows plus a
  SPAXX cash-balance snapshot.
- `dal/parsers/fidelity_1099.py` — separate path for tax document PDFs.
- `scripts/dummy_data/generator.py::generate_fidelity_investment_history`
  — synthetic Fidelity history. Uses `_generate_trusted_investment_account_history`
  with `TRUSTED_INVESTMENT_ACCOUNT_SPECS[_FIDELITY_ACCT]`:
  - `starting_cents=5_000_000` ($50,000 baseline)
  - `monthly_cents=100_000` ($1,000/mo EFT)
  - `description="FIDELITY EFT TRANSFER"`
  - `contribution_type="BUY"`
  - Fixed price $100 for all tickers, 8 equal-weight allocations.
- Real Fidelity CSV samples already on disk in `raw_exports/fidelity/`
  (gitignored — do not commit raw copies):
  - `History_for_Account_2024.csv`
  - `History_for_Account_2025.csv`
  - `History_for_Account_2026.csv`
  - `Portfolio_Positions_Mar-04-2026.csv`
- Closed audit pointers worth re-reading:
  - `docs/data-lineage/ACTION_ITEMS.md` AI-010 (Fidelity EFT cash leg
    pairing), AI-016 (live Fidelity dividend parser must emit
    `category='Investment Income'`).
- Migrations relevant to investments shape:
  - v24 investment linkage, v25 positions_ledger cost-basis columns,
    v27 fund composition, v34 investment-contributions view, v41
    investment details, v43 investment contributions via bank_txn_id.

### Initial live-shape signals (from existing exports)

These observations are *seeds* for the audit, not conclusions. Codex
must verify each from the actual files:

- History CSV header row:
  `Run Date,Action,Symbol,Description,Type,Price ($),Quantity,Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date`
- The `Action` column carries verbose phrasing such as
  `"DIVIDEND RECEIVED ..."`, `"REINVESTMENT ..."`,
  `"YOU BOUGHT ..."`, `"Electronic Funds Transfer Received (Cash)"`.
- SPAXX appears as a money-market sweep with paired
  `DIVIDEND RECEIVED` and `REINVESTMENT` rows.
- Fractional share quantities exist (e.g., 0.196, 0.755).
- Positions CSV contains `Cost Basis Total`, `Average Cost Basis`,
  and a money-market row for SPAXX with empty cost-basis fields.
- Header/footer noise rows precede and follow the data block in
  History CSV.
- Currency formatting includes `$` prefixes, parentheses for
  negatives, and trailing whitespace.

### Synthetic shape for comparison

- Synthetic Fidelity ledger uses only `BUY` rows at fixed $100 price.
- No `DIVIDEND RECEIVED`, `REINVESTMENT`, `SELL`, `Cash Balance`, or
  fractional-share rounding events.
- SPAXX is not part of the synthetic allocation.
- Cost-basis is implicit (`amount = shares * 100`) and stored on
  `positions_ledger.cost_basis_dec`.
- No tax-lot disambiguation (FIFO/LIFO/specific-lot) — every BUY is a
  fresh implied lot at fixed price.

### Graph context at prompt-authoring time

Treat Graphify as advisory only; live code and tests are executable
truth. Likely-related nodes:

- `extractors/fidelity_connector.py`
- `scripts/ingest_fidelity_history.py`
- `scripts/dummy_data/generator.py`
- `dal/migrations/v25_positions_ledger_cost_basis.py`
- `dal/investments.py::get_lots`
- `seed_dummy_data.seed_fidelity_investments`
- Phase 4 P4-T04 Fidelity Cost Basis Positions CSV
- Phase 13 P13-T06 Fidelity Synthetic Data Pipeline
- Phase 5 P5-T07 Investments Page Live Data
- Phase 14 P14-T03 dividends-interest-income

## Task

Produce an evidence-backed live-shape audit. The work is in four parts.

### Part A — Capture live shape

Codex's primary source of live-shape truth is the existing
`raw_exports/fidelity/` directory. Codex should **not** run the live
`FidelityConnector` against the real Fidelity site as part of this
audit; the user has already exported representative samples. If the
samples are insufficient (for example, no SELL rows, no transfer-out
events, no margin/option records), Codex must:

1. Document the gap in the mismatch ledger.
2. Recommend in `## Follow-Up Drafts` a HItL connector run that
   captures the missing event types — but do **not** execute that
   run inside this branch.

For each existing CSV, write a redacted, structural fixture under
`tests/fixtures/fidelity/`:

- Replace any account number with `X<redacted>`.
- Round or scrub real balance/holding values to a deterministic dummy
  while preserving column order, dtypes, header noise, footer noise,
  decimal precision, currency formatting, and the diversity of
  `Action` strings.
- Keep at least one row of every distinct `Action` verb observed.
- Preserve SPAXX behavior (dividend + reinvestment pair, blank cost
  basis on positions row).
- Preserve fractional-share quantity precision.

These redacted fixtures are the only Fidelity-shape evidence allowed
in tracked files. Real CSVs stay in `raw_exports/` (gitignored).

### Part B — Live-shape contract

Author `docs/audits/fidelity-live-shape/live-shape-contract.md`. The
contract is the canonical, code-grounded description of what the
Fidelity live ingest path *must* tolerate. At minimum it covers:

1. **History CSV schema**: column order, blank-row tolerance, footer
   tolerance, the full set of distinct `Action` verbs observed plus
   any not-yet-observed verbs Codex flags as plausible (SELL,
   transfer-out, fee, journal entry). For each verb, document:
   - Codex's read of the verb's semantic mapping
     (BUY / SELL / DIVIDEND / REINVESTMENT / EFT_IN / EFT_OUT /
     INTEREST / FEE / OTHER).
   - Whether the current ingest pipeline routes the row correctly.
2. **Positions CSV schema**: column order, money-market row handling,
   `Cost Basis Total` vs `Average Cost Basis` precedence, blank-cost
   handling for cash sweep, multi-account/multi-position headers if
   present.
3. **Currency / numeric formatting**: `$` prefixes, parentheses
   negatives, trailing whitespace, scientific notation tolerance,
   integer vs decimal cents.
4. **Dividend semantics**: per AI-016, live Fidelity dividends MUST
   land as `category='Investment Income'`. Document the exact
   `Action` substring patterns Codex would key on, and call out any
   ambiguity (e.g., SPAXX dividends vs equity dividends vs
   long-term-cap-gain distributions).
5. **EFT cash-leg coupling**: per AI-010, live EFT-in events must
   pair to a `summit_chk` debit. Document the live `Action` strings
   that emit a cash leg and which currently do not.
6. **Cost-basis source of truth**: cost basis comes from the
   Positions CSV today, not from per-row `positions_ledger.cost_basis_dec`.
   Document where each downstream consumer (UI, derived metrics,
   reports) reads cost basis from, and whether they read live or
   synthetic.
7. **Tax-lot readiness**: a frank assessment of what tax-lot data
   *is* and *is not* present in the current exports. The Activity +
   Positions CSVs cannot, on their own, reconstruct per-lot acquisition
   dates and lot-level cost basis. Document what additional sources
   would be needed (statements, GainsKeeper export, Closed Positions
   page, 1099-B PDF, in-page lot detail click loop) and rank them by
   feasibility/risk.

### Part C — Mismatch ledger

Author `docs/audits/fidelity-live-shape/mismatch-ledger.md`. Each
mismatch row needs:

- **ID**: stable identifier, e.g., `FID-LS-001`.
- **Severity**: `block` (live ingest will silently produce wrong
  numbers), `gap` (live ingest will lose data but not corrupt
  existing rows), `cosmetic` (UI/label drift).
- **Synthetic claim**: what the synthetic seeder, schema, or test
  asserts. Receipt: file path + line number.
- **Live reality**: what the live CSV / connector actually emits.
  Receipt: redacted CSV row(s) or connector code reference.
- **Downstream impact**: which UI/aggregate/test would be wrong or
  missing.
- **Recommended fix**: short, scoped description (one bullet).

The minimum mismatch areas Codex must investigate (mark each as
covered, even if the verdict is "no mismatch"):

1. Action-verb coverage — synthetic emits only BUY; live emits
   BUY/SELL/DIVIDEND/REINVESTMENT/EFT/etc.
2. SPAXX cash-sweep modeling.
3. Fractional shares precision (5dp synthetic vs whatever live
   precision Fidelity ships).
4. EFT cash-leg coupling under the live `Action` string (compare
   AI-010's `"FIDELITY EFT TRANSFER"` literal vs live
   `"Electronic Funds Transfer Received (Cash)"`).
5. Dividend `Investment Income` category routing under the live
   `Action` strings (compare AI-016's invariant vs the live verb
   set).
6. Cost-basis live-vs-synthetic source — synthetic packs cost basis
   into ledger rows; live takes it from Positions CSV.
7. Tax-lot reconstructability gap.
8. Settlement-date handling (some live rows blank, some populated).
9. Header/footer noise tolerance in the parser.
10. Currency formatting tolerance (`$`, parentheses, trailing space).
11. Multi-account scoping — does the live CSV support multiple
    Fidelity accounts in one export, and does the parser scope by
    account number?
12. Closed-position / sold-out lots — synthetic never sells, so the
    `positions_ledger` SELL path is structurally untested against
    live shape.
13. Long-term capital gain / qualified dividend distinctions
    (forward-looking, may be out of scope but should be flagged).
14. 1099 reconciliation path (`dal/parsers/fidelity_1099.py`) —
    does it match the live shape? Mark as out-of-scope-but-flagged
    if Codex cannot easily verify.

### Part D — Regression test gauntlet

Add `tests/test_fidelity_live_shape_contract.py`. The test must:

1. Load the redacted fixtures from `tests/fixtures/fidelity/`.
2. Assert column order and dtype expectations match the live-shape
   contract.
3. Assert at least one row exists for each distinct `Action` verb
   the contract names as supported.
4. Assert SPAXX dividend + reinvestment rows are present and
   structurally distinguishable.
5. Assert fractional-share precision is preserved through any parser
   path that the audit identifies (read-only — do not modify the
   parser).
6. Assert that *if* the parser were given the redacted fixture, the
   resulting parse output classifies dividends as `Investment Income`
   — or, if the current parser does not, the test marks the
   mismatch with `pytest.xfail` and links to the relevant
   `FID-LS-###` mismatch ID.

The gauntlet is a regression boundary, not a fix vehicle. `xfail` is
preferred over green-test-for-broken-behavior.

### Part E — Audit report root

Author `docs/audits/fidelity-live-shape/README.md` with:

- One-paragraph summary.
- Pointer to the live-shape contract and mismatch ledger.
- A short table of mismatches by severity.
- A "How this audit was built" section listing the live samples used
  (file names + redacted summaries — no balances, no account numbers).
- A "What this audit does NOT cover" section, e.g., 1099 PDF parser
  fidelity, options, margin, fixed income, foreign equities,
  bond CUSIPs, mutual-fund NAV-only positions, partial-share
  redemptions during corporate actions.

## Implementation Notes

- This is a **read-mostly** branch. The only writes are: new audit
  files, new test, redacted fixtures, and this prompt's `## Outcome`
  / `## Follow-Up Drafts`.
- Do not modify production code paths. If a defect is obvious (for
  example, a parser substring mismatch that will silently drop live
  dividends), document it as a `block`-severity mismatch with a
  recommended fix and a follow-up draft. Claude or a subsequent prompt
  applies the fix.
- Honor canonical conventions when writing test assertions: integer
  cents for money, `signed_amount`/`direction` invariant
  (ARCHITECTURE §4.6), `transfer_tag IS NULL` for income/spending
  aggregates.
- Do not add new yfinance, vendor, or cloud dependencies.
- Do not extend the `FidelityConnector` lifecycle, MFA flow, or
  selectors.
- Do not introduce new SSE event shapes.
- Treat any account number, last4, holding count, or balance from the
  raw exports as untrusted PII. Redact before committing.

## Verification

Static and unit verification:

```powershell
python -m pytest tests/test_fidelity_live_shape_contract.py -q
python -m pytest tests/test_fidelity_investment_extractor.py tests/test_dal_investments_writes.py tests/test_result_writer_investment.py tests/test_investment_contributions_view.py tests/test_dividend_interest_flows.py -q
```

Spot-check that no existing investment behavior regressed:

```powershell
python -m pytest tests/test_investment_panel_bundle.py tests/test_investment_details.py -q
```

Targeted search checks (these should report only audit-related
additions, not edits to production code):

```powershell
git diff --stat main...HEAD
git diff main...HEAD -- extractors scripts dal backend frontend
```

The second diff command must be empty or near-empty (the audit branch
is read-mostly).

PII / leakage checks before commit:

```powershell
rg -n "X[0-9]{8}|\$[0-9][0-9,]*\.[0-9]{2}" docs/audits tests/fixtures
```

Any hit must be either redacted (`X<redacted>`) or scrubbed to a
deterministic dummy. Real account numbers and balances are not
allowed in tracked files.

Doc-coupling gate sanity (the gate runs on commit; this is a
pre-flight):

```powershell
python -m pytest tests/test_doc_coupling.py -q
```

If the gate complains because `tests/fixtures/fidelity/*.csv` look
like data-import additions, address the underlying expectation —
do not bypass with `SKIP_DOCS_CHECK` unless the gate truly does not
apply (and then say so clearly in the commit message trailer).

## Done Criteria

- `docs/audits/fidelity-live-shape/README.md` exists and links to
  the contract and ledger.
- `docs/audits/fidelity-live-shape/live-shape-contract.md` covers
  the seven contract sections (history schema, positions schema,
  numeric formatting, dividend semantics, EFT cash leg, cost-basis
  source, tax-lot readiness).
- `docs/audits/fidelity-live-shape/mismatch-ledger.md` covers all
  fourteen minimum investigation areas; each has a verdict and, where
  a mismatch exists, a receipt and recommended fix.
- Redacted fixtures live under `tests/fixtures/fidelity/` with no
  PII.
- `tests/test_fidelity_live_shape_contract.py` runs green or with
  documented `xfail`s pointing at mismatch IDs.
- This prompt's `## Outcome` and `## Follow-Up Drafts` sections are
  populated.
- No production extractor / ingest / parser / DAL / migration / seeder
  code was modified.
- No `ROADMAP.md` or `ROADMAP_ARCHIVE.md` edits.
- No real Fidelity account numbers, balances, holding amounts, or
  PDF/screenshot content committed.

## Outcome

Files added:

- `docs/audits/fidelity-live-shape/README.md`
- `docs/audits/fidelity-live-shape/live-shape-contract.md`
- `docs/audits/fidelity-live-shape/mismatch-ledger.md`
- `tests/test_fidelity_live_shape_contract.py`
- `tests/fixtures/fidelity/history_2024_redacted.csv`
- `tests/fixtures/fidelity/history_2025_redacted.csv`
- `tests/fixtures/fidelity/history_2026_redacted.csv`
- `tests/fixtures/fidelity/positions_mar_04_2026_redacted.csv`

Headline numbers:

- 15 ledger rows: 4 `block`, 9 `gap`, 2 `cosmetic`.
- 12 action patterns documented: 7 observed in current samples and
  5 plausible/not-yet-observed families.
- 7 contract sections completed.
- 10 regression tests with 29 explicit assertions; 2 expected `xfail`s
  for FID-LS-005 and FID-LS-011.

Blockers preventing full live-readiness:

- The current live ingest parser recognizes much of the history CSV
  shape, but `persist_to_db` only writes a SPAXX cash balance and does
  not write live Fidelity `positions_ledger`, `investment_holdings`, or
  `portfolio_snapshots` rows. Receipt: FID-LS-001,
  `scripts/ingest_fidelity_history.py:598-636`.
- Live dividends/capital-gain rows do not become
  `category='Investment Income'` cash transactions. Receipt: FID-LS-005.
- Live EFT rows do not link to bank-side cash legs via
  `positions_ledger.bank_txn_id`. Receipt: FID-LS-004.
- Positions cost basis is summed into `loan_details`, not persisted as
  per-holding/lot basis consumed by Investments. Receipt: FID-LS-006.

Surprises:

- This prompt's starting-state claim that
  `scripts/ingest_fidelity_history.py` persists `positions_ledger` /
  `investment_holdings` rows did not match live code. The script writes
  output CSVs and records SPAXX cash only. Receipts:
  `scripts/ingest_fidelity_history.py:598-636` and
  `extractors/fidelity_connector.py:499-517`.
- AI-010 is resolved for the synthetic seed, but the live action string
  is `Electronic Funds Transfer Received (Cash)` rather than
  `FIDELITY EFT TRANSFER`; no live linker handles that shape yet.
  Receipt: FID-LS-004.

Deliberately deferred:

- No production parser/writer fixes were made in this branch.
- No live Fidelity connector run was executed.
- SELL/closed-position, lot-detail, and 1099 reconciliation evidence
  require follow-up source capture/audit.

## Follow-Up Drafts

- `[ ]` **Fidelity live writer for holdings, snapshots, and ledger rows** - Persist parsed Fidelity history and positions into `positions_ledger`, `investment_holdings`, and `portfolio_snapshots` instead of stopping at output CSVs plus a SPAXX balance snapshot. Include SPAXX cash/equivalent handling and preserve settlement dates where present. Receipts: FID-LS-001, FID-LS-003, FID-LS-009. Severity: `block`. Estimated blast radius: `scripts/ingest_fidelity_history.py`, `extractors/fidelity_connector.py`, investment DAL tests, flow/accountability tests. Suggested prompt name: `docs/prompts/Phase-17/P17-T27_fidelity-live-writer.md`.

- `[ ]` **Fidelity live EFT cash-leg linker** - Map live `Electronic Funds Transfer Received/Paid (Cash)` rows to imported bank-side cash transactions, set `transfer_tag`, and stamp exactly one primary Fidelity ledger row with `bank_txn_id` so Shape B cash-flow reports remain truthful. Receipts: FID-LS-004, AI-010. Severity: `block`. Estimated blast radius: Fidelity ingest writer, reconciliation/linking helpers, `dal/reports/flow.py`, `tests/test_investment_contributions_view.py`, `tests/test_flow_shape_b_brokerage.py`. Suggested prompt name: `docs/prompts/Phase-17/P17-T28_fidelity-eft-cash-leg-linker.md`.

- `[ ]` **Fidelity dividend and capital-gain income writer** - Convert live `DIVIDEND RECEIVED` and `CAP GAIN` rows into posted cash transactions with `category='Investment Income'`, positive `signed_amount`, no `transfer_tag`, and enough ticker/description structure for reinvestment-flow pairing. Preserve distribution subtype for future tax reporting. Receipts: FID-LS-005, FID-LS-014, AI-016. Severity: `block`. Estimated blast radius: Fidelity ingest writer, `dal/transactions.py`, `dal/reports/flow.py`, dividend/interest flow tests. Suggested prompt name: `docs/prompts/Phase-17/P17-T29_fidelity-dividend-income-writer.md`.

- `[ ]` **Fidelity per-position cost-basis persistence** - Persist `Cost Basis Total` from the Positions CSV to `investment_holdings.cost_basis`, use `Average Cost Basis` as a validation/fallback signal, and populate `positions_ledger.cost_basis_dec` only where trade/reinvestment evidence supports a lot-forming row. Receipts: FID-LS-006, FID-LS-011. Severity: `block`. Estimated blast radius: Fidelity positions parser/writer, `dal/investments.py`, investment details/panel tests, number-trust Investments oracle. Suggested prompt name: `docs/prompts/Phase-17/P17-T30_fidelity-cost-basis-persistence.md`.

- `[ ]` **Fidelity live-shape parser hardening and source capture** - Harden action-verb, currency, multi-account, SELL/closed-position, and header/footer fixture coverage before live trust. Capture a HItL sample for missing SELL/closed-position events if available; otherwise keep the gap explicit. Receipts: FID-LS-002, FID-LS-008, FID-LS-010, FID-LS-011, FID-LS-012, FID-LS-013. Severity: `gap`. Estimated blast radius: Fidelity parser tests/fixtures, connector download contract, docs/audit fixtures. Suggested prompt name: `docs/prompts/Phase-17/P17-T31_fidelity-parser-hardening.md`.

- `[ ]` **Fidelity tax-lot and 1099 reconciliation source audit** - Decide the next authoritative tax-lot source (GainsKeeper/export, in-page lot detail, Closed Positions, statements, or 1099-B) and run a separate redacted reconciliation audit against `dal/parsers/fidelity_1099.py`. Receipts: FID-LS-007, FID-LS-015. Severity: `gap`. Estimated blast radius: tax-lot docs, Fidelity 1099 parser tests, yearly wrap-up tax document flow. Suggested prompt name: `docs/prompts/Phase-17/P17-T32_fidelity-tax-lot-source-audit.md`.