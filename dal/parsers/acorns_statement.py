"""Acorns monthly statement PDF parser.

Extracts per-ETF purchase/sale transactions from Acorns monthly statements
and writes them to positions_ledger, upgrading scraper estimates where a
matching entry exists.

Recognition: filename contains 'acorns' and 'statement', or content contains
'ACORNS SECURITIES' and 'Statement Period'.
"""

import io
import logging
import re
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation

from dal.accounts_config import get_account_id
from dal.parsers.base import DocumentParser, ParseResult

log = logging.getLogger("sentry.parsers.acorns_statement")

KNOWN_TICKERS = {"IJH", "IJR", "IXUS", "VOO"}


def _preprocess_text(raw_text: str) -> str:
    """Fix IXUS line-wrapping in pdfplumber output."""
    lines = raw_text.split("\n")
    merged = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Stock ETF (IXUS)") and merged:
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


def _extract_statement_period(text: str) -> tuple[str | None, str | None]:
    """Extract start and end dates from 'Statement Period M/D/YYYY - M/D/YYYY'."""
    m = re.search(
        r"Statement Period\s+(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})",
        text,
    )
    if m:
        return m.group(1), m.group(2)
    return None, None


def _extract_transactions(text: str) -> list[dict]:
    """Extract Bought/Sold transactions from statement text."""
    text = _preprocess_text(text)

    txn_pattern = re.compile(
        r"\d{1,2}/\d{1,2}/\d{4}\s+"      # Trade date (ignored)
        r"(\d{1,2}/\d{1,2}/\d{4})\s+"    # Settlement date (captured)
        r"(Bought|Sold)\s+"               # Activity
        r".*?\(([A-Z]+)\)\s+"             # ETF name ... (TICKER)
        r"([\d.]+)\s+"                    # Quantity
        r"\(?\$([\d,.]+)\)?\s+"           # Price
        r"\(?\$([\d,.]+)\)?\s+"           # Amount
        r"Base",
        re.IGNORECASE,
    )

    transactions = []
    for m in txn_pattern.finditer(text):
        settle_date = m.group(1)
        action = m.group(2).title()
        ticker = m.group(3)
        qty = Decimal(m.group(4))
        price = Decimal(m.group(5).replace(",", ""))
        amount = Decimal(m.group(6).replace(",", ""))

        if ticker not in KNOWN_TICKERS:
            continue
        if price == 0 and amount == 0:
            continue

        dt = datetime.strptime(settle_date, "%m/%d/%Y")
        dt = dt.replace(hour=12, minute=0, second=0)

        transactions.append({
            "date": dt.isoformat(),
            "date_str": settle_date,
            "action": action,
            "ticker": ticker,
            "shares": qty,
            "price": price,
            "amount": amount,
        })

    return transactions


def _extract_splits(text: str) -> list[dict]:
    """Scan for Forward Split entries in Corporate Actions."""
    split_pattern = re.compile(
        r"(\d{1,2}/\d{1,2}/\d{4})\s+Forward Split\s+.*?\(([A-Z]+)\)\s+([\d.]+)",
        re.IGNORECASE,
    )
    splits = []
    for m in split_pattern.finditer(text):
        date_str = m.group(1)
        ticker = m.group(2)
        new_shares = Decimal(m.group(3))
        dt = datetime.strptime(date_str, "%m/%d/%Y")
        dt = dt.replace(hour=0, minute=0, second=1)
        splits.append({
            "date": dt.isoformat(),
            "ticker": ticker,
            "new_shares_received": new_shares,
        })
    return splits


class AcornsStatementParser(DocumentParser):
    @property
    def parser_type(self) -> str:
        return "acorns_statement"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        name = filename.lower()
        if "acorns" in name and "statement" in name:
            return True
        try:
            text = self._extract_pdf_text(content_bytes)
            return "ACORNS SECURITIES" in text and "Statement Period" in text
        except Exception:
            return False

    def parse(self, content_bytes: bytes) -> ParseResult:
        try:
            text = self._extract_pdf_text(content_bytes)
        except Exception as e:
            return ParseResult(self.parser_type, {}, {}, [f"PDF extraction failed: {e}"])

        start_date, end_date = _extract_statement_period(text)
        transactions = _extract_transactions(text)
        splits = _extract_splits(text)

        warnings = []
        if not start_date or not end_date:
            warnings.append("Could not extract statement period dates.")
        if not transactions and not splits:
            warnings.append(
                "No Bought/Sold transactions or splits found in this statement."
            )

        can_commit = bool(transactions or splits)
        if not can_commit and not warnings:
            warnings.append(
                "Statement appears empty — no transactions to commit."
            )

        preview = {
            "Statement Period": f"{start_date or '?'} - {end_date or '?'}",
            "Transactions": str(len(transactions)),
            "Splits": str(len(splits)),
            "Tickers": ", ".join(sorted({t["ticker"] for t in transactions})),
        }

        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data={
                "start_date": start_date,
                "end_date": end_date,
                "transactions": [
                    {**t, "shares": str(t["shares"]),
                     "price": str(t["price"]), "amount": str(t["amount"])}
                    for t in transactions
                ],
                "splits": [
                    {**s, "new_shares_received": str(s["new_shares_received"])}
                    for s in splits
                ],
            },
            warnings=warnings,
            can_commit=can_commit,
        )

    def commit(self, conn: sqlite3.Connection, result: ParseResult) -> dict:
        """Write statement transactions to positions_ledger.

        For each transaction:
        - Look for an existing scraper entry in the same month/ticker
          with a similar share delta (within 10% tolerance).
        - If found: upgrade it (replace timestamp + price, set source='statement').
        - If not found: insert a new entry.
        """
        data = result.data
        txns = data.get("transactions", [])
        splits = data.get("splits", [])

        upgraded = 0
        inserted = 0
        split_count = 0

        # Determine the account_id (first Acorns account found)
        acct_row = conn.execute(
            "SELECT id FROM accounts WHERE institution_id LIKE 'acorns%' LIMIT 1"
        ).fetchone()
        acct_id = (
            acct_row[0]
            if acct_row
            else (get_account_id("acorns", account_type="investment") or "acorns_XXXX")
        )

        for txn in txns:
            ticker = txn["ticker"]
            shares = Decimal(txn["shares"])
            price = Decimal(txn["price"])
            amount = Decimal(txn["amount"])
            ts = txn["date"]
            month_prefix = ts[:7]  # YYYY-MM

            # Try to find a matching scraper entry to upgrade
            candidates = conn.execute(
                """SELECT id, share_delta_dec, timestamp
                   FROM positions_ledger
                   WHERE account_id = ? AND ticker = ?
                     AND source = 'scraper'
                     AND timestamp LIKE ?
                   ORDER BY timestamp""",
                (acct_id, ticker, f"{month_prefix}%"),
            ).fetchall()

            matched = False
            for cand in candidates:
                try:
                    cand_delta = Decimal(cand["share_delta_dec"] or "0")
                except (InvalidOperation, TypeError):
                    continue
                # Within 10% tolerance
                if cand_delta > 0 and abs(shares - cand_delta) / cand_delta < Decimal("0.1"):
                    # Upgrade this entry
                    conn.execute(
                        """UPDATE positions_ledger
                           SET timestamp = ?,
                               yfinance_closing_price = ?,
                               estimated_transaction_value = ?,
                               source = 'statement'
                           WHERE id = ?""",
                        (ts, float(price), float(amount), cand["id"]),
                    )
                    upgraded += 1
                    matched = True
                    break

            if not matched:
                # Insert new entry
                # Get current running total for this ticker
                last = conn.execute(
                    """SELECT new_total_shares_dec
                       FROM positions_ledger
                       WHERE account_id = ? AND ticker = ?
                       ORDER BY timestamp DESC LIMIT 1""",
                    (acct_id, ticker),
                ).fetchone()
                prev_shares = Decimal(last[0]) if last and last[0] else Decimal("0")
                if txn["action"] == "Sold":
                    new_total = prev_shares - shares
                else:
                    new_total = prev_shares + shares

                txn_type = "IMPLIED_BUY" if txn["action"] == "Bought" else "IMPLIED_SELL"
                conn.execute(
                    """INSERT INTO positions_ledger
                       (account_id, timestamp, ticker, transaction_type,
                        share_delta, new_total_shares,
                        yfinance_closing_price, estimated_transaction_value,
                        share_delta_dec, new_total_shares_dec, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'statement')""",
                    (acct_id, ts, ticker, txn_type,
                     float(shares), float(new_total),
                     float(price), float(amount),
                     str(shares), str(new_total)),
                )
                inserted += 1

        # Handle splits
        for split in splits:
            ticker = split["ticker"]
            new_shares = Decimal(split["new_shares_received"])
            ts = split["date"]

            last = conn.execute(
                """SELECT new_total_shares_dec
                   FROM positions_ledger
                   WHERE account_id = ? AND ticker = ? AND timestamp < ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (acct_id, ticker, ts),
            ).fetchone()
            prev_shares = Decimal(last[0]) if last and last[0] else Decimal("0")
            new_total = prev_shares + new_shares

            conn.execute(
                """INSERT INTO positions_ledger
                   (account_id, timestamp, ticker, transaction_type,
                    share_delta, new_total_shares,
                    share_delta_dec, new_total_shares_dec, source)
                   VALUES (?, ?, ?, 'STOCK_SPLIT', ?, ?, ?, ?, 'statement')""",
                (acct_id, ts, ticker,
                 float(new_shares), float(new_total),
                 str(new_shares), str(new_total)),
            )
            split_count += 1

        conn.commit()

        return {
            "upgraded": upgraded,
            "inserted": inserted,
            "splits": split_count,
            "total_processed": upgraded + inserted + split_count,
        }
