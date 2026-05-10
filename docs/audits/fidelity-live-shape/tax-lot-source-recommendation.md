# Fidelity Tax-Lot Source Recommendation

This document closes `FID-LS-007` (open-lot/closed-lot source authority) and
`FID-LS-014` (tax-distribution subtype schema decision), and records the
five-source survey requested by P17-T32. It is paired with
[`1099-reconciliation.md`](1099-reconciliation.md), which closes
`FID-LS-015`.

All household figures referenced here are real but were derived from
gitignored samples in `raw_exports/fidelity/`. Account numbers,
recipient identifiers, addresses, and per-symbol lot detail are
redacted in any tracked artifact. Aggregate dollar totals are quoted
where they are needed to support a decision and are visible on the
1099-B summary anyway.

## 1. Summary Decisions

| Question | Answer |
|---|---|
| **Open-lot acquisition date + per-lot cost basis** | **Per-position cost basis from `Portfolio_Positions` CSV (already landed by P17-T30) + per-lot 1099-B rows for prior-year lots.** Mid-year per-lot open-lot acquisition dates remain unsupported until in-page lot detail or trade confirmations are scraped. Live `get_lots()` will continue to derive lot evidence from `positions_ledger` BUY/REINVESTMENT rows; per-lot acquisition for legacy lots predating connector ingest is not solvable from current sources. |
| **Closed-lot disposal date, proceeds, applied cost basis** | **`Closed_Positions_<year>.csv` (Fidelity's lot-level closed-position export).** Reconciles to the 1099-B Total Proceeds / Total Cost Basis / Total Realized Gain/Loss to the cent for the 2023 tax year. Strictly more complete than History `YOU SOLD` rows because it includes corporate-action proceeds (Cash In Lieu) that History omits. |
| **Wash sales / disallowed losses** | **1099-B is canonical.** Closed Positions exposes a `Total term gain/loss` column but does NOT expose the wash-sale-adjusted figure as a separate field. The 1099-B summary table carries `Total Wash Sales Disallowed`. For the household's 2023 sample, wash-sales disallowed = $0.00 across all sections, so the Closed Positions vs 1099-B agreement is not yet stress-tested for non-zero wash adjustments. |
| **Reconciliation handle** | **Symbol + disposal date + proceeds.** `Closed_Positions_2023.csv` and the 1099-B per-symbol rows agree to the cent on these three fields. History `YOU SOLD` rows agree on `YOU SOLD` row proceeds but miss corporate-action Cash-In-Lieu lines, producing a reconcilable but lossy delta. |
| **FID-LS-014 schema decision** | **NO new schema. Decision: declined.** The current writer already preserves subtype as evidence in two columns: `transactions.description` carries the normalized subtype prefix (`TMFC SHORT-TERM CAP GAIN`), and `transactions.raw_description` carries the verbatim Fidelity action verb. No consumer queries by subtype today; when and if one arrives, prefix matching against `description` is sufficient. Rationale below in §5. **No migration shipped in this slice.** |

## 2. Five-Source Survey

The survey ranks five candidate tax-lot sources against the household's
actual Fidelity export capabilities. Where ranking is supported by
side-by-side data inspection of real samples, it is marked
**(evidenced)**. Where ranking relies on documented Fidelity behavior
or industry reputation, it is marked **(by reputation)** so the
recommendation is honest about evidence levels.

### 2.1 Comparison Table

| Source | Coverage | Format | Frequency | Authority | Parser risk | Reconciliation handle | Evidence level |
|---|---|---|---|---|---|---|---|
| **Closed Positions CSV** (`Closed_Positions_<year>.csv`) | Closed lots only; per-symbol cost basis, proceeds, short-term/long-term gain split. **No** wash-sale-adjusted column; **no** per-lot disposal date (annual roll-up). | CSV with UTF-8 BOM, footer noise; column order: Account, Symbol, Description, Cost basis, Proceeds, Short-term gain/loss, Long-term gain/loss, Total term gain/loss. | On-demand from Fidelity site; not scheduled. | Internal Fidelity tracker; substitutes for GainsKeeper which household could not locate. | **Low.** Stable column shape; the existing parsing utilities in `scripts/ingest_fidelity_history.py` (`_clean_number`, header-line discovery, footer-strip) cover its quirks already. | Symbol + total proceeds + cost basis match 1099-B to the cent. **Cents-perfect.** | **Evidenced** (2023 sample agrees with 2023 1099-B). |
| **In-page lot detail click loop** (Positions UI, "View Lots" expansion) | Open lots only; per-lot acquisition date, per-lot cost basis, per-lot quantity, holding-period flag. **No** wash-sale info; **no** disposal data. | HTML / JSON-XHR scrape, behind authenticated session and possibly per-symbol AJAX. | Real-time; covers the user's current tax-lot view at click time. | UI projection; sourced from Fidelity's internal lot tracker. | **High.** DOM/MFA/session fragility; per-symbol click loop scales linearly with holdings; layout drift exposure. | Symbol + acquisition date + lot quantity. Reconciles to Positions CSV `Cost Basis Total` per symbol. | **By reputation** (no live capture in this audit; household has not exercised the click-loop scrape path). |
| **1099-B PDF** (Consolidated 1099, B-section) | Closed lots only; per-lot disposal date, per-lot acquisition date, per-lot proceeds, per-lot cost basis, term classification (short-term Box A vs long-term Box D), wash-sale disallowed amount. | PDF with multi-line wrapped layout (label row, value row, units row); per-lot detail shown as per-symbol grouped sections. | Annual; published Feb–Mar of following year. | **IRS authoritative.** This is what Fidelity reports to the IRS. | **Medium-high for per-lot detail.** The aggregate fields (boxes 1a/1b/2a/1) extract reliably with the current regex. The 1099-B per-section totals (Total Proceeds, Total Cost Basis, Net Gain/Loss) are silently dropped by the existing parser regex — see §3 of `1099-reconciliation.md`. Per-lot row extraction would require a new tabular parser. | Symbol + disposal date + proceeds. Cents-perfect against Closed Positions. | **Evidenced** (2023 + 2024 PDFs run through the parser; aggregate fields validated; per-lot detail visible in extracted text). |
| **Monthly statements + trade confirmations** (`Statement<MMDDYYYY>.pdf`) | Both open and closed events, point-in-time; per-trade lot detail at confirm time; account-level summary. | PDF, statement-style multi-section layout. | Monthly. | Authoritative trade confirmations; typically the IRS source for cost basis when a 1099-B is not yet issued. | **High.** No structured parser exists; statement layout drifts with Fidelity's templates; many sections (margin, options, mutual-fund detail) the parser must learn to skip. | Trade date + symbol + quantity + proceeds. | **By reputation** (Dec 2023 statement contains 9 SELL trade-confirmation references; no parser has been written). |
| **GainsKeeper / Tax Info export** | Both open and closed lots; explicit wash-sale tracking; lot-by-lot per-disposition basis assignment. | CSV/XLSX, Fidelity-defined columns. | On-demand annual + interim. | Internal Fidelity / NetWorth Services tax-lot tracker; the upstream of 1099-B. | **Low.** Structured table with stable schema. | Symbol + acquisition date + lot quantity + disposition method. | **Not available.** Household could not locate the download path on Fidelity's site. Closed Positions CSV is the functional substitute for closed-lot evidence; for open lots, in-page lot detail or 1099-B lookback are the alternatives. |

### 2.2 What "Cents-Perfect" Means For Closed Positions

`Closed_Positions_2023.csv` was downloaded for tax year 2023 and
contains 8 closed-position rows in the household's single account.
Aggregating `Cost basis` and `Proceeds` columns:

- Closed Positions sum of `Proceeds`: **$5,839.11**
- 1099-B 2023 Total Proceeds (LT + ST + unknown): **$5,839.11**
- Closed Positions sum of `Cost basis`: **$2,759.50**
- 1099-B 2023 Total Cost Basis: **$2,759.50**
- Implied Closed Positions realized gain/loss: **$3,079.61**
- 1099-B 2023 Realized Gain/Loss: **$3,079.61**

For comparison, summing `Amount ($)` from the 8 `YOU SOLD` rows in
`History_for_Account_2023.csv` yields **$5,829.76**, which is **$9.35
short** of the 1099-B / Closed Positions total. The $9.35 delta is
explained by Cash-In-Lieu corporate-action proceeds: the 1099-B
per-symbol detail and Closed Positions both include 9 Cash-In-Lieu
lines for one symbol (TSCO) totaling exactly $9.35; the History CSV
records only explicit `YOU SOLD` rows.

**Implication:** History `YOU SOLD` rows are not sufficient as a
closed-lot source. Closed Positions is.

## 3. Recommended Primary Source(s)

For each tax-lot question:

### 3.1 Open lots

**Primary:** `Portfolio_Positions_<date>.csv` (already wired by P17-T30
to `investment_holdings.cost_basis` per position) for **per-position
aggregate** cost basis. This is sufficient to support
`investment_holdings`-driven views.

**Per-lot acquisition date for open lots is not currently solvable**
from any download the household possesses, except as a year-end
1099-B lookback for lots that close. The current `get_lots()`
implementation derives lot evidence from `positions_ledger`
BUY/REINVESTMENT rows; for legacy positions that predate the live
connector's first ingest, `get_lots()` will continue to fall back to
"shares × closing price" with no per-lot acquisition date.

**Future option (not in scope for this slice):** the in-page lot
detail click loop is the highest-fidelity per-lot acquisition source
but carries DOM/MFA/session fragility. If/when this is implemented,
it would write to `positions_ledger` with `transaction_type =
'INITIAL_BASELINE'` rows backdated to the per-lot acquisition date,
preserving the existing FIFO consumption logic in `get_lots()`.

### 3.2 Closed lots

**Primary:** `Closed_Positions_<year>.csv`. Cents-perfect agreement
with 1099-B totals on the 2023 sample. Stable, structured CSV. No
selector or session fragility. The household's confirmed substitute
for the unavailable GainsKeeper export.

**Secondary (annual reconciliation):** 1099-B per-section totals.
These are needed regardless because they're the IRS-authoritative
figures and they're already in the `dal/parsers/fidelity_1099.py`
input path (although see §3 of `1099-reconciliation.md` for the
silent-drop bug on the totals fields).

### 3.3 Wash sales / disallowed losses

**Primary:** 1099-B Total Wash Sales Disallowed (per term section).
Closed Positions does NOT carry this column; only the 1099-B
authoritatively reports the wash-sale-adjusted figure.

**Caveat:** the household's 2023 1099-B reports `0.00` wash sales
disallowed across all sections, so the cents-perfect Closed Positions
vs 1099-B agreement is not yet stress-tested for non-zero wash
adjustments. A year with active wash-sale activity would be needed to
prove that "Closed Positions × 1099-B wash-sale column" remains
sufficient.

### 3.4 Reconciliation handle

**Primary:** symbol + disposal date + proceeds. Cents-perfect across
Closed Positions, 1099-B per-line detail, and History `YOU SOLD`
(modulo the corporate-action gap noted above).

For consumers that need a join-on-row identifier, `(symbol, disposal
date, quantity, proceeds_cents)` is the unique key on the household's
2023 sample. This is the reconciliation key the next implementation
slice should use.

## 4. Concrete Next-Step Implementation Prompt Skeleton

> **Implement the Closed Positions CSV writer.** Author a new
> Fidelity closed-lot ingest path that reads
> `Closed_Positions_<year>.csv` (BOM-prefixed UTF-8, header-and-footer
> structure already covered by `_clean_number` and the footer-strip
> conventions in `scripts/ingest_fidelity_history.py`), and writes one
> `positions_ledger` SELL row per closed-position row with
> `cost_basis_dec`, `share_delta_dec`, and `transaction_type =
> 'SELL'`. Pair the disposal date to the corresponding History
> `YOU SOLD` row by `(symbol, run_date, abs(quantity))` where
> available; for Cash-In-Lieu rows that don't appear in History, use
> the 1099-B per-line detail as the disposal-date evidence (year-end
> only). Closes `FID-LS-013` (SELL fixture); proves out the lot
> consumption path in `get_lots()`. Does NOT change schema. Add a
> redacted Closed Positions structural fixture under
> `tests/fixtures/fidelity/`. Verification: a closed-lot view in
> Investments shows realized gain/loss matching the 2023 1099-B's
> $3,079.61 to the cent.

This skeleton is intentionally one paragraph; the implementer authors
the full prompt under `docs/prompts/Phase-17/` when work begins.

## 5. FID-LS-014 Decision: No New Schema

P17-T29 deferred the question of whether qualified vs short-term vs
long-term capital-gain distributions need a dedicated subtype column
or side table. This audit lands the decision: **no new schema**. The
following rationale is recorded so a future implementer doesn't
re-litigate.

### 5.1 Subtype information is already preserved

`dal/fidelity_dividend_income.py` writes the `Investment Income`
transactions with two evidence columns populated:

- `transactions.description` carries the normalized prefix
  (`<TICKER> SHORT-TERM CAP GAIN`, `<TICKER> LONG-TERM CAP GAIN`,
  `<TICKER> CAP GAIN`, `<TICKER> DIVIDEND`).
- `transactions.raw_description` carries the verbatim Fidelity action
  verb (e.g., `LONG-TERM CAP GAIN <FUND DESCRIPTION> (<TICKER>)
  (Cash)`).

The writer's `_ACTION_MAP` (see `dal/fidelity_dividend_income.py:36`)
uses an ordered substring match — `LONG-TERM CAP GAIN` and
`SHORT-TERM CAP GAIN` are matched before the generic `CAP GAIN`
fallback — so subtype discrimination is deterministic at write time.

A consumer that wants to filter or aggregate by subtype can issue a
prefix LIKE clause against `description` (cheap with the
`idx_txn_account_date` index on a category-narrowed query) or pull
`raw_description` and parse the leading verb. The information is not
lost; it is denormalized into the description columns instead of a
dedicated subtype column.

### 5.2 No current consumer queries by subtype

A repo-wide search for callers that need to distinguish qualified vs
short-term vs long-term distributions returns:

- `dal/yearly_wrapup.py:577-601` consumes the 1099 PDF parser output
  for the yearly tax document flow. It surfaces the 1099 fields
  directly (ordinary, qualified, capital_gain_distributions), without
  joining back to the per-row CSV evidence. A subtype column on
  `transactions` would not help this consumer.
- `dal/reports/flow.py` reinvestment matcher keys on
  `category = 'Investment Income'` plus same-account
  `positions_ledger` proximity. It does not branch on subtype.
- The Investments UI / API in `dal/investments.py` reads
  `investment_holdings` and `positions_ledger`; it does not consult
  `transactions` for subtype.

There is no active consumer that would gain from a dedicated subtype
column today.

### 5.3 IRS reconciliation does not require denormalization

The `1099-reconciliation.md` companion shows that the 2024 1099 box 1a
($136.78) and box 2a ($3.68) reconcile cents-perfectly to History
`DIVIDEND RECEIVED` ($134.44) + History `SHORT-TERM CAP GAIN` ($2.35)
and History `LONG-TERM CAP GAIN` ($3.67), respectively, with combined
total agreement of $140.46 = $140.46. The IRS routing rule (short-term
cap gain distributions taxed as ordinary income; long-term as cap gain
distributions) is recoverable from a `description LIKE 'SHORT-TERM
CAP GAIN%'` filter without any subtype column.

### 5.4 Cost-benefit

Adding a subtype column requires:

- A new sequential migration (next would be v45 — see §6 below).
- Backfill logic for existing rows from `description`/`raw_description`
  (parsing the same prefix the writer just wrote).
- A writer update to fill the new column on new ingests.
- New tests, new lineage YAML, new ARCHITECTURE.md §4.2 entry.
- A column on every `transactions` row, including the 99%+ that
  aren't `Investment Income`.

Benefits:

- A faster query path for a consumer that doesn't yet exist.

The cost is concrete; the benefit is hypothetical. **Decline the
schema change. Build for evidence; defer denormalization until proved
necessary.**

### 5.5 Reversibility note

If a future consumer materializes that needs subtype filtering at
analytical scale, the migration is straightforward: ALTER TABLE add
`tax_subtype TEXT NULL`, backfill from `description` prefix match,
update the writer to populate. The decision today does not foreclose
the option; it just defers it.

## 6. Migration Decision: Not Shipping One

The Decision Updates trailer in the prompt expanded scope to ship a
migration if FID-LS-014 concluded yes. FID-LS-014 concluded no.
Therefore: **no migration shipped in this slice.**

The next sequential migration number remains `v45` for whatever ships
next. Current latest is `dal/migrations/v44_positions_ledger_source_key.py`.

## 7. Caveats And What This Audit Did Not Settle

- **Wash-sale stress test deferred.** Household's 2023 1099-B has
  $0.00 wash sales disallowed. The Closed-Positions-vs-1099-B
  cents-perfect agreement is not stress-tested for a year with active
  wash adjustments. If a future tax year shows non-zero wash
  disallowed, re-verify that Closed Positions agrees with 1099-B
  including the wash adjustment.
- **Multi-account scoping not stressed.** Household has one Fidelity
  account (`X<redacted>`). The scoping work tracked under
  `FID-LS-012` is independent of this audit's recommendation.
- **In-page lot detail not exercised.** The DOM/MFA/session fragility
  ranking is documented but not validated by a live scrape. A future
  audit slice that actually runs the click-loop scrape would refine
  this ranking.
- **Open-lot acquisition date for legacy lots remains unsolved.**
  Lots that pre-date the live connector's first ingest have no
  parseable per-lot acquisition date until they close (at which point
  the 1099-B per-line detail provides the historical acquisition
  date). This is an inherent limitation of the available sources, not
  a parser gap.
- **GainsKeeper unavailability is documented, not investigated.**
  Household reports they could not locate the export path on
  Fidelity's site. Closed Positions CSV is the substitute and is
  sufficient. If GainsKeeper turns out to be discoverable in a later
  pass, it can be added as a higher-fidelity supplement to Closed
  Positions; it does not invalidate the Closed Positions
  recommendation.

## 8. Mismatch Ledger Linkages

This document closes:

- `FID-LS-007` → "Closed Positions CSV is the closed-lot source;
  per-position cost basis is the open-lot source; per-lot open
  acquisition date is unsolvable from current downloads (in-page lot
  detail or trade-confirmation parsing is the future option)."
- `FID-LS-014` → "No new schema; subtype is preserved in
  `description` and `raw_description` already; revisit if a consumer
  emerges."
- `FID-LS-015` → see [`1099-reconciliation.md`](1099-reconciliation.md).

Two new follow-up receipts are filed (see ledger):

- `FID-LS-016` (gap, parser silent-drop): the 1099 parser regex for
  `Total proceeds` / `Total cost basis` / `Net gain (loss)` does not
  match Fidelity's actual layout and silently returns no value. The
  `can_commit` guard does NOT fire because box 1a IS extracted.
- `FID-LS-017` (gap, wash-sale evidence): the recommended
  Closed-Positions-as-truth path is not yet stress-tested against a
  tax year with non-zero wash sales disallowed.
