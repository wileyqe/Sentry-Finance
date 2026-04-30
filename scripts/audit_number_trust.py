"""Number-trust audit for the canonical synthetic seed.

The audit intentionally does not call production DAL report helpers for oracle
values.  It reads raw tables, applies independent formulas, calls the public
API, and writes JSON/Markdown diffs under docs/audits/number-trust/reports.
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MANIFEST_PATH = ROOT / "data" / "trusted_seed_manifest.json"
REGISTRY_PATH = ROOT / "docs" / "audits" / "number-trust" / "ui-number-registry.yaml"
ORACLE_VOCABULARY_PATH = ROOT / "docs" / "audits" / "number-trust" / "oracle-vocabulary.json"
SECOND_LANGUAGE_ORACLE_PATH = ROOT / "scripts" / "number_trust_oracle.mjs"
REPORT_DIR = ROOT / "docs" / "audits" / "number-trust" / "reports"
REGISTRY_AUDIT_STAGES = {"api_oracle", "registered_pending"}

import yaml  # noqa: E402

from dal.category_classifications import (  # noqa: E402
    ALL_EXCL_FROM_SPEND,
    EXCLUDED_FROM_SPEND,
    INCOME_CATEGORIES,
    INCOME_EXCL_FROM_INC,
)
from backend.runtime_context import build_runtime_context  # noqa: E402

CASH_ACCOUNT_TYPES = {"checking", "savings", "money_market"}
CASHOUT_SPEND_EXCLUDE = set(INCOME_CATEGORIES) | {
    "Transfers",
    "Transfer",
    "Refunds/Adjustments",
    "Mortgages",
    "Mortgage",
}
DEBT_CASH_CATEGORIES = {
    "Loan Payments",
    "Loan Payment",
    "Auto Loan",
    "Student Loan",
    "Credit Card Payments",
    "BNPL Payments",
}
DEBT_ACCUMULATED_EXCLUDE = {
    "Refunds/Adjustments",
    "Transfers",
    "Transfer",
    "Credit Card Payments",
    "Loan Payments",
    "Mortgages",
    "Auto Loan",
    "Student Loan",
}
LIABILITY_TYPES = {"credit_card", "credit", "loan", "mortgage", "bnpl"}
ILLIQUID_TRANSFER_TYPES = {"investment", "brokerage", "retirement", "hsa"}
RECURRING_FREQ_DIVISOR = {
    "monthly": 1,
    "weekly": 1 / 4.33,
    "biweekly": 1 / 2.17,
    "quarterly": 3,
    "semi-annual": 6,
    "annual": 12,
    "yearly": 12,
}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _manifest(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = 'trusted_seed_manifest'"
    ).fetchone()
    if row:
        return json.loads(row["value"])
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    raise RuntimeError("trusted seed manifest not found")


def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        raise RuntimeError(f"number-trust registry not found: {REGISTRY_PATH}")
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}


def _registry_view_states(registry: dict[str, Any]) -> list[dict[str, Any]]:
    states = registry.get("view_states") or []
    if not isinstance(states, list):
        return []
    normalized = []
    for state in states:
        if not isinstance(state, dict):
            continue
        normalized.append({
            "id": state.get("id"),
            "view": state.get("view"),
            "owner_id": state.get("owner_id"),
            "expected_state": state.get("expected_state"),
        })
    return normalized


def _registry_value_contexts(
    registry: dict[str, Any],
    *,
    audit_stage: str | None = None,
) -> list[dict[str, Any]]:
    view_states = {state["id"]: state for state in _registry_view_states(registry)}
    contexts: list[dict[str, Any]] = []
    for surface in registry.get("surfaces") or []:
        for value in surface.get("values") or []:
            value_stage = value.get("audit_stage")
            if audit_stage and value_stage != audit_stage:
                continue
            for state_id in value.get("view_states") or []:
                state = view_states.get(state_id)
                if state:
                    contexts.append({
                        "surface_id": surface.get("id"),
                        "page": surface.get("page"),
                        "route": surface.get("route"),
                        "value_id": value.get("id"),
                        "check_id": value.get("check_id"),
                        "label": value.get("label"),
                        "api": value.get("api"),
                        "oracle": value.get("oracle"),
                        "audit_stage": value_stage,
                        "formatter": value.get("formatter"),
                        "selector": value.get("selector"),
                        "view_state": state,
                    })
    return contexts


def _registry_diffs(registry: dict[str, Any]) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    states = _registry_view_states(registry)
    seen: set[str] = set()
    for state in states:
        state_id = state.get("id")
        if not state_id:
            diffs.append({
                "id": "registry.view_states.id",
                "expected": "non-empty id",
                "actual": state,
                "classification": "lineage/docs drift",
            })
            continue
        if state_id in seen:
            diffs.append({
                "id": f"registry.view_states.{state_id}.unique",
                "expected": "unique id",
                "actual": "duplicate",
                "classification": "lineage/docs drift",
            })
        seen.add(state_id)
        if state.get("view") not in {"household", "owner"}:
            diffs.append({
                "id": f"registry.view_states.{state_id}.view",
                "expected": "household or owner",
                "actual": state.get("view"),
                "classification": "lineage/docs drift",
            })
        if state.get("view") == "household" and state.get("owner_id") is not None:
            diffs.append({
                "id": f"registry.view_states.{state_id}.owner_id",
                "expected": None,
                "actual": state.get("owner_id"),
                "classification": "lineage/docs drift",
            })
        if state.get("view") == "owner" and not state.get("owner_id"):
            diffs.append({
                "id": f"registry.view_states.{state_id}.owner_id",
                "expected": "owner id",
                "actual": state.get("owner_id"),
                "classification": "lineage/docs drift",
            })

    valid_state_ids = {state["id"] for state in states if state.get("id")}
    seen_values: set[str] = set()
    for surface in registry.get("surfaces") or []:
        surface_id = surface.get("id") or "<missing>"
        if not surface.get("page"):
            diffs.append({
                "id": f"registry.{surface_id}.page",
                "expected": "page name",
                "actual": surface.get("page"),
                "classification": "lineage/docs drift",
            })
        if not surface.get("route"):
            diffs.append({
                "id": f"registry.{surface_id}.route",
                "expected": "frontend route",
                "actual": surface.get("route"),
                "classification": "lineage/docs drift",
            })
        for value in surface.get("values") or []:
            value_id = value.get("id") or "<missing>"
            if value_id in seen_values:
                diffs.append({
                    "id": f"registry.{value_id}.unique",
                    "expected": "unique value id",
                    "actual": "duplicate",
                    "classification": "lineage/docs drift",
                })
            seen_values.add(value_id)
            if not value.get("label"):
                diffs.append({
                    "id": f"registry.{value_id}.label",
                    "expected": "visible label",
                    "actual": value.get("label"),
                    "classification": "lineage/docs drift",
                })
            stage = value.get("audit_stage")
            if stage not in REGISTRY_AUDIT_STAGES:
                diffs.append({
                    "id": f"registry.{value_id}.audit_stage",
                    "expected": sorted(REGISTRY_AUDIT_STAGES),
                    "actual": stage,
                    "classification": "lineage/docs drift",
                })
            if not value.get("api"):
                diffs.append({
                    "id": f"registry.{value_id}.api",
                    "expected": "API source path",
                    "actual": value.get("api"),
                    "classification": "lineage/docs drift",
                })
            if not value.get("formatter"):
                diffs.append({
                    "id": f"registry.{value_id}.formatter",
                    "expected": "formatter contract",
                    "actual": value.get("formatter"),
                    "classification": "formatter mismatch",
                })
            if not value.get("selector"):
                diffs.append({
                    "id": f"registry.{value_id}.selector",
                    "expected": "DOM selector or pending",
                    "actual": value.get("selector"),
                    "classification": "lineage/docs drift",
                })
            if stage == "api_oracle" and not value.get("check_id"):
                diffs.append({
                    "id": f"registry.{value_id}.check_id",
                    "expected": "audit check id for api_oracle value",
                    "actual": value.get("check_id"),
                    "classification": "lineage/docs drift",
                })
            declared = value.get("view_states")
            if not declared:
                diffs.append({
                    "id": f"registry.{value_id}.view_states",
                    "expected": "at least one explicit owner/view state",
                    "actual": declared,
                    "classification": "lineage/docs drift",
                })
                continue
            unknown = [state_id for state_id in declared if state_id not in valid_state_ids]
            if unknown:
                diffs.append({
                    "id": f"registry.{value_id}.view_states.known",
                    "expected": sorted(valid_state_ids),
                    "actual": unknown,
                    "classification": "lineage/docs drift",
                })
    return diffs


def _registry_check_ids(registry: dict[str, Any], audit_stage: str = "api_oracle") -> set[str]:
    return {
        value.get("check_id")
        for surface in registry.get("surfaces") or []
        for value in surface.get("values") or []
        if value.get("audit_stage") == audit_stage and value.get("check_id")
    }


def _run_second_language_oracle(db_path: Path) -> dict[str, Any]:
    command = [
        "node",
        str(SECOND_LANGUAGE_ORACLE_PATH),
        "--db",
        str(db_path),
        "--registry",
        str(REGISTRY_PATH),
        "--vocabulary",
        str(ORACLE_VOCABULARY_PATH),
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
    except Exception as exc:
        return {
            "status": "error",
            "command": command,
            "error": str(exc),
        }
    if proc.returncode != 0:
        return {
            "status": "error",
            "command": command,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "command": command,
            "error": f"invalid JSON from second-language oracle: {exc}",
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    payload["status"] = "ok"
    return payload


def _compare_second_language_oracle(
    oracle_report: dict[str, Any],
    checks: list[dict[str, Any]],
    diffs: list[dict[str, Any]],
) -> None:
    if oracle_report.get("status") != "ok":
        diffs.append({
            "id": "second_language_oracle.execution",
            "expected": "ok",
            "actual": oracle_report,
            "classification": "oracle issue",
        })
        return

    python_expected = {
        check["id"]: check["expected"]
        for check in checks
        if "expected" in check
        and not check["id"].startswith("runtime_context")
        and not check["id"].startswith("registry.view_state@")
    }
    oracle_expected = {
        check["id"]: check.get("expected")
        for check in oracle_report.get("checks", [])
    }
    _compare(
        "second_language_oracle.check_ids",
        sorted(python_expected),
        sorted(oracle_expected),
        diffs,
        classification="oracle issue",
    )
    for check_id in sorted(set(python_expected) & set(oracle_expected)):
        _compare(
            f"second_language_oracle.{check_id}",
            python_expected[check_id],
            oracle_expected[check_id],
            diffs,
            classification="oracle issue",
        )


def _round2(value: float | int | None) -> float:
    return round(float(value or 0), 2)


def _cents(value: float | int | None) -> int:
    return int(round(float(value or 0) * 100))


def _month_bounds(ref: date) -> tuple[str, str]:
    last = calendar.monthrange(ref.year, ref.month)[1]
    return f"{ref.year}-{ref.month:02d}-01", f"{ref.year}-{ref.month:02d}-{last:02d}"


def _add_months(d: date, delta: int) -> date:
    month_index = d.year * 12 + (d.month - 1) + delta
    year, month_zero = divmod(month_index, 12)
    return date(year, month_zero + 1, 1)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _period_month_count(start: str, end: str) -> int:
    try:
        sy, sm = [int(x) for x in start[:7].split("-")]
        ey, em = [int(x) for x in end[:7].split("-")]
    except ValueError:
        return 1
    return max(1, (ey * 12 + em) - (sy * 12 + sm) + 1)


def _month_series(ref: date, months: int) -> list[date]:
    start = _add_months(ref.replace(day=1), -(months - 1))
    return [_add_months(start, i) for i in range(months)]


def _api_get(path: str) -> Any:
    from fastapi.testclient import TestClient
    from backend.api_server import app

    with TestClient(app) as client:
        res = client.get(path)
        if res.status_code >= 400:
            raise RuntimeError(f"API {path} failed: {res.status_code} {res.text}")
        return res.json()


def _api_path(path: str, owner_id: str | None) -> str:
    if owner_id is None:
        return path
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}owner_id={quote(owner_id)}"


def _scoped_id(base_id: str, view_state: dict[str, Any]) -> str:
    return f"{base_id}@{view_state['id']}"


def _owner_account_ids(conn: sqlite3.Connection, owner_id: str | None) -> list[str] | None:
    if owner_id is None:
        return None
    owner = conn.execute(
        "SELECT id FROM owners WHERE LOWER(id) = LOWER(?)",
        (owner_id,),
    ).fetchone()
    if owner is None:
        return []
    rows = conn.execute(
        """
        SELECT id
          FROM accounts
         WHERE is_active = 1
           AND (LOWER(owner_id) = LOWER(?) OR owner_id IS NULL)
         ORDER BY id
        """,
        (owner_id,),
    ).fetchall()
    return [row["id"] for row in rows]


def _account_scope(
    conn: sqlite3.Connection,
    owner_id: str | None,
    *,
    column: str = "account_id",
) -> tuple[str, list[Any]]:
    account_ids = _owner_account_ids(conn, owner_id)
    if account_ids is None:
        return "", []
    if not account_ids:
        return " AND 1=0", []
    placeholders = ", ".join("?" for _ in account_ids)
    return f" AND {column} IN ({placeholders})", list(account_ids)


def raw_report_summary(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    owner_id: str | None = None,
) -> dict[str, Any]:
    cashout = raw_cashout_period(conn, start, end, owner_id=owner_id)
    top_categories = [
        {
            "category": row["category"],
            "total_spent": row["total"],
            "transaction_count": row["count"],
            "pct_of_total": row["pct"],
        }
        for row in cashout["spending_categories"][:3]
    ]
    return {
        "total_income": cashout["income"],
        "total_spending": cashout["spending"],
        "net": cashout["net"],
        "savings_rate": cashout["savings_rate"],
        "debt_service": cashout["debt_service"],
        "debt_accumulated": cashout["debt_accumulated"],
        "debt_paid_down": cashout["debt_paid_down"],
        "net_debt_change": cashout["net_debt_change"],
        "definition": "cash_out_grossup",
        "top_categories": top_categories,
        "categories_with_spend": len(cashout["spending_categories"]),
    }


def raw_latest_net_worth(
    conn: sqlite3.Connection,
    ref: date,
    owner_id: str | None = None,
) -> dict[str, Any] | None:
    month_end = f"{ref.year}-{ref.month:02d}-{calendar.monthrange(ref.year, ref.month)[1]:02d}"
    banking = 0.0
    liabilities = 0.0
    acct_filter, acct_params = _account_scope(conn, owner_id, column="id")
    account_rows = conn.execute(
        f"SELECT id, type, is_active FROM accounts WHERE 1=1{acct_filter}",
        acct_params,
    ).fetchall()
    if not account_rows:
        return None
    for acct in account_rows:
        bal = conn.execute(
            """
            SELECT balance FROM balance_snapshots
             WHERE account_id = ? AND as_of <= ?
             ORDER BY as_of DESC LIMIT 1
            """,
            (acct["id"], month_end),
        ).fetchone()
        if not bal:
            continue
        if acct["type"] in {"checking", "savings"}:
            banking += float(bal["balance"] or 0)
        elif acct["type"] in {"credit_card", "loan", "bnpl", "mortgage"} and acct["is_active"]:
            liabilities += float(bal["balance"] or 0)

    portfolio = 0.0
    portfolio_filter, portfolio_params = _account_scope(conn, owner_id, column="id")
    for acct in conn.execute(
        f"""
        SELECT id
          FROM accounts
         WHERE type IN ('investment', 'retirement')
           {portfolio_filter}
        """,
        portfolio_params,
    ).fetchall():
        row = conn.execute(
            """
            SELECT total_account_value FROM portfolio_snapshots
             WHERE account_id = ? AND timestamp < date(?, '+1 month')
             ORDER BY timestamp DESC LIMIT 1
            """,
            (acct["id"], month_end[:7] + "-01"),
        ).fetchone()
        if row:
            portfolio += float(row["total_account_value"] or 0)

    real_estate = 0.0
    re_sql = """
        SELECT name, estimated_value FROM real_estate r
         WHERE name NOT LIKE '%[%'
           AND as_of = (
             SELECT MAX(as_of) FROM real_estate r2
              WHERE r2.name = r.name AND r2.as_of <= ?
           )
    """
    re_params: list[Any] = [month_end]
    if owner_id:
        re_sql += " AND LOWER(owner_id) = LOWER(?)"
        re_params.append(owner_id)
    for row in conn.execute(re_sql, re_params).fetchall():
        real_estate += float(row["estimated_value"] or 0)

    vehicles = 0.0
    vehicle_sql = """
        SELECT vehicle_id, estimated_value FROM vehicle_valuations vv
         WHERE valuation_date = (
           SELECT MAX(valuation_date) FROM vehicle_valuations vv2
            WHERE vv2.vehicle_id = vv.vehicle_id AND vv2.valuation_date <= ?
         )
    """
    vehicle_params: list[Any] = [month_end]
    if owner_id:
        vehicle_sql += """
          AND EXISTS (
            SELECT 1 FROM vehicle_assets va
             WHERE va.id = vv.vehicle_id
               AND LOWER(va.owner_id) = LOWER(?)
          )
        """
        vehicle_params.append(owner_id)
    for row in conn.execute(vehicle_sql, vehicle_params).fetchall():
        vehicles += float(row["estimated_value"] or 0)

    assets = _round2(banking + portfolio + real_estate + vehicles)
    return {
        "month": month_end[:7],
        "assets": assets,
        "liabilities": _round2(liabilities),
        "net_worth": _round2(assets + liabilities),
    }


def raw_net_worth_history(
    conn: sqlite3.Connection,
    ref: date,
    months: int = 6,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for month_start in _month_series(ref, months):
        snapshot = raw_net_worth_month(
            conn,
            month_start.year,
            month_start.month,
            owner_id=owner_id,
        )
        if snapshot is not None:
            history.append(snapshot)
    return history


def raw_net_worth_month(
    conn: sqlite3.Connection,
    year: int,
    month: int,
    owner_id: str | None = None,
) -> dict[str, Any] | None:
    as_of = _month_end(year, month).isoformat()
    acct_filter, acct_params = _account_scope(conn, owner_id, column="id")
    accounts = conn.execute(
        f"SELECT id, type, is_active FROM accounts WHERE 1=1{acct_filter}",
        acct_params,
    ).fetchall()
    if not accounts:
        return None

    banking = 0.0
    liabilities = 0.0
    for acct in accounts:
        bal = conn.execute(
            """
            SELECT balance FROM balance_snapshots
             WHERE account_id = ? AND date(as_of) <= date(?)
             ORDER BY as_of DESC LIMIT 1
            """,
            (acct["id"], as_of),
        ).fetchone()
        if not bal:
            continue
        if acct["type"] in {"checking", "savings"}:
            banking += float(bal["balance"] or 0)
        elif acct["type"] in {"credit_card", "loan", "bnpl", "mortgage"} and acct["is_active"]:
            liabilities += float(bal["balance"] or 0)

    portfolio = 0.0
    portfolio_filter, portfolio_params = _account_scope(conn, owner_id, column="id")
    investment_accounts = conn.execute(
        f"""
        SELECT id
          FROM accounts
         WHERE type IN ('investment', 'retirement')
           {portfolio_filter}
        """,
        portfolio_params,
    ).fetchall()
    for acct in investment_accounts:
        row = conn.execute(
            """
            SELECT total_account_value FROM portfolio_snapshots
             WHERE account_id = ? AND date(timestamp) <= date(?)
             ORDER BY timestamp DESC LIMIT 1
            """,
            (acct["id"], as_of),
        ).fetchone()
        if row:
            portfolio += float(row["total_account_value"] or 0)

    real_estate = 0.0
    re_sql = """
        SELECT estimated_value FROM (
            SELECT name, estimated_value,
                   ROW_NUMBER() OVER (
                     PARTITION BY name ORDER BY as_of DESC, rowid DESC
                   ) AS rn
              FROM real_estate
             WHERE name NOT LIKE '%[%'
               AND date(as_of) <= date(?)
    """
    re_params: list[Any] = [as_of]
    if owner_id:
        re_sql += " AND LOWER(owner_id) = LOWER(?)"
        re_params.append(owner_id)
    re_sql += ") ranked WHERE rn = 1 AND estimated_value IS NOT NULL"
    for row in conn.execute(re_sql, re_params).fetchall():
        real_estate += float(row["estimated_value"] or 0)

    vehicles = 0.0
    try:
        veh_sql = """
            SELECT estimated_value FROM (
                SELECT vv.vehicle_id, vv.estimated_value,
                       ROW_NUMBER() OVER (
                         PARTITION BY vv.vehicle_id
                         ORDER BY vv.valuation_date DESC, vv.id DESC
                       ) AS rn
                  FROM vehicle_valuations vv
        """
        veh_params: list[Any] = [as_of]
        if owner_id:
            veh_sql += """
                  JOIN vehicle_assets va ON va.id = vv.vehicle_id
                 WHERE date(vv.valuation_date) <= date(?)
                   AND LOWER(va.owner_id) = LOWER(?)
            """
            veh_params.append(owner_id)
        else:
            veh_sql += " WHERE date(vv.valuation_date) <= date(?)"
        veh_sql += ") ranked WHERE rn = 1 AND estimated_value IS NOT NULL"
        for row in conn.execute(veh_sql, veh_params).fetchall():
            vehicles += float(row["estimated_value"] or 0)
    except sqlite3.OperationalError:
        pass

    assets = _round2(banking + portfolio + real_estate + vehicles)
    return {
        "month": f"{year}-{month:02d}",
        "banking_assets": _round2(banking),
        "investment_assets": _round2(portfolio),
        "real_estate_assets": _round2(real_estate),
        "vehicle_assets": _round2(vehicles),
        "assets": assets,
        "liabilities": _round2(liabilities),
        "net_worth": _round2(assets + liabilities),
    }


def raw_net_worth_velocity(
    conn: sqlite3.Connection,
    ref: date,
    owner_id: str | None = None,
) -> dict[str, Any]:
    history = raw_net_worth_history(conn, ref, months=24, owner_id=owner_id)
    velocity_history = []
    for idx, item in enumerate(history):
        row = {
            "month": item["month"],
            "net_worth": item["net_worth"],
            "mom_change": None,
            "mom_pct": None,
        }
        if idx > 0:
            previous = history[idx - 1]["net_worth"]
            change = _round2(item["net_worth"] - previous)
            row["mom_change"] = change
            if previous:
                row["mom_pct"] = round((change / abs(previous)) * 100, 1)
        velocity_history.append(row)

    current_net_worth = velocity_history[-1]["net_worth"] if velocity_history else 0.0
    mom_change = velocity_history[-1]["mom_change"] if velocity_history else None
    mom_pct = velocity_history[-1]["mom_pct"] if velocity_history else None
    rolling_3m_change = rolling_3m_avg = rolling_12m_change = rolling_12m_avg = None
    if len(velocity_history) >= 4:
        rolling_3m_change = _round2(current_net_worth - velocity_history[-4]["net_worth"])
        rolling_3m_avg = _round2(rolling_3m_change / 3)
    if len(velocity_history) >= 13:
        rolling_12m_change = _round2(current_net_worth - velocity_history[-13]["net_worth"])
        rolling_12m_avg = _round2(rolling_12m_change / 12)
    trend = "insufficient_data"
    if rolling_3m_avg is not None:
        if rolling_3m_avg < 0:
            trend = "declining"
        elif rolling_12m_avg is not None:
            if rolling_3m_avg > 0 and rolling_12m_avg > 0:
                lower = rolling_12m_avg * 0.8
                upper = rolling_12m_avg * 1.2
                if rolling_3m_avg > upper:
                    trend = "accelerating"
                elif rolling_3m_avg < lower:
                    trend = "decelerating"
                else:
                    trend = "steady"
            else:
                trend = "accelerating" if rolling_3m_avg > rolling_12m_avg else "decelerating"
    return {
        "current_net_worth": _round2(current_net_worth),
        "mom_change": mom_change,
        "mom_pct": mom_pct,
        "rolling_3m_change": rolling_3m_change,
        "rolling_3m_monthly_avg": rolling_3m_avg,
        "rolling_12m_change": rolling_12m_change,
        "rolling_12m_monthly_avg": rolling_12m_avg,
        "trend": trend,
        "history": velocity_history,
    }


def raw_dashboard_net_worth_details(
    conn: sqlite3.Connection,
    ref: date,
    owner_id: str | None = None,
) -> dict[str, Any]:
    history = raw_net_worth_history(conn, ref, months=6, owner_id=owner_id)
    if not history:
        return {
            "assets": 0.0,
            "liabilities": 0.0,
            "delta_amount": 0.0,
            "delta_percent": 0.0,
            "velocity_amount": 0.0,
        }
    first = history[0]["net_worth"]
    latest = history[-1]
    delta = _round2(latest["net_worth"] - first)
    months = max(1, len(history) - 1)
    return {
        "assets": latest["assets"],
        "liabilities": latest["liabilities"],
        "delta_amount": delta,
        "delta_percent": round((delta / first) * 100, 1) if first else 0.0,
        "velocity_amount": _round2(delta / months),
    }


def _payroll_adjustment(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    owner_id: str | None = None,
) -> tuple[int, int, int, set[str], list[dict[str, Any]]]:
    start_em, end_em = start[:7], end[:7]
    payroll_owner_clause = ""
    payroll_params: list[Any] = [start_em, end_em]
    if owner_id:
        payroll_owner_clause = "AND LOWER(owner_id) = LOWER(?)"
        payroll_params.append(owner_id)
    rows = conn.execute(
        f"""
        SELECT * FROM payroll_snapshots
         WHERE pay_period BETWEEN ? AND ?
           {payroll_owner_clause}
         ORDER BY pay_period ASC, id ASC
        """,
        payroll_params,
    ).fetchall()
    match_account_filter, match_account_params = _account_scope(
        conn,
        owner_id,
        column="account_id",
    )
    income_add_cents = 0
    withholding_cents = 0
    withholding_count = 0
    excluded_tx_ids: set[str] = set()
    income_categories: list[dict[str, Any]] = []
    for r in rows:
        gross = _cents(r["gross_pay"])
        for col in [
            "federal_tax",
            "state_tax",
            "sbp_premium",
            "health_insurance",
            "dental_vision",
            "other_deductions",
        ]:
            cents = _cents(r[col])
            if cents:
                withholding_cents += cents
                withholding_count += 1
        source = (r["source"] or "").strip().lower()
        match = None
        if len(source) >= 3:
            pattern = f"%{source}%"
            match = conn.execute(
                f"""
                SELECT id FROM transactions
                 WHERE status = 'posted'
                   AND signed_amount > 0
                   AND transfer_tag IS NULL
                   AND substr(COALESCE(effective_month, strftime('%Y-%m', posting_date)), 1, 7) = ?
                   {match_account_filter}
                   AND (LOWER(COALESCE(merchant, '')) LIKE ?
                        OR LOWER(COALESCE(description, '')) LIKE ?)
                 ORDER BY signed_amount DESC, id ASC LIMIT 1
                """,
                [r["pay_period"], *match_account_params, pattern, pattern],
            ).fetchone()
        if match and match["id"] not in excluded_tx_ids:
            excluded_tx_ids.add(match["id"])
            income_add_cents += gross
            label = "Paycheck (gross)"
        else:
            income_add_cents += gross
            label = "Paycheck (no deposit matched)"
        if gross > 0:
            income_categories.append({
                "category": label,
                "total_cents": gross,
                "count": 1,
            })
    return (
        income_add_cents,
        withholding_cents,
        withholding_count,
        excluded_tx_ids,
        income_categories,
    )


def raw_cashout_period(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    owner_id: str | None = None,
) -> dict[str, Any]:
    start_em, end_em = start[:7], end[:7]
    (
        _payroll_income_add,
        payroll_withholding,
        payroll_withholding_count,
        excluded_tx_ids,
        payroll_income_categories,
    ) = _payroll_adjustment(conn, start, end, owner_id=owner_id)

    txn_account_filter, txn_account_params = _account_scope(
        conn,
        owner_id,
        column="account_id",
    )
    txn_account_filter_t, txn_account_params_t = _account_scope(
        conn,
        owner_id,
        column="t.account_id",
    )

    excluded_clause = ""
    excluded_params: list[Any] = []
    if excluded_tx_ids:
        excluded_clause = "AND id NOT IN (" + ",".join("?" for _ in excluded_tx_ids) + ")"
        excluded_params = sorted(excluded_tx_ids)

    ph_income_excl = ",".join("?" for _ in INCOME_EXCL_FROM_INC)
    income_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Other Income') AS category,
               COALESCE(SUM(signed_amount), 0) AS total,
               COUNT(*) AS count
          FROM transactions
         WHERE status = 'posted'
           AND signed_amount > 0
           AND transfer_tag IS NULL
           AND COALESCE(category, 'Other Income') NOT IN ({ph_income_excl})
           {excluded_clause}
           AND COALESCE(effective_month, strftime('%Y-%m', posting_date)) BETWEEN ? AND ?
           {txn_account_filter}
         GROUP BY category
        """,
        [*INCOME_EXCL_FROM_INC, *excluded_params, start_em, end_em, *txn_account_params],
    ).fetchall()
    income_categories = [
        {
            "category": r["category"],
            "total_cents": _cents(r["total"]),
            "count": r["count"],
        }
        for r in income_rows
    ]
    income_categories.extend(payroll_income_categories)
    income_categories.sort(key=lambda row: row["total_cents"], reverse=True)
    income_cents = sum(row["total_cents"] for row in income_categories)

    ph_cash_types = ",".join("?" for _ in CASH_ACCOUNT_TYPES)
    ph_spend_excl = ",".join("?" for _ in CASHOUT_SPEND_EXCLUDE)
    spend_rows = conn.execute(
        f"""
        SELECT COALESCE(t.category, 'Uncategorized') AS category,
               SUM(-t.signed_amount) AS total,
               COUNT(*) AS count
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
         WHERE t.status = 'posted'
           AND t.signed_amount < 0
           AND t.transfer_tag IS NULL
           AND a.type IN ({ph_cash_types})
           AND COALESCE(t.category, 'Uncategorized') NOT IN ({ph_spend_excl})
           AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
           {txn_account_filter_t}
         GROUP BY category
        """,
        [*CASH_ACCOUNT_TYPES, *CASHOUT_SPEND_EXCLUDE, start_em, end_em, *txn_account_params_t],
    ).fetchall()
    ordinary_spend_cents = sum(_cents(r["total"]) for r in spend_rows)
    spending_categories = [
        {
            "category": r["category"],
            "total_cents": _cents(r["total"]),
            "count": r["count"],
        }
        for r in spend_rows
    ]
    raw_debt_cash_cents = sum(
        _cents(r["total"]) for r in spend_rows if r["category"] in DEBT_CASH_CATEGORIES
    )

    mortgage = conn.execute(
        f"""
        SELECT t.id, t.signed_amount, s.principal_cents, s.interest_cents, s.escrow_cents
          FROM transactions t
          LEFT JOIN loan_payment_splits s ON s.transaction_id = t.id
         WHERE t.status = 'posted'
           AND t.signed_amount < 0
           AND t.transfer_tag IS NULL
           AND t.category IN ('Mortgage', 'Mortgages')
           AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
           {txn_account_filter_t}
        """,
        [start_em, end_em, *txn_account_params_t],
    ).fetchall()
    mortgage_consumed_cents = 0
    mortgage_principal_cents = 0
    for r in mortgage:
        total = _cents(abs(float(r["signed_amount"] or 0)))
        if r["principal_cents"] is None:
            mortgage_consumed_cents += total
        else:
            mortgage_principal_cents += int(r["principal_cents"] or 0)
            mortgage_consumed_cents += int(r["interest_cents"] or 0) + int(r["escrow_cents"] or 0)

    transfer_to_liability_cents = 0
    cc_payment_cents = 0
    cc_payment_count = 0
    loan_payment_via_transfer_cents = 0
    loan_payment_via_transfer_count = 0
    transfer_rows = conn.execute(
        f"""
        SELECT t.id, t.transfer_tag, t.account_id, t.signed_amount
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
         WHERE t.status = 'posted'
           AND t.signed_amount < 0
           AND t.transfer_tag IS NOT NULL
           AND a.type IN ('checking', 'savings', 'money_market')
           AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
           {txn_account_filter_t}
        """,
        [start_em, end_em, *txn_account_params_t],
    ).fetchall()
    for t in transfer_rows:
        peer = conn.execute(
            """
            SELECT a.type FROM transactions p
              JOIN accounts a ON a.id = p.account_id
             WHERE p.transfer_tag = ?
               AND p.id != ?
               AND p.signed_amount > 0
             ORDER BY p.posting_date LIMIT 1
            """,
            (t["transfer_tag"], t["id"]),
        ).fetchone()
        peer_type = (peer["type"] or "").lower() if peer else ""
        if peer_type in LIABILITY_TYPES:
            amount_cents = _cents(abs(float(t["signed_amount"] or 0)))
            transfer_to_liability_cents += amount_cents
            if peer_type in {"credit_card", "credit", "bnpl"}:
                cc_payment_cents += amount_cents
                cc_payment_count += 1
            elif peer_type in {"loan", "mortgage"}:
                loan_payment_via_transfer_cents += amount_cents
                loan_payment_via_transfer_count += 1

    ph_debt_accumulated_excl = ",".join("?" for _ in DEBT_ACCUMULATED_EXCLUDE)
    debt_accumulated_row = conn.execute(
        f"""
        SELECT COALESCE(SUM(-t.signed_amount), 0) AS total
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
         WHERE t.status = 'posted'
           AND t.signed_amount < 0
           AND t.transfer_tag IS NULL
           AND a.type IN ('credit_card', 'credit', 'bnpl')
           AND COALESCE(t.category, '') NOT IN ({ph_debt_accumulated_excl})
           AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
           {txn_account_filter_t}
        """,
        [*DEBT_ACCUMULATED_EXCLUDE, start_em, end_em, *txn_account_params_t],
    ).fetchone()
    debt_accumulated_cents = _cents(debt_accumulated_row["total"])

    spending_cents = ordinary_spend_cents + payroll_withholding + mortgage_consumed_cents + transfer_to_liability_cents
    debt_service_cents = mortgage_consumed_cents + transfer_to_liability_cents + raw_debt_cash_cents
    debt_paid_down_cents = mortgage_principal_cents + transfer_to_liability_cents + raw_debt_cash_cents
    net_cents = income_cents - spending_cents
    savings_rate = round((net_cents / income_cents) * 100, 1) if income_cents else 0.0

    if mortgage_consumed_cents > 0:
        spending_categories.append({
            "category": "Mortgage Interest & Escrow",
            "total_cents": mortgage_consumed_cents,
            "count": len(mortgage),
        })
    if cc_payment_cents > 0:
        spending_categories.append({
            "category": "Credit Card Payments",
            "total_cents": cc_payment_cents,
            "count": cc_payment_count,
        })
    if loan_payment_via_transfer_cents > 0:
        spending_categories.append({
            "category": "Loan / Mortgage Transfers",
            "total_cents": loan_payment_via_transfer_cents,
            "count": loan_payment_via_transfer_count,
        })
    if payroll_withholding > 0:
        spending_categories.append({
            "category": "Taxes & Withholdings",
            "total_cents": payroll_withholding,
            "count": payroll_withholding_count,
        })
    spending_categories.sort(key=lambda row: row["total_cents"], reverse=True)

    def _to_breakdown(rows: list[dict[str, Any]], total_cents: int) -> list[dict[str, Any]]:
        return [
            {
                "category": row["category"],
                "total": round(row["total_cents"] / 100, 2),
                "count": row["count"],
                "pct": round(row["total_cents"] / total_cents * 100, 1)
                if total_cents
                else 0.0,
            }
            for row in rows
            if row["total_cents"] > 0
        ]

    return {
        "income": round(income_cents / 100, 2),
        "spending": round(spending_cents / 100, 2),
        "net": round(net_cents / 100, 2),
        "savings_rate": savings_rate,
        "debt_service": round(debt_service_cents / 100, 2),
        "debt_accumulated": round(debt_accumulated_cents / 100, 2),
        "debt_paid_down": round(debt_paid_down_cents / 100, 2),
        "net_debt_change": round((debt_accumulated_cents - debt_paid_down_cents) / 100, 2),
        "income_categories": _to_breakdown(income_categories, income_cents),
        "spending_categories": _to_breakdown(spending_categories, spending_cents),
    }


def raw_emergency_fund(
    conn: sqlite3.Connection,
    ref: date,
    owner_id: str | None = None,
) -> dict[str, Any]:
    acct_filter_a, acct_params_a = _account_scope(conn, owner_id, column="a.id")
    acct_filter_tx, acct_params_tx = _account_scope(conn, owner_id, column="account_id")
    liquid = conn.execute(
        f"""
        SELECT COALESCE(SUM(latest.balance), 0) AS total
          FROM accounts a
          JOIN (
            SELECT bs.account_id, bs.balance
              FROM balance_snapshots bs
              JOIN (
                SELECT account_id, MAX(as_of) AS max_as_of
                  FROM balance_snapshots GROUP BY account_id
              ) mx ON mx.account_id = bs.account_id AND mx.max_as_of = bs.as_of
          ) latest ON latest.account_id = a.id
         WHERE a.type IN ('checking', 'savings') AND a.is_active = 1
           {acct_filter_a}
        """
        ,
        acct_params_a,
    ).fetchone()["total"]

    current_month = ref.replace(day=1)
    start_month_index = current_month.year * 12 + current_month.month - 1 - 6
    start = date(start_month_index // 12, start_month_index % 12 + 1, 1).isoformat()
    end = current_month.isoformat()
    ph = ",".join("?" for _ in ALL_EXCL_FROM_SPEND)
    rows = conn.execute(
        f"""
        SELECT COALESCE(effective_month, strftime('%Y-%m', posting_date)) AS month,
               SUM(-signed_amount) AS total
          FROM transactions
         WHERE status = 'posted'
           AND signed_amount < 0
           AND transfer_tag IS NULL
           {acct_filter_tx}
           AND COALESCE(category, 'Uncategorized') NOT IN ({ph})
           AND posting_date >= ?
           AND posting_date < ?
         GROUP BY month
        """,
        [*acct_params_tx, *ALL_EXCL_FROM_SPEND, start, end],
    ).fetchall()
    avg = sum(float(r["total"] or 0) for r in rows) / len(rows) if rows else 0.0
    return {
        "liquid_balance": _round2(liquid),
        "avg_monthly_spending": _round2(avg),
        "months_of_runway": round(float(liquid or 0) / avg, 1) if avg else None,
    }


def raw_latest_credit_scores(
    conn: sqlite3.Connection,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    owner_inner_clause = ""
    owner_outer_clause = ""
    params: list[Any] = []
    if owner_id:
        owner_inner_clause = "WHERE LOWER(owner_id) = LOWER(?)"
        owner_outer_clause = "WHERE LOWER(cs.owner_id) = LOWER(?)"
        params.extend([owner_id, owner_id])
    rows = conn.execute(
        f"""
        SELECT cs.score, cs.score_type, cs.source, cs.institution_id,
               cs.score_date, cs.owner_id
          FROM credit_scores cs
          JOIN (
            SELECT owner_id, institution_id, source, MAX(score_date) AS max_date
              FROM credit_scores
             {owner_inner_clause}
             GROUP BY owner_id, institution_id, source
          ) latest ON cs.owner_id IS latest.owner_id
                   AND cs.institution_id = latest.institution_id
                   AND cs.source = latest.source
                   AND cs.score_date = latest.max_date
         {owner_outer_clause}
         ORDER BY cs.owner_id, cs.score_date DESC
        """,
        params,
    ).fetchall()
    return [{**dict(r), "factors": []} for r in rows]


def raw_freshness(
    conn: sqlite3.Connection,
    ref: date,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    now = datetime.combine(ref, time.min, tzinfo=timezone.utc)
    acct_filter, acct_params = _account_scope(conn, owner_id, column="id")
    acct_filter_alias, acct_params_alias = _account_scope(conn, owner_id, column="a.id")
    active_rows = conn.execute(
        f"SELECT DISTINCT institution_id FROM accounts WHERE is_active = 1{acct_filter}",
        acct_params,
    ).fetchall()
    active_institutions = {r["institution_id"] for r in active_rows}
    active_institutions.update({"tsp", "mypay"})
    try:
        active_institutions.update(
            r["institution_id"]
            for r in conn.execute("SELECT institution_id FROM institution_refresh_status")
        )
    except sqlite3.OperationalError:
        pass

    refresh_last = {}
    try:
        refresh_last = {
            r["institution_id"]: r["last_success"]
            for r in conn.execute(
                "SELECT institution_id, last_success FROM institution_refresh_status"
            ).fetchall()
            if r["last_success"]
        }
    except sqlite3.OperationalError:
        pass

    balance_last = {
        r["institution_id"]: r["latest"]
        for r in conn.execute(
            f"""
            SELECT a.institution_id, MAX(bs.as_of) AS latest
              FROM balance_snapshots bs
              JOIN accounts a ON a.id = bs.account_id
             WHERE 1=1
               {acct_filter_alias}
             GROUP BY a.institution_id
            """,
            acct_params_alias,
        ).fetchall()
        if r["latest"]
    }
    portfolio_last = {
        r["institution_id"]: r["latest"]
        for r in conn.execute(
            f"""
            SELECT a.institution_id, MAX(ps.timestamp) AS latest
              FROM portfolio_snapshots ps
              JOIN accounts a ON a.id = ps.account_id
             WHERE 1=1
               {acct_filter_alias}
             GROUP BY a.institution_id
            """,
            acct_params_alias,
        ).fetchall()
        if r["latest"]
    }
    apy_last = {}
    try:
        apy_last = {
            r["institution_id"]: r["latest"]
            for r in conn.execute(
                f"""
                SELECT a.institution_id, MAX(ah.as_of) AS latest
                  FROM apy_history ah
                  JOIN accounts a ON a.id = ah.account_id
                 WHERE 1=1
                   {acct_filter_alias}
                 GROUP BY a.institution_id
                """,
                acct_params_alias,
            ).fetchall()
            if r["latest"]
        }
    except sqlite3.OperationalError:
        pass

    result = []
    for inst in active_institutions:
        ts_raw = max(
            (
                ts
                for ts in [
                    refresh_last.get(inst),
                    balance_last.get(inst),
                    portfolio_last.get(inst),
                    apy_last.get(inst),
                ]
                if ts
            ),
            default=None,
        )
        expected_hours = 720 if inst in {"tsp", "mypay"} else 24
        staleness = "no_data"
        if ts_raw:
            if "T" not in ts_raw and " " not in ts_raw:
                ts = datetime.fromisoformat(ts_raw[:10] + "T23:59:59").replace(tzinfo=timezone.utc)
            else:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            hours_since = max((now - ts).total_seconds() / 3600, 0)
            if hours_since <= expected_hours:
                staleness = "fresh"
            elif hours_since <= expected_hours * 3:
                staleness = "stale"
            else:
                staleness = "critical"
        result.append({"institution_id": inst, "staleness": staleness})
    return sorted(result, key=lambda x: x["institution_id"])


def raw_dti_series(
    conn: sqlite3.Connection,
    ref: date,
    months: int = 12,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    inc_cats = list(INCOME_CATEGORIES)
    debt_cats = ["Mortgages", "Loan Payments", "Credit Card Payments", "BNPL Payments"]
    inc_ph = ",".join("?" for _ in inc_cats)
    debt_ph = ",".join("?" for _ in debt_cats)
    acct_filter, acct_params = _account_scope(conn, owner_id, column="t.account_id")
    current_month = ref.replace(day=1)
    window_start = _add_months(current_month, -months).isoformat()
    window_end = current_month.isoformat()
    rows = conn.execute(
        f"""
        SELECT COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) AS month,
               SUM(CASE
                   WHEN t.transfer_tag IS NULL
                    AND t.signed_amount > 0
                    AND COALESCE(t.category, 'Other Income') IN ({inc_ph})
                   THEN t.signed_amount ELSE 0 END) AS gross_income,
               SUM(CASE
                   WHEN t.signed_amount < 0
                    AND a.type IN ('checking', 'savings')
                    AND COALESCE(t.category, '') IN ({debt_ph})
                   THEN ABS(t.signed_amount) ELSE 0 END) AS debt_payments
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
         WHERE t.status = 'posted'
           AND t.posting_date >= ?
           AND t.posting_date < ?
           {acct_filter}
         GROUP BY month
         ORDER BY month ASC
        """,
        [*inc_cats, *debt_cats, window_start, window_end, *acct_params],
    ).fetchall()
    result = []
    for row in rows:
        income = _round2(row["gross_income"])
        debt = _round2(row["debt_payments"])
        dti = round((debt / income) * 100, 1) if income else None
        status = None
        if dti is not None:
            if dti <= 28.0:
                status = "healthy"
            elif dti <= 36.0:
                status = "moderate"
            elif dti <= 43.0:
                status = "high"
            else:
                status = "critical"
        result.append({
            "month": row["month"],
            "debt_payments": debt,
            "gross_income": income,
            "dti_ratio": dti,
            "status": status,
        })
    return result


def raw_spending_comparison(
    conn: sqlite3.Connection,
    ref: date,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    this_month_start = ref.replace(day=1)
    this_month_end = _month_end(ref.year, ref.month)
    prev_month_start = _add_months(this_month_start, -1)
    prev_month_end = _month_end(prev_month_start.year, prev_month_start.month)
    max_days = max(this_month_end.day, prev_month_end.day, 31)
    acct_filter, acct_params = _account_scope(conn, owner_id)
    ph = ",".join("?" for _ in ALL_EXCL_FROM_SPEND)

    def daily(start_date: date, end_date: date) -> dict[int, float]:
        rows = conn.execute(
            f"""
            SELECT CAST(strftime('%d', posting_date) AS INTEGER) AS day,
                   SUM(-signed_amount) AS daily_spent
              FROM transactions
             WHERE status = 'posted'
               AND signed_amount < 0
               AND transfer_tag IS NULL
               AND COALESCE(category, 'Uncategorized') NOT IN ({ph})
               AND posting_date >= ?
               AND posting_date <= ?
               {acct_filter}
             GROUP BY day
            """,
            [*ALL_EXCL_FROM_SPEND, start_date.isoformat(), end_date.isoformat(), *acct_params],
        ).fetchall()
        return {int(r["day"]): float(r["daily_spent"] or 0) for r in rows}

    current = daily(this_month_start, this_month_end)
    previous = daily(prev_month_start, prev_month_end)
    rows = []
    cum_current = 0.0
    cum_previous = 0.0
    for day in range(1, max_days + 1):
        if day <= prev_month_end.day:
            cum_previous += previous.get(day, 0.0)
        item: dict[str, Any] = {
            "period": f"Day {day}",
            "Previous": _round2(cum_previous),
        }
        if day <= ref.day and day <= this_month_end.day:
            cum_current += current.get(day, 0.0)
            item["Current"] = _round2(cum_current)
        rows.append(item)
    return rows


def raw_dashboard_spending(
    conn: sqlite3.Connection,
    ref: date,
    total_spending: float,
    owner_id: str | None = None,
) -> dict[str, Any]:
    comparison = raw_spending_comparison(conn, ref, owner_id=owner_id)
    prev_total = 0.0
    for row in reversed(comparison):
        value = row.get("Previous")
        if value is not None and value > 0:
            prev_total = value
            break
    delta = _round2(total_spending - prev_total)
    per_day = total_spending / ref.day if ref.day else 0.0
    projected = per_day * _month_end(ref.year, ref.month).day
    return {
        "current_month_total": _round2(total_spending),
        "previous_total": _round2(prev_total),
        "delta_amount": delta,
        "delta_percent": round((delta / prev_total) * 100, 1) if prev_total else 0.0,
        "per_day": _round2(per_day),
        "projected_eom": _round2(projected),
        "comparison": comparison,
    }


def raw_budget_summary(
    conn: sqlite3.Connection,
    month: str,
) -> dict[str, Any]:
    targets = {
        row["category"]: float(row["target_amount"] or 0)
        for row in conn.execute(
            "SELECT category, target_amount FROM budgets WHERE month = ? AND owner_id IS NULL",
            (month,),
        ).fetchall()
    }
    ph = ",".join("?" for _ in ALL_EXCL_FROM_SPEND)
    actual_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Uncategorized') AS category,
               SUM(-signed_amount) AS spending
          FROM transactions
         WHERE status = 'posted'
           AND signed_amount < 0
           AND transfer_tag IS NULL
           AND COALESCE(effective_month, strftime('%Y-%m', posting_date)) = ?
           AND COALESCE(category, 'Uncategorized') NOT IN ({ph})
         GROUP BY category
        """,
        [month, *ALL_EXCL_FROM_SPEND],
    ).fetchall()
    actuals = {row["category"]: float(row["spending"] or 0) for row in actual_rows}
    categories = []
    for cat in sorted(set(targets) | set(actuals)):
        target = targets.get(cat, 0.0)
        actual = actuals.get(cat, 0.0)
        pct_used = actual / target * 100 if target > 0 else (100 if actual > 0 else 0)
        if pct_used >= 100:
            status = "over"
        elif pct_used >= 80:
            status = "warning"
        elif pct_used >= 50:
            status = "on_track"
        else:
            status = "under"
        categories.append({
            "category": cat,
            "target": _round2(target),
            "target_amount": _round2(target),
            "actual": _round2(actual),
            "spent": _round2(actual),
            "remaining": _round2(target - actual),
            "pct_used": round(pct_used, 1),
            "status": status,
        })
    categories.sort(key=lambda row: -row["pct_used"])
    total_budget = _round2(sum(row["target"] for row in categories))
    total_spent = _round2(sum(row["actual"] for row in categories))
    return {
        "month": month,
        "total_budget": total_budget,
        "total_budgeted": total_budget,
        "total_spent": total_spent,
        "total_remaining": _round2(total_budget - total_spent),
        "pct_used": round((total_spent / total_budget) * 100, 1) if total_budget else 0.0,
        "over_budget_count": sum(1 for row in categories if row["status"] == "over"),
        "categories_tracked": len(categories),
        "categories": categories,
    }


def raw_recurring_dashboard(
    conn: sqlite3.Connection,
    owner_id: str | None = None,
) -> dict[str, Any]:
    acct_filter = ""
    params: list[Any] = ["active"]
    if owner_id:
        acct_filter, acct_params = _account_scope(conn, owner_id)
        if acct_filter:
            acct_filter = acct_filter.replace(" AND ", " AND ")
            params.extend(acct_params)
    rows = conn.execute(
        f"""
        SELECT id, merchant, frequency, expected_amount, last_amount
          FROM recurring_transactions
         WHERE status = ?
           {acct_filter}
         ORDER BY frequency, merchant
        """,
        params,
    ).fetchall()
    items = [dict(row) for row in rows]
    bills = [
        item
        for item in items
        if float(item.get("expected_amount") if item.get("expected_amount") is not None else item.get("last_amount") or 0) < 0
    ]
    monthly = 0.0
    for item in bills:
        raw = float(item.get("expected_amount") if item.get("expected_amount") is not None else item.get("last_amount") or 0)
        divisor = RECURRING_FREQ_DIVISOR.get((item.get("frequency") or "monthly").lower(), 1)
        monthly += abs(raw) / divisor
    return {
        "monthly_total": round(monthly),
        "item_amounts": [
            _round2(item.get("expected_amount") if item.get("expected_amount") is not None else item.get("last_amount") or 0)
            for item in bills[:5]
        ],
        "item_ids": [item["id"] for item in bills[:5]],
        "count": len(items),
    }


def raw_transactions_page(
    conn: sqlite3.Connection,
    owner_id: str | None = None,
    *,
    limit: int = 1000,
    start_date: str | None = None,
    end_date: str | None = None,
    exclude_transfers: bool = False,
) -> dict[str, Any]:
    clauses = ["1=1"]
    params: list[Any] = []
    if start_date:
        clauses.append("posting_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("posting_date <= ?")
        params.append(end_date)
    if exclude_transfers:
        ph = ",".join("?" for _ in EXCLUDED_FROM_SPEND)
        clauses.append(f"COALESCE(category, 'Uncategorized') NOT IN ({ph})")
        params.extend(EXCLUDED_FROM_SPEND)
        clauses.append("transfer_tag IS NULL")
    scope, scope_params = _account_scope(conn, owner_id)
    where = " AND ".join(clauses) + scope
    total_count = conn.execute(
        f"SELECT COUNT(*) AS count FROM transactions WHERE {where}",
        [*params, *scope_params],
    ).fetchone()["count"]
    rows = conn.execute(
        f"""
        SELECT id, posting_date, signed_amount, amount, category, account_id, transfer_tag
          FROM transactions
         WHERE {where}
         ORDER BY posting_date DESC
         LIMIT ? OFFSET 0
        """,
        [*params, *scope_params, limit],
    ).fetchall()
    txns = [dict(row) for row in rows]
    page = txns[:25]
    return {
        "row_amounts": [_round2(tx.get("signed_amount") if tx.get("signed_amount") is not None else tx.get("amount")) for tx in page],
        "row_dates": [tx.get("posting_date") for tx in page],
        "filtered_count": len(txns),
        "total_count": total_count,
        "range_start": 1 if page else 0,
        "range_end": min(25, len(txns)),
        "active_filter_count": 0,
        "recent_amounts": [
            _round2(tx.get("signed_amount") if tx.get("signed_amount") is not None else tx.get("amount"))
            for tx in txns
        ],
    }


def raw_cashout_rolling(
    conn: sqlite3.Connection,
    ref: date,
    owner_id: str | None = None,
    months: int = 18,
) -> list[dict[str, Any]]:
    result = []
    for month_start in _month_series(ref, months):
        end = _month_end(month_start.year, month_start.month)
        detail = raw_cashout_period(
            conn,
            month_start.isoformat(),
            end.isoformat(),
            owner_id=owner_id,
        )
        result.append({
            "year": month_start.year,
            "month": month_start.month,
            "label": f"{calendar.month_abbr[month_start.month]} '{month_start.year % 100:02d}",
            **{
                key: detail[key]
                for key in [
                    "income",
                    "spending",
                    "net",
                    "savings_rate",
                    "debt_service",
                    "debt_accumulated",
                    "debt_paid_down",
                    "net_debt_change",
                ]
            },
        })
    return result


def _raw_bypass_flows(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, display_label, owner_id, tax_treatment, match_rule_json
          FROM income_sources
         WHERE active = 1
           AND bypass_cash_routing = 1
    """
    params: list[Any] = []
    if owner_id:
        sql += " AND LOWER(owner_id) = LOWER(?)"
        params.append(owner_id)
    rows = conn.execute(sql, params).fetchall()
    flows = []
    months = _period_month_count(start, end)
    for row in rows:
        try:
            rule = json.loads(row["match_rule_json"] or "{}")
        except ValueError:
            continue
        monthly = int(rule.get("monthly_amount_cents") or 0)
        if monthly <= 0:
            continue
        flows.append({
            "source_id": row["id"],
            "display_label": row["display_label"],
            "owner_id": row["owner_id"],
            "tax_treatment": row["tax_treatment"],
            "monthly_amount_cents": monthly,
            "months": months,
            "amount_cents": monthly * months,
            "bucket": "STORED_ILLIQUID",
        })
    return flows


def _raw_investment_transfer_cents(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    owner_id: str | None = None,
) -> int:
    start_em, end_em = start[:7], end[:7]
    t1_filter, t1_params = _account_scope(conn, owner_id, column="t1.account_id")
    t_filter, t_params = _account_scope(conn, owner_id, column="t.account_id")
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(amount), 0) AS total FROM (
            SELECT t1.id, ABS(t1.signed_amount) AS amount
              FROM transactions t1
              JOIN transactions t2
                   ON t1.transfer_tag = t2.transfer_tag AND t1.id != t2.id
              JOIN accounts a2 ON a2.id = t2.account_id
             WHERE t1.status = 'posted'
               AND t1.signed_amount < 0
               AND t1.transfer_tag IS NOT NULL
               AND a2.type IN ('investment', 'brokerage', 'retirement', 'hsa')
               AND COALESCE(t1.effective_month, strftime('%Y-%m', t1.posting_date)) BETWEEN ? AND ?
               {t1_filter}
            UNION
            SELECT t.id, ABS(t.signed_amount) AS amount
              FROM transactions t
              JOIN positions_ledger pl ON pl.bank_txn_id = t.id
             WHERE t.status = 'posted'
               AND t.signed_amount < 0
               AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
               {t_filter}
        )
        """,
        [start_em, end_em, *t1_params, start_em, end_em, *t_params],
    ).fetchone()
    return _cents(row["total"] if row else 0)


def raw_reports_flow(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    owner_id: str | None = None,
) -> dict[str, Any]:
    cashout = raw_cashout_period(conn, start, end, owner_id=owner_id)
    bypass_flows = _raw_bypass_flows(conn, start, end, owner_id=owner_id)
    bypass_cents = sum(flow["amount_cents"] for flow in bypass_flows)
    investment_transfer_cents = _raw_investment_transfer_cents(conn, start, end, owner_id=owner_id)
    consumed_cents = _cents(cashout["spending"])
    illiquid_cents = investment_transfer_cents + bypass_cents
    total_inflow_cents = _cents(cashout["income"]) + bypass_cents
    liquid_cents = total_inflow_cents - consumed_cents - illiquid_cents
    bucket_totals_cents = {
        "CONSUMED": consumed_cents,
        "STORED_LIQUID": liquid_cents,
        "STORED_ILLIQUID": illiquid_cents,
    }
    bucket_total = sum(bucket_totals_cents.values())
    bucket_totals = {key: _round2(value / 100) for key, value in bucket_totals_cents.items()}
    return {
        "total_income": cashout["income"],
        "total_spending": cashout["spending"],
        "net": cashout["net"],
        "savings_rate": cashout["savings_rate"],
        "bucket_totals": bucket_totals,
        "bucket_totals_cents": bucket_totals_cents,
        "bucket_percents": {
            key: round((value / bucket_total) * 100, 1) if bucket_total else 0.0
            for key, value in bucket_totals_cents.items()
        },
        "total_inflow_cents": total_inflow_cents,
        "bucket_invariant_drift_cents": sum(bucket_totals_cents.values()) - total_inflow_cents,
        "bypass_flows": bypass_flows,
        "debt_service": cashout["debt_service"],
        "debt_accumulated": cashout["debt_accumulated"],
        "debt_paid_down": cashout["debt_paid_down"],
        "net_debt_change": cashout["net_debt_change"],
    }


def raw_net_worth_at_date(
    conn: sqlite3.Connection,
    as_of: str,
    owner_id: str | None = None,
) -> dict[str, int]:
    acct_filter, acct_params = _account_scope(conn, owner_id, column="a.id")
    row = conn.execute(
        f"""
        WITH latest_bal AS (
            SELECT a.id, a.type, a.is_active,
                   (SELECT bs.balance
                      FROM balance_snapshots bs
                     WHERE bs.account_id = a.id
                       AND date(bs.as_of) <= date(?)
                     ORDER BY bs.as_of DESC LIMIT 1) AS balance
              FROM accounts a
             WHERE 1=1 {acct_filter}
        )
        SELECT SUM(CASE WHEN type IN ('checking','savings') THEN balance ELSE 0 END) AS banking,
               SUM(CASE WHEN type IN ('credit_card','loan','bnpl','mortgage')
                         AND is_active = 1 THEN balance ELSE 0 END) AS liabilities
          FROM latest_bal
         WHERE balance IS NOT NULL
        """,
        [as_of, *acct_params],
    ).fetchone()
    banking = _cents(row["banking"] if row else 0)
    liabilities = _cents(row["liabilities"] if row else 0)
    port = conn.execute(
        f"""
        WITH latest_port AS (
            SELECT a.id,
                   (SELECT ps.total_account_value
                      FROM portfolio_snapshots ps
                     WHERE ps.account_id = a.id
                       AND date(ps.timestamp) <= date(?)
                     ORDER BY ps.timestamp DESC LIMIT 1) AS total
              FROM accounts a
             WHERE a.type IN ('investment','retirement')
               {acct_filter}
        )
        SELECT SUM(total) AS portfolio FROM latest_port WHERE total IS NOT NULL
        """,
        [as_of, *acct_params],
    ).fetchone()
    investment = _cents(port["portfolio"] if port else 0)
    re_sql = """
        SELECT estimated_value FROM (
            SELECT estimated_value,
                   ROW_NUMBER() OVER (PARTITION BY name ORDER BY as_of DESC, rowid DESC) AS rn
              FROM real_estate
             WHERE name NOT LIKE '%[%'
               AND date(as_of) <= date(?)
    """
    re_params: list[Any] = [as_of]
    if owner_id:
        re_sql += " AND LOWER(owner_id) = LOWER(?)"
        re_params.append(owner_id)
    re_sql += ") ranked WHERE rn = 1 AND estimated_value IS NOT NULL"
    real_estate = sum(_cents(r["estimated_value"]) for r in conn.execute(re_sql, re_params).fetchall())
    vehicle = 0
    try:
        veh_sql = """
            SELECT estimated_value FROM (
                SELECT vv.estimated_value,
                       ROW_NUMBER() OVER (
                         PARTITION BY vv.vehicle_id
                         ORDER BY vv.valuation_date DESC, vv.id DESC
                       ) AS rn
                  FROM vehicle_valuations vv
        """
        veh_params: list[Any] = [as_of]
        if owner_id:
            veh_sql += """
                  JOIN vehicle_assets va ON va.id = vv.vehicle_id
                 WHERE date(vv.valuation_date) <= date(?)
                   AND LOWER(va.owner_id) = LOWER(?)
            """
            veh_params.append(owner_id)
        else:
            veh_sql += " WHERE date(vv.valuation_date) <= date(?)"
        veh_sql += ") ranked WHERE rn = 1 AND estimated_value IS NOT NULL"
        vehicle = sum(_cents(r["estimated_value"]) for r in conn.execute(veh_sql, veh_params).fetchall())
    except sqlite3.OperationalError:
        pass
    return {
        "banking_cents": banking,
        "investment_cents": investment,
        "real_estate_cents": real_estate,
        "vehicle_cents": vehicle,
        "liabilities_cents": liabilities,
        "net_worth_cents": banking + investment + real_estate + vehicle + liabilities,
    }


def raw_accountability(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    owner_id: str | None = None,
) -> dict[str, Any]:
    nw_start = raw_net_worth_at_date(conn, start, owner_id=owner_id)
    nw_end = raw_net_worth_at_date(conn, end, owner_id=owner_id)
    flow = raw_reports_flow(conn, start, end, owner_id=owner_id)
    user_contrib = _raw_investment_transfer_cents(conn, start, end, owner_id=owner_id)
    acct_filter, acct_params = _account_scope(conn, owner_id)
    capex = conn.execute(
        f"""
        SELECT COALESCE(SUM(-signed_amount), 0) AS capex
          FROM transactions
         WHERE status = 'posted'
           AND signed_amount < 0
           AND transfer_tag IS NULL
           AND category = 'Home Improvement'
           AND date(posting_date) >= date(?)
           AND date(posting_date) <= date(?)
           {acct_filter}
        """,
        [start, end, *acct_params],
    ).fetchone()
    capex_cents = _cents(capex["capex"] if capex else 0)
    net_worth_delta = nw_end["net_worth_cents"] - nw_start["net_worth_cents"]
    market_delta = nw_end["investment_cents"] - nw_start["investment_cents"] - user_contrib
    real_estate_delta = nw_end["real_estate_cents"] - nw_start["real_estate_cents"] - capex_cents
    vehicle_delta = nw_end["vehicle_cents"] - nw_start["vehicle_cents"]
    dollars_in = int(flow["total_inflow_cents"])
    dollars_spent = int(flow["bucket_totals_cents"]["CONSUMED"])
    accounted = dollars_in - dollars_spent + market_delta + real_estate_delta + vehicle_delta
    unexplained = net_worth_delta - accounted
    accounted_pct = 1.0 if net_worth_delta == 0 else max(0.0, 1.0 - abs(unexplained) / abs(net_worth_delta))

    # Independent minimal drift-source count for canonical-seed visible UI.
    re_owner_clause = "AND LOWER(owner_id) = LOWER(?)" if owner_id else ""
    re_params = [owner_id] if owner_id else []
    stale_real_estate = int(conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM (
            SELECT name, MAX(date(as_of)) AS latest
              FROM real_estate
             WHERE name NOT LIKE '%[%'
               AND source != '[source]'
               {re_owner_clause}
             GROUP BY name
            HAVING latest < date(?, '-90 days')
        )
        """,
        [*re_params, end],
    ).fetchone()["n"] or 0)
    drift_count = stale_real_estate
    drift_count += int(conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM (
            SELECT name, COUNT(*) AS valuations
              FROM real_estate
             WHERE name NOT LIKE '%[%'
               AND source != '[source]'
               {re_owner_clause}
             GROUP BY name
            HAVING valuations < 2
        )
        """,
        re_params,
    ).fetchone()["n"] or 0)
    if stale_real_estate:
        drift_count += stale_real_estate
    return {
        "start_date": start,
        "end_date": end,
        "net_worth_start_cents": nw_start["net_worth_cents"],
        "net_worth_end_cents": nw_end["net_worth_cents"],
        "net_worth_delta_cents": net_worth_delta,
        "identity_terms": {
            "dollars_in_cents": dollars_in,
            "dollars_spent_cents": dollars_spent,
            "market_value_delta_cents": market_delta,
            "real_estate_delta_cents": real_estate_delta,
            "vehicle_delta_cents": vehicle_delta,
        },
        "unexplained_cents": unexplained,
        "accounted_for_pct": round(accounted_pct, 4),
        "drift_source_count": drift_count,
    }


def raw_accounts_snapshot(
    conn: sqlite3.Connection,
    owner_id: str | None = None,
) -> dict[str, Any]:
    acct_filter, acct_params = _account_scope(conn, owner_id, column="id")
    rows = conn.execute(
        f"""
        SELECT id, institution_id, name, last4, type, owner_id, closed_at, is_synthetic
          FROM accounts
         WHERE is_active = 1
           AND id IN (
             SELECT DISTINCT account_id FROM balance_snapshots
             UNION
             SELECT DISTINCT account_id FROM transactions
           )
           {acct_filter}
        """,
        acct_params,
    ).fetchall()
    accounts = [dict(row) for row in rows]
    latest_balances = {
        row["account_id"]: dict(row)
        for row in conn.execute(
            """
            SELECT bs.account_id, bs.balance, bs.as_of
              FROM balance_snapshots bs
             WHERE bs.id = (
               SELECT id FROM balance_snapshots b2
                WHERE b2.account_id = bs.account_id
                ORDER BY b2.as_of DESC LIMIT 1
             )
            """
        ).fetchall()
    }
    loan_details = {
        row["account_id"]: dict(row)
        for row in conn.execute(
            """
            WITH latest AS (
                SELECT ld.account_id, ld.field_name, ld.field_value
                  FROM loan_details ld
                 WHERE ld.as_of = (
                   SELECT MAX(ld2.as_of)
                     FROM loan_details ld2
                    WHERE ld2.account_id = ld.account_id
                      AND ld2.field_name = ld.field_name
                 )
            )
            SELECT account_id,
                   MAX(CASE WHEN field_name='purchase_price' THEN CAST(field_value AS REAL) END) AS purchase_price,
                   MAX(CASE WHEN field_name='interest_rate' THEN CAST(field_value AS REAL) END) AS interest_rate,
                   MAX(CASE WHEN field_name='minimum_payment' THEN CAST(field_value AS REAL) END) AS minimum_payment,
                   MAX(CASE WHEN field_name='term_months' THEN CAST(field_value AS INTEGER) END) AS term_months,
                   MAX(CASE WHEN field_name='origination_date' THEN field_value END) AS origination_date,
                   MAX(CASE WHEN field_name='credit_limit' THEN CAST(field_value AS REAL) END) AS credit_limit,
                   MAX(CASE WHEN field_name='rewards_points' THEN field_value END) AS rewards_points
              FROM latest
             GROUP BY account_id
            """
        ).fetchall()
    }

    for acct in accounts:
        bal = latest_balances.get(acct["id"])
        acct["balance"] = bal["balance"] if bal else None
        acct["balance_as_of"] = bal["as_of"] if bal else None
        if acct["type"] in {"investment", "retirement"}:
            snap = conn.execute(
                """
                SELECT total_account_value, cash_balance FROM portfolio_snapshots
                 WHERE account_id = ? ORDER BY timestamp DESC LIMIT 1
                """,
                (acct["id"],),
            ).fetchone()
            total_value = float(snap["total_account_value"] or 0) if snap else 0.0
            cash_value = float(snap["cash_balance"] or 0) if snap else 0.0
            acct["holdings_value"] = _round2(total_value - cash_value)
            acct["investment_cash"] = _round2(cash_value)
            if (acct["balance"] or 0) == 0 or total_value > (acct["balance"] or 0):
                acct["balance"] = _round2(total_value)
        if acct["id"] in loan_details:
            acct.update({
                key: value
                for key, value in loan_details[acct["id"]].items()
                if key != "account_id"
            })
        if acct.get("closed_at"):
            acct["status"] = "closed"
        elif acct["type"] in {"loan", "mortgage", "bnpl"}:
            acct["status"] = "paid_off" if acct.get("balance") is not None and acct["balance"] >= 0 else "active"
        else:
            acct["status"] = "active"

    manual_owner_clause = ""
    manual_params: list[Any] = []
    if owner_id:
        manual_owner_clause = " AND LOWER(owner_id) = LOWER(?)"
        manual_params.append(owner_id)
    real_estate = [
        dict(row)
        for row in conn.execute(
            f"""
            WITH latest AS (
                SELECT id, name, estimated_value, linked_loan_id, source,
                       as_of, owner_id,
                       ROW_NUMBER() OVER (
                         PARTITION BY name ORDER BY as_of DESC, id DESC
                       ) AS rn
                  FROM real_estate
                 WHERE source != '[source]'
                   {manual_owner_clause}
            )
            SELECT id, name, estimated_value, as_of, source, linked_loan_id, owner_id
              FROM latest
             WHERE rn = 1
             ORDER BY name
            """,
            manual_params,
        ).fetchall()
    ]
    vehicles = []
    veh_sql = "SELECT id, make, model, year, purchase_date, purchase_price FROM vehicle_assets"
    veh_params: list[Any] = []
    if owner_id:
        veh_sql += " WHERE LOWER(owner_id) = LOWER(?)"
        veh_params.append(owner_id)
    for row in conn.execute(veh_sql, veh_params).fetchall():
        vehicle = dict(row)
        latest = conn.execute(
            """
            SELECT valuation_date, estimated_value, source, source_url
              FROM vehicle_valuations
             WHERE vehicle_id = ?
             ORDER BY valuation_date DESC LIMIT 1
            """,
            (vehicle["id"],),
        ).fetchone()
        vehicle["latest_value"] = latest["estimated_value"] if latest else None
        vehicle["latest_value_as_of"] = latest["valuation_date"] if latest else None
        vehicle["latest_value_source"] = latest["source"] if latest else None
        vehicles.append(vehicle)

    display_accounts = list(accounts)
    for re_row in real_estate:
        display_accounts.append({
            "id": f"manual:re:{re_row['id']}",
            "institution_id": "manual",
            "name": re_row["name"],
            "type": "real_estate",
            "balance": re_row["estimated_value"] or 0,
            "balance_as_of": re_row["as_of"],
            "status": "active",
        })
    for vehicle in vehicles:
        display_accounts.append({
            "id": f"manual:veh:{vehicle['id']}",
            "institution_id": "manual",
            "name": f"{vehicle['year']} {vehicle['make']} {vehicle['model']}",
            "type": "vehicle",
            "balance": vehicle["latest_value"] or 0,
            "balance_as_of": vehicle["latest_value_as_of"],
            "status": "active",
        })

    groups = {
        "Credit cards": [a for a in display_accounts if a["type"] in {"credit_card", "credit"}],
        "Loans": [a for a in display_accounts if a["type"] in {"loan", "bnpl", "mortgage"}],
        "Cash": [a for a in display_accounts if a["type"] in {"checking", "savings"}],
        "Real Estate": [a for a in display_accounts if a["type"] in {"real_estate", "property"}],
        "Vehicles": [a for a in display_accounts if a["type"] == "vehicle"],
        "Investments": [a for a in display_accounts if a["type"] in {"investment", "retirement"}],
    }
    group_totals = {
        name: _round2(sum(float(a.get("balance") or 0) for a in rows))
        for name, rows in groups.items()
        if rows
    }
    asset_buckets = {
        "Real Estate": sum(float(a.get("balance") or 0) for a in groups["Real Estate"] if (a.get("balance") or 0) >= 0),
        "Vehicles": sum(float(a.get("balance") or 0) for a in groups["Vehicles"] if (a.get("balance") or 0) >= 0),
        "Investments": sum(float(a.get("balance") or 0) for a in groups["Investments"] if (a.get("balance") or 0) >= 0),
        "Cash": sum(float(a.get("balance") or 0) for a in groups["Cash"] if (a.get("balance") or 0) >= 0),
    }
    asset_buckets = {key: _round2(value) for key, value in asset_buckets.items() if value > 0}
    liabilities = {
        "Credit Cards": abs(sum(float(a.get("balance") or 0) for a in groups["Credit cards"])),
        "BNPL": abs(sum(float(a.get("balance") or 0) for a in display_accounts if a["type"] == "bnpl")),
        "Loans": abs(sum(float(a.get("balance") or 0) for a in display_accounts if a["type"] in {"loan", "mortgage"})),
    }
    liabilities = {key: _round2(value) for key, value in liabilities.items() if value > 0}
    assets_total = _round2(sum(asset_buckets.values()))
    liabilities_total = _round2(sum(liabilities.values()))
    bucket_totals = {**asset_buckets, **liabilities}
    bucket_percents = {
        **{
            key: round((value / assets_total) * 100, 1) if assets_total else 0.0
            for key, value in asset_buckets.items()
        },
        **{
            key: round((value / liabilities_total) * 100, 1) if liabilities_total else 0.0
            for key, value in liabilities.items()
        },
    }
    return {
        "display_total": None,
        "group_totals": group_totals,
        "row_balances": [_round2(a.get("balance") or 0) for a in display_accounts],
        "row_balance_as_of": [a.get("balance_as_of") for a in display_accounts],
        "apr": [a.get("interest_rate") for a in display_accounts if a.get("interest_rate")],
        "rewards_points": [
            int(str(a.get("rewards_points")).replace(",", ""))
            for a in display_accounts
            if a.get("rewards_points") and str(a.get("rewards_points")).replace(",", "").isdigit()
        ],
        "installment_paid_percent": [
            max(0, min(100, round(((a.get("purchase_price") + (a.get("balance") or 0)) / a.get("purchase_price")) * 100)))
            for a in display_accounts
            if a.get("purchase_price") and a.get("purchase_price") > 0
        ],
        "credit_utilization_percent": [
            max(0, min(100, round((abs(a.get("balance") or 0) / a.get("credit_limit")) * 100)))
            for a in display_accounts
            if a.get("credit_limit") and a.get("credit_limit") > 0 and not a.get("purchase_price")
        ],
        "summary": {
            "assets_total": assets_total,
            "liabilities_total": liabilities_total,
            "bucket_totals": bucket_totals,
            "bucket_percents": bucket_percents,
        },
    }


def accounts_snapshot_from_api(
    accounts_api: dict[str, Any],
) -> dict[str, Any]:
    display_accounts: list[dict[str, Any]] = []
    for account in accounts_api.get("accounts") or []:
        acct = dict(account)
        if acct.get("type") == "investment" and acct.get("holdings_value") is not None:
            holdings = float(acct.get("holdings_value") or 0)
            cash_portion = float(acct.get("balance") or 0) - holdings
            if cash_portion > 1.0:
                investment_part = dict(acct)
                investment_part["id"] = f"{acct['id']}_inv"
                investment_part["_originalId"] = acct["id"]
                investment_part["name"] = f"{acct.get('name')} (Investments)"
                investment_part["balance"] = holdings
                display_accounts.append(investment_part)

                cash_part = dict(acct)
                cash_part["id"] = f"{acct['id']}_cash"
                cash_part["_originalId"] = acct["id"]
                cash_part["name"] = f"{acct.get('name')} (Cash)"
                cash_part["type"] = "savings"
                cash_part["balance"] = cash_portion
                display_accounts.append(cash_part)
                continue
        display_accounts.append(acct)

    manual_assets = accounts_api.get("manual_assets") or {}
    for re_row in manual_assets.get("real_estate") or []:
        display_accounts.append({
            "id": f"manual:re:{re_row['id']}",
            "institution_id": "manual",
            "name": re_row["name"],
            "type": "real_estate",
            "balance": re_row.get("estimated_value") or 0,
            "balance_as_of": re_row.get("as_of"),
            "status": "active",
        })
    for vehicle in manual_assets.get("vehicles") or []:
        display_accounts.append({
            "id": f"manual:veh:{vehicle['id']}",
            "institution_id": "manual",
            "name": f"{vehicle['year']} {vehicle['make']} {vehicle['model']}",
            "type": "vehicle",
            "balance": vehicle.get("latest_value") or 0,
            "balance_as_of": vehicle.get("latest_value_as_of"),
            "status": "active",
        })

    groups = {
        "Credit cards": [a for a in display_accounts if a["type"] in {"credit_card", "credit"}],
        "Loans": [a for a in display_accounts if a["type"] in {"loan", "bnpl", "mortgage"}],
        "Cash": [a for a in display_accounts if a["type"] in {"checking", "savings"}],
        "Real Estate": [a for a in display_accounts if a["type"] in {"real_estate", "property"}],
        "Vehicles": [a for a in display_accounts if a["type"] == "vehicle"],
        "Investments": [a for a in display_accounts if a["type"] in {"investment", "retirement"}],
    }
    group_totals = {
        name: _round2(sum(float(a.get("balance") or 0) for a in rows))
        for name, rows in groups.items()
        if rows
    }
    asset_buckets = {
        "Real Estate": sum(float(a.get("balance") or 0) for a in groups["Real Estate"] if (a.get("balance") or 0) >= 0),
        "Vehicles": sum(float(a.get("balance") or 0) for a in groups["Vehicles"] if (a.get("balance") or 0) >= 0),
        "Investments": sum(float(a.get("balance") or 0) for a in groups["Investments"] if (a.get("balance") or 0) >= 0),
        "Cash": sum(float(a.get("balance") or 0) for a in groups["Cash"] if (a.get("balance") or 0) >= 0),
    }
    asset_buckets = {key: _round2(value) for key, value in asset_buckets.items() if value > 0}
    liabilities = {
        "Credit Cards": abs(sum(float(a.get("balance") or 0) for a in groups["Credit cards"])),
        "BNPL": abs(sum(float(a.get("balance") or 0) for a in display_accounts if a["type"] == "bnpl")),
        "Loans": abs(sum(float(a.get("balance") or 0) for a in display_accounts if a["type"] in {"loan", "mortgage"})),
    }
    liabilities = {key: _round2(value) for key, value in liabilities.items() if value > 0}
    assets_total = _round2(sum(asset_buckets.values()))
    liabilities_total = _round2(sum(liabilities.values()))
    bucket_totals = {**asset_buckets, **liabilities}
    bucket_percents = {
        **{
            key: round((value / assets_total) * 100, 1) if assets_total else 0.0
            for key, value in asset_buckets.items()
        },
        **{
            key: round((value / liabilities_total) * 100, 1) if liabilities_total else 0.0
            for key, value in liabilities.items()
        },
    }
    return {
        "display_total": None,
        "group_totals": group_totals,
        "row_balances": [_round2(a.get("balance") or 0) for a in display_accounts],
        "row_balance_as_of": [a.get("balance_as_of") for a in display_accounts],
        "apr": [a.get("interest_rate") for a in display_accounts if a.get("interest_rate")],
        "rewards_points": [
            int(str(a.get("rewards_points")).replace(",", ""))
            for a in display_accounts
            if a.get("rewards_points") and str(a.get("rewards_points")).replace(",", "").isdigit()
        ],
        "installment_paid_percent": [
            max(0, min(100, round(((a.get("purchase_price") + (a.get("balance") or 0)) / a.get("purchase_price")) * 100)))
            for a in display_accounts
            if a.get("purchase_price") and a.get("purchase_price") > 0
        ],
        "credit_utilization_percent": [
            max(0, min(100, round((abs(a.get("balance") or 0) / a.get("credit_limit")) * 100)))
            for a in display_accounts
            if a.get("credit_limit") and a.get("credit_limit") > 0 and not a.get("purchase_price")
        ],
        "summary": {
            "assets_total": assets_total,
            "liabilities_total": liabilities_total,
            "bucket_totals": bucket_totals,
            "bucket_percents": bucket_percents,
        },
    }


def _compare(name: str, expected: Any, actual: Any, diffs: list[dict[str, Any]], classification: str = "API/DAL logic bug") -> None:
    if expected != actual:
        diffs.append({
            "id": name,
            "expected": expected,
            "actual": actual,
            "classification": classification,
        })


def _compare_money_cents(
    name: str,
    expected: float | int | None,
    actual: float | int | None,
    diffs: list[dict[str, Any]],
    classification: str = "API/DAL logic bug",
) -> None:
    _compare(name, _cents(expected), _cents(actual), diffs, classification=classification)


def _check_partition(
    name: str,
    rows: list[dict[str, Any]],
    total: float | int | None,
    diffs: list[dict[str, Any]],
) -> None:
    row_total_cents = sum(_cents(row.get("total")) for row in rows)
    total_cents = _cents(total)
    _compare(
        f"{name}.category_total_matches_headline",
        total_cents,
        row_total_cents,
        diffs,
        classification="invariant violation",
    )
    if total_cents:
        pct_sum = round(sum(float(row.get("pct") or 0) for row in rows), 1)
        expected_pct = 100.0 if row_total_cents else 0.0
        if abs(pct_sum - expected_pct) > 0.5:
            diffs.append({
                "id": f"{name}.category_pct_sum",
                "expected": expected_pct,
                "actual": pct_sum,
                "classification": "invariant violation",
            })


def run(db_path: Path) -> dict[str, Any]:
    os.environ["SENTRY_DB_PATH"] = str(db_path)
    os.environ.setdefault("SENTRY_DB_MODE", "trusted")
    conn = _connect(db_path)
    try:
        manifest = _manifest(conn)
        registry = _load_registry()
        runtime_context = build_runtime_context()
        ref = date.fromisoformat(manifest["reference_date"])
        start, end = _month_bounds(ref)

        diffs: list[dict[str, Any]] = _registry_diffs(registry)
        checks: list[dict[str, Any]] = []
        view_states = _registry_view_states(registry)
        if not runtime_context["proof"]["trusted_seed_ready"]:
            diffs.append({
                "id": "runtime_context.trusted_seed_ready",
                "expected": True,
                "actual": runtime_context["proof"],
                "classification": "seed issue",
            })
        checks.append({
            "id": "runtime_context",
            "expected": {"trusted_seed_ready": True},
            "actual": runtime_context,
        })

        for view_state in view_states:
            owner_id = view_state.get("owner_id")
            view_check = {
                "id": _scoped_id("registry.view_state", view_state),
                "view_state": view_state,
                "expected": {"owner_id": owner_id},
                "actual": {"account_ids": _owner_account_ids(conn, owner_id)},
            }
            checks.append(view_check)

            nw_expected = raw_latest_net_worth(conn, ref, owner_id=owner_id)
            nw_api = _api_get(_api_path("/api/reports/net-worth-history?months=6", owner_id))
            nw_history = nw_api.get("history") or []
            nw_actual = nw_history[-1] if nw_history else None
            if nw_expected is None or nw_actual is None:
                _compare(
                    _scoped_id("dashboard.net_worth.latest.present", view_state),
                    nw_expected is not None,
                    nw_actual is not None,
                    diffs,
                )
            else:
                _compare_money_cents(
                    _scoped_id("dashboard.net_worth.latest", view_state),
                    nw_expected["net_worth"],
                    nw_actual.get("net_worth"),
                    diffs,
                )
            checks.append({
                "id": _scoped_id("dashboard.net_worth.latest", view_state),
                "view_state": view_state,
                "expected": nw_expected,
                "actual": nw_actual,
            })

            summary_expected = raw_report_summary(conn, start, end, owner_id=owner_id)
            summary_api = _api_get(_api_path(
                f"/api/reports/summary?start_date={start}&end_date={end}",
                owner_id,
            ))
            for field in [
                "total_income",
                "total_spending",
                "net",
                "debt_service",
                "debt_accumulated",
                "debt_paid_down",
                "net_debt_change",
            ]:
                _compare_money_cents(
                    _scoped_id(f"dashboard.monthly_net_flow.{field}", view_state),
                    summary_expected[field],
                    summary_api.get(field),
                    diffs,
                )
            _compare(
                _scoped_id("dashboard.monthly_net_flow.savings_rate", view_state),
                summary_expected["savings_rate"],
                summary_api.get("savings_rate"),
                diffs,
            )
            _compare(
                _scoped_id("dashboard.monthly_net_flow.definition", view_state),
                summary_expected["definition"],
                summary_api.get("definition"),
                diffs,
                classification="label mismatch",
            )
            _compare(
                _scoped_id("dashboard.monthly_net_flow.categories_with_spend", view_state),
                summary_expected["categories_with_spend"],
                summary_api.get("categories_with_spend"),
                diffs,
            )
            checks.append({
                "id": _scoped_id("dashboard.monthly_net_flow", view_state),
                "view_state": view_state,
                "expected": summary_expected,
                "actual": summary_api,
            })

            emergency_expected = raw_emergency_fund(conn, ref, owner_id=owner_id)
            emergency_api = _api_get(_api_path("/api/metrics/emergency-fund", owner_id))
            for field in ["liquid_balance", "avg_monthly_spending"]:
                _compare_money_cents(
                    _scoped_id(f"dashboard.emergency_runway.{field}", view_state),
                    emergency_expected[field],
                    emergency_api.get(field),
                    diffs,
                )
            _compare(
                _scoped_id("dashboard.emergency_runway.months_of_runway", view_state),
                emergency_expected["months_of_runway"],
                emergency_api.get("months_of_runway"),
                diffs,
            )
            checks.append({
                "id": _scoped_id("dashboard.emergency_runway", view_state),
                "view_state": view_state,
                "expected": emergency_expected,
                "actual": emergency_api,
            })

            credit_expected = raw_latest_credit_scores(conn, owner_id=owner_id)
            credit_api = _api_get(_api_path("/api/metrics/credit-scores", owner_id)).get("latest") or []
            _compare(
                _scoped_id("dashboard.credit_scores.latest", view_state),
                credit_expected,
                credit_api,
                diffs,
            )
            checks.append({
                "id": _scoped_id("dashboard.credit_scores.latest", view_state),
                "view_state": view_state,
                "expected": credit_expected,
                "actual": credit_api,
            })

            fresh_expected = raw_freshness(conn, ref, owner_id=owner_id)
            fresh_api = sorted(
                [
                    {"institution_id": r["institution_id"], "staleness": r["staleness"]}
                    for r in _api_get(_api_path("/api/freshness", owner_id))
                ],
                key=lambda x: x["institution_id"],
            )
            _compare(
                _scoped_id("dashboard.freshness.state_labels", view_state),
                fresh_expected,
                fresh_api,
                diffs,
                classification="label mismatch",
            )
            checks.append({
                "id": _scoped_id("dashboard.freshness.state_labels", view_state),
                "view_state": view_state,
                "expected": fresh_expected,
                "actual": fresh_api,
            })

            nw_details_expected = raw_dashboard_net_worth_details(conn, ref, owner_id=owner_id)
            nw_details_actual = None
            if nw_history:
                first = nw_history[0].get("net_worth") or 0
                latest_row = nw_history[-1]
                delta = _round2((latest_row.get("net_worth") or 0) - first)
                months = max(1, len(nw_history) - 1)
                nw_details_actual = {
                    "assets": _round2(latest_row.get("assets")),
                    "liabilities": _round2(latest_row.get("liabilities")),
                    "delta_amount": delta,
                    "delta_percent": round((delta / first) * 100, 1) if first else 0.0,
                    "velocity_amount": _round2(delta / months),
                }
            else:
                nw_details_actual = {
                    "assets": 0.0,
                    "liabilities": 0.0,
                    "delta_amount": 0.0,
                    "delta_percent": 0.0,
                    "velocity_amount": 0.0,
                }
            _compare(
                _scoped_id("dashboard.net_worth.details", view_state),
                nw_details_expected,
                nw_details_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("dashboard.net_worth.details", view_state),
                "view_state": view_state,
                "expected": nw_details_expected,
                "actual": nw_details_actual,
            })

            velocity_expected = raw_net_worth_velocity(conn, ref, owner_id=owner_id)
            velocity_api = _api_get(_api_path("/api/metrics/net-worth-velocity", owner_id))
            velocity_actual = {
                key: velocity_api.get(key)
                for key in [
                    "current_net_worth",
                    "mom_change",
                    "mom_pct",
                    "rolling_3m_change",
                    "rolling_3m_monthly_avg",
                    "rolling_12m_change",
                    "rolling_12m_monthly_avg",
                    "trend",
                    "history",
                ]
            }
            _compare(
                _scoped_id("dashboard.net_worth.velocity", view_state),
                velocity_expected,
                velocity_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("dashboard.net_worth.velocity", view_state),
                "view_state": view_state,
                "expected": velocity_expected,
                "actual": velocity_actual,
            })

            dti_series_expected = raw_dti_series(conn, ref, months=12, owner_id=owner_id)
            dti_series_api = _api_get(_api_path("/api/metrics/dti?months=12", owner_id))
            dti_latest_expected = dti_series_expected[-1] if dti_series_expected else None
            dti_latest_actual = dti_series_api[-1] if dti_series_api else None
            _compare(
                _scoped_id("cash_flow.dti.latest", view_state),
                dti_latest_expected,
                dti_latest_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("cash_flow.dti.latest", view_state),
                "view_state": view_state,
                "expected": dti_latest_expected,
                "actual": dti_latest_actual,
            })

            spending_expected = raw_dashboard_spending(
                conn,
                ref,
                summary_expected["total_spending"],
                owner_id=owner_id,
            )
            spending_api_rows = _api_get(_api_path(
                f"/api/reports/spending-comparison?reference_date={ref.isoformat()}&timeframe=month_vs_last_month",
                owner_id,
            )).get("data") or []
            spending_actual = raw_dashboard_spending(
                conn,
                ref,
                summary_api.get("total_spending") or 0,
                owner_id=owner_id,
            )
            spending_actual["comparison"] = spending_api_rows
            _compare(
                _scoped_id("dashboard.spending.hero", view_state),
                spending_expected,
                spending_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("dashboard.spending.hero", view_state),
                "view_state": view_state,
                "expected": spending_expected,
                "actual": spending_actual,
            })

            budget_expected = raw_budget_summary(conn, f"{ref.year}-{ref.month:02d}")
            budget_summary_api = _api_get(f"/api/budgets/summary?month={ref.year}-{ref.month:02d}")
            budget_categories_api = _api_get(f"/api/budgets?month={ref.year}-{ref.month:02d}").get("categories") or []
            budget_actual = {
                "month": budget_summary_api.get("month"),
                "total_budget": budget_summary_api.get("total_budget"),
                "total_budgeted": budget_summary_api.get("total_budgeted"),
                "total_spent": budget_summary_api.get("total_spent"),
                "total_remaining": budget_summary_api.get("total_remaining"),
                "pct_used": budget_summary_api.get("pct_used"),
                "over_budget_count": budget_summary_api.get("over_budget_count"),
                "categories_tracked": budget_summary_api.get("categories_tracked"),
                "categories": [
                    {
                        key: row.get(key)
                        for key in [
                            "category",
                            "target",
                            "target_amount",
                            "actual",
                            "spent",
                            "remaining",
                            "pct_used",
                            "status",
                        ]
                    }
                    for row in budget_categories_api
                ],
            }
            _compare(
                _scoped_id("dashboard.budget.summary", view_state),
                budget_expected,
                budget_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("dashboard.budget.summary", view_state),
                "view_state": view_state,
                "expected": budget_expected,
                "actual": budget_actual,
            })

            recurring_expected = raw_recurring_dashboard(conn, owner_id=owner_id)
            recurring_api = _api_get(_api_path("/api/recurring", owner_id))
            recurring_items = recurring_api.get("recurring") or []
            recurring_bills = [
                item for item in recurring_items
                if float(item.get("expected_amount") if item.get("expected_amount") is not None else item.get("last_amount") or 0) < 0
            ]
            recurring_monthly = 0.0
            for item in recurring_bills:
                raw = float(item.get("expected_amount") if item.get("expected_amount") is not None else item.get("last_amount") or 0)
                divisor = RECURRING_FREQ_DIVISOR.get((item.get("frequency") or "monthly").lower(), 1)
                recurring_monthly += abs(raw) / divisor
            recurring_actual = {
                "monthly_total": round(recurring_monthly),
                "item_amounts": [
                    _round2(item.get("expected_amount") if item.get("expected_amount") is not None else item.get("last_amount") or 0)
                    for item in recurring_bills[:5]
                ],
                "item_ids": [item["id"] for item in recurring_bills[:5]],
                "count": recurring_api.get("count"),
            }
            _compare(
                _scoped_id("dashboard.recurring.summary", view_state),
                recurring_expected,
                recurring_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("dashboard.recurring.summary", view_state),
                "view_state": view_state,
                "expected": recurring_expected,
                "actual": recurring_actual,
            })

            recent_expected = raw_transactions_page(
                conn,
                owner_id=owner_id,
                limit=8,
                exclude_transfers=True,
            )["recent_amounts"][:8]
            recent_api = _api_get(_api_path("/api/transactions?limit=8&exclude_transfers=true", owner_id))
            recent_actual = [
                _round2(tx.get("signed_amount") if tx.get("signed_amount") is not None else tx.get("amount"))
                for tx in recent_api.get("transactions") or []
            ]
            _compare(
                _scoped_id("dashboard.recent_transactions", view_state),
                recent_expected,
                recent_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("dashboard.recent_transactions", view_state),
                "view_state": view_state,
                "expected": recent_expected,
                "actual": recent_actual,
            })

            cash_expected = raw_cashout_period(conn, start, end, owner_id=owner_id)
            cash_api = _api_get(_api_path(f"/api/cash-flow/period?start={start}&end={end}", owner_id))
            for field in [
                "income",
                "spending",
                "net",
                "debt_service",
                "debt_accumulated",
                "debt_paid_down",
                "net_debt_change",
            ]:
                _compare_money_cents(
                    _scoped_id(f"cash_flow.current_month.{field}", view_state),
                    cash_expected[field],
                    cash_api.get(field),
                    diffs,
                )
            _compare(
                _scoped_id("cash_flow.current_month.savings_rate", view_state),
                cash_expected["savings_rate"],
                _round2(cash_api.get("savings_rate")),
                diffs,
            )
            _compare(
                _scoped_id("cash_flow.current_month.debt_service_percent", view_state),
                round((cash_expected["debt_service"] / cash_expected["spending"]) * 100, 1)
                if cash_expected["spending"]
                else 0.0,
                round(((cash_api.get("debt_service") or 0) / cash_api.get("spending")) * 100, 1)
                if cash_api.get("spending")
                else 0.0,
                diffs,
            )
            _compare(
                _scoped_id("cash_flow.current_month.income_categories", view_state),
                cash_expected["income_categories"],
                cash_api.get("income_categories") or [],
                diffs,
            )
            _compare(
                _scoped_id("cash_flow.current_month.spending_categories", view_state),
                cash_expected["spending_categories"],
                cash_api.get("spending_categories") or [],
                diffs,
            )
            _check_partition(
                _scoped_id("cash_flow.current_month.income", view_state),
                cash_api.get("income_categories") or [],
                cash_api.get("income"),
                diffs,
            )
            _check_partition(
                _scoped_id("cash_flow.current_month.spending", view_state),
                cash_api.get("spending_categories") or [],
                cash_api.get("spending"),
                diffs,
            )
            for summary_field, cash_field in [
                ("total_income", "income"),
                ("total_spending", "spending"),
                ("net", "net"),
            ]:
                _compare_money_cents(
                    _scoped_id(f"reports_summary.matches_cash_flow.{summary_field}", view_state),
                    summary_api.get(summary_field),
                    cash_api.get(cash_field),
                    diffs,
                    classification="API/DAL logic bug",
                )
            checks.append({
                "id": _scoped_id("cash_flow.current_month", view_state),
                "view_state": view_state,
                "expected": cash_expected,
                "actual": cash_api,
            })

            rolling_api = _api_get(_api_path("/api/cash-flow/monthly-rolling", owner_id))
            latest = (rolling_api.get("months") or [])[-1]
            rolling_actual = {
                k: _round2(latest.get(k))
                for k in [
                    "income",
                    "spending",
                    "net",
                    "savings_rate",
                    "debt_service",
                    "debt_accumulated",
                    "debt_paid_down",
                    "net_debt_change",
                ]
            }
            rolling_expected = {k: cash_expected[k] for k in rolling_actual}
            for field in [
                "income",
                "spending",
                "net",
                "debt_service",
                "debt_accumulated",
                "debt_paid_down",
                "net_debt_change",
            ]:
                _compare_money_cents(
                    _scoped_id(f"cash_flow.rolling.latest_month.{field}", view_state),
                    rolling_expected[field],
                    rolling_actual[field],
                    diffs,
                )
            _compare(
                _scoped_id("cash_flow.rolling.latest_month.savings_rate", view_state),
                rolling_expected["savings_rate"],
                rolling_actual["savings_rate"],
                diffs,
            )
            checks.append({
                "id": _scoped_id("cash_flow.rolling.latest_month", view_state),
                "view_state": view_state,
                "expected": rolling_expected,
                "actual": rolling_actual,
            })

            rolling_chart_expected = raw_cashout_rolling(conn, ref, owner_id=owner_id, months=18)
            rolling_chart_actual = [
                {
                    key: row.get(key)
                    for key in [
                        "year",
                        "month",
                        "label",
                        "income",
                        "spending",
                        "net",
                        "savings_rate",
                        "debt_service",
                        "debt_accumulated",
                        "debt_paid_down",
                        "net_debt_change",
                    ]
                }
                for row in rolling_api.get("months") or []
            ]
            _compare(
                _scoped_id("cash_flow.chart.monthly_points", view_state),
                rolling_chart_expected,
                rolling_chart_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("cash_flow.chart.monthly_points", view_state),
                "view_state": view_state,
                "expected": rolling_chart_expected,
                "actual": rolling_chart_actual,
            })

            transactions_expected = raw_transactions_page(conn, owner_id=owner_id, limit=1000)
            transactions_api = _api_get(_api_path("/api/transactions?limit=1000", owner_id))
            transactions_rows = transactions_api.get("transactions") or []
            transactions_actual = {
                "row_amounts": [
                    _round2(tx.get("signed_amount") if tx.get("signed_amount") is not None else tx.get("amount"))
                    for tx in transactions_rows[:25]
                ],
                "row_dates": [tx.get("posting_date") for tx in transactions_rows[:25]],
                "filtered_count": len(transactions_rows),
                "total_count": transactions_api.get("total_count"),
                "range_start": 1 if transactions_rows[:25] else 0,
                "range_end": min(25, len(transactions_rows)),
                "active_filter_count": 0,
                "recent_amounts": [
                    _round2(tx.get("signed_amount") if tx.get("signed_amount") is not None else tx.get("amount"))
                    for tx in transactions_rows
                ],
            }
            _compare(
                _scoped_id("transactions.table", view_state),
                transactions_expected,
                transactions_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("transactions.table", view_state),
                "view_state": view_state,
                "expected": transactions_expected,
                "actual": transactions_actual,
            })

            reports_start = start
            reports_end = ref.isoformat()
            reports_flow_expected = raw_reports_flow(
                conn,
                reports_start,
                reports_end,
                owner_id=owner_id,
            )
            reports_flow_api = _api_get(_api_path(
                f"/api/reports/flow?start_date={reports_start}&end_date={reports_end}",
                owner_id,
            ))
            reports_flow_actual = {
                "total_income": reports_flow_api.get("total_income"),
                "total_spending": reports_flow_api.get("total_spending"),
                "net": reports_flow_api.get("net"),
                "savings_rate": reports_flow_api.get("savings_rate"),
                "bucket_totals": reports_flow_api.get("bucket_totals"),
                "bucket_totals_cents": reports_flow_api.get("bucket_totals_cents"),
                "bucket_percents": {
                    key: round((value / sum((reports_flow_api.get("bucket_totals") or {}).values())) * 100, 1)
                    if sum((reports_flow_api.get("bucket_totals") or {}).values())
                    else 0.0
                    for key, value in (reports_flow_api.get("bucket_totals") or {}).items()
                },
                "total_inflow_cents": reports_flow_api.get("total_inflow_cents"),
                "bucket_invariant_drift_cents": reports_flow_api.get("bucket_invariant_drift_cents"),
                "bypass_flows": reports_flow_api.get("bypass_flows") or [],
                "debt_service": reports_flow_api.get("debt_service"),
                "debt_accumulated": reports_flow_api.get("debt_accumulated"),
                "debt_paid_down": reports_flow_api.get("debt_paid_down"),
                "net_debt_change": reports_flow_api.get("net_debt_change"),
            }
            _compare(
                _scoped_id("reports.flow", view_state),
                reports_flow_expected,
                reports_flow_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("reports.flow", view_state),
                "view_state": view_state,
                "expected": reports_flow_expected,
                "actual": reports_flow_actual,
            })

            accountability_expected = raw_accountability(
                conn,
                reports_start,
                reports_end,
                owner_id=owner_id,
            )
            accountability_api = _api_get(_api_path(
                f"/api/reports/accountability?start_date={reports_start}&end_date={reports_end}",
                owner_id,
            ))
            accountability_actual = {
                "start_date": accountability_api.get("start_date"),
                "end_date": accountability_api.get("end_date"),
                "net_worth_start_cents": accountability_api.get("net_worth_start_cents"),
                "net_worth_end_cents": accountability_api.get("net_worth_end_cents"),
                "net_worth_delta_cents": accountability_api.get("net_worth_delta_cents"),
                "identity_terms": accountability_api.get("identity_terms"),
                "unexplained_cents": accountability_api.get("unexplained_cents"),
                "accounted_for_pct": accountability_api.get("accounted_for_pct"),
                "drift_source_count": len(accountability_api.get("drift_sources") or []),
            }
            _compare(
                _scoped_id("reports.accountability", view_state),
                accountability_expected,
                accountability_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("reports.accountability", view_state),
                "view_state": view_state,
                "expected": accountability_expected,
                "actual": accountability_actual,
            })

            reports_transactions_expected = raw_transactions_page(
                conn,
                owner_id=owner_id,
                limit=1000,
                start_date=reports_start,
                end_date=reports_end,
            )["recent_amounts"]
            reports_tx_api = _api_get(_api_path(
                f"/api/transactions?limit=1000&start_date={reports_start}&end_date={reports_end}",
                owner_id,
            ))
            reports_transactions_actual = [
                _round2(tx.get("signed_amount") if tx.get("signed_amount") is not None else tx.get("amount"))
                for tx in reports_tx_api.get("transactions") or []
            ]
            _compare(
                _scoped_id("reports.transactions.visible", view_state),
                reports_transactions_expected,
                reports_transactions_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("reports.transactions.visible", view_state),
                "view_state": view_state,
                "expected": reports_transactions_expected,
                "actual": reports_transactions_actual,
            })

            accounts_expected = raw_accounts_snapshot(conn, owner_id=owner_id)
            accounts_history = raw_net_worth_history(conn, ref, months=6, owner_id=owner_id)
            accounts_expected["display_total"] = accounts_history[-1]["net_worth"] if accounts_history else 0.0
            if len(accounts_history) >= 2 and accounts_history[0]["net_worth"]:
                accounts_expected["trend_percent"] = round(
                    ((accounts_history[-1]["net_worth"] - accounts_history[0]["net_worth"])
                     / abs(accounts_history[0]["net_worth"]))
                    * 100,
                    1,
                )
            else:
                accounts_expected["trend_percent"] = 0.0
            accounts_expected["data_through"] = None

            accounts_api = _api_get(_api_path("/api/accounts", owner_id))
            accounts_api_history = _api_get(_api_path("/api/reports/net-worth-history?months=6", owner_id)).get("history") or []
            accounts_actual = accounts_snapshot_from_api(accounts_api)
            accounts_actual["display_total"] = accounts_api_history[-1].get("net_worth") if accounts_api_history else 0.0
            if len(accounts_api_history) >= 2 and accounts_api_history[0].get("net_worth"):
                accounts_actual["trend_percent"] = round(
                    ((accounts_api_history[-1].get("net_worth") - accounts_api_history[0].get("net_worth"))
                     / abs(accounts_api_history[0].get("net_worth")))
                    * 100,
                    1,
                )
            else:
                accounts_actual["trend_percent"] = 0.0
            accounts_actual["data_through"] = None
            _compare(
                _scoped_id("accounts.snapshot", view_state),
                accounts_expected,
                accounts_actual,
                diffs,
            )
            checks.append({
                "id": _scoped_id("accounts.snapshot", view_state),
                "view_state": view_state,
                "expected": accounts_expected,
                "actual": accounts_actual,
            })

        covered_check_ids = {
            check["id"].split("@", 1)[0]
            for check in checks
            if not check["id"].startswith("runtime_context")
            and not check["id"].startswith("registry.view_state@")
        }
        _compare(
            "registry.api_oracle.check_ids_covered",
            sorted(_registry_check_ids(registry)),
            sorted(covered_check_ids & _registry_check_ids(registry)),
            diffs,
            classification="lineage/docs drift",
        )

        second_language_oracle = _run_second_language_oracle(db_path)
        _compare_second_language_oracle(second_language_oracle, checks, diffs)

        registered_contexts = _registry_value_contexts(registry)
        api_oracle_contexts = _registry_value_contexts(registry, audit_stage="api_oracle")
        pending_contexts = _registry_value_contexts(registry, audit_stage="registered_pending")
        return {
            "seed_version": manifest.get("seed_version"),
            "database_fingerprint": manifest.get("database_fingerprint"),
            "reference_date": manifest.get("reference_date"),
            "registry": {
                "path": str(REGISTRY_PATH),
                "version": registry.get("version"),
                "value_contexts": registered_contexts,
                "api_oracle_value_contexts": api_oracle_contexts,
                "registered_pending_value_contexts": pending_contexts,
                "view_states": view_states,
            },
            "second_language_oracle": second_language_oracle,
            "runtime_context": runtime_context,
            "diff_count": len(diffs),
            "diffs": diffs,
            "checks": checks,
        }
    finally:
        conn.close()


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_DIR / f"number-trust-{stamp}.json"
    md_path = REPORT_DIR / f"number-trust-{stamp}.md"
    json_path.write_text(json.dumps(_report_artifact_payload(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Number Trust Audit",
        "",
        f"- Seed version: `{report['seed_version']}`",
        f"- Reference date: `{report['reference_date']}`",
        f"- Database fingerprint: `{report['database_fingerprint']}`",
        f"- Runtime contract: `{report['runtime_context']['contract_version']}`",
        f"- Runtime DB path: `{report['runtime_context']['database']['path']}`",
        f"- Runtime clock source: `{report['runtime_context']['clock']['source']}`",
        f"- Trusted seed ready: `{report['runtime_context']['proof']['trusted_seed_ready']}`",
        f"- Registry registered value/view contexts: `{len(report['registry']['value_contexts'])}`",
        f"- API/oracle audited value/view contexts: `{len(report['registry']['api_oracle_value_contexts'])}`",
        f"- Registry-only pending value/view contexts: `{len(report['registry']['registered_pending_value_contexts'])}`",
        f"- Second-language oracle: `{report['second_language_oracle'].get('oracle_version', 'unavailable')}`",
        f"- Second-language checks: `{report['second_language_oracle'].get('check_count', 0)}`",
        f"- Diff count: `{report['diff_count']}`",
        "",
        "## Owner/View States",
        "",
    ]
    for state in report["registry"]["view_states"]:
        lines.append(
            f"- `{state['id']}`: view `{state['view']}`, owner `{state['owner_id']}`, "
            f"expected state `{state['expected_state']}`"
        )
    lines.append("")
    if report["diffs"]:
        lines.append("## Diffs")
        lines.append("")
        for diff in report["diffs"]:
            lines.extend([
                f"### {diff['id']}",
                "",
                f"- Classification: `{diff['classification']}`",
                f"- Expected: `{diff['expected']}`",
                f"- Actual: `{diff['actual']}`",
                "",
            ])
    else:
        lines.append("No diffs found.")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def _report_artifact_payload(report: dict[str, Any]) -> dict[str, Any]:
    """Return a commit-safe proof artifact without the full value dump.

    The audit still compares full expected/actual payloads in memory. The
    committed JSON artifact keeps diff payloads, registry/runtime proof, and
    check identities, but omits passing checks' values so synthetic amounts do
    not false-positive against real last-4 PII values.
    """
    payload = dict(report)
    payload["checks"] = [
        {
            "id": check.get("id"),
            "view_state": check.get("view_state"),
        }
        for check in report.get("checks") or []
    ]
    second_language = dict(report.get("second_language_oracle") or {})
    second_language["checks"] = [
        {
            "id": check.get("id"),
            "view_state": check.get("view_state"),
        }
        for check in second_language.get("checks") or []
    ]
    payload["second_language_oracle"] = second_language
    payload["artifact_policy"] = "passing_check_values_omitted"
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit UI numbers against raw trusted-seed facts")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()
    db_path = args.db
    if db_path is None and os.environ.get("SENTRY_DB_PATH"):
        db_path = Path(os.environ["SENTRY_DB_PATH"])
    if db_path is None:
        parser.error("--db or SENTRY_DB_PATH is required; there is no implicit audit database")
    report = run(db_path)
    json_path, md_path = write_reports(report)
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    print(f"Diff count: {report['diff_count']}")
    return 1 if report["diff_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
