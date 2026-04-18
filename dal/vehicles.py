"""Persistence and logic for tracking vehicle assets and their equity over time."""

import sqlite3
from typing import Optional


def list_vehicles(
    conn: sqlite3.Connection,
    owner_id: Optional[str] = None,
) -> list[dict]:
    """Return all configured vehicles, optionally scoped to an owner."""
    sql = """SELECT id, make, model, year, purchase_date, purchase_price
             FROM vehicle_assets"""
    params: list = []
    if owner_id is not None:
        sql += " WHERE LOWER(owner_id) = LOWER(?)"
        params.append(owner_id)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_latest_valuation(conn: sqlite3.Connection, vehicle_id: str) -> Optional[dict]:
    """Return the most recent valuation for a vehicle.

    Owner scoping is applied by callers via :func:`list_vehicles` — once a
    vehicle id is in scope, its valuations belong to that owner.
    """
    row = conn.execute(
        """SELECT valuation_date, estimated_value, source, source_url
           FROM vehicle_valuations
           WHERE vehicle_id = ?
           ORDER BY valuation_date DESC LIMIT 1""",
        (vehicle_id,),
    ).fetchone()
    return dict(row) if row else None


def add_vehicle(
    conn: sqlite3.Connection,
    vehicle_id: str,
    make: str,
    model: str,
    year: int,
    purchase_date: Optional[str] = None,
    purchase_price: Optional[float] = None,
    owner_id: Optional[str] = None,
):
    """Add or update a vehicle asset.  Caller commits.

    ``owner_id`` preserves existing value on UPDATE when ``None`` so
    re-runs don't wipe a previously-set owner.
    """
    conn.execute(
        """INSERT INTO vehicle_assets
           (id, make, model, year, purchase_date, purchase_price, owner_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               make=excluded.make,
               model=excluded.model,
               year=excluded.year,
               purchase_date=excluded.purchase_date,
               purchase_price=excluded.purchase_price,
               owner_id=COALESCE(excluded.owner_id, vehicle_assets.owner_id)""",
        (vehicle_id, make, model, year, purchase_date, purchase_price, owner_id),
    )


def add_valuation(
    conn: sqlite3.Connection,
    vehicle_id: str,
    valuation_date: str,
    estimated_value: float,
    source: str = "Manual",
    source_url: Optional[str] = None,
):
    """Record a new valuation entry for a vehicle.

    Invariant: ``estimated_value > 0``. Violations raise ``ValueError``.
    Caller commits — the internal commit was removed in Phase 17 to
    align with ``dal.transactions.upsert_transactions``.
    """
    if not isinstance(estimated_value, (int, float)) or estimated_value <= 0:
        raise ValueError(
            f"vehicle_valuations.estimated_value must be > 0, got "
            f"{estimated_value!r}. vehicle_id={vehicle_id!r} "
            f"valuation_date={valuation_date!r} source={source!r}"
        )

    # Prevent duplicate valuations on the same date for the same source
    existing = conn.execute(
        """SELECT id FROM vehicle_valuations
           WHERE vehicle_id = ? AND valuation_date = ? AND source = ?""",
        (vehicle_id, valuation_date, source),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE vehicle_valuations
               SET estimated_value = ?, source_url = ?, as_of = datetime('now')
               WHERE id = ?""",
            (estimated_value, source_url, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO vehicle_valuations
               (vehicle_id, valuation_date, estimated_value, source, source_url)
               VALUES (?, ?, ?, ?, ?)""",
            (vehicle_id, valuation_date, estimated_value, source, source_url),
        )


def get_vehicle_equity_history(
    conn: sqlite3.Connection,
    months: int = 12,
    owner_id: Optional[str] = None,
) -> list[dict]:
    """Calculate the total vehicle equity per month.

    Like get_property_equity_history, we return a dense time series by filling
    forward the most recent valuation for each vehicle. When ``owner_id`` is
    set, only vehicles owned by that owner contribute to the totals.
    """
    vehicles = list_vehicles(conn, owner_id=owner_id)
    if not vehicles:
        return []

    # Restrict the valuations CTE to the in-scope vehicle ids so the
    # SUM rolls up only the owner's vehicles.
    vehicle_ids = [v["id"] for v in vehicles]
    placeholders = ",".join("?" * len(vehicle_ids))

    rows = conn.execute(
        f"""
        WITH MonthlyVals AS (
            SELECT
                vehicle_id,
                strftime('%Y-%m', valuation_date) as month,
                estimated_value,
                ROW_NUMBER() OVER(PARTITION BY vehicle_id, strftime('%Y-%m', valuation_date) ORDER BY valuation_date DESC) as rn
            FROM vehicle_valuations
            WHERE valuation_date >= date('now', ?)
              AND vehicle_id IN ({placeholders})
        )
        SELECT month, sum(estimated_value) as total_value
        FROM MonthlyVals
        WHERE rn = 1
        GROUP BY month
        ORDER BY month ASC
        """,
        (f"-{months} months", *vehicle_ids),
    ).fetchall()

    return [{"month": r["month"], "total_value": r["total_value"]} for r in rows]
