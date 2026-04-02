# P4-T05: Eventlink Import

## Context

You are working on Sentry Finance, a local-first personal finance app.
The user has officiating side income tracked via Eventlink, a sports
officiating management platform. The seasonal income model (P3-T01) already
classifies "Officiating Income" as a seasonal stream with monthly
coefficients, but the historical data backing that model comes from
bank transaction records (deposits from Eventlink payouts).

Eventlink provides a payment history export (XLSX or CSV format) with
per-game payment details. This data is more granular than bank transactions:
- Individual game payments vs. lump-sum bi-weekly payouts
- Game dates vs. deposit dates (lag of 1-3 weeks)
- Breakdown by sport, level (varsity/JV/freshman), and pay rate

Importing this data enables:
- Backfilling historical game data for more accurate seasonal modeling
- Per-game payment tracking (supplement to bank transaction totals)
- Game count analytics (games/month, games/sport)

## Starting State

- `dal/parsers/` has an established parser pattern: `base.py` (ABC with
  `ParseResult(parser_type, fields, raw_data)`) and concrete parsers
  (`tsp_statement.py`, `mypay_ras.py`)
- `dal/document_drop.py` has a recognition chain that auto-routes uploaded
  files to the correct parser
- `backend/routers/documents.py` has upload/commit/history endpoints
- Transaction categories include "Officiating Income" in `categories.yaml`
- The `transactions` table stores all historical transactions

## Task

### 1. Research Eventlink Export Format

**Investigation required:** Eventlink's export capabilities need to be
verified:
- Log into Eventlink and navigate to Payment History or Earnings
- Determine available export formats (XLSX, CSV, PDF)
- Document the exact column headers in the export file
- Note the URL paths for the export page

Expected columns (based on similar platforms):
```
Date | Game/Event | Sport | Level | Role | Pay Rate | Amount | Status | Pay Period
```

If Eventlink does not support data export, document the alternative:
manual scraping or screenshot parsing.

### 2. New Parser: `dal/parsers/eventlink.py`

Create a parser following the established pattern:

```python
"""Eventlink officiating payment history parser."""

from dal.parsers.base import BaseParser, ParseResult


class EventlinkParser(BaseParser):
    """Parse Eventlink payment history exports (XLSX/CSV)."""

    parser_type = "eventlink_payments"

    @classmethod
    def can_parse(cls, filename: str, file_bytes: bytes) -> bool:
        """Detect Eventlink exports by filename pattern or content markers."""
        name = filename.lower()
        # Check for Eventlink-specific filename pattern
        if "eventlink" in name or "payment_history" in name:
            return True
        # Check content for Eventlink headers
        try:
            text = file_bytes.decode("utf-8", errors="ignore")[:2000]
            markers = ["Game Date", "Pay Rate", "Assignor", "Official"]
            return sum(1 for m in markers if m.lower() in text.lower()) >= 2
        except Exception:
            return False

    @classmethod
    def parse(cls, filename: str, file_bytes: bytes) -> ParseResult:
        """Parse the export file into structured payment records."""
        # Determine format from extension
        if filename.lower().endswith(".xlsx"):
            return cls._parse_xlsx(file_bytes)
        else:
            return cls._parse_csv(file_bytes)

    @classmethod
    def _parse_xlsx(cls, file_bytes: bytes) -> ParseResult:
        """Parse XLSX format using openpyxl."""
        import io
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.active
        # ... Parse rows into payment records
        raise NotImplementedError("Complete after Eventlink format is verified")

    @classmethod
    def _parse_csv(cls, file_bytes: bytes) -> ParseResult:
        """Parse CSV format."""
        import csv
        import io

        reader = csv.DictReader(io.StringIO(file_bytes.decode("utf-8")))
        # ... Parse rows into payment records
        raise NotImplementedError("Complete after Eventlink format is verified")
```

### 3. Transaction Conversion

Convert parsed Eventlink payment records into `transactions` table format:

```python
def _to_transactions(self, payments: list[dict]) -> list[dict]:
    """Convert Eventlink payments to Sentry transaction format."""
    transactions = []
    for pay in payments:
        transactions.append({
            "posting_date": pay["pay_date"],           # When the money was received
            "transaction_date": pay.get("game_date"),  # When the game was played
            "amount": abs(pay["amount"]),
            "signed_amount": pay["amount"],             # Positive (income)
            "direction": "credit",
            "description": f"Officiating - {pay.get('sport', '')} {pay.get('level', '')}".strip(),
            "raw_description": pay.get("raw_line", ""),
            "category": "Officiating Income",
        })
    return transactions
```

### 4. Register Parser in Document Drop Chain

In `dal/document_drop.py`, add `EventlinkParser` to the recognition chain:

```python
from dal.parsers.eventlink import EventlinkParser

_PARSERS = [
    # ... existing parsers ...
    EventlinkParser,
]
```

### 5. Deduplication Strategy

Eventlink payment records may overlap with existing bank transactions
(the same income appears as a bank deposit). The commit step must:
- Check for existing transactions in the "Officiating Income" category
  near the same date (±7 days) with similar amounts
- Mark potential duplicates for user review rather than auto-inserting
- Store game-level metadata (sport, level, game count) in a supplementary
  field or separate table

**Decision needed:** Either:
A) Import into `transactions` with duplicate detection (simpler)
B) Create a new `officiating_games` table for game-level detail and link
   to existing transactions (richer, but more complex)

Recommend option A for the initial implementation, with raw game data
stored in `document_drops.raw_data` for future enrichment.

## Files to Create

1. `dal/parsers/eventlink.py` — XLSX/CSV parser

## Files to Modify

1. `dal/document_drop.py` — register parser in chain

## Files NOT to Modify

- Other parser files
- Frontend files
- Connector files
- Migration files (no schema changes for option A)

## Constraints

- Parser implementation depends on actual Eventlink export format —
  the format skeleton above is a **best-guess** that needs validation
  against real exported data
- `openpyxl` may need to be added to `requirements.txt` if XLSX support
  is needed (check if it's already a dependency)
- Eventlink may require authentication to export — document any login
  requirements for manual download instructions
- Category must be "Officiating Income" to integrate with the seasonal
  income model from P3-T01
- All parsed amounts should be positive (income direction)
- Game dates and pay dates may differ — store both when available

## Done Checklist

- [ ] Eventlink export format documented (columns, file type)
- [ ] `EventlinkParser` class created following `BaseParser` pattern
- [ ] `can_parse()` detects Eventlink files by name or content
- [ ] `parse()` extracts payment records with date, amount, sport, level
- [ ] Parser registered in document drop chain
- [ ] Transaction conversion maps to "Officiating Income" category
- [ ] Deduplication handles overlap with bank transaction records
- [ ] Edge cases: empty file, partial data, unknown sport types

## Verification

After completion, Claude will:
1. Verify parser follows `BaseParser` interface
2. Verify `can_parse()` detection logic
3. Run import check: `python -c "from dal.parsers.eventlink import EventlinkParser"`
4. Verify parser is registered in document drop chain
5. Test with synthetic Eventlink data if real export format is available
