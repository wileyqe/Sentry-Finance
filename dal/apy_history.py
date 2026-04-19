"""APY time-series persistence and retrieval.

Schema lives in ``dal/migrations/v30_apy_history.py``. This module is the
only write path; invariants (``apy_rate ∈ [0, 100]``, ``source`` in the
three-value set, ISO-8601 dates) are enforced here so violations fail
fast with context in the stack trace — same convention as
``dal/credit_scores.py``.

APY rates are stored as percentage numbers (e.g. ``4.00`` for 4%), not
as fractions, to match how the UI renders them and how connectors emit
them.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Optional

_VALID_SOURCES = {"scrape", "manual", "statement"}
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_APY_STRING_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%?")


def _assert_apy_valid(apy_rate: float, as_of: str, source: str) -> None:
    """Fail-fast guard for ``record_apy_history``.

    ``apy_rate`` out of [0, 100], non-ISO dates, and sources outside the
    three-value set all indicate a scraper/caller bug rather than valid
    data. Raising early keeps bad rows out of the time series.
    """
    if not isinstance(apy_rate, (int, float)) or not (0.0 <= float(apy_rate) <= 100.0):
        raise ValueError(
            f"apy_history.apy_rate {apy_rate!r} outside valid [0, 100] range. "
            f"as_of={as_of!r} source={source!r}"
        )
    if not isinstance(as_of, str) or not _ISO_DATE_RE.match(as_of):
        raise ValueError(
            f"apy_history.as_of {as_of!r} is not an ISO-8601 date (YYYY-MM-DD). "
            f"apy_rate={apy_rate!r} source={source!r}"
        )
    if source not in _VALID_SOURCES:
        raise ValueError(
            f"apy_history.source {source!r} not in {sorted(_VALID_SOURCES)!r}. "
            f"apy_rate={apy_rate!r} as_of={as_of!r}"
        )


def parse_apy_string(value: str | float | int) -> float:
    """Coerce a scraped APY value like ``"4.00%"`` or ``0.250`` to a float.

    Connectors emit APY in two shapes — as a raw float (Affirm extracts
    it with ``float(match.group(1))``) or as a string like ``"0.250%"``
    (NFCU's generic loan-detail scraper returns whatever the page shows).
    This helper normalises both to a percent-scaled float.

    Raises ``ValueError`` if no numeric prefix is found.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise ValueError(f"apy_history: unsupported APY type {type(value).__name__}")
    match = _APY_STRING_RE.search(value)
    if not match:
        raise ValueError(f"apy_history: could not parse APY from {value!r}")
    return float(match.group(1))


def record_apy_history(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    apy_rate: float,
    as_of: str,
    source: str,
) -> bool:
    """Insert one APY row; no-op if ``(account_id, as_of, source)`` exists.

    Invariants enforced in ``_assert_apy_valid``. **Caller commits** —
    this function never calls ``conn.commit()``, matching the P17-T03
    wrapper convention (``dal.credit_scores.record_credit_score`` etc).

    Returns True if a new row was inserted, False if the unique index
    suppressed a duplicate.
    """
    _assert_apy_valid(apy_rate, as_of, source)

    cur = conn.execute(
        """INSERT OR IGNORE INTO apy_history
           (account_id, apy_rate, as_of, source)
           VALUES (?, ?, ?, ?)""",
        (account_id, float(apy_rate), as_of, source),
    )
    return cur.rowcount > 0


def get_latest_apy(
    conn: sqlite3.Connection,
    account_id: str,
) -> Optional[dict]:
    """Return the newest APY row for ``account_id``, or None if empty.

    "Newest" is max(as_of); ties break by max(id). Shape matches the
    direct table columns so callers can destructure without translation.
    """
    row = conn.execute(
        """SELECT id, account_id, apy_rate, as_of, source, created_at
           FROM apy_history
           WHERE account_id = ?
           ORDER BY as_of DESC, id DESC
           LIMIT 1""",
        (account_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def get_apy_history(
    conn: sqlite3.Connection,
    account_id: str,
    months: Optional[int] = None,
) -> list[dict]:
    """Return chronologically-ordered APY rows for one account.

    ``months`` restricts to the last N months via SQLite date arithmetic;
    ``None`` returns the full history. Order is ascending so chart-style
    callers get oldest → newest without an extra reverse.
    """
    if months is not None:
        rows = conn.execute(
            """SELECT id, account_id, apy_rate, as_of, source, created_at
               FROM apy_history
               WHERE account_id = ? AND as_of >= date('now', ?)
               ORDER BY as_of ASC, id ASC""",
            (account_id, f"-{months} months"),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, account_id, apy_rate, as_of, source, created_at
               FROM apy_history
               WHERE account_id = ?
               ORDER BY as_of ASC, id ASC""",
            (account_id,),
        ).fetchall()
    return [dict(r) for r in rows]
