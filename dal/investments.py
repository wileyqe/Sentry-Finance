"""
dal/investments.py — Read functions for investment holdings, activity, and performance.

Public API:
    get_holdings(conn, owner_id=None)     — current per-ETF positions per account
    get_activity(conn, account_id, months) — recent investment activity
    get_performance(conn, account_id)      — monthly value time-series
"""

import logging
import sqlite3
from datetime import date, timedelta

from dal.owners import build_account_filter

log = logging.getLogger("sentry.dal.investments")


def get_holdings(
    conn: sqlite3.Connection,
    owner_id: str | None = None,
) -> list[dict]:
    """Return current per-ETF positions for each investment account.

    For each investment/retirement account, reads the latest
    positions_ledger row per ticker (for share counts) and the latest
    benchmark_prices row (for current price).  Returns one dict per
    account with nested holdings.
    """
    acct_filter_sql, acct_params = build_account_filter(
        conn, owner_id, None, column="a.id"
    )

    accounts = conn.execute(
        f"""SELECT a.id, a.name, a.institution_id, a.type
            FROM accounts a
            WHERE a.type IN ('investment', 'retirement')
              AND a.is_active = 1
              {acct_filter_sql}
            ORDER BY a.name""",
        acct_params,
    ).fetchall()

    result = []
    for acct in accounts:
        acct_id = acct["id"]

        # Latest share count per ticker
        positions = conn.execute(
            """SELECT ticker,
                      COALESCE(new_total_shares_dec, CAST(new_total_shares AS TEXT)) as shares,
                      yfinance_closing_price as last_price,
                      MAX(timestamp) as last_ts
               FROM positions_ledger
               WHERE account_id = ?
               GROUP BY ticker
               HAVING shares IS NOT NULL AND CAST(shares AS REAL) > 0
               ORDER BY ticker""",
            (acct_id,),
        ).fetchall()

        # Latest portfolio snapshot for total value
        snap = conn.execute(
            """SELECT total_account_value, timestamp
               FROM portfolio_snapshots
               WHERE account_id = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (acct_id,),
        ).fetchone()

        holdings = []
        total_value = 0.0
        for pos in positions:
            shares_str = pos["shares"]
            shares_val = float(shares_str) if shares_str else 0.0

            # Try to get a recent price from benchmark_prices
            bp = conn.execute(
                """SELECT close_price FROM benchmark_prices
                   WHERE ticker = ? ORDER BY price_date DESC LIMIT 1""",
                (pos["ticker"],),
            ).fetchone()
            price = bp["close_price"] if bp else pos["last_price"]

            market_value = shares_val * price if price else None
            if market_value:
                total_value += market_value

            holdings.append({
                "ticker": pos["ticker"],
                "shares": shares_str,
                "price": round(price, 2) if price else None,
                "market_value": round(market_value, 2) if market_value else None,
            })

        # Compute allocation percentages
        if total_value > 0:
            for h in holdings:
                if h["market_value"]:
                    h["allocation_pct"] = round(
                        h["market_value"] / total_value * 100, 1
                    )
                else:
                    h["allocation_pct"] = 0.0

        result.append({
            "account_id": acct_id,
            "name": acct["name"],
            "institution_id": acct["institution_id"],
            "total_value": round(snap["total_account_value"], 2) if snap else round(total_value, 2),
            "holdings": holdings,
            "last_scraped": snap["timestamp"] if snap else None,
        })

    return result


def get_activity(
    conn: sqlite3.Connection,
    account_id: str,
    months: int = 6,
) -> list[dict]:
    """Return recent investment activity for an account.

    Joins bank-side Acorns debits (from transactions via investment_link)
    with investment-side share changes (from positions_ledger).
    """
    cutoff = (date.today() - timedelta(days=months * 31)).isoformat()

    # Bank-side Acorns debits (transfers, roundups, fees)
    bank_txns = conn.execute(
        """SELECT t.id, t.posting_date, t.amount, t.description,
                  t.transfer_tag, t.investment_link
           FROM transactions t
           WHERE t.account_id IN (
               SELECT DISTINCT pl.bank_txn_id
               FROM positions_ledger pl WHERE pl.account_id = ?
               UNION
               SELECT t2.id FROM transactions t2
               WHERE t2.investment_link IS NOT NULL
                 AND t2.description LIKE '%ACORNS%'
           )
           OR (t.description LIKE '%ACORNS%'
               AND t.direction = 'Debit'
               AND t.posting_date >= ?)
           ORDER BY t.posting_date DESC""",
        (account_id, cutoff),
    ).fetchall()

    activity = []
    for txn in bank_txns:
        desc = txn["description"] or ""
        if "FEE" in desc.upper():
            act_type = "fee"
        elif "ROUNDUP" in desc.upper():
            act_type = "roundup"
        elif "TRANSFER" in desc.upper():
            act_type = "contribution"
        else:
            act_type = "contribution"

        activity.append({
            "date": txn["posting_date"],
            "type": act_type,
            "amount": round(txn["amount"], 2),
        })

    return activity


def get_performance(
    conn: sqlite3.Connection,
    account_id: str,
) -> list[dict]:
    """Return monthly portfolio value time-series for charting.

    Each entry contains total_value (from portfolio_snapshots),
    contributions (sum of bank-side debits that month), and
    gain_loss (value change minus contributions).
    """
    # Monthly portfolio values from snapshots
    snapshots = conn.execute(
        """SELECT strftime('%Y-%m', timestamp) as month,
                  MAX(total_account_value) as total_value
           FROM portfolio_snapshots
           WHERE account_id = ?
           GROUP BY month
           ORDER BY month""",
        (account_id,),
    ).fetchall()

    # Monthly contributions from bank-side debits
    contribs = conn.execute(
        """SELECT strftime('%Y-%m', posting_date) as month,
                  SUM(amount) as total_contrib
           FROM transactions
           WHERE transfer_tag LIKE 'invest:%'
             AND direction = 'Debit'
             AND description LIKE '%ACORNS%'
             AND description NOT LIKE '%FEE%'
           GROUP BY month""",
    ).fetchall()
    contrib_map = {r["month"]: r["total_contrib"] for r in contribs}

    result = []
    prev_value = 0.0
    for snap in snapshots:
        month = snap["month"]
        total_value = snap["total_value"] or 0.0
        contributions = contrib_map.get(month, 0.0)
        value_change = total_value - prev_value
        gain_loss = value_change - contributions

        result.append({
            "month": month,
            "total_value": round(total_value, 2),
            "contributions": round(contributions, 2),
            "gain_loss": round(gain_loss, 2),
        })
        prev_value = total_value

    return result
