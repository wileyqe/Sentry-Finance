"""
dal/allocation.py — Sector and asset class allocation for investment accounts.

Enriches portfolio holdings with sector/industry/asset-class metadata sourced
from yfinance and caches results in the `ticker_metadata` table (Schema V10).

Allocation views:
  - by_sector      : Technology 35%, Healthcare 15%, etc.
  - by_asset_class : US Equity, Int'l Equity, Bonds, Real Estate, Cash, etc.
  - by_account     : Per-account value breakdown (already available from portfolio_snapshots)

Enrichment is lazy: metadata is fetched once per ticker and cached indefinitely
(updated only when explicitly refreshed or when last_updated > 30 days).
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("sentry.dal.allocation")

# How many days before we consider cached metadata stale
METADATA_STALENESS_DAYS = 30

# Well-known ETF → asset class overrides (yfinance doesn't classify ETFs well)
_KNOWN_ASSET_CLASSES = {
    # Cash / Money Market
    "SPAXX": "Cash", "FDRXX": "Cash", "VMFXX": "Cash",
    # US Equity
    "VOO": "US Equity", "VTI": "US Equity", "SPY": "US Equity",
    "QQQ": "US Equity", "IVV": "US Equity", "ITOT": "US Equity",
    "IJH": "US Equity", "IJR": "US Equity", "SCHB": "US Equity",
    "VO": "ETF",
    # International Equity
    "IXUS": "International Equity", "VEA": "International Equity",
    "VWO": "International Equity", "EFA": "International Equity",
    "VXUS": "International Equity",
    # Bonds
    "BND": "Bonds", "AGG": "Bonds", "TLT": "Bonds",
    "LQD": "Bonds", "VCIT": "Bonds", "SCHZ": "Bonds",
    # Real Estate
    "VNQ": "Real Estate", "SCHH": "Real Estate",
    # Commodities
    "GLD": "Commodities", "SLV": "Commodities", "IAU": "Commodities",
    # TSP Funds (mapped by description)
    "G Fund": "Bonds", "F Fund": "Bonds", "C Fund": "US Equity",
    "S Fund": "US Equity", "I Fund": "International Equity",
}

_KNOWN_SECTORS = {
    "SPAXX": "Cash & Money Market", "FDRXX": "Cash & Money Market", "VMFXX": "Cash & Money Market",
    "VOO": "Diversified", "VTI": "Diversified", "SPY": "Diversified",
    "VO": "Diversified", "QQQ": "Technology", "IJH": "Diversified", "IJR": "Diversified",
    "IXUS": "International", "BND": "Fixed Income",
    "VNQ": "Real Estate", "GLD": "Commodities",
}


# ── Metadata Enrichment ────────────────────────────────────────────────────────


def enrich_ticker_metadata(
    conn: sqlite3.Connection,
    tickers: list[str],
    force: bool = False,
) -> dict[str, dict]:
    """
    Fetch and cache sector/industry/asset_class for a list of tickers.

    Uses the `ticker_metadata` table as a cache. Fetches from yfinance only
    if the record is missing or stale (> METADATA_STALENESS_DAYS old), unless
    force=True.

    Returns a dict mapping ticker → metadata dict.
    """
    stale_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=METADATA_STALENESS_DAYS)
    ).strftime("%Y-%m-%d")

    results: dict[str, dict] = {}
    needs_fetch: list[str] = []

    for ticker in tickers:
        row = conn.execute(
            "SELECT * FROM ticker_metadata WHERE ticker = ?", (ticker,)
        ).fetchone()

        if row and not force and (row["last_updated"] or "") >= stale_cutoff:
            results[ticker] = dict(row)
        else:
            needs_fetch.append(ticker)

    if not needs_fetch:
        return results

    # Apply hardcoded overrides first (for ETFs yfinance doesn't classify)
    for ticker in list(needs_fetch):
        if ticker in _KNOWN_ASSET_CLASSES or ticker in _KNOWN_SECTORS:
            asset_class = _KNOWN_ASSET_CLASSES.get(ticker, "Unknown")
            sector = _KNOWN_SECTORS.get(ticker, "Diversified")
            _upsert_ticker_metadata(conn, ticker, sector=sector, asset_class=asset_class)
            results[ticker] = {"ticker": ticker, "sector": sector, "asset_class": asset_class}
            needs_fetch.remove(ticker)

    # Fetch remaining from yfinance
    if needs_fetch:
        try:
            import yfinance as yf

            for ticker in needs_fetch:
                try:
                    info = yf.Ticker(ticker).info
                    sector = info.get("sector", "Unknown")
                    industry = info.get("industry", "Unknown")
                    quote_type = info.get("quoteType", "")

                    # Infer asset class from quote type + sector
                    if quote_type == "ETF":
                        asset_class = _KNOWN_ASSET_CLASSES.get(ticker, "ETF")
                    elif quote_type == "MUTUALFUND":
                        asset_class = "Mutual Fund"
                    elif sector in ("Healthcare", "Technology", "Financials",
                                    "Consumer Cyclical", "Industrials",
                                    "Communication Services", "Consumer Defensive",
                                    "Energy", "Basic Materials", "Real Estate", "Utilities"):
                        asset_class = "US Equity"
                    else:
                        asset_class = "US Equity"

                    _upsert_ticker_metadata(conn, ticker, sector=sector, industry=industry, asset_class=asset_class)
                    results[ticker] = {
                        "ticker": ticker, "sector": sector,
                        "industry": industry, "asset_class": asset_class,
                    }
                    log.info("Enriched %s: sector=%s asset_class=%s", ticker, sector, asset_class)
                except Exception as e:
                    log.warning("Could not enrich %s: %s", ticker, e)
                    _upsert_ticker_metadata(conn, ticker, sector="Unknown", asset_class="Unknown")
                    results[ticker] = {"ticker": ticker, "sector": "Unknown", "asset_class": "Unknown"}

            conn.commit()

        except ImportError:
            log.warning("yfinance not available — cannot enrich ticker metadata")
            for ticker in needs_fetch:
                results[ticker] = {"ticker": ticker, "sector": "Unknown", "asset_class": "Unknown"}

    return results


def _upsert_ticker_metadata(
    conn: sqlite3.Connection,
    ticker: str,
    sector: str = "Unknown",
    industry: Optional[str] = None,
    asset_class: str = "Unknown",
) -> None:
    conn.execute(
        """
        INSERT INTO ticker_metadata (ticker, sector, industry, asset_class, last_updated)
        VALUES (?, ?, ?, ?, date('now'))
        ON CONFLICT(ticker) DO UPDATE SET
            sector = excluded.sector,
            industry = excluded.industry,
            asset_class = excluded.asset_class,
            last_updated = excluded.last_updated
        """,
        (ticker, sector, industry, asset_class),
    )


# ── Allocation Computation ─────────────────────────────────────────────────────


def get_allocation(
    conn: sqlite3.Connection,
    account_ids: Optional[list[str]] = None,
) -> dict:
    """
    Compute portfolio allocation by sector, asset class, and account.

    Uses the latest `investment_holdings` row per ticker per account.
    Enriches with `ticker_metadata` (fetching if needed).

    Returns:
      {
        total_value: float,
        by_sector: [{sector, value, pct}, ...],
        by_asset_class: [{asset_class, value, pct}, ...],
        by_account: [{account_id, name, value, pct}, ...]
      }
    """
    acct_filter = ""
    params: list = []
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        acct_filter = f" AND ih.account_id IN ({placeholders})"
        params.extend(account_ids)

    # Get latest holdings per account + ticker
    rows = conn.execute(
        f"""
        SELECT ih.account_id, ih.ticker, ih.market_value, a.name as account_name
        FROM investment_holdings ih
        JOIN accounts a ON a.id = ih.account_id
        WHERE ih.date = (
            SELECT MAX(date) FROM investment_holdings ih2
            WHERE ih2.account_id = ih.account_id
              AND ih2.ticker = ih.ticker
        )
          AND ih.market_value IS NOT NULL
          AND ih.market_value > 0
          {acct_filter}
        """,
        params,
    ).fetchall()

    if not rows:
        return {
            "total_value": 0,
            "by_sector": [],
            "by_asset_class": [],
            "by_account": [],
        }

    # Get all distinct tickers and enrich
    tickers = list({r["ticker"] for r in rows})
    metadata = enrich_ticker_metadata(conn, tickers)

    # Aggregate
    total_value = 0.0
    sector_map: dict[str, float] = {}
    asset_class_map: dict[str, float] = {}
    account_map: dict[str, dict] = {}

    for r in rows:
        ticker = r["ticker"]
        val = r["market_value"] or 0
        total_value += val

        meta = metadata.get(ticker, {})
        sector = meta.get("sector") or "Unknown"
        asset_class = meta.get("asset_class") or "Unknown"

        sector_map[sector] = sector_map.get(sector, 0) + val
        asset_class_map[asset_class] = asset_class_map.get(asset_class, 0) + val

        acct_id = r["account_id"]
        if acct_id not in account_map:
            account_map[acct_id] = {"account_id": acct_id, "name": r["account_name"], "value": 0}
        account_map[acct_id]["value"] += val

    def _pct(val: float) -> float:
        return round(val / total_value * 100, 1) if total_value > 0 else 0

    by_sector = sorted(
        [{"sector": k, "value": round(v, 2), "pct": _pct(v)} for k, v in sector_map.items()],
        key=lambda x: x["value"], reverse=True,
    )
    by_asset_class = sorted(
        [{"asset_class": k, "value": round(v, 2), "pct": _pct(v)} for k, v in asset_class_map.items()],
        key=lambda x: x["value"], reverse=True,
    )
    by_account = sorted(
        [{"account_id": v["account_id"], "name": v["name"], "value": round(v["value"], 2), "pct": _pct(v["value"])}
         for v in account_map.values()],
        key=lambda x: x["value"], reverse=True,
    )

    return {
        "total_value": round(total_value, 2),
        "by_sector": by_sector,
        "by_asset_class": by_asset_class,
        "by_account": by_account,
    }
