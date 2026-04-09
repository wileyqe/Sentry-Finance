"""Acorns Consolidated 1099 PDF parser."""

import re
import sqlite3
import logging
from dal.parsers.base import DocumentParser, ParseResult

log = logging.getLogger("sentry.parsers.acorns_1099")

class Acorns1099Parser(DocumentParser):
    @property
    def parser_type(self) -> str:
        return "acorns_1099"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        """Detect Acorns 1099 by filename or content."""
        name = filename.lower()
        if "acorns" in name and "1099" in name:
            return True
        try:
            text = self._extract_pdf_text(content_bytes)
            return "ACORNS SECURITIES" in text and "1099" in text
        except Exception:
            return False

    def parse(self, content_bytes: bytes) -> ParseResult:
        try:
            text = self._extract_pdf_text(content_bytes)
        except Exception as e:
            return ParseResult(self.parser_type, {}, {}, [f"PDF extraction failed: {e}"])
            
        fields = {}
        
        # We need to extract: ordinary_dividends, qualified_dividends,
        # total_proceeds, total_cost_basis, tax_year.
        
        m_div_1a = re.search(r"1a[\-\s]*Total ordinary dividends.*?([\d,]+\.\d{2})", text, re.IGNORECASE)
        if m_div_1a: fields["ordinary_dividends"] = float(m_div_1a.group(1).replace(",", ""))
            
        m_div_1b = re.search(r"1b[\-\s]*Qualified dividends.*?([\d,]+\.\d{2})", text, re.IGNORECASE)
        if m_div_1b: fields["qualified_dividends"] = float(m_div_1b.group(1).replace(",", ""))
            
        # Acorns Proceeds / Cost are usually in the Summary table
        m_st = re.search(r"Total Short-term\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})", text, re.IGNORECASE)
        m_lt = re.search(r"Total Long-term\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})", text, re.IGNORECASE)
        
        pro = 0.0
        cost = 0.0
        if m_st:
            pro += float(m_st.group(1).replace(",", ""))
            cost += float(m_st.group(2).replace(",", ""))
        if m_lt:
            pro += float(m_lt.group(1).replace(",", ""))
            cost += float(m_lt.group(2).replace(",", ""))
            
        if pro > 0: fields["total_proceeds"] = pro
        if cost > 0: fields["total_cost_basis"] = cost
            
        # Year
        my = re.search(r"Form 1099 Composite\s+([2]\d{3})", text, re.IGNORECASE)
        if not my:
            my = re.search(r"Form 1099DIV.*?20\d{2}.*?20\d{2}.*?(20\d{2})", text, re.DOTALL)
        if my: fields["tax_year"] = my.group(1)
            
        warnings = []
        can_commit = True
        if not fields.get("tax_year"):
            warnings.append("Could not extract tax year.")

        # Silent-failure guard: recognized as an Acorns 1099 but none
        # of the core dollar fields were extracted.
        core_fields = ["ordinary_dividends", "qualified_dividends", "total_proceeds"]
        if not any(k in fields for k in core_fields):
            warnings.append(
                "⚠ BLOCK: Recognized as an Acorns 1099 but could not "
                "extract any core dollar fields (dividends or proceeds). "
                "The form layout may have changed."
            )
            can_commit = False

        preview = {
            "Tax Year": fields.get("tax_year", "Unknown"),
            "Ordinary Div": f"${fields.get('ordinary_dividends', 0):,.2f}",
            "Proceeds": f"${fields.get('total_proceeds', 0):,.2f}",
        }

        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data=fields,
            warnings=warnings,
            can_commit=can_commit,
        )

    def commit(self, conn: sqlite3.Connection, result: ParseResult) -> dict:
        return result.data
