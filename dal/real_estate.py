"""
dal/real_estate.py — Write wrappers for the ``real_estate`` table.

The ``real_estate`` table is append-only time-series: each row is a
``(name, as_of)`` valuation anchored to an owner. The seeder wraps
writes with its own ``DELETE FROM real_estate`` to rebuild the window;
real connectors will append over time.

Part of the Phase-17 parity pass: seeder and live connectors share one
validated write path, mirroring the ``dal.transactions.upsert_transactions``
choke-point pattern. Caller commits.
"""

import sqlite3
from datetime import datetime
from typing import Optional


_VALID_ISO_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


def _parse_as_of(as_of: str) -> None:
    """Fail fast if ``as_of`` is not a recognizable ISO date/time."""
    for fmt in _VALID_ISO_DATE_FORMATS:
        try:
            datetime.strptime(as_of, fmt)
            return
        except (ValueError, TypeError):
            continue
    raise ValueError(
        f"real_estate.as_of {as_of!r} is not a parseable ISO date "
        f"(expected YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)."
    )


def _assert_real_estate_invariant(row: dict) -> None:
    """Pre-write guard for ``record_real_estate_valuations``.

    Raises ``ValueError`` naming the offending row on violation.
    """
    for key in ("name", "estimated_value", "as_of"):
        if key not in row:
            raise ValueError(
                f"real_estate row missing required key {key!r}: {row!r}"
            )

    value = row["estimated_value"]
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(
            f"real_estate.estimated_value must be > 0, got {value!r}. "
            f"name={row['name']!r} as_of={row['as_of']!r}"
        )

    _parse_as_of(row["as_of"])


def record_real_estate_valuations(
    conn: sqlite3.Connection,
    rows: list[dict],
) -> dict:
    """Insert a batch of ``real_estate`` valuation rows.

    Each dict must contain: ``name``, ``estimated_value``, ``as_of``.
    Optional keys: ``linked_loan_id``, ``source`` (default ``'manual'``),
    ``owner_id``.

    ``real_estate`` has no UNIQUE constraint — this is an append-only
    table and rows with the same ``(name, as_of)`` are legal if the
    caller wants multiple provenance sources. The seeder clears the
    window with its own ``DELETE`` before calling.

    Invariants enforced per row before any write:

    * ``estimated_value`` present, numeric, and strictly positive.
    * ``as_of`` is a parseable ISO date (``YYYY-MM-DD`` or
      ``YYYY-MM-DDTHH:MM:SS``).
    * ``name`` present.

    Any violation raises ``ValueError`` with row context.

    Returns ``{"inserted": int}``. Caller commits.
    """
    if not rows:
        return {"inserted": 0}

    for row in rows:
        _assert_real_estate_invariant(row)

    params = [
        (
            row["name"],
            float(row["estimated_value"]),
            row.get("linked_loan_id"),
            row.get("source", "manual"),
            row["as_of"],
            row.get("owner_id"),
            row.get("address"),
            (
                float(row["purchase_price"])
                if row.get("purchase_price") is not None
                else None
            ),
            row.get("purchase_date"),
        )
        for row in rows
    ]
    conn.executemany(
        """INSERT INTO real_estate
               (name, estimated_value, linked_loan_id, source, as_of, owner_id,
                address, purchase_price, purchase_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        params,
    )
    return {"inserted": len(params)}


def get_valuation_history(
    conn: sqlite3.Connection,
    name: str,
    months: Optional[int] = None,
) -> list[dict]:
    """Return chronologically-ascending valuations for a single property.

    ``months`` restricts to the last N months via SQLite date arithmetic;
    ``None`` returns the full history. Mirrors ``dal.apy_history.get_apy_history``
    so T08's sparkline/trend helper can consume either series the same way.
    """
    if months is not None:
        rows = conn.execute(
            """SELECT id, name, estimated_value, as_of, source
               FROM real_estate
               WHERE name = ? AND source != '[source]'
                 AND as_of >= date('now', ?)
               ORDER BY as_of ASC, id ASC""",
            (name, f"-{months} months"),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, name, estimated_value, as_of, source
               FROM real_estate
               WHERE name = ? AND source != '[source]'
               ORDER BY as_of ASC, id ASC""",
            (name,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_real_estate_details(
    conn: sqlite3.Connection,
    property_id: int,
) -> Optional[dict]:
    """Return an end-to-end detail bundle for a single property row.

    ``property_id`` is the numeric PK the frontend hands back from
    ``list_real_estate`` (the latest row per property name). The detail
    response layers that row's own fields on top of the linked-mortgage
    scraped fields so the T08 panel can render both in one fetch.

    Returns ``None`` if no row with ``property_id`` exists. Otherwise::

        {
            "property_id": int,
            "name": str,
            "address": str | None,
            "purchase_price": float | None,
            "purchase_date": str | None,
            "latest_valuation": {"estimated_value", "source", "as_of"},
            "linked_loan_id": str | None,
            "valuation_history": [{"estimated_value", "as_of"}, ...],  # 12mo asc
        }

    ``address`` / ``purchase_price`` / ``purchase_date`` were added in v37 as
    the canonical home for property identity that used to live in the
    loan_details KV. ``real_estate`` is append-only — this returns the
    LATEST non-null value across all rows for the property name, so a
    quarterly valuation row that omits address still surfaces the
    address that was set on a prior row.

    Linked-mortgage fields (loan_details, apy) are NOT merged here —
    the router composes those by calling this + the account-details
    handler's helpers, keeping the DAL single-purpose.
    """
    row = conn.execute(
        """SELECT id, name, estimated_value, linked_loan_id, source,
                  as_of, owner_id
           FROM real_estate
           WHERE id = ?""",
        (property_id,),
    ).fetchone()
    if row is None:
        return None

    history = get_valuation_history(conn, row["name"], months=12)

    # Identity fields (added in v37) live on whichever row(s) carry them
    # — pick the latest non-null per column across the property's
    # history. Append-only table semantics: we don't know which row a
    # given column was first set on, only that the most recent non-null
    # is current.
    identity = conn.execute(
        """SELECT
               (SELECT address FROM real_estate
                WHERE name = ? AND address IS NOT NULL
                ORDER BY as_of DESC, id DESC LIMIT 1) AS address,
               (SELECT purchase_price FROM real_estate
                WHERE name = ? AND purchase_price IS NOT NULL
                ORDER BY as_of DESC, id DESC LIMIT 1) AS purchase_price,
               (SELECT purchase_date FROM real_estate
                WHERE name = ? AND purchase_date IS NOT NULL
                ORDER BY as_of DESC, id DESC LIMIT 1) AS purchase_date
        """,
        (row["name"], row["name"], row["name"]),
    ).fetchone()

    return {
        "property_id": row["id"],
        "name": row["name"],
        "address": identity["address"] if identity else None,
        "purchase_price": identity["purchase_price"] if identity else None,
        "purchase_date": identity["purchase_date"] if identity else None,
        "latest_valuation": {
            "estimated_value": row["estimated_value"],
            "source": row["source"],
            "as_of": row["as_of"],
        },
        "linked_loan_id": row["linked_loan_id"],
        "valuation_history": [
            {"estimated_value": h["estimated_value"], "as_of": h["as_of"]}
            for h in history
        ],
    }


def list_real_estate(
    conn: sqlite3.Connection,
    owner_id: Optional[str] = None,
) -> list[dict]:
    """Return one row per distinct property with its latest valuation.

    Real estate is an append-only time series; this collapses the table
    to "latest known value per property name" using a window function,
    the same pattern used in ``dal/reports.py::get_net_worth_snapshot``.

    Returned dict shape (frontend-facing):
        {
            "id": int,                          # latest row's PK (handle for POSTs)
            "name": str,                        # property name (the natural key)
            "estimated_value": float,           # dollars
            "as_of": str,                       # ISO date
            "source": str,                      # 'homesquad' | 'manual' | 'estimate' | ...
            "linked_loan_id": str | None,       # accounts.id of the linked mortgage
            "owner_id": str | None,
        }
    """
    sql = """
        WITH latest AS (
            SELECT id, name, estimated_value, linked_loan_id, source,
                   as_of, owner_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY name
                       ORDER BY as_of DESC, id DESC
                   ) AS rn
            FROM real_estate
            WHERE source != '[source]'  -- exclude audit/provenance rows
    """
    params: list = []
    if owner_id is not None:
        sql += " AND LOWER(owner_id) = LOWER(?)"
        params.append(owner_id)
    sql += """
        )
        SELECT id, name, estimated_value, linked_loan_id, source, as_of, owner_id
        FROM latest
        WHERE rn = 1
        ORDER BY name
    """
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
