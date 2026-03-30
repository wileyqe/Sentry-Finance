"""Persistence and logic for tracking vehicle assets and their equity over time."""

import sqlite3
from typing import Optional


def list_vehicles(conn: sqlite3.Connection) -> list[dict]:
    """Return all configured vehicles."""
    rows = conn.execute(
        """SELECT id, make, model, year, purchase_date, purchase_price
           FROM vehicle_assets"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest_valuation(conn: sqlite3.Connection, vehicle_id: str) -> Optional[dict]:
    """Return the most recent valuation for a vehicle."""
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
):
    """Add or update a vehicle asset."""
    conn.execute(
        """INSERT INTO vehicle_assets 
           (id, make, model, year, purchase_date, purchase_price)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               make=excluded.make,
               model=excluded.model,
               year=excluded.year,
               purchase_date=excluded.purchase_date,
               purchase_price=excluded.purchase_price""",
        (vehicle_id, make, model, year, purchase_date, purchase_price),
    )
    conn.commit()


def add_valuation(
    conn: sqlite3.Connection,
    vehicle_id: str,
    valuation_date: str,
    estimated_value: float,
    source: str = "Manual",
    source_url: Optional[str] = None,
):
    """Record a new valuation entry for a vehicle."""
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
    conn.commit()


def get_vehicle_equity_history(conn: sqlite3.Connection, months: int = 12) -> list[dict]:
    """Calculate the total vehicle equity per month.
    
    Like get_property_equity_history, we return a dense time series by filling
    forward the most recent valuation for each vehicle.
    """
    vehicles = list_vehicles(conn)
    if not vehicles:
        return []

    # Get max date from our reporting horizon
    # For now, just return all recorded raw valuations for simplicity, aggregated by month.
    # To do this optimally, we'd use a calendar CTE or simply query all points and resample in Python.
    
    rows = conn.execute(
        """
        WITH MonthlyVals AS (
            SELECT 
                vehicle_id,
                strftime('%Y-%m', valuation_date) as month,
                estimated_value,
                ROW_NUMBER() OVER(PARTITION BY vehicle_id, strftime('%Y-%m', valuation_date) ORDER BY valuation_date DESC) as rn
            FROM vehicle_valuations
            WHERE valuation_date >= date('now', ?)
        )
        SELECT month, sum(estimated_value) as total_value
        FROM MonthlyVals
        WHERE rn = 1
        GROUP BY month
        ORDER BY month ASC
        """,
        (f"-{months} months",),
    ).fetchall()

    return [{"month": r["month"], "total_value": r["total_value"]} for r in rows]
