"""
dal/investments.py — Investment holdings and portfolio tracking.

Manages daily per-ticker positions, portfolio valuations, and
investment-specific queries for the dashboard.
"""

import logging
import sqlite3

log = logging.getLogger("sentry.dal.investments")


def upsert_holding(
    conn: sqlite3.Connection,
    account_id: str,
    date: str,
    ticker: str,
    shares: float,
    close_price: float | None = None,
    market_value: float | None = None,
    cost_basis: float | None = None,
) -> None:
    """Insert or update a single holding record."""
    conn.execute(
        """
        INSERT INTO investment_holdings
            (account_id, date, ticker, shares, close_price, market_value, cost_basis)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, date, ticker)
        DO UPDATE SET shares = excluded.shares,
                      close_price = excluded.close_price,
                      market_value = excluded.market_value,
                      cost_basis = COALESCE(excluded.cost_basis, investment_holdings.cost_basis)
    """,
        (account_id, date, ticker, shares, close_price, market_value, cost_basis),
    )


def upsert_holdings_batch(
    conn: sqlite3.Connection,
    rows: list[dict],
) -> int:
    """Bulk upsert a list of holding dicts.

    Each dict should have: account_id, date, ticker, shares,
    and optionally: close_price, market_value, cost_basis.

    Returns the number of rows upserted.
    """
    count = 0
    for r in rows:
        upsert_holding(
            conn,
            account_id=r["account_id"],
            date=r["date"],
            ticker=r["ticker"],
            shares=r["shares"],
            close_price=r.get("close_price"),
            market_value=r.get("market_value"),
            cost_basis=r.get("cost_basis"),
        )
        count += 1
    return count


def get_latest_holdings(
    conn: sqlite3.Connection,
    account_id: str,
) -> list[dict]:
    """Get the most recent holdings for an account."""
    rows = conn.execute(
        """
        SELECT ticker, shares, close_price, market_value, cost_basis, date
        FROM investment_holdings
        WHERE account_id = ? AND date = (
            SELECT MAX(date) FROM investment_holdings WHERE account_id = ?
        )
        ORDER BY market_value DESC
    """,
        (account_id, account_id),
    ).fetchall()
    return [dict(r) for r in rows]


def get_holdings_history(
    conn: sqlite3.Connection,
    account_id: str,
    ticker: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Get historical holdings for charting.

    If ticker is specified, returns history for that ticker only.
    Otherwise returns total portfolio value per date.
    """
    if ticker:
        clauses = ["account_id = ?", "ticker = ?"]
        params: list = [account_id, ticker]
    else:
        clauses = ["account_id = ?"]
        params = [account_id]

    if start_date:
        clauses.append("date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("date <= ?")
        params.append(end_date)

    where = " AND ".join(clauses)
    params.append(limit)

    if ticker:
        rows = conn.execute(
            f"""
            SELECT date, shares, close_price, market_value
            FROM investment_holdings
            WHERE {where}
            ORDER BY date ASC
            LIMIT ?
        """,
            params,
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT date, SUM(market_value) as total_value,
                   COUNT(DISTINCT ticker) as num_tickers
            FROM investment_holdings
            WHERE {where}
            GROUP BY date
            ORDER BY date ASC
            LIMIT ?
        """,
            params,
        ).fetchall()

    return [dict(r) for r in rows]


def get_portfolio_total(
    conn: sqlite3.Connection,
    account_id: str,
) -> dict | None:
    """Get the latest total portfolio value for an account.

    Returns: {total_value, num_tickers, date, cash_balance}
    """
    row = conn.execute(
        """
        SELECT SUM(market_value) as total_value,
               COUNT(DISTINCT ticker) as num_tickers,
               MAX(date) as date
        FROM investment_holdings
        WHERE account_id = ? AND date = (
            SELECT MAX(date) FROM investment_holdings WHERE account_id = ?
        )
    """,
        (account_id, account_id),
    ).fetchone()

    if not row or row["total_value"] is None:
        return None

    result = dict(row)

    # Add cash balance from portfolio_snapshots if available
    cash_row = conn.execute(
        """
        SELECT cash_balance FROM portfolio_snapshots
        WHERE account_id = ?
        ORDER BY timestamp DESC LIMIT 1
    """,
        (account_id,),
    ).fetchone()

    result["cash_balance"] = cash_row["cash_balance"] if cash_row else 0.0
    return result
