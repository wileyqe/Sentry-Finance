# P17-T32: Fidelity Tax-Lot And 1099 Reconciliation Source Audit

## Context

The Fidelity live-shape readiness audit (P17-T26) found that the current
Activity plus Positions CSV pair is not enough to reconstruct full tax lots.
The contract document explicitly says: "current Activity plus Positions CSVs
do not provide per-lot acquisition dates, lot-specific basis for still-open
lots, disposal lot selection, or wash-sale adjustments." The mismatch ledger
captures this as `FID-LS-007` (gap), with a five-way feasibility ranking of
candidate sources (GainsKeeper export, in-page lot detail, Closed Positions
page/export, statements/trade confirmations, 1099-B PDF). Separately,
`FID-LS-015` (gap) flags that the CSV live-shape audit did not validate
`dal/parsers/fidelity_1099.py`, so the existing 1099 PDF parser cannot yet be
used as evidence that CSV dividends and cost basis agree with tax forms.

**This is an audit prompt, not an implementation prompt.** The deliverable is
a recommendation document and a small redacted reconciliation evidence pack;
no Fidelity live writer, parser, or schema changes are produced by this slice.
The output of this audit is what feeds the next implementation slice.

## Starting State

- `docs/audits/fidelity-live-shape/mismatch-ledger.md` carries:
  - `FID-LS-007` (gap): `get_lots` (`dal/investments.py:193-272`) renders
    FIFO lots from ledger buy/reinvestment rows, but live Activity plus
    Positions CSVs do not expose open-lot acquisition dates, lot-specific
    basis, or disposal selections. Live tax-lot UI would be inferred
    rather than evidenced. The recommended fix is "a follow-up
    source-discovery task" — that is this prompt.
  - `FID-LS-015` (gap): the CSV audit did not validate
    `dal/parsers/fidelity_1099.py`. 1099 reconciliation cannot yet be
    used as evidence that CSV dividends and cost basis agree with tax
    forms. The recommended fix is a separate redacted Fidelity 1099
    parser/reconciliation audit — also this prompt.
  - `FID-LS-013` (gap): no redacted SELL/closed-position sample is
    committed. P17-T31 owns capturing that fixture; this audit may
    benefit from it but does not block on it.
  - `FID-LS-014` (gap): live `CAP GAIN` rows currently flatten into a
    single `DIVIDEND` classifier with no qualified vs. short-term vs.
    long-term subtype. P17-T29 (already merged) writes ticker-first
    descriptions and preserves raw action text in `raw_description`, but
    no tax-distribution subtype exists in the schema. This audit decides
    whether such a subtype is needed and where its truth lives.
- `docs/audits/fidelity-live-shape/live-shape-contract.md` section 7 (Tax-Lot
  Readiness) is the canonical pre-existing analysis: it ranks the five
  candidate sources by feasibility but does not commit to one.
- `dal/investments.py` `get_lots()` (lines around 193-272) renders FIFO lots
  from `positions_ledger` buy/reinvestment rows with `cost_basis_dec`,
  falling back to shares times closing price when basis is missing. P17-T30
  is hardening the per-position basis path; this audit informs whether the
  ledger is sufficient or whether a separate `tax_lots` source is needed.
- `dal/parsers/fidelity_1099.py` is the existing Consolidated 1099 PDF
  parser. It extracts: ordinary dividends (1a), qualified dividends (1b),
  total capital gain distributions (2a), interest income (1), total
  proceeds, total cost basis, net gain/loss, and tax year. It does not
  produce per-lot or per-symbol output.
- `dal/yearly_wrapup.py` (lines around 577-601) is where surfaced 1099
  values land for the yearly tax document flow; the audit must understand
  what shape the consumer expects.
- P17-T29 (merged) writes `Investment Income` cash transactions for
  `DIVIDEND RECEIVED` and `CAP GAIN` rows with no tax subtype, by design.
  See `docs/prompts/Phase-17/P17-T29_fidelity-dividend-income-writer.md`
  "Design Decisions" — subtype was deferred to this audit.
- `raw_exports/fidelity/` is gitignored. Any sample 1099 PDF or
  GainsKeeper/Closed-Positions/statement export must stay there; only
  redacted structural fixtures are committed under
  `tests/fixtures/fidelity/`.

## Task

This audit produces a recommendation document plus a small redacted
reconciliation evidence pack. Concretely:

1. Read `CLAUDE.md`, `docs/ROADMAP.md` (P17-T32 entry), the three audit
   docs under `docs/audits/fidelity-live-shape/`, the relevant DAL
   (`dal/investments.py`, `dal/yearly_wrapup.py`, `dal/parsers/fidelity_1099.py`),
   and the P17-T29 prompt for the deferred subtype context.
2. **Survey the five candidate tax-lot sources** named in the live-shape
   contract section 7 against the household's actual Fidelity export
   capabilities (HItL: ask the user what is downloadable, what requires
   navigation, what is gated, what is paywalled). For each candidate,
   record:
   - **Coverage:** open lots only, closed lots only, both; partial vs. full
     wash-sale adjustment; whether per-lot acquisition date and per-lot
     basis are present.
   - **Format:** structured CSV/XLSX/JSON vs. PDF vs. HTML scrape.
   - **Frequency:** continuously available vs. annual vs. on-demand.
   - **Authority:** is this the source Fidelity itself reports to the IRS
     (1099-B), an internal tracker (GainsKeeper), or a UI projection?
   - **Parser risk:** layout drift exposure, DOM/MFA fragility, PDF-text
     extraction reliability.
   - **Reconciliation handle:** can rows be keyed back to existing
     Activity/Positions CSV evidence (symbol + date + quantity + amount)?
   The candidate set: GainsKeeper / Tax Info export, in-page lot detail
   click loop on Positions, Closed Positions page/export, monthly
   statements / trade confirmations, 1099-B PDF.
3. **Recommend a primary tax-lot source of truth.** Decide which of the
   five (or which combination) becomes the next implementation target,
   and document the decision with explicit trade-offs. The decision must
   answer:
   - Open lots (still held): what is the source for per-lot acquisition
     date and lot-specific cost basis?
   - Closed lots (sold): what is the source for disposal date, disposal
     proceeds, and cost-basis applied?
   - Wash sales and disallowed losses: how does the chosen source
     surface adjustments, if at all?
   - Reconciliation: how does the chosen source agree with Positions
     `Cost Basis Total` (P17-T30's authority for per-position aggregate
     basis) and Activity `YOU BOUGHT` / `REINVESTMENT` / `YOU SOLD`
     rows?
4. **Run a redacted Fidelity 1099 reconciliation audit** against
   `dal/parsers/fidelity_1099.py`. Concretely:
   - HItL: ask the user for one or more sample Fidelity Consolidated
     1099 PDFs covering a tax year where Activity and Positions CSVs are
     also available. The PDF stays in `raw_exports/fidelity/`.
   - Run the parser locally and capture `fields` + `warnings` output.
   - Reconcile:
     - 1099 box 1a (Total ordinary dividends) vs. sum of P17-T29
       `Investment Income` transactions tagged as `DIVIDEND RECEIVED`
       for that tax year.
     - 1099 box 2a (Total capital gain distributions) vs. sum of P17-T29
       `Investment Income` transactions whose `raw_description` contains
       `CAP GAIN`.
     - 1099 box 1b (Qualified dividends) vs. the lack of a qualified
       subtype today; quantify the gap.
     - 1099-B Total proceeds and Total cost basis vs. derived sums from
       Activity `YOU SOLD` rows (if any) and Positions cost basis.
     - 1099 box 1 (Interest income) vs. SPAXX/FDRXX dividend rows
       categorized as `Investment Income`.
   - Record exact-cents agreement where possible; record
     reasonable-rounding tolerance where the 1099 reports whole-dollar
     boxes.
   - Note any silent-failure cases the parser hits today (it currently
     refuses to commit when no core fields extract; flag if any sample
     hits that path).
5. **Decide whether to add a tax-distribution subtype schema.** P17-T29
   deferred this. Recommend yes/no, where the column lives if yes
   (`transactions` tax subtype column? a new `investment_income_details`
   side table keyed by `transactions.id`? evidence-only column for
   `qualified` / `short_term` / `long_term`?), and what migration shape
   is required. If no, document why ticker-first description plus
   `raw_description` is sufficient indefinitely.
6. **Commit a redacted reconciliation evidence pack** under
   `docs/audits/fidelity-live-shape/` (suggested filename:
   `tax-lot-source-recommendation.md`, plus a separate
   `1099-reconciliation.md`). Include:
   - The five-source comparison table.
   - The chosen primary source(s) and the rationale.
   - The 1099 reconciliation table with redacted figures (real ratios,
     dummy magnitudes), `FID-LS-007` and `FID-LS-015` updated to point
     at the recommendation document.
   - A concrete next-step implementation prompt skeleton (one
     paragraph) that names what would be built and which mismatch
     receipts it would close. Do not author the full follow-up prompt
     in this slice; that is for the implementer to write when work
     begins.
7. **Update the mismatch ledger.** `FID-LS-007` and `FID-LS-015` should
   move from open-gap to "decided, see recommendation" with a link to
   the new audit document. `FID-LS-014` should either move to
   "subtype decision recorded" with a link, or stay open with a
   pointer to the deferred-implementation paragraph.

## Non-Goals

- Do not implement any tax-lot writer, schema migration, or 1099
  reconciliation runner in this slice. The deliverable is research and
  recommendation, not code.
- Do not modify `dal/investments.py`, `dal/parsers/fidelity_1099.py`, or
  any DAL/migration. If the parser needs hardening, name it as a
  follow-up; do not change it here.
- Do not log into the live Fidelity site, scrape DOM, or use
  credentials. The audit may direct the user to download specific
  exports HItL, but this agent does not perform the download.
- Do not commit raw 1099 PDFs, raw GainsKeeper exports, or any other
  unredacted Fidelity document. `raw_exports/fidelity/` is gitignored;
  only structural/redacted documentation goes into tracked files.
- Do not author the follow-up implementation prompt file here. The
  audit produces a one-paragraph next-step skeleton; the implementer
  authors the full prompt when the work actually starts.
- Do not decide cost-basis persistence shape. P17-T30 owns that and
  may already be merged before this audit runs; align with whatever
  P17-T30 settled on rather than re-litigating.
- Do not change the live verb classifier or money parser. P17-T31
  owns parser hardening. If this audit surfaces a new verb that needs
  classification, file it as a P17-T31 follow-up receipt rather than
  implementing.

## Verification

This is a docs-only / audit slice. Verification is structural:

- The recommendation document exists at the chosen path under
  `docs/audits/fidelity-live-shape/` and answers all four "decide"
  questions in step 3 (open lots, closed lots, wash sales,
  reconciliation handle).
- The 1099 reconciliation document exists and includes a redacted
  reconciliation table covering boxes 1a, 1b, 2a, 1, and the 1099-B
  totals against the corresponding CSV-derived sums for at least one
  tax year.
- `docs/audits/fidelity-live-shape/mismatch-ledger.md` is updated:
  `FID-LS-007` and `FID-LS-015` transition state and link to the new
  documents; `FID-LS-014` either transitions or stays open with a
  pointer.
- The doc-coupling pre-commit hook passes (this is doc-only; no
  schema or DAL touch should be required).
- No code change in this slice. If the audit triggers a "must fix
  this immediately" finding (e.g., the 1099 parser silent-fails on a
  representative sample), record it as a follow-up receipt with a
  severity, not a fix in this slice.
- Run `python scripts/audit_reference_clock_usage.py` only if any
  doc edit accidentally touches code; not expected to be needed.

## Agent Shutdown

Use a branch named for the agent lane, for example
`codex/p17-t32-fidelity-tax-lot-audit` or
`claude/p17-t32-fidelity-tax-lot-audit`. Commit the work with a clear
message. Do not merge. Leave a summary with: the chosen primary tax-lot
source(s) and rationale, the 1099 reconciliation result (agree to the
cent, agree within tolerance, or specific disagreements), the
subtype-schema decision, and any new follow-up receipts the audit
generated.

## Decision Updates (2026-05-10)

The following adjustments override or refine sections above. Read these
before executing — they reflect decisions made after the prompt was
authored.

### Scope expanded: ship migration if audit warrants

This task is no longer "audit only." If step 5's tax-distribution
subtype audit concludes "yes, add a schema field" (or "yes, add a new
`tax_lots` table"), the agent **ships the migration as part of this
slice**:

- Author a new sequential migration under `migrations/` (next `vN+1`
  number — check existing migration count first).
- Update `docs/data-lineage/lineage/*.yaml` and/or
  `docs/data-lineage/events.yaml` per the doc-coupling gate.
- Update `docs/ARCHITECTURE.md` §4.2 to reflect the schema change.
- Run `scripts/install_hooks.sh`-installed pre-commit gate to confirm
  doc-coupling check passes.

**Writer changes that populate the new schema** (e.g., updating
P17-T29's `Investment Income` writer to fill the new `tax_subtype`
column) remain **deferred** to a follow-up slice. T32 ships: audit docs
+ reconciliation evidence + (if warranted) migration + doc coupling.
T32 does NOT ship writer logic that uses the new schema.

If the audit concludes no schema change is needed, write that
conclusion explicitly in the recommendation doc with rationale and skip
the migration step.

### FID-LS-014 placement locked: T32 owns it

FID-LS-014 (qualified vs short-term vs long-term capital-gain subtype)
is **fully owned by this audit**. The audit MUST land a decision —
either:

- "Yes, schema field needed. Here is the migration." (proceed to
  schema-write per the section above), OR
- "No, ticker-first description plus `raw_description` is sufficient
  indefinitely. Here is why."

Do not punt FID-LS-014 back to P17-T29 or to a future slice. Update the
mismatch ledger entry to "decided" with a link to the recommendation
document.

### Data inventory in raw_exports/fidelity/

The household has dropped the following local samples (gitignored —
do NOT commit raw):

| File | Coverage |
|---|---|
| `2023-Individual-*-Consolidated-Form-1099.pdf` | Tax year 2023, covers the Dec 2023 `YOU SOLD` rows in History CSV |
| `2024-Individual-*-Consolidated-Form-1099.pdf` | Tax year 2024, parser-anchor for format consistency |
| `Statement12312023.pdf` | Dec 2023 monthly statement, contains SELL trade confirmations |
| `Closed_Positions_2023.csv` | Fidelity's lot-level closed-position view for tax year 2023; **functionally replaces GainsKeeper for closed lots** |
| `History_for_Account_2023.csv` through `History_for_Account_2026.csv` | Four years of activity (2023 has 8 `YOU SOLD` rows) |
| `Portfolio_Positions_Mar-04-2026.csv` | Current open-position snapshot, single account (`X93690827`) |

**Not available:**

- **GainsKeeper export** — household could not locate the download path
  on Fidelity's site. `Closed_Positions_2023.csv` is the substitute for
  closed-lot evidence; document this caveat in the recommendation doc.
- **Realized Gain/Loss CSV** — substantially redundant with Closed
  Positions for closed-lot truth; not a blocker.
- **Multi-account Positions CSV** — household has one Fidelity account.

The 2023 1099 + Dec 2023 Statement + `Closed_Positions_2023.csv` +
`History_for_Account_2023.csv` is enough evidence to run a complete
cross-source reconciliation for the December 2023 SELL events. That
becomes your primary worked example in the reconciliation doc.

The five-source survey (step 2) can still rank GainsKeeper vs
alternatives using documented Fidelity behavior — note where the
ranking is "by reputation/documentation" vs "by side-by-side data
comparison" so the recommendation is honest about evidence levels.

### Verification adjustment

The "no code change in this slice" line in the original Verification
section is overridden when step 5 concludes a migration is warranted.
In that case:

- A new migration file exists under `migrations/`.
- The migration applies cleanly on a fresh DB and as an upgrade.
- Doc-coupling pre-commit gate passes (lineage YAML + ARCHITECTURE.md
  updated).
- Run `python scripts/audit_reference_clock_usage.py`.
- Run any backend tests that touch the affected schema area
  (`pytest tests/test_dal_*` for any DAL touch).

If no migration is warranted, the original docs-only verification
applies unchanged.

### Pre-existing test failure to ignore

`tests/test_performance_by_asset_class.py::test_perf_by_class` fails on
`main` independently of any Fidelity work. A separate fix-up issue
tracks it. Do NOT investigate or fix it as part of this slice.
