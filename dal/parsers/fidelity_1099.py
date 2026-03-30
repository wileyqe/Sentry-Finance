"""Fidelity Consolidated 1099 PDF parser."""

import re
import sqlite3
import logging
from dal.parsers.base import DocumentParser, ParseResult

log = logging.getLogger("sentry.parsers.fidelity_1099")

class Fidelity1099Parser(DocumentParser):
    @property
    def parser_type(self) -> str:
        return "fidelity_1099"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        """Detect Fidelity 1099 by filename or content."""
        name = filename.lower()
        if "1099" in name and "fidelity" in name:
            return True
        try:
            text = self._extract_pdf_text(content_bytes)
            return "Fidelity" in text and "1099" in text and "Consolidated" in text
        except Exception:
            return False

    def parse(self, content_bytes: bytes) -> ParseResult:
        try:
            text = self._extract_pdf_text(content_bytes)
        except Exception as e:
            return ParseResult(self.parser_type, {}, {}, [f"PDF extraction failed: {e}"])
            
        fields = {}
        
        # We need to extract: ordinary_dividends, qualified_dividends, capital_gain_distributions,
        # total_proceeds, total_cost_basis, total_gain_loss, interest_income, tax_year.
        
        m_div_1a = re.search(r"1a\s+Total ordinary dividends.*?([\d,]+\.\d{2})", text, re.IGNORECASE)
        if m_div_1a: fields["ordinary_dividends"] = float(m_div_1a.group(1).replace(",", ""))
            
        m_div_1b = re.search(r"1b\s+Qualified dividends.*?([\d,]+\.\d{2})", text, re.IGNORECASE)
        if m_div_1b: fields["qualified_dividends"] = float(m_div_1b.group(1).replace(",", ""))
            
        m_div_2a = re.search(r"2a\s+Total capital gain distr.*?([\d,]+\.\d{2})", text, re.IGNORECASE)
        if m_div_2a: fields["capital_gain_distributions"] = float(m_div_2a.group(1).replace(",", ""))
            
        m_b_proc = re.search(r"Total proceeds.*?([\d,]+\.\d{2})", text, re.IGNORECASE)
        if m_b_proc: fields["total_proceeds"] = float(m_b_proc.group(1).replace(",", ""))
            
        m_b_cost = re.search(r"Total cost basis.*?([\d,]+\.\d{2})", text, re.IGNORECASE)
        if m_b_cost: fields["total_cost_basis"] = float(m_b_cost.group(1).replace(",", ""))
            
        m_b_gain = re.search(r"Net gain \(loss\).*?(\-?[\d,]+\.\d{2})", text, re.IGNORECASE)
        if m_b_gain: fields["total_gain_loss"] = float(m_b_gain.group(1).replace(",", ""))
            
        m_int_1 = re.search(r"1\s+Interest income.*?([\d,]+\.\d{2})", text, re.IGNORECASE)
        if m_int_1: fields["interest_income"] = float(m_int_1.group(1).replace(",", ""))
            
        # Year
        my = re.search(r"(20\d{2})\s+TAX REPORTING STATEMENT", text, re.IGNORECASE)
        if not my:
            my = re.search(r"(20\d{2})\s+Consolidated Form 1099", text, re.IGNORECASE)
        if my: fields["tax_year"] = my.group(1)
            
        warnings = []
        if not fields.get("tax_year"):
            warnings.append("Could not extract tax year.")
            
        preview = {
            "Tax Year": fields.get("tax_year", "Unknown"),
            "Ordinary Div": f"${fields.get('ordinary_dividends', 0):,.2f}",
            "Interest": f"${fields.get('interest_income', 0):,.2f}",
        }
            
        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data=fields,
            warnings=warnings
        )

    def commit(self, conn: sqlite3.Connection, result: ParseResult) -> dict:
        return result.data
