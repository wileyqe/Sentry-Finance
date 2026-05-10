# Fidelity 1099 Reconciliation Audit

This document closes `FID-LS-015` (CSV audit did not validate
`dal/parsers/fidelity_1099.py`). It pairs with
[`tax-lot-source-recommendation.md`](tax-lot-source-recommendation.md)
which closes `FID-LS-007` and `FID-LS-014`.

The reconciliation runs the existing
`dal/parsers/fidelity_1099.py` against two real Consolidated 1099
PDFs (tax years 2023 and 2024) the household placed in
`raw_exports/fidelity/` (gitignored), and compares the parser output
against:

- the corresponding History CSV `DIVIDEND RECEIVED` /
  `LONG-TERM CAP GAIN` / `SHORT-TERM CAP GAIN` row sums;
- the corresponding `Closed_Positions_<year>.csv` totals (where
  applicable);
- the 1099-B per-section totals visible in the extracted PDF text.

Per-symbol detail is not reproduced here. Aggregate dollar totals are
quoted because they are needed to support the agreement claim and are
visible on the 1099-B summary tables.

## 1. Parser Run Results

Run via `Fidelity1099Parser.parse(content)` against each PDF:

| Tax Year | `can_parse` | `can_commit` | Warnings | Fields extracted |
|---|:---:|:---:|---|---|
| 2023 | ✓ | ✓ | (none) | `tax_year`, `ordinary_dividends`, `qualified_dividends`, `capital_gain_distributions`, `interest_income` |
| 2024 | ✓ | ✓ | (none) | `tax_year`, `ordinary_dividends`, `qualified_dividends`, `capital_gain_distributions`, `interest_income` |

**Fields the parser does NOT extract on either sample:**

- `total_proceeds` (1099-B summary)
- `total_cost_basis` (1099-B summary)
- `total_gain_loss` (1099-B summary)

The parser regex for these three fields does not match the actual
Fidelity 1099-B summary layout. **This is a silent drop.** No warning
is raised. The `can_commit` guard does not trip because the four
fields it monitors (`ordinary_dividends`, `qualified_dividends`,
`capital_gain_distributions`, `interest_income`, `total_proceeds`)
include three that DO extract.

See §3 below for the layout analysis and §4 for the follow-up receipt.

## 2. Aggregate Reconciliation

### 2.1 Tax Year 2023

| 1099 Field | 1099 Value (parsed) | CSV-derived | Source CSV(s) | Result |
|---|---:|---:|---|---|
| Box 1a (Total ordinary dividends) | $35.14 | $0.00 | History 2023 has no dividend rows (account had only sells) | **Pre-funding history; no in-period dividend evidence in CSV.** The $35.14 reflects dividends that posted during a period not covered by the CSV pull. **Not a parser/writer mismatch.** |
| Box 1b (Qualified dividends) | $24.43 | n/a | (no consumer today) | **Subtype not denormalized into a DB column.** This is the deliberate design conclusion of FID-LS-014. |
| Box 2a (Total capital gain distributions) | $0.00 | $0.00 | History 2023 has no `CAP GAIN` rows | **Agree to the cent.** |
| Box 1 (Interest income) | $0.00 | $0.00 | History 2023 has no SPAXX/FDRXX dividend or interest rows | **Agree to the cent.** |
| 1099-B Total Proceeds | (parser drops it; **see §3**) | $5,839.11 | `Closed_Positions_2023.csv` | 1099-B PDF text shows $5,839.11; agrees to the cent against Closed Positions; **parser silently drops the field** (FID-LS-016). |
| 1099-B Total Cost Basis | (parser drops it) | $2,759.50 | `Closed_Positions_2023.csv` | 1099-B PDF text shows $2,759.50; agrees to the cent; parser silently drops. |
| 1099-B Total Realized Gain/Loss | (parser drops it) | $3,079.61 | `Closed_Positions_2023.csv` (implied) | 1099-B PDF text shows $3,079.61; agrees to the cent; parser silently drops. |

History `YOU SOLD` row sum for 2023: $5,829.76, which is **$9.35
short** of the 1099-B / Closed Positions total. The $9.35 delta is
explained by Cash-In-Lieu corporate-action proceeds that the
1099-B per-line detail and Closed Positions both record as separate
rows (visible per-line evidence in the extracted PDF text totals: 9
Cash-In-Lieu lines for one symbol summing to exactly $9.35). History
records only explicit `YOU SOLD` rows. Implication: History is not a
sufficient closed-lot source on its own (already reflected in the
recommendation in `tax-lot-source-recommendation.md` §3.2).

### 2.2 Tax Year 2024

| 1099 Field | 1099 Value (parsed) | CSV-derived | Source CSV | Result |
|---|---:|---:|---|---|
| Box 1a (Total ordinary dividends) | $136.78 | $134.44 | History 2024 `DIVIDEND RECEIVED` rows (26 rows) | **Off by -$2.34.** Resolved by adding History `SHORT-TERM CAP GAIN` row ($2.35); see combined row below. |
| Box 1b (Qualified dividends) | $60.31 | n/a | (no consumer today) | FID-LS-014 conclusion: subtype not denormalized; not a writer gap. |
| Box 2a (Total capital gain distributions) | $3.68 | $3.67 | History 2024 `LONG-TERM CAP GAIN` row (1 row) | **Off by +$0.01 (rounding).** |
| Box 1 (Interest income) | $0.00 | $0.00 | History 2024 has no SPAXX/FDRXX interest | **Agree.** |
| **Combined: Box 1a + Box 2a vs History (DIV + ST CAP + LT CAP)** | $140.46 | $140.46 | History 2024 dividend + cap-gain rows | **Agree to the cent.** |
| 1099-B Total Proceeds | (parser drops it) | n/a | n/a | 1099-B PDF text shows $0.00 for 2024; no `Closed_Positions_2024.csv` provided by household. |
| 1099-B Total Cost Basis | (parser drops it) | n/a | n/a | 1099-B PDF text shows $16.40 for 2024 (a small worthless-security write-off). |
| 1099-B Total Realized Gain/Loss | (parser drops it) | n/a | n/a | 1099-B PDF text shows -$16.40 for 2024. |

The 2024 result is the more interesting reconciliation: it confirms
the **IRS routing rule** that short-term capital gain distributions
roll into Box 1a (taxed as ordinary income), while long-term
distributions roll into Box 2a. The History CSV preserves both
verbatim:

- `SHORT-TERM CAP GAIN <fund description> (<TICKER>) (Cash)` →
  $2.35 → contributes to Box 1a.
- `LONG-TERM CAP GAIN <fund description> (<TICKER>) (Cash)` →
  $3.67 → contributes to Box 2a.

This is exactly the discrimination the writer's `_ACTION_MAP`
preserves in `transactions.description` and `transactions.raw_description`
already, validating the FID-LS-014 "no new schema" decision.

### 2.3 Box 1b (Qualified Dividends) Gap Quantification

Box 1b is reported by Fidelity but has no CSV-derived counterpart.
History `DIVIDEND RECEIVED` rows do not carry a qualified flag. The
qualified-vs-non-qualified split is determined at the security and
holding-period level by Fidelity's tax engine and surfaced only on
the 1099, not in the History CSV.

For the household's two sample years:

| Year | 1a Total | 1b Qualified | Qualified ratio |
|---|---:|---:|---:|
| 2023 | $35.14 | $24.43 | 69.5% |
| 2024 | $136.78 | $60.31 | 44.1% |

Today's downstream consumer is `dal/yearly_wrapup.py:577-601`, which
surfaces both fields as separate keys
(`ordinary_dividends`, `qualified_dividends`) in the Fidelity yearly
investment-income block. **No reconciliation against CSV is required
for Box 1b**: the CSV doesn't carry the truth, and the 1099 is the
authoritative source. The audit's role here is to confirm that the
existing parser path correctly extracts Box 1b (✓ verified for both
sample years).

## 3. Parser Layout Analysis: 1099-B Totals Silent Drop

The parser at `dal/parsers/fidelity_1099.py:46-53` defines:

```python
m_b_proc = re.search(r"Total proceeds.*?([\d,]+\.\d{2})", text, re.IGNORECASE)
m_b_cost = re.search(r"Total cost basis.*?([\d,]+\.\d{2})", text, re.IGNORECASE)
m_b_gain = re.search(r"Net gain \(loss\).*?(\-?[\d,]+\.\d{2})", text, re.IGNORECASE)
```

The actual 1099-B summary layout in the household's PDFs reads (with
extracted PDF whitespace preserved):

```text
Summary of 2023 Proceeds From Broker and Barter Exchange Transactions
1099-BSection Total Total Total Total Realized Federal
Proceeds CostBasis Market Wash Gain/Loss IncomeTax
Discount Sales Withheld
Short-termtransactionsforwhichbasisisreportedtotheIRS 3.18 3.20 0.00 0.00 -0.02 0.00
Short-termtransactionsforwhichbasisisnotreportedtotheIRS 0.00 0.00 0.00 0.00 0.00 0.00
Long-termtransactionsforwhichbasisisreportedtotheIRS 5,835.93 2,756.30 0.00 0.00 3,079.63 0.00
Long-termtransactionsforwhichbasisisnotreportedtotheIRSandTermisUnknown 0.00 0.00 0.00 0.00 0.00 0.00
TransactionsforwhichbasisisnotreportedtotheIRSandTermisUnknown 0.00 0.00 0.00 0.00 0.00 0.00
5,839.11 2,759.50 0.00 0.00 3,079.61 0.00
```

Three observations:

1. The literal substring `Total proceeds` does not appear in this
   block. The labels are wrapped: `Total Total Total Total Realized
   Federal` on one line and `Proceeds CostBasis Market Wash Gain/Loss
   IncomeTax` on the next. The regex `Total proceeds.*?([\d,]+\.\d{2})`
   would only match if a literal "Total proceeds" appeared adjacent to
   a number, which it does not in this layout.
2. The actual aggregate totals (`5,839.11 2,759.50 0.00 0.00
   3,079.61 0.00`) appear as an **unlabeled trailing line** at the
   end of the per-section breakdown. They cannot be matched by a
   simple literal-prefix regex.
3. The "Net gain (loss)" string in the `m_b_gain` regex never appears
   in either sample PDF; the IRS-shaped header label is "Realized
   Gain/Loss" (no parentheses).

The current `can_commit` silent-failure guard (lines 73–85) fires only
if NONE of the core fields (`ordinary_dividends`, `qualified_dividends`,
`capital_gain_distributions`, `interest_income`, `total_proceeds`)
extracts. Because boxes 1a/1b/2a/1 do extract reliably, the guard does
not fire even when the three 1099-B totals are silently dropped. The
parser appears healthy from the consumer's point of view but silently
loses three fields the consumer claims to want.

**Downstream impact:** `dal/yearly_wrapup.py:577-601` reads
`fields.get("total_proceeds")` and `fields.get("total_cost_basis")`
into the Fidelity investment-income block. Both keys are currently
returning `None` on real 1099 inputs. This means the yearly tax
document UI is missing the Fidelity 1099-B closed-position aggregate
totals on every household with non-zero closed positions, with no
warning shown.

This is a real bug, not a parser hardening preference. It is filed
as `FID-LS-016` in the mismatch ledger as a follow-up gap. **It is
not fixed in this slice** because the slice is scoped to
audit-and-recommend-or-migration; the parser hardening fix is a
separate code-change slice that should add a tabular extractor for
the `Summary of <YYYY> Proceeds From Broker and Barter Exchange
Transactions` block and update the `can_commit` guard to flag a
section-recognized-but-totals-missing case.

## 4. Recommended Follow-Up Issues

### 4.1 Parser silent-drop fix (FID-LS-016)

**Severity:** gap (not a block — the parser still commits and
reports four valid fields, but it silently loses three claimed
fields).

**Scope:**

- Add a tabular extractor for the `Summary of <YYYY> Proceeds From
  Broker and Barter Exchange Transactions` block. Match the
  per-section rows by anchoring on
  `Short-termtransactionsforwhichbasisisreportedtotheIRS\s+(\d+\.\d{2})\s+(\d+\.\d{2})...`
  pattern and sum the per-section rows; or match the trailing
  unlabeled total line that follows the four per-section rows.
- Replace the `Net gain (loss)` regex with `Realized\s+Gain/Loss`
  (the actual label on the 1099 layout) or compute `total_proceeds -
  total_cost_basis` directly.
- Update the `can_commit` guard so it can also detect "section
  recognized but totals not extracted" and surface that as a warning
  rather than a silent zero.
- Add a redacted regression fixture under `tests/fixtures/fidelity/`
  with the expected layout shape (totals row only; no per-symbol
  detail).

**Verification:** parser output on the 2023 PDF gives
`total_proceeds=5839.11`, `total_cost_basis=2759.50`,
`total_gain_loss=3079.61`; parser output on the 2024 PDF gives
`total_proceeds=0.00`, `total_cost_basis=16.40`, `total_gain_loss=-16.40`.

### 4.2 Wash-sale evidence (FID-LS-017)

**Severity:** gap (cannot validate today; requires future tax-year
data).

**Scope:** when a tax year with non-zero wash sales disallowed
becomes available, re-run the Closed Positions vs 1099-B
reconciliation including the wash-sales-disallowed column. Confirm
that Closed Positions either carries the wash-adjusted figure or
that the recommendation's "1099-B is canonical for wash-sale
disallowed" assertion holds without surprise.

## 5. Mismatch Ledger Linkage

`FID-LS-015` → "Parser run on real 2023 + 2024 PDFs; box 1a/1b/2a/1
extract reliably; 1099-B totals (proceeds/cost basis/realized
gain/loss) silently drop. Decided. See this document and follow-up
receipt FID-LS-016."

`FID-LS-016` (new) → see §4.1 above.

`FID-LS-017` (new) → see §4.2 above.
