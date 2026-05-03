"""
backend/document_ingest.py — Shared document upload+commit helper.

Both the manual upload flow (`backend/routers/documents.py`) and
automated connector flows (e.g. `extractors/mypay_connector.py`) need
to:

  1. Recognize the document via `dal.document_drop.get_parser`
  2. Parse it (enforcing `ParseResult.can_commit`)
  3. Stage the bytes under `raw_exports/document_drop/{file_id}{ext}`
     so a follow-up `/api/documents/commit` (or replay tooling) can
     re-parse without re-upload
  4. Insert / update the `document_drops` row with parser type,
     summary JSON, owner attribution, and committed_at
  5. Call `parser.commit(conn, parse_result)` to write the parser's
     target table (e.g. `payroll_snapshots`)

Centralizing the logic ensures the connector path emits identical
`document_drops` and target-table rows as the manual drop, including
the file-id provenance and silent-failure guards.

Public API:

  stage_document(filename, content) -> StagedDocument
  commit_staged_document(filename, content, file_id=..., document_drop_id=...)
      -> CommitOutcome
  ingest_document(filename, content) -> CommitOutcome
      Convenience: stage + commit in one call. Use from connectors.

Errors:

  RecognitionError    — no parser claimed this document
  ParseBlockedError   — parser ran but tripped a silent-failure guard
                        (`can_commit=False`); raised with the blocking
                        warning so callers can surface it.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dal.database import get_db
from dal.document_drop import get_parser
from dal.parsers.base import DocumentParser, ParseResult

log = logging.getLogger("sentry.backend.document_ingest")

# Staging area used by both the upload router and the connector path.
# Connector ingests use the same directory so a connector-driven file
# can be re-parsed by a manual replay through /api/documents/commit if
# the user ever wants to inspect or correct it.
STAGING_DIR = Path(__file__).resolve().parent.parent / "raw_exports" / "document_drop"
STAGING_DIR.mkdir(parents=True, exist_ok=True)


class DocumentIngestError(Exception):
    """Base class for ingest failures."""


class RecognitionError(DocumentIngestError):
    """No parser matched this document."""


class ParseBlockedError(DocumentIngestError):
    """Parser ran but a silent-failure guard blocked the commit."""

    def __init__(self, message: str, *, parser_type: str, warnings: list[str]):
        super().__init__(message)
        self.parser_type = parser_type
        self.warnings = warnings


@dataclass
class StagedDocument:
    """Outcome of `stage_document` — the upload preview half of the flow."""

    file_id: str
    document_drop_id: int
    filename: str
    parser_type: str
    preview: dict
    warnings: list[str]
    can_commit: bool
    staged_path: Path


@dataclass
class CommitOutcome:
    """Outcome of `commit_staged_document` / `ingest_document`."""

    parser_type: str
    document_drop_id: int
    file_id: str
    summary: dict
    pipeline: dict = field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────


# Parser types whose commit writes business data and therefore need the
# post-commit pipeline (categorization → derived metrics → alerts → goal
# sync → notifications). Tax-doc parsers (1099/1098) intentionally
# excluded — their commit is a summary_json-only no-op.
#
# Mirrors the institution_map in backend/routers/documents.py; kept in
# lockstep when adding new parser types. The router imports this map so
# both paths stay in sync.
PARSER_INSTITUTION_MAP: dict[str, str] = {
    "tsp_statement": "tsp",
    "mypay_ras": "mypay",
    "eventlink": "eventlink",
    "acorns_statement": "acorns",
    "acorns_confirmation": "acorns",
}


def _stage_bytes(content: bytes, filename: str) -> tuple[str, Path]:
    """Write content to STAGING_DIR under a fresh UUID. Returns (file_id, path)."""
    file_id = str(uuid.uuid4())
    ext = Path(filename).suffix or ".bin"
    staged_path = STAGING_DIR / f"{file_id}{ext}"
    staged_path.write_bytes(content)
    return file_id, staged_path


def _resolve_owner(parser: DocumentParser, conn: sqlite3.Connection,
                   result: ParseResult) -> Optional[str]:
    try:
        return parser.resolve_owner_id(conn, result)
    except Exception as e:
        log.warning("resolve_owner_id failed for %s: %s", parser.parser_type, e)
        return None


# ── Public API ───────────────────────────────────────────────────────────────


def stage_document(filename: str, content: bytes) -> StagedDocument:
    """Recognize, parse, and stage a document for later commit.

    Mirrors the upload half of the existing /api/documents/upload flow.
    Inserts an initial `document_drops` row with `committed_at=NULL` and
    `summary_json={"file_id": ..., "staged": true}`.

    `can_commit` reflects parser silent-failure guards. Caller decides
    whether to follow up with `commit_staged_document`.
    """
    from dal.document_drop import parse_document

    result = parse_document(filename, content)

    file_id, staged_path = _stage_bytes(content, filename)

    parser = get_parser(filename, content) if result.parser_type != "unknown" else None
    with get_db() as conn:
        owner_id = _resolve_owner(parser, conn, result) if parser is not None else None
        cursor = conn.execute(
            """
            INSERT INTO document_drops
                (file_name, parser_type, file_size, summary_json, owner_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                filename,
                result.parser_type,
                len(content),
                json.dumps({"file_id": file_id, "staged": True}),
                owner_id,
            ),
        )
        document_drop_id = cursor.lastrowid
        conn.commit()

    can_commit = result.parser_type != "unknown" and result.can_commit

    return StagedDocument(
        file_id=file_id,
        document_drop_id=document_drop_id,
        filename=filename,
        parser_type=result.parser_type,
        preview=result.preview,
        warnings=list(result.warnings),
        can_commit=can_commit,
        staged_path=staged_path,
    )


def commit_staged_document(
    filename: str,
    content: bytes,
    *,
    file_id: str,
    document_drop_id: int | None = None,
    run_pipeline: bool = True,
) -> CommitOutcome:
    """Commit a previously-staged document to the database.

    Re-parses (deterministic) so a stale stage can't slip past silent-
    failure guards. Updates `document_drops` with `committed_at`, final
    `summary_json`, and re-stamped `owner_id`.

    When `run_pipeline=True` and the parser_type is in
    `PARSER_INSTITUTION_MAP`, runs the post-commit pipeline. The router
    handles its own pipeline dispatch; the connector path uses
    `run_pipeline=False` so the lifecycle owner-driver can decide when
    to fire it.

    Raises `RecognitionError` if no parser matches, `ParseBlockedError`
    if a silent-failure guard tripped.
    """
    parser = get_parser(filename, content)
    if parser is None:
        raise RecognitionError(f"No parser recognized {filename!r}")

    parse_result = parser.parse(content)
    if parse_result.parser_type == "unknown":
        raise RecognitionError(
            f"Parser claimed {filename!r} but produced parser_type='unknown'"
        )

    if not parse_result.can_commit:
        blocking = [w for w in parse_result.warnings if w.startswith("⚠ BLOCK:")]
        detail = (
            blocking[0]
            if blocking
            else "Parser blocked commit (silent-failure guard)."
        )
        raise ParseBlockedError(
            detail,
            parser_type=parse_result.parser_type,
            warnings=list(parse_result.warnings),
        )

    with get_db() as conn:
        summary = parser.commit(conn, parse_result)
        new_summary_json = json.dumps({**summary, "file_id": file_id})
        owner_id = _resolve_owner(parser, conn, parse_result)
        if document_drop_id is not None:
            conn.execute(
                """
                UPDATE document_drops
                SET committed_at = datetime('now'),
                    summary_json = ?,
                    owner_id = ?
                WHERE id = ?
                """,
                (new_summary_json, owner_id, document_drop_id),
            )
        else:
            conn.execute(
                """
                UPDATE document_drops
                SET committed_at = datetime('now'),
                    summary_json = ?,
                    owner_id = ?
                WHERE summary_json LIKE ?
                """,
                (new_summary_json, owner_id, f'%"file_id": "{file_id}"%'),
            )
        conn.commit()

    pipeline_summary: dict = {}
    institution = PARSER_INSTITUTION_MAP.get(parse_result.parser_type)
    if run_pipeline and institution:
        try:
            from backend.result_writer import run_post_commit_pipeline
            pipeline_summary = run_post_commit_pipeline(institution)
        except Exception as e:
            log.warning("Post-commit pipeline failed (non-fatal): %s", e)

    return CommitOutcome(
        parser_type=parse_result.parser_type,
        document_drop_id=document_drop_id or -1,
        file_id=file_id,
        summary=summary,
        pipeline=pipeline_summary,
    )


def ingest_document(
    filename: str,
    content: bytes,
    *,
    run_pipeline: bool = True,
) -> CommitOutcome:
    """Stage + commit in one call, the connector-friendly entry point.

    Differences from the two-step flow:
      * Skips the upload preview — connectors download trusted PDFs
        from authenticated sessions, so the manual confirmation step
        isn't applicable.
      * Returns a single CommitOutcome covering both halves.
      * Still writes the same `document_drops` provenance row a manual
        upload would, including `summary_json={file_id,staged:true}`
        before the commit step UPDATEs it.

    Raises `RecognitionError` or `ParseBlockedError` on failure.
    """
    staged = stage_document(filename, content)
    if staged.parser_type == "unknown":
        # Caller cleanup: we already inserted a document_drops row with
        # parser_type='unknown'. Leave it for forensic visibility — the
        # manual flow does the same.
        try:
            staged.staged_path.unlink()
        except Exception:
            pass
        raise RecognitionError(
            f"No parser recognized {filename!r} during connector ingest"
        )
    if not staged.can_commit:
        # Same — staged row remains for visibility. Surface the blocking
        # warning so the connector caller can log/return it.
        try:
            staged.staged_path.unlink()
        except Exception:
            pass
        blocking = [w for w in staged.warnings if w.startswith("⚠ BLOCK:")]
        detail = (
            blocking[0]
            if blocking
            else "Parser blocked commit (silent-failure guard)."
        )
        raise ParseBlockedError(
            detail,
            parser_type=staged.parser_type,
            warnings=staged.warnings,
        )

    outcome = commit_staged_document(
        staged.filename,
        content,
        file_id=staged.file_id,
        document_drop_id=staged.document_drop_id,
        run_pipeline=run_pipeline,
    )

    # Connector path: clean up the staged copy now that the commit
    # finished — the canonical store is already in
    # raw_exports/<institution>/ owned by the connector. The router
    # path keeps its own staged copy because /commit runs in a
    # separate request.
    try:
        staged.staged_path.unlink()
    except Exception:
        pass

    return outcome
