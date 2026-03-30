"""Navy Federal Mortgage 1098 PDF parser."""

import re
import sqlite3
import logging
from dal.parsers.base import DocumentParser, ParseResult

log = logging.getLogger("sentry.parsers.nfcu_1098")

class NFCU1098Parser(DocumentParser):
    @property
    def parser_type(self) -> str:
        return "nfcu_1098"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        name = filename.lower()
        if "1098" in name and ("navy federal" in name or "navfed" in name):
            return True
        try:
            text = self._extract_pdf_text(content_bytes).lower()
            return "navy federal" in text and "1098" in text
        except Exception:
            return False

    def parse(self, content_bytes: bytes) -> ParseResult:
        try:
            text = self._extract_pdf_text(content_bytes)
        except Exception as e:
            return ParseResult(self.parser_type, {}, {}, [f"PDF extraction failed: {e}"])
            
        fields = {}
        
        # 1 Mortgage interest received
        m_int = re.search(r"Mortgagei?\s*nter\s*est.{1,200}?\$([\s\d,]+\.\s*\d{2})", text, re.IGNORECASE | re.DOTALL)
        if m_int: fields["mortgage_interest_received"] = float(re.sub(r'[\s,]', '', m_int.group(1)))
            
        # 2 Outstanding mortgage principal
        m_prin = re.search(r"Outstanding\s*mortgage\s*prin.{1,200}?\$([\s\d,]+\.\s*\d{2})", text, re.IGNORECASE | re.DOTALL)
        if m_prin: fields["outstanding_mortgage_principal"] = float(re.sub(r'[\s,]', '', m_prin.group(1)))
            
        # 5 Mortgage insurance premiums
        m_mip = re.search(r"Mortgage\s*insuranc\s*e\s*pre\s*miums.{1,200}?\$([\s\d,]+\.\s*\d{2})", text, re.IGNORECASE | re.DOTALL)
        if m_mip: fields["mortgage_insurance_premiums"] = float(re.sub(r'[\s,]', '', m_mip.group(1)))
        
        # 6 / 11 Property taxes 
        m_tax = re.search(r"Real\s*Esta\s*te\s*Ta\s*x.{1,50}?([\s\d,]+\.\s*\d{2})", text, re.IGNORECASE | re.DOTALL)
        if not m_tax:
            m_tax = re.search(r"Property\s*taxes.{1,200}?\$([\s\d,]+\.\s*\d{2})", text, re.IGNORECASE | re.DOTALL)
        if m_tax: fields["property_taxes"] = float(re.sub(r'[\s,]', '', m_tax.group(1)))
            
        my = re.search(r"\b([2]\d{3})\b", text)
        if my: fields["tax_year"] = my.group(1)
            
        warnings = []
        if not fields.get("tax_year"):
            warnings.append("Could not extract tax year.")
            
        preview = {
            "Tax Year": fields.get("tax_year", "Unknown"),
            "Interest Paid": f"${fields.get('mortgage_interest_received', 0):,.2f}",
        }
            
        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data=fields,
            warnings=warnings
        )

    def commit(self, conn: sqlite3.Connection, result: ParseResult) -> dict:
        return result.data
