"""
dal/parsers/tsp_statement.py — TSP quarterly statement parser.

Recognizes: TSP statement PDFs containing "Thrift Savings Plan"
            and "Activity Detail by Fund".

Parses: per-fund unit counts, NAV prices, closing balances, statement date.

Commits: balance_snapshot + portfolio_snapshot for account tsp_7777.
"""

import io
import re
import logging
from datetime import datetime, timezone

import pdfplumber

from dal.parsers.base import DocumentParser, ParseResult
from dal.balances import record_balance

log = logging.getLogger("sentry.parsers.tsp_statement")

RECOGNITION_KEYWORDS = ["Thrift Savings Plan", "Activity Detail by Fund"]


class TSPStatementParser(DocumentParser):

    @property
    def parser_type(self) -> str:
        return "tsp_statement"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        """Check for TSP-specific keywords in first-page text."""
        try:
            with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
                first_text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
                return all(kw in first_text for kw in RECOGNITION_KEYWORDS)
        except Exception:
            return False

    def parse(self, content_bytes: bytes) -> ParseResult:
        """Extract statement date, total balance, per-fund positions."""
        with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        result = {
            "statement_date": None,
            "total_balance": 0.0,
            "funds": {},
        }

        # Extract statement end date
        m = re.search(
            r"Account Summary\s+\d{2}-\d{2}-\d{4}\s+to\s+(\d{2}-\d{2}-\d{4})",
            full_text
        )
        if m:
            result["statement_date"] = datetime.strptime(m.group(1), "%m-%d-%Y").date().isoformat()

        # Extract total closing balance
        m = re.search(r"Closing Balance\s+\$([\d,]+\.\d{2})", full_text)
        if m:
            result["total_balance"] = _clean_number(m.group(1))

        # Per-fund activity detail
        with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if "Activity Detail by Fund" in text:
                    _parse_activity_detail(text, result)
                    break

        preview = {
            "statement_date": result["statement_date"] or "unknown",
            "total_balance": f"${result['total_balance']:,.2f}",
            "funds_found": len(result["funds"]),
            "fund_breakdown": {
                name: f"${data['balance']:,.2f}"
                for name, data in result["funds"].items()
            },
        }

        warnings = []
        if not result["statement_date"]:
            warnings.append("Could not extract statement date — will use today's date")
        if result["total_balance"] <= 0:
            warnings.append("Total balance is zero — verify the PDF is a TSP statement")

        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data=result,
            warnings=warnings,
        )

    def commit(self, conn, result: ParseResult) -> dict:
        """Write balance + portfolio snapshot to DB."""
        data = result.data
        total = data["total_balance"]
        as_of = data.get("statement_date") or datetime.now(timezone.utc).date().isoformat()
        now = datetime.now(timezone.utc).isoformat()

        record_balance(conn, "tsp_7777", total, as_of + "T12:00:00")
        conn.execute(
            """
            INSERT INTO portfolio_snapshots
                (account_id, timestamp, total_account_value, cash_balance)
            VALUES (?, ?, ?, ?)
            """,
            ("tsp_7777", now, total, 0.0),
        )
        return {
            "account": "tsp_7777",
            "total_balance": total,
            "statement_date": as_of,
            "funds_committed": len(data.get("funds", {})),
        }


# ── Helpers (adapted from scripts/ingest_tsp.py) ─────────────────────────────

def _parse_activity_detail(text: str, result: dict) -> None:
    lines = text.split("\n")
    fund_names = []
    for line in lines:
        if "Fund Name" in line:
            parts = line.split("All Funds Total")
            if len(parts) > 1:
                names = re.findall(r"(L\s+\d{4}|[GCFSI]\s+Fund|L\s+Income)", parts[1])
                fund_names = names
            break

    if not fund_names:
        return

    closing_balances, closing_units, nav_prices = [], [], []
    for line in lines:
        if line.strip().startswith("Closing Balance"):
            closing_balances = [_clean_number(a) for a in re.findall(r"\$([\d,]+\.\d{2})", line)[1:]]
        elif "Closing Units" in line:
            closing_units = [_clean_number(u) for u in re.findall(r"([\d,]+\.\d{3})", line)]
        elif "Unit Price (NAV)" in line:
            nav_prices = [float(p) for p in re.findall(r"(\d+\.\d{4,6})", line)]

    for i, fund in enumerate(fund_names):
        result["funds"][fund] = {
            "units": closing_units[i] if i < len(closing_units) else 0.0,
            "nav": nav_prices[i] if i < len(nav_prices) else 0.0,
            "balance": closing_balances[i] if i < len(closing_balances) else 0.0,
        }


def _clean_number(val: str) -> float:
    if not val:
        return 0.0
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except ValueError:
        return 0.0
