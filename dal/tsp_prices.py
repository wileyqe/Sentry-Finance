"""
dal/tsp_prices.py — TSP share price service.

Provides daily TSP fund prices from two sources:
  - MaxTSP API (current day, no auth)
  - Cached CSV from TSP.gov share price history (historical, no login)

Also provides daily holdings interpolation: for a retired/no-contribution
TSP account, units are constant so portfolio value = units × daily price.
This has been validated penny-accurate against TSP.gov balance history.

Public API:
    fetch_current_prices()                  — today's prices from MaxTSP API
    load_price_history(start, end)          — historical prices from CSV
    upsert_benchmark_prices(conn, prices, date) — write to benchmark_prices table
    interpolate_daily_holdings(conn, ...)   — fill investment_holdings from prices
"""

import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from dal.accounts_config import get_account_id
from dal.owners import redact_account_id_for_logs
from dal.parsers.tsp_statement import _fund_to_ticker

log = logging.getLogger("sentry.dal.tsp_prices")


def _tsp_account_id() -> str:
    return get_account_id("tsp", account_type="retirement") or "tsp_XXXX"

# MaxTSP API — free, no auth, returns current-day TSP fund prices
_MAXTSP_API = "https://api.maxtsp.com/funds/prices"

# Local price cache (downloaded from TSP.gov share price history page)
_BASE_DIR = Path(__file__).resolve().parent.parent
_PRICE_CSV = _BASE_DIR / "raw_exports" / "TSP" / "share-price-history.csv"
_PRICE_CSV_LEGACY = _BASE_DIR / "raw_exports" / "TSP" / "share_prices.csv"

# TSP funds held by the account (map fund-name → canonical ticker)
_HELD_FUNDS = ["L 2065", "C Fund", "S Fund"]


def fetch_current_prices() -> dict[str, float] | None:
    """Fetch today's TSP share prices from the MaxTSP API.

    Returns dict like {"C Fund": 109.43, "S Fund": 103.12, ...}
    or None if the API is unreachable.
    """
    try:
        r = requests.get(_MAXTSP_API, timeout=15)
        if r.status_code != 200:
            log.warning("[tsp_prices] MaxTSP API returned %d", r.status_code)
            return None
        data = r.json()
        # API returns {"2026-04-10": {"G Fund": 19.81, ...}}
        for _date_key, funds in data.items():
            return funds
        return None
    except Exception as e:
        log.warning("[tsp_prices] MaxTSP API error: %s", e)
        return None


def load_price_history(
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """Load TSP share prices from the local CSV cache.

    Handles both TSP.gov format ("Mar 4, 2024") and ISO format ("2024-03-04").
    Returns DataFrame indexed by date with fund-name columns, sorted ascending.
    Weekends/holidays are forward-filled.
    """
    csv_path = _PRICE_CSV if _PRICE_CSV.exists() else _PRICE_CSV_LEGACY
    if not csv_path.exists():
        log.warning("[tsp_prices] No price CSV found at %s", _PRICE_CSV)
        return pd.DataFrame()

    df = pd.read_csv(csv_path)
    # Normalize date column name
    if "Date" in df.columns:
        df = df.rename(columns={"Date": "date"})
    df["date"] = pd.to_datetime(df["date"], format="mixed")
    df = df.sort_values("date").set_index("date")
    df = df[~df.index.duplicated(keep="last")]

    # Filter to requested range
    if start_date:
        df = df[df.index >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df.index <= pd.Timestamp(end_date)]

    return df


def upsert_benchmark_prices(
    conn: sqlite3.Connection,
    fund_prices: dict[str, float],
    price_date: str,
) -> int:
    """Write TSP fund prices to the benchmark_prices table.

    Args:
        fund_prices: {"C Fund": 109.43, "S Fund": 103.12, ...}
        price_date: ISO date string ("2026-04-10")

    Returns number of rows upserted.
    """
    count = 0
    for fund_name, price in fund_prices.items():
        ticker = _fund_to_ticker(fund_name)
        conn.execute(
            """INSERT OR REPLACE INTO benchmark_prices
                   (ticker, price_date, close_price)
               VALUES (?, ?, ?)""",
            (ticker, price_date, price),
        )
        count += 1
    return count


def interpolate_daily_holdings(
    conn: sqlite3.Connection,
    account_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> int:
    """Fill investment_holdings rows using constant units × daily prices.

    Reads the most recent per-fund unit counts from investment_holdings
    (statement-anchored), then for each trading day in the price CSV,
    writes a holdings row with units × that day's price.

    Validated penny-accurate against TSP.gov balance history.

    Returns number of rows written.
    """
    if account_id is None:
        account_id = _tsp_account_id()
    # Get the anchor units (most recent statement-based holdings)
    anchor_date = conn.execute(
        "SELECT MAX(date) FROM investment_holdings WHERE account_id = ?",
        (account_id,),
    ).fetchone()[0]

    if not anchor_date:
        log.warning(
            "[tsp_prices] No anchor holdings found for %s",
            redact_account_id_for_logs(account_id),
        )
        return 0

    anchor_rows = conn.execute(
        """SELECT ticker, shares FROM investment_holdings
           WHERE account_id = ? AND date = ?""",
        (account_id, anchor_date),
    ).fetchall()

    if not anchor_rows:
        log.warning("[tsp_prices] No holdings rows at anchor date %s", anchor_date)
        return 0

    # Build ticker → units map (ticker is like TSP_C, fund name is like C Fund)
    ticker_units = {row["ticker"]: row["shares"] for row in anchor_rows}

    # Build reverse map: ticker → fund name (for price CSV column lookup)
    ticker_to_fund = {}
    for fund_name in _HELD_FUNDS:
        ticker_to_fund[_fund_to_ticker(fund_name)] = fund_name
    # Also map any tickers from the anchor that aren't in _HELD_FUNDS
    for ticker in ticker_units:
        if ticker not in ticker_to_fund:
            # Try to find the fund name from the ticker mapping
            for label, t in _get_all_ticker_mappings().items():
                if t == ticker:
                    ticker_to_fund[ticker] = label
                    break

    # Load price history
    prices = load_price_history(start_date, end_date)
    if prices.empty:
        log.warning("[tsp_prices] No price data available for interpolation")
        return 0

    count = 0
    for trade_date, row in prices.iterrows():
        date_str = trade_date.strftime("%Y-%m-%d")
        daily_total = 0.0

        for ticker, units in ticker_units.items():
            fund_name = ticker_to_fund.get(ticker)
            if not fund_name or fund_name not in row.index:
                continue
            price = row[fund_name]
            if pd.isna(price):
                continue
            market_value = units * price

            conn.execute(
                """INSERT OR REPLACE INTO investment_holdings
                       (account_id, date, ticker, shares, close_price,
                        market_value, cost_basis)
                   VALUES (?, ?, ?, ?, ?, ?, NULL)""",
                (account_id, date_str, ticker, units, price, market_value),
            )
            daily_total += market_value
            count += 1

        # Portfolio snapshot for this day (no UNIQUE constraint, so delete first)
        if daily_total > 0:
            ts = date_str + "T16:00:00"
            conn.execute(
                """DELETE FROM portfolio_snapshots
                   WHERE account_id = ? AND timestamp = ?""",
                (account_id, ts),
            )
            conn.execute(
                """INSERT INTO portfolio_snapshots
                       (account_id, timestamp, total_account_value, cash_balance)
                   VALUES (?, ?, ?, 0.0)""",
                (account_id, ts, daily_total),
            )

    log.info(
        "[tsp_prices] Interpolated %d holdings rows (%s to %s)",
        count,
        prices.index.min().date() if not prices.empty else "?",
        prices.index.max().date() if not prices.empty else "?",
    )
    return count


def _get_all_ticker_mappings() -> dict[str, str]:
    """Return all known fund label → ticker mappings."""
    from dal.parsers.tsp_statement import _TSP_FUND_TICKERS
    return dict(_TSP_FUND_TICKERS)
