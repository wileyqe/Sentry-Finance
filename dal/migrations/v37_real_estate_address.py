"""
v37: Add ``address``, ``purchase_price``, ``purchase_date`` to ``real_estate``.

PR1 of the Account/Asset Details single-source-of-truth fix
(``docs/prompts/Phase-15/P15-T10_details-panel-single-source.md``).

Today the property address lives ONLY in the ``loan_details`` KV table
(as ``collateral_description``) and ``real_estate.name`` carries a
generic label like "Primary Residence". That puts the address on the
loan side of the join even though it identifies the property, not the
loan, and means the home-side details panel cannot render the address
at all. Same reasoning for ``purchase_price`` (currently in loan KV)
and ``purchase_date`` (not stored anywhere).

``real_estate`` is append-only — every quarterly valuation is its own
row. New columns are nullable; only the latest row per property needs
to carry them. The composer reads the latest non-null value per column
when assembling the panel bundle.

Idempotent against partial re-runs via ``column_exists``.
"""

from dal.migrations import column_exists

VERSION = 37


def run(conn):
    if not column_exists(conn, "real_estate", "address"):
        conn.execute("ALTER TABLE real_estate ADD COLUMN address TEXT")
    if not column_exists(conn, "real_estate", "purchase_price"):
        conn.execute("ALTER TABLE real_estate ADD COLUMN purchase_price REAL")
    if not column_exists(conn, "real_estate", "purchase_date"):
        conn.execute("ALTER TABLE real_estate ADD COLUMN purchase_date TEXT")
