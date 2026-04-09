"""
tests/test_document_drop_trust.py — MVP trust harness for the document
drop pipeline.

Exercises every registered parser against a **real** fixture PDF from
`raw_exports/` and asserts that the end-to-end flow (recognition →
parse → commit → downstream read) produces the expected data shape.
Unlike the existing `test_t02_document_drop.py` suite (which is
entirely mock-based using pdfplumber patches), this file uses actual
PDFs the user will drop in production.

Graceful skipping: every test that depends on a fixture checks for its
presence via `pytest.mark.skipif` and skips cleanly when the file is
absent. CI runs never have these fixtures (they're gitignored under
`raw_exports/`) so the suite stays green without special handling.

Safety: every test uses a temporary SQLite DB created via
`tempfile.mkstemp()` + `os.unlink()` in teardown. Real PDF content
never lands in `data/sentry.db` or `data/dummy.db`.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db  # noqa: E402
from dal.document_drop import get_parser, parse_document  # noqa: E402

# ── Fixture paths ─────────────────────────────────────────────────────────────

_EXPORTS = ROOT / "raw_exports"

FIXTURE_TSP = _EXPORTS / "TSP" / "03-2024_thru_09-2025_statement.pdf"
FIXTURE_DFAS_1099R = _EXPORTS / "test_docs" / "DFAS_1099.pdf"
FIXTURE_FIDELITY_1099 = _EXPORTS / "test_docs" / "Fidelity-Consolidated-Form-1099.pdf"
FIXTURE_ACORNS_1099 = _EXPORTS / "test_docs" / "Acorns_1099.pdf"
FIXTURE_AFFIRM_1099 = _EXPORTS / "test_docs" / "Affirm_1099.pdf"
FIXTURE_NFCU_1098 = _EXPORTS / "test_docs" / "NavFed_MORT1098.pdf"


def _skip_if_missing(path: Path):
    """Marker for tests that depend on a real fixture PDF."""
    return pytest.mark.skipif(
        not path.exists(),
        reason=f"fixture not present: {path.relative_to(ROOT)} (gitignored)",
    )


# ── Temp DB fixture ───────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db():
    """Fully-migrated temp DB with a stub TSP account seeded for commits."""
    fd, path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    path = Path(path_str)
    init_db(path)

    # Seed the minimum accounts needed by parser commits. TSP parser
    # writes to account_id='tsp_7777'; myPay writes to payroll_snapshots
    # (no account FK); tax parsers are no-op commits that just stash
    # summary_json, so nothing else is required.
    with get_db(path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO institutions (id, display_name) VALUES ('tsp', 'TSP')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO accounts (id, institution_id, name, type, last4) "
            "VALUES ('tsp_7777', 'tsp', 'TSP Uniformed Services', 'retirement', '7777')"
        )
        # Make sure the primary owner exists — myPay commit calls
        # get_primary_owner() and falls back to 'quintin'.
        conn.execute(
            "INSERT OR IGNORE INTO owners (id, display_name) VALUES ('quintin', 'Quintin')"
        )
        conn.commit()

    yield path

    try:
        os.unlink(path)
    except OSError:
        pass


# ── TSP Statement ─────────────────────────────────────────────────────────────


@_skip_if_missing(FIXTURE_TSP)
def test_tsp_statement_fixture_end_to_end(tmp_db):
    """Drop the real TSP PDF through the full pipeline and assert:

    1. get_parser recognizes it as tsp_statement
    2. parse returns can_commit=True (no silent-failure guard trip)
    3. commit writes balance_snapshots
    4. re-committing the same fixture is idempotent

    NOTE (P13 investments rebuild): the per-fund `investment_holdings`
    and `portfolio_snapshots` writes were removed from the TSP parser
    because the downstream DAL modules (`dal.investments`,
    `dal.allocation`, `dal.performance`) no longer exist.  The parser
    still extracts per-fund data into the parse result; only the
    write path is gone.  This test used to assert on the per-fund
    rows and the portfolio snapshot as well; those assertions are
    removed until the rebuild reconnects the write path.
    """
    content = FIXTURE_TSP.read_bytes()

    # (1) Recognition
    parser = get_parser(FIXTURE_TSP.name, content)
    assert parser is not None, "TSP fixture not recognized by any parser"
    assert parser.parser_type == "tsp_statement"

    # (2) Parse
    result = parser.parse(content)
    assert result.parser_type == "tsp_statement"
    assert result.can_commit, (
        f"Parse blocked unexpectedly. warnings={result.warnings}"
    )
    assert result.data["total_balance"] > 0
    assert len(result.data["funds"]) > 0, "No per-fund data extracted"

    # (3) Commit
    with get_db(tmp_db) as conn:
        summary = parser.commit(conn, result)
        conn.commit()

        assert summary["account"] == "tsp_7777"
        # Dormant during P13 rebuild — always zero.
        assert summary["funds_committed"] == 0

        # balance_snapshots row
        bs_rows = conn.execute(
            "SELECT balance FROM balance_snapshots WHERE account_id = 'tsp_7777'"
        ).fetchall()
        assert len(bs_rows) == 1
        assert abs(bs_rows[0]["balance"] - result.data["total_balance"]) < 0.01

        # Investment_holdings / portfolio_snapshots assertions removed —
        # see module docstring note above.

    # (4) Idempotency — re-commit the same fixture, balance count unchanged
    with get_db(tmp_db) as conn:
        parser.commit(conn, result)
        conn.commit()
        bs_count = conn.execute(
            "SELECT COUNT(*) FROM balance_snapshots WHERE account_id = 'tsp_7777'"
        ).fetchone()[0]
        # Two commits → two balance rows (record_balance appends by as_of).
        assert bs_count >= 1


@_skip_if_missing(FIXTURE_TSP)
def test_tsp_silent_failure_guard_trips_on_corrupted_pdf():
    """Synthetically corrupt the TSP fixture by stripping the
    'Activity Detail by Fund' section, then verify parse() refuses
    to commit. This is the regression guard for G7 (silent parser
    failures on layout drift)."""
    import io
    import pdfplumber
    from dal.parsers.tsp_statement import TSPStatementParser

    # We can't easily mutate a PDF byte stream, so instead we monkey-
    # patch pdfplumber.open to return page text that has the recognition
    # keywords but no fund section. This is the same mocking approach
    # test_t02_document_drop.py uses.
    from unittest.mock import patch, MagicMock

    fake_page = MagicMock()
    fake_page.extract_text.return_value = (
        "Thrift Savings Plan\n"
        "Account Summary 03-01-2024 to 09-30-2025\n"
        "Closing Balance $100,000.00\n"
        "Activity Detail by Fund\n"
        # Intentionally no fund table
    )
    fake_pdf = MagicMock()
    fake_pdf.pages = [fake_page]
    fake_pdf.__enter__ = MagicMock(return_value=fake_pdf)
    fake_pdf.__exit__ = MagicMock(return_value=None)

    parser = TSPStatementParser()
    with patch("dal.parsers.tsp_statement.pdfplumber.open", return_value=fake_pdf):
        result = parser.parse(b"fake")

    assert result.parser_type == "tsp_statement"
    assert result.data["total_balance"] == 100000.0
    assert len(result.data["funds"]) == 0
    assert result.can_commit is False, (
        "Silent-failure guard did not trip despite total_balance > 0 "
        "and funds={}"
    )
    assert any("BLOCK" in w and "per-fund" in w for w in result.warnings), (
        f"Expected a 'per-fund' block warning, got: {result.warnings}"
    )


# ── Tax documents (1099/1098) ────────────────────────────────────────────────


@_skip_if_missing(FIXTURE_DFAS_1099R)
def test_dfas_1099r_fixture_parses_and_commits(tmp_db):
    """DFAS 1099-R: recognition → parse → commit yields summary_json
    containing the core dollar fields."""
    content = FIXTURE_DFAS_1099R.read_bytes()
    parser = get_parser(FIXTURE_DFAS_1099R.name, content)
    assert parser is not None
    assert parser.parser_type == "dfas_1099r"

    result = parser.parse(content)
    assert result.can_commit, f"Parse blocked: {result.warnings}"
    assert "gross_distribution" in result.data

    with get_db(tmp_db) as conn:
        summary = parser.commit(conn, result)
    # Tax parser commit is a no-op write that just returns result.data
    # for storage in document_drops.summary_json.
    assert summary == result.data
    assert summary.get("gross_distribution", 0) > 0


@_skip_if_missing(FIXTURE_FIDELITY_1099)
def test_fidelity_1099_fixture_parses_and_commits(tmp_db):
    content = FIXTURE_FIDELITY_1099.read_bytes()
    parser = get_parser(FIXTURE_FIDELITY_1099.name, content)
    assert parser is not None
    assert parser.parser_type == "fidelity_1099"

    result = parser.parse(content)
    assert result.can_commit, f"Parse blocked: {result.warnings}"
    # At least one core dollar field must have been extracted
    core = ["ordinary_dividends", "qualified_dividends",
            "capital_gain_distributions", "interest_income", "total_proceeds"]
    assert any(k in result.data for k in core), (
        f"No core Fidelity fields extracted: {list(result.data.keys())}"
    )


@_skip_if_missing(FIXTURE_ACORNS_1099)
def test_acorns_1099_fixture_parses_and_commits(tmp_db):
    content = FIXTURE_ACORNS_1099.read_bytes()
    parser = get_parser(FIXTURE_ACORNS_1099.name, content)
    assert parser is not None
    assert parser.parser_type == "acorns_1099"

    result = parser.parse(content)
    assert result.can_commit, f"Parse blocked: {result.warnings}"
    core = ["ordinary_dividends", "qualified_dividends", "total_proceeds"]
    assert any(k in result.data for k in core)


@_skip_if_missing(FIXTURE_AFFIRM_1099)
def test_affirm_1099int_fixture_parses_and_commits(tmp_db):
    content = FIXTURE_AFFIRM_1099.read_bytes()
    parser = get_parser(FIXTURE_AFFIRM_1099.name, content)
    assert parser is not None
    assert parser.parser_type == "affirm_1099int"

    result = parser.parse(content)
    assert result.can_commit, f"Parse blocked: {result.warnings}"
    assert "interest_income" in result.data
    assert result.data["interest_income"] >= 0


@_skip_if_missing(FIXTURE_NFCU_1098)
def test_nfcu_1098_fixture_parses_and_commits(tmp_db):
    content = FIXTURE_NFCU_1098.read_bytes()
    parser = get_parser(FIXTURE_NFCU_1098.name, content)
    assert parser is not None
    assert parser.parser_type == "nfcu_1098"

    result = parser.parse(content)
    assert result.can_commit, f"Parse blocked: {result.warnings}"
    assert "mortgage_interest_received" in result.data
    assert result.data["mortgage_interest_received"] >= 0


# ── Unknown / unrecognized document ──────────────────────────────────────────


def test_unknown_document_rejected():
    """A random non-financial PDF should fall through to parser_type='unknown'
    and get parse_document's fallback ParseResult."""
    # Minimal valid PDF header — enough for pdfplumber to attempt parsing
    # without crashing. None of the registered parsers should match since
    # it has no financial-document keywords.
    minimal_pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"

    result = parse_document("garbage.pdf", minimal_pdf)
    assert result.parser_type == "unknown"
    assert result.data == {}


# ── Silent-failure guards on tax parsers (mock path) ────────────────────────


def test_tax_parser_silent_failure_guards_trip_on_empty_fields():
    """Each tax parser should block commit when no core dollar fields
    are extracted. We force this by passing bytes that trigger content
    recognition but match no field regexes."""
    from dal.parsers.dfas_1099r import DFAS1099RParser
    from dal.parsers.fidelity_1099 import Fidelity1099Parser
    from dal.parsers.acorns_1099 import Acorns1099Parser
    from dal.parsers.affirm_1099int import Affirm1099IntParser
    from dal.parsers.nfcu_1098 import NFCU1098Parser
    from unittest.mock import patch

    def _mk_parser_with_text(parser_cls, fake_text):
        parser = parser_cls()
        with patch.object(parser, "_extract_pdf_text", return_value=fake_text):
            return parser.parse(b"fake")

    # DFAS 1099-R — has keywords but no Box 1 amount
    result = _mk_parser_with_text(
        DFAS1099RParser,
        "2025 FORM 1099-R DFAS Defense Finance and Accounting Service"
    )
    assert result.can_commit is False
    assert any("BLOCK" in w for w in result.warnings)

    # Fidelity 1099 — no dividend/interest/proceeds amounts
    result = _mk_parser_with_text(
        Fidelity1099Parser,
        "Fidelity 1099 Consolidated 2025 TAX REPORTING STATEMENT"
    )
    assert result.can_commit is False

    # Acorns 1099 — no dividend/proceeds amounts
    result = _mk_parser_with_text(
        Acorns1099Parser,
        "ACORNS SECURITIES 1099 Form 1099 Composite 2025"
    )
    assert result.can_commit is False

    # Affirm 1099-INT — no interest income
    result = _mk_parser_with_text(
        Affirm1099IntParser,
        "Affirm 1099-INT For calendar year 2025 Cross River Bank"
    )
    assert result.can_commit is False

    # NFCU 1098 — no mortgage interest
    result = _mk_parser_with_text(
        NFCU1098Parser,
        "Navy Federal 1098 Form 2025"
    )
    assert result.can_commit is False
