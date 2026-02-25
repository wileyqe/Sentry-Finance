"""
dal/balances.py — Balance snapshot and loan detail storage.

Balance snapshots are immutable time-series records.
Loan details are key-value pairs snapshotted per refresh.
"""
import logging
import sqlite3
from datetime import datetime

log = logging.getLogger("sentry")


def record_balance(conn: sqlite3.Connection,
                   account_id: str,
                   balance: float,
                   as_of: str | None = None,
                   refresh_run_id: str | None = None) -> None:
    """Record a balance snapshot for an account.

    Args:
        account_id: e.g. "nfcu_1167"
        balance: current balance value
        as_of: ISO datetime (defaults to now)
        refresh_run_id: UUID of the refresh run
    """
    if as_of is None:
        as_of = datetime.utcnow().isoformat()

    conn.execute("""
        INSERT INTO balance_snapshots (account_id, balance, as_of,
                                       refresh_run_id)
        VALUES (?, ?, ?, ?)
    """, (account_id, balance, as_of, refresh_run_id))


def get_latest_balance(conn: sqlite3.Connection,
                       account_id: str) -> dict | None:
    """Get the most recent balance for an account."""
    row = conn.execute(
        "SELECT balance, as_of FROM balance_snapshots "
        "WHERE account_id = ? ORDER BY as_of DESC LIMIT 1",
        (account_id,)
    ).fetchone()
    return dict(row) if row else None


def get_balance_history(conn: sqlite3.Connection,
                        account_id: str,
                        start_date: str | None = None,
                        end_date: str | None = None,
                        limit: int = 365) -> list[dict]:
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
        params
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_latest_balances(conn: sqlite3.Connection) -> list[dict]:
    """Get the latest balance for every account."""
    rows = conn.execute("""
        SELECT bs.account_id, a.name, a.last4, a.type,
               a.institution_id, bs.balance, bs.as_of
        FROM balance_snapshots bs
        JOIN accounts a ON a.id = bs.account_id
        WHERE bs.id = (
            SELECT id FROM balance_snapshots b2
            WHERE b2.account_id = bs.account_id
            ORDER BY b2.as_of DESC LIMIT 1
        )
        ORDER BY a.institution_id, a.name
    """).fetchall()
    return [dict(r) for r in rows]


# ── Loan Details ─────────────────────────────────────────────────────────────

def record_loan_details(conn: sqlite3.Connection,
                        account_id: str,
                        details: dict[str, str],
                        as_of: str | None = None,
                        refresh_run_id: str | None = None) -> None:
    """Record a set of loan detail fields for an account.

    Args:
        account_id: e.g. "nfcu_3533"
        details: {"original_loan_amount": "$25,000", "apr": "4.5%", ...}
        as_of: ISO datetime (defaults to now)
    """
    if as_of is None:
        as_of = datetime.utcnow().isoformat()

    for field_name, field_value in details.items():
        conn.execute("""
            INSERT INTO loan_details (account_id, field_name,
                                      field_value, as_of,
                                      refresh_run_id)
            VALUES (?, ?, ?, ?, ?)
        """, (account_id, field_name, field_value, as_of,
              refresh_run_id))


def get_latest_loan_details(conn: sqlite3.Connection,
                            account_id: str) -> dict[str, str]:
    """Get the latest loan detail snapshot for an account.

    Returns a dict of field_name → field_value.
    """
    # Get the most recent as_of for this account
    latest = conn.execute(
        "SELECT MAX(as_of) as latest FROM loan_details "
        "WHERE account_id = ?",
        (account_id,)
    ).fetchone()

    if not latest or not latest["latest"]:
        return {}

    rows = conn.execute(
        "SELECT field_name, field_value FROM loan_details "
        "WHERE account_id = ? AND as_of = ?",
        (account_id, latest["latest"])
    ).fetchall()

    return {row["field_name"]: row["field_value"] for row in rows}

