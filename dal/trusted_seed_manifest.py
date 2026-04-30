"""Trusted synthetic seed manifest and live fingerprint helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime
from typing import Any


TRUSTED_MANIFEST_TABLES = [
    "owners",
    "institutions",
    "institution_refresh_status",
    "accounts",
    "transactions",
    "balance_snapshots",
    "budgets",
    "recurring_transactions",
    "recurring_mutations",
    "savings_goals",
    "loan_details",
    "investment_holdings",
    "portfolio_snapshots",
    "positions_ledger",
    "benchmark_prices",
    "ticker_metadata",
    "tax_buckets",
    "fund_composition",
    "fund_sector_weights",
    "credit_scores",
    "real_estate",
    "vehicle_assets",
    "vehicle_valuations",
    "apy_history",
    "investment_details",
    "payroll_snapshots",
    "income_sources",
    "loan_payment_splits",
    "derived_summaries",
    "alert_rules",
    "alert_events",
    "notifications",
]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [row["name"] for row in conn.execute(f"PRAGMA table_info([{table}])").fetchall()]
    except Exception:
        return []


def fingerprint_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        info = conn.execute(f"PRAGMA table_info([{table}])").fetchall()
    except Exception:
        return []
    cols: list[str] = []
    for row in info:
        name = row["name"]
        col_type = (row["type"] or "").upper()
        is_pk = int(row["pk"] or 0) > 0
        if name == "id" and is_pk and "INT" in col_type:
            continue
        cols.append(name)
    return cols


def normalized_table_fingerprint(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    cols = fingerprint_columns(conn, table)
    if not cols:
        return {"row_count": 0, "sha256": None}
    order_cols = ", ".join(f"[{c}]" for c in cols)
    rows = conn.execute(f"SELECT {order_cols} FROM [{table}] ORDER BY {order_cols}").fetchall()
    normalized = [{col: row[col] for col in cols} for row in rows]
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "row_count": len(normalized),
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def live_seed_fingerprint(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = {
        table: normalized_table_fingerprint(conn, table)
        for table in TRUSTED_MANIFEST_TABLES
        if table_exists(conn, table)
    }
    all_table_hashes = {
        table: info["sha256"]
        for table, info in tables.items()
        if info["sha256"] is not None
    }
    database_fingerprint = hashlib.sha256(
        json.dumps(all_table_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "database_fingerprint": database_fingerprint,
        "row_counts": {table: info["row_count"] for table, info in tables.items()},
        "fingerprints": {table: info["sha256"] for table, info in tables.items()},
    }


def build_seed_manifest(
    conn: sqlite3.Connection,
    *,
    seed_version: str,
    end_date: date,
    reference_date: date,
    reference_datetime: datetime,
    years: int,
) -> dict[str, Any]:
    live = live_seed_fingerprint(conn)
    return {
        "seed_version": seed_version,
        "end_date": end_date.isoformat(),
        "reference_date": reference_date.isoformat(),
        "reference_datetime": reference_datetime.isoformat(),
        "years": years,
        "generated_at": reference_datetime.isoformat(),
        "row_counts": live["row_counts"],
        "fingerprints": live["fingerprints"],
        "database_fingerprint": live["database_fingerprint"],
    }


def load_manifest(conn: sqlite3.Connection) -> dict[str, Any] | None:
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'trusted_seed_manifest'"
        ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        return json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return None
