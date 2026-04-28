"""
v43: Rewrite ``v_investment_contributions`` to join via ``bank_txn_id``.

The v34 view classified positions_ledger rows by joining transactions on
``(account_id, date, transfer_tag IS NOT NULL)`` — a workaround for not
using the link column the data already maintains. That predicate is wrong
for every Shape-B money flow into an investment account (Acorns, Fidelity
EFT, future TSP, future taxable broker), because the bank-side cash leg
sits on a checking account while the ledger rows sit on the brokerage
account. The account_id predicate never aligns and Acorns/Fidelity
contributions ALWAYS classify as ``intra_account_credit``, never
``user_contribution`` (AI-021).

Brokerages don't emit bank-style transactions rows in their feeds. A
brokerage statement is share movements (positions_ledger), not currency
movements. The structurally honest link from a bank-side cash leg to
the brokerage activity it funded is ``positions_ledger.bank_txn_id``,
which the post-commit linker already populates for both Acorns and
Fidelity (mirrors the ``_link_acorns_bank_debits`` pattern at
``backend/result_writer.py:473``).

The new view joins on that column directly. Only the ONE primary ledger
row per cash leg (the row carrying ``bank_txn_id``) classifies as
``user_contribution``; downstream allocation rows on the same date stay
``intra_account_credit``, which is semantically correct — they're
redeployment of money that already arrived, not new user contributions.

A partial covering index on ``bank_txn_id`` keeps the LEFT JOIN cheap
(typical synthetic DB has ~50 linked rows out of ~3000 ledger rows;
live data follows the same shape).

Idempotent: ``DROP VIEW IF EXISTS`` + ``CREATE INDEX IF NOT EXISTS``.
"""

VERSION = 43


def run(conn):
    cur = conn.cursor()

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_positions_ledger_bank_txn_id
            ON positions_ledger(bank_txn_id)
            WHERE bank_txn_id IS NOT NULL
        """
    )

    cur.execute("DROP VIEW IF EXISTS v_investment_contributions")

    cur.execute("""
        CREATE VIEW v_investment_contributions AS
        SELECT
            pl.id               AS ledger_id,
            pl.account_id       AS account_id,
            pl.timestamp        AS timestamp,
            pl.ticker           AS ticker,
            pl.transaction_type AS transaction_type,
            pl.share_delta      AS share_delta,
            pl.new_total_shares AS new_total_shares,
            pl.bank_txn_id      AS bank_txn_id,
            t.id                AS matched_tx_id,
            t.signed_amount     AS matched_tx_signed_amount,
            t.transfer_tag      AS matched_tx_transfer_tag,
            t.account_id        AS matched_tx_account_id,
            CASE
                WHEN pl.share_delta > 0 AND t.id IS NOT NULL THEN 'user_contribution'
                WHEN pl.share_delta > 0 AND t.id IS NULL     THEN 'intra_account_credit'
                WHEN pl.share_delta < 0                       THEN 'sale_or_transfer_out'
                ELSE 'unknown'
            END                 AS classification
        FROM positions_ledger pl
        LEFT JOIN transactions t
          ON t.id = pl.bank_txn_id
    """)
