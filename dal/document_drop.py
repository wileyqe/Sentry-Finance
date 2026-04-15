"""
dal/document_drop.py — Document drop recognition and routing.

Provides:
  recognize(filename, content_bytes) -> parser | None
  parse(filename, content_bytes) -> ParseResult
"""

import logging
from dal.parsers.base import DocumentParser, ParseResult
from dal.parsers.tsp_statement import TSPStatementParser
from dal.parsers.mypay_ras import MyPayRASParser
from dal.parsers.eventlink import EventlinkParser
from dal.parsers.dfas_1099r import DFAS1099RParser
from dal.parsers.fidelity_1099 import Fidelity1099Parser
from dal.parsers.acorns_1099 import Acorns1099Parser
from dal.parsers.acorns_confirmation import AcornsConfirmationParser
from dal.parsers.acorns_statement import AcornsStatementParser
from dal.parsers.affirm_1099int import Affirm1099IntParser
from dal.parsers.nfcu_1098 import NFCU1098Parser

log = logging.getLogger("sentry.dal.document_drop")

# Ordered list of all registered parsers (first match wins)
_PARSERS: list[DocumentParser] = [
    TSPStatementParser(),
    MyPayRASParser(),
    EventlinkParser(),
    DFAS1099RParser(),
    Fidelity1099Parser(),
    AcornsConfirmationParser(),
    AcornsStatementParser(),
    Acorns1099Parser(),
    Affirm1099IntParser(),
    NFCU1098Parser(),
]


def get_parser(filename: str, content_bytes: bytes) -> DocumentParser | None:
    """Return the first parser that claims it can handle this document."""
    for parser in _PARSERS:
        try:
            if parser.can_parse(filename, content_bytes):
                log.info("Document '%s' matched parser: %s", filename, parser.parser_type)
                return parser
        except Exception as e:
            log.warning("Parser %s raised during recognition: %s", parser.parser_type, e)
    log.info("Document '%s' — no matching parser found", filename)
    return None


def parse_document(filename: str, content_bytes: bytes) -> ParseResult:
    """Auto-recognize and parse a document. Returns ParseResult with parser_type='unknown'
    if no parser matches."""
    parser = get_parser(filename, content_bytes)
    if parser is None:
        return ParseResult(
            parser_type="unknown",
            preview={"message": "No parser found for this document type."},
            data={},
            warnings=["Document type not recognized. Supported: TSP statement, myPay RAS."],
        )
    return parser.parse(content_bytes)
