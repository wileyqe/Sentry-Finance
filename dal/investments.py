"""
dal/investments.py — Read functions for investment holdings, activity,
performance, tax lots, and allocation.

Public API:
    get_holdings(conn, owner_id=None)          — current per-ticker positions per account
    get_activity(conn, account_id, months)     — recent investment activity
    get_performance(conn, account_id, timeframe) — value time-series with adaptive granularity
    get_lots(conn, account_id, ticker)         — FIFO tax lot detail
    get_allocation(conn, owner_id=None)        — aggregated allocation by sector/geo/cap
    get_tax_buckets(conn, account_id)          — tax bucket balances for mixed accounts
    get_tax_summary(conn, owner_id=None)       — portfolio-wide tax treatment breakdown
"""

import logging
import sqlite3
from datetime import date, timedelta

from dal.clock import reference_date
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
        f"""SELECT a.id, a.name, a.institution_id, a.type, a.is_synthetic,
                   a.tax_status
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
            "is_synthetic": acct["is_synthetic"],
            "tax_status": acct["tax_status"],
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
        days_held = (today - lot_date).days
        result.append({
            "date": lot["date"],
            "quantity": round(lot["remaining_shares"], 5),
            "cost_basis": lot["cost_basis"],
            "current_value": round(current_value, 2) if current_value else None,
            "gain_loss": round(gain_loss, 2) if gain_loss is not None else None,
            "holding_period_days": days_held,
            "is_long_term": days_held >= 365,
        })

    return result


def get_allocation(
    conn: sqlite3.Connection,
    owner_id: str | None = None,
    account_id: str | None = None,
    lookthrough: bool = False,
) -> dict:
    """Return aggregated allocation data across investment accounts.

    When account_id is provided, narrows to that single account.
    Joins ticker_metadata for sector, industry, asset_class.

    When lookthrough=True, decomposes funds/ETFs via fund_composition
    into underlying asset-class exposures (e.g. TSP_C + VOO merge into
    "US Large Cap Equity").  Also returns sunburst, treemap_lookthrough,
    and stacked_bars keys for enhanced visualization.

    Returns: by_asset_class, by_sector, by_market_cap, cash_total,
             and (when lookthrough) treemap_lookthrough, sunburst, stacked_bars.
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
                   tm.sector, tm.industry, tm.asset_class,
                   a.id AS account_id, a.name AS account_name
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

    # by_market_cap — use fund_composition.cap_class, then ticker_metadata fallback
    # Load cap_class from fund_composition (deduplicated: take first match per ticker)
    _fc_cap_rows = conn.execute(
        "SELECT ticker, cap_class FROM fund_composition WHERE cap_class IS NOT NULL"
    ).fetchall()
    _fc_cap_map: dict[str, str] = {}
    for fcr in _fc_cap_rows:
        if fcr["ticker"] not in _fc_cap_map:
            _fc_cap_map[fcr["ticker"]] = fcr["cap_class"]
    cap_map: dict[str, float] = {}
    for r in rows:
        if r["ticker"] in CASH_EQUIVALENTS:
            continue
        cap = _fc_cap_map.get(r["ticker"])
        if not cap:
            # Fallback: ETFs as Blend/Index, equities as Large Cap
            cap = "Large Cap" if r["asset_class"] == "ETF" else "Large Cap"
        cap_map[cap] = cap_map.get(cap, 0) + (r["market_value"] or 0)
    by_market_cap = sorted(
        [{"name": c, "amount": round(v, 2), "pct": round(v / total_value * 100, 1)}
         for c, v in cap_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )

    # by_geography — use fund_composition geography weights when available,
    # otherwise assume US for domestic equities/ETFs
    _fc_geo_rows = conn.execute(
        "SELECT ticker, geography, weight FROM fund_composition WHERE geography IS NOT NULL"
    ).fetchall()
    _fc_geo_map: dict[str, list[tuple[str, float]]] = {}
    for fcr in _fc_geo_rows:
        _fc_geo_map.setdefault(fcr["ticker"], []).append((fcr["geography"], fcr["weight"]))
    _GEO_LABELS = {"US": "United States", "Developed Intl": "Developed Int'l",
                    "Emerging Markets": "Emerging Markets"}
    geo_map: dict[str, float] = {}
    for r in rows:
        if r["ticker"] in CASH_EQUIVALENTS:
            continue
        mv = r["market_value"] or 0
        fc_entries = _fc_geo_map.get(r["ticker"])
        if fc_entries:
            for geo_raw, weight in fc_entries:
                label = _GEO_LABELS.get(geo_raw, geo_raw)
                geo_map[label] = geo_map.get(label, 0) + mv * weight
        else:
            geo_map["United States"] = geo_map.get("United States", 0) + mv
    if total_cash > 0:
        geo_map["United States"] = geo_map.get("United States", 0) + total_cash
    by_geography = sorted(
        [{"name": g, "amount": round(v, 2), "pct": round(v / total_value * 100, 1)}
         for g, v in geo_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )

    # treemap — individual holdings (include account_name for drill-down)
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
            "account_name": r["account_name"] or "Unknown",
        })
    if total_cash > 0:
        treemap.append({
            "ticker": "CASH",
            "size": round(total_cash, 2),
            "pct": round(total_cash / total_value * 100, 1),
            "asset_class": "Cash / Equivalents",
            "sector": "Cash",
        })

    result = {
        "by_asset_class": by_asset_class,
        "by_sector": by_sector,
        "by_geography": by_geography,
        "by_market_cap": by_market_cap,
        "treemap": treemap,
        "cash_total": round(total_cash, 2),
        "total_value": round(total_value, 2),
    }

    if not lookthrough:
        return result

    # ── Look-through decomposition ──────────────────────────────────
    # Load full fund_composition table for decomposition
    fc_rows = conn.execute(
        "SELECT ticker, asset_class, weight, geography, cap_class FROM fund_composition"
    ).fetchall()
    fc_map: dict[str, list[dict]] = {}
    for fcr in fc_rows:
        fc_map.setdefault(fcr["ticker"], []).append({
            "asset_class": fcr["asset_class"],
            "weight": fcr["weight"],
            "geography": fcr["geography"],
            "cap_class": fcr["cap_class"],
        })

    # Decompose each holding → asset class buckets
    lt_class_map: dict[str, float] = {}          # merged asset class → dollar
    lt_class_sources: dict[str, dict[str, float]] = {}  # asset class → {ticker: amount}
    # sunburst: account → asset class → sources
    sb_map: dict[str, dict[str, dict[str, float]]] = {}  # account → {asset_class → {ticker: $}}
    # stacked_bars: account → {asset_class → dollar}
    sb_acct_totals: dict[str, float] = {}

    # Also build look-through geography and market cap
    lt_geo_map: dict[str, float] = {}
    lt_cap_map: dict[str, float] = {}

    for r in rows:
        ticker = r["ticker"]
        if ticker in CASH_EQUIVALENTS:
            continue
        mv = r["market_value"] or 0
        acct_name = r["account_name"] or "Unknown Account"
        sb_acct_totals[acct_name] = sb_acct_totals.get(acct_name, 0) + mv

        compositions = fc_map.get(ticker)
        if compositions:
            # Decompose via fund_composition weights
            for comp in compositions:
                ac = comp["asset_class"]
                amt = mv * comp["weight"]
                lt_class_map[ac] = lt_class_map.get(ac, 0) + amt
                lt_class_sources.setdefault(ac, {})[ticker] = (
                    lt_class_sources.setdefault(ac, {}).get(ticker, 0) + amt
                )
                sb_map.setdefault(acct_name, {}).setdefault(ac, {})[ticker] = (
                    sb_map.setdefault(acct_name, {}).setdefault(ac, {}).get(ticker, 0) + amt
                )
                # Geography
                geo_label = _GEO_LABELS.get(comp["geography"], comp["geography"] or "Unknown")
                lt_geo_map[geo_label] = lt_geo_map.get(geo_label, 0) + amt
                # Market cap
                cap = comp["cap_class"] or "Large Cap"
                lt_cap_map[cap] = lt_cap_map.get(cap, 0) + amt
        else:
            # Terminal holding — use ticker_metadata fallback
            ac = r["asset_class"] or "Uncategorized"
            lt_class_map[ac] = lt_class_map.get(ac, 0) + mv
            lt_class_sources.setdefault(ac, {})[ticker] = (
                lt_class_sources.setdefault(ac, {}).get(ticker, 0) + mv
            )
            sb_map.setdefault(acct_name, {}).setdefault(ac, {})[ticker] = (
                sb_map.setdefault(acct_name, {}).setdefault(ac, {}).get(ticker, 0) + mv
            )
            lt_geo_map["United States"] = lt_geo_map.get("United States", 0) + mv
            cap = _fc_cap_map.get(ticker, "Large Cap" if r["asset_class"] == "ETF" else "Large Cap")
            lt_cap_map[cap] = lt_cap_map.get(cap, 0) + mv

    # Add cash
    if total_cash > 0:
        lt_class_map["Cash / Equivalents"] = total_cash
        lt_geo_map["United States"] = lt_geo_map.get("United States", 0) + total_cash

    # Build look-through by_asset_class (replaces the normal one)
    lt_by_asset_class = sorted(
        [{"name": c, "amount": round(v, 2), "pct": round(v / total_value * 100, 1)}
         for c, v in lt_class_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )

    # treemap_lookthrough — asset class cells with source drill-down
    lt_treemap = []
    for ac, amt in sorted(lt_class_map.items(), key=lambda x: x[1], reverse=True):
        sources = [{"ticker": t, "amount": round(a, 2)}
                   for t, a in sorted((lt_class_sources.get(ac) or {}).items(),
                                      key=lambda x: x[1], reverse=True)]
        lt_treemap.append({
            "asset_class": ac,
            "size": round(amt, 2),
            "pct": round(amt / total_value * 100, 1),
            "sources": sources,
        })

    # sunburst — account → asset class → holdings hierarchy
    sunburst = []
    for acct_name in sorted(sb_map.keys()):
        children = []
        for ac, tickers in sorted(sb_map[acct_name].items(),
                                   key=lambda x: sum(x[1].values()), reverse=True):
            ac_total = sum(tickers.values())
            children.append({
                "name": ac,
                "value": round(ac_total, 2),
                "sources": [t for t in tickers.keys()],
            })
        acct_total = sb_acct_totals.get(acct_name, 0)
        sunburst.append({
            "name": acct_name,
            "value": round(acct_total, 2),
            "children": children,
        })

    # stacked_bars — per-account percentage breakdown by asset class
    stacked_bars = []
    for acct_name in sorted(sb_map.keys()):
        acct_total = sb_acct_totals.get(acct_name, 0)
        if acct_total <= 0:
            continue
        bar = {"account": acct_name}
        for ac, tickers in sb_map[acct_name].items():
            bar[ac] = round(sum(tickers.values()) / acct_total * 100, 1)
        stacked_bars.append(bar)

    # Look-through geography
    lt_by_geography = sorted(
        [{"name": g, "amount": round(v, 2), "pct": round(v / total_value * 100, 1)}
         for g, v in lt_geo_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )

    # Look-through market cap
    lt_by_market_cap = sorted(
        [{"name": c, "amount": round(v, 2), "pct": round(v / total_value * 100, 1)}
         for c, v in lt_cap_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )

    # ── Look-through sector decomposition ─────────────────────────────
    # Load fund_sector_weights for direct fund→sector mapping
    sw_rows = conn.execute(
        "SELECT ticker, sector, weight FROM fund_sector_weights"
    ).fetchall()
    sw_map: dict[str, list[tuple[str, float]]] = {}
    for swr in sw_rows:
        sw_map.setdefault(swr["ticker"], []).append((swr["sector"], swr["weight"]))

    # For lifecycle funds (TSP_L2065, TSP_LINCOME): derive sector weights
    # by chaining fund_composition → constituent fund → fund_sector_weights.
    # E.g. L2065 is 52% TSP_C → TSP_C is 32% Technology → L2065 Tech = 0.52*0.32
    # Only need to derive for tickers that have fund_composition rows but NO
    # direct fund_sector_weights rows.
    _FIXED_INCOME_CLASSES = {"US Fixed Income", "US Government Securities"}
    for ticker, comps in fc_map.items():
        if ticker in sw_map:
            continue  # Already has direct sector weights
        derived: dict[str, float] = {}
        for comp in comps:
            ac = comp["asset_class"]
            w = comp["weight"]
            if ac in _FIXED_INCOME_CLASSES:
                continue  # Fixed income has no sector
            # Find which constituent fund this maps to by matching asset class
            # TSP_L2065's "US Large Cap Equity" at 0.52 → comes from TSP_C
            # We need to find the core fund that is 100% this asset class
            for candidate_ticker, candidate_comps in fc_map.items():
                if candidate_ticker == ticker:
                    continue
                if len(candidate_comps) == 1 and candidate_comps[0]["asset_class"] == ac:
                    # Found the single-class fund matching this asset class
                    if candidate_ticker in sw_map:
                        for sector, sw in sw_map[candidate_ticker]:
                            derived[sector] = derived.get(sector, 0) + w * sw
                    break
            else:
                # No matching single-class fund — check if candidate has sector weights
                # and the asset class partially matches (e.g. Small Cap → TSP_S)
                pass  # Lifecycle portions without a clear fund match are skipped
        if derived:
            sw_map[ticker] = [(s, w) for s, w in derived.items()]

    lt_sector_map: dict[str, float] = {}
    for r in rows:
        ticker = r["ticker"]
        if ticker in CASH_EQUIVALENTS:
            continue
        mv = r["market_value"] or 0
        sector_entries = sw_map.get(ticker)
        if sector_entries:
            for sector, weight in sector_entries:
                lt_sector_map[sector] = lt_sector_map.get(sector, 0) + mv * weight
        else:
            # Fallback to ticker_metadata.sector for individual equities
            sector = r["sector"] or "Unknown"
            if sector != "Blend":
                lt_sector_map[sector] = lt_sector_map.get(sector, 0) + mv
            # "Blend" with no sector weights → skip (shouldn't happen with proper data)

    lt_by_sector = sorted(
        [{"name": s, "amount": round(v, 2), "pct": round(v / total_value * 100, 1)}
         for s, v in lt_sector_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )

    result["by_asset_class"] = lt_by_asset_class
    result["by_sector"] = lt_by_sector
    result["by_geography"] = lt_by_geography
    result["by_market_cap"] = lt_by_market_cap
    result["treemap_lookthrough"] = lt_treemap
    result["sunburst"] = sunburst
    result["stacked_bars"] = stacked_bars
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


def _sample_to_granularity(daily: list[dict], granularity: str) -> list[dict]:
    """Post-sample a list of daily {date, total_value} rows to the caller's
    granularity.  Weekly and monthly buckets keep the LAST row in each
    bucket so the line reflects end-of-period value (what the user sees
    as "where my portfolio was at month-end").
    """
    if not daily:
        return []
    if granularity == "daily":
        return daily
    if granularity == "biday":
        return [r for i, r in enumerate(daily) if i % 2 == 0 or i == len(daily) - 1]
    if granularity == "weekly":
        buckets: dict[str, dict] = {}
        for r in daily:
            # ISO year-week key so Dec/Jan crossings bucket correctly
            y, m, d = r["date"].split("-")
            iso = date(int(y), int(m), int(d)).isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
            buckets[key] = r
        return [buckets[k] for k in sorted(buckets.keys())]
    # monthly
    buckets: dict[str, dict] = {}
    for r in daily:
        key = r["date"][:7]  # YYYY-MM
        buckets[key] = r
    return [buckets[k] for k in sorted(buckets.keys())]


def _daily_totals_unfiltered(
    conn: sqlite3.Connection,
    *,
    ih_where: str,
    ih_params: list,
    ps_where: str,
    ps_params: list,
    cutoff: str,
) -> list[dict]:
    """Per-date total portfolio value = SUM(ih.market_value) + most recent
    cash_balance as of that date.  This is the canonical daily series
    used for ALL granularities in the unfiltered path — post-sample via
    _sample_to_granularity for weekly/monthly.

    Cash carry-forward: portfolio_snapshots may snapshot less frequently
    than holdings (e.g. weekly vs. daily).  For each holdings date we use
    the most recent snapshot's cash_balance at-or-before that date so the
    line doesn't dip to zero on days without a snapshot.
    """
    rows = conn.execute(
        f"""SELECT ih.date AS date,
                   SUM(ih.market_value) AS holdings_value
            FROM investment_holdings ih
            WHERE {ih_where} AND ih.date >= ?
            GROUP BY ih.date
            ORDER BY ih.date""",
        ih_params + [cutoff],
    ).fetchall()
    if not rows:
        return []

    cash_snap = conn.execute(
        f"""SELECT substr(ps.timestamp, 1, 10) AS snap_date,
                   SUM(ps.cash_balance) AS cash_balance
            FROM portfolio_snapshots ps
            WHERE {ps_where} AND ps.timestamp >= ?
            GROUP BY snap_date
            ORDER BY snap_date""",
        ps_params + [cutoff],
    ).fetchall()
    cash_by_date = {r["snap_date"]: r["cash_balance"] or 0 for r in cash_snap}
    sorted_cash_dates = sorted(cash_by_date.keys())

    result = []
    for r in rows:
        d = r["date"]
        cash = 0.0
        for cd in sorted_cash_dates:
            if cd <= d:
                cash = cash_by_date[cd]
            else:
                break
        result.append({
            "date": d,
            "total_value": round((r["holdings_value"] or 0) + cash, 2),
        })
    return result


def _enrich_monthly_with_contributions(
    conn: sqlite3.Connection, monthly_rows: list[dict]
) -> list[dict]:
    """For the 'All' (monthly) timeframe, add per-month contributions
    (from transactions tagged 'invest:*') and gain_loss = month-over-month
    value_change minus contributions.  Preserves the legacy response shape
    for this endpoint.
    """
    if not monthly_rows:
        return monthly_rows
    contribs = conn.execute(
        """SELECT strftime('%Y-%m', posting_date) AS month,
                  SUM(amount) AS total_contrib
           FROM transactions
           WHERE transfer_tag LIKE 'invest:%'
             AND direction = 'Debit'
           GROUP BY month""",
    ).fetchall()
    contrib_map = {r["month"]: r["total_contrib"] for r in contribs}

    result = []
    prev_value = 0.0
    for r in monthly_rows:
        month = r["date"][:7]  # YYYY-MM
        total_value = r["total_value"]
        contributions = contrib_map.get(month, 0.0)
        value_change = total_value - prev_value
        gain_loss = value_change - contributions
        result.append({
            "date": r["date"],
            "month": month,
            "total_value": total_value,
            "contributions": round(contributions, 2),
            "gain_loss": round(gain_loss, 2),
        })
        prev_value = total_value
    return result


def _performance_by_asset_class(
    conn: sqlite3.Connection,
    *,
    ih_where: str,
    ih_params: list,
    ps_where: str,
    ps_params: list,
    cutoff: str,
    granularity: str,
    asset_class: str,
    lookthrough: bool,
) -> list[dict]:
    """Build a class-filtered portfolio value time-series.

    Three cases (see plan — lexical-yawning-kazoo):
      A. asset_class == "Cash / Equivalents" → SUM(portfolio_snapshots.cash_balance)
      B. lookthrough=False  → SUM(ih.market_value) filtered by ticker_metadata.asset_class
      C. lookthrough=True   → SUM(ih.market_value * fund_composition.weight)
                              filtered by fund_composition.asset_class

    The SQL always returns daily-grain rows; _sample_to_granularity then
    down-samples to the caller's granularity.
    """
    if asset_class == "Cash / Equivalents":
        # Case A — cash comes from portfolio_snapshots, not holdings.
        rows = conn.execute(
            f"""SELECT substr(ps.timestamp, 1, 10) AS date,
                       SUM(ps.cash_balance) AS total_value
                FROM portfolio_snapshots ps
                WHERE {ps_where} AND ps.timestamp >= ?
                GROUP BY date
                ORDER BY date""",
            ps_params + [cutoff],
        ).fetchall()
    elif lookthrough:
        # Case C — weighted decomposition via fund_composition.
        rows = conn.execute(
            f"""SELECT ih.date AS date,
                       SUM(ih.market_value * fc.weight) AS total_value
                FROM investment_holdings ih
                JOIN fund_composition fc ON fc.ticker = ih.ticker
                WHERE {ih_where}
                  AND ih.date >= ?
                  AND fc.asset_class = ?
                GROUP BY ih.date
                ORDER BY ih.date""",
            ih_params + [cutoff, asset_class],
        ).fetchall()
    else:
        # Case B — raw ticker classification via ticker_metadata.
        rows = conn.execute(
            f"""SELECT ih.date AS date,
                       SUM(ih.market_value) AS total_value
                FROM investment_holdings ih
                LEFT JOIN ticker_metadata tm ON tm.ticker = ih.ticker
                WHERE {ih_where}
                  AND ih.date >= ?
                  AND COALESCE(tm.asset_class, 'Unknown') = ?
                GROUP BY ih.date
                ORDER BY ih.date""",
            ih_params + [cutoff, asset_class],
        ).fetchall()

    daily = [
        {"date": r["date"], "total_value": round(r["total_value"] or 0.0, 2)}
        for r in rows
    ]
    return _sample_to_granularity(daily, granularity)


def get_performance(
    conn: sqlite3.Connection,
    account_id: str | None = None,
    timeframe: str = "All",
    owner_id: str | None = None,
    asset_class: str | None = None,
    lookthrough: bool = False,
) -> list[dict]:
    """Return portfolio value time-series with adaptive granularity.

    When account_id is None or "all", aggregates across all investment
    accounts (optionally filtered by owner_id).  Uses investment_holdings
    for daily/biday resolution and portfolio_snapshots for weekly/monthly.

    When asset_class is set, filters the series to that class only.  Pass
    lookthrough=True to decompose fund holdings via fund_composition (matches
    the look-through math used by get_allocation).  Result rows keep the
    same {date, total_value} shape so callers do not need to branch.
    """
    config = _TIMEFRAME_CONFIG.get(timeframe, _TIMEFRAME_CONFIG["All"])
    granularity = config["granularity"]

    ref_date = reference_date(conn)
    if timeframe == "YTD":
        cutoff = date(ref_date.year, 1, 1).isoformat()
    elif config["days"] is not None:
        cutoff = (ref_date - timedelta(days=config["days"])).isoformat()
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

    # Asset-class filtered path: rebuild series from holdings (three SQL
    # cases depending on cash / lookthrough), then down-sample.
    if asset_class is not None:
        return _performance_by_asset_class(
            conn,
            ih_where=ih_where, ih_params=ih_params,
            ps_where=ps_where, ps_params=ps_params,
            cutoff=cutoff,
            granularity=granularity,
            asset_class=asset_class,
            lookthrough=lookthrough,
        )

    # Unfiltered path: single source of truth is the daily holdings + cash
    # series, post-sampled to the requested granularity.  This replaces the
    # previous three forked paths (daily/biday direct, weekly from
    # portfolio_snapshots, monthly from portfolio_snapshots GROUP BY YYYY-MM)
    # — the monthly path was double-counting by pooling every snapshot of
    # every account in a month and summing their per-account values.
    daily = _daily_totals_unfiltered(
        conn,
        ih_where=ih_where, ih_params=ih_params,
        ps_where=ps_where, ps_params=ps_params,
        cutoff=cutoff,
    )
    sampled = _sample_to_granularity(daily, granularity)

    if granularity == "monthly":
        return _enrich_monthly_with_contributions(conn, sampled)
    return sampled


# ── Tax treatment ──────────────────────────────────────────────────────────


def get_tax_buckets(
    conn: sqlite3.Connection,
    account_id: str,
) -> list[dict]:
    """Return latest tax bucket balances for a mixed-tax account (e.g. TSP).

    Returns list of dicts: {bucket_type, balance, vested_pct, as_of}.
    Balance is in dollars (converted from stored cents).
    """
    latest = conn.execute(
        "SELECT MAX(as_of) FROM tax_buckets WHERE account_id = ?",
        (account_id,),
    ).fetchone()[0]

    if not latest:
        return []

    rows = conn.execute(
        """SELECT bucket_type, balance, vested_pct, as_of
           FROM tax_buckets
           WHERE account_id = ? AND as_of = ?
           ORDER BY bucket_type""",
        (account_id, latest),
    ).fetchall()

    total_cents = sum(r["balance"] for r in rows)

    return [
        {
            "bucket_type": r["bucket_type"],
            "balance": round(r["balance"] / 100, 2),
            "pct": round(r["balance"] / total_cents * 100, 1) if total_cents > 0 else 0.0,
            "vested_pct": r["vested_pct"],
            "as_of": r["as_of"],
        }
        for r in rows
    ]


def get_tax_summary(
    conn: sqlite3.Connection,
    owner_id: str | None = None,
    account_id: str | None = None,
) -> dict:
    """Aggregate tax treatment breakdown across all investment accounts.

    Returns {by_treatment: [{name, amount, pct}], total}.
    Categories: Tax-Deferred (traditional), Tax-Free (roth), Taxable.
    """
    account_ids = [account_id] if account_id else None
    acct_filter_sql, acct_params = build_account_filter(
        conn, owner_id, account_ids, column="a.id"
    )

    accounts = conn.execute(
        f"""SELECT a.id, a.tax_status
            FROM accounts a
            WHERE a.type IN ('investment', 'retirement')
              AND a.is_active = 1
              AND a.tax_status IS NOT NULL
              {acct_filter_sql}""",
        acct_params,
    ).fetchall()

    buckets = {"Tax-Deferred": 0.0, "Tax-Free": 0.0, "Taxable": 0.0}

    for acct in accounts:
        acct_id = acct["id"]
        tax_status = acct["tax_status"]

        # Get account total value from latest snapshot or holdings
        snap = conn.execute(
            """SELECT total_account_value FROM portfolio_snapshots
               WHERE account_id = ? ORDER BY timestamp DESC LIMIT 1""",
            (acct_id,),
        ).fetchone()
        acct_value = snap["total_account_value"] if snap else 0.0

        if not acct_value:
            # Fall back to summing investment_holdings
            latest = conn.execute(
                "SELECT MAX(date) FROM investment_holdings WHERE account_id = ?",
                (acct_id,),
            ).fetchone()[0]
            if latest:
                row = conn.execute(
                    "SELECT SUM(market_value) AS mv FROM investment_holdings "
                    "WHERE account_id = ? AND date = ?",
                    (acct_id, latest),
                ).fetchone()
                acct_value = row["mv"] or 0.0

        if tax_status == "mixed":
            # Use tax_buckets for breakdown
            tb_rows = conn.execute(
                """SELECT bucket_type, balance
                   FROM tax_buckets
                   WHERE account_id = ? AND as_of = (
                       SELECT MAX(as_of) FROM tax_buckets WHERE account_id = ?
                   )""",
                (acct_id, acct_id),
            ).fetchall()
            if tb_rows:
                for tb in tb_rows:
                    dollars = tb["balance"] / 100
                    if tb["bucket_type"] == "traditional":
                        buckets["Tax-Deferred"] += dollars
                    else:  # roth (includes tax-exempt)
                        buckets["Tax-Free"] += dollars
            else:
                # No bucket data — assume traditional as conservative default
                buckets["Tax-Deferred"] += acct_value
        elif tax_status == "traditional":
            buckets["Tax-Deferred"] += acct_value
        elif tax_status in ("roth", "hsa"):
            buckets["Tax-Free"] += acct_value
        elif tax_status == "taxable":
            buckets["Taxable"] += acct_value

    total = sum(buckets.values())
    by_treatment = []
    for name in ("Tax-Deferred", "Tax-Free", "Taxable"):
        amt = buckets[name]
        if amt > 0:
            by_treatment.append({
                "name": name,
                "amount": round(amt, 2),
                "pct": round(amt / total * 100, 1) if total > 0 else 0.0,
            })

    return {"by_treatment": by_treatment, "total": round(total, 2)}
