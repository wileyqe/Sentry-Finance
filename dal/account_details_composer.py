"""
dal/account_details_composer.py — Single composer for the Details panels.

Loan-side (`/api/accounts/{id}/details`) and asset-side
(`/api/vehicles/{id}/details`, `/api/real_estate/{id}/details`) panels
all return a bundle with the same ``collateral`` slot resolved from the
linked asset row. The schema-level denylist in
``record_loan_details`` blocks writes the other way; this module is the
read-side join point so the two surfaces cannot disagree.
"""

from __future__ import annotations

import sqlite3
from typing import Literal, Optional, TypedDict


# ── Bundle shapes (typed dicts; document the wire contract) ─────────────────


class _DetailField(TypedDict):
    value: str
    as_of: str


class _ApyLatest(TypedDict, total=False):
    apy_rate: float
    as_of: str
    source: str


class VehicleCollateral(TypedDict, total=False):
    """Vehicle-as-collateral identity composed from ``vehicle_assets``."""
    kind: Literal["vehicle"]
    vehicle_id: str
    make: str
    model: str
    year: int
    vin: Optional[str]
    purchase_date: Optional[str]
    purchase_price: Optional[float]
    gap_insurance: Optional[bool]
    description: str  # f"{year} {make} {model}".upper()


class RealEstateCollateral(TypedDict, total=False):
    """Real-estate-as-collateral identity composed from ``real_estate``."""
    kind: Literal["real_estate"]
    property_id: int
    name: str
    address: Optional[str]
    purchase_date: Optional[str]
    purchase_price: Optional[float]
    description: str  # address if known, else property name


def _empty_loan_bundle() -> dict:
    """Bundle returned for an asset whose linked loan does not exist."""
    return {
        "account_id": None,
        "details": {},
        "apy_latest": None,
        "apy_history": [],
        "collateral": None,
    }


# ── Public composers ────────────────────────────────────────────────────────


def get_loan_panel_bundle(
    conn: sqlite3.Connection,
    account_id: str,
    *,
    collateral: Optional[dict] = None,
) -> dict:
    """Bundle for ``/api/accounts/{id}/details`` (loan-side panel).

    Returns ``{
        "account_id": str,
        "details": {field_name: {value, as_of}, ...},
        "apy_latest": ApyLatest | None,
        "apy_history": [{apy_rate, as_of}, ...],
        "collateral": VehicleCollateral | RealEstateCollateral | None,
    }``.

    ``collateral`` may be passed by an asset-side composer that already
    fetched the asset row, avoiding a second query against
    ``vehicle_assets`` / ``real_estate``. Pass ``None`` to resolve via
    the linked-asset lookup.
    """
    from dal.apy_history import get_apy_history

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

    apy_rows = get_apy_history(conn, account_id, months=12)
    apy_history = [
        {"apy_rate": r["apy_rate"], "as_of": r["as_of"]} for r in apy_rows
    ]
    apy_latest = (
        {
            "apy_rate": apy_rows[-1]["apy_rate"],
            "as_of": apy_rows[-1]["as_of"],
            "source": apy_rows[-1]["source"],
        }
        if apy_rows
        else None
    )

    if collateral is None:
        collateral = _resolve_collateral_for_loan(conn, account_id)

    return {
        "account_id": account_id,
        "details": seen,
        "apy_latest": apy_latest,
        "apy_history": apy_history,
        "collateral": collateral,
    }


def get_investment_panel_bundle(
    conn: sqlite3.Connection, account_id: str
) -> dict:
    """Bundle for ``/api/accounts/{id}/details`` when the account is an
    ``investment`` or ``retirement`` row.

    P15-T09 captures per-account investment metadata in
    ``investment_details`` (account-level rows with
    ``fund_ticker IS NULL``; per-fund rows keyed by ticker). This
    composer joins both into a single bundle that is a *structural
    superset* of ``get_loan_panel_bundle``'s shape — the shared keys
    (``account_id``, ``details``, ``apy_latest``, ``apy_history``,
    ``collateral``) are always present so the frontend
    ``DetailsResponse`` interface stays compatible. The investment-only
    additions are ``kind`` and ``funds``::

        {
            "account_id": str,
            "kind": "investment",
            "details": {field_name: {value, as_of}, ...},  # account-level
            "funds": [
                {"ticker": str, "name": str | None,
                 "fields": {field_name: {value, as_of}, ...}},
                ...                                          # alphabetical
            ],
            "apy_latest": None,        # always None for investment
            "apy_history": [],         # always empty for investment
            "collateral": None,        # always None for investment
        }
    """
    from dal.investment_details import get_latest_investment_details

    snap = get_latest_investment_details(conn, account_id)

    # Account-level details map directly into ``details``. Per-fund rows
    # become a sorted list so the frontend renders deterministically.
    details = dict(snap["account_level"])
    funds_list: list[dict] = []
    for ticker in sorted(snap["funds"].keys()):
        fields = dict(snap["funds"][ticker])
        # ``fund_name`` is metadata, not a row to render. Lift it onto
        # the entry so the FE can show a human label without filtering.
        name_entry = fields.pop("fund_name", None)
        funds_list.append(
            {
                "ticker": ticker,
                "name": name_entry["value"] if name_entry else None,
                "fields": fields,
            }
        )

    # Merge loan_details + apy_history when present. Brokerage accounts
    # like Fidelity carry both: loan_details holds the cash-side
    # ``available_balance`` / ``dividends_ytd`` rows that the AccountsPage
    # "(Cash)" virtual entry depends on; apy_history holds the SPAXX
    # sweep yield. Investment-specific rows still take precedence on
    # name collisions so a future ``ytd_return`` written via both paths
    # would resolve to the investment_details version.
    loan_bundle = get_loan_panel_bundle(conn, account_id)
    for k, v in loan_bundle["details"].items():
        if k not in details:
            details[k] = v

    return {
        "account_id": account_id,
        "kind": "investment",
        "details": details,
        "funds": funds_list,
        "apy_latest": loan_bundle["apy_latest"],
        "apy_history": loan_bundle["apy_history"],
        "collateral": None,
    }


def get_vehicle_panel_bundle(
    conn: sqlite3.Connection, vehicle_id: str
) -> Optional[dict]:
    """Bundle for ``/api/vehicles/{id}/details`` (asset-side panel).

    Returns ``None`` when the vehicle id is unknown. Otherwise a
    superset of ``get_loan_panel_bundle``'s shape with the vehicle's
    own valuation curve and depreciation suggestion attached.
    """
    from dal.vehicles import get_vehicle_details

    vbundle = get_vehicle_details(conn, vehicle_id)
    if vbundle is None:
        return None

    collateral = _vehicle_collateral_from_bundle(vbundle)
    loan_id = vbundle.get("linked_loan_id")
    loan_bundle = (
        get_loan_panel_bundle(conn, loan_id, collateral=collateral)
        if loan_id
        else _empty_loan_bundle() | {"collateral": collateral}
    )

    return {
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
        "details": loan_bundle["details"],
        "apy_latest": loan_bundle["apy_latest"],
        "apy_history": loan_bundle["apy_history"],
        "collateral": loan_bundle["collateral"],
    }


def get_real_estate_panel_bundle(
    conn: sqlite3.Connection, property_id: int
) -> Optional[dict]:
    """Bundle for ``/api/real_estate/{id}/details`` (asset-side panel).

    Returns ``None`` when the property id does not exist.
    """
    from dal.real_estate import get_real_estate_details

    rbundle = get_real_estate_details(conn, property_id)
    if rbundle is None:
        return None

    collateral = _real_estate_collateral_from_bundle(rbundle)
    loan_id = rbundle.get("linked_loan_id")
    loan_bundle = (
        get_loan_panel_bundle(conn, loan_id, collateral=collateral)
        if loan_id
        else _empty_loan_bundle() | {"collateral": collateral}
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


def _vehicle_collateral_from_bundle(v: dict) -> dict:
    return {
        "kind": "vehicle",
        "vehicle_id": v["vehicle_id"],
        "make": v["make"],
        "model": v["model"],
        "year": v["year"],
        "vin": v["vin"],
        "purchase_date": v["purchase_date"],
        "purchase_price": v["purchase_price"],
        "gap_insurance": v["gap_insurance"],
        "description": f"{v['year']} {v['make']} {v['model']}".upper(),
    }


def _real_estate_collateral_from_bundle(p: dict) -> dict:
    return {
        "kind": "real_estate",
        "property_id": p["property_id"],
        "name": p["name"],
        "address": p["address"],
        "purchase_date": p["purchase_date"],
        "purchase_price": p["purchase_price"],
        "description": p["address"] or p["name"],
    }


def _resolve_collateral_for_loan(
    conn: sqlite3.Connection, account_id: str
) -> Optional[dict]:
    """Resolve collateral identity from the linked asset.

    A loan can be backed by at most one asset in the current schema.
    Returns ``None`` for unsecured loans (BNPL, personal lines).
    """
    from dal.real_estate import resolve_latest_identity
    from dal.vehicles import get_vehicle_details

    v = conn.execute(
        "SELECT id FROM vehicle_assets WHERE linked_loan_id = ? LIMIT 1",
        (account_id,),
    ).fetchone()
    if v is not None:
        vbundle = get_vehicle_details(conn, v["id"])
        if vbundle is not None:
            return _vehicle_collateral_from_bundle(vbundle)

    p = conn.execute(
        """SELECT id, name FROM real_estate
           WHERE linked_loan_id = ?
           ORDER BY as_of DESC, id DESC
           LIMIT 1""",
        (account_id,),
    ).fetchone()
    if p is not None:
        identity = resolve_latest_identity(conn, p["name"])
        return {
            "kind": "real_estate",
            "property_id": p["id"],
            "name": p["name"],
            "address": identity["address"],
            "purchase_price": identity["purchase_price"],
            "purchase_date": identity["purchase_date"],
            "description": identity["address"] or p["name"],
        }

    return None
