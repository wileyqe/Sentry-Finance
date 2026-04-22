"""
dal/income_sources.py — CRUD for the Phase 14 Phase B income-source registry.

Single source of truth for per-owner income source metadata consumed by
``dal.flow_classification`` and the Sankey assembly in ``dal.reports``.
Table shape lives in migration v32; see that file for column semantics.

All functions are thin SQL — no business logic here beyond ``active``
defaults, ``updated_at`` stamping, and JSON validation deferred to the
matcher module.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Optional

log = logging.getLogger("sentry.dal.income_sources")


_VALID_TAX_TREATMENTS: frozenset[str] = frozenset({
    "w2_withheld",
    "pension_withheld",
    "nontaxable",
    "contractor_no_withholding",
    "interest_dividend",
    "employer_match_bypass",
    "rental_income",
    "other",
})


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "display_label": row["display_label"],
        "owner_id": row["owner_id"],
        "tax_treatment": row["tax_treatment"],
        "default_category": row["default_category"],
        "match_rule_json": row["match_rule_json"],
        "estimated_tax_reserve_pct": float(row["estimated_tax_reserve_pct"] or 0.0),
        "bypass_cash_routing": bool(row["bypass_cash_routing"]),
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _validate_match_rule(match_rule: Any) -> str:
    """Return a serialized JSON string for ``match_rule``.

    Accepts a dict (preferred) or already-serialized string. Rejects blobs
    that have neither ``counterparty_substring`` nor ``category`` — such
    a rule would match every transaction and is almost certainly a bug.
    """
    if isinstance(match_rule, str):
        try:
            parsed = json.loads(match_rule)
        except (TypeError, ValueError) as e:
            raise ValueError(f"match_rule_json is not valid JSON: {e}")
    elif isinstance(match_rule, dict):
        parsed = match_rule
    else:
        raise ValueError(
            "match_rule must be a dict or JSON string, "
            f"got {type(match_rule).__name__}"
        )

    if not isinstance(parsed, dict):
        raise ValueError("match_rule must decode to a JSON object (dict)")

    if not parsed.get("counterparty_substring") and not parsed.get("category"):
        raise ValueError(
            "match_rule must have at least one of 'counterparty_substring' "
            "or 'category' — an empty rule matches every transaction."
        )

    return json.dumps(parsed, sort_keys=True)


# ── Reads ────────────────────────────────────────────────────────────────────


def get_by_id(conn: sqlite3.Connection, source_id: str) -> Optional[dict]:
    """Return one row or None."""
    row = conn.execute(
        "SELECT * FROM income_sources WHERE id = ?",
        (source_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_for_owner(
    conn: sqlite3.Connection,
    owner_id: str,
    *,
    include_inactive: bool = False,
) -> list[dict]:
    """Return income sources registered for ``owner_id``.

    ``include_inactive=False`` (default) omits ``active=0`` rows.
    """
    if include_inactive:
        sql = (
            "SELECT * FROM income_sources WHERE owner_id = ? "
            "ORDER BY tax_treatment, display_label"
        )
        params: tuple = (owner_id,)
    else:
        sql = (
            "SELECT * FROM income_sources WHERE owner_id = ? AND active = 1 "
            "ORDER BY tax_treatment, display_label"
        )
        params = (owner_id,)

    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def list_all(conn: sqlite3.Connection, *, include_inactive: bool = False) -> list[dict]:
    """Return every income source across all owners — used by the classifier
    when classifying household-level aggregates."""
    if include_inactive:
        sql = "SELECT * FROM income_sources ORDER BY owner_id, display_label"
    else:
        sql = (
            "SELECT * FROM income_sources WHERE active = 1 "
            "ORDER BY owner_id, display_label"
        )
    return [_row_to_dict(r) for r in conn.execute(sql).fetchall()]


# ── Writes ───────────────────────────────────────────────────────────────────


def create(
    conn: sqlite3.Connection,
    *,
    display_label: str,
    owner_id: str,
    tax_treatment: str,
    match_rule: Any,
    default_category: Optional[str] = None,
    estimated_tax_reserve_pct: float = 0.0,
    bypass_cash_routing: bool = False,
    source_id: Optional[str] = None,
    active: bool = True,
) -> str:
    """Insert a new income source row. Returns the row's id."""
    if tax_treatment not in _VALID_TAX_TREATMENTS:
        raise ValueError(
            f"tax_treatment {tax_treatment!r} not in allowed set "
            f"{sorted(_VALID_TAX_TREATMENTS)}"
        )

    rule_json = _validate_match_rule(match_rule)
    row_id = source_id or str(uuid.uuid4())
    now = datetime.now().replace(microsecond=0).isoformat(sep=" ")

    conn.execute(
        """
        INSERT INTO income_sources (
            id, display_label, owner_id, tax_treatment, default_category,
            match_rule_json, estimated_tax_reserve_pct, bypass_cash_routing,
            active, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row_id,
            display_label,
            owner_id,
            tax_treatment,
            default_category,
            rule_json,
            float(estimated_tax_reserve_pct),
            1 if bypass_cash_routing else 0,
            1 if active else 0,
            now,
            now,
        ),
    )
    return row_id


def update(
    conn: sqlite3.Connection,
    source_id: str,
    **fields: Any,
) -> bool:
    """Partial update. Returns True when a row was modified.

    Accepted fields: display_label, tax_treatment, default_category,
    match_rule (validated), estimated_tax_reserve_pct, bypass_cash_routing,
    active.
    """
    if not fields:
        return False

    sets: list[str] = []
    params: list[Any] = []

    if "display_label" in fields:
        sets.append("display_label = ?")
        params.append(fields["display_label"])

    if "tax_treatment" in fields:
        tt = fields["tax_treatment"]
        if tt not in _VALID_TAX_TREATMENTS:
            raise ValueError(
                f"tax_treatment {tt!r} not in allowed set "
                f"{sorted(_VALID_TAX_TREATMENTS)}"
            )
        sets.append("tax_treatment = ?")
        params.append(tt)

    if "default_category" in fields:
        sets.append("default_category = ?")
        params.append(fields["default_category"])

    if "match_rule" in fields:
        sets.append("match_rule_json = ?")
        params.append(_validate_match_rule(fields["match_rule"]))

    if "estimated_tax_reserve_pct" in fields:
        sets.append("estimated_tax_reserve_pct = ?")
        params.append(float(fields["estimated_tax_reserve_pct"]))

    if "bypass_cash_routing" in fields:
        sets.append("bypass_cash_routing = ?")
        params.append(1 if fields["bypass_cash_routing"] else 0)

    if "active" in fields:
        sets.append("active = ?")
        params.append(1 if fields["active"] else 0)

    if not sets:
        return False

    sets.append("updated_at = ?")
    params.append(datetime.now().replace(microsecond=0).isoformat(sep=" "))

    sql = f"UPDATE income_sources SET {', '.join(sets)} WHERE id = ?"
    params.append(source_id)

    cur = conn.execute(sql, params)
    return cur.rowcount > 0


def deactivate(conn: sqlite3.Connection, source_id: str) -> bool:
    """Mark a source as inactive (shortcut for update(..., active=False))."""
    return update(conn, source_id, active=False)
