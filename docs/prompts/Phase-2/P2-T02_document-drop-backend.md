# P2-T02: Document Drop Backend

## Context

You are working on Sentry Finance, a local-first personal finance app.
Some institutions resist full automation (TSP is Tier 2 but still manual
during MFA; myPay has no API; tax docs come as PDFs once a year). The
document drop system lets the user drag-and-drop a PDF or XLSX file onto
the dashboard and have it auto-recognized and parsed.

This task builds the **server-side backend only** (upload endpoint,
auto-recognition, parsers, database schema, commit endpoint). The
frontend drag-and-drop UI is built in P2-T03.

From `ARCHITECTURE.md § 3.3`:
> UI accepts drag-and-drop of PDF and XLSX files.
> Auto-recognition: file content is matched against known document parsers.
> Parsed data is ingested into the appropriate tables.
> If a Tier 3 institution hasn't been updated by the 5th of the month,
> a persistent toast remains on screen until the document is dropped.

---

## Starting State

### Database schema version: V13 (22 tables)
Migration files are in `dal/migrations/`. The latest is `v13_user_rules.py`.
New migrations must follow the naming pattern `vNN_description.py` with
a `VERSION = NN` constant and a `run(conn)` function.

### Existing TSP parser (adapt, don't duplicate):
`scripts/ingest_tsp.py` already implements a working TSP statement parser
with these functions:
- `parse_statement(pdf_path)` → `{statement_date, total_balance, funds: {name: {units, nav, balance}}}`
- `_parse_activity_detail(text, result)` → fills the funds dict
- `_clean_number(val)` → parses dollar/numeric strings to float

The document drop TSP parser should reuse this logic, adapted to accept
`bytes` instead of a file path.

### Existing `dal/balances.py`:
Contains `record_balance(conn, account_id, balance, as_of)` used to
write balance snapshots.

### Existing `dal/database.py`:
- `get_db()` — context manager returning a WAL-mode SQLite connection
- `init_db()` — runs all migrations in sequence

### Migration pattern (from `v13_user_rules.py`):
```python
VERSION = 13

def run(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_categorization_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ...
        );
    """)
```

The migration runner in `dal/database.py` reads `VERSION` and runs `run(conn)`.

---

## Task

### 1. Create `dal/migrations/v14_document_drops.py`

Track uploaded document history:

```python
VERSION = 14

def run(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS document_drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name    TEXT NOT NULL,
            parser_type  TEXT NOT NULL,    -- 'tsp_statement', 'mypay_ras', 'unknown', etc.
            file_size    INTEGER,
            dropped_at   TEXT DEFAULT (datetime('now')),
            committed_at TEXT,             -- NULL until user confirms
            summary_json TEXT              -- JSON blob of what was parsed/committed
        );
    """)
```

### 2. Create `dal/parsers/__init__.py`

```python
"""dal/parsers — Document parsers for the document drop system."""
```

### 3. Create `dal/parsers/base.py`

Abstract base for all document parsers:

```python
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
```

### 4. Create `dal/parsers/tsp_statement.py`

Adapt `scripts/ingest_tsp.py` to work with bytes input instead of file path:

```python
"""
dal/parsers/tsp_statement.py — TSP quarterly statement parser.

Recognizes: TSP statement PDFs containing "Thrift Savings Plan"
            and "Activity Detail by Fund".

Parses: per-fund unit counts, NAV prices, closing balances, statement date.

Commits: balance_snapshot + portfolio_snapshot for account tsp_7777.
"""

import io
import re
import logging
from datetime import datetime

import pdfplumber

from dal.parsers.base import DocumentParser, ParseResult
from dal.balances import record_balance

log = logging.getLogger("sentry.parsers.tsp_statement")

RECOGNITION_KEYWORDS = ["Thrift Savings Plan", "Activity Detail by Fund"]


class TSPStatementParser(DocumentParser):

    @property
    def parser_type(self) -> str:
        return "tsp_statement"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        """Check for TSP-specific keywords in first-page text."""
        try:
            with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
                first_text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
                return all(kw in first_text for kw in RECOGNITION_KEYWORDS)
        except Exception:
            return False

    def parse(self, content_bytes: bytes) -> ParseResult:
        """Extract statement date, total balance, per-fund positions."""
        with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        result = {
            "statement_date": None,
            "total_balance": 0.0,
            "funds": {},
        }

        # Extract statement end date
        m = re.search(
            r"Account Summary\s+\d{2}-\d{2}-\d{4}\s+to\s+(\d{2}-\d{2}-\d{4})",
            full_text
        )
        if m:
            result["statement_date"] = datetime.strptime(m.group(1), "%m-%d-%Y").date().isoformat()

        # Extract total closing balance
        m = re.search(r"Closing Balance\s+\$([\d,]+\.\d{2})", full_text)
        if m:
            result["total_balance"] = _clean_number(m.group(1))

        # Per-fund activity detail
        with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if "Activity Detail by Fund" in text:
                    _parse_activity_detail(text, result)
                    break

        preview = {
            "statement_date": result["statement_date"] or "unknown",
            "total_balance": f"${result['total_balance']:,.2f}",
            "funds_found": len(result["funds"]),
            "fund_breakdown": {
                name: f"${data['balance']:,.2f}"
                for name, data in result["funds"].items()
            },
        }

        warnings = []
        if not result["statement_date"]:
            warnings.append("Could not extract statement date — will use today's date")
        if result["total_balance"] <= 0:
            warnings.append("Total balance is zero — verify the PDF is a TSP statement")

        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data=result,
            warnings=warnings,
        )

    def commit(self, conn, result: ParseResult) -> dict:
        """Write balance + portfolio snapshot to DB."""
        data = result.data
        total = data["total_balance"]
        as_of = data.get("statement_date") or datetime.utcnow().date().isoformat()
        now = datetime.utcnow().isoformat()

        record_balance(conn, "tsp_7777", total, as_of + "T12:00:00")
        conn.execute(
            """
            INSERT INTO portfolio_snapshots
                (account_id, timestamp, total_account_value, cash_balance)
            VALUES (?, ?, ?, ?)
            """,
            ("tsp_7777", now, total, 0.0),
        )
        return {
            "account": "tsp_7777",
            "total_balance": total,
            "statement_date": as_of,
            "funds_committed": len(data.get("funds", {})),
        }


# ── Helpers (adapted from scripts/ingest_tsp.py) ─────────────────────────────

def _parse_activity_detail(text: str, result: dict) -> None:
    lines = text.split("\n")
    fund_names = []
    for line in lines:
        if "Fund Name" in line:
            parts = line.split("All Funds Total")
            if len(parts) > 1:
                names = re.findall(r"(L\s+\d{4}|[GCFSI]\s+Fund|L\s+Income)", parts[1])
                fund_names = names
            break

    if not fund_names:
        return

    closing_balances, closing_units, nav_prices = [], [], []
    for line in lines:
        if line.strip().startswith("Closing Balance"):
            closing_balances = [_clean_number(a) for a in re.findall(r"\$([\d,]+\.\d{2})", line)[1:]]
        elif "Closing Units" in line:
            closing_units = [_clean_number(u) for u in re.findall(r"([\d,]+\.\d{3})", line)]
        elif "Unit Price (NAV)" in line:
            nav_prices = [float(p) for p in re.findall(r"(\d+\.\d{4,6})", line)]

    for i, fund in enumerate(fund_names):
        result["funds"][fund] = {
            "units": closing_units[i] if i < len(closing_units) else 0.0,
            "nav": nav_prices[i] if i < len(nav_prices) else 0.0,
            "balance": closing_balances[i] if i < len(closing_balances) else 0.0,
        }


def _clean_number(val: str) -> float:
    if not val:
        return 0.0
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except ValueError:
        return 0.0
```

### 5. Create `dal/document_drop.py`

Auto-recognition and orchestration:

```python
"""
dal/document_drop.py — Document drop recognition and routing.

Provides:
  recognize(filename, content_bytes) -> parser | None
  parse(filename, content_bytes) -> ParseResult
"""

import logging
from dal.parsers.base import DocumentParser, ParseResult
from dal.parsers.tsp_statement import TSPStatementParser
# Future parsers imported here:
# from dal.parsers.mypay_ras import MyPayRASParser

log = logging.getLogger("sentry.dal.document_drop")

# Ordered list of all registered parsers (first match wins)
_PARSERS: list[DocumentParser] = [
    TSPStatementParser(),
    # MyPayRASParser(),  # P2-T04
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
            warnings=["Document type not recognized. Supported: TSP statement."],
        )
    return parser.parse(content_bytes)
```

### 6. Create `backend/routers/documents.py`

```python
"""
backend/routers/documents.py — Document drop endpoints.

Flow:
  POST /api/documents/upload  → auto-recognize, parse, return preview
  POST /api/documents/commit  → commit parsed data to DB
  GET  /api/documents/history → list past document drops
"""

import json
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel

from dal.database import get_db
from dal.document_drop import parse_document, get_parser
from backend.result_writer import run_post_commit_pipeline

log = logging.getLogger("sentry.backend.api.documents")
router = APIRouter(tags=["documents"])

# Temp staging area for uploaded files pending commit
_STAGING_DIR = Path(__file__).resolve().parent.parent.parent / "raw_exports" / "document_drop"
_STAGING_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB limit


@router.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """Accept a document, auto-recognize type, parse, return preview.

    Does NOT commit to database — use /commit to finalize.
    """
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (50 MB max).")

    filename = file.filename or "unknown"
    result = parse_document(filename, content)

    # Stage the file so /commit can re-parse without re-upload
    file_id = str(uuid.uuid4())
    ext = Path(filename).suffix or ".bin"
    staged_path = _STAGING_DIR / f"{file_id}{ext}"
    staged_path.write_bytes(content)

    # Record the upload attempt in document_drops
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO document_drops (id, file_name, parser_type, file_size)
            VALUES (?, ?, ?, ?)
            """,
            # Use file_id as a text ID embedded in summary — actual PK is autoincrement
        )
        # Insert with summary
        conn.execute(
            """
            INSERT INTO document_drops (file_name, parser_type, file_size, summary_json)
            VALUES (?, ?, ?, ?)
            """,
            (filename, result.parser_type, len(content),
             json.dumps({"file_id": file_id, "staged": True})),
        )
        conn.commit()

    return {
        "file_id": file_id,
        "filename": filename,
        "parser_type": result.parser_type,
        "preview": result.preview,
        "warnings": result.warnings,
        "can_commit": result.parser_type != "unknown",
    }


class CommitRequest(BaseModel):
    file_id: str


@router.post("/api/documents/commit")
def commit_document(body: CommitRequest):
    """Commit a previously uploaded document to the database."""
    # Find staged file
    matches = list(_STAGING_DIR.glob(f"{body.file_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Staged file not found. Re-upload required.")

    staged_path = matches[0]
    content = staged_path.read_bytes()
    filename = staged_path.name

    # Re-parse (deterministic)
    parser = get_parser(filename, content)
    if parser is None:
        raise HTTPException(status_code=422, detail="Document type not recognized.")

    parse_result = parser.parse(content)
    if parse_result.parser_type == "unknown":
        raise HTTPException(status_code=422, detail="Parser failed to extract data.")

    # Commit to DB
    with get_db() as conn:
        try:
            summary = parser.commit(conn, parse_result)
            conn.execute(
                """
                UPDATE document_drops
                SET committed_at = datetime('now'), summary_json = ?
                WHERE summary_json LIKE ?
                """,
                (json.dumps({**summary, "file_id": body.file_id}),
                 f'%"file_id": "{body.file_id}"%'),
            )
            conn.commit()
        except Exception as e:
            log.error("Document commit failed: %s", e)
            raise HTTPException(status_code=500, detail=f"Commit failed: {e}")

    # Determine institution from parser_type for post-commit pipeline
    institution_map = {
        "tsp_statement": "tsp",
        "mypay_ras": None,   # No connector institution; pipeline runs selectively
    }
    institution = institution_map.get(parse_result.parser_type)
    pipeline_summary = {}
    if institution:
        try:
            pipeline_summary = run_post_commit_pipeline(institution)
        except Exception as e:
            log.warning("Post-commit pipeline failed (non-fatal): %s", e)

    # Clean up staged file
    try:
        staged_path.unlink()
    except Exception:
        pass

    return {
        "status": "committed",
        "parser_type": parse_result.parser_type,
        "summary": summary,
        "pipeline": pipeline_summary,
    }


@router.get("/api/documents/history")
def document_history(limit: int = 20):
    """List past document drops."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, file_name, parser_type, file_size,
                   dropped_at, committed_at, summary_json
            FROM document_drops
            ORDER BY dropped_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"documents": [dict(r) for r in rows]}


@router.get("/api/documents/pending-nudges")
def pending_nudges():
    """Return Tier 3 institutions overdue for a document drop.

    'Overdue' = institution has no committed document this calendar month
    and today is on or after the 5th.
    """
    from datetime import date
    today = date.today()
    if today.day < 5:
        return {"nudges": []}

    current_month = today.strftime("%Y-%m")

    with get_db() as conn:
        # TSP statement: check for committed tsp_statement this month
        tsp_row = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM document_drops
            WHERE parser_type = 'tsp_statement'
              AND committed_at IS NOT NULL
              AND committed_at >= ?
            """,
            (current_month + "-01",),
        ).fetchone()

    nudges = []
    if not tsp_row or tsp_row["cnt"] == 0:
        nudges.append({
            "institution": "tsp",
            "display_name": "Thrift Savings Plan",
            "message": "TSP statement not received this month. Drop your PDF to update.",
        })

    return {"nudges": nudges}
```

### 7. Register documents router in `backend/api_server.py`

```python
from backend.routers import (
    # ... existing imports ...
    documents,    # ← add
)

app.include_router(documents.router)   # ← add
```

---

## Fix the upload endpoint INSERT

The `/api/documents/upload` endpoint has a broken INSERT above — it has
two `conn.execute()` calls, the first of which has a syntax error.
Replace both with a single correct INSERT:

```python
with get_db() as conn:
    conn.execute(
        """
        INSERT INTO document_drops (file_name, parser_type, file_size, summary_json)
        VALUES (?, ?, ?, ?)
        """,
        (filename, result.parser_type, len(content),
         json.dumps({"file_id": file_id, "staged": True})),
    )
    conn.commit()
```

---

## Files to Create

1. `dal/migrations/v14_document_drops.py`
2. `dal/parsers/__init__.py`
3. `dal/parsers/base.py`
4. `dal/parsers/tsp_statement.py`
5. `dal/document_drop.py`
6. `backend/routers/documents.py`

## Files to Modify

7. `backend/api_server.py` — register documents router

## Files NOT to Modify

- `scripts/ingest_tsp.py` — leave as-is (still useful for initial backfill)
- Any frontend files
- Any existing connector files
- `dal/balances.py` — use `record_balance` as-is

---

## Constraints

- `pdfplumber` is already installed (used by `scripts/ingest_tsp.py`)
- The staging directory must be under `raw_exports/document_drop/` (gitignored)
- 50 MB upload cap is sufficient for any PDF statement or XLSX export
- The commit step MUST be idempotent-ish: if the same PDF is re-committed,
  it just adds another record (timestamps differ) — no uniqueness constraint
- Parser recognition MUST use content signals, not just filename
- `unknown` parser_type: upload succeeds (200), `can_commit: false` returned,
  user sees "unrecognized document" message
- `run_post_commit_pipeline` from `backend/result_writer.py` — it accepts
  `institution_id` string. For TSP document drops: pass `"tsp"`. For myPay:
  skip (no institution ID maps to it in the orchestrator)
- `dal/database.py` `init_db()` automatically picks up the new v14 migration
  because it scans `dal/migrations/` for all `vNN_*.py` files

---

## Done Checklist

- [ ] `dal/migrations/v14_document_drops.py` with `VERSION = 14`
- [ ] `dal/parsers/__init__.py`, `base.py`, `tsp_statement.py` created
- [ ] `dal/document_drop.py` with `get_parser()` and `parse_document()`
- [ ] `backend/routers/documents.py` with upload, commit, history, pending-nudges endpoints
- [ ] Documents router registered in `api_server.py`
- [ ] `document_drops` table created via migration (no manual SQL needed)
- [ ] Upload endpoint: saves staged file, records drop, returns preview
- [ ] Commit endpoint: re-parses from staged file, writes to DB, deletes staged file
- [ ] TSP statement parser: reuses `_parse_activity_detail` and `_clean_number` logic
- [ ] `can_parse` uses content keywords, not filename
- [ ] INSERT in upload endpoint is a single correct SQL statement

## Verification

After completion, Claude will:
1. Read all new files — check for the broken INSERT and fix it
2. Run migration: `python -c "from dal.database import init_db; init_db(); print('OK')"`
3. Run import check: `python -c "from dal.document_drop import parse_document; print('OK')"`
4. Run import check: `python -c "from backend.routers.documents import router; print('OK')"`
5. Write a pytest test for TSP statement parser: give it a mock PDF bytes object
   (or mock pdfplumber), verify ParseResult structure
6. Test the recognition logic with a fake document that should NOT match
7. Verify `pending-nudges` logic returns correct results based on today's date
