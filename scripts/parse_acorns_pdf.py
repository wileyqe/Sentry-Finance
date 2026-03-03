"""
scripts/parse_acorns_pdf.py — Acorns statement PDF parser (V2).

Two-phase extraction strategy:
  Phase 1: Baseline snapshot from the oldest statement's Page 2 Asset Allocation.
  Phase 2: Monthly transaction deltas from all subsequent statements' transaction pages.

Stock splits are detected from "Corporate Actions" pages and injected as synthetic ledger entries.

Usage:
    python scripts/parse_acorns_pdf.py --dir "C:/path/to/pdfs"
"""

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

# Ensure the root project directory is in the path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dal.database import get_db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("sentry.pdf_parser")

try:
    import pdfplumber
except ImportError:
    pdfplumber = None
    log.error("pdfplumber is not installed. Run: pip install pdfplumber")

# Known tickers in the Acorns portfolio
KNOWN_TICKERS = {"IJH", "IJR", "IXUS", "VOO"}


# ---------------------------------------------------------------------------
# Phase 1: Baseline Snapshot (oldest statement, Page 2)
# ---------------------------------------------------------------------------
def extract_baseline(pdf_path: Path) -> dict:
    """
    Extract the end-of-month position snapshot from Page 2 (Asset Allocation).
    Returns {ticker: {shares, price, value}} and the statement closing date.
    """
    with pdfplumber.open(pdf_path) as pdf:
        # Get statement closing date from page 1
        page1 = pdf.pages[0].extract_text() or ""
        period_match = re.search(
            r"Statement Period\s+[\d/]+\s*-\s*(\d{1,2}/\d{1,2}/\d{4})", page1
        )
        if not period_match:
            log.error(f"Could not find Statement Period in {pdf_path.name}")
            return {}

        closing_date = datetime.strptime(period_match.group(1), "%m/%d/%Y")
        closing_ts = closing_date.replace(hour=23, minute=59, second=59).isoformat()

        # Page 2: Asset Allocation table
        page2 = pdf.pages[1].extract_text() or ""

    # Pattern: (TICKER) SHARES $PRICE $VALUE ALLOCATION% Base
    pattern = re.compile(
        r"\(([A-Z]+)\)\s+([\d.]+)\s+\$([\d,.]+)\s+\$([\d,.]+)\s+\d+%\s+Base"
    )

    positions = {}
    for m in pattern.finditer(page2):
        ticker = m.group(1)
        if ticker not in KNOWN_TICKERS:
            continue
        positions[ticker] = {
            "shares": float(m.group(2)),
            "price": float(m.group(3).replace(",", "")),
            "value": float(m.group(4).replace(",", "")),
        }

    log.info(
        f"  Baseline from {pdf_path.name} (closing {closing_date.strftime('%m/%d/%Y')}):"
    )
    for t, p in positions.items():
        log.info(
            f"    {t}: {p['shares']:.5f} shares @ ${p['price']:.2f} = ${p['value']:.2f}"
        )

    return {"date": closing_ts, "positions": positions}


# ---------------------------------------------------------------------------
# Phase 2: Transaction Extraction (subsequent statements)
# ---------------------------------------------------------------------------
def _preprocess_text(raw_text: str) -> str:
    """
    Fix IXUS line-wrapping: pdfplumber splits the name across two lines, e.g.:
        ... Bought iShares Core MSCI Total International 0.02304 $66.27 $1.53 Base
        Stock ETF (IXUS)
    We need to splice '(IXUS)' back into the previous line right after 'International',
    producing:
        ... Bought iShares Core MSCI Total International Stock ETF (IXUS) 0.02304 $66.27 $1.53 Base
    """
    lines = raw_text.split("\n")
    merged = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Stock ETF (IXUS)") and merged:
            # Insert " Stock ETF (IXUS)" right after "International" in the previous line
            prev = merged[-1]
            prev = prev.replace(
                "iShares Core MSCI Total International ",
                "iShares Core MSCI Total International Stock ETF (IXUS) ",
                1,
            )
            merged[-1] = prev
        else:
            merged.append(line)
    return "\n".join(merged)


def extract_transactions(pdf_path: Path) -> list[dict]:
    """
    Extract Bought/Sold transactions from the Transactions pages.
    Skips $0.00 split-redistribution rows.
    Returns a list of {date, action, ticker, shares, price, amount}.
    """
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    full_text = _preprocess_text(full_text)

    # Pattern:  SETTLEMENT_DATE  (Bought|Sold)  ...ETF_NAME (TICKER)  QTY  $PRICE  ($AMOUNT)  Base
    # Sold amounts use accounting-style parens: ($123.23) instead of $123.23
    # We use the settlement date (second date column)
    txn_pattern = re.compile(
        r"\d{1,2}/\d{1,2}/\d{4}\s+"  # Trade date (ignored)
        r"(\d{1,2}/\d{1,2}/\d{4})\s+"  # Settlement date (captured)
        r"(Bought|Sold)\s+"  # Activity
        r".*?\(([A-Z]+)\)\s+"  # ETF name ... (TICKER)
        r"([\d.]+)\s+"  # Quantity
        r"\(?\$([\d,.]+)\)?\s+"  # Price (may have parens)
        r"\(?\$([\d,.]+)\)?\s+"  # Amount (may have parens)
        r"Base",
        re.IGNORECASE,
    )

    transactions = []
    for m in txn_pattern.finditer(full_text):
        settle_date = m.group(1)
        action = m.group(2).title()
        ticker = m.group(3)
        qty = float(m.group(4))
        price = float(m.group(5).replace(",", ""))
        amount = float(m.group(6).replace(",", ""))

        if ticker not in KNOWN_TICKERS:
            continue

        # Skip $0.00 split-redistribution ghost rows
        if price == 0.0 and amount == 0.0:
            continue

        dt = datetime.strptime(settle_date, "%m/%d/%Y")
        dt = dt.replace(hour=12, minute=0, second=0)

        transactions.append(
            {
                "date": dt.isoformat(),
                "action": action,
                "ticker": ticker,
                "shares": qty,
                "price": price,
                "amount": amount,
            }
        )

    log.info(f"  {pdf_path.name}: {len(transactions)} transactions extracted")
    return transactions


# ---------------------------------------------------------------------------
# Stock Split Detection
# ---------------------------------------------------------------------------
def detect_splits(pdf_path: Path) -> list[dict]:
    """
    Scan the Corporate Actions page for Forward Split entries.
    Returns a list of {date, ticker, ratio}.
    """
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    splits = []
    # Pattern: DATE Forward Split ETF_NAME (TICKER) QUANTITY $0.00 $0.00
    split_pattern = re.compile(
        r"(\d{1,2}/\d{1,2}/\d{4})\s+Forward Split\s+.*?\(([A-Z]+)\)\s+([\d.]+)",
        re.IGNORECASE,
    )

    for m in split_pattern.finditer(full_text):
        date_str = m.group(1)
        ticker = m.group(2)
        # The "Quantity" in Corporate Actions is the number of NEW shares received
        # For a 5:1 split of 0.51293 shares, you receive 2.05172 new shares
        new_shares = float(m.group(3))

        dt = datetime.strptime(date_str, "%m/%d/%Y")
        dt = dt.replace(hour=0, minute=0, second=1)  # Before any same-day trades

        splits.append(
            {
                "date": dt.isoformat(),
                "ticker": ticker,
                "new_shares_received": new_shares,
            }
        )
        log.info(
            f"  {pdf_path.name}: Detected {ticker} forward split on {date_str} (+{new_shares} shares)"
        )

    return splits


# ---------------------------------------------------------------------------
# Database Writer
# ---------------------------------------------------------------------------
def write_to_db(baseline: dict, all_transactions: list[dict], all_splits: list[dict]):
    """
    Write everything into positions_ledger sequentially, maintaining running totals.

    Order:
      1. INITIAL_BASELINE entries (from Jan 2024 Page 2)
      2. STOCK_SPLIT entries (from Corporate Actions)
      3. IMPLIED_BUY / IMPLIED_SELL entries (from transaction pages)

    All sorted chronologically, then processed in order.
    """
    records = []
    acct_id = "acorns_0000"

    # 1. Baseline entries
    for ticker, pos in baseline["positions"].items():
        records.append(
            {
                "date": baseline["date"],
                "ticker": ticker,
                "type": "INITIAL_BASELINE",
                "share_delta": pos["shares"],
                "price": pos["price"],
                "value": pos["value"],
            }
        )

    # 2. Split entries
    for split in all_splits:
        records.append(
            {
                "date": split["date"],
                "ticker": split["ticker"],
                "type": "STOCK_SPLIT",
                "share_delta": split["new_shares_received"],
                "price": 0.0,
                "value": 0.0,
            }
        )

    # 3. Transaction entries
    for txn in all_transactions:
        txn_type = "IMPLIED_BUY" if txn["action"] == "Bought" else "IMPLIED_SELL"
        records.append(
            {
                "date": txn["date"],
                "ticker": txn["ticker"],
                "type": txn_type,
                "share_delta": txn["shares"],
                "price": txn["price"],
                "value": txn["amount"],
            }
        )

    # Deduplicate: same date + ticker + type + rounded shares
    seen = set()
    unique_records = []
    for r in records:
        sig = (r["date"], r["ticker"], r["type"], round(r["share_delta"], 5))
        if sig not in seen:
            seen.add(sig)
            unique_records.append(r)

    # Sort chronologically
    unique_records.sort(key=lambda x: x["date"])

    # Calculate running totals per ticker
    running_totals = {}

    with get_db() as conn:
        for item in unique_records:
            ticker = item["ticker"]
            delta = item["share_delta"]

            if ticker not in running_totals:
                running_totals[ticker] = 0.0

            if item["type"] == "IMPLIED_SELL":
                running_totals[ticker] -= delta
            else:
                running_totals[ticker] += delta

            new_total = round(running_totals[ticker], 5)

            conn.execute(
                """
                INSERT INTO positions_ledger
                (account_id, timestamp, ticker, transaction_type, share_delta, new_total_shares, yfinance_closing_price, estimated_transaction_value)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    acct_id,
                    item["date"],
                    ticker,
                    item["type"],
                    delta,
                    new_total,
                    item.get("price"),
                    item.get("value"),
                ),
            )

            log.info(
                f"  ✔ {item['type']:18s} {ticker} {delta:+.5f} → {new_total:.5f} shares ({item['date'][:10]})"
            )

        conn.commit()

    # Final summary
    log.info("\n--- Final Running Totals ---")
    for ticker in sorted(running_totals):
        total = running_totals[ticker]
        log.info(f"  {ticker}: {total:.5f} shares")
        if total < 0:
            log.warning(f"  ⚠ NEGATIVE SHARES for {ticker}!")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Parse Acorns PDFs (V2)")
    parser.add_argument(
        "--dir", required=True, help="Directory containing Acorns PDF statements"
    )
    args = parser.parse_args()

    pdf_dir = Path(args.dir)
    if not pdf_dir.exists() or not pdf_dir.is_dir():
        log.error(f"Directory not found: {pdf_dir}")
        return

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        log.warning(f"No PDFs found in {pdf_dir}")
        return

    log.info(f"Found {len(pdfs)} PDFs in {pdf_dir}\n")

    # Sort by statement month (filename format: user_statement-MM-YYYY.pdf)
    def sort_key(p: Path):
        m = re.search(r"(\d{2})-(\d{4})", p.stem)
        if m:
            return (int(m.group(2)), int(m.group(1)))
        return (9999, 99)

    pdfs.sort(key=sort_key)

    # Phase 1: Extract baseline from the oldest statement
    oldest = pdfs[0]
    log.info(f"Phase 1: Extracting baseline from {oldest.name}")
    baseline = extract_baseline(oldest)
    if not baseline:
        log.error("Failed to extract baseline. Aborting.")
        return

    # Phase 2: Extract transactions from remaining statements
    log.info(
        f"\nPhase 2: Extracting transactions from {len(pdfs) - 1} subsequent statements"
    )
    all_transactions = []
    all_splits = []
    for pdf_path in pdfs[1:]:
        splits = detect_splits(pdf_path)
        all_splits.extend(splits)
        txns = extract_transactions(pdf_path)
        all_transactions.extend(txns)

    log.info(f"\nTotal: {len(all_transactions)} transactions, {len(all_splits)} splits")

    # Write to DB
    log.info("\nWriting to database...")
    write_to_db(baseline, all_transactions, all_splits)
    log.info("\n✔ Ingestion complete.")


if __name__ == "__main__":
    main()
