"""
scripts/migrate_fidelity_to_db.py — Migrate Fidelity CSV data to SQLite.

Reads data/fidelity/daily_portfolio_snapshot.csv and bulk-inserts
per-ticker daily holdings into the investment_holdings table.
Also updates portfolio_snapshots with daily totals.

Usage:
    python scripts/migrate_fidelity_to_db.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
from dal.database import init_db, get_db
from dal.investments import upsert_holding

ACCOUNT_ID = "fidelity_0827"
CSV_PATH = ROOT / "data" / "fidelity" / "daily_portfolio_snapshot.csv"


def main():
    if not CSV_PATH.exists():
        print(f"  ✗  CSV not found: {CSV_PATH}")
        sys.exit(1)

    init_db()
    df = pd.read_csv(CSV_PATH)
    print(f"  📊  Loaded {len(df)} rows × {len(df.columns)} cols from Fidelity CSV")

    # Identify ticker columns: *_Shares, *_ClosePrice, *_Value, *_CostBasis
    share_cols = [c for c in df.columns if c.endswith("_Shares")]
    tickers = [c.replace("_Shares", "") for c in share_cols]
    print(f"  📈  Found {len(tickers)} tickers: {', '.join(tickers)}")

    total_upserted = 0

    with get_db() as conn:
        for _, row in df.iterrows():
            date = str(row["Date"])

            for ticker in tickers:
                shares = row.get(f"{ticker}_Shares", 0)
                if pd.isna(shares) or shares == 0:
                    continue

                close_price = row.get(f"{ticker}_ClosePrice")
                if pd.isna(close_price):
                    close_price = None

                market_value = row.get(f"{ticker}_Value")
                if pd.isna(market_value):
                    market_value = (shares * close_price) if close_price else None

                cost_basis = row.get(f"{ticker}_CostBasis")
                if pd.isna(cost_basis):
                    cost_basis = None

                upsert_holding(
                    conn,
                    account_id=ACCOUNT_ID,
                    date=date,
                    ticker=ticker,
                    shares=shares,
                    close_price=close_price,
                    market_value=market_value,
                    cost_basis=cost_basis,
                )
                total_upserted += 1

            # Also record the daily portfolio total as a portfolio_snapshot
            total_val = row.get("Total_Account_Value")
            cash = row.get("Cash_Balance", 0)
            if not pd.isna(total_val):
                # Use ON CONFLICT to avoid duplicates in portfolio_snapshots
                conn.execute(
                    """
                    INSERT OR IGNORE INTO portfolio_snapshots
                        (account_id, timestamp, total_account_value, cash_balance)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        ACCOUNT_ID,
                        date,
                        float(total_val),
                        float(cash) if not pd.isna(cash) else 0.0,
                    ),
                )

        conn.commit()

    print(f"  ✔  Upserted {total_upserted:,} holding records")
    print(f"  ✔  {len(df)} portfolio snapshots written")

    # Verify
    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) c FROM investment_holdings WHERE account_id = ?",
            (ACCOUNT_ID,),
        ).fetchone()["c"]
        dates = conn.execute(
            "SELECT COUNT(DISTINCT date) d FROM investment_holdings WHERE account_id = ?",
            (ACCOUNT_ID,),
        ).fetchone()["d"]
        tickers_count = conn.execute(
            "SELECT COUNT(DISTINCT ticker) t FROM investment_holdings WHERE account_id = ?",
            (ACCOUNT_ID,),
        ).fetchone()["t"]
        print(
            f"\n  📋  Verification: {count:,} rows, {dates} dates, {tickers_count} tickers"
        )


if __name__ == "__main__":
    main()
