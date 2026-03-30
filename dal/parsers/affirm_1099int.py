"""Affirm 1099-INT PDF parser."""

import re
import sqlite3
import logging
from dal.parsers.base import DocumentParser, ParseResult

log = logging.getLogger("sentry.parsers.affirm_1099int")

class Affirm1099IntParser(DocumentParser):
    @property
    def parser_type(self) -> str:
        return "affirm_1099int"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        name = filename.lower()
        if "1099" in name and "affirm" in name:
            return True
        try:
            text = self._extract_pdf_text(content_bytes)
            return ("Affirm" in text or "Cross River Bank" in text) and "1099-INT" in text
        except Exception:
            return False

    def parse(self, content_bytes: bytes) -> ParseResult:
        try:
            text = self._extract_pdf_text(content_bytes)
        except Exception as e:
            return ParseResult(self.parser_type, {}, {}, [f"PDF extraction failed: {e}"])
            
        fields = {}
        
        m_int_1 = re.search(r"1\s*Interest income.{1,200}?\$[\s]*([\d,]+\.\d{2})", text, re.DOTALL | re.IGNORECASE)
        if m_int_1: fields["interest_income"] = float(m_int_1.group(1).replace(",", ""))
            
        my = re.search(r"For calendar year.*?([2]\d{3})", text, re.DOTALL | re.IGNORECASE)
        if my: fields["tax_year"] = my.group(1)
            
        warnings = []
        if not fields.get("tax_year"):
            warnings.append("Could not extract tax year.")
            
        preview = {
            "Tax Year": fields.get("tax_year", "Unknown"),
            "Interest Earned": f"${fields.get('interest_income', 0):,.2f}",
        }
            
        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data=fields,
            warnings=warnings
        )

    def commit(self, conn: sqlite3.Connection, result: ParseResult) -> dict:
        return result.data
