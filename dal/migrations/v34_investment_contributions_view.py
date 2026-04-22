"""
v34: v_investment_contributions view (Phase 14 Phase C).

Classifies every ``positions_ledger`` row as either a user-driven contribution
(a paired cash-side transfer exists), an intra-account credit (dividend
reinvestment, employer match), or a sale/transfer-out. Phase D's accountability
scorecard joins against this view to separate "dollars the user sent in" from
"cash that appeared inside the account and bought more shares."

The left join matches on ``(account_id, posting_date == timestamp date)`` and
requires ``transfer_tag IS NOT NULL`` so we only catch the cash leg of a
reconciled transfer. A dividend transaction that credits the brokerage account
has ``transfer_tag IS NULL`` and will therefore NOT match — that's intentional,
the reinvestment leg is an intra-account credit regardless of whether a cash-side
dividend transaction exists.

View, not materialized table: contribution classification depends on the
current ``transactions.transfer_tag`` — any recategorization or re-reconcile
would silently stale a cache. If Phase D benchmarks show >500ms latency on
the scorecard, revisit and add a recompute hook.

DDL only: no data changes, no constraints to backfill.
"""

VERSION = 34


def run(conn):
    cur = conn.cursor()

    cur.execute("DROP VIEW IF EXISTS v_investment_contributions")

    cur.execute("""
        CREATE VIEW v_investment_contributions AS
        SELECT
            pl.id             AS ledger_id,
            pl.account_id     AS account_id,
            pl.timestamp      AS timestamp,
            pl.ticker         AS ticker,
            pl.transaction_type AS transaction_type,
            pl.share_delta    AS share_delta,
            pl.new_total_shares AS new_total_shares,
            t.id              AS matched_tx_id,
            t.signed_amount   AS matched_tx_signed_amount,
            t.transfer_tag    AS matched_tx_transfer_tag,
            CASE
                WHEN pl.share_delta > 0 AND t.id IS NOT NULL THEN 'user_contribution'
                WHEN pl.share_delta > 0 AND t.id IS NULL     THEN 'intra_account_credit'
                WHEN pl.share_delta < 0                       THEN 'sale_or_transfer_out'
                ELSE 'unknown'
            END               AS classification
        FROM positions_ledger pl
        LEFT JOIN transactions t
          ON t.account_id = pl.account_id
         AND date(t.posting_date) = date(pl.timestamp)
         AND t.transfer_tag IS NOT NULL
    """)
