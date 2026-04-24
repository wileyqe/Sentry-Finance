"""
v37: Add ``address``, ``purchase_price``, ``purchase_date`` to ``real_estate``.

These describe the property, not the linked loan, so they get
first-class columns rather than living in the ``loan_details`` KV.
``real_estate`` is append-only and the columns are nullable; readers
take the latest non-null value per column across the property's history.

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
