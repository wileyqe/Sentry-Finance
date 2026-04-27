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
from dal.documents import get_pending_nudges as _dal_pending_nudges
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

    # Record the upload attempt in document_drops. Capture lastrowid so
    # the upload response can return the row's PK, which /commit uses
    # to update the staged row directly (AI-040 fix; see CommitRequest
    # below).
    #
    # owner_id is best-effort at upload time (the parse happens here so
    # we can call resolve_owner_id), but the canonical stamp happens at
    # /commit time too — the staged owner_id may be NULL for "unknown"
    # parser_type rows that never get re-parsed.
    parser = get_parser(filename, content) if result.parser_type != "unknown" else None
    with get_db() as conn:
        owner_id = parser.resolve_owner_id(conn, result) if parser is not None else None
        cursor = conn.execute(
            """
            INSERT INTO document_drops
                (file_name, parser_type, file_size, summary_json, owner_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (filename, result.parser_type, len(content),
             json.dumps({"file_id": file_id, "staged": True}),
             owner_id),
        )
        document_drop_id = cursor.lastrowid
        conn.commit()

    # can_commit is False when either (a) no parser matched or (b) the
    # parser tripped a silent-failure guard (layout drift, missing core
    # fields). See ParseResult.can_commit + each parser's parse()
    # blocking warnings.
    can_commit = result.parser_type != "unknown" and result.can_commit

    return {
        "file_id": file_id,
        "document_drop_id": document_drop_id,
        "filename": filename,
        "parser_type": result.parser_type,
        "preview": result.preview,
        "warnings": result.warnings,
        "can_commit": can_commit,
    }


class CommitRequest(BaseModel):
    file_id: str
    # AI-040 fix: prefer the row's PK for the post-commit UPDATE. The
    # upload response now includes `document_drop_id`; older clients
    # that don't pass it fall back to the legacy substring lookup.
    document_drop_id: int | None = None


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

    # Enforce silent-failure guards on the backend — even if a stale
    # frontend bypasses the UI "Commit disabled" state, a blocked
    # ParseResult must not reach the database.
    if not parse_result.can_commit:
        blocking = [w for w in parse_result.warnings if w.startswith("⚠ BLOCK:")]
        detail = blocking[0] if blocking else "Parser blocked commit (silent-failure guard)."
        raise HTTPException(status_code=409, detail=detail)

    # Commit to DB
    with get_db() as conn:
        try:
            summary = parser.commit(conn, parse_result)
            new_summary_json = json.dumps({**summary, "file_id": body.file_id})
            owner_id = parser.resolve_owner_id(conn, parse_result)
            if body.document_drop_id is not None:
                # AI-040 fix: PK lookup is exact and immune to JSON-shape
                # drift. New clients always send this; legacy clients
                # fall back to the substring path below.
                conn.execute(
                    """
                    UPDATE document_drops
                    SET committed_at = datetime('now'),
                        summary_json = ?,
                        owner_id = ?
                    WHERE id = ?
                    """,
                    (new_summary_json, owner_id, body.document_drop_id),
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
                    (new_summary_json, owner_id,
                     f'%"file_id": "{body.file_id}"%'),
                )
            conn.commit()
        except Exception as e:
            log.error("Document commit failed: %s", e)
            raise HTTPException(status_code=500, detail=f"Commit failed: {e}")

    # Determine institution from parser_type for post-commit pipeline.
    # Tax parsers (1099/1098) are intentionally None — their commit is a
    # no-op write to summary_json only, nothing downstream to recompute.
    #
    # AI-038 fix (2026-04-26): the eventlink, acorns_statement, and
    # acorns_confirmation parsers WRITE business data (transactions,
    # positions_ledger, accounts) but had no entry in this map, so the
    # categorization, reconciliation, recurring detection, alerts, goal
    # sync, and notification steps were ALL skipped after these
    # uploads. Map them to a synthetic institution id so the pipeline
    # fires; the institution id is informational (used only by
    # `recompute_for_institution` to scope per-account metric writes,
    # which is harmless to over-trigger).
    institution_map = {
        "tsp_statement": "tsp",
        "mypay_ras": "mypay",     # M3: trigger payroll recompute post-ingest
        "eventlink": "eventlink",
        "acorns_statement": "acorns",
        "acorns_confirmation": "acorns",
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
    with get_db() as conn:
        nudges = _dal_pending_nudges(conn)
    return {"nudges": nudges}


@router.get("/api/documents/tax-summary/{year}")
def tax_summary(year: int):
    """Return all parsed tax documents for a given year.

    Aggregates key figures across all 1099s and 1098s.
    """
    with get_db() as conn:
        docs = conn.execute(
            """SELECT parser_type, summary_json
               FROM document_drops
               WHERE committed_at IS NOT NULL
                 AND json_extract(summary_json, '$.tax_year') = ?
               ORDER BY parser_type""",
            (str(year),),
        ).fetchall()

    summary = {
        "year": year,
        "documents": [],
        "totals": {
            "gross_income": 0,
            "investment_income": 0,
            "interest_earned": 0,
            "mortgage_interest_paid": 0,
            "federal_tax_withheld": 0,
            "state_tax_withheld": 0,
            "capital_gains": 0,
            "property_taxes": 0,
        },
    }

    for doc in docs:
        fields = json.loads(doc["summary_json"] or "{}")
        summary["documents"].append({
            "type": doc["parser_type"],
            "fields": fields,
        })
        
        # Aggregate totals based on parser type
        pt = doc["parser_type"]
        if pt == "dfas_1099r":
            summary["totals"]["gross_income"] += fields.get("gross_distribution", 0)
            summary["totals"]["federal_tax_withheld"] += fields.get("federal_tax_withheld", 0)
            summary["totals"]["state_tax_withheld"] += fields.get("state_tax_withheld", 0)
        elif pt in ["fidelity_1099", "acorns_1099"]:
            summary["totals"]["investment_income"] += fields.get("ordinary_dividends", 0)
            summary["totals"]["interest_earned"] += fields.get("interest_income", 0)
            
            # Determine capital gains
            if "total_gain_loss" in fields:
                summary["totals"]["capital_gains"] += fields["total_gain_loss"]
            elif "capital_gain_distributions" in fields:
                summary["totals"]["capital_gains"] += fields["capital_gain_distributions"]
            elif "total_proceeds" in fields and "total_cost_basis" in fields:
                summary["totals"]["capital_gains"] += fields["total_proceeds"] - fields["total_cost_basis"]

        elif pt == "affirm_1099int":
            summary["totals"]["interest_earned"] += fields.get("interest_income", 0)
        elif pt == "nfcu_1098":
            summary["totals"]["mortgage_interest_paid"] += fields.get("mortgage_interest_received", 0)
            summary["totals"]["property_taxes"] = summary["totals"].get("property_taxes", 0) + fields.get("property_taxes", 0)

    # Round totals
    for k in summary["totals"]:
        summary["totals"][k] = round(summary["totals"][k], 2)

    return summary
