"""
backend/routers/freshness.py — Data freshness API endpoints.
"""

import logging
from fastapi import APIRouter, Query
from typing import Optional

from dal.database import get_db
from dal.freshness import (
    get_institution_freshness,
    get_net_worth_data_age,
    get_document_drop_status,
)

log = logging.getLogger("sentry.backend.routers.freshness")
router = APIRouter(prefix="/api/freshness", tags=["freshness"])

@router.get("")
@router.get("/")
def get_freshness(owner_id: Optional[str] = Query(None)):
    with get_db() as conn:
        return get_institution_freshness(conn, owner_id=owner_id)

@router.get("/net-worth-age")
def get_net_worth_age(owner_id: Optional[str] = Query(None)):
    with get_db() as conn:
        return get_net_worth_data_age(conn, owner_id=owner_id)

@router.get("/document-status")
def get_doc_status(owner_id: Optional[str] = Query(None)):
    with get_db() as conn:
        return get_document_drop_status(conn, owner_id=owner_id)
