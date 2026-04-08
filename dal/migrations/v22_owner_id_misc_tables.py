"""V22 — Add owner_id to payroll_snapshots, vehicle_assets, and real_estate.

These three tables predate the multi-user model and never had per-owner
attribution. Until now they were implicitly household-level / single-owner,
which leaked synthetic data into every per-owner dashboard view.

This migration:

1. Adds a nullable ``owner_id TEXT REFERENCES owners(id)`` column to each
   of the three tables.
2. Backfills existing rows to the configured ``primary_owner`` from
   ``owner_config.yaml`` so legacy installs continue to attribute their
   real data to the right person.
3. Adds owner-aware indexes for the new filter paths.

After this migration, the read-side DAL functions in ``dal/payroll.py``,
``dal/vehicles.py``, ``dal/derived.py``, ``dal/reports.py``, and
``dal/scenarios.py`` are updated to thread an optional ``owner_id`` filter
through.
"""

VERSION = 22


def _add_column_if_missing(conn, table: str, column_def: str, col_name: str):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def run(conn):
    # ── 1. Add owner_id columns ──────────────────────────────────────────
    _add_column_if_missing(
        conn,
        "payroll_snapshots",
        "owner_id TEXT REFERENCES owners(id)",
        "owner_id",
    )
    _add_column_if_missing(
        conn,
        "vehicle_assets",
        "owner_id TEXT REFERENCES owners(id)",
        "owner_id",
    )
    _add_column_if_missing(
        conn,
        "real_estate",
        "owner_id TEXT REFERENCES owners(id)",
        "owner_id",
    )

    # ── 2. Backfill: legacy single-user data is the stand-in for the
    #    configured primary owner. Lazy-import to avoid pulling the
    #    full dal package during migration bootstrap.
    from dal.owners import get_primary_owner

    primary = (get_primary_owner() or "quintin").lower()

    conn.execute(
        "UPDATE payroll_snapshots SET owner_id = ? WHERE owner_id IS NULL",
        (primary,),
    )
    conn.execute(
        "UPDATE vehicle_assets SET owner_id = ? WHERE owner_id IS NULL",
        (primary,),
    )
    conn.execute(
        "UPDATE real_estate SET owner_id = ? WHERE owner_id IS NULL",
        (primary,),
    )

    # ── 3. Indexes for owner-scoped reads ────────────────────────────────
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_payroll_owner "
        "ON payroll_snapshots(owner_id, pay_period DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vehicle_assets_owner "
        "ON vehicle_assets(owner_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_real_estate_owner "
        "ON real_estate(owner_id, as_of DESC)"
    )
