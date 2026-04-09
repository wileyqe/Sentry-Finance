"""
tests/test_t02_document_drop.py — Verify P2-T02: document drop backend.

Tests:
  - ParseResult and DocumentParser base class contract
  - TSPStatementParser recognition and parse helpers
  - document_drop.get_parser() routing
  - document_drop.parse_document() unknown fallback
  - documents router: upload, commit, history, pending-nudges endpoints
  - v14 migration: document_drops table schema
  - pending_nudges logic
"""
import io
import json
import sqlite3
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from dal.parsers.base import DocumentParser, ParseResult
from dal.parsers.tsp_statement import (
    TSPStatementParser,
    _clean_number,
    _parse_activity_detail,
)
from dal.document_drop import get_parser, parse_document


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_conn():
    """In-memory SQLite DB with the tables TSP commit() writes to."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS document_drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name    TEXT NOT NULL,
            parser_type  TEXT NOT NULL,
            file_size    INTEGER,
            dropped_at   TEXT DEFAULT (datetime('now')),
            committed_at TEXT,
            summary_json TEXT
        );
        CREATE TABLE IF NOT EXISTS balance_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            as_of TEXT NOT NULL,
            balance REAL NOT NULL,
            refresh_run_id TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            total_account_value REAL,
            cash_balance REAL DEFAULT 0.0
        );
        -- Added for M1: TSP commit() now writes per-fund holdings via
        -- dal.investments.upsert_holding(). Mirror the real schema
        -- (including the Decimal *_dec columns and the ON CONFLICT key).
        CREATE TABLE IF NOT EXISTS investment_holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            shares REAL NOT NULL,
            close_price REAL,
            market_value REAL,
            cost_basis REAL,
            created_at TEXT DEFAULT (datetime('now')),
            shares_dec TEXT,
            close_price_dec TEXT,
            market_value_dec TEXT,
            cost_basis_dec TEXT,
            UNIQUE(account_id, date, ticker)
        );
    """)
    yield conn
    conn.close()


# ── ParseResult dataclass ─────────────────────────────────────────────────────

def test_parse_result_defaults():
    """ParseResult warnings default to empty list."""
    r = ParseResult(parser_type="test", preview={}, data={})
    assert r.warnings == []
    assert r.parser_type == "test"


def test_parse_result_with_warnings():
    r = ParseResult(
        parser_type="tsp_statement",
        preview={"balance": "$100"},
        data={"total_balance": 100.0},
        warnings=["missing date"],
    )
    assert len(r.warnings) == 1
    assert r.data["total_balance"] == 100.0


# ── DocumentParser ABC ────────────────────────────────────────────────────────

def test_document_parser_is_abstract():
    """Cannot instantiate DocumentParser directly — it is an ABC."""
    with pytest.raises(TypeError):
        DocumentParser()


# ── TSPStatementParser helpers ────────────────────────────────────────────────

def test_clean_number_basic():
    assert _clean_number("$36,901.55") == 36901.55
    assert _clean_number("1,234.56") == 1234.56
    assert _clean_number("0.00") == 0.0


def test_clean_number_empty():
    assert _clean_number("") == 0.0
    assert _clean_number(None) == 0.0


def test_clean_number_invalid():
    assert _clean_number("N/A") == 0.0


def test_parse_activity_detail_extracts_funds():
    """_parse_activity_detail populates result['funds'] from table text."""
    sample_text = (
        "Activity Detail by Fund\n"
        "Fund Name  All Funds Total  L 2065  C Fund  S Fund\n"
        "Opening Balance $300,000.00 $100,000.00 $120,000.00 $80,000.00\n"
        "Closing Balance $310,000.00 $103,000.00 $124,000.00 $83,000.00\n"
        "Closing Units  1830.661  802.341  1100.000\n"
        "Unit Price (NAV)  20.1575  103.6295  75.4545\n"
    )
    result = {"statement_date": None, "total_balance": 310000.0, "funds": {}}
    _parse_activity_detail(sample_text, result)

    assert "L 2065" in result["funds"]
    assert "C Fund" in result["funds"]
    assert "S Fund" in result["funds"]
    assert result["funds"]["L 2065"]["units"] == 1830.661
    assert result["funds"]["C Fund"]["nav"] == 103.6295


# ── TSPStatementParser.can_parse ──────────────────────────────────────────────

def test_tsp_parser_can_parse_positive():
    """PDF bytes with both recognition keywords → True."""
    parser = TSPStatementParser()
    fake_text = "Thrift Savings Plan\nActivity Detail by Fund\nsome content"

    # Simulate pdfplumber returning our fake text
    mock_page = MagicMock()
    mock_page.extract_text.return_value = fake_text
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    with patch("dal.parsers.tsp_statement.pdfplumber.open", return_value=mock_pdf):
        assert parser.can_parse("statement.pdf", b"fake") is True


def test_tsp_parser_can_parse_negative_wrong_content():
    """PDF with only one keyword → False."""
    parser = TSPStatementParser()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Thrift Savings Plan\nsome other content"
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    with patch("dal.parsers.tsp_statement.pdfplumber.open", return_value=mock_pdf):
        assert parser.can_parse("statement.pdf", b"fake") is False


def test_tsp_parser_can_parse_exception_returns_false():
    """Exception during recognition → False (never propagates)."""
    parser = TSPStatementParser()
    with patch("dal.parsers.tsp_statement.pdfplumber.open", side_effect=Exception("corrupt")):
        assert parser.can_parse("bad.pdf", b"garbage") is False


# ── TSPStatementParser.parse ──────────────────────────────────────────────────

def _make_tsp_pdf_mock(full_text: str, activity_text: str | None = None):
    """Create a mock pdfplumber context for TSPStatementParser.parse()."""
    # parse() opens pdfplumber twice: once for full_text, once for activity detail
    page1 = MagicMock()
    page1.extract_text.return_value = full_text

    activity_page = MagicMock()
    activity_page.extract_text.return_value = activity_text or full_text

    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [page1, activity_page]
    return mock_pdf


def test_tsp_parser_parse_extracts_date_and_balance():
    parser = TSPStatementParser()
    text = (
        "Account Summary 01-01-2026 to 03-31-2026\n"
        "Closing Balance $310,000.00\n"
        "Activity Detail by Fund\n"
        "Fund Name All Funds Total L 2065 C Fund\n"
        "Closing Balance $310,000.00 $103,000.00 $207,000.00\n"
        "Closing Units 5000.000 2000.000\n"
        "Unit Price (NAV) 20.6000 103.5000\n"
    )
    mock_pdf = _make_tsp_pdf_mock(text)
    with patch("dal.parsers.tsp_statement.pdfplumber.open", return_value=mock_pdf):
        result = parser.parse(b"fake")

    assert result.parser_type == "tsp_statement"
    assert result.data["statement_date"] == "2026-03-31"
    assert result.data["total_balance"] == 310000.0
    assert result.warnings == []  # No warnings when date and balance are found


def test_tsp_parser_parse_warns_on_missing_date():
    parser = TSPStatementParser()
    text = "Closing Balance $100,000.00\nActivity Detail by Fund\nFund Name All Funds Total\n"
    mock_pdf = _make_tsp_pdf_mock(text)
    with patch("dal.parsers.tsp_statement.pdfplumber.open", return_value=mock_pdf):
        result = parser.parse(b"fake")

    assert result.data["statement_date"] is None
    assert any("date" in w.lower() for w in result.warnings)


def test_tsp_parser_parse_warns_on_zero_balance():
    parser = TSPStatementParser()
    text = "Account Summary 01-01-2026 to 03-31-2026\nNo balance line here\n"
    mock_pdf = _make_tsp_pdf_mock(text)
    with patch("dal.parsers.tsp_statement.pdfplumber.open", return_value=mock_pdf):
        result = parser.parse(b"fake")

    assert result.data["total_balance"] == 0.0
    assert any("zero" in w.lower() for w in result.warnings)


# ── TSPStatementParser.commit ─────────────────────────────────────────────────

def test_tsp_parser_commit_writes_balance_and_portfolio(mem_conn):
    parser = TSPStatementParser()
    parse_result = ParseResult(
        parser_type="tsp_statement",
        preview={},
        data={
            "statement_date": "2026-03-31",
            "total_balance": 310000.0,
            "funds": {"L 2065": {"units": 5000, "nav": 20.6, "balance": 103000}},
        },
    )
    summary = parser.commit(mem_conn, parse_result)

    assert summary["account"] == "tsp_7777"
    assert summary["total_balance"] == 310000.0
    assert summary["statement_date"] == "2026-03-31"
    assert summary["funds_committed"] == 1

    # Verify balance_snapshot was written
    row = mem_conn.execute(
        "SELECT balance FROM balance_snapshots WHERE account_id = 'tsp_7777'"
    ).fetchone()
    assert row is not None
    assert row["balance"] == 310000.0

    # Verify portfolio_snapshot was written
    row = mem_conn.execute(
        "SELECT total_account_value FROM portfolio_snapshots WHERE account_id = 'tsp_7777'"
    ).fetchone()
    assert row is not None
    assert row["total_account_value"] == 310000.0

    # M1 regression: per-fund holdings must also land in investment_holdings.
    # The old commit() extracted funds but dropped them on the floor —
    # the user dropping a real TSP PDF saw an empty per-fund breakdown on
    # the Investments page. This assertion locks the fix.
    holdings = mem_conn.execute(
        "SELECT ticker, shares, close_price, market_value, cost_basis "
        "FROM investment_holdings WHERE account_id = 'tsp_7777'"
    ).fetchall()
    assert len(holdings) == 1
    h = holdings[0]
    assert h["ticker"] == "TSP_L2065"
    assert h["shares"] == 5000
    assert h["close_price"] == 20.6
    assert h["market_value"] == 103000
    assert h["cost_basis"] is None  # TSP PDFs don't report cost basis


def test_tsp_parser_commit_uses_today_when_no_date(mem_conn):
    """commit() falls back to a date string when statement_date is None."""
    parser = TSPStatementParser()
    parse_result = ParseResult(
        parser_type="tsp_statement",
        preview={},
        data={"statement_date": None, "total_balance": 50000.0, "funds": {}},
    )
    summary = parser.commit(mem_conn, parse_result)
    # Code uses datetime.utcnow().date() — just verify it's a valid YYYY-MM-DD
    import re
    assert re.match(r"\d{4}-\d{2}-\d{2}", summary["statement_date"])


# ── get_parser routing ────────────────────────────────────────────────────────

def test_get_parser_returns_tsp_parser_for_tsp_content():
    """get_parser returns TSPStatementParser when content matches."""
    fake_text = "Thrift Savings Plan\nActivity Detail by Fund"
    mock_page = MagicMock()
    mock_page.extract_text.return_value = fake_text
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    with patch("dal.parsers.tsp_statement.pdfplumber.open", return_value=mock_pdf):
        parser = get_parser("whatever.pdf", b"fake")

    assert parser is not None
    assert parser.parser_type == "tsp_statement"


def test_get_parser_returns_none_for_unknown():
    """get_parser returns None when no parser matches."""
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Some random bank PDF content"
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    with patch("dal.parsers.tsp_statement.pdfplumber.open", return_value=mock_pdf):
        parser = get_parser("unknown.pdf", b"fake")

    assert parser is None


# ── parse_document fallback ───────────────────────────────────────────────────

def test_parse_document_returns_unknown_when_no_parser():
    """parse_document returns unknown ParseResult when content doesn't match."""
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Unrecognized document content"
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    with patch("dal.parsers.tsp_statement.pdfplumber.open", return_value=mock_pdf):
        result = parse_document("random.pdf", b"fake")

    assert result.parser_type == "unknown"
    assert len(result.warnings) > 0


# ── pending_nudges logic ──────────────────────────────────────────────────────

def test_pending_nudges_returns_tsp_when_no_commit_this_month(mem_conn):
    """pending_nudges returns TSP nudge when no tsp_statement committed this month."""
    from backend.routers.documents import pending_nudges
    today = date.today()

    if today.day < 5:
        pytest.skip("Nudge only fires on day >= 5")

    with patch("backend.routers.documents.get_db") as mock_get_db:
        # Make get_db() context manager return mem_conn
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mem_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_ctx

        result = pending_nudges()

    assert "nudges" in result
    institutions = [n["institution"] for n in result["nudges"]]
    assert "tsp" in institutions


def test_pending_nudges_suppressed_before_5th():
    """pending_nudges returns no nudges before the 5th of the month."""
    from backend.routers.documents import pending_nudges

    # date is now a module-level import in documents.py, so patch it there
    fake_date = MagicMock(wraps=date)
    fake_date.today.return_value = date(2026, 3, 3)  # Day 3 — before threshold
    with patch("backend.routers.documents.date", fake_date):
        result = pending_nudges()

    assert result == {"nudges": []}


def test_pending_nudges_no_tsp_when_committed_this_month(mem_conn):
    """No TSP nudge when a tsp_statement was committed this month."""
    from backend.routers.documents import pending_nudges
    today = date.today()

    if today.day < 5:
        pytest.skip("Nudge only fires on day >= 5")

    current_month = today.strftime("%Y-%m")
    # Insert a committed drop this month
    mem_conn.execute(
        """
        INSERT INTO document_drops (file_name, parser_type, file_size, committed_at)
        VALUES ('tsp.pdf', 'tsp_statement', 1024, ?)
        """,
        (current_month + "-10T12:00:00",),
    )
    mem_conn.commit()

    with patch("backend.routers.documents.get_db") as mock_get_db:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mem_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_ctx

        result = pending_nudges()

    institutions = [n["institution"] for n in result["nudges"]]
    assert "tsp" not in institutions


# ── v14 migration schema ──────────────────────────────────────────────────────

def test_v14_migration_creates_document_drops_table():
    """v14 migration creates document_drops with all expected columns."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    from dal.migrations.v14_document_drops import run
    run(conn)

    cols = [r[1] for r in conn.execute("PRAGMA table_info(document_drops)").fetchall()]
    expected = {"id", "file_name", "parser_type", "file_size",
                "dropped_at", "committed_at", "summary_json"}
    assert expected == set(cols)
    conn.close()


def test_v14_migration_is_idempotent():
    """Running v14 migration twice does not raise (CREATE TABLE IF NOT EXISTS)."""
    conn = sqlite3.connect(":memory:")
    from dal.migrations.v14_document_drops import run
    run(conn)
    run(conn)   # Should not raise
    conn.close()
