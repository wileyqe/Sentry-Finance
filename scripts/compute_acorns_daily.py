"""
scripts/compute_acorns_daily.py — Compute daily Acorns portfolio valuations.

Reads the latest share counts from positions_ledger, fetches daily
closing prices from yfinance, and backfills portfolio_snapshots for
days between scrapes.

Usage:
    python scripts/compute_acorns_daily.py
    python scripts/compute_acorns_daily.py --days 30
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yfinance as yf
import pandas as pd
from dal.database import init_db, get_db

ACCOUNT_ID = "acorns_0000"
TICKERS = ["VOO", "IJH", "IJR", "IXUS"]


def get_share_counts(conn) -> dict:
    """Get latest share counts per ticker from positions_ledger."""
    result = {}
    for ticker in TICKERS:
        row = conn.execute(
            """
            SELECT new_total_shares FROM positions_ledger
            WHERE account_id = ? AND ticker = ?
            ORDER BY timestamp DESC LIMIT 1
        """,
            (ACCOUNT_ID, ticker),
        ).fetchone()
        if row:
            result[ticker] = row["new_total_shares"]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="Days to backfill")
    args = parser.parse_args()

    init_db()

    with get_db() as conn:
        shares = get_share_counts(conn)
        if not shares:
            print("  ✗  No position data found for Acorns")
            sys.exit(1)

        print("  📊  Current Acorns holdings:")
        for ticker, count in shares.items():
            print(f"    {ticker}: {count:.4f} shares")

    # Fetch historical prices
    end_date = datetime.now()
    start_date = end_date - timedelta(days=args.days)

    print(f"\n  📈  Fetching prices for {start_date.date()} → {end_date.date()}...")
    prices_df = yf.download(
        TICKERS,
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
        progress=False,
    )

    if prices_df.empty:
        print("  ✗  No price data returned from yfinance")
        sys.exit(1)

    # yfinance returns multi-level columns when multiple tickers
    close_prices = (
        prices_df["Close"]
        if "Close" in prices_df.columns.get_level_values(0)
        else prices_df
    )

    inserted = 0
    with get_db() as conn:
        for date_idx in close_prices.index:
            date_str = date_idx.strftime("%Y-%m-%d")
            total_value = 0.0
            has_data = False

            for ticker in TICKERS:
                if ticker not in shares:
                    continue
                try:
                    price = float(close_prices.loc[date_idx, ticker])
                    if pd.isna(price):
                        continue
                    total_value += shares[ticker] * price
                    has_data = True
                except (KeyError, TypeError):
                    continue

            if has_data and total_value > 0:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO portfolio_snapshots
                        (account_id, timestamp, total_account_value, cash_balance)
                    VALUES (?, ?, ?, 0.0)
                """,
                    (ACCOUNT_ID, date_str, round(total_value, 2)),
                )
                inserted += 1

        conn.commit()

    print(f"  ✔  Inserted {inserted} daily portfolio snapshots for Acorns")


if __name__ == "__main__":
    main()
