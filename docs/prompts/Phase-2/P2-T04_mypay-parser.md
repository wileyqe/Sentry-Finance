# P2-T04: myPay RAS Parser

## Context

You are working on Sentry Finance, a local-first personal finance app.
The DFAS (Defense Finance and Accounting Service) Retiree Account Statement
(RAS) is a monthly PDF that shows the full income and deduction breakdown
for the military pension. It is the authoritative source for:

- Gross pension (before any deductions)
- Federal income tax withheld
- State income tax withheld
- SBP (Survivor Benefit Plan) premium
- Health/dental/vision insurance premiums
- Other DFAS deductions
- Net pay (deposited to NFCU checking)

This data enables two future metrics that are currently impossible:
**pre-tax savings rate** and **effective tax rate**. It also allows the
yearly wrap-up to show where pension dollars actually went.

The RAS PDF is provided via the document drop system (P2-T02). This task
builds the parser and registers it with `dal/document_drop.py`.

---

## Starting State

### Document drop system (P2-T02 output):
- `dal/parsers/base.py` — `DocumentParser` ABC, `ParseResult` dataclass
- `dal/parsers/__init__.py` — empty
- `dal/parsers/tsp_statement.py` — reference parser implementation
- `dal/document_drop.py` — `_PARSERS` list, auto-recognition chain

### Database schema (V14, from P2-T02):
Table `document_drops` exists. No income breakdown table exists yet.

### Where RAS income data should go:

The RAS describes a single monthly paycheck. The most useful storage is a
new `payroll_snapshots` table (V15 migration) that captures each
RAS-month's deduction breakdown. This enables:
- Year-over-year pension growth tracking
- Pre-tax savings rate computation (net pay vs. gross)
- Effective tax rate (total withholding / gross pension)
- Monthly deduction trend tracking

Do NOT try to store RAS data as transactions — the NFCU connector already
captures the pension deposit as a transaction. The RAS adds the decomposition
of that deposit, not a new deposit.

---

## What a myPay RAS Looks Like

The DFAS Retiree Account Statement is a PDF with a consistent layout.
Key fields to extract (with common label patterns — verify against a real PDF):

```
GROSS PAY             $X,XXX.XX
FEDERAL WITHHOLDING   $XXX.XX     (may also appear as "FED TAX" or "Federal Tax")
STATE WITHHOLDING     $XXX.XX     (may appear as "STATE TAX" or specific state name)
SBP                   $XXX.XX     (Survivor Benefit Plan premium)
DENTAL/VISION         $XXX.XX     (combined or separate)
TRICARE PRIME         $XXX.XX     (or other TRICARE plan variant)
ALLOTMENTS            $XXX.XX     (if any)
NET PAY               $X,XXX.XX
```

Additional context fields:
- Pay period: the month this statement covers (e.g., "01 FEB 2026")
- Pay grade and name (for verification; not stored)
- DFAS document identifier

**Recognition signature:** The RAS PDF contains "Defense Finance and
Accounting Service" AND ("Retiree Account Statement" OR "RETIREMENT").
The first page typically has a header block with "DFAS" prominently.

---

## Task

### 1. Create `dal/migrations/v15_payroll_snapshots.py`

```python
VERSION = 15

def run(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS payroll_snapshots (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            pay_period       TEXT NOT NULL,    -- YYYY-MM of the pay period
            source           TEXT NOT NULL,    -- 'mypay_ras', 'manual'
            gross_pay        REAL,
            federal_tax      REAL,
            state_tax        REAL,
            sbp_premium      REAL,
            health_insurance REAL,             -- TRICARE / health plan
            dental_vision    REAL,
            other_deductions REAL,             -- catch-all for other line items
            net_pay          REAL,
            raw_json         TEXT,             -- full extracted field dict as JSON
            created_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(pay_period, source)
                ON CONFLICT REPLACE
        );
    """)
```

### 2. Create `dal/parsers/mypay_ras.py`

```python
"""
dal/parsers/mypay_ras.py — DFAS Retiree Account Statement (RAS) parser.

Recognizes: PDFs containing "Defense Finance and Accounting Service"
            AND ("Retiree Account Statement" OR "RETIREMENT")

Parses: gross pay, federal/state tax withholding, SBP, health insurance,
        dental/vision, other deductions, net pay, pay period.

Commits: payroll_snapshots row for the statement's pay period.
"""

import io
import json
import logging
import re
from datetime import datetime

import pdfplumber

from dal.parsers.base import DocumentParser, ParseResult

log = logging.getLogger("sentry.parsers.mypay_ras")

# Recognition keywords — all must be present in the document
RECOGNITION_KEYWORDS = ["Defense Finance and Accounting Service"]
RECOGNITION_ANY_OF = ["Retiree Account Statement", "RETIREMENT"]

# Field label → canonical name mapping
# These cover common DFAS label variations. Add more if the real PDF uses different text.
FIELD_MAP = {
    # Gross
    r"GROSS\s+PAY":                        "gross_pay",
    r"GROSS\s+RETIRED\s+PAY":             "gross_pay",
    # Federal tax
    r"FEDERAL\s+WITHHOLDING":             "federal_tax",
    r"FED(?:ERAL)?\s+TAX":               "federal_tax",
    r"FED\s+INC\s+TAX":                  "federal_tax",
    # State tax
    r"STATE\s+WITHHOLDING":              "state_tax",
    r"STATE\s+TAX":                      "state_tax",
    r"IN\s+STATE\s+TAX":                "state_tax",    # Indiana
    # SBP
    r"SBP(?:\s+PREMIUM)?":              "sbp_premium",
    r"SURVIVOR\s+BENEFIT":              "sbp_premium",
    # Health / TRICARE
    r"TRICARE\s+(?:PRIME|RETIRED|SELECT)": "health_insurance",
    r"HEALTH\s+(?:PLAN|INSURANCE)":       "health_insurance",
    r"FEHB":                              "health_insurance",
    # Dental/Vision
    r"DENTAL(?:\s*/\s*VISION)?":          "dental_vision",
    r"VISION(?:\s*/\s*DENTAL)?":          "dental_vision",
    r"FEDVIP":                            "dental_vision",
    # Net pay
    r"NET\s+PAY":                         "net_pay",
    r"NET\s+AMOUNT":                      "net_pay",
}

# Pay period patterns: "01 FEB 2026", "February 2026", "02/2026"
PERIOD_PATTERNS = [
    r"(\d{2})\s+([A-Z]{3})\s+(\d{4})",    # "01 FEB 2026"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
    r"(\d{2})/(\d{4})",                    # "02/2026"
    r"PAY\s+PERIOD[:\s]+(\w+\s+\d{4})",
]

MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
MONTH_FULL = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}


class MyPayRASParser(DocumentParser):

    @property
    def parser_type(self) -> str:
        return "mypay_ras"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        """Recognize RAS by content keywords."""
        try:
            with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
                # Check first two pages
                text = ""
                for page in pdf.pages[:2]:
                    text += (page.extract_text() or "") + "\n"
                has_dfas = RECOGNITION_KEYWORDS[0] in text
                has_ras = any(kw in text for kw in RECOGNITION_ANY_OF)
                return has_dfas and has_ras
        except Exception:
            return False

    def parse(self, content_bytes: bytes) -> ParseResult:
        """Extract pay breakdown from RAS."""
        with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        extracted = {}
        raw_fields = {}

        # ── Extract pay period ─────────────────────────────────────────
        pay_period = _extract_pay_period(full_text)

        # ── Extract dollar amounts for each field ──────────────────────
        # Strategy: scan line by line looking for label patterns followed by amount
        lines = full_text.split("\n")
        for line in lines:
            line = line.strip()
            for pattern, field_name in FIELD_MAP.items():
                if re.search(pattern, line, re.IGNORECASE):
                    amount = _extract_amount_from_line(line)
                    if amount is not None and field_name not in extracted:
                        extracted[field_name] = amount
                        raw_fields[line.strip()] = amount
                    break  # First matching pattern wins per line

        # ── Compute other_deductions ───────────────────────────────────
        # other = gross - federal - state - sbp - health - dental - net
        known_deductions = (
            extracted.get("federal_tax", 0)
            + extracted.get("state_tax", 0)
            + extracted.get("sbp_premium", 0)
            + extracted.get("health_insurance", 0)
            + extracted.get("dental_vision", 0)
        )
        if "gross_pay" in extracted and "net_pay" in extracted:
            total_deductions = extracted["gross_pay"] - extracted["net_pay"]
            other = max(0.0, round(total_deductions - known_deductions, 2))
            extracted["other_deductions"] = other

        # ── Build preview ──────────────────────────────────────────────
        preview = {"pay_period": pay_period or "unknown"}
        for key in ["gross_pay", "federal_tax", "state_tax", "sbp_premium",
                    "health_insurance", "dental_vision", "other_deductions", "net_pay"]:
            if key in extracted:
                preview[key] = f"${extracted[key]:,.2f}"

        # ── Warnings ───────────────────────────────────────────────────
        warnings = []
        if not pay_period:
            warnings.append("Could not determine pay period — please verify before importing")
        if "gross_pay" not in extracted:
            warnings.append("Gross pay not found — verify this is a DFAS RAS PDF")
        if "net_pay" not in extracted:
            warnings.append("Net pay not found")

        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data={
                "pay_period": pay_period,
                "extracted": extracted,
                "raw_fields": raw_fields,
            },
            warnings=warnings,
        )

    def commit(self, conn, result: ParseResult) -> dict:
        """Insert or replace payroll_snapshots row."""
        data = result.data
        extracted = data.get("extracted", {})
        pay_period = data.get("pay_period") or datetime.utcnow().strftime("%Y-%m")

        conn.execute(
            """
            INSERT INTO payroll_snapshots
                (pay_period, source, gross_pay, federal_tax, state_tax,
                 sbp_premium, health_insurance, dental_vision,
                 other_deductions, net_pay, raw_json)
            VALUES (?, 'mypay_ras', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pay_period,
                extracted.get("gross_pay"),
                extracted.get("federal_tax"),
                extracted.get("state_tax"),
                extracted.get("sbp_premium"),
                extracted.get("health_insurance"),
                extracted.get("dental_vision"),
                extracted.get("other_deductions"),
                extracted.get("net_pay"),
                json.dumps(data.get("raw_fields", {})),
            ),
        )

        return {
            "pay_period": pay_period,
            "gross_pay": extracted.get("gross_pay"),
            "net_pay": extracted.get("net_pay"),
            "fields_extracted": len(extracted),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_pay_period(text: str) -> str | None:
    """Extract the pay period and return as YYYY-MM string."""
    # Pattern 1: "01 FEB 2026"
    m = re.search(r"(\d{2})\s+([A-Z]{3})\s+(\d{4})", text)
    if m:
        month_num = MONTH_ABBR.get(m.group(2).upper())
        if month_num:
            return f"{m.group(3)}-{month_num:02d}"

    # Pattern 2: "February 2026"
    m = re.search(
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(\d{4})",
        text
    )
    if m:
        month_num = MONTH_FULL.get(m.group(1))
        if month_num:
            return f"{m.group(2)}-{month_num:02d}"

    # Pattern 3: "PAY DATE: 01/01/2026" — use as year-month
    m = re.search(r"PAY\s+DATE[:\s]+\d{2}/\d{2}/(\d{4})", text, re.IGNORECASE)
    if m:
        return None  # Need month too, can't get it from year alone

    return None


def _extract_amount_from_line(line: str) -> float | None:
    """Extract the first dollar amount from a line of text."""
    # Match: $1,234.56 or 1,234.56 (with or without $ sign)
    m = re.search(r"\$?([\d,]+\.\d{2})", line)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None
```

### 3. Register `MyPayRASParser` in `dal/document_drop.py`

In `_PARSERS`, uncomment or add:

```python
from dal.parsers.mypay_ras import MyPayRASParser

_PARSERS: list[DocumentParser] = [
    TSPStatementParser(),
    MyPayRASParser(),   # ← add
]
```

### 4. Add myPay RAS to `pending-nudges` endpoint

In `backend/routers/documents.py`, extend `pending_nudges()` to also check
for myPay RAS:

```python
# myPay RAS: check for committed mypay_ras this month
mypay_row = conn.execute(
    """
    SELECT COUNT(*) as cnt FROM document_drops
    WHERE parser_type = 'mypay_ras'
      AND committed_at IS NOT NULL
      AND committed_at >= ?
    """,
    (current_month + "-01",),
).fetchone()

if not mypay_row or mypay_row["cnt"] == 0:
    nudges.append({
        "institution": "mypay",
        "display_name": "myPay (DFAS)",
        "message": "Monthly pension statement not received. Drop your RAS PDF to update.",
    })
```

---

## Files to Create

1. `dal/migrations/v15_payroll_snapshots.py`
2. `dal/parsers/mypay_ras.py`

## Files to Modify

3. `dal/document_drop.py` — import and register `MyPayRASParser`
4. `backend/routers/documents.py` — add myPay check to `pending_nudges()`

## Files NOT to Modify

- `dal/parsers/base.py` — use ParseResult and DocumentParser as-is
- `dal/parsers/tsp_statement.py` — don't touch
- Any frontend files
- Any connector files

---

## Constraints

- The RAS parser must be **resilient to label variation**: DFAS has changed
  the RAS format over the years. The `FIELD_MAP` uses regex patterns rather
  than exact strings. Add more patterns if you observe additional variants.
- If a field is not found, it should be stored as NULL (not 0) — NULL means
  "not present in this document", while 0 means "zero withheld"
- The `UNIQUE(pay_period, source) ON CONFLICT REPLACE` constraint in V15
  means re-committing the same month's RAS is safe — it just overwrites
- `other_deductions` is computed, not extracted directly — it prevents
  double-counting. If gross and net are both missing, set it to NULL
- The parser should NOT attempt to calculate or derive savings rate or
  effective tax rate — that's an analytical layer built later using this data
- The `raw_json` column stores ALL extracted label→amount pairs before
  normalization — useful for debugging when DFAS changes their format
- `pdfplumber` is already installed

---

## Done Checklist

- [ ] `dal/migrations/v15_payroll_snapshots.py` with `VERSION = 15`
- [ ] `payroll_snapshots` table has `UNIQUE(pay_period, source) ON CONFLICT REPLACE`
- [ ] `dal/parsers/mypay_ras.py` implements all three `DocumentParser` methods
- [ ] `can_parse()` uses content keywords (DFAS + RAS), not filename
- [ ] `parse()` extracts gross_pay, federal_tax, state_tax, sbp_premium,
      health_insurance, dental_vision, net_pay
- [ ] `parse()` computes `other_deductions` from gross - net - known_deductions
- [ ] `parse()` extracts pay period as YYYY-MM
- [ ] Missing fields stored as None (not 0)
- [ ] `commit()` inserts into `payroll_snapshots` with correct column names
- [ ] `MyPayRASParser` registered in `dal/document_drop._PARSERS`
- [ ] `pending_nudges()` checks for myPay RAS alongside TSP statement

## Verification

After completion, Claude will:
1. Run migration: `python -c "from dal.database import init_db; init_db(); print('OK')"`
2. Run import: `python -c "from dal.parsers.mypay_ras import MyPayRASParser; print('OK')"`
3. Run import: `python -c "from dal.document_drop import parse_document; print('OK')"`
4. Write a pytest test (`tests/test_t04_mypay.py`) that:
   a. Tests `can_parse()` with fake bytes containing recognition keywords → True
   b. Tests `can_parse()` with random bytes → False
   c. Tests `_extract_pay_period()` with sample text → correct YYYY-MM
   d. Tests `_extract_amount_from_line()` with "$1,234.56" → 1234.56
   e. Tests `_extract_amount_from_line()` with "GROSS PAY $3,456.00" → 3456.00
   f. Tests `other_deductions` computation: gross=3000, net=2100, federal=500,
      state=100, sbp=50, health=150, dental=0 → other=100.0
   g. Tests `commit()` with a mock DB: inserts correct row
5. All tests pass
6. Check `dal/document_drop.py` — `MyPayRASParser` is in `_PARSERS`
7. Check `documents.py` pending_nudges — myPay check present
