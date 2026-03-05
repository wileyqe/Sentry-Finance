"""
scripts/ingest_tsp.py — TSP (Thrift Savings Plan) ingestion pipeline.

No browser automation.  Statement-driven baseline + API-sourced share prices.

Pipeline:
  1. Parse TSP statement PDF for per-fund unit counts (closing units + NAV)
  2. Fetch daily share prices from MaxTSP API (or local cache)
  3. Build daily portfolio snapshot: units × share_prices
  4. Persist to SQLite (balance_snapshots + portfolio_snapshots)

Usage:
    python scripts/ingest_tsp.py                    # Full run
    python scripts/ingest_tsp.py --parse-only       # Just parse PDF, show positions
    python scripts/ingest_tsp.py --fetch-prices     # Fetch & cache share prices only
"""

import logging
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pdfplumber
import requests
import re

# ── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_exports" / "TSP"
OUT_DIR = BASE_DIR / "data" / "outputs" / "tsp"
PRICE_CACHE = RAW_DIR / "share_prices.csv"

log = logging.getLogger("sentry.scripts.ingest_tsp")

# ── Constants ────────────────────────────────────────────────────────────────

# MaxTSP API — free, no auth, returns current-day TSP fund prices
MAXTSP_API = "https://api.maxtsp.com/funds/prices"

# All TSP fund names (API keys)
ALL_FUNDS = [
    "G Fund",
    "F Fund",
    "C Fund",
    "S Fund",
    "I Fund",
    "L Income",
    "L 2030",
    "L 2035",
    "L 2040",
    "L 2045",
    "L 2050",
    "L 2055",
    "L 2060",
    "L 2065",
    "L 2070",
    "L 2075",
]

TODAY = date.today()


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1 — Parse TSP Statement PDF
# ═══════════════════════════════════════════════════════════════════════════


def find_statement_pdf() -> Path:
    """Find the most recent TSP statement PDF in raw_exports/TSP/."""
    pdfs = sorted(RAW_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not pdfs:
        print("FATAL: No TSP statement PDF found in raw_exports/TSP/")
        sys.exit(1)
    print(f"  ✓ Using statement: {pdfs[0].name}")
    return pdfs[0]


def parse_statement(pdf_path: Path) -> dict:
    """Parse a TSP statement PDF and extract per-fund positions.

    Extracts from the 'Activity Detail by Fund' table (typically page 3):
      - Fund names
      - Closing Units (share count)
      - Unit Price (NAV)
      - Closing Balance ($)
      - Statement date range

    Returns:
        {
            'statement_date': date,       # End date of statement period
            'total_balance': float,
            'funds': {
                'L 2065': {'units': 1830.661, 'nav': 20.1575, 'balance': 36901.55},
                'C Fund': {'units': 802.341, 'nav': 103.6295, 'balance': 83146.22},
                ...
            }
        }
    """
    print("\n" + "=" * 70)
    print("STEP 1: Parsing TSP Statement PDF")
    print("=" * 70)

    result = {
        "statement_date": None,
        "total_balance": 0.0,
        "funds": {},
    }

    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    # ── Extract statement end date ─────────────────────────────────────
    # Look for "Account Summary MM-DD-YYYY to MM-DD-YYYY"
    date_match = re.search(
        r"Account Summary\s+\d{2}-\d{2}-\d{4}\s+to\s+(\d{2}-\d{2}-\d{4})",
        full_text,
    )
    if date_match:
        end_str = date_match.group(1)
        result["statement_date"] = datetime.strptime(end_str, "%m-%d-%Y").date()
        print(f"  ✓ Statement end date: {result['statement_date']}")
    else:
        print("  ⚠ Could not extract statement date, defaulting to today")
        result["statement_date"] = TODAY

    # ── Extract total closing balance ──────────────────────────────────
    closing_match = re.search(
        r"Closing Balance\s+\$([\d,]+\.\d{2})",
        full_text,
    )
    if closing_match:
        result["total_balance"] = _clean_number(closing_match.group(1))
        print(f"  ✓ Total closing balance: ${result['total_balance']:,.2f}")

    # ── Extract per-fund data from Activity Detail table ───────────────
    # Pattern: "Closing Units  <number>" and "Unit Price (NAV) <number>"
    # The table on page 3 has columns per fund.
    #
    # We parse by finding fund names and their associated units/NAV lines.
    # Fund names in TSP: L 20xx, C Fund, S Fund, I Fund, F Fund, G Fund

    # Strategy: extract structured data from page 3 tables
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "Activity Detail by Fund" not in text:
                continue

            # Extract fund columns from the "Fund Name" header row
            # Then get Closing Balance, Closing Units, Unit Price per column
            _parse_activity_detail(text, result)
            break

    # Print summary
    print(f"\n  ── TSP Positions (as of {result['statement_date']}) ──")
    for fund, data in result["funds"].items():
        print(
            f"    {fund:12s}: {data['units']:>12,.3f} units × "
            f"${data['nav']:>10,.4f} = ${data['balance']:>12,.2f}"
        )

    computed_total = sum(d["balance"] for d in result["funds"].values())
    print(f"\n    {'Total':12s}: ${computed_total:>36,.2f}")
    if abs(computed_total - result["total_balance"]) > 0.10:
        print(
            f"    ⚠ Discrepancy with statement total: ${result['total_balance']:,.2f}"
        )

    return result


def _parse_activity_detail(text: str, result: dict) -> None:
    """Parse the Activity Detail by Fund table text.

    The table has this structure (columnwise per fund):
        Fund Name       All Funds Total  L 2065    C Fund    S Fund
        Opening Balance $X         $X     $X        $X
        Gains/Losses    $X         $X     $X        $X
        Closing Balance $X         $X     $X        $X
        Closing Units              X      X         X
        Unit Price (NAV)           X      X         X
    """
    lines = text.split("\n")

    # Find the fund names from the "Fund Name" header line
    fund_names = []
    for line in lines:
        if "Fund Name" in line:
            # Extract fund names from this line
            # They appear after "All Funds Total" as column headers
            parts = line.split("All Funds Total")
            if len(parts) > 1:
                # Parse the fund names from the remainder
                remainder = parts[1].strip()
                # TSP fund names: L 20XX, C Fund, S Fund, etc.
                names = re.findall(r"(L\s+\d{4}|[GCFSI]\s+Fund|L\s+Income)", remainder)
                fund_names = names
            break

    if not fund_names:
        log.warning("Could not find fund names in Activity Detail table")
        return

    print(f"  ✓ Funds found: {fund_names}")

    # Extract Closing Balance, Closing Units, Unit Price (NAV) rows
    closing_balances = []
    closing_units = []
    nav_prices = []

    for line in lines:
        # Match "Closing Balance" line — has $ amounts
        if line.strip().startswith("Closing Balance"):
            amounts = re.findall(r"\$([\d,]+\.\d{2})", line)
            if amounts:
                # First amount is "All Funds Total", rest are per-fund
                closing_balances = [_clean_number(a) for a in amounts[1:]]

        # Match "Closing Units" line — has unit counts (no $)
        elif "Closing Units" in line:
            units = re.findall(r"([\d,]+\.\d{3})", line)
            closing_units = [_clean_number(u) for u in units]

        # Match "Unit Price (NAV)" line — has prices (no $)
        elif "Unit Price (NAV)" in line:
            prices = re.findall(r"(\d+\.\d{4,6})", line)
            nav_prices = [float(p) for p in prices]

    # Assemble per-fund data
    for i, fund in enumerate(fund_names):
        result["funds"][fund] = {
            "units": closing_units[i] if i < len(closing_units) else 0.0,
            "nav": nav_prices[i] if i < len(nav_prices) else 0.0,
            "balance": closing_balances[i] if i < len(closing_balances) else 0.0,
        }


def _clean_number(val: str) -> float:
    """Strip $, commas, whitespace and return float. Returns 0.0 for empty."""
    if not val:
        return 0.0
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except ValueError:
        return 0.0


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — Fetch TSP Share Prices
# ═══════════════════════════════════════════════════════════════════════════


def fetch_share_prices(start_date: date, end_date: date) -> pd.DataFrame:
    """Fetch TSP share prices and return a DataFrame indexed by date.

    Strategy:
      1. Load any locally cached prices (share_prices.csv)
      2. Fetch today's price from MaxTSP API and append
      3. Return the merged set covering start_date → end_date

    If the cache doesn't cover the full range, prints a warning
    with instructions for the one-time browser download.
    """
    print("\n" + "=" * 70)
    print("STEP 2: Loading TSP Share Prices")
    print("=" * 70)

    frames = []

    # ── Load cached prices ─────────────────────────────────────────────
    if PRICE_CACHE.exists():
        cached = pd.read_csv(PRICE_CACHE)
        # Normalize column name: TSP.gov uses "Date", API uses "date"
        if "Date" in cached.columns:
            cached = cached.rename(columns={"Date": "date"})
        # Parse dates — TSP uses "Mar 4, 2026" format, API uses "2026-03-04"
        cached["date"] = pd.to_datetime(cached["date"], format="mixed")
        cached = cached.set_index("date").sort_index()
        # Drop any non-trading days (NaN rows)
        cached = cached.dropna(how="all")
        frames.append(cached)
        print(
            f"  ✓ Cache: {len(cached)} days "
            f"({cached.index.min().date()} → {cached.index.max().date()})"
        )

    # ── Fetch today from MaxTSP API ────────────────────────────────────
    try:
        r = requests.get(MAXTSP_API, timeout=15)
        if r.status_code == 200:
            data = r.json()
            today_prices = {}
            for date_str, funds in data.items():
                today_prices = funds
                break  # API returns single-day dict
            if today_prices:
                row = pd.DataFrame([today_prices])
                row["date"] = pd.Timestamp(TODAY)
                row = row.set_index("date")
                frames.append(row)
                print(f"  ✓ API: fetched {TODAY} prices for {len(today_prices)} funds")
        else:
            log.warning("MaxTSP API returned status %d", r.status_code)
    except Exception as e:
        log.warning("MaxTSP API error: %s", e)
        print(f"  ⚠ API fetch failed: {e}")

    # ── Merge ──────────────────────────────────────────────────────────
    if not frames:
        print("  ❌ No share price data available!")
        print("  ℹ  To seed historical prices, download from tsp.gov:")
        print("     1. Visit https://www.tsp.gov/fund-performance/share-price-history/")
        print("     2. Select all funds, date range, click 'Download results'")
        print(f"     3. Save as: {PRICE_CACHE}")
        return pd.DataFrame()

    prices = pd.concat(frames)
    prices = prices[~prices.index.duplicated(keep="last")]
    prices = prices.sort_index()

    # Check coverage
    actual_start = prices.index.min().date()
    actual_end = prices.index.max().date()

    if actual_start > start_date:
        gap_days = (actual_start - start_date).days
        print(f"\n  ⚠ Missing {gap_days} days of history before {actual_start}")
        print(f"     Need prices from {start_date} to {actual_start}")
        print("     → Download from tsp.gov and save to share_prices.csv")

    # Save updated cache
    prices.to_csv(PRICE_CACHE)
    print(f"\n  ✓ Price data: {len(prices)} days ({actual_start} → {actual_end})")

    return prices


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — Build Daily Portfolio Snapshot
# ═══════════════════════════════════════════════════════════════════════════


def build_daily_snapshot(
    positions: dict, prices: pd.DataFrame, start_date: date
) -> pd.DataFrame:
    """Build a day-by-day portfolio snapshot from positions × prices.

    Args:
        positions: dict from parse_statement()
        prices: DataFrame with daily share prices per fund
        start_date: first day of the snapshot (statement date)

    Returns:
        DataFrame with columns: Date, per-fund values, Total
    """
    print("\n" + "=" * 70)
    print("STEP 3: Building Daily Portfolio Snapshot")
    print("=" * 70)

    funds = positions["funds"]
    stmt_date = positions["statement_date"]

    # Build a date range from statement date → today
    date_range = pd.date_range(start=stmt_date, end=TODAY, freq="D")
    snapshot = pd.DataFrame({"Date": date_range})
    snapshot = snapshot.set_index("Date")

    total_value = pd.Series(0.0, index=snapshot.index)

    for fund_name, fund_data in funds.items():
        units = fund_data["units"]

        # Map fund name to price column
        # Statement uses "L 2065", API uses "L 2065" — should match directly
        price_col = fund_name

        if price_col in prices.columns:
            # Align prices to our date range, forward-fill weekends/holidays
            fund_prices = prices[price_col].reindex(snapshot.index).ffill().bfill()
            fund_values = units * fund_prices
        else:
            log.warning("No price data for fund '%s'", fund_name)
            # Use the statement NAV as a flat price
            fund_values = pd.Series(units * fund_data["nav"], index=snapshot.index)

        col_shares = f"{fund_name}_Units"
        col_price = f"{fund_name}_Price"
        col_value = f"{fund_name}_Value"

        snapshot[col_shares] = units
        snapshot[col_price] = (
            fund_prices if price_col in prices.columns else fund_data["nav"]
        )
        snapshot[col_value] = fund_values.round(2)

        total_value += fund_values

    snapshot["Total_Value"] = total_value.round(2)

    # Reset index for clean output
    snapshot = snapshot.reset_index()
    snapshot = snapshot.rename(columns={"index": "Date"})

    # Save output
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "daily_portfolio_snapshot.csv"
    snapshot.to_csv(out_path, index=False)

    print(f"  ✓ Snapshot: {len(snapshot)} days ({stmt_date} → {TODAY})")
    print(f"  ✓ Saved: {out_path.name}")

    # Print first and last rows
    value_cols = ["Date", "Total_Value"] + [f"{f}_Value" for f in funds.keys()]
    existing_cols = [c for c in value_cols if c in snapshot.columns]

    print("\n  ── First 3 rows ──")
    print(snapshot[existing_cols].head(3).to_string(index=False))
    print("\n  ── Last 3 rows ──")
    print(snapshot[existing_cols].tail(3).to_string(index=False))

    return snapshot


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4 — Persist to Database
# ═══════════════════════════════════════════════════════════════════════════


def persist_to_db(snapshot: pd.DataFrame, positions: dict) -> None:
    """Write TSP balance to the SQLite database.

    Records the latest portfolio value as a balance snapshot and
    a portfolio_snapshot entry.
    """
    print("\n" + "=" * 70)
    print("STEP 4: Persisting TSP data to SQLite")
    print("=" * 70)

    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

    from dal.database import get_db, init_db, seed_institutions
    from dal.balances import record_balance

    init_db()
    seed_institutions()

    if snapshot.empty:
        print("  ⚠ Empty snapshot — nothing to persist")
        return

    last_row = snapshot.iloc[-1]
    total_value = float(last_row["Total_Value"])
    snap_date = str(last_row["Date"])[:10]
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        # Record total balance for the TSP account
        record_balance(conn, "tsp_7777", total_value, now)

        # Also write a portfolio_snapshot entry
        conn.execute(
            """
            INSERT INTO portfolio_snapshots
                (account_id, timestamp, total_account_value, cash_balance)
            VALUES (?, ?, ?, ?)
            """,
            ("tsp_7777", now, total_value, 0.0),  # No cash in TSP
        )

        conn.commit()

    print(f"  ✓ Recorded TSP balance: ${total_value:,.2f} as of {snap_date}")

    # Per-fund breakdown
    for fund_name, fund_data in positions["funds"].items():
        val_col = f"{fund_name}_Value"
        if val_col in last_row:
            current_val = float(last_row[val_col])
            print(f"    {fund_name:12s}: ${current_val:>12,.2f}")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="TSP Ingestion — Statement PDF + Share Price API"
    )
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="Only parse the statement PDF; don't fetch prices or build snapshot",
    )
    parser.add_argument(
        "--fetch-prices",
        action="store_true",
        help="Only fetch and cache share prices",
    )
    args = parser.parse_args()

    print("\n  🏛️  TSP Ingestion Pipeline")
    print(f"  ⏰  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()

    # Step 1: Parse statement
    pdf_path = find_statement_pdf()
    positions = parse_statement(pdf_path)

    if args.parse_only:
        print("\n  ✅  Parse-only mode — done.")
        return

    # Step 2: Fetch prices
    prices = fetch_share_prices(
        start_date=positions["statement_date"],
        end_date=TODAY,
    )

    if args.fetch_prices:
        print("\n  ✅  Price fetch mode — done.")
        return

    # Step 3: Build snapshot
    snapshot = build_daily_snapshot(positions, prices, positions["statement_date"])

    # Step 4: Persist
    persist_to_db(snapshot, positions)

    print("\n  ✅  TSP ingestion complete!")


if __name__ == "__main__":
    main()
