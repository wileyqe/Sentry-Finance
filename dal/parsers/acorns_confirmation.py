"""Acorns daily trade confirmation PDF parser.

Parses the daily trade confirmation PDFs that Acorns publishes in their
Confirmations section. Each PDF lists all trades that settled on a given
day with exact ticker, price, quantity, and principal.

Format (pdfplumber text):
    Trade Confirmation
    Buy Symbol Trade Date Settlement Date Price ($) Quantity Principal ($) Order Type
    International Company StocksIXUS 4/6/2026 4/7/2026 $87.57 0.061208 $5.36 Discretionary
    Total $5.36

Recognition: filename contains 'trade_confirmation' or 'confirmation' (not
'1099'), OR content contains 'Trade Confirmation' and 'Acorns Securities'.
"""

import logging
import re
import sqlite3
from datetime import datetime
from decimal import Decimal

from dal.parsers.base import DocumentParser, ParseResult

log = logging.getLogger("sentry.parsers.acorns_confirmation")

KNOWN_TICKERS = {"IJH", "IJR", "IXUS", "VOO"}

# Trade data row pattern.  The ETF description runs into the ticker without
# a space (e.g. "International Company StocksIXUS"), so we anchor on the
# ticker followed by the date pattern.
#
# Captures: (ticker, trade_date, settlement_date, price, quantity, principal)
_TRADE_RE = re.compile(
    r"([A-Z]{2,5})\s+"           # ticker (2-5 uppercase letters)
    r"(\d{1,2}/\d{1,2}/\d{4})\s+"  # trade date
    r"(\d{1,2}/\d{1,2}/\d{4})\s+"  # settlement date
    r"\$([\d,.]+)\s+"            # price
    r"([\d.]+)\s+"               # quantity
    r"\$([\d,.]+)\s+"            # principal
    r"(\w+)",                    # order type
)

# Header line that marks the start of a Buy or Sell block.
_BLOCK_RE = re.compile(r"^(Buy|Sell)\s+Symbol\s+Trade Date", re.MULTILINE)


def _extract_trades(text: str) -> list[dict]:
    """Extract all trades from confirmation PDF text."""
    trades = []

    # Find all block headers to determine Buy vs Sell context
    blocks = list(_BLOCK_RE.finditer(text))

    for i, block_match in enumerate(blocks):
        action = block_match.group(1)  # "Buy" or "Sell"
        block_start = block_match.end()
        block_end = blocks[i + 1].start() if i + 1 < len(blocks) else len(text)
        block_text = text[block_start:block_end]

        for m in _TRADE_RE.finditer(block_text):
            ticker = m.group(1)
            if ticker not in KNOWN_TICKERS:
                continue

            trades.append({
                "action": action,
                "ticker": ticker,
                "trade_date": m.group(2),
                "settlement_date": m.group(3),
                "price": Decimal(m.group(4).replace(",", "")),
                "quantity": Decimal(m.group(5)),
                "principal": Decimal(m.group(6).replace(",", "")),
            })

    return trades


def _extract_confirmation_date(text: str) -> str | None:
    """Extract the confirmation date from the header."""
    m = re.search(r"Date\s+(\d{1,2}/\d{1,2}/\d{4})", text)
    return m.group(1) if m else None


class AcornsConfirmationParser(DocumentParser):
    @property
    def parser_type(self) -> str:
        return "acorns_confirmation"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        name = filename.lower()
        # Filename match — but not 1099s
        if ("confirmation" in name or "trade_confirmation" in name) and "1099" not in name:
            if "acorns" in name or "trade" in name:
                return True
        # Content match
        try:
            text = self._extract_pdf_text(content_bytes)
            return "Trade Confirmation" in text and "Acorns Securities" in text
        except Exception:
            return False

    def parse(self, content_bytes: bytes) -> ParseResult:
        try:
            text = self._extract_pdf_text(content_bytes)
        except Exception as e:
            return ParseResult(self.parser_type, {}, {}, [f"PDF extraction failed: {e}"])

        conf_date = _extract_confirmation_date(text)
        trades = _extract_trades(text)

        warnings = []
        if not trades:
            warnings.append("No trades found in this confirmation PDF.")

        # Serialize Decimals for JSON-safe storage in ParseResult.data
        serialized_trades = [
            {
                "action": t["action"],
                "ticker": t["ticker"],
                "trade_date": t["trade_date"],
                "settlement_date": t["settlement_date"],
                "price": str(t["price"]),
                "quantity": str(t["quantity"]),
                "principal": str(t["principal"]),
            }
            for t in trades
        ]

        total_principal = sum(t["principal"] for t in trades)
        tickers_seen = sorted({t["ticker"] for t in trades})

        preview = {
            "Date": conf_date or "Unknown",
            "Trades": str(len(trades)),
            "Tickers": ", ".join(tickers_seen),
            "Total": f"${total_principal:,.2f}",
        }

        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data={
                "confirmation_date": conf_date,
                "trades": serialized_trades,
            },
            warnings=warnings,
            can_commit=bool(trades),
        )

    def commit(self, conn: sqlite3.Connection, result: ParseResult) -> dict:
        """Write confirmation trades to positions_ledger.

        For each trade:
        - Check for an existing scraper entry (same month + ticker + similar
          delta) and upgrade it if found.
        - Otherwise insert a new entry with source='confirmation'.
        """
        data = result.data
        trades = data.get("trades", [])

        # Determine account_id
        acct_row = conn.execute(
            "SELECT id FROM accounts WHERE institution_id LIKE 'acorns%' LIMIT 1"
        ).fetchone()
        acct_id = acct_row[0] if acct_row else "acorns_0000"

        upgraded = 0
        inserted = 0

        for trade in trades:
            ticker = trade["ticker"]
            quantity = Decimal(trade["quantity"])
            price = Decimal(trade["price"])
            principal = Decimal(trade["principal"])
            action = trade["action"]

            # Build timestamp from settlement date
            settle_dt = datetime.strptime(trade["settlement_date"], "%m/%d/%Y")
            settle_dt = settle_dt.replace(hour=12, minute=0, second=0)
            ts = settle_dt.isoformat()
            month_prefix = ts[:7]

            # Check for existing scraper entry to upgrade
            candidates = conn.execute(
                """SELECT id, share_delta_dec
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
                except Exception:
                    continue
                if cand_delta > 0 and abs(quantity - cand_delta) / cand_delta < Decimal("0.1"):
                    conn.execute(
                        """UPDATE positions_ledger
                           SET timestamp = ?,
                               yfinance_closing_price = ?,
                               estimated_transaction_value = ?,
                               source = 'confirmation'
                           WHERE id = ?""",
                        (ts, float(price), float(principal), cand["id"]),
                    )
                    upgraded += 1
                    matched = True
                    break

            if not matched:
                # Get running total
                last = conn.execute(
                    """SELECT new_total_shares_dec
                       FROM positions_ledger
                       WHERE account_id = ? AND ticker = ?
                       ORDER BY timestamp DESC LIMIT 1""",
                    (acct_id, ticker),
                ).fetchone()
                prev = Decimal(last[0]) if last and last[0] else Decimal("0")

                if action == "Sell":
                    new_total = prev - quantity
                    txn_type = "IMPLIED_SELL"
                else:
                    new_total = prev + quantity
                    txn_type = "IMPLIED_BUY"

                conn.execute(
                    """INSERT INTO positions_ledger
                       (account_id, timestamp, ticker, transaction_type,
                        share_delta, new_total_shares,
                        yfinance_closing_price, estimated_transaction_value,
                        share_delta_dec, new_total_shares_dec, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmation')""",
                    (acct_id, ts, ticker, txn_type,
                     float(quantity), float(new_total),
                     float(price), float(principal),
                     str(quantity), str(new_total)),
                )
                inserted += 1

        conn.commit()

        return {
            "upgraded": upgraded,
            "inserted": inserted,
            "total_trades": len(trades),
        }
