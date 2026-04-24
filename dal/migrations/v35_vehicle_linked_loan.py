"""
v35: Add ``linked_loan_id`` to ``vehicle_assets``.

Parallels ``real_estate.linked_loan_id`` (added back in v03) so both
manual-asset tables carry the link to their backing loan in the same
direction. Lets the P15-T08 manual-asset details panel join scraped
auto-loan fields (VIN, GAP, payoff) without string-matching VINs at
query time.

No backfill: the seeder writes the link for the single seeded RAV4,
and real connectors will fill it as VIN-aware scraping lands (parked
in the ROADMAP "Scraper Adjustments Backlog"). The column is
nullable; pre-existing rows keep NULL.

Idempotent against partial re-runs via ``column_exists``.
"""

from dal.migrations import column_exists

VERSION = 35


def run(conn):
    if not column_exists(conn, "vehicle_assets", "linked_loan_id"):
        conn.execute(
            "ALTER TABLE vehicle_assets "
            "ADD COLUMN linked_loan_id TEXT REFERENCES accounts(id)"
        )
