"""
scripts/ingest_fidelity_history.py — Fidelity historical data ingestion.

One-shot script that:
  1. Parses Fidelity CSV exports (transaction history + positions snapshot)
  2. Reconstructs daily portfolio holdings from Jan 1, 2024 → today
  3. Over-collects yfinance market data (OHLCV + dividends + splits)
  4. Exports three CSV datasets for downstream dashboard use

Usage:
    python scripts/ingest_fidelity_history.py
"""

import re
import sys
from datetime import date, timedelta
from io import StringIO
from pathlib import Path

import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_exports" / "fidelity"
OUT_DIR = BASE_DIR / "data" / "fidelity"

HISTORY_FILES = sorted(RAW_DIR.glob("History_for_Account_*.csv"))

# Dynamically discover the latest positions snapshot file
_positions_candidates = sorted(
    RAW_DIR.glob("Portfolio_Positions_*.csv"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)
POSITIONS_FILE = _positions_candidates[0] if _positions_candidates else None

# Money-market funds treated as cash equivalents (always $1.00)
CASH_EQUIVALENTS = {"SPAXX", "FDRXX"}

START_DATE = date(2024, 1, 1)
TODAY = date.today()

# yfinance lookback starts a few trading days before our window
YF_START = "2023-12-28"
YF_END = (TODAY + timedelta(days=2)).strftime("%Y-%m-%d")


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1 — Parse Fidelity CSVs
# ═══════════════════════════════════════════════════════════════════════════


def _clean_number(val) -> float:
    """Strip $, commas, and whitespace from a value and return a float.
    Returns 0.0 for empty / unparseable strings."""
    if pd.isna(val):
        return 0.0
    s = str(val).strip().replace("$", "").replace(",", "").replace('"', "")
    if s == "" or s.lower() == "processing":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _classify_action(raw_action: str) -> str:
    """Map verbose Fidelity action strings to canonical categories."""
    a = raw_action.upper().strip()
    if "YOU BOUGHT" in a:
        return "BOUGHT"
    if "REINVESTMENT" in a:
        return "REINVESTMENT"
    if "YOU SOLD" in a:
        return "SOLD"
    if "DIVIDEND RECEIVED" in a or "CAP GAIN" in a:
        return "DIVIDEND"  # cash event only, no share change
    if "ELECTRONIC FUNDS TRANSFER RECEIVED" in a:
        return "DEPOSIT"
    if "ELECTRONIC FUNDS TRANSFER PAID" in a:
        return "WITHDRAWAL"
    if "EXPIRED" in a:
        return "EXPIRED"
    return "OTHER"


def parse_history_csv(filepath: Path) -> pd.DataFrame:
    """Parse a single Fidelity transaction-history CSV.

    Handles:
      - 1-2 blank/metadata rows at the top
      - Disclaimer text at the bottom
      - Comma-formatted currency strings
    """
    raw = filepath.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()

    # Find the header row containing "Run Date"
    header_idx = None
    for i, line in enumerate(lines):
        if "Run Date" in line:
            header_idx = i
            break

    if header_idx is None:
        print(f"  ⚠ Could not find header in {filepath.name}, skipping.")
        return pd.DataFrame()

    # Read from header row onward
    csv_text = "\n".join(lines[header_idx:])
    df = pd.read_csv(StringIO(csv_text), dtype=str)

    # Parse the date column — invalid rows (disclaimers) become NaT
    df["Run Date"] = pd.to_datetime(df["Run Date"], format="%m/%d/%Y", errors="coerce")
    df = df.dropna(subset=["Run Date"])

    if df.empty:
        print(f"  ⚠ No valid rows in {filepath.name}.")
        return df

    # Clean numeric columns
    for col in [
        "Price ($)",
        "Quantity",
        "Commission ($)",
        "Fees ($)",
        "Accrued Interest ($)",
        "Amount ($)",
        "Cash Balance ($)",
    ]:
        if col in df.columns:
            df[col] = df[col].apply(_clean_number)

    # Clean symbol: strip whitespace and asterisks
    df["Symbol"] = df["Symbol"].fillna("").str.strip().str.replace("*", "", regex=False)

    # Classify actions
    df["Action_Type"] = df["Action"].apply(_classify_action)

    print(
        f"  ✓ {filepath.name}: {len(df)} rows, "
        f"{df['Run Date'].min().date()} → {df['Run Date'].max().date()}"
    )
    return df


def parse_positions_csv(filepath: Path) -> pd.DataFrame:
    """Parse the Fidelity portfolio-positions snapshot CSV."""
    df = pd.read_csv(filepath, dtype=str)

    # Strip asterisks from symbols (e.g., SPAXX** → SPAXX)
    df["Symbol"] = df["Symbol"].fillna("").str.strip().str.replace("*", "", regex=False)

    # Clean numeric columns
    for col in [
        "Quantity",
        "Last Price",
        "Current Value",
        "Cost Basis Total",
        "Average Cost Basis",
        "Total Gain/Loss Dollar",
    ]:
        if col in df.columns:
            df[col] = df[col].apply(_clean_number)

    # Drop rows with no symbol (trailing blank rows)
    df = df[df["Symbol"].str.len() > 0]

    print(f"  ✓ {filepath.name}: {len(df)} positions loaded")
    return df


def load_all_data():
    """Load and combine all Fidelity exports."""
    print("=" * 70)
    print("STEP 1: Parsing Fidelity CSV exports")
    print("=" * 70)

    # --- Transaction histories ---
    history_frames = []
    for f in HISTORY_FILES:
        df = parse_history_csv(f)
        if not df.empty:
            history_frames.append(df)

    if not history_frames:
        print("FATAL: No transaction history parsed. Check raw_exports/fidelity/")
        sys.exit(1)

    txns = pd.concat(history_frames, ignore_index=True)
    txns = txns.sort_values("Run Date").reset_index(drop=True)
    print(
        f"\n  Combined transactions: {len(txns)} rows, "
        f"{txns['Run Date'].min().date()} → {txns['Run Date'].max().date()}"
    )

    # --- Positions snapshot ---
    if POSITIONS_FILE is None:
        print("FATAL: No Portfolio_Positions_*.csv found in raw_exports/fidelity/")
        sys.exit(1)
    positions = parse_positions_csv(POSITIONS_FILE)

    # Summary
    all_symbols = set(txns["Symbol"].unique()) | set(positions["Symbol"].unique())
    all_symbols.discard("")
    equity_symbols = all_symbols - CASH_EQUIVALENTS
    print(f"\n  Unique symbols (total): {sorted(all_symbols)}")
    print(f"  Equity symbols (for yfinance): {sorted(equity_symbols)}")

    return txns, positions


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — Reconstruct the Daily Ledger
# ═══════════════════════════════════════════════════════════════════════════


def reconstruct_daily_ledger(txns: pd.DataFrame, positions: pd.DataFrame):
    """Build a day-by-day holdings snapshot from Jan 1, 2024 → today.

    Strategy:
      1. Start from current positions (the snapshot file).
      2. Walk BACKWARD through all transactions to derive Jan 1, 2024 baseline.
      3. Roll FORWARD day-by-day applying transactions to produce daily snapshot.
    """
    print("\n" + "=" * 70)
    print("STEP 2: Reconstructing daily portfolio ledger")
    print("=" * 70)

    # ---- 2a: Extract current holdings from positions file ----
    current_holdings = {}  # symbol → shares (float)
    current_cash = 0.0

    for _, row in positions.iterrows():
        sym = row["Symbol"]
        qty = row["Quantity"]

        if sym in CASH_EQUIVALENTS:
            # SPAXX row: the "Current Value" is the cash balance
            current_cash = _clean_number(row["Current Value"])
            print(f"  Current cash (from {sym}): ${current_cash:,.2f}")
        else:
            current_holdings[sym] = float(qty)

    print(f"  Current equity positions: {len(current_holdings)} tickers")
    for sym in sorted(current_holdings):
        print(f"    {sym}: {current_holdings[sym]:.6f} shares")

    # ---- 2b: Backward pass — unwind transactions to find Jan 1, 2024 baseline ----
    baseline_holdings = dict(current_holdings)  # copy
    baseline_cash = current_cash

    # Sort transactions NEWEST first for the backward walk
    txns_sorted = txns.sort_values("Run Date", ascending=False).copy()

    for _, row in txns_sorted.iterrows():
        sym = row["Symbol"]
        action = row["Action_Type"]
        qty = float(row["Quantity"])
        amount = float(row["Amount ($)"])

        # Skip cash-equivalent shares — they fold into cash balance
        is_cash_eq = sym in CASH_EQUIVALENTS

        if action in ("BOUGHT", "REINVESTMENT"):
            if not is_cash_eq:
                # Undo a purchase: subtract shares (we're going backward)
                baseline_holdings[sym] = baseline_holdings.get(sym, 0.0) - qty
            # Undo cash impact: purchase spent cash, so backward we add it back
            baseline_cash -= amount  # amount is negative for buys, so subtracting adds

        elif action == "SOLD":
            if not is_cash_eq:
                # Undo a sale: add shares back
                baseline_holdings[sym] = baseline_holdings.get(sym, 0.0) + qty
            baseline_cash -= amount  # amount is positive for sales

        elif action == "EXPIRED":
            if not is_cash_eq:
                # Undo an expiration: add shares back
                baseline_holdings[sym] = baseline_holdings.get(sym, 0.0) + qty
            # No cash impact for expirations

        elif action == "DIVIDEND":
            # Cash-only event: undo the dividend income
            baseline_cash -= amount

        elif action == "DEPOSIT":
            # Undo: transfer in → cash was added → subtract
            baseline_cash -= amount

        elif action == "WITHDRAWAL":
            # Undo: transfer out → cash was removed → add back
            baseline_cash -= amount  # amount is negative, so this adds

    # Clean up: remove symbols with ~0 shares (floating point dust)
    baseline_holdings = {
        sym: shares for sym, shares in baseline_holdings.items() if abs(shares) > 1e-9
    }

    print(f"\n  ── Reconstructed baseline (Jan 1, 2024) ──")
    print(f"  Cash: ${baseline_cash:,.2f}")
    for sym in sorted(baseline_holdings):
        print(f"    {sym}: {baseline_holdings[sym]:.6f} shares")

    # ---- 2c: Forward pass — roll day-by-day from baseline ----
    # Index transactions by date for fast lookup
    txns["txn_date"] = txns["Run Date"].dt.date
    txn_by_date = txns.groupby("txn_date")

    # Collect all equity symbols ever held (exclude cash equivalents)
    all_equity_syms = sorted(
        (
            set(baseline_holdings.keys())
            | set(current_holdings.keys())
            | set(
                txns[~txns["Symbol"].isin(CASH_EQUIVALENTS) & (txns["Symbol"] != "")][
                    "Symbol"
                ].unique()
            )
        )
        - CASH_EQUIVALENTS
        - {""}
    )

    # Remove CUSIP-style symbols (like 46185L103) that aren't real tickers
    # They are numeric+alpha codes from expired/delisted stocks
    valid_equity_syms = [s for s in all_equity_syms if not re.match(r"^\d", s)]

    print(f"\n  Symbols tracked in daily ledger: {valid_equity_syms}")

    # Build daily snapshot
    date_range = pd.date_range(start=START_DATE, end=TODAY, freq="D")
    daily_records = []

    holdings = dict(baseline_holdings)
    cash = baseline_cash

    for d in date_range:
        d_date = d.date()

        # Apply any transactions on this date
        if d_date in txn_by_date.groups:
            day_txns = txn_by_date.get_group(d_date)
            for _, row in day_txns.iterrows():
                sym = row["Symbol"]
                action = row["Action_Type"]
                qty = float(row["Quantity"])
                amount = float(row["Amount ($)"])

                is_cash_eq = sym in CASH_EQUIVALENTS

                if action in ("BOUGHT", "REINVESTMENT"):
                    if not is_cash_eq:
                        holdings[sym] = holdings.get(sym, 0.0) + qty
                    cash += amount  # amount is negative for buys

                elif action == "SOLD":
                    if not is_cash_eq:
                        holdings[sym] = holdings.get(sym, 0.0) - qty
                    cash += amount  # amount is positive for sales

                elif action == "EXPIRED":
                    if not is_cash_eq:
                        holdings[sym] = holdings.get(sym, 0.0) - qty

                elif action == "DIVIDEND":
                    cash += amount  # dividend income adds cash

                elif action == "DEPOSIT":
                    cash += amount  # EFT received

                elif action == "WITHDRAWAL":
                    cash += amount  # amount is negative

        # Record today's snapshot
        record = {"Date": d_date, "Cash_Balance": round(cash, 2)}
        for sym in valid_equity_syms:
            record[f"{sym}_Shares"] = round(holdings.get(sym, 0.0), 6)
        daily_records.append(record)

    daily_df = pd.DataFrame(daily_records)
    daily_df["Date"] = pd.to_datetime(daily_df["Date"])

    print(
        f"\n  Daily ledger: {len(daily_df)} days, "
        f"{daily_df['Date'].iloc[0].date()} → {daily_df['Date'].iloc[-1].date()}"
    )

    # Sanity check: compare today's shares to the positions file
    print(f"\n  ── Sanity check: today's shares vs positions file ──")
    for sym in sorted(current_holdings):
        if sym in valid_equity_syms:
            ledger_shares = daily_df.iloc[-1].get(f"{sym}_Shares", 0.0)
            pos_shares = current_holdings[sym]
            match = "✓" if abs(ledger_shares - pos_shares) < 0.01 else "✗ MISMATCH"
            print(
                f"    {sym}: ledger={ledger_shares:.6f}, "
                f"positions={pos_shares:.6f}  {match}"
            )

    return daily_df, valid_equity_syms


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — Over-Collect yfinance Data
# ═══════════════════════════════════════════════════════════════════════════


def fetch_market_data(tickers: list[str]):
    """Download comprehensive market data from yfinance.

    Returns:
        market_df:  DataFrame with OHLCV data (multi-level columns)
        actions_df: DataFrame with dividends and stock splits
    """
    print("\n" + "=" * 70)
    print("STEP 3: Downloading yfinance market data")
    print("=" * 70)
    print(f"  Tickers: {tickers}")
    print(f"  Date range: {YF_START} → {YF_END}")

    # ---- 3a: Bulk OHLCV download ----
    print(f"\n  Downloading OHLCV for {len(tickers)} tickers...")
    try:
        market_df = yf.download(
            tickers,
            start=YF_START,
            end=YF_END,
            auto_adjust=False,  # keep raw + Adj Close
            progress=True,
            threads=True,
        )
    except Exception as e:
        print(f"  ⚠ Bulk download failed: {e}")
        market_df = pd.DataFrame()

    if not market_df.empty:
        print(
            f"  ✓ OHLCV data: {market_df.shape[0]} trading days, "
            f"{market_df.shape[1]} columns"
        )
        # Forward-fill for weekends/holidays
        full_range = pd.date_range(start=YF_START, end=TODAY, freq="D")
        market_df = market_df.reindex(full_range).ffill()
        market_df.index.name = "Date"
        print(f"  ✓ After ffill (calendar days): {len(market_df)} rows")

    # ---- 3b: Per-ticker corporate actions (dividends + splits) ----
    print(f"\n  Fetching dividends & splits per ticker...")
    all_actions = []

    for sym in tickers:
        try:
            ticker_obj = yf.Ticker(sym)
            actions = ticker_obj.actions  # columns: Dividends, Stock Splits
            if actions is not None and not actions.empty:
                # Filter to our date window
                actions = actions.loc[YF_START:YF_END].copy()
                if not actions.empty:
                    actions["Symbol"] = sym
                    all_actions.append(actions)
                    div_count = (actions["Dividends"] > 0).sum()
                    split_count = (actions["Stock Splits"] > 0).sum()
                    print(f"    {sym}: {div_count} dividends, {split_count} splits")
                else:
                    print(f"    {sym}: no events in window")
            else:
                print(f"    {sym}: no corporate actions data")
        except Exception as e:
            print(f"    ⚠ {sym}: failed — {e}")

    if all_actions:
        actions_df = pd.concat(all_actions)
        actions_df.index.name = "Date"
        print(f"\n  ✓ Corporate actions: {len(actions_df)} total events")
    else:
        actions_df = pd.DataFrame(columns=["Dividends", "Stock Splits", "Symbol"])
        actions_df.index.name = "Date"
        print(f"\n  ⚠ No corporate actions found")

    return market_df, actions_df


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4 — Generate Output Datasets
# ═══════════════════════════════════════════════════════════════════════════


def generate_outputs(
    daily_df: pd.DataFrame,
    market_df: pd.DataFrame,
    actions_df: pd.DataFrame,
    equity_syms: list[str],
):
    """Merge ledger with pricing to produce the final output CSVs."""
    print("\n" + "=" * 70)
    print("STEP 4: Generating output datasets")
    print("=" * 70)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 4a: raw_market_data.csv ----
    market_path = OUT_DIR / "raw_market_data.csv"
    if not market_df.empty:
        market_df.to_csv(market_path)
        print(
            f"  ✓ raw_market_data.csv: {market_df.shape[0]} rows × "
            f"{market_df.shape[1]} columns"
        )
    else:
        print(f"  ⚠ raw_market_data.csv: skipped (no data)")

    # ---- 4b: corporate_actions.csv ----
    actions_path = OUT_DIR / "corporate_actions.csv"
    actions_df.to_csv(actions_path)
    print(f"  ✓ corporate_actions.csv: {len(actions_df)} events")

    # ---- 4c: daily_portfolio_snapshot.csv ----
    # For each equity ticker, merge in the Close price and compute daily value
    snapshot = daily_df.copy()
    snapshot = snapshot.set_index("Date")

    # Extract Close prices from the market data (multi-level columns)
    for sym in equity_syms:
        shares_col = f"{sym}_Shares"
        price_col = f"{sym}_ClosePrice"
        value_col = f"{sym}_Value"

        if not market_df.empty:
            try:
                # yfinance multi-ticker download has multi-level columns
                # Format: ('Close', 'AAPL'), etc.
                if isinstance(market_df.columns, pd.MultiIndex):
                    close_series = market_df[("Close", sym)]
                else:
                    # Single ticker case
                    close_series = market_df["Close"]

                # Align to our daily index
                close_aligned = close_series.reindex(snapshot.index).ffill().bfill()
                snapshot[price_col] = close_aligned.round(4)
            except (KeyError, TypeError):
                print(f"    ⚠ No Close price data for {sym}, using NaN")
                snapshot[price_col] = float("nan")
        else:
            snapshot[price_col] = float("nan")

        # Compute daily value = shares × close price
        snapshot[value_col] = (snapshot[shares_col] * snapshot[price_col]).round(2)

    # Total equity value = sum of all ticker values
    value_cols = [f"{sym}_Value" for sym in equity_syms]
    snapshot["Total_Equity_Value"] = snapshot[value_cols].sum(axis=1).round(2)

    # Total account value = equity + cash
    snapshot["Total_Account_Value"] = (
        snapshot["Total_Equity_Value"] + snapshot["Cash_Balance"]
    ).round(2)

    # Reset index for cleaner CSV
    snapshot = snapshot.reset_index()
    snapshot = snapshot.rename(columns={"index": "Date"})

    snapshot_path = OUT_DIR / "daily_portfolio_snapshot.csv"
    snapshot.to_csv(snapshot_path, index=False)
    print(
        f"  ✓ daily_portfolio_snapshot.csv: {len(snapshot)} rows × "
        f"{len(snapshot.columns)} columns"
    )

    # ---- Summary ----
    print(f"\n  ── Output files written to {OUT_DIR} ──")
    for f in OUT_DIR.glob("*.csv"):
        size_kb = f.stat().st_size / 1024
        print(f"    {f.name}: {size_kb:.1f} KB")

    # Print first and last few rows of the snapshot
    print(f"\n  ── Daily Snapshot: First 3 rows ──")
    print(
        snapshot[["Date", "Cash_Balance", "Total_Equity_Value", "Total_Account_Value"]]
        .head(3)
        .to_string(index=False)
    )
    print(f"\n  ── Daily Snapshot: Last 3 rows ──")
    print(
        snapshot[["Date", "Cash_Balance", "Total_Equity_Value", "Total_Account_Value"]]
        .tail(3)
        .to_string(index=False)
    )

    return snapshot


def persist_to_db(snapshot: pd.DataFrame) -> None:
    """Write the latest Fidelity SPAXX cash balance to the SQLite database.

    This ensures the Fidelity cash position (held as SPAXX money market)
    appears alongside NFCU/Chase checking balances in aggregate queries.
    """
    print("\n" + "=" * 70)
    print("STEP 5: Persisting Fidelity cash (SPAXX) to SQLite")
    print("=" * 70)

    # Add project root to path so we can import dal modules
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

    from dal.database import get_db, init_db, seed_institutions
    from dal.balances import record_balance
    from datetime import datetime

    # Ensure schema and Fidelity account exist
    init_db()
    seed_institutions()

    # Get today's cash balance from the snapshot (last row)
    last_row = snapshot.iloc[-1]
    cash_balance = float(last_row["Cash_Balance"])
    snap_date = str(last_row["Date"])[:10]
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        # Record SPAXX cash as a balance snapshot for fidelity_0827
        record_balance(conn, "fidelity_0827", cash_balance, now)
        conn.commit()

    print(f"  ✓ Recorded Fidelity cash (SPAXX): ${cash_balance:,.2f} as of {snap_date}")


def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  Fidelity Historical Data Ingestion Pipeline                    ║")
    print("║  Reconstructing Jan 1, 2024 → Today                            ║")
    print("╚══════════════════════════════════════════════════════════════════╝\n")

    # Step 1: Parse CSVs
    txns, positions = load_all_data()

    # Step 2: Reconstruct daily ledger
    daily_df, equity_syms = reconstruct_daily_ledger(txns, positions)

    # Step 3: Fetch yfinance data
    market_df, actions_df = fetch_market_data(equity_syms)

    # Step 4: Generate outputs
    snapshot = generate_outputs(daily_df, market_df, actions_df, equity_syms)

    # Step 5: Persist SPAXX cash to the DB
    persist_to_db(snapshot)

    print("\n✅ Pipeline complete!")
    return snapshot


if __name__ == "__main__":
    main()
