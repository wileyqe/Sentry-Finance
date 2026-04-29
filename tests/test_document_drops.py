import os
import sys
import tempfile
from pathlib import Path

import pytest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.parsers.tsp_statement import TSPStatementParser  # noqa: E402
from backend.routers.documents import pending_nudges  # noqa: E402
from dal.database import init_db  # noqa: E402

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    fd, path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    path = Path(path_str)
    previous = os.environ.get("SENTRY_DB_PATH")
    os.environ["SENTRY_DB_PATH"] = str(path)
    init_db(path)
    yield
    if previous is None:
        os.environ.pop("SENTRY_DB_PATH", None)
    else:
        os.environ["SENTRY_DB_PATH"] = previous
    try:
        os.unlink(path)
    except OSError:
        pass

@patch('dal.parsers.tsp_statement.pdfplumber.open')
def test_tsp_statement_parser_success(mock_pdfplumber_open):
    # Setup mock
    mock_pdf = MagicMock()
    mock_page1 = MagicMock()
    
    # We combine it into one page so that it hits both extract end date and activity detail
    activity_text = """
    Thrift Savings Plan
    Account Summary 01-01-2023 to 03-31-2023
    Closing Balance $100,000.00
    
    Activity Detail by Fund
    Fund Name All Funds Total L 2050 C Fund
    Opening Balance $90,000.00 $40,000.00 $50,000.00
    Closing Balance $100,000.00 $45,000.00 $55,000.00
    Closing Units 1,000.000 2,000.000
    Unit Price (NAV) 45.0000 27.5000
    """
    mock_page1.extract_text.return_value = activity_text
    
    mock_pdf.pages = [mock_page1]
    
    mock_context_manager = MagicMock()
    mock_context_manager.__enter__.return_value = mock_pdf
    mock_pdfplumber_open.return_value = mock_context_manager

    parser = TSPStatementParser()
    fake_bytes = b"fake pdf content"
    
    # Test recognition
    assert parser.can_parse("stmt.pdf", fake_bytes) is True
    
    # Test extraction
    result = parser.parse(fake_bytes)
    assert result.parser_type == "tsp_statement"
    assert result.data["statement_date"] == "2023-03-31"
    assert result.data["total_balance"] == 100000.0
    
    assert "L 2050" in result.data["funds"]
    assert "C Fund" in result.data["funds"]
    
    assert result.data["funds"]["L 2050"]["balance"] == 45000.0
    assert result.data["funds"]["L 2050"]["units"] == 1000.0
    assert result.data["funds"]["L 2050"]["nav"] == 45.0

def test_tsp_statement_parser_recognition_failure():
    parser = TSPStatementParser()
    assert parser.can_parse("dummy.pdf", b"not a pdf") is False

def test_pending_nudges():
    from datetime import date
    
    res = pending_nudges()
    assert "nudges" in res
    
    today = date.today()
    if today.day < 5:
        assert len(res["nudges"]) == 0
    else:
        # Before we add a drop, if today is > 5th, it should nudge
        pass
