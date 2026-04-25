"""
dal/documents.py — Document-drop query helpers.

Extracted from backend/routers/documents.py so the pending-nudges
logic can be reused by the notification producer without inline SQL
outside the DAL layer.
"""

import sqlite3
from datetime import date
from typing import Optional


def get_pending_nudges(
    conn: sqlite3.Connection,
    as_of: Optional[date] = None,
) -> list[dict]:
    """Return Tier-3 institutions overdue for a document drop this month.

    'Overdue' = the institution has no committed document this calendar month
    and today is on or after the 5th of the month.

    Returns a list of dicts with keys: institution, display_name, message.
    Returns an empty list before the 5th, or when all institutions are current.
    """
    today = as_of or date.today()
    if today.day < 5:
        return []

    current_month = today.strftime("%Y-%m")
    month_start = current_month + "-01"

    tsp_row = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM document_drops
        WHERE parser_type = 'tsp_statement'
          AND committed_at IS NOT NULL
          AND committed_at >= ?
        """,
        (month_start,),
    ).fetchone()

    mypay_row = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM document_drops
        WHERE parser_type = 'mypay_ras'
          AND committed_at IS NOT NULL
          AND committed_at >= ?
        """,
        (month_start,),
    ).fetchone()

    nudges = []
    if not tsp_row or tsp_row["cnt"] == 0:
        nudges.append({
            "institution": "tsp",
            "display_name": "Thrift Savings Plan",
            "message": "TSP statement not received this month. Drop your PDF to update.",
        })
    if not mypay_row or mypay_row["cnt"] == 0:
        nudges.append({
            "institution": "mypay",
            "display_name": "myPay (DFAS)",
            "message": "Monthly pension statement not received. Drop your RAS PDF to update.",
        })
    return nudges
