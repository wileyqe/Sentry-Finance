"""
tests/test_t04_mypay.py — Tests for the myPay RAS parser (P2-T04).

Covers:
  a. can_parse() with recognition keywords → True
  b. can_parse() with random bytes → False
  c. _extract_pay_period() with sample text → correct YYYY-MM
  d. _extract_amount_from_line() with "$1,234.56" → 1234.56
  e. _extract_amount_from_line() with "GROSS PAY $3,456.00" → 3456.00
  f. other_deductions computation correctness
  g. commit() with a real temp DB: inserts correct row
"""

import io
import json
import sqlite3
import pytest

# We need a minimal PDF with the recognition keywords.
# pdfplumber requires a well-formed PDF, so we use reportlab to build one
# on the fly, or we mock at the pdfplumber level.
# Strategy: use a fake PDF approach — create a minimal PDF with fpdf if
# available, otherwise mock pdfplumber.

from dal.parsers.mypay_ras import (
    MyPayRASParser,
    _extract_pay_period,
    _extract_amount_from_line,
)
from dal.parsers.base import ParseResult


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_fake_pdf(text: str) -> bytes:
    """Create a minimal PDF containing the given text using fpdf2 or reportlab.

    Falls back to a monkeypatch-friendly approach if neither library is available.
    """
    try:
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        for line in text.split("\n"):
            pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())
    except ImportError:
        pass

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        y = 750
        for line in text.split("\n"):
            c.drawString(72, y, line)
            y -= 14
        c.save()
        return buf.getvalue()
    except ImportError:
        pass

    pytest.skip("Neither fpdf2 nor reportlab installed — cannot create test PDFs")


RAS_TEXT = """\
Defense Finance and Accounting Service
Retiree Account Statement
01 FEB 2026

GROSS PAY                    $3,000.00
FEDERAL WITHHOLDING          $500.00
STATE TAX                    $100.00
SBP PREMIUM                  $50.00
TRICARE PRIME                $150.00
DENTAL/VISION                $0.00
NET PAY                      $2,100.00
"""


# ── a. can_parse() with recognition keywords → True ──────────────────────────

def test_can_parse_with_keywords():
    parser = MyPayRASParser()
    pdf_bytes = _make_fake_pdf(RAS_TEXT)
    assert parser.can_parse("statement.pdf", pdf_bytes) is True


# ── b. can_parse() with random bytes → False ─────────────────────────────────

def test_can_parse_random_bytes():
    parser = MyPayRASParser()
    assert parser.can_parse("random.pdf", b"just some random bytes") is False


# ── c. _extract_pay_period() with sample text → correct YYYY-MM ──────────────

def test_extract_pay_period_dd_mmm_yyyy():
    assert _extract_pay_period("Statement for 01 FEB 2026") == "2026-02"


def test_extract_pay_period_full_month():
    assert _extract_pay_period("Pay Period: February 2026") == "2026-02"


def test_extract_pay_period_mm_slash_yyyy():
    assert _extract_pay_period("Period 02/2026 ending") == "2026-02"


def test_extract_pay_period_pay_date():
    assert _extract_pay_period("PAY DATE: 03/01/2026") == "2026-03"


def test_extract_pay_period_none():
    assert _extract_pay_period("No date here") is None


# ── d. _extract_amount_from_line() with "$1,234.56" ──────────────────────────

def test_extract_amount_dollar():
    assert _extract_amount_from_line("$1,234.56") == 1234.56


# ── e. _extract_amount_from_line() with "GROSS PAY $3,456.00" ────────────────

def test_extract_amount_label_plus_value():
    assert _extract_amount_from_line("GROSS PAY $3,456.00") == 3456.00


def test_extract_amount_no_dollar_sign():
    assert _extract_amount_from_line("GROSS PAY 3,456.00") == 3456.00


def test_extract_amount_no_match():
    assert _extract_amount_from_line("No amounts here") is None


# ── f. other_deductions computation ──────────────────────────────────────────

def test_other_deductions_computation():
    """gross=3000, net=2100, federal=500, state=100, sbp=50, health=150, dental=0
    → other = 3000 - 2100 - (500 + 100 + 50 + 150 + 0) = 900 - 800 = 100.0
    """
    parser = MyPayRASParser()
    pdf_bytes = _make_fake_pdf(RAS_TEXT)
    result = parser.parse(pdf_bytes)

    assert result.parser_type == "mypay_ras"
    assert result.data["extracted"]["gross_pay"] == 3000.00
    assert result.data["extracted"]["net_pay"] == 2100.00
    assert result.data["extracted"]["federal_tax"] == 500.00
    assert result.data["extracted"]["state_tax"] == 100.00
    assert result.data["extracted"]["sbp_premium"] == 50.00
    assert result.data["extracted"]["health_insurance"] == 150.00
    assert result.data["extracted"]["other_deductions"] == 100.00
    assert result.data["pay_period"] == "2026-02"


# ── g. commit() with a real temp DB ──────────────────────────────────────────

def test_commit_inserts_row():
    """Commit a ParseResult to a real SQLite DB and verify the row."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE payroll_snapshots (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            pay_period       TEXT NOT NULL,
            source           TEXT NOT NULL,
            gross_pay        REAL,
            federal_tax      REAL,
            state_tax        REAL,
            sbp_premium      REAL,
            health_insurance REAL,
            dental_vision    REAL,
            other_deductions REAL,
            net_pay          REAL,
            raw_json         TEXT,
            created_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(pay_period, source) ON CONFLICT REPLACE
        );
    """)

    result = ParseResult(
        parser_type="mypay_ras",
        preview={},
        data={
            "pay_period": "2026-02",
            "extracted": {
                "gross_pay": 3000.00,
                "federal_tax": 500.00,
                "state_tax": 100.00,
                "sbp_premium": 50.00,
                "health_insurance": 150.00,
                "dental_vision": 0.00,
                "other_deductions": 100.00,
                "net_pay": 2100.00,
            },
            "raw_fields": {"GROSS PAY $3,000.00": 3000.00},
        },
    )

    parser = MyPayRASParser()
    summary = parser.commit(conn, result)
    conn.commit()

    assert summary["pay_period"] == "2026-02"
    assert summary["gross_pay"] == 3000.00
    assert summary["net_pay"] == 2100.00
    assert summary["fields_extracted"] == 8

    row = conn.execute("SELECT * FROM payroll_snapshots WHERE pay_period = '2026-02'").fetchone()
    assert row is not None
    assert row["source"] == "mypay_ras"
    assert row["gross_pay"] == 3000.00
    assert row["federal_tax"] == 500.00
    assert row["state_tax"] == 100.00
    assert row["sbp_premium"] == 50.00
    assert row["health_insurance"] == 150.00
    assert row["dental_vision"] == 0.00
    assert row["other_deductions"] == 100.00
    assert row["net_pay"] == 2100.00
    assert json.loads(row["raw_json"]) == {"GROSS PAY $3,000.00": 3000.00}

    conn.close()


# ── h. Missing fields stored as None (not 0) ─────────────────────────────────

def test_missing_fields_are_none():
    """When a field is not in the PDF, it should be stored as NULL/None in DB."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE payroll_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pay_period TEXT NOT NULL, source TEXT NOT NULL,
            gross_pay REAL, federal_tax REAL, state_tax REAL,
            sbp_premium REAL, health_insurance REAL, dental_vision REAL,
            other_deductions REAL, net_pay REAL, raw_json TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(pay_period, source) ON CONFLICT REPLACE
        );
    """)

    result = ParseResult(
        parser_type="mypay_ras",
        preview={},
        data={
            "pay_period": "2026-01",
            "extracted": {"gross_pay": 3000.00, "net_pay": 2500.00},
            "raw_fields": {},
        },
    )

    parser = MyPayRASParser()
    parser.commit(conn, result)
    conn.commit()

    row = conn.execute("SELECT * FROM payroll_snapshots WHERE pay_period = '2026-01'").fetchone()
    assert row["gross_pay"] == 3000.00
    assert row["federal_tax"] is None  # Not 0
    assert row["state_tax"] is None
    assert row["sbp_premium"] is None

    conn.close()


# ── i. UNIQUE constraint re-import safety ────────────────────────────────────

def test_unique_constraint_replaces():
    """Re-importing the same pay_period+source should overwrite, not fail."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE payroll_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pay_period TEXT NOT NULL, source TEXT NOT NULL,
            gross_pay REAL, federal_tax REAL, state_tax REAL,
            sbp_premium REAL, health_insurance REAL, dental_vision REAL,
            other_deductions REAL, net_pay REAL, raw_json TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(pay_period, source) ON CONFLICT REPLACE
        );
    """)

    parser = MyPayRASParser()

    r1 = ParseResult(
        parser_type="mypay_ras", preview={},
        data={"pay_period": "2026-02", "extracted": {"gross_pay": 3000.00}, "raw_fields": {}},
    )
    parser.commit(conn, r1)
    conn.commit()

    r2 = ParseResult(
        parser_type="mypay_ras", preview={},
        data={"pay_period": "2026-02", "extracted": {"gross_pay": 3200.00}, "raw_fields": {}},
    )
    parser.commit(conn, r2)
    conn.commit()

    rows = conn.execute("SELECT * FROM payroll_snapshots WHERE pay_period = '2026-02'").fetchall()
    assert len(rows) == 1
    assert rows[0]["gross_pay"] == 3200.00  # Updated value

    conn.close()
