"""
dal/investments.py — Investment holdings and portfolio tracking.

Manages daily per-ticker positions, portfolio valuations, and
investment-specific queries for the dashboard.

Precision note (schema V4):
  All fractional share counts and prices are stored in TEXT columns
  (*_dec suffix) as exact decimal strings and accessed via
  decimal.Decimal.  The legacy REAL columns are kept for backward
  compatibility but should not be used for new writes.
"""

import logging
import sqlite3
from decimal import Decimal, InvalidOperation

log = logging.getLogger("sentry.dal.investments")

# ── Decimal helpers ─────────────────────────────────────────────────────────


def _to_dec(value) -> Decimal | None:
    """Convert a float, int, string, or None to Decimal. Returns None on failure."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _dec_str(value) -> str | None:
    """Serialize a Decimal (or compatible value) to a canonical string for storage."""
    d = _to_dec(value)
    return str(d) if d is not None else None


def _from_dec_col(row: dict, col: str, fallback_col: str | None = None):
    """Read a Decimal-precision column from a row dict.

    Tries the TEXT *_dec column first; falls back to the REAL column
    (converted via Decimal for consistency) if the _dec column is absent
    or NULL.
    """
    val = row.get(col)
    if val is not None:
        try:
            return Decimal(val)
        except (InvalidOperation, TypeError):
            pass
    if fallback_col:
        fb = row.get(fallback_col)
        if fb is not None:
            return _to_dec(fb)
    return None


# ── Write helpers ────────────────────────────────────────────────────────────


def upsert_holding(
    conn: sqlite3.Connection,
    account_id: str,
    date: str,
    ticker: str,
    shares,
    close_price=None,
    market_value=None,
    cost_basis=None,
) -> None:
    """Insert or update a single holding record.

    Args:
        shares, close_price, market_value, cost_basis: Accept float, int,
            str, or Decimal.  Stored in both the legacy REAL column (for
            dashboard queries that haven't migrated yet) and the new TEXT
            *_dec column (for precision-sensitive calculations).
    """
    shares_d = _dec_str(shares)
    price_d = _dec_str(close_price)
    mv_d = _dec_str(market_value)
    cb_d = _dec_str(cost_basis)

    # Keep legacy REAL columns populated for zero-downtime compatibility
    shares_f = float(_to_dec(shares)) if shares is not None else None
    price_f = float(_to_dec(close_price)) if close_price is not None else None
    mv_f = float(_to_dec(market_value)) if market_value is not None else None
    cb_f = float(_to_dec(cost_basis)) if cost_basis is not None else None

    conn.execute(
        """
        INSERT INTO investment_holdings
            (account_id, date, ticker,
             shares, close_price, market_value, cost_basis,
             shares_dec, close_price_dec, market_value_dec, cost_basis_dec)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, date, ticker)
        DO UPDATE SET
            shares            = excluded.shares,
            close_price       = excluded.close_price,
            market_value      = excluded.market_value,
            cost_basis        = COALESCE(excluded.cost_basis, investment_holdings.cost_basis),
            shares_dec        = excluded.shares_dec,
            close_price_dec   = excluded.close_price_dec,
            market_value_dec  = excluded.market_value_dec,
            cost_basis_dec    = COALESCE(excluded.cost_basis_dec, investment_holdings.cost_basis_dec)
    """,
        (
            account_id,
            date,
            ticker,
            shares_f,
            price_f,
            mv_f,
            cb_f,
            shares_d,
            price_d,
            mv_d,
            cb_d,
        ),
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


# ── Read helpers ─────────────────────────────────────────────────────────────


def get_latest_holdings(
    conn: sqlite3.Connection,
    account_id: str,
) -> list[dict]:
    """Get the most recent holdings for an account.

    Returns dicts with Decimal-typed shares/price/value fields.
    """
    rows = conn.execute(
        """
        SELECT ticker,
               shares, close_price, market_value, cost_basis, date,
               shares_dec, close_price_dec, market_value_dec, cost_basis_dec
        FROM investment_holdings
        WHERE account_id = ? AND date = (
            SELECT MAX(date) FROM investment_holdings WHERE account_id = ?
        )
        ORDER BY market_value DESC
    """,
        (account_id, account_id),
    ).fetchall()

    result = []
    for r in rows:
        rd = dict(r)
        rd["shares"] = _from_dec_col(rd, "shares_dec", "shares")
        rd["close_price"] = _from_dec_col(rd, "close_price_dec", "close_price")
        rd["market_value"] = _from_dec_col(rd, "market_value_dec", "market_value")
        rd["cost_basis"] = _from_dec_col(rd, "cost_basis_dec", "cost_basis")
        result.append(rd)
    return result


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
            SELECT date,
                   shares, close_price, market_value,
                   shares_dec, close_price_dec, market_value_dec
            FROM investment_holdings
            WHERE {where}
            ORDER BY date ASC
            LIMIT ?
        """,
            params,
        ).fetchall()
        result = []
        for r in rows:
            rd = dict(r)
            rd["shares"] = _from_dec_col(rd, "shares_dec", "shares")
            rd["close_price"] = _from_dec_col(rd, "close_price_dec", "close_price")
            rd["market_value"] = _from_dec_col(rd, "market_value_dec", "market_value")
            result.append(rd)
        return result
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
