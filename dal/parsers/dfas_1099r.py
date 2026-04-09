"""DFAS 1099-R (Military Pension Distribution) PDF parser."""

import re
import sqlite3
import logging
from dal.parsers.base import DocumentParser, ParseResult

log = logging.getLogger("sentry.parsers.dfas_1099r")

class DFAS1099RParser(DocumentParser):
    @property
    def parser_type(self) -> str:
        return "dfas_1099r"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        """Detect DFAS 1099-R by filename or content."""
        name = filename.lower()
        if "1099" in name and ("dfas" in name or "ras" in name):
            return True
        try:
            text = self._extract_pdf_text(content_bytes)
            return "1099-R" in text and ("DFAS" in text or "Defense Finance" in text)
        except Exception:
            return False

    def parse(self, content_bytes: bytes) -> ParseResult:
        try:
            text = self._extract_pdf_text(content_bytes)
        except Exception as e:
            return ParseResult(self.parser_type, {}, {}, [f"PDF extraction failed: {e}"])
            
        fields = {}
        
        # Gross distribution (Box 1)
        m = re.search(r"1\s*Gross distribution.{1,150}?\$[\s]*([\d,]+\.\d{2})", text, re.DOTALL | re.IGNORECASE)
        if m: fields["gross_distribution"] = float(m.group(1).replace(",", ""))
            
        # Taxable amount (Box 2a)
        m2 = re.search(r"2a\s*Taxable amount.{1,150}?\$[\s]*([\d,]+\.\d{2})", text, re.DOTALL | re.IGNORECASE)
        if m2: fields["taxable_amount"] = float(m2.group(1).replace(",", ""))
            
        # Federal income tax withheld (Box 4)
        m4 = re.search(r"4\s*Federal[a-z\s]*withheld.{1,150}?\$[\s]*([\d,]+\.\d{2})", text, re.DOTALL | re.IGNORECASE)
        if m4: fields["federal_tax_withheld"] = float(m4.group(1).replace(",", ""))
            
        # State tax withheld
        m12 = re.search(r"14\s*State tax withheld.{1,150}?\$[\s]*([\d,]+\.\d{2})", text, re.DOTALL | re.IGNORECASE)
        if m12: fields["state_tax_withheld"] = float(m12.group(1).replace(",", ""))
            
        # Distribution code (Box 7)
        m7 = re.search(r"7\s*Distribution code\s*([A-Z0-9]+)", text)
        if m7: fields["distribution_code"] = m7.group(1)
            
        # Year - look for common year format at top
        my = re.search(r"(20\d{2})\s+FORM 1099-R", text, re.IGNORECASE)
        if my: fields["tax_year"] = my.group(1)
            
        warnings = []
        can_commit = True
        if not fields.get("tax_year"):
            warnings.append("Could not extract tax year.")

        # Silent-failure guard: recognized as a DFAS 1099-R but the
        # gross distribution is missing → the PDF layout changed or
        # it's a false positive. A "committed" badge with zero dollar
        # fields is misleading; refuse the commit.
        if "gross_distribution" not in fields:
            warnings.append(
                "⚠ BLOCK: Recognized as a DFAS 1099-R but could not "
                "extract the gross distribution (Box 1). The form "
                "layout may have changed — re-upload only after the "
                "parser is updated."
            )
            can_commit = False

        preview = {
            "Tax Year": fields.get("tax_year", "Unknown"),
            "Gross Distribution": f"${fields.get('gross_distribution', 0):,.2f}",
            "Taxable Amount": f"${fields.get('taxable_amount', 0):,.2f}",
            "Fed Tax Withheld": f"${fields.get('federal_tax_withheld', 0):,.2f}",
        }

        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data=fields,
            warnings=warnings,
            can_commit=can_commit,
        )

    def commit(self, conn: sqlite3.Connection, result: ParseResult) -> dict:
        """Tax parsers do not write to ledger tables. Return data to be saved in summary_json."""
        return result.data
