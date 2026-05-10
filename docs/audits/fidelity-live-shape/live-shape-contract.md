# Fidelity Live-Shape Contract

This contract describes what the Fidelity live ingest path must tolerate before
the single-user trust bar. It is grounded in redacted fixtures under
`tests/fixtures/fidelity/`, raw-export structural summaries, and current code.

## 1. History CSV Schema

Observed history files contain two blank lines before the header, then this
column order:

```text
Run Date,Action,Symbol,Description,Type,Price ($),Quantity,Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date
```

Rows after the valid dated records contain footer/disclaimer noise. The parser
must find the `Run Date` header, read from there, and drop rows where `Run Date`
does not parse as `MM/DD/YYYY`. Current code does this in
`scripts/ingest_fidelity_history.py:90`, `:114`, and `:118`.

| Action substring | Observed in samples | Semantic mapping | Current route |
|---|---:|---|---|
| `YOU BOUGHT` | yes | `BUY` | Classified as `BOUGHT`; used in in-memory daily reconstruction only. |
| `REINVESTMENT` | yes | `REINVESTMENT` | Classified as `REINVESTMENT`; used in reconstruction only. |
| `DIVIDEND RECEIVED` | yes | `DIVIDEND` cash event | Classified as `DIVIDEND`; no `Investment Income` transaction is written. |
| `CAP GAIN` | yes | dividend/capital-gain distribution | Classified as `DIVIDEND`; qualified/long-term distinction is lost. |
| `Electronic Funds Transfer Received (Cash)` | yes | `EFT_IN` | Classified as `DEPOSIT`; no bank-side transaction or `bank_txn_id` link is written. |
| `Electronic Funds Transfer Paid (Cash)` | yes | `EFT_OUT` | Classified as `WITHDRAWAL`; no bank-side transaction/link is written. |
| `EXPIRED` | yes | position removal without cash | Classified as `EXPIRED`; not persisted to the DB. |
| `YOU SOLD` | not in samples | `SELL` | Classifier supports `SOLD`, but the available live samples do not prove the shape. |
| fee, journal, transfer of shares, option/margin verbs | not in samples | `FEE`, `JOURNAL`, `TRANSFER`, `OTHER` | Would fall to `OTHER` today unless a substring already matches. |

## 2. Positions CSV Schema

Observed positions files use this column order:

```text
Account Number,Account Name,Symbol,Description,Quantity,Last Price,Last Price Change,Current Value,Today's Gain/Loss Dollar,Today's Gain/Loss Percent,Total Gain/Loss Dollar,Total Gain/Loss Percent,Percent Of Account,Cost Basis Total,Average Cost Basis,Type
```

The parser strips asterisks from `Symbol`, cleans selected numeric columns, and
drops rows with no symbol (`scripts/ingest_fidelity_history.py:150-169`). A
SPAXX row is present as a money-market sweep and has blank cost-basis fields.
The live writer must keep SPAXX as cash/equivalent, not an equity allocation.

`Cost Basis Total` is the preferred positions-level basis source when present.
`Average Cost Basis` is useful only as a cross-check or fallback. As of
P17-T30 the live Fidelity writer
(`dal/fidelity_investment_writes.py::write_fidelity_investment_state`)
persists `Cost Basis Total` directly to `investment_holdings.cost_basis`
for non-cash positions (SPAXX/FDRXX excluded), and falls back to
`Average Cost Basis × Quantity` only when `Cost Basis Total` is blank.
The legacy aggregate write to `loan_details.cost_basis` was retired —
`extractors/fidelity_connector.py` no longer calls `record_loan_details`,
so the Investments holdings/lots readers (`dal/investments.py:56-94`,
`:193-272`) are the canonical source of truth.

## 3. Currency And Numeric Formatting

The live path must tolerate:

- History amounts with minus signs and blank numeric cells.
- Positions currency with dollar prefixes, comma groupings, trailing spaces,
  and parenthesized negative gain/loss values.
- Integer, decimal, and blank quantities.
- Fractional share quantities with at least three decimal places in current
  samples; tests preserve 0.196 and 0.755 dummy quantities.
- Scientific notation if Fidelity emits it in future exports.

Current `_clean_number` strips dollar signs, commas, quotes, and whitespace, but
does not parse parenthesized negatives (`scripts/ingest_fidelity_history.py:56`).

## 4. Dividend Semantics

Live dividend-like rows are identified by:

- `DIVIDEND RECEIVED`
- `CAP GAIN`

The live writer must create posted cash transactions with:

- `category = 'Investment Income'`
- positive `signed_amount`
- `transfer_tag IS NULL`
- a merchant/description shape that can pair to a same-account
  `positions_ledger` `REINVESTMENT` or `BUY` row when the dividend is
  reinvested.
- `Run Date` as the factual `posting_date` / `transaction_date`; missing
  dates or non-positive amounts must skip without writing rather than guessing.
- raw Fidelity action text preserved as source evidence, not a new subtype
  schema in P17-T29.

This is required because reinvestment flow detection keys on
`category = 'Investment Income'` and a nearby `positions_ledger` row
(`dal/reports/flow.py:557-620`). AI-016 carried the same rule forward in
`docs/data-lineage/ACTION_ITEMS.md:192-204`.

Ambiguity to preserve: SPAXX sweep dividends, equity dividends, short-term
capital gains, long-term capital gains, and qualified dividends may all require
the same cash-flow category while retaining source evidence for a future tax
subtype decision. SPAXX/FDRXX are cash equivalents: their dividend income can be
written as `Investment Income`, but their sweep reinvestment must not be forced
into an illiquid reinvestment flow.

## 5. EFT Cash-Leg Coupling

Observed live EFT substrings:

- `Electronic Funds Transfer Received (Cash)`
- `Electronic Funds Transfer Paid (Cash)`

Current synthetic Fidelity contributions are checking-account debits described
as `FIDELITY EFT TRANSFER`, linked to a primary investment ledger row via
`positions_ledger.bank_txn_id` and `transactions.investment_link`
(`scripts/dummy_data/generator.py:1083`, `:1241-1247`). The reporting path
depends on Shape B, `transactions JOIN positions_ledger ON pl.bank_txn_id = t.id`
(`dal/reports/flow.py:358-439`).

The live Fidelity writer must create zero-share investment-side marker rows
for each external EFT: `DEPOSIT` for cash received into Fidelity and
`WITHDRAWAL` for cash paid out of Fidelity. Those marker rows are Fidelity-side
evidence only; they must not create bank-side transactions or link to later
security buys.

The follow-on EFT linker is link-only: it may stamp `bank_txn_id` only when an
existing imported bank transaction uniquely matches the Fidelity marker. SPAXX
reinvestments and later security purchases must not be classified as user
contributions; the lane movement is bank cash -> Fidelity/SPAXX.

## 6. Cost-Basis Source Of Truth

Current downstream readers:

- Holdings UI/API: `investment_holdings.cost_basis` when latest holdings exist
  (`dal/investments.py:56-94`).
- Holdings fallback: `positions_ledger` shares with no cost basis
  (`dal/investments.py:102-138`).
- Lot UI/API: FIFO lots from `positions_ledger.cost_basis_dec`, with a fallback
  to shares times closing price (`dal/investments.py:193-272`).
- Reinvestment flow matching: `positions_ledger.cost_basis_dec` compared to the
  cash dividend amount (`dal/reports/flow.py:604-620`).

Therefore, live per-position cost basis must land in `investment_holdings`, and
trade/reinvestment basis must land in `positions_ledger.cost_basis_dec` when the
row represents a lot-forming event. A single summed cost basis in `loan_details`
is not sufficient for current consumers, and is no longer written by the live
Fidelity path as of P17-T30.

## 7. Tax-Lot Readiness

The current Activity plus Positions CSVs cannot reconstruct full tax lots. They
show current position-level cost basis and activity-level share changes, but do
not provide per-lot acquisition dates, lot-specific basis for still-open lots,
disposal lot selection, or wash-sale adjustments.

Feasibility ranking for additional sources:

1. GainsKeeper or Tax Info export: best structured lot-level source if
   available; lower parser risk than UI scraping.
2. In-page lot detail click loop from Positions: direct current-lot evidence,
   but higher selector/MFA/session fragility.
3. Closed Positions page/export: useful for sold lots and realized gains, but
   may not cover open-lot basis.
4. Trade confirmations or statements: authoritative but PDF-heavy and noisier.
5. 1099-B PDF: useful annual reconciliation after year end, not sufficient for
   current in-year open-lot UI.
