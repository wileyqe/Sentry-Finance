"""
dal/parsers/base.py — Abstract base class for document parsers.

All parsers implement:
  - can_parse(filename, content_bytes) -> bool  (recognition check)
  - parse(content_bytes) -> ParseResult          (extraction)
  - commit(conn, parse_result) -> dict           (write to DB, return summary)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import sqlite3


@dataclass
class ParseResult:
    """Result of parsing a document. Used for preview and commit."""
    parser_type: str
    preview: dict           # Human-readable key-value pairs for UI confirmation
    data: dict              # Raw parsed data passed to commit()
    warnings: list[str] = field(default_factory=list)


class DocumentParser(ABC):
    """Base class for all document parsers."""

    @property
    @abstractmethod
    def parser_type(self) -> str:
        """Unique identifier string, e.g. 'tsp_statement'."""
        ...

    @abstractmethod
    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        """Return True if this parser can handle this document.

        Use CONTENT signals (keywords in first-page text), not just filename.
        Filename is unreliable — users rename files.
        """
        ...

    @abstractmethod
    def parse(self, content_bytes: bytes) -> ParseResult:
        """Parse the document and return structured data + preview."""
        ...

    @abstractmethod
    def commit(self, conn: sqlite3.Connection, result: ParseResult) -> dict:
        """Write parsed data to the database. Return a summary dict."""
        ...

    @staticmethod
    def _extract_pdf_text(file_bytes: bytes) -> str:
        """Extract text from a PDF file using pdfplumber."""
        import io
        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages)
