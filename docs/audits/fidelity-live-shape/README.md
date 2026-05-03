# Fidelity Live-Shape Readiness Audit

This audit compares the existing Fidelity live CSV exports against the
synthetic investment model and the current ingest/UI contracts. The headline
finding is that the parser recognizes much of the observed live shape, but the
live ingest path does not yet write Fidelity holdings, activity, dividends, EFT
links, or per-holding cost basis into the investment tables that the app reads.

## Artifacts

- [Live-shape contract](live-shape-contract.md)
- [Mismatch ledger](mismatch-ledger.md)
- Regression gauntlet:
  `tests/test_fidelity_live_shape_contract.py`
- Redacted fixtures:
  `tests/fixtures/fidelity/`

## Mismatch Summary

| Severity | Count | IDs |
|---|---:|---|
| `block` | 4 | FID-LS-001, FID-LS-004, FID-LS-005, FID-LS-006 |
| `gap` | 9 | FID-LS-002, FID-LS-003, FID-LS-007, FID-LS-009, FID-LS-011, FID-LS-012, FID-LS-013, FID-LS-014, FID-LS-015 |
| `cosmetic` | 2 | FID-LS-008, FID-LS-010 |

## How This Audit Was Built

Source-only live samples were read from gitignored `raw_exports/fidelity/`:

| File | Redacted structural summary |
|---|---|
| `History_for_Account_2024.csv` | Two blank pre-header lines, expected history columns, 54 valid dated rows, 9 footer/noise rows, 7 observed action verb families. |
| `History_for_Account_2025.csv` | Two blank pre-header lines, expected history columns, 101 valid dated rows, 9 footer/noise rows, 5 observed action verb families. |
| `History_for_Account_2026.csv` | Two blank pre-header lines, expected history columns, 11 valid dated rows, 9 footer/noise rows, 4 observed action verb families. |
| `Portfolio_Positions_Mar-04-2026.csv` | Expected positions columns, 19 position rows, one SPAXX money-market row, one row with blank cost-basis fields. |

Only redacted structural fixtures were committed. Account numbers are replaced
with `X<redacted>`, descriptions use deterministic dummy security names, and
balances/holding amounts are scrubbed to dummy values while preserving column
order, header/footer noise, SPAXX shape, decimal precision, settlement-date
presence/absence, and currency formatting.

## What This Audit Does Not Cover

- Running the live Fidelity connector against the real site.
- Raw CSV, PDF, screenshot, account-number, balance, or real holding review in
  tracked files.
- 1099 PDF parser accuracy beyond identifying the separate code path.
- Options, margin, fixed income, foreign equities, bond CUSIPs, mutual-fund
  NAV-only positions, or corporate-action partial-share redemptions.
- Tax-lot perfection. The current Activity plus Positions CSV set is not enough
  to reconstruct lot-level acquisition dates and basis.
