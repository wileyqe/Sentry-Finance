"""Fidelity dividend and capital-gain income writer.

Converts parsed DIVIDEND and CAP GAIN history rows into posted cash
transactions with ``category='Investment Income'``, routed through
``dal.transactions.upsert_transactions()``.

Design contract (P17-T29):
  - Positive signed_amount, direction='Credit', no transfer_tag.
  - Run Date as posting_date / transaction_date.
  - Ticker-first description for reinvestment matcher pairing.
  - Original Fidelity action text preserved in raw_description.
  - Deterministic institution_txn_id for idempotent reruns.
  - SPAXX/FDRXX dividend income written as cash-equivalent; no illiquid
    reinvestment flow created.
  - Rows with missing Run Date or non-positive amount are skipped.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from collections import defaultdict
from typing import Any

import pandas as pd

from dal.transactions import upsert_transactions

log = logging.getLogger("sentry.dal.fidelity_dividend_income")

FIDELITY_INSTITUTION_ID = "fidelity"

# Fidelity action substrings → normalized action keys for descriptions
# and institution_txn_id generation.
_ACTION_MAP: list[tuple[str, str, str]] = [
    # (substring to match, normalized_action for txn_id, description suffix)
    ("LONG-TERM CAP GAIN", "LONG_TERM_CAP_GAIN", "LONG-TERM CAP GAIN"),
    ("SHORT-TERM CAP GAIN", "SHORT_TERM_CAP_GAIN", "SHORT-TERM CAP GAIN"),
    ("CAP GAIN", "CAP_GAIN", "CAP GAIN"),
    ("DIVIDEND RECEIVED", "DIVIDEND", "DIVIDEND"),
]


def _classify_income_action(raw_action: str) -> tuple[str, str] | None:
    """Return (normalized_action, description_suffix) or None if not income."""
    upper = raw_action.upper()
    for substring, norm_action, desc_suffix in _ACTION_MAP:
        if substring in upper:
            return norm_action, desc_suffix
    return None


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


def _parse_run_date(value: Any) -> str | None:
    """Parse Run Date to ISO format, returning None on failure."""
    if _is_missing(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    text = str(value).strip()
    if not text:
        return None
    parsed = pd.to_datetime(text, format="%m/%d/%Y", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _extract_symbol(row: pd.Series) -> str:
    """Extract ticker symbol from the row."""
    sym = row.get("Symbol")
    if _is_missing(sym):
        return ""
    return str(sym).strip().upper()


def _build_institution_txn_id(
    account_id: str,
    posting_date: str,
    symbol: str,
    amount_cents: int,
    normalized_action: str,
    same_day_sequence: int,
) -> str:
    """Build deterministic institution_txn_id for idempotent upserts."""
    parts = [
        "fidelity-income",
        account_id,
        posting_date,
        symbol,
        str(amount_cents),
        normalized_action,
    ]
    if same_day_sequence > 0:
        parts.append(str(same_day_sequence))
    return ":".join(parts)


def write_fidelity_dividend_income(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    history: pd.DataFrame,
) -> dict:
    """Convert Fidelity dividend/cap-gain rows into Investment Income transactions.

    Args:
        conn: Database connection (caller commits).
        account_id: Fidelity brokerage account_id.
        history: Parsed Fidelity history DataFrame with columns including
            Action, Action_Type, Symbol, Amount ($), Run Date.

    Returns:
        Structured summary dict with counts for written, unchanged,
        skipped_missing_date, skipped_non_positive_amount, and
        skipped_unsupported.
    """
    summary = {
        "written": 0,
        "unchanged": 0,
        "skipped_missing_date": 0,
        "skipped_non_positive_amount": 0,
        "skipped_unsupported": 0,
    }

    if history.empty:
        return summary

    # Filter to dividend/cap-gain rows only
    dividend_rows = history[history["Action_Type"].eq("DIVIDEND")].copy()
    if dividend_rows.empty:
        return summary

    # Stable ordering makes same-day duplicate sequence assignment deterministic
    # across reruns, even if caller row order changes.
    sort_cols = [
        col for col in ("Run Date", "Symbol", "Amount ($)", "Action")
        if col in dividend_rows.columns
    ]
    if sort_cols:
        dividend_rows = dividend_rows.sort_values(
            by=sort_cols, kind="mergesort", na_position="last"
        )

    # Track same-day sequences for dedup
    sequence_counters: dict[str, int] = defaultdict(int)
    txns_to_write: list[dict] = []

    for _, row in dividend_rows.iterrows():
        raw_action = str(row.get("Action", ""))
        classification = _classify_income_action(raw_action)
        if classification is None:
            summary["skipped_unsupported"] += 1
            log.debug("Skipping unsupported action: %s", raw_action)
            continue

        normalized_action, desc_suffix = classification

        # Validate Run Date
        posting_date = _parse_run_date(row.get("Run Date"))
        if posting_date is None:
            summary["skipped_missing_date"] += 1
            log.warning(
                "Skipping dividend row with missing/unparseable Run Date: %s",
                raw_action,
            )
            continue

        # Validate amount
        amount = _float_or_none(row.get("Amount ($)"))
        if amount is None or amount <= 0:
            summary["skipped_non_positive_amount"] += 1
            log.warning(
                "Skipping dividend row with non-positive amount (%.2f): %s",
                amount or 0.0,
                raw_action,
            )
            continue

        symbol = _extract_symbol(row)
        amount_cents = round(amount * 100)

        # Build same-day sequence key
        seq_key = f"{posting_date}:{symbol}:{amount_cents}:{normalized_action}"
        same_day_seq = sequence_counters[seq_key]
        sequence_counters[seq_key] += 1

        institution_txn_id = _build_institution_txn_id(
            account_id, posting_date, symbol, amount_cents, normalized_action,
            same_day_seq,
        )

        # Build description: ticker-first for reinvestment matcher pairing
        description = f"{symbol} {desc_suffix}" if symbol else desc_suffix

        txns_to_write.append({
            "account_id": account_id,
            "institution_id": FIDELITY_INSTITUTION_ID,
            "posting_date": posting_date,
            "transaction_date": posting_date,
            "amount": amount,
            "signed_amount": amount,  # positive Credit
            "direction": "Credit",
            "description": description,
            "raw_description": raw_action,
            "category": "Investment Income",
            "status": "posted",
            "institution_txn_id": institution_txn_id,
        })

    if not txns_to_write:
        return summary

    result = upsert_transactions(conn, txns_to_write)
    summary["written"] = result.get("inserted", 0)
    summary["unchanged"] = result.get("unchanged", 0) + result.get("updated", 0)

    log.info(
        "Fidelity dividend income: %d written, %d unchanged, "
        "%d skipped (date: %d, amount: %d, unsupported: %d)",
        summary["written"],
        summary["unchanged"],
        summary["skipped_missing_date"]
        + summary["skipped_non_positive_amount"]
        + summary["skipped_unsupported"],
        summary["skipped_missing_date"],
        summary["skipped_non_positive_amount"],
        summary["skipped_unsupported"],
    )
    return summary
