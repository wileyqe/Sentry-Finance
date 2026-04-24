"""
dal/balances.py — Balance snapshot and loan detail storage.

Balance snapshots are immutable time-series records.
Loan details are key-value pairs snapshotted per refresh.
"""

import logging
import sqlite3
from datetime import datetime

log = logging.getLogger("sentry.dal.balances")


def record_balance(
    conn: sqlite3.Connection,
    account_id: str,
    balance: float,
    as_of: str | None = None,
    refresh_run_id: str | None = None,
) -> None:
    """Record a balance snapshot for an account.

    Args:
        account_id: e.g. "nfcu_XXXX"
        balance: current balance value
        as_of: ISO datetime (defaults to now)
        refresh_run_id: UUID of the refresh run
    """
    if as_of is None:
        as_of = datetime.now().replace(microsecond=0).isoformat()

    conn.execute(
        """
        INSERT INTO balance_snapshots (account_id, balance, as_of,
                                       refresh_run_id)
        VALUES (?, ?, ?, ?)
    """,
        (account_id, balance, as_of, refresh_run_id),
    )


def get_latest_balance(conn: sqlite3.Connection, account_id: str) -> dict | None:
    """Get the most recent balance for an account."""
    row = conn.execute(
        "SELECT balance, as_of FROM balance_snapshots "
        "WHERE account_id = ? ORDER BY as_of DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    return dict(row) if row else None


def get_latest_balances(
    conn: sqlite3.Connection, account_ids: list[str]
) -> dict[str, dict]:
    """Batched latest-balance lookup for a set of accounts.

    Returns a ``{account_id: {"balance": float, "as_of": str}}`` dict. Missing
    accounts are omitted. Replaces the N+1 pattern of calling
    :func:`get_latest_balance` inside a loop — see ``result_writer.persist_connector_result``.
    """
    if not account_ids:
        return {}
    placeholders = ",".join("?" for _ in account_ids)
    rows = conn.execute(
        f"""
        SELECT bs.account_id, bs.balance, bs.as_of
        FROM balance_snapshots bs
        WHERE bs.id = (
            SELECT id FROM balance_snapshots b2
            WHERE b2.account_id = bs.account_id
            ORDER BY b2.as_of DESC LIMIT 1
        )
          AND bs.account_id IN ({placeholders})
        """,
        list(account_ids),
    ).fetchall()
    return {r["account_id"]: {"balance": r["balance"], "as_of": r["as_of"]} for r in rows}


def get_balance_history(
    conn: sqlite3.Connection,
    account_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 365,
) -> list[dict]:
    """Get balance history for charting."""
    clauses = ["account_id = ?"]
    params: list = [account_id]

    if start_date:
        clauses.append("as_of >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("as_of <= ?")
        params.append(end_date)

    where = " AND ".join(clauses)
    params.append(limit)

    rows = conn.execute(
        f"SELECT balance, as_of FROM balance_snapshots "
        f"WHERE {where} ORDER BY as_of ASC LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_latest_balances(conn: sqlite3.Connection, owner_id: str | None = None) -> list[dict]:
    """Get the latest balance for every account."""
    extra_where = ""
    params: list = []
    if owner_id:
        from dal.owners import resolve_account_ids_for_view
        acct_ids = resolve_account_ids_for_view(conn, owner_id)
        if acct_ids is not None:
            placeholders = ",".join("?" for _ in acct_ids)
            extra_where = f"AND a.id IN ({placeholders})"
            params.extend(acct_ids)

    rows = conn.execute(f"""
        SELECT bs.account_id, a.name, a.last4, a.type,
               a.institution_id, bs.balance, bs.as_of
        FROM balance_snapshots bs
        JOIN accounts a ON a.id = bs.account_id
        WHERE bs.id = (
            SELECT id FROM balance_snapshots b2
            WHERE b2.account_id = bs.account_id
            ORDER BY b2.as_of DESC LIMIT 1
        )
        {extra_where}
        ORDER BY a.institution_id, a.name
    """, params).fetchall()
    return [dict(r) for r in rows]


# ── Loan Details ─────────────────────────────────────────────────────────────


# Field names that describe the COLLATERAL ASSET (vehicle / property),
# not the loan itself. For loans with a linked asset they belong on the
# asset's row (vehicle_assets / real_estate), not in this KV store.
# Exported so the seeder integrity check can build its SQL `IN (...)`
# clause from the same source rather than duplicating the literal.
COLLATERAL_FIELDS = frozenset({
    "vin",
    "collateral_description",
    "purchase_price",
    "gap_flag",
    "date_opened",
})


def _account_has_linked_asset(
    conn: sqlite3.Connection, account_id: str
) -> bool:
    """Return True if any vehicle_assets or real_estate row links here."""
    row = conn.execute(
        """SELECT 1 FROM vehicle_assets WHERE linked_loan_id = ?
           UNION ALL
           SELECT 1 FROM real_estate   WHERE linked_loan_id = ?
           LIMIT 1""",
        (account_id, account_id),
    ).fetchone()
    return row is not None


def record_loan_details(
    conn: sqlite3.Connection,
    account_id: str,
    details: dict[str, str],
    as_of: str | None = None,
    refresh_run_id: str | None = None,
) -> None:
    """Record a set of loan detail fields for an account.

    Args:
        account_id: e.g. "nfcu_XXXX"
        details: {"original_loan_amount": "$25,000", "apr": "4.5%", ...}
        as_of: ISO datetime (defaults to now)

    Raises:
        ValueError: if any ``details`` key is in ``COLLATERAL_FIELDS``
            AND the account has a linked vehicle or property row. Those
            facts belong on the asset row, not the loan KV.
    """
    leaked = COLLATERAL_FIELDS.intersection(details.keys())
    if leaked and _account_has_linked_asset(conn, account_id):
        raise ValueError(
            f"record_loan_details({account_id!r}): cannot write "
            f"collateral identity fields {sorted(leaked)} to loan KV — "
            f"this account has a linked vehicle_assets or real_estate "
            f"row. Write them on the asset instead. "
            f"See docs/prompts/Phase-15/P15-T10_details-panel-single-source.md."
        )

    if as_of is None:
        as_of = datetime.now().replace(microsecond=0).isoformat()

    for field_name, field_value in details.items():
        conn.execute(
            """
            INSERT INTO loan_details (account_id, field_name,
                                      field_value, as_of,
                                      refresh_run_id)
            VALUES (?, ?, ?, ?, ?)
        """,
            (account_id, field_name, field_value, as_of, refresh_run_id),
        )


def get_latest_loan_details(
    conn: sqlite3.Connection, account_id: str
) -> dict[str, str]:
    """Get the latest loan detail snapshot for an account.

    Returns a dict of field_name → field_value.
    """
    # Get the most recent as_of for this account
    latest = conn.execute(
        "SELECT MAX(as_of) as latest FROM loan_details WHERE account_id = ?",
        (account_id,),
    ).fetchone()

    if not latest or not latest["latest"]:
        return {}

    rows = conn.execute(
        "SELECT field_name, field_value FROM loan_details "
        "WHERE account_id = ? AND as_of = ?",
        (account_id, latest["latest"]),
    ).fetchall()

    return {row["field_name"]: row["field_value"] for row in rows}
