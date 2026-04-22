"""
v33: loan_payment_splits (Phase 14 Phase B).

Stores the amortization decomposition of each posted mortgage/loan payment
into ``principal_cents + interest_cents + escrow_cents``. The Sankey
classifier routes principal → STORED_ILLIQUID and interest/escrow → CONSUMED.

Invariant
---------
    principal_cents + interest_cents + escrow_cents == abs(transactions.signed_amount)

Enforced in ``dal.debt.decompose_payment`` at write time; a ``CHECK``
is not added at the SQL layer because the reference transaction's
``signed_amount`` is stored as REAL (legacy) — a row-level SQL check
against a cross-table value is awkward. The DAL helper validates on
every upsert and re-validation is a one-line SQL assert in tests.

Method values
-------------
- ``amortization`` — computed from APR (``loan_details``) and outstanding
  balance (``balance_snapshots``) at ``posting_date``.
- ``statement`` — parsed directly from a loan statement line item.
  Reserved for when a statement parser is wired; Phase B does not ship
  one, but the method value is reserved so a future parser does not
  require a schema change.
- ``manual`` — future UI override path (backlog).

Note: ``transactions.id`` is TEXT in this repo (opaque id after v31), so
``transaction_id`` is TEXT here despite the prompt file referencing
INTEGER — the prompt doc is wrong about the column type.
"""

VERSION = 33


def run(conn):
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS loan_payment_splits (
            transaction_id    TEXT    PRIMARY KEY REFERENCES transactions(id),
            principal_cents   INTEGER NOT NULL,
            interest_cents    INTEGER NOT NULL,
            escrow_cents      INTEGER NOT NULL DEFAULT 0,
            computed_at       TEXT    NOT NULL DEFAULT (datetime('now')),
            method            TEXT    NOT NULL CHECK (method IN
                                        ('amortization', 'statement', 'manual'))
        )
    """)

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_loan_payment_splits_method "
        "ON loan_payment_splits(method)"
    )
