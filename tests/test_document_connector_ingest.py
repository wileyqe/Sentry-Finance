"""
tests/test_document_connector_ingest.py — Shared document-ingest helper (P17-T25).

The myPay connector and the manual `/api/documents/upload` +
`/api/documents/commit` router both go through `backend.document_ingest`
to produce identical `document_drops` / `payroll_snapshots` rows.

These tests pin that contract:

  a. `ingest_document` writes both `payroll_snapshots` AND a committed
     `document_drops` row from a parser-backed myPay RAS PDF.
  b. The `mypay_ras` parser_type triggers the post-commit pipeline
     for institution "mypay" (run_pipeline=True path).
  c. Recognition failure → `RecognitionError`; silent-failure guard
     → `ParseBlockedError`.
  d. The connector's `ingest_ras_pdf` entry point routes through the
     shared helper and refuses non-RAS PDFs even if the underlying
     parser would accept them.
"""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.document_ingest import (
    ParseBlockedError,
    RecognitionError,
    PARSER_INSTITUTION_MAP,
    ingest_document,
    stage_document,
)


# ── Shared fixtures: minimal in-memory DB + fake PDF text ───────────────────


def _make_fake_pdf(text: str) -> bytes:
    """Produce a real PDF the existing MyPayRASParser can read."""
    try:
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        for line in text.split("\n"):
            pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())
    except ImportError:
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
            pytest.skip("Neither fpdf2 nor reportlab installed")


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


@pytest.fixture
def mem_conn():
    """In-memory SQLite DB with the tables the ingest path writes to."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE document_drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name    TEXT NOT NULL,
            parser_type  TEXT NOT NULL,
            file_size    INTEGER,
            dropped_at   TEXT DEFAULT (datetime('now')),
            committed_at TEXT,
            summary_json TEXT,
            owner_id     TEXT
        );
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
            owner_id         TEXT,
            created_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(pay_period, source) ON CONFLICT REPLACE
        );
    """)
    yield conn
    conn.close()


def _patch_get_db(mem_conn):
    """Make backend.document_ingest.get_db return the in-memory connection."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mem_conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return patch("backend.document_ingest.get_db", return_value=ctx)


# ── a. ingest_document writes payroll_snapshots + document_drops ────────────


def test_ingest_document_writes_both_tables(mem_conn):
    """Connector-side ingest must produce both rows the manual flow does."""
    pdf_bytes = _make_fake_pdf(RAS_TEXT)

    with _patch_get_db(mem_conn), \
         patch("backend.document_ingest.run_post_commit_pipeline", create=True):
        # Skip pipeline by using run_pipeline=False — we're asserting
        # the write contract, not the cascade.
        outcome = ingest_document(
            "mypay_ras_2026-02_test.pdf", pdf_bytes, run_pipeline=False
        )

    assert outcome.parser_type == "mypay_ras"
    assert outcome.summary["pay_period"] == "2026-02"
    assert outcome.summary["gross_pay"] == 3000.00
    assert outcome.summary["net_pay"] == 2100.00

    # document_drops row exists, committed_at populated, file_id stable.
    drops = mem_conn.execute(
        "SELECT * FROM document_drops WHERE parser_type = 'mypay_ras'"
    ).fetchall()
    assert len(drops) == 1
    drop = dict(drops[0])
    assert drop["committed_at"] is not None
    assert drop["file_size"] == len(pdf_bytes)
    assert drop["file_name"] == "mypay_ras_2026-02_test.pdf"
    summary_json = json.loads(drop["summary_json"])
    assert summary_json["pay_period"] == "2026-02"
    assert summary_json["gross_pay"] == 3000.00
    assert "file_id" in summary_json

    # payroll_snapshots row exists with correct values.
    payroll = mem_conn.execute(
        "SELECT * FROM payroll_snapshots WHERE pay_period = '2026-02'"
    ).fetchone()
    assert payroll is not None
    assert payroll["source"] == "mypay_ras"
    assert payroll["gross_pay"] == 3000.00
    assert payroll["net_pay"] == 2100.00
    # myPay RAS is single-owner — owner_id must be the primary owner.
    assert payroll["owner_id"] is not None


def test_parser_institution_map_includes_mypay():
    """Connector path needs `mypay_ras` → `mypay` to fire post-commit pipeline."""
    assert PARSER_INSTITUTION_MAP["mypay_ras"] == "mypay"


# ── b. Post-commit pipeline dispatch ─────────────────────────────────────────


def test_ingest_document_triggers_pipeline_for_mypay(mem_conn):
    """run_pipeline=True must call run_post_commit_pipeline('mypay')."""
    pdf_bytes = _make_fake_pdf(RAS_TEXT)

    with _patch_get_db(mem_conn), \
         patch("backend.result_writer.run_post_commit_pipeline") as mock_pipeline:
        mock_pipeline.return_value = {"categorization": {"matched": 0}}
        outcome = ingest_document(
            "mypay_ras_2026-02_test.pdf", pdf_bytes, run_pipeline=True
        )

    # The helper imports run_post_commit_pipeline lazily from
    # backend.result_writer; the patched symbol must have been called
    # exactly once with institution="mypay".
    mock_pipeline.assert_called_once_with("mypay")
    assert outcome.pipeline.get("categorization") == {"matched": 0}


# ── c. Recognition / silent-failure guard error paths ───────────────────────


def test_ingest_document_recognition_error(mem_conn):
    """Non-recognized bytes raise RecognitionError without writing rows."""
    with _patch_get_db(mem_conn):
        with pytest.raises(RecognitionError):
            ingest_document("random.txt", b"not a pdf", run_pipeline=False)

    # No payroll_snapshots row should have been written.
    rows = mem_conn.execute("SELECT COUNT(*) AS c FROM payroll_snapshots").fetchone()
    assert rows["c"] == 0


def test_ingest_document_blocks_on_silent_failure_guard(mem_conn):
    """Silent-failure guards must surface as ParseBlockedError + skip commit."""
    # Build a RAS PDF that lacks BOTH gross and net pay → the
    # MyPayRASParser silent-failure guard trips and sets can_commit=False.
    bad_text = (
        "Defense Finance and Accounting Service\n"
        "Retiree Account Statement\n"
        "01 MAR 2026\n"
        "STATE TAX           $50.00\n"
    )
    pdf_bytes = _make_fake_pdf(bad_text)

    with _patch_get_db(mem_conn):
        with pytest.raises(ParseBlockedError) as exc_info:
            ingest_document("bad_ras.pdf", pdf_bytes, run_pipeline=False)

    assert exc_info.value.parser_type == "mypay_ras"
    assert any("BLOCK" in w for w in exc_info.value.warnings)

    # No payroll_snapshots row should have been written even though
    # stage_document inserted a document_drops row earlier.
    rows = mem_conn.execute("SELECT COUNT(*) AS c FROM payroll_snapshots").fetchone()
    assert rows["c"] == 0
    # The staged document_drops row exists but stays uncommitted.
    drop = mem_conn.execute(
        "SELECT * FROM document_drops WHERE parser_type = 'mypay_ras'"
    ).fetchone()
    assert drop is not None
    assert drop["committed_at"] is None


# ── d. ingest_ras_pdf module entry refuses non-RAS PDFs ─────────────────────


def test_ingest_ras_pdf_refuses_non_ras_pdf(mem_conn):
    """`ingest_ras_pdf` is the connector-side guard; mismatched parser → raise."""
    from extractors.mypay_connector import ingest_ras_pdf

    # A PDF that the MyPayRASParser doesn't recognize → ingest_document
    # raises RecognitionError BEFORE we even reach the parser_type check.
    with _patch_get_db(mem_conn):
        with pytest.raises(RecognitionError):
            ingest_ras_pdf("not_ras.pdf", b"%PDF-1.4 random")


def test_ingest_ras_pdf_refuses_recognized_non_ras_before_db_write(mem_conn):
    """F2 regression: a recognized non-RAS doc must produce zero writes.

    The earlier test exercised the unrecognized path (no parser
    matches at all). This test fakes a successful recognition for a
    non-mypay parser_type (e.g. tsp_statement) and proves that the
    pre-stage `expected_parser_type` guard fires BEFORE
    `document_drops` insert, BEFORE any target-table commit, and
    BEFORE the post-commit pipeline dispatch.
    """
    from extractors.mypay_connector import ingest_ras_pdf

    fake_parser = MagicMock()
    fake_parser.parser_type = "tsp_statement"
    # parse() / commit() / resolve_owner_id() must NEVER be called on
    # this parser — the guard runs before them.
    fake_parser.parse = MagicMock(side_effect=AssertionError(
        "parser.parse must not run when expected_parser_type mismatches"
    ))
    fake_parser.commit = MagicMock(side_effect=AssertionError(
        "parser.commit must not run when expected_parser_type mismatches"
    ))
    fake_parser.resolve_owner_id = MagicMock(side_effect=AssertionError(
        "parser.resolve_owner_id must not run when expected_parser_type mismatches"
    ))

    received_pipeline_calls: list[str] = []

    def _fake_pipeline(institution_id):
        received_pipeline_calls.append(institution_id)
        return {}

    with _patch_get_db(mem_conn), \
         patch("backend.document_ingest.get_parser", return_value=fake_parser), \
         patch(
             "backend.result_writer.run_post_commit_pipeline",
             side_effect=_fake_pipeline,
         ):
        with pytest.raises(RecognitionError, match=r"mypay_ras"):
            ingest_ras_pdf("looks_like_tsp.pdf", b"%PDF-1.4 fake")

    # Nothing landed in the DB.
    drops = mem_conn.execute(
        "SELECT COUNT(*) AS c FROM document_drops"
    ).fetchone()
    assert drops["c"] == 0
    payroll = mem_conn.execute(
        "SELECT COUNT(*) AS c FROM payroll_snapshots"
    ).fetchone()
    assert payroll["c"] == 0
    # Pipeline was never dispatched.
    assert received_pipeline_calls == []
    # The fake parser's parse/commit/resolve_owner_id never ran (all
    # three would have raised AssertionError if they had).


# ── e. Manual document-drop path still works through the helper ────────────


def test_stage_document_writes_pending_row(mem_conn):
    """Upload step writes an UN-committed document_drops row."""
    pdf_bytes = _make_fake_pdf(RAS_TEXT)
    with _patch_get_db(mem_conn):
        staged = stage_document("mypay_ras_2026-02_test.pdf", pdf_bytes)

    assert staged.parser_type == "mypay_ras"
    assert staged.can_commit is True
    assert staged.preview["gross_pay"] == "$3,000.00"

    drop = mem_conn.execute(
        "SELECT * FROM document_drops WHERE id = ?", (staged.document_drop_id,)
    ).fetchone()
    assert drop is not None
    assert drop["committed_at"] is None
    summary = json.loads(drop["summary_json"])
    assert summary == {"file_id": staged.file_id, "staged": True}
    # Cleanup the staged file so we don't pollute raw_exports/.
    try:
        staged.staged_path.unlink()
    except Exception:
        pass
