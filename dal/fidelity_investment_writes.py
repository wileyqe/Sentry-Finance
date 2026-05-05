"""Fidelity-specific investment state writer.

The generic investment write wrappers own ``investment_holdings`` and
``portfolio_snapshots`` invariants. This module keeps Fidelity CSV mapping
rules close to the live source shape and uses those wrappers for the shared
tables. Caller commits.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import math
import sqlite3
from typing import Any

import pandas as pd

from dal.investments_writes import (
    record_investment_holdings,
    record_portfolio_snapshots,
)

CASH_EQUIVALENTS = {"SPAXX", "FDRXX"}
FIDELITY_LEDGER_SOURCE = "fidelity_live"
EFT_MARKER_TICKER = "CASH"

_SECURITY_ACTIONS = {
    "BOUGHT": "BUY",
    "REINVESTMENT": "REINVESTMENT",
    "SOLD": "SELL",
    "EXPIRED": "EXPIRED",
}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _float_or_none(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def _decimal_text(value: Any, places: str | None = None) -> str | None:
    numeric = _float_or_none(value)
    if numeric is None:
        return None
    try:
        dec = Decimal(str(numeric))
    except InvalidOperation:
        return None
    if places is not None:
        dec = dec.quantize(Decimal(places))
    return format(dec, "f")


def _iso_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)[:10]


def _optional_iso_date(value: Any) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    if isinstance(value, (date, datetime)) or hasattr(value, "date"):
        return _iso_date(value)

    parsed = pd.to_datetime(text, format="%m/%d/%Y", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return _iso_date(parsed)


def _snapshot_timestamp(value: Any) -> str:
    return f"{_iso_date(value)}T16:00:00"


def _ledger_timestamp(value: Any) -> str:
    return f"{_iso_date(value)}T09:00:00"


def _normalize_text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return " ".join(str(value).strip().split())


def _source_key(prefix: str, parts: list[Any], counters: dict[str, int]) -> str:
    base = "|".join(_normalize_text(part) for part in parts)
    ordinal = counters[base]
    counters[base] += 1
    digest = hashlib.sha256(f"{base}|{ordinal}".encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _validate_single_fidelity_account(positions: pd.DataFrame) -> None:
    if "Account Number" not in positions.columns:
        return
    account_numbers = {
        _normalize_text(value)
        for value in positions["Account Number"].dropna().tolist()
        if _normalize_text(value)
    }
    if len(account_numbers) > 1:
        raise ValueError(
            "Fidelity positions CSV contains multiple account numbers; "
            "single-account live writer cannot safely merge them."
        )


def _snapshot_tickers(snapshot: pd.DataFrame) -> list[str]:
    tickers = []
    for column in snapshot.columns:
        if not column.endswith("_Shares"):
            continue
        ticker = column.removesuffix("_Shares").upper()
        if ticker and ticker not in CASH_EQUIVALENTS:
            tickers.append(ticker)
    return sorted(tickers)


def _build_holdings(
    account_id: str,
    snapshot: pd.DataFrame,
    tickers: list[str],
) -> list[dict]:
    holdings: list[dict] = []
    for _, row in snapshot.iterrows():
        snap_date = _iso_date(row["Date"])
        for ticker in tickers:
            shares = _float_or_none(row.get(f"{ticker}_Shares")) or 0.0
            price = _float_or_none(row.get(f"{ticker}_ClosePrice"))
            market_value = _float_or_none(row.get(f"{ticker}_Value"))
            holdings.append(
                {
                    "account_id": account_id,
                    "date": snap_date,
                    "ticker": ticker,
                    "shares": shares,
                    "close_price": price,
                    "market_value": market_value,
                    "cost_basis": None,
                }
            )
    return holdings


def _build_snapshots(account_id: str, snapshot: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for _, row in snapshot.iterrows():
        rows.append(
            {
                "account_id": account_id,
                "timestamp": _snapshot_timestamp(row["Date"]),
                "total_account_value": _float_or_none(row["Total_Account_Value"])
                or 0.0,
                "cash_balance": _float_or_none(row.get("Cash_Balance")) or 0.0,
            }
        )
    return rows


def _first_snapshot_running_shares(
    snapshot: pd.DataFrame,
    tickers: list[str],
) -> dict[str, float]:
    if snapshot.empty:
        return {}
    first = snapshot.sort_values("Date").iloc[0]
    return {
        ticker: _float_or_none(first.get(f"{ticker}_Shares")) or 0.0
        for ticker in tickers
    }


def _build_baseline_rows(
    account_id: str,
    snapshot: pd.DataFrame,
    tickers: list[str],
    counters: dict[str, int],
) -> list[dict]:
    if snapshot.empty:
        return []
    first = snapshot.sort_values("Date").iloc[0]
    timestamp = _ledger_timestamp(first["Date"])
    rows: list[dict] = []
    for ticker in tickers:
        shares = _float_or_none(first.get(f"{ticker}_Shares")) or 0.0
        if abs(shares) <= 1e-12:
            continue
        price = _float_or_none(first.get(f"{ticker}_ClosePrice"))
        value = _float_or_none(first.get(f"{ticker}_Value"))
        rows.append(
            {
                "account_id": account_id,
                "timestamp": timestamp,
                "ticker": ticker,
                "transaction_type": "INITIAL_BASELINE",
                "share_delta": shares,
                "new_total_shares": shares,
                "yfinance_closing_price": price,
                "estimated_transaction_value": value,
                "share_delta_dec": _decimal_text(shares),
                "new_total_shares_dec": _decimal_text(shares),
                "close_price_dec": _decimal_text(price),
                "txn_value_dec": _decimal_text(value, "0.01"),
                "source": FIDELITY_LEDGER_SOURCE,
                "bank_txn_id": None,
                "cost_basis_dec": None,
                "realized_gain_dec": None,
                "settlement_date": None,
                "commission_dec": None,
                "fees_dec": None,
                "source_key": _source_key(
                    "fidelity-baseline",
                    [account_id, timestamp, ticker, shares],
                    counters,
                ),
            }
        )
    return rows


def _build_history_ledger_rows(
    account_id: str,
    history: pd.DataFrame,
    snapshot: pd.DataFrame,
    tickers: list[str],
    counters: dict[str, int],
) -> list[dict]:
    running = _first_snapshot_running_shares(snapshot, tickers)
    rows: list[dict] = []
    sorted_history = history.sort_values("Run Date").reset_index(drop=True)

    for _, row in sorted_history.iterrows():
        action = _normalize_text(row.get("Action_Type")).upper()
        symbol = _normalize_text(row.get("Symbol")).upper()
        quantity = _float_or_none(row.get("Quantity")) or 0.0
        amount = _float_or_none(row.get("Amount ($)")) or 0.0
        timestamp = _ledger_timestamp(row["Run Date"])
        settlement = _optional_iso_date(row.get("Settlement Date"))

        if action in {"DEPOSIT", "WITHDRAWAL"}:
            rows.append(
                {
                    "account_id": account_id,
                    "timestamp": timestamp,
                    "ticker": EFT_MARKER_TICKER,
                    "transaction_type": action,
                    "share_delta": 0.0,
                    "new_total_shares": 0.0,
                    "yfinance_closing_price": None,
                    "estimated_transaction_value": amount,
                    "share_delta_dec": "0",
                    "new_total_shares_dec": "0",
                    "close_price_dec": None,
                    "txn_value_dec": _decimal_text(amount, "0.01"),
                    "source": FIDELITY_LEDGER_SOURCE,
                    "bank_txn_id": None,
                    "cost_basis_dec": None,
                    "realized_gain_dec": None,
                    "settlement_date": settlement,
                    "commission_dec": _decimal_text(row.get("Commission ($)"), "0.01"),
                    "fees_dec": _decimal_text(row.get("Fees ($)"), "0.01"),
                    "source_key": _source_key(
                        "fidelity-eft",
                        [
                            account_id,
                            timestamp,
                            action,
                            row.get("Action"),
                            amount,
                            row.get("Cash Balance ($)"),
                        ],
                        counters,
                    ),
                }
            )
            continue

        if action not in _SECURITY_ACTIONS:
            continue
        if not symbol or symbol in CASH_EQUIVALENTS:
            continue
        if symbol not in running:
            running[symbol] = 0.0

        if action in {"BOUGHT", "REINVESTMENT"}:
            share_delta = quantity
        elif action in {"SOLD", "EXPIRED"}:
            share_delta = -quantity
        else:
            share_delta = 0.0

        running[symbol] += share_delta
        price = _float_or_none(row.get("Price ($)"))
        value = 0.0 if action == "EXPIRED" else abs(amount)
        rows.append(
            {
                "account_id": account_id,
                "timestamp": timestamp,
                "ticker": symbol,
                "transaction_type": _SECURITY_ACTIONS[action],
                "share_delta": share_delta,
                "new_total_shares": running[symbol],
                "yfinance_closing_price": price,
                "estimated_transaction_value": value,
                "share_delta_dec": _decimal_text(share_delta),
                "new_total_shares_dec": _decimal_text(running[symbol]),
                "close_price_dec": _decimal_text(price),
                "txn_value_dec": _decimal_text(value, "0.01"),
                "source": FIDELITY_LEDGER_SOURCE,
                "bank_txn_id": None,
                "cost_basis_dec": None,
                "realized_gain_dec": None,
                "settlement_date": settlement,
                "commission_dec": _decimal_text(row.get("Commission ($)"), "0.01"),
                "fees_dec": _decimal_text(row.get("Fees ($)"), "0.01"),
                "source_key": _source_key(
                    "fidelity-row",
                    [
                        account_id,
                        timestamp,
                        action,
                        symbol,
                        row.get("Action"),
                        quantity,
                        amount,
                        settlement,
                    ],
                    counters,
                ),
            }
        )

    return rows


def _upsert_positions_ledger(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0

    changed = 0
    for row in rows:
        existing = conn.execute(
            """SELECT id, bank_txn_id
               FROM positions_ledger
               WHERE account_id = ? AND source = ? AND source_key = ?""",
            (row["account_id"], row["source"], row["source_key"]),
        ).fetchone()
        params = (
            row["account_id"],
            row["timestamp"],
            row["ticker"],
            row["transaction_type"],
            row["share_delta"],
            row["new_total_shares"],
            row["yfinance_closing_price"],
            row["estimated_transaction_value"],
            row["share_delta_dec"],
            row["new_total_shares_dec"],
            row["close_price_dec"],
            row["txn_value_dec"],
            row["source"],
            row["cost_basis_dec"],
            row["realized_gain_dec"],
            row["settlement_date"],
            row["commission_dec"],
            row["fees_dec"],
            row["source_key"],
        )
        if existing is None:
            conn.execute(
                """INSERT INTO positions_ledger
                   (account_id, timestamp, ticker, transaction_type,
                    share_delta, new_total_shares, yfinance_closing_price,
                    estimated_transaction_value, share_delta_dec,
                    new_total_shares_dec, close_price_dec, txn_value_dec,
                    source, bank_txn_id, cost_basis_dec, realized_gain_dec,
                    settlement_date, commission_dec, fees_dec, source_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL,
                           ?, ?, ?, ?, ?, ?)""",
                params,
            )
        else:
            conn.execute(
                """UPDATE positions_ledger
                   SET account_id = ?,
                       timestamp = ?,
                       ticker = ?,
                       transaction_type = ?,
                       share_delta = ?,
                       new_total_shares = ?,
                       yfinance_closing_price = ?,
                       estimated_transaction_value = ?,
                       share_delta_dec = ?,
                       new_total_shares_dec = ?,
                       close_price_dec = ?,
                       txn_value_dec = ?,
                       source = ?,
                       cost_basis_dec = ?,
                       realized_gain_dec = ?,
                       settlement_date = ?,
                       commission_dec = ?,
                       fees_dec = ?,
                       source_key = ?
                   WHERE id = ?""",
                (*params, existing["id"]),
            )
        changed += 1
    return changed


def _replace_portfolio_snapshots(
    conn: sqlite3.Connection,
    account_id: str,
    snapshots: list[dict],
) -> None:
    for row in snapshots:
        conn.execute(
            "DELETE FROM portfolio_snapshots WHERE account_id = ? AND timestamp = ?",
            (account_id, row["timestamp"]),
        )


def write_fidelity_investment_state(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    history: pd.DataFrame,
    positions: pd.DataFrame,
    snapshot: pd.DataFrame,
) -> dict[str, int]:
    """Persist reconstructed Fidelity live investment state.

    Writes position-state rows only: holdings, account snapshots, security
    ledger activity, and zero-share EFT marker rows. It intentionally does
    not create bank-side transactions or claim dividend/cost-basis truth.
    """
    if snapshot.empty:
        return {
            "holdings": 0,
            "snapshots": 0,
            "ledger_rows": 0,
        }

    _validate_single_fidelity_account(positions)
    tickers = _snapshot_tickers(snapshot)
    counters: dict[str, int] = defaultdict(int)

    holdings = _build_holdings(account_id, snapshot, tickers)
    snapshots = _build_snapshots(account_id, snapshot)
    ledger_rows = _build_baseline_rows(account_id, snapshot, tickers, counters)
    ledger_rows.extend(
        _build_history_ledger_rows(account_id, history, snapshot, tickers, counters)
    )

    holding_result = record_investment_holdings(conn, holdings)
    _replace_portfolio_snapshots(conn, account_id, snapshots)
    snapshot_result = record_portfolio_snapshots(conn, snapshots)
    ledger_count = _upsert_positions_ledger(conn, ledger_rows)

    return {
        "holdings": holding_result["inserted_or_replaced"],
        "snapshots": snapshot_result["inserted"],
        "ledger_rows": ledger_count,
    }
