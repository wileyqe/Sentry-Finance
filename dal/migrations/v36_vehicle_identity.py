"""
v36: Add ``vin`` and ``gap_insurance`` to ``vehicle_assets``.

VIN and the GAP-insurance flag describe the vehicle, not the loan, so
they get first-class columns rather than living in the ``loan_details``
KV. ``vin`` is unique-when-present to catch double-seeding bugs; both
columns are nullable since existing rows pre-date VIN-aware scraping.

Idempotent against partial re-runs via ``column_exists``.
"""

from dal.migrations import column_exists

VERSION = 36


def run(conn):
    if not column_exists(conn, "vehicle_assets", "vin"):
        conn.execute("ALTER TABLE vehicle_assets ADD COLUMN vin TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicle_assets_vin "
            "ON vehicle_assets(vin) WHERE vin IS NOT NULL"
        )
    if not column_exists(conn, "vehicle_assets", "gap_insurance"):
        conn.execute(
            "ALTER TABLE vehicle_assets ADD COLUMN gap_insurance INTEGER"
        )
