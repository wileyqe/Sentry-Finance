"""
dal/investments.py — Read functions for investment holdings, activity,
performance, tax lots, and allocation.

Public API:
    get_holdings(conn, owner_id=None)          — current per-ticker positions per account
    get_activity(conn, account_id, months)     — recent investment activity
    get_performance(conn, account_id, timeframe) — value time-series with adaptive granularity
    get_lots(conn, account_id, ticker)         — FIFO tax lot detail
    get_allocation(conn, owner_id=None)        — aggregated allocation by sector/geo/cap
"""

import logging
import sqlite3
from datetime import date, timedelta

from dal.owners import build_account_filter

log = logging.getLogger("sentry.dal.investments")

CASH_EQUIVALENTS = {"SPAXX", "FDRXX"}


def get_holdings(
    conn: sqlite3.Connection,
    owner_id: str | None = None,
) -> list[dict]:
    """Return current per-ticker positions for each investment account.

    Reads latest investment_holdings snapshot (preferred) or falls back to
    positions_ledger.  Includes cost_basis, gain/loss, and sector data
    from ticker_metadata.  Cash equivalents (SPAXX/FDRXX) are separated
    into a cash_balance field per account.
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

        # Try investment_holdings first (latest date)
        latest_date = conn.execute(
            "SELECT MAX(date) FROM investment_holdings WHERE account_id = ?",
            (acct_id,),
        ).fetchone()[0]

        holdings = []
        total_equity_value = 0.0
        cash_balance = 0.0

        if latest_date:
            rows = conn.execute(
                """SELECT ih.ticker, ih.shares, ih.close_price, ih.market_value,
                          ih.cost_basis,
                          tm.sector, tm.industry, tm.asset_class
                   FROM investment_holdings ih
                   LEFT JOIN ticker_metadata tm ON tm.ticker = ih.ticker
                   WHERE ih.account_id = ? AND ih.date = ?
                   ORDER BY ih.market_value DESC""",
                (acct_id, latest_date),
            ).fetchall()

            for r in rows:
                if r["ticker"] in CASH_EQUIVALENTS:
                    cash_balance += r["market_value"] or 0.0
                    continue

                cost = r["cost_basis"] or 0.0
                mv = r["market_value"] or 0.0
                gain = mv - cost if cost > 0 else 0.0
                gain_pct = (gain / cost * 100) if cost > 0 else 0.0
                total_equity_value += mv

                holdings.append({
                    "ticker": r["ticker"],
                    "shares": str(r["shares"]),
                    "price": round(r["close_price"], 2) if r["close_price"] else None,
                    "market_value": round(mv, 2),
                    "cost_basis": round(cost, 2),
                    "total_gain_loss": round(gain, 2),
                    "gain_loss_pct": round(gain_pct, 1),
                    "sector": r["sector"],
                    "industry": r["industry"],
                    "asset_class": r["asset_class"],
                })
        else:
            # Fallback: aggregate from positions_ledger
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

            for pos in positions:
                shares_val = float(pos["shares"]) if pos["shares"] else 0.0
                bp = conn.execute(
                    "SELECT close_price FROM benchmark_prices WHERE ticker = ? ORDER BY price_date DESC LIMIT 1",
                    (pos["ticker"],),
                ).fetchone()
                price = bp["close_price"] if bp else pos["last_price"]
                market_value = shares_val * price if price else None
                if market_value:
                    total_equity_value += market_value

                # Try to get metadata
                tm = conn.execute(
                    "SELECT sector, industry, asset_class FROM ticker_metadata WHERE ticker = ?",
                    (pos["ticker"],),
                ).fetchone()

                holdings.append({
                    "ticker": pos["ticker"],
                    "shares": pos["shares"],
                    "price": round(price, 2) if price else None,
                    "market_value": round(market_value, 2) if market_value else None,
                    "cost_basis": None,
                    "total_gain_loss": None,
                    "gain_loss_pct": None,
                    "sector": tm["sector"] if tm else None,
                    "industry": tm["industry"] if tm else None,
                    "asset_class": tm["asset_class"] if tm else None,
                })

        # Get cash_balance from latest portfolio snapshot if not from holdings
        if cash_balance == 0.0:
            snap = conn.execute(
                """SELECT cash_balance FROM portfolio_snapshots
                   WHERE account_id = ? ORDER BY timestamp DESC LIMIT 1""",
                (acct_id,),
            ).fetchone()
            if snap and snap["cash_balance"]:
                cash_balance = snap["cash_balance"]

        # Compute allocation percentages
        total_value = total_equity_value + cash_balance
        if total_value > 0:
            for h in holdings:
                if h["market_value"]:
                    h["allocation_pct"] = round(h["market_value"] / total_value * 100, 1)
                else:
                    h["allocation_pct"] = 0.0

        snap = conn.execute(
            """SELECT total_account_value, timestamp
               FROM portfolio_snapshots
               WHERE account_id = ? ORDER BY timestamp DESC LIMIT 1""",
            (acct_id,),
        ).fetchone()

        # Use computed total (equity + cash) when we have holdings,
        # fall back to snapshot for accounts with no holdings data yet.
        display_value = total_value if holdings else (
            round(snap["total_account_value"], 2) if snap else 0.0
        )

        result.append({
            "account_id": acct_id,
            "name": acct["name"],
            "institution_id": acct["institution_id"],
            "total_value": round(display_value, 2),
            "cash_balance": round(cash_balance, 2),
            "holdings": holdings,
            "last_scraped": snap["timestamp"] if snap else None,
        })

    return result


def get_lots(
    conn: sqlite3.Connection,
    account_id: str,
    ticker: str,
) -> list[dict]:
    """Return FIFO tax lot detail for a specific ticker in an account.

    Reads BUY/REINVESTMENT/INITIAL_BASELINE/IMPLIED_BUY entries from
    positions_ledger with remaining shares > 0.  Computes current value
    per lot from latest benchmark_prices.
    """
    # Get current price
    bp = conn.execute(
        "SELECT close_price FROM benchmark_prices WHERE ticker = ? ORDER BY price_date DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    current_price = bp["close_price"] if bp else None

    rows = conn.execute(
        """SELECT timestamp, share_delta, share_delta_dec,
                  yfinance_closing_price, cost_basis_dec
           FROM positions_ledger
           WHERE account_id = ? AND ticker = ?
             AND transaction_type IN ('BUY', 'REINVESTMENT', 'INITIAL_BASELINE', 'IMPLIED_BUY')
             AND CAST(COALESCE(share_delta_dec, share_delta) AS REAL) > 0
           ORDER BY timestamp""",
        (account_id, ticker),
    ).fetchall()

    # Track FIFO consumption by sells
    sells = conn.execute(
        """SELECT share_delta_dec, share_delta
           FROM positions_ledger
           WHERE account_id = ? AND ticker = ?
             AND transaction_type = 'SELL'
           ORDER BY timestamp""",
        (account_id, ticker),
    ).fetchall()

    # Build lot list, then apply FIFO consumption
    lot_list = []
    for r in rows:
        shares = float(r["share_delta_dec"] or r["share_delta"])
        cost = float(r["cost_basis_dec"]) if r["cost_basis_dec"] else (shares * (r["yfinance_closing_price"] or 0))
        lot_list.append({
            "date": r["timestamp"][:10],
            "original_shares": shares,
            "remaining_shares": shares,
            "cost_basis": round(cost, 2),
            "price_paid": round(r["yfinance_closing_price"], 2) if r["yfinance_closing_price"] else None,
        })

    # Apply FIFO sell consumption
    for sell in sells:
        sold = abs(float(sell["share_delta_dec"] or sell["share_delta"]))
        for lot in lot_list:
            if sold <= 0:
                break
            if lot["remaining_shares"] <= 0:
                continue
            consumed = min(lot["remaining_shares"], sold)
            fraction = consumed / lot["original_shares"] if lot["original_shares"] > 0 else 0
            lot["remaining_shares"] -= consumed
            lot["cost_basis"] = round(lot["cost_basis"] * (1 - fraction), 2) if fraction < 1 else 0.0
            sold -= consumed

    # Build result — only lots with remaining shares
    result = []
    today = date.today()
    for lot in lot_list:
        if lot["remaining_shares"] <= 0.0001:
            continue
        current_value = lot["remaining_shares"] * current_price if current_price else None
        gain_loss = (current_value - lot["cost_basis"]) if current_value and lot["cost_basis"] else None
        lot_date = date.fromisoformat(lot["date"])
        result.append({
            "date": lot["date"],
            "quantity": round(lot["remaining_shares"], 5),
            "cost_basis": lot["cost_basis"],
            "current_value": round(current_value, 2) if current_value else None,
            "gain_loss": round(gain_loss, 2) if gain_loss is not None else None,
            "holding_period_days": (today - lot_date).days,
        })

    return result


def get_allocation(
    conn: sqlite3.Connection,
    owner_id: str | None = None,
    account_id: str | None = None,
) -> dict:
    """Return aggregated allocation data across investment accounts.

    When account_id is provided, narrows to that single account.
    Joins ticker_metadata for sector, industry, asset_class.
    Returns: by_asset_class, by_sector, by_market_cap, cash_total.
    """
    acct_filter_sql, acct_params = build_account_filter(
        conn, owner_id, None, column="a.id"
    )

    # Narrow to single account when requested
    acct_narrow_sql = ""
    acct_narrow_params: list = []
    if account_id and account_id != "all":
        acct_narrow_sql = " AND a.id = ?"
        acct_narrow_params = [account_id]

    # Get latest holdings across investment accounts
    rows = conn.execute(
        f"""SELECT ih.ticker, ih.market_value, ih.shares, ih.close_price,
                   ih.cost_basis,
                   tm.sector, tm.industry, tm.asset_class
            FROM investment_holdings ih
            JOIN accounts a ON a.id = ih.account_id
            LEFT JOIN ticker_metadata tm ON tm.ticker = ih.ticker
            WHERE a.type IN ('investment', 'retirement')
              AND a.is_active = 1
              {acct_filter_sql}
              {acct_narrow_sql}
              AND ih.date = (
                  SELECT MAX(ih2.date) FROM investment_holdings ih2
                  WHERE ih2.account_id = ih.account_id
              )
            ORDER BY ih.market_value DESC""",
        acct_params + acct_narrow_params,
    ).fetchall()

    # Get cash balances from portfolio_snapshots
    cash_rows = conn.execute(
        f"""SELECT ps.cash_balance
            FROM portfolio_snapshots ps
            JOIN accounts a ON a.id = ps.account_id
            WHERE a.type IN ('investment', 'retirement')
              AND a.is_active = 1
              {acct_filter_sql}
              {acct_narrow_sql}
              AND ps.timestamp = (
                  SELECT MAX(ps2.timestamp) FROM portfolio_snapshots ps2
                  WHERE ps2.account_id = ps.account_id
              )""",
        acct_params + acct_narrow_params,
    ).fetchall()
    total_cash = sum(r["cash_balance"] or 0 for r in cash_rows)

    # Aggregate
    total_value = sum(r["market_value"] or 0 for r in rows if r["ticker"] not in CASH_EQUIVALENTS) + total_cash
    if total_value <= 0:
        return {"by_asset_class": [], "by_sector": [], "by_market_cap": [], "cash_total": 0, "total_value": 0}

    # by_sector
    sector_map: dict[str, float] = {}
    for r in rows:
        if r["ticker"] in CASH_EQUIVALENTS:
            continue
        sector = r["sector"] or "Unknown"
        sector_map[sector] = sector_map.get(sector, 0) + (r["market_value"] or 0)
    by_sector = sorted(
        [{"name": s, "amount": round(v, 2), "pct": round(v / total_value * 100, 1)}
         for s, v in sector_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )

    # by_asset_class
    class_map: dict[str, float] = {}
    for r in rows:
        if r["ticker"] in CASH_EQUIVALENTS:
            continue
        ac = r["asset_class"] or "Unknown"
        class_map[ac] = class_map.get(ac, 0) + (r["market_value"] or 0)
    if total_cash > 0:
        class_map["Cash / Equivalents"] = total_cash
    by_asset_class = sorted(
        [{"name": c, "amount": round(v, 2), "pct": round(v / total_value * 100, 1)}
         for c, v in class_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )

    # by_market_cap — use _FIDELITY_TICKERS metadata for cap info, ETFs as "Blend"
    from scripts.dummy_data.generator import _FIDELITY_TICKERS
    cap_map: dict[str, float] = {}
    for r in rows:
        if r["ticker"] in CASH_EQUIVALENTS:
            continue
        ft = _FIDELITY_TICKERS.get(r["ticker"])
        if ft:
            cap = ft.get("cap", "Large Cap")
        elif r["asset_class"] == "ETF":
            cap = "Blend / Index"
        else:
            cap = "Large Cap"
        cap_map[cap] = cap_map.get(cap, 0) + (r["market_value"] or 0)
    by_market_cap = sorted(
        [{"name": c, "amount": round(v, 2), "pct": round(v / total_value * 100, 1)}
         for c, v in cap_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )

    # treemap — individual holdings
    treemap = []
    for r in rows:
        if r["ticker"] in CASH_EQUIVALENTS:
            continue
        mv = r["market_value"] or 0
        treemap.append({
            "ticker": r["ticker"],
            "size": round(mv, 2),
            "pct": round(mv / total_value * 100, 1),
            "asset_class": r["asset_class"] or "Unknown",
            "sector": r["sector"] or "Unknown",
        })
    if total_cash > 0:
        treemap.append({
            "ticker": "CASH",
            "size": round(total_cash, 2),
            "pct": round(total_cash / total_value * 100, 1),
            "asset_class": "Cash / Equivalents",
            "sector": "Cash",
        })

    return {
        "by_asset_class": by_asset_class,
        "by_sector": by_sector,
        "by_market_cap": by_market_cap,
        "treemap": treemap,
        "cash_total": round(total_cash, 2),
        "total_value": round(total_value, 2),
    }


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


# Timeframe → granularity mapping
_TIMEFRAME_CONFIG = {
    "1D":  {"days": 1,    "granularity": "daily"},
    "1W":  {"days": 7,    "granularity": "daily"},
    "1M":  {"days": 30,   "granularity": "daily"},
    "3M":  {"days": 90,   "granularity": "biday"},
    "6M":  {"days": 180,  "granularity": "weekly"},
    "YTD": {"days": None, "granularity": "weekly"},
    "1Y":  {"days": 365,  "granularity": "weekly"},
    "All": {"days": None, "granularity": "monthly"},
}


def get_performance(
    conn: sqlite3.Connection,
    account_id: str | None = None,
    timeframe: str = "All",
    owner_id: str | None = None,
) -> list[dict]:
    """Return portfolio value time-series with adaptive granularity.

    When account_id is None or "all", aggregates across all investment
    accounts (optionally filtered by owner_id).  Uses investment_holdings
    for daily/biday resolution and portfolio_snapshots for weekly/monthly.
    """
    config = _TIMEFRAME_CONFIG.get(timeframe, _TIMEFRAME_CONFIG["All"])
    granularity = config["granularity"]

    if timeframe == "YTD":
        cutoff = date(date.today().year, 1, 1).isoformat()
    elif config["days"] is not None:
        cutoff = (date.today() - timedelta(days=config["days"])).isoformat()
    else:
        cutoff = "2000-01-01"

    # Build account filter
    aggregate_all = (account_id is None or account_id == "all")
    if aggregate_all:
        acct_filter_sql, acct_params = build_account_filter(
            conn, owner_id, None, column="a.id"
        )
        # Holdings query: join through accounts for owner filtering
        ih_where = f"""ih.account_id IN (
            SELECT a.id FROM accounts a
            WHERE a.type IN ('investment','retirement') AND a.is_active = 1
            {acct_filter_sql}
        )"""
        ih_params = acct_params
        # Snapshot query
        ps_where = f"""ps.account_id IN (
            SELECT a.id FROM accounts a
            WHERE a.type IN ('investment','retirement') AND a.is_active = 1
            {acct_filter_sql}
        )"""
        ps_params = acct_params
    else:
        ih_where = "ih.account_id = ?"
        ih_params = [account_id]
        ps_where = "ps.account_id = ?"
        ps_params = [account_id]

    if granularity in ("daily", "biday"):
        rows = conn.execute(
            f"""SELECT date, SUM(market_value) as total_value
                FROM investment_holdings ih
                WHERE {ih_where} AND date >= ?
                GROUP BY date
                ORDER BY date""",
            ih_params + [cutoff],
        ).fetchall()

        if rows:
            cash_snap = conn.execute(
                f"""SELECT substr(ps.timestamp, 1, 10) as snap_date,
                           SUM(ps.cash_balance) as cash_balance
                    FROM portfolio_snapshots ps
                    WHERE {ps_where} AND ps.timestamp >= ?
                    GROUP BY snap_date
                    ORDER BY snap_date""",
                ps_params + [cutoff],
            ).fetchall()
            cash_by_date = {r["snap_date"]: r["cash_balance"] or 0 for r in cash_snap}

            result = []
            step = 2 if granularity == "biday" else 1
            for i, r in enumerate(rows):
                if i % step != 0 and i != len(rows) - 1:
                    continue
                d = r["date"]
                cash = 0
                for cd in sorted(cash_by_date.keys()):
                    if cd <= d:
                        cash = cash_by_date[cd]
                result.append({
                    "date": d,
                    "total_value": round((r["total_value"] or 0) + cash, 2),
                })
            return result
        granularity = "weekly"

    if granularity == "weekly":
        rows = conn.execute(
            f"""SELECT substr(ps.timestamp, 1, 10) as snap_date,
                       SUM(ps.total_account_value) as total_value
                FROM portfolio_snapshots ps
                WHERE {ps_where} AND ps.timestamp >= ?
                GROUP BY snap_date
                ORDER BY snap_date""",
            ps_params + [cutoff],
        ).fetchall()
        return [
            {"date": r["snap_date"], "total_value": round(r["total_value"], 2)}
            for r in rows
        ]

    else:  # monthly
        rows = conn.execute(
            f"""SELECT strftime('%Y-%m', ps.timestamp) as month,
                       SUM(ps.total_account_value) as total_value
                FROM portfolio_snapshots ps
                WHERE {ps_where}
                GROUP BY month
                ORDER BY month""",
            ps_params,
        ).fetchall()

        contribs = conn.execute(
            """SELECT strftime('%Y-%m', posting_date) as month,
                      SUM(amount) as total_contrib
               FROM transactions
               WHERE transfer_tag LIKE 'invest:%'
                 AND direction = 'Debit'
               GROUP BY month""",
        ).fetchall()
        contrib_map = {r["month"]: r["total_contrib"] for r in contribs}

        result = []
        prev_value = 0.0
        for snap in rows:
            month = snap["month"]
            total_value = snap["total_value"] or 0.0
            contributions = contrib_map.get(month, 0.0)
            value_change = total_value - prev_value
            gain_loss = value_change - contributions

            result.append({
                "date": f"{month}-01",
                "month": month,
                "total_value": round(total_value, 2),
                "contributions": round(contributions, 2),
                "gain_loss": round(gain_loss, 2),
            })
            prev_value = total_value

        return result
