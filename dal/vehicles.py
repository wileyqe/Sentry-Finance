"""Persistence and logic for tracking vehicle assets and their equity over time."""

import sqlite3
from datetime import date, datetime
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
    linked_loan_id: Optional[str] = None,
    vin: Optional[str] = None,
    gap_insurance: Optional[bool] = None,
):
    """Add or update a vehicle asset.  Caller commits.

    ``owner_id`` / ``linked_loan_id`` / ``vin`` / ``gap_insurance``
    preserve existing values on UPDATE when ``None`` so re-runs don't
    wipe previously-set fields. ``vin`` and ``gap_insurance`` were added
    in v36 — they are the canonical home for vehicle identity that
    used to live in the loan_details KV.
    """
    gap_int = None if gap_insurance is None else (1 if gap_insurance else 0)
    conn.execute(
        """INSERT INTO vehicle_assets
           (id, make, model, year, purchase_date, purchase_price,
            owner_id, linked_loan_id, vin, gap_insurance)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               make=excluded.make,
               model=excluded.model,
               year=excluded.year,
               purchase_date=excluded.purchase_date,
               purchase_price=excluded.purchase_price,
               owner_id=COALESCE(excluded.owner_id, vehicle_assets.owner_id),
               linked_loan_id=COALESCE(
                   excluded.linked_loan_id, vehicle_assets.linked_loan_id
               ),
               vin=COALESCE(excluded.vin, vehicle_assets.vin),
               gap_insurance=COALESCE(
                   excluded.gap_insurance, vehicle_assets.gap_insurance
               )""",
        (
            vehicle_id,
            make,
            model,
            year,
            purchase_date,
            purchase_price,
            owner_id,
            linked_loan_id,
            vin,
            gap_int,
        ),
    )


def link_vehicle_to_loan_by_vin(
    conn: sqlite3.Connection,
    vin: str,
    loan_account_id: str,
) -> Optional[str]:
    """Auto-link a vehicle row to a loan account by VIN match.

    Connector-side helper for the NFCU auto-loan scrape. When the loan
    detail page surfaces a VIN, the connector calls this to set
    ``vehicle_assets.linked_loan_id`` on the matching vehicle row, so
    the Manual Asset Details panel can resolve the loan side without
    the seed-time hand-wired link.

    Returns the vehicle id if a match was found and linked (or already
    linked to the same loan); ``None`` if no vehicle has that VIN. The
    UNIQUE index ``idx_vehicle_assets_vin`` (v36) guarantees at most one
    match. Caller commits.

    The function is idempotent: re-running with the same arguments is a
    no-op write. If a vehicle's existing ``linked_loan_id`` differs, it
    is overwritten (the live VIN scrape is the source of truth once it
    lands; the seed link is the fallback we're aiming to retire).
    """
    if not vin:
        return None
    row = conn.execute(
        "SELECT id, linked_loan_id FROM vehicle_assets WHERE vin = ?",
        (vin,),
    ).fetchone()
    if row is None:
        return None
    if row["linked_loan_id"] != loan_account_id:
        conn.execute(
            "UPDATE vehicle_assets SET linked_loan_id = ? WHERE id = ?",
            (loan_account_id, row["id"]),
        )
    return row["id"]


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


_DEPRECIATION_CURVE_LABEL = "15% off the lot + 10%/yr compounded, floor 15%"


def suggested_value(
    conn: sqlite3.Connection,
    vehicle_id: str,
    as_of: Optional[str] = None,
) -> Optional[dict]:
    """Heuristic depreciation-based suggested value for a vehicle.

    Curve: an immediate 15% drop "off the lot", then 10%/year compounded
    on the remaining 85%, with a 15%-of-purchase-price floor so the
    asset never models to zero. This is a deliberately simple stand-in
    for KBB/Edmunds (no free public APIs as of 2026-04). Used to
    pre-fill the manual valuation modal so the user has a sensible
    starting number to accept or override.

    Returns ``None`` if the vehicle is unknown or has no purchase_price.
    Otherwise returns::

        {
            "suggested_value": float,        # dollars
            "basis": {
                "purchase_price": float,
                "purchase_date": str | None,
                "age_years": float,
                "depreciation_curve": str,
            },
        }
    """
    row = conn.execute(
        "SELECT purchase_date, purchase_price FROM vehicle_assets WHERE id = ?",
        (vehicle_id,),
    ).fetchone()
    if not row or row["purchase_price"] is None:
        return None

    purchase_price = float(row["purchase_price"])
    purchase_date = row["purchase_date"]

    # No purchase_date → can't compute age; suggest purchase price as a starting point.
    if not purchase_date:
        return {
            "suggested_value": round(purchase_price, 2),
            "basis": {
                "purchase_price": purchase_price,
                "purchase_date": None,
                "age_years": 0.0,
                "depreciation_curve": "no purchase_date — defaulted to purchase price",
            },
        }

    as_of_str = as_of or date.today().isoformat()
    try:
        pd = datetime.fromisoformat(purchase_date).date()
        aod = datetime.fromisoformat(as_of_str).date()
    except ValueError:
        return None

    age_years = max(0.0, (aod - pd).days / 365.25)
    raw_value = purchase_price * 0.85 * (0.90 ** age_years)
    floor = purchase_price * 0.15
    value = max(raw_value, floor)

    return {
        "suggested_value": round(value, 2),
        "basis": {
            "purchase_price": purchase_price,
            "purchase_date": purchase_date,
            "age_years": round(age_years, 2),
            "depreciation_curve": _DEPRECIATION_CURVE_LABEL,
        },
    }


def get_valuation_history(
    conn: sqlite3.Connection,
    vehicle_id: str,
    months: Optional[int] = None,
) -> list[dict]:
    """Return ascending valuation rows for a single vehicle.

    Mirrors ``dal.real_estate.get_valuation_history`` and ``dal.apy_history
    .get_apy_history`` so the T08 sparkline/trend helper consumes all three
    series the same way.
    """
    if months is not None:
        rows = conn.execute(
            """SELECT valuation_date, estimated_value, source
               FROM vehicle_valuations
               WHERE vehicle_id = ?
                 AND valuation_date >= date('now', ?)
               ORDER BY valuation_date ASC""",
            (vehicle_id, f"-{months} months"),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT valuation_date, estimated_value, source
               FROM vehicle_valuations
               WHERE vehicle_id = ?
               ORDER BY valuation_date ASC""",
            (vehicle_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_vehicle_details(
    conn: sqlite3.Connection,
    vehicle_id: str,
) -> Optional[dict]:
    """Return an end-to-end detail bundle for a single vehicle.

    Returns ``None`` if the vehicle is unknown. Otherwise::

        {
            "vehicle_id": str,
            "make": str, "model": str, "year": int,
            "purchase_date": str | None,
            "purchase_price": float | None,
            "linked_loan_id": str | None,
            "latest_valuation": {"estimated_value", "source", "as_of"} | null,
            "valuation_history": [{"estimated_value", "as_of"}, ...],
            "suggested_value": float | None,
            "depreciation_curve": str | None,
        }

    ``valuation_history`` is the recorded ``vehicle_valuations`` series
    (12-month asc). ``suggested_value`` is today's depreciation heuristic.
    Linked-loan fields are composed by the router so this DAL stays
    single-purpose, the same split used for real estate.
    """
    row = conn.execute(
        """SELECT id, make, model, year, purchase_date, purchase_price,
                  linked_loan_id, vin, gap_insurance
           FROM vehicle_assets
           WHERE id = ?""",
        (vehicle_id,),
    ).fetchone()
    if row is None:
        return None

    latest = get_latest_valuation(conn, vehicle_id)
    latest_out: Optional[dict] = None
    if latest is not None:
        latest_out = {
            "estimated_value": latest["estimated_value"],
            "source": latest["source"],
            "as_of": latest["valuation_date"],
        }

    history = get_valuation_history(conn, vehicle_id, months=12)
    suggested = suggested_value(conn, vehicle_id)

    gap_raw = row["gap_insurance"]
    gap_out: Optional[bool] = None if gap_raw is None else bool(gap_raw)

    return {
        "vehicle_id": row["id"],
        "make": row["make"],
        "model": row["model"],
        "year": row["year"],
        "purchase_date": row["purchase_date"],
        "purchase_price": row["purchase_price"],
        "linked_loan_id": row["linked_loan_id"],
        "vin": row["vin"],
        "gap_insurance": gap_out,
        "latest_valuation": latest_out,
        "valuation_history": [
            {"estimated_value": h["estimated_value"], "as_of": h["valuation_date"]}
            for h in history
        ],
        "suggested_value": suggested["suggested_value"] if suggested else None,
        "depreciation_curve": (
            suggested["basis"]["depreciation_curve"] if suggested else None
        ),
    }


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
