"""
tests/test_details_panel_invariants.py — PR1 invariant suite for the
single-source-of-truth Details panel composer.

Locks in:

* The ``record_loan_details`` denylist refuses collateral-identity
  field writes for loans with a linked vehicle or property.
* The denylist still permits the same field names on loans with no
  linked asset (BNPL ``purchase_price`` keeps working).
* ``get_loan_panel_bundle`` and ``get_vehicle_panel_bundle`` /
  ``get_real_estate_panel_bundle`` resolve to the SAME ``collateral``
  slot regardless of which side initiates the lookup.
* The composed ``collateral.description`` always matches the linked
  asset's identity (no "loan says Kia, asset says Toyota" drift can
  resurface).

These invariants are the structural part of the
docs/prompts/Phase-15/P15-T10_details-panel-single-source.md
remediation; their failure is the regression we are guarding against.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.account_details_composer import (  # noqa: E402
    get_loan_panel_bundle,
    get_real_estate_panel_bundle,
    get_vehicle_panel_bundle,
)
from dal.balances import record_loan_details  # noqa: E402
from dal.connection import get_db as real_get_db  # noqa: E402
from dal.database import init_db  # noqa: E402
from dal.real_estate import record_real_estate_valuations  # noqa: E402
from dal.vehicles import add_valuation, add_vehicle  # noqa: E402


# ── Fixture ──────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    """Tempfile DB pre-populated with a vehicle+loan and a property+mortgage."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    p = Path(path)
    init_db(p)
    with real_get_db(p) as conn:
        conn.execute(
            "INSERT INTO owners (id, display_name) VALUES ('quintin','Quintin')"
        )
        conn.execute(
            "INSERT INTO institutions (id, display_name) VALUES ('summit','Summit')"
        )
        # Three accounts: secured auto loan, secured mortgage, unsecured BNPL
        conn.executemany(
            "INSERT INTO accounts (id, institution_id, name, last4, type, "
            "owner_id, is_active) VALUES (?,?,?,?,?,?,?)",
            [
                ("summit_auto", "summit", "Auto Loan", "AUTO", "loan", "quintin", 1),
                ("summit_mtg", "summit", "Mortgage", "MTG", "mortgage", "quintin", 1),
                ("payflex_bnpl", "summit", "BNPL", "BNPL", "loan", "quintin", 1),
            ],
        )
        # Linked vehicle (Honda Civic — synthetic)
        add_vehicle(
            conn,
            vehicle_id="civic_2020",
            make="Honda",
            model="Civic",
            year=2020,
            purchase_date="2021-06-01",
            purchase_price=30000.0,
            owner_id="quintin",
            linked_loan_id="summit_auto",
            vin="1HGFAKEDUMMY00001",
            gap_insurance=True,
        )
        add_valuation(
            conn,
            vehicle_id="civic_2020",
            valuation_date="2026-01-01",
            estimated_value=22000.0,
            source="KBB",
        )
        # Linked property
        record_real_estate_valuations(
            conn,
            [
                {
                    "name": "Primary Residence",
                    "estimated_value": 300000.0,
                    "linked_loan_id": "summit_mtg",
                    "source": "estimate",
                    "as_of": "2025-01-01",
                    "owner_id": "quintin",
                    "address": "123 Demo Lane, Exampleton",
                    "purchase_price": 300000.0,
                    "purchase_date": "2020-09-01",
                },
                {
                    # Later quarterly valuation that omits the identity
                    # columns — verifies "latest non-null per column" merge.
                    "name": "Primary Residence",
                    "estimated_value": 305000.0,
                    "linked_loan_id": "summit_mtg",
                    "source": "estimate",
                    "as_of": "2025-04-01",
                    "owner_id": "quintin",
                },
            ],
        )
        conn.commit()
    yield p
    try:
        os.unlink(path)
    except OSError:
        pass


# ── Denylist invariants ──────────────────────────────────────────────────


class TestDenylist:
    """``record_loan_details`` rejects collateral fields on linked-asset loans."""

    @pytest.mark.parametrize(
        "field_name,field_value",
        [
            ("vin", "1HGFAKEDUMMY00099"),
            ("collateral_description", "1999 Pontiac Aztek"),
            ("purchase_price", "99999.99"),
            ("gap_flag", "No"),
            ("date_opened", "01/01/1999"),
        ],
    )
    def test_rejects_collateral_field_on_linked_vehicle_loan(
        self, db, field_name, field_value
    ):
        with real_get_db(db) as conn:
            with pytest.raises(ValueError, match=field_name):
                record_loan_details(
                    conn,
                    account_id="summit_auto",
                    details={field_name: field_value},
                )

    @pytest.mark.parametrize(
        "field_name,field_value",
        [
            ("address", "999 Real Street"),
            ("purchase_price", "999999.99"),
            ("date_opened", "01/01/1999"),
        ],
    )
    def test_rejects_collateral_field_on_linked_property_loan(
        self, db, field_name, field_value
    ):
        with real_get_db(db) as conn:
            # Only fields in the denylist raise; address is NOT in the
            # denylist (lives on real_estate.address) so the only ones
            # that should raise here are purchase_price and date_opened.
            if field_name in {"purchase_price", "date_opened"}:
                with pytest.raises(ValueError, match=field_name):
                    record_loan_details(
                        conn,
                        account_id="summit_mtg",
                        details={field_name: field_value},
                    )
            else:
                # Sanity: non-denylist fields still write fine.
                record_loan_details(
                    conn,
                    account_id="summit_mtg",
                    details={field_name: field_value},
                )

    def test_permits_purchase_price_on_unsecured_loan(self, db):
        """BNPL has no linked asset; ``purchase_price`` keeps working there."""
        with real_get_db(db) as conn:
            record_loan_details(
                conn,
                account_id="payflex_bnpl",
                details={"purchase_price": "1100", "interest_rate": "0.0"},
            )
            conn.commit()
            row = conn.execute(
                "SELECT field_value FROM loan_details "
                "WHERE account_id = 'payflex_bnpl' AND field_name = 'purchase_price'"
            ).fetchone()
            assert row["field_value"] == "1100"

    def test_permits_non_collateral_fields_on_secured_loan(self, db):
        """``interest_rate`` / ``minimum_payment`` etc. still write fine."""
        with real_get_db(db) as conn:
            record_loan_details(
                conn,
                account_id="summit_auto",
                details={
                    "interest_rate": "3.9",
                    "minimum_payment": "600.0",
                    "term_months": "60",
                    "origination_date": "2021-06-01",
                },
            )
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM loan_details "
                "WHERE account_id = 'summit_auto'"
            ).fetchone()
            assert count["n"] == 4


# ── Composer convergence invariants ──────────────────────────────────────


class TestComposerConvergence:
    """Loan-side and asset-side panels resolve the same ``collateral`` slot."""

    def test_loan_and_vehicle_panels_share_collateral(self, db):
        with real_get_db(db) as conn:
            loan_bundle = get_loan_panel_bundle(conn, "summit_auto")
            vehicle_bundle = get_vehicle_panel_bundle(conn, "civic_2020")

        assert loan_bundle["collateral"] == vehicle_bundle["collateral"]
        coll = loan_bundle["collateral"]
        assert coll is not None
        assert coll["kind"] == "vehicle"
        assert coll["vin"] == "1HGFAKEDUMMY00001"
        assert coll["description"] == "2020 HONDA CIVIC"
        assert coll["gap_insurance"] is True

    def test_loan_and_real_estate_panels_share_collateral(self, db):
        with real_get_db(db) as conn:
            loan_bundle = get_loan_panel_bundle(conn, "summit_mtg")
            # Look up the latest property_id for "Primary Residence"
            row = conn.execute(
                "SELECT id FROM real_estate WHERE name = 'Primary Residence' "
                "ORDER BY as_of DESC LIMIT 1"
            ).fetchone()
            property_id = row["id"]
            re_bundle = get_real_estate_panel_bundle(conn, property_id)

        assert loan_bundle["collateral"] == re_bundle["collateral"]
        coll = loan_bundle["collateral"]
        assert coll is not None
        assert coll["kind"] == "real_estate"
        assert coll["address"] == "123 Demo Lane, Exampleton"
        assert coll["description"] == "123 Demo Lane, Exampleton"
        assert coll["purchase_price"] == 300000.0
        assert coll["purchase_date"] == "2020-09-01"

    def test_real_estate_identity_carries_across_appended_rows(self, db):
        """A later quarterly valuation row with NULL identity columns
        must not shadow the identity set on an earlier row."""
        with real_get_db(db) as conn:
            row = conn.execute(
                "SELECT id FROM real_estate WHERE name = 'Primary Residence' "
                "ORDER BY as_of DESC LIMIT 1"
            ).fetchone()
            re_bundle = get_real_estate_panel_bundle(conn, row["id"])

        # The latest row was inserted with NULL address but the composer
        # MUST surface the address from the earlier row.
        assert re_bundle["address"] == "123 Demo Lane, Exampleton"
        assert re_bundle["purchase_price"] == 300000.0

    def test_unsecured_loan_has_null_collateral(self, db):
        with real_get_db(db) as conn:
            loan_bundle = get_loan_panel_bundle(conn, "payflex_bnpl")
        assert loan_bundle["collateral"] is None

    def test_vehicle_panel_returns_none_for_unknown_id(self, db):
        with real_get_db(db) as conn:
            assert get_vehicle_panel_bundle(conn, "nonexistent") is None

    def test_real_estate_panel_returns_none_for_unknown_id(self, db):
        with real_get_db(db) as conn:
            assert get_real_estate_panel_bundle(conn, 999999) is None
