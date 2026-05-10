# TSP Inter-Fund Transfer Model Guidance

## Rule

A TSP inter-fund transfer is an intra-account reallocation. It changes units by
fund but does not create new household money.

It must not appear as:

- income,
- spending,
- a bank transfer,
- a user contribution,
- a withdrawal,
- an investment dividend.

## Proposed Ledger Shape

Use `positions_ledger` rows with:

- `account_id`: the TSP account id.
- `timestamp`: factual TSP transfer effective date/time when known.
- `ticker`: each affected TSP fund ticker.
- `transaction_type`: a future explicit value such as `INTER_FUND_TRANSFER`,
  or paired `SELL`/`BUY` rows only if downstream code can keep them out of
  cash-flow/contribution reporting.
- `share_delta`: negative for the source fund, positive for destination funds.
- `new_total_shares`: post-transfer units for each affected fund.
- `yfinance_closing_price` / `close_price_dec`: TSP NAV used to value the unit
  movement.
- `estimated_transaction_value`: value of each leg for auditability.
- `source`: `tsp_statement`, `tsp_connector`, or another TSP-specific source.
- `source_key`: stable source id if available.
- `bank_txn_id`: `NULL`.

The positive destination-fund rows must classify as `intra_account_credit`, not
`user_contribution`. If the current `v_investment_contributions` CASE statement
cannot express this safely for positive share deltas with no `bank_txn_id`, the
P17-T50 slice should add a test before changing behavior.

## Snapshot Shape

After an IFT:

- `investment_holdings` should record the post-transfer units and NAV by fund.
- `portfolio_snapshots.total_account_value` should reflect market value after
  the transfer.
- Top-line value should change only by market price movement and rounding, not
  by the transfer itself.
- `tax_buckets` should remain unchanged unless the TSP evidence explicitly
  says the tax bucket split changed.

## Cash-Flow Exclusions

No `transactions` row should be synthesized for an IFT. No
`transactions.transfer_tag` should be created. Cash Flow, Reports, Sankey, and
accountability contribution views should see zero income, zero spending, and
zero user contribution from the event.
