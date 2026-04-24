"""
v36: Add ``vin`` and ``gap_insurance`` to ``vehicle_assets``.

PR1 of the Account/Asset Details single-source-of-truth fix
(``docs/prompts/Phase-15/P15-T10_details-panel-single-source.md``).

Today VIN and the GAP-insurance flag live ONLY in the ``loan_details``
KV table, even though they describe the vehicle, not the loan. That
forces the seeder to hardcode them from a connector-shaped string
constant — which is how the Apr 2026 Kia VIN PII leak happened. Giving
``vehicle_assets`` first-class columns lets the composer (and a future
VIN-aware connector) write VIN where it belongs; the loan KV stops
being the home for collateral identity.

Both columns are nullable on existing rows — a v37+ backfill / connector
work fills them as VIN-aware scraping lands. ``vin`` is unique-when-present
to catch double-seeding bugs.

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
