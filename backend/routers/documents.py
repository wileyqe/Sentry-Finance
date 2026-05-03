"""
backend/routers/documents.py — Document drop endpoints.

Flow:
  POST /api/documents/upload  → auto-recognize, parse, return preview
  POST /api/documents/commit  → commit parsed data to DB
  GET  /api/documents/history → list past document drops
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel

from dal.database import get_db
from dal.documents import get_pending_nudges as _dal_pending_nudges
from backend.document_ingest import (
    PARSER_INSTITUTION_MAP,
    ParseBlockedError,
    RecognitionError,
    STAGING_DIR as _STAGING_DIR,
    commit_staged_document,
    stage_document,
)
from backend.result_writer import run_post_commit_pipeline

log = logging.getLogger("sentry.backend.api.documents")
router = APIRouter(tags=["documents"])

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
    staged = stage_document(filename, content)

    return {
        "file_id": staged.file_id,
        "document_drop_id": staged.document_drop_id,
        "filename": staged.filename,
        "parser_type": staged.parser_type,
        "preview": staged.preview,
        "warnings": staged.warnings,
        "can_commit": staged.can_commit,
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
    matches = list(_STAGING_DIR.glob(f"{body.file_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Staged file not found. Re-upload required.")

    staged_path = matches[0]
    content = staged_path.read_bytes()
    filename = staged_path.name

    # Router path runs the post-commit pipeline itself below so it can
    # surface a structured `pipeline_summary` separate from the parser
    # commit summary; pass run_pipeline=False to avoid double dispatch.
    try:
        outcome = commit_staged_document(
            filename,
            content,
            file_id=body.file_id,
            document_drop_id=body.document_drop_id,
            run_pipeline=False,
        )
    except RecognitionError as e:
        # Mirror legacy 422s: "Document type not recognized" /
        # "Parser failed to extract data".
        raise HTTPException(status_code=422, detail=str(e))
    except ParseBlockedError as e:
        # Silent-failure guard — backend rejection even if a stale
        # frontend bypassed the UI Commit-disabled state.
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        log.error("Document commit failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Commit failed: {e}")

    # Determine institution from parser_type for post-commit pipeline.
    # Tax parsers (1099/1098) are intentionally excluded — their commit
    # is a no-op write to summary_json only, nothing downstream to
    # recompute. Mapping kept in `backend.document_ingest` so the
    # connector path stays in lockstep.
    institution = PARSER_INSTITUTION_MAP.get(outcome.parser_type)
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
        "parser_type": outcome.parser_type,
        "summary": outcome.summary,
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
