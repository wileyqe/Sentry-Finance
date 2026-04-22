"""
tests/test_income_sources_registry.py — Phase 14 Phase B registry CRUD.

Covers ``dal.income_sources``:

  1. ``get_by_id`` + ``list_for_owner`` basics.
  2. ``active=0`` rows are excluded from ``list_for_owner`` by default.
  3. ``match_rule_json`` requires at least one of ``counterparty_substring``
     or ``category``.
  4. ``tax_treatment`` is validated against the canonical set.
  5. ``update`` partial writes and ``deactivate`` shortcut.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.owners import create_owner
from dal import income_sources as income_sources_dal


@pytest.fixture
def tiny_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(Path(path))
        with get_db(Path(path)) as conn:
            create_owner(conn, "alpha", "Alpha")
            create_owner(conn, "beta", "Beta")
            conn.commit()
        yield Path(path)
    finally:
        os.unlink(path)


def test_get_by_id_and_list_for_owner(tiny_db):
    with get_db(tiny_db) as conn:
        sid = income_sources_dal.create(
            conn,
            display_label="Alpha W-2",
            owner_id="alpha",
            tax_treatment="w2_withheld",
            match_rule={"counterparty_substring": "alpha corp"},
        )
        conn.commit()

        row = income_sources_dal.get_by_id(conn, sid)
        assert row is not None
        assert row["display_label"] == "Alpha W-2"
        assert row["owner_id"] == "alpha"
        assert row["tax_treatment"] == "w2_withheld"
        assert row["active"] is True
        assert row["bypass_cash_routing"] is False

        listed = income_sources_dal.list_for_owner(conn, "alpha")
        assert len(listed) == 1
        assert listed[0]["id"] == sid


def test_list_for_owner_excludes_inactive_by_default(tiny_db):
    with get_db(tiny_db) as conn:
        active_id = income_sources_dal.create(
            conn,
            display_label="Alpha active",
            owner_id="alpha",
            tax_treatment="w2_withheld",
            match_rule={"counterparty_substring": "a"},
        )
        inactive_id = income_sources_dal.create(
            conn,
            display_label="Alpha deactivated",
            owner_id="alpha",
            tax_treatment="w2_withheld",
            match_rule={"counterparty_substring": "b"},
            active=False,
        )
        conn.commit()

        default = income_sources_dal.list_for_owner(conn, "alpha")
        default_ids = [r["id"] for r in default]
        assert active_id in default_ids
        assert inactive_id not in default_ids

        with_inactive = income_sources_dal.list_for_owner(
            conn, "alpha", include_inactive=True
        )
        assert len(with_inactive) == 2


def test_match_rule_requires_counterparty_or_category(tiny_db):
    """An empty match rule would match every transaction — rejected."""
    with get_db(tiny_db) as conn:
        with pytest.raises(ValueError, match="at least one of"):
            income_sources_dal.create(
                conn,
                display_label="bad rule",
                owner_id="alpha",
                tax_treatment="other",
                match_rule={},  # empty — invalid
            )

        with pytest.raises(ValueError, match="at least one of"):
            income_sources_dal.create(
                conn,
                display_label="owner-only rule",
                owner_id="alpha",
                tax_treatment="other",
                # Only owner_id — no counterparty or category.
                match_rule={"owner_id": "alpha"},
            )


def test_match_rule_accepts_string_or_dict(tiny_db):
    with get_db(tiny_db) as conn:
        sid1 = income_sources_dal.create(
            conn,
            display_label="dict rule",
            owner_id="alpha",
            tax_treatment="w2_withheld",
            match_rule={"category": "Paychecks/Salary"},
        )
        sid2 = income_sources_dal.create(
            conn,
            display_label="str rule",
            owner_id="alpha",
            tax_treatment="w2_withheld",
            match_rule='{"counterparty_substring": "alpha"}',
        )
        conn.commit()

        for sid in (sid1, sid2):
            row = income_sources_dal.get_by_id(conn, sid)
            parsed = json.loads(row["match_rule_json"])
            assert isinstance(parsed, dict)


def test_tax_treatment_validated(tiny_db):
    with get_db(tiny_db) as conn:
        with pytest.raises(ValueError, match="tax_treatment"):
            income_sources_dal.create(
                conn,
                display_label="bad treatment",
                owner_id="alpha",
                tax_treatment="made_up_value",
                match_rule={"counterparty_substring": "x"},
            )


def test_update_partial_and_deactivate(tiny_db):
    with get_db(tiny_db) as conn:
        sid = income_sources_dal.create(
            conn,
            display_label="original",
            owner_id="alpha",
            tax_treatment="w2_withheld",
            match_rule={"counterparty_substring": "a"},
        )
        conn.commit()

        changed = income_sources_dal.update(
            conn, sid,
            display_label="renamed",
            bypass_cash_routing=True,
        )
        assert changed is True

        row = income_sources_dal.get_by_id(conn, sid)
        assert row["display_label"] == "renamed"
        assert row["bypass_cash_routing"] is True
        assert row["owner_id"] == "alpha"  # untouched

        assert income_sources_dal.deactivate(conn, sid) is True
        row2 = income_sources_dal.get_by_id(conn, sid)
        assert row2["active"] is False


def test_bypass_routing_flag_persists_with_optional_amount(tiny_db):
    """Phase B convention: bypass sources may carry ``monthly_amount_cents``
    inside match_rule_json. The registry stores it opaquely — no schema
    constraint — but downstream consumers (reports.py) rely on it."""
    with get_db(tiny_db) as conn:
        sid = income_sources_dal.create(
            conn,
            display_label="employer match",
            owner_id="alpha",
            tax_treatment="employer_match_bypass",
            match_rule={
                "counterparty_substring": "employer match",
                "monthly_amount_cents": 26000,
            },
            bypass_cash_routing=True,
        )
        conn.commit()

        row = income_sources_dal.get_by_id(conn, sid)
        parsed = json.loads(row["match_rule_json"])
        assert parsed["monthly_amount_cents"] == 26000
        assert row["bypass_cash_routing"] is True
