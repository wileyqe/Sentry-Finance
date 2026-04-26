"""
dal/parsers/tsp_statement.py — TSP quarterly statement parser.

Recognizes: TSP statement PDFs containing "Thrift Savings Plan"
            and "Activity Detail by Fund".

Parses: per-fund unit counts, NAV prices, closing balances, statement date.

Commits: balance_snapshot, investment_holdings (per-fund), portfolio_snapshot,
         and ticker_metadata for the TSP retirement account (id looked up
         from accounts.yaml via dal.accounts_config.get_account_id).
"""

import io
import re
import logging
from datetime import datetime, timezone

import pdfplumber

from dal.accounts_config import get_account_id
from dal.parsers.base import DocumentParser, ParseResult
from dal.balances import record_balance

log = logging.getLogger("sentry.parsers.tsp_statement")

RECOGNITION_KEYWORDS = ["Thrift Savings Plan", "Activity Detail by Fund"]

# Canonical TSP fund ticker mapping. Once any TSP holdings row is written
# with one of these tickers, the mapping is locked — changing it later
# requires a migration + re-parse of every historical TSP statement.
# Pattern: "<Fund Label>" → "TSP_<short>". L-series uses the target year.
_TSP_FUND_TICKERS: dict[str, str] = {
    "G Fund": "TSP_G",
    "F Fund": "TSP_F",
    "C Fund": "TSP_C",
    "S Fund": "TSP_S",
    "I Fund": "TSP_I",
    "L Income": "TSP_LINCOME",
}


def _fund_to_ticker(fund_name: str) -> str:
    """Normalize a TSP fund label from the statement into a canonical ticker.

    Handles the static funds (G/F/C/S/I/L Income) via the lookup table
    and the L-series target-date funds by extracting the year. Unknown
    labels fall through to a defensive `TSP_` + alphanumeric squeeze
    so the write still succeeds rather than dropping the row.
    """
    name = fund_name.strip()
    if name in _TSP_FUND_TICKERS:
        return _TSP_FUND_TICKERS[name]
    # L-series: "L 2025" / "L2065" / "L 2070"
    m = re.match(r"^L\s*(\d{4})$", name)
    if m:
        return f"TSP_L{m.group(1)}"
    # Defensive fallback — preserve the data but mark the odd shape.
    squeezed = re.sub(r"[^A-Za-z0-9]", "", name).upper()
    return f"TSP_{squeezed}" if squeezed else "TSP_UNKNOWN"


class TSPStatementParser(DocumentParser):

    @property
    def parser_type(self) -> str:
        return "tsp_statement"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        """Check for TSP-specific keywords across the first several pages.

        Multi-statement PDFs (e.g. a bundled 18-month export) put the
        account summary on page 0 but the "Activity Detail by Fund"
        section on page 2 or later. A cover-page-only check rejects
        legitimate TSP exports.
        """
        try:
            with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
                # Scan up to the first 6 pages — enough for a bundled
                # multi-quarter statement while still bounding the
                # recognition cost for unrelated PDFs.
                combined = "\n".join(
                    (page.extract_text() or "")
                    for page in pdf.pages[:6]
                )
                return all(kw in combined for kw in RECOGNITION_KEYWORDS)
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
        can_commit = True
        if not result["statement_date"]:
            warnings.append("Could not extract statement date — will use today's date")
        if result["total_balance"] <= 0:
            warnings.append("Total balance is zero — verify the PDF is a TSP statement")
        # Silent-failure guard: recognized as a TSP statement with a real
        # balance but no per-fund detail means the "Activity Detail by
        # Fund" section changed layout. Refuse to commit — a headline-
        # only write would silently lose the per-fund holdings and
        # produce a broken Investments page.
        if result["total_balance"] > 0 and len(result["funds"]) == 0:
            warnings.append(
                "⚠ BLOCK: Recognized as a TSP statement but could not "
                "extract per-fund positions — the PDF layout may have "
                "changed. Committing now would record only the top-line "
                "balance and leave the Investments page missing every "
                "TSP fund. Re-upload only after the parser is updated."
            )
            can_commit = False

        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data=result,
            warnings=warnings,
            can_commit=can_commit,
        )

    def commit(self, conn, result: ParseResult) -> dict:
        """Write balance snapshot, per-fund holdings, and portfolio snapshot.

        Writes:
          1. balance_snapshots — top-line total via record_balance()
          2. investment_holdings — per-fund rows (units, NAV, market value)
          3. portfolio_snapshots — account-level total for time-series
          4. ticker_metadata — fund classification (INSERT OR IGNORE)
          5. tax_buckets — placeholder traditional row (AI-025). The TSP
             statement does NOT carry the Roth/Traditional contribution
             split, so we record one ``bucket_type='traditional'`` row at
             full balance — this matches the existing
             ``get_tax_summary`` fallback (``"no bucket data — assume
             traditional"``) but makes the implicit assumption explicit
             and queryable. A future feature may infer the split from a
             user-provided allocation config and override these rows.
        """
        data = result.data
        total = data["total_balance"]
        as_of = data.get("statement_date") or datetime.now(timezone.utc).date().isoformat()
        tsp_id = get_account_id("tsp", account_type="retirement") or "tsp_XXXX"

        record_balance(conn, tsp_id, total, as_of + "T12:00:00")

        # Per-fund investment_holdings
        funds_committed = 0
        for fund_name, fund_data in data.get("funds", {}).items():
            ticker = _fund_to_ticker(fund_name)
            units = fund_data.get("units", 0.0)
            nav = fund_data.get("nav", 0.0)
            balance = fund_data.get("balance", 0.0)
            if units <= 0:
                continue
            conn.execute(
                """INSERT OR REPLACE INTO investment_holdings
                       (account_id, date, ticker, shares, close_price,
                        market_value, cost_basis)
                   VALUES (?, ?, ?, ?, ?, ?, NULL)""",
                (tsp_id, as_of, ticker, units, nav, balance),
            )
            funds_committed += 1

        # Portfolio snapshot (account-level total, no cash in TSP)
        # No UNIQUE constraint on this table, so delete-then-insert
        ps_ts = as_of + "T12:00:00"
        conn.execute(
            "DELETE FROM portfolio_snapshots WHERE account_id = ? AND timestamp = ?",
            (tsp_id, ps_ts),
        )
        conn.execute(
            """INSERT INTO portfolio_snapshots
                   (account_id, timestamp, total_account_value, cash_balance)
               VALUES (?, ?, ?, 0.0)""",
            (tsp_id, ps_ts, total),
        )

        # Seed ticker_metadata for TSP funds (idempotent)
        _seed_ticker_metadata(conn)

        # AI-025: write a placeholder tax_buckets row so the table is no
        # longer write-only for live ingestion. Bucket split is unknown
        # from the statement, so we record 100% traditional — same shape
        # as the existing get_tax_summary fallback. log.warning makes the
        # placeholder visible to anyone tailing logs after a TSP upload.
        balance_cents = round(float(total) * 100)
        conn.execute(
            """INSERT OR REPLACE INTO tax_buckets
                   (account_id, bucket_type, balance, vested_pct, as_of)
               VALUES (?, 'traditional', ?, 1.0, ?)""",
            (tsp_id, balance_cents, as_of),
        )
        log.warning(
            "TSP statement commit (account=%s, as_of=%s): bucket_type "
            "split is unknown from the statement document; recorded a "
            "placeholder traditional bucket at 100%% of the balance. If "
            "the account holds Roth contributions, the Allocation donut "
            "and tax-summary will under-represent them until a real "
            "split is configured.",
            tsp_id,
            as_of,
        )

        return {
            "account": tsp_id,
            "total_balance": total,
            "statement_date": as_of,
            "funds_committed": funds_committed,
        }


# ── Ticker metadata ──────────────────────────────────────────────────────────

_TSP_METADATA = {
    "TSP_G":       ("Fixed Income", "Government Bonds", "Fixed Income"),
    "TSP_F":       ("Fixed Income", "Bond Index",       "Fixed Income"),
    "TSP_C":       ("Equity",       "Large Cap",        "US Equity"),
    "TSP_S":       ("Equity",       "Small-Mid Cap",    "US Equity"),
    "TSP_I":       ("Equity",       "International",    "Intl Equity"),
    "TSP_LINCOME": ("Balanced",     "Target Date",      "Target Date Fund"),
    "TSP_L2065":   ("Balanced",     "Target Date",      "Target Date Fund"),
}


def _seed_ticker_metadata(conn) -> None:
    """Ensure ticker_metadata rows exist for all TSP funds (idempotent)."""
    # Static funds + any L-series from _TSP_FUND_TICKERS
    all_tickers = dict(_TSP_METADATA)
    for label, ticker in _TSP_FUND_TICKERS.items():
        if ticker not in all_tickers:
            all_tickers[ticker] = ("Balanced", "Target Date", "Target Date Fund")

    for ticker, (sector, industry, asset_class) in all_tickers.items():
        conn.execute(
            """INSERT OR IGNORE INTO ticker_metadata
                   (ticker, sector, industry, asset_class)
               VALUES (?, ?, ?, ?)""",
            (ticker, sector, industry, asset_class),
        )


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
