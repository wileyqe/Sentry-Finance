"""
v40: Partial index on ``transactions.transfer_tag``.

The transfer-pair self-join used by ``dal/reports.py::_compute_bucket_totals``
(and consequently by every period-totals computation) was running ~700ms
on a 2k-row dummy DB because there was no index on ``transfer_tag``. The
self-join (``t1.transfer_tag = t2.transfer_tag AND t1.id != t2.id``) was
forcing a full-scan-of-t2 per row of t1.

A *partial* index (``WHERE transfer_tag IS NOT NULL``) keeps the index
small (only the ~10% of transactions that are transfers) while still
giving SQLite a hash-able key for the equi-join.

After this index lands, the same self-join completes in <5ms on the
seeded DB.

Idempotent: ``CREATE INDEX IF NOT EXISTS``.
"""

VERSION = 40


def run(conn):
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_txn_transfer_tag
            ON transactions(transfer_tag)
            WHERE transfer_tag IS NOT NULL
        """
    )
