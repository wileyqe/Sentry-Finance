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
from datetime import datetime, timezone

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
    r"GROSS\s+ENTITLEMENT":               "gross_pay",
    # Federal tax
    r"FEDERAL\s+WITHHOLDING":             "federal_tax",
    r"FED(?:ERAL)?\s+TAX":               "federal_tax",
    r"FED\s+INC\s+TAX":                  "federal_tax",
    r"FITW":                              "federal_tax",
    # State tax
    r"STATE\s+WITHHOLDING":              "state_tax",
    r"STATE\s+TAX":                      "state_tax",
    r"SITW":                             "state_tax",
    r"IN\s+STATE\s+TAX":                "state_tax",     # Indiana
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
    r"NET\s+RETIRED\s+PAY":              "net_pay",
}

# Pay period month abbreviations and full names
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
            line_stripped = line.strip()
            for pattern, field_name in FIELD_MAP.items():
                if re.search(pattern, line_stripped, re.IGNORECASE):
                    amount = _extract_amount_from_line(line_stripped)
                    if amount is not None and field_name not in extracted:
                        extracted[field_name] = amount
                        raw_fields[line_stripped] = amount
                    break  # First matching pattern wins per line

        # ── Compute other_deductions ───────────────────────────────────
        # other = gross - net - (sum of known deductions)
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
        # If gross or net missing, leave other_deductions absent (→ NULL in DB)

        # ── Build preview ──────────────────────────────────────────────
        preview = {"pay_period": pay_period or "unknown"}
        for key in ["gross_pay", "federal_tax", "state_tax", "sbp_premium",
                    "health_insurance", "dental_vision", "other_deductions", "net_pay"]:
            if key in extracted:
                preview[key] = f"${extracted[key]:,.2f}"

        # ── Warnings ───────────────────────────────────────────────────
        warnings = []
        can_commit = True
        if not pay_period:
            warnings.append("Could not determine pay period — please verify before importing")
        if "gross_pay" not in extracted:
            warnings.append("Gross pay not found — verify this is a DFAS RAS PDF")
        if "net_pay" not in extracted:
            warnings.append("Net pay not found")

        # Silent-failure guard: recognized as a RAS but neither the
        # gross nor the net pay line extracted means the layout drifted
        # or the PDF is malformed. Committing a row where every dollar
        # field is NULL is worse than refusing — downstream cash-flow
        # recomputes would silently report $0 income for the month.
        if "gross_pay" not in extracted and "net_pay" not in extracted:
            warnings.append(
                "⚠ BLOCK: Recognized as a DFAS RAS but could not extract "
                "either gross pay or net pay. The statement layout may "
                "have changed. Committing now would record an empty "
                "payroll row and silently zero out this month's income. "
                "Re-upload only after the parser is updated."
            )
            can_commit = False

        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data={
                "pay_period": pay_period,
                "extracted": extracted,
                "raw_fields": raw_fields,
            },
            warnings=warnings,
            can_commit=can_commit,
        )

    def commit(self, conn, result: ParseResult) -> dict:
        """Insert or replace payroll_snapshots row."""
        data = result.data
        extracted = data.get("extracted", {})
        pay_period = data.get("pay_period") or datetime.now(timezone.utc).strftime("%Y-%m")

        # myPay RAS is a single-owner stream — attribute new ingests to the
        # configured primary owner so per-owner dashboards see them. (v22)
        from dal.owners import get_primary_owner
        owner_id = (get_primary_owner() or "quintin").lower()

        conn.execute(
            """
            INSERT INTO payroll_snapshots
                (pay_period, source, gross_pay, federal_tax, state_tax,
                 sbp_premium, health_insurance, dental_vision,
                 other_deductions, net_pay, raw_json, owner_id)
            VALUES (?, 'mypay_ras', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                owner_id,
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

    # Pattern 3: "PAY DATE: 02/01/2026" — derive month from MM/DD/YYYY date
    # Must be checked BEFORE bare MM/YYYY to avoid false positives
    m = re.search(r"PAY\s+DATE[:\s]+(\d{2})/\d{2}/(\d{4})", text, re.IGNORECASE)
    if m:
        month_num = int(m.group(1))
        if 1 <= month_num <= 12:
            return f"{m.group(2)}-{month_num:02d}"

    # Pattern 4: "02/2026" (bare MM/YYYY, no day component)
    m = re.search(r"\b(\d{2})/(\d{4})\b", text)
    if m:
        month_num = int(m.group(1))
        if 1 <= month_num <= 12:
            return f"{m.group(2)}-{month_num:02d}"

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
