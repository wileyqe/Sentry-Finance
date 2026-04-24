"""
dal/account_details_composer.py — Single composer for the Details panels.

PR1 of the Account/Asset Details single-source-of-truth fix
(``docs/prompts/Phase-15/P15-T10_details-panel-single-source.md``).

Today the loan-side (`/api/accounts/{id}/details`) and asset-side
(`/api/vehicles/{id}/details`, `/api/real_estate/{id}/details`) panels
each compose their own bundle from `loan_details` KV + asset row +
APY history. That diffuse pattern is how the Apr 2026 collateral drift
shipped: the loan panel reported "2022 KIA NIRO" while the linked
vehicle row carried a Toyota RAV4. Each surface had its own truth.

This module is the read-side join point. Each composer returns a
typed bundle that:

* Resolves COLLATERAL identity (vin, collateral_description, address,
  purchase_price, purchase_date, gap_insurance) from the LINKED ASSET
  row, never from the loan KV. Schema-level denylist in
  ``record_loan_details`` stops writes the other way too.
* Composes loan terms (rate, term, origination, payoff, min payment)
  from ``loan_details`` KV and APY from ``apy_history``.
* Returns the same shape regardless of which side (loan or asset)
  initiated the lookup, so the two panel components can converge on
  one consumer in PR3.

PR2 will rewrite the seeder to write only canonical sources; PR3 will
swap the router endpoints to call these composers directly.
"""

from __future__ import annotations

import sqlite3
from typing import Optional, TypedDict


# ── Bundle shapes (typed dicts; document the wire contract) ─────────────────


class _DetailField(TypedDict):
    """A loan-detail KV entry as it appears in panel responses."""
    value: str
    as_of: str


class _ApyLatest(TypedDict, total=False):
    apy_rate: float
    as_of: str
    source: str


class _LatestValuation(TypedDict, total=False):
    estimated_value: float
    source: Optional[str]
    as_of: str


class VehicleCollateral(TypedDict, total=False):
    """Vehicle-as-collateral identity composed from ``vehicle_assets``."""
    vehicle_id: str
    make: str
    model: str
    year: int
    vin: Optional[str]
    purchase_date: Optional[str]
    purchase_price: Optional[float]
    gap_insurance: Optional[bool]
    description: str  # f"{year} {make} {model}".upper() — for loan-panel rendering


class RealEstateCollateral(TypedDict, total=False):
    """Real-estate-as-collateral identity composed from ``real_estate``."""
    property_id: int
    name: str
    address: Optional[str]
    purchase_date: Optional[str]
    purchase_price: Optional[float]


# ── Public composers ────────────────────────────────────────────────────────


def get_loan_panel_bundle(
    conn: sqlite3.Connection, account_id: str
) -> dict:
    """Bundle for ``/api/accounts/{id}/details`` (loan-side panel).

    Returns ``{
        "account_id": str,
        "details": {field_name: {value, as_of}, ...},
        "apy_latest": ApyLatest | None,
        "apy_history": [{apy_rate, as_of}, ...],
        "collateral": VehicleCollateral | RealEstateCollateral | None,
    }``.

    The ``collateral`` slot is the structural fix: any vehicle / property
    identity the loan panel needs to render (VIN, address, purchase
    price, GAP) comes through here, NOT through the loan_details KV.
    Frontend can stop reading those keys from ``details`` once PR3 lands.
    """
    from dal.apy_history import get_apy_history, get_latest_apy  # late import

    rows = conn.execute(
        """SELECT field_name, field_value, as_of
           FROM loan_details
           WHERE account_id = ?
           ORDER BY as_of DESC""",
        (account_id,),
    ).fetchall()
    seen: dict[str, _DetailField] = {}
    for r in rows:
        if r["field_name"] not in seen:
            seen[r["field_name"]] = {
                "value": r["field_value"],
                "as_of": r["as_of"],
            }

    apy_latest = get_latest_apy(conn, account_id)
    apy_rows = get_apy_history(conn, account_id, months=12)
    apy_history = [
        {"apy_rate": r["apy_rate"], "as_of": r["as_of"]} for r in apy_rows
    ]

    collateral = _resolve_collateral_for_loan(conn, account_id)

    return {
        "account_id": account_id,
        "details": seen,
        "apy_latest": apy_latest,
        "apy_history": apy_history,
        "collateral": collateral,
    }


def get_vehicle_panel_bundle(
    conn: sqlite3.Connection, vehicle_id: str
) -> Optional[dict]:
    """Bundle for ``/api/vehicles/{id}/details`` (asset-side panel).

    Returns ``None`` if no vehicle with ``vehicle_id`` exists. Otherwise
    a superset of ``get_loan_panel_bundle``'s shape with the vehicle's
    own valuation curve and depreciation suggestion bolted on.

    Both sides of the join (loan ↔ vehicle) end up referring to the
    SAME ``collateral`` slot resolved from the same ``vehicle_assets``
    row, so the two panels cannot disagree.
    """
    from dal.vehicles import get_vehicle_details

    vbundle = get_vehicle_details(conn, vehicle_id)
    if vbundle is None:
        return None

    loan_id = vbundle.get("linked_loan_id")
    loan_bundle = (
        get_loan_panel_bundle(conn, loan_id)
        if loan_id
        else {"account_id": None, "details": {}, "apy_latest": None,
              "apy_history": [], "collateral": None}
    )

    return {
        # asset-side fields (the hero card's data)
        "vehicle_id": vbundle["vehicle_id"],
        "make": vbundle["make"],
        "model": vbundle["model"],
        "year": vbundle["year"],
        "vin": vbundle["vin"],
        "purchase_date": vbundle["purchase_date"],
        "purchase_price": vbundle["purchase_price"],
        "gap_insurance": vbundle["gap_insurance"],
        "linked_loan_id": vbundle["linked_loan_id"],
        "latest_valuation": vbundle["latest_valuation"],
        "valuation_history": vbundle["valuation_history"],
        "suggested_value": vbundle["suggested_value"],
        "depreciation_curve": vbundle["depreciation_curve"],
        # loan-side fields (composed via the same loan-panel bundle)
        "details": loan_bundle["details"],
        "apy_latest": loan_bundle["apy_latest"],
        "apy_history": loan_bundle["apy_history"],
        "collateral": loan_bundle["collateral"],
    }


def get_real_estate_panel_bundle(
    conn: sqlite3.Connection, property_id: int
) -> Optional[dict]:
    """Bundle for ``/api/real_estate/{id}/details`` (asset-side panel).

    Mirrors ``get_vehicle_panel_bundle``: same join shape, real-estate
    flavor of the asset hero. Returns ``None`` when the property id
    does not exist.
    """
    from dal.real_estate import get_real_estate_details

    rbundle = get_real_estate_details(conn, property_id)
    if rbundle is None:
        return None

    loan_id = rbundle.get("linked_loan_id")
    loan_bundle = (
        get_loan_panel_bundle(conn, loan_id)
        if loan_id
        else {"account_id": None, "details": {}, "apy_latest": None,
              "apy_history": [], "collateral": None}
    )

    return {
        "property_id": rbundle["property_id"],
        "name": rbundle["name"],
        "address": rbundle["address"],
        "purchase_price": rbundle["purchase_price"],
        "purchase_date": rbundle["purchase_date"],
        "linked_loan_id": rbundle["linked_loan_id"],
        "latest_valuation": rbundle["latest_valuation"],
        "valuation_history": rbundle["valuation_history"],
        "details": loan_bundle["details"],
        "apy_latest": loan_bundle["apy_latest"],
        "apy_history": loan_bundle["apy_history"],
        "collateral": loan_bundle["collateral"],
    }


# ── Internal helpers ────────────────────────────────────────────────────────


def _resolve_collateral_for_loan(
    conn: sqlite3.Connection, account_id: str
) -> Optional[dict]:
    """Look for a linked vehicle, then a linked property, else None.

    A loan can be backed by at most one asset in the current schema
    (no UI for multi-asset collateral). Returns the canonical identity
    bundle the loan panel renders for the "Collateral" / "VIN" /
    "Address" rows. ``None`` for unsecured loans (BNPL, personal lines).
    """
    v = conn.execute(
        """SELECT id, make, model, year, vin, purchase_date,
                  purchase_price, gap_insurance
           FROM vehicle_assets
           WHERE linked_loan_id = ?
           LIMIT 1""",
        (account_id,),
    ).fetchone()
    if v is not None:
        gap_raw = v["gap_insurance"]
        return {
            "kind": "vehicle",
            "vehicle_id": v["id"],
            "make": v["make"],
            "model": v["model"],
            "year": v["year"],
            "vin": v["vin"],
            "purchase_date": v["purchase_date"],
            "purchase_price": v["purchase_price"],
            "gap_insurance": None if gap_raw is None else bool(gap_raw),
            "description": f"{v['year']} {v['make']} {v['model']}".upper(),
        }

    # Fall through to real-estate lookup. We pick the LATEST row by
    # as_of for this loan_id so the appended quarterly valuations
    # don't shadow whichever row carried the identity columns.
    p = conn.execute(
        """SELECT id, name, address, purchase_date, purchase_price
           FROM real_estate
           WHERE linked_loan_id = ?
           ORDER BY as_of DESC, id DESC
           LIMIT 1""",
        (account_id,),
    ).fetchone()
    if p is not None:
        # Identity columns may be on a sibling row (real_estate is
        # append-only). Pull latest non-null per column across all
        # rows for the same property name.
        identity = conn.execute(
            """SELECT
                   (SELECT address FROM real_estate
                    WHERE name = ? AND address IS NOT NULL
                    ORDER BY as_of DESC, id DESC LIMIT 1) AS address,
                   (SELECT purchase_price FROM real_estate
                    WHERE name = ? AND purchase_price IS NOT NULL
                    ORDER BY as_of DESC, id DESC LIMIT 1) AS purchase_price,
                   (SELECT purchase_date FROM real_estate
                    WHERE name = ? AND purchase_date IS NOT NULL
                    ORDER BY as_of DESC, id DESC LIMIT 1) AS purchase_date
            """,
            (p["name"], p["name"], p["name"]),
        ).fetchone()
        return {
            "kind": "real_estate",
            "property_id": p["id"],
            "name": p["name"],
            "address": identity["address"] if identity else None,
            "purchase_price": (
                identity["purchase_price"] if identity else None
            ),
            "purchase_date": (
                identity["purchase_date"] if identity else None
            ),
            "description": (identity["address"] if identity and identity["address"] else p["name"]),
        }

    return None
