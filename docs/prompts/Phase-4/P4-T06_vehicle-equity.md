# P4-T06: Vehicle Equity Tracking

## Context

You are working on Sentry Finance, a local-first personal finance app.
The system tracks net worth across financial accounts, real estate, and
investment portfolios. Vehicles are a significant asset class that is
currently **not tracked**:

- The user has an auto loan (already captured in NFCU loan details),
  but the **asset value** of the vehicle is not recorded
- Vehicle equity = estimated market value − loan balance
- Without vehicle equity, net worth is understated by the vehicle's value
  and overstated by the loan (loan is already a liability, but asset is missing)

The existing `real_estate` table tracks property valuations with a
`linked_loan_id` field that connects the asset to its financing. A similar
pattern works for vehicles: create an asset record, link it to the auto loan,
and periodically update the estimated value.

## Starting State

- `real_estate` table: `(id, name, estimated_value, linked_loan_id, source, as_of, created_at)`
- `dal/reports.py` → `get_net_worth_history()` includes `real_estate` valuations
- Auto loan exists in NFCU connector (account type "loan", tracked in
  `balance_snapshots` and `loan_details`)
- No vehicle-specific tracking exists in the system

## Task

### 1. New Migration: `v18_vehicle_assets.py`

Create a dedicated vehicles table (keeping `real_estate` purely for property):

```python
"""Schema V18 — Vehicle assets table for equity tracking."""

VERSION = 18

_DDL = """
CREATE TABLE IF NOT EXISTS vehicle_assets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,           -- "2022 Toyota Camry SE"
    year            INTEGER NOT NULL,
    make            TEXT NOT NULL,           -- "Toyota"
    model           TEXT NOT NULL,           -- "Camry"
    trim            TEXT,                    -- "SE"
    mileage         INTEGER,                -- Current odometer reading
    vin             TEXT,                    -- Optional VIN for precise lookups
    estimated_value REAL NOT NULL,
    linked_loan_id  TEXT REFERENCES accounts(id),
    source          TEXT DEFAULT 'manual',   -- 'manual', 'kbb', 'nada', 'carvana'
    source_url      TEXT,                    -- URL of the valuation source
    as_of           TEXT NOT NULL,
    is_active       INTEGER DEFAULT 1,       -- 0 = sold/disposed
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vehicle_active
    ON vehicle_assets(is_active);
"""

def run(conn):
    conn.executescript(_DDL)
```

### 2. New DAL Module: `dal/vehicles.py`

```python
"""Vehicle asset tracking for net worth calculation."""

import sqlite3
from datetime import datetime


def upsert_vehicle(
    conn: sqlite3.Connection,
    name: str,
    year: int,
    make: str,
    model: str,
    estimated_value: float,
    linked_loan_id: str | None = None,
    trim: str | None = None,
    mileage: int | None = None,
    vin: str | None = None,
    source: str = "manual",
    source_url: str | None = None,
) -> int:
    """Create or update a vehicle asset entry.

    If a vehicle with the same (year, make, model) already exists,
    inserts a new valuation row (historical tracking).
    Returns the row ID.
    """
    now = datetime.now().strftime("%Y-%m-%d")
    cur = conn.execute(
        """INSERT INTO vehicle_assets
           (name, year, make, model, trim, mileage, vin,
            estimated_value, linked_loan_id, source, source_url, as_of)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, year, make, model, trim, mileage, vin,
         estimated_value, linked_loan_id, source, source_url, now),
    )
    conn.commit()
    return cur.lastrowid


def get_active_vehicles(conn: sqlite3.Connection) -> list[dict]:
    """Return all active vehicles with their latest valuation.

    For each vehicle, also computes equity if linked to a loan.
    """
    rows = conn.execute("""
        SELECT v.*, bs.balance as loan_balance
        FROM vehicle_assets v
        LEFT JOIN (
            SELECT account_id, balance
            FROM balance_snapshots
            WHERE id IN (
                SELECT MAX(id) FROM balance_snapshots
                GROUP BY account_id
            )
        ) bs ON bs.account_id = v.linked_loan_id
        WHERE v.is_active = 1
          AND v.id IN (
              SELECT MAX(id) FROM vehicle_assets
              WHERE is_active = 1
              GROUP BY year, make, model
          )
        ORDER BY v.as_of DESC
    """).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        loan_bal = abs(d.pop("loan_balance", 0) or 0)
        d["equity"] = round(d["estimated_value"] - loan_bal, 2)
        d["loan_balance"] = round(loan_bal, 2)
        result.append(d)
    return result


def get_vehicle_valuation_history(
    conn: sqlite3.Connection,
    year: int,
    make: str,
    model: str,
) -> list[dict]:
    """Return valuation history for a specific vehicle."""
    rows = conn.execute(
        """SELECT estimated_value, source, as_of, mileage
           FROM vehicle_assets
           WHERE year = ? AND make = ? AND model = ?
           ORDER BY as_of ASC""",
        (year, make, model),
    ).fetchall()
    return [dict(r) for r in rows]


def deactivate_vehicle(conn: sqlite3.Connection, vehicle_id: int) -> None:
    """Mark a vehicle as sold/disposed."""
    conn.execute(
        "UPDATE vehicle_assets SET is_active = 0 WHERE id = ?",
        (vehicle_id,),
    )
    conn.commit()
```

### 3. Integrate with Net Worth

Update `dal/reports.py` → `get_net_worth_history()` to include vehicle
valuations alongside real estate:

```python
# In the net worth calculation, add vehicle equity:
vehicle_rows = conn.execute("""
    SELECT v.estimated_value, v.as_of
    FROM vehicle_assets v
    WHERE v.is_active = 1
""").fetchall()
```

Apply the same time-aware lookup pattern used for real estate (P1-T05):
for each history month, pick the most recent vehicle valuation known at
that time.

### 4. API Endpoints

Add to `backend/routers/reports.py` (or create a new `vehicles.py` router):

```python
@router.get("/api/vehicles")
def vehicles_list():
    """Return active vehicles with equity calculation."""
    with get_db() as conn:
        from dal.vehicles import get_active_vehicles
        vehicles = get_active_vehicles(conn)
    return {"vehicles": vehicles, "count": len(vehicles)}


@router.post("/api/vehicles")
def vehicles_create(body: VehicleCreate):
    """Add or update a vehicle asset."""
    with get_db() as conn:
        from dal.vehicles import upsert_vehicle
        row_id = upsert_vehicle(conn, **body.model_dump())
    return {"status": "created", "id": row_id}


@router.delete("/api/vehicles/{vehicle_id}")
def vehicles_deactivate(vehicle_id: int):
    """Mark a vehicle as sold/disposed."""
    with get_db() as conn:
        from dal.vehicles import deactivate_vehicle
        deactivate_vehicle(conn, vehicle_id)
    return {"status": "deactivated"}
```

### 5. (Optional/Future) Automated Valuation

This prompt covers **manual** vehicle entry. A future enhancement could
add automated lookups via:
- KBB API (paid, requires partnership)
- Carvana/CarMax instant offer pages (scrape-based)
- NADA API (paid)
- CarGurus market value (scrape-based)

For now, document the manual entry flow and leave hooks for future
automation (the `source` and `source_url` fields support this).

## Files to Create

1. `dal/migrations/v18_vehicle_assets.py` — new table
2. `dal/vehicles.py` — CRUD + equity calculation

## Files to Modify

1. `dal/reports.py` — add vehicle valuations to net worth history
2. `backend/routers/reports.py` — add vehicle API endpoints (or new router)

## Files NOT to Modify

- `real_estate` table — keep for properties only
- Connector files — vehicle data is user-entered, not scraped
- Frontend files

## Constraints

- Vehicle equity = `estimated_value - ABS(loan_balance)` (loan balances are
  stored as negative in `balance_snapshots`)
- If no loan is linked (`linked_loan_id` is NULL), equity = estimated_value
  (vehicle owned outright)
- Multiple valuations for the same vehicle create a history — the latest
  `as_of` date is the "current" value
- `is_active = 0` means the vehicle has been sold — exclude from all
  active queries and net worth
- VIN is optional — KBB lookups work with year/make/model/trim/mileage
- The recompute pipeline (`dal/derived.py`) should pick up vehicle equity
  in net worth if `get_net_worth_history()` is updated
- Round all dollar values to 2 decimal places

## Done Checklist

- [ ] V18 migration creates `vehicle_assets` table with proper schema
- [ ] `dal/vehicles.py` has `upsert_vehicle()`, `get_active_vehicles()`, `get_vehicle_valuation_history()`, `deactivate_vehicle()`
- [ ] Equity calculation: `estimated_value - ABS(loan_balance)`
- [ ] `get_net_worth_history()` includes vehicle valuations
- [ ] API endpoints: GET/POST /api/vehicles, DELETE /api/vehicles/{id}
- [ ] Valuation history supports multiple entries per vehicle
- [ ] `is_active` flag works for sold vehicles

## Verification

After completion, Claude will:
1. Read V18 migration and verify table schema
2. Read `dal/vehicles.py` and verify equity calculation
3. Verify `get_net_worth_history()` integration
4. Run import check: `python -c "from dal.vehicles import upsert_vehicle, get_active_vehicles"`
5. Verify API endpoints compile without import errors
