"""Investment-details key-value persistence and retrieval.

Schema lives in ``dal/migrations/v41_investment_details.py``. This
module is the only write path; invariants (ISO-8601 ``as_of`` dates,
non-empty ``field_name``, optional uppercase ``fund_ticker``) are
enforced here so violations fail fast — same convention as
``dal/apy_history.py``.

Phase 15-T09 captures three field families:

* Account-level (``fund_ticker IS NULL``): Acorns ``round_up_ytd``,
  ``round_up_lifetime``.
* Fund-level (``fund_ticker = 'SPAXX'`` or ETF / TSP fund symbol):
  ``sec_yield``, ``ytd_return``, optional ``fund_name``.

Values are stored as the raw scraped string (``"4.32%"``,
``"+12.4%"``, ``"$2,580.00"``); rendering / coercion happens in the
frontend ``formatDetailField`` dispatcher and downstream consumers.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Optional

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,11}$")


def _assert_row_valid(
    field_name: str,
    as_of: str,
    fund_ticker: Optional[str],
) -> None:
    """Fail-fast guard for ``record_investment_details``.

    Empty field names, non-ISO dates, and lowercase / oversized
    tickers all indicate a connector bug rather than valid data.
    Raising early keeps junk rows out of the time series.
    """
    if not isinstance(field_name, str) or not field_name.strip():
        raise ValueError(
            f"investment_details.field_name {field_name!r} must be a "
            f"non-empty string. as_of={as_of!r} fund_ticker={fund_ticker!r}"
        )
    if not isinstance(as_of, str) or not _ISO_DATE_RE.match(as_of):
        raise ValueError(
            f"investment_details.as_of {as_of!r} is not an ISO-8601 "
            f"date (YYYY-MM-DD). field_name={field_name!r}"
        )
    if fund_ticker is not None:
        if not isinstance(fund_ticker, str) or not _TICKER_RE.match(fund_ticker):
            raise ValueError(
                f"investment_details.fund_ticker {fund_ticker!r} must be "
                f"uppercase alphanumeric (≤10 chars) or None. "
                f"field_name={field_name!r}"
            )


def record_investment_details(
    conn: sqlite3.Connection,
    account_id: str,
    fields: dict[str, str],
    *,
    fund_ticker: Optional[str] = None,
    as_of: str,
    refresh_run_id: Optional[int] = None,
) -> int:
    """Insert one batch of (field_name → field_value) rows.

    The unique index ``(account_id, COALESCE(fund_ticker,''),
    field_name, refresh_run_id)`` makes this an INSERT-OR-IGNORE on
    repeat calls within the same refresh.

    **Caller commits** — this function never calls ``conn.commit()``,
    matching the P17-T03 wrapper convention.

    Returns the count of newly inserted rows.
    """
    inserted = 0
    for field_name, field_value in fields.items():
        if field_value is None or field_value == "":
            continue
        _assert_row_valid(field_name, as_of, fund_ticker)
        cur = conn.execute(
            """INSERT OR IGNORE INTO investment_details
                 (account_id, fund_ticker, field_name, field_value,
                  as_of, refresh_run_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                account_id,
                fund_ticker,
                field_name,
                str(field_value),
                as_of,
                refresh_run_id,
            ),
        )
        if cur.rowcount > 0:
            inserted += 1
    return inserted


def get_latest_investment_details(
    conn: sqlite3.Connection,
    account_id: str,
) -> dict:
    """Return the latest-per-(fund_ticker, field_name) snapshot for an account.

    Shape::

        {
          "account_level": {field_name: {"value": str, "as_of": str}},
          "funds": {
            ticker: {field_name: {"value": str, "as_of": str}},
            ...
          },
        }

    "Latest" is max(as_of), ties broken by max(id). Fund tickers
    appear in the order they were first inserted (sqlite preserves
    insertion order for the same as_of).
    """
    rows = conn.execute(
        """SELECT fund_ticker, field_name, field_value, as_of, id
           FROM investment_details
           WHERE account_id = ?
           ORDER BY as_of DESC, id DESC""",
        (account_id,),
    ).fetchall()

    account_level: dict[str, dict] = {}
    funds: dict[str, dict[str, dict]] = {}
    for r in rows:
        ticker = r["fund_ticker"]
        bucket = (
            account_level
            if ticker is None
            else funds.setdefault(ticker, {})
        )
        if r["field_name"] in bucket:
            continue  # already saw a newer row
        bucket[r["field_name"]] = {
            "value": r["field_value"],
            "as_of": r["as_of"],
        }

    return {"account_level": account_level, "funds": funds}


def get_investment_field_history(
    conn: sqlite3.Connection,
    account_id: str,
    field_name: str,
    *,
    fund_ticker: Optional[str] = None,
    months: Optional[int] = None,
) -> list[dict]:
    """Return chronologically-ordered rows for one (account, fund, field).

    Useful for a future ``returnTrend`` sparkline. Order is ascending
    so chart-style callers get oldest → newest without an extra reverse.
    """
    where = ["account_id = ?", "field_name = ?"]
    params: list = [account_id, field_name]
    if fund_ticker is None:
        where.append("fund_ticker IS NULL")
    else:
        where.append("fund_ticker = ?")
        params.append(fund_ticker)
    if months is not None:
        where.append("as_of >= date('now', ?)")
        params.append(f"-{months} months")
    rows = conn.execute(
        f"""SELECT id, account_id, fund_ticker, field_name,
                   field_value, as_of, created_at
            FROM investment_details
            WHERE {' AND '.join(where)}
            ORDER BY as_of ASC, id ASC""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]
