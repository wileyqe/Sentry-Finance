"""
dal/bills.py — Bill tracking and reminders.

Surfaces upcoming bills from the recurring_transactions table.
Uses next_expected dates to compute what's due soon and what's overdue.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("sentry.dal.bills")


def get_upcoming_bills(
    conn: sqlite3.Connection,
    days: int = 30,
    account_id: Optional[str] = None,
) -> list[dict]:
    """Get bills due within the next N days.

    Returns a list of dicts sorted by next_expected date:
      {id, merchant, category, frequency, expected_amount, next_expected,
       days_until, status (upcoming/due_soon/overdue), account_id}
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = (now + timedelta(days=days)).strftime("%Y-%m-%d")

    clauses = [
        "status = 'active'",
        "amount_stable = 1",
        "next_expected IS NOT NULL",
        f"next_expected <= '{cutoff}'",
    ]
    params: list = []

    if account_id:
        clauses.append("account_id = ?")
        params.append(account_id)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT * FROM recurring_transactions WHERE {where} "
        f"ORDER BY next_expected",
        params,
    ).fetchall()

    results = []
    for r in rows:
        try:
            next_dt = datetime.strptime(r["next_expected"], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        days_until = (next_dt - now).days

        if days_until < 0:
            bill_status = "overdue"
        elif days_until <= 3:
            bill_status = "due_soon"
        else:
            bill_status = "upcoming"

        results.append({
            "id": r["id"],
            "merchant": r["merchant"],
            "category": r["category"],
            "frequency": r["frequency"],
            "expected_amount": r["expected_amount"],
            "last_amount": r["last_amount"],
            "next_expected": r["next_expected"],
            "days_until": days_until,
            "status": bill_status,
            "account_id": r["account_id"],
        })

    return results


def get_overdue_bills(
    conn: sqlite3.Connection,
    account_id: Optional[str] = None,
) -> list[dict]:
    """Get all overdue bills (next_expected has passed)."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # date-only, tz irrelevant

    clauses = [
        "status = 'active'",
        "amount_stable = 1",
        "next_expected IS NOT NULL",
        "next_expected < ?",
    ]
    params: list = [now_iso]

    if account_id:
        clauses.append("account_id = ?")
        params.append(account_id)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT * FROM recurring_transactions WHERE {where} "
        f"ORDER BY next_expected",
        params,
    ).fetchall()

    results = []
    seen = set()
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])

        try:
            next_dt = datetime.strptime(r["next_expected"], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        days_overdue = (datetime.now(timezone.utc).replace(tzinfo=None) - next_dt).days

        results.append({
            "id": r["id"],
            "merchant": r["merchant"],
            "category": r["category"],
            "frequency": r["frequency"],
            "expected_amount": r["expected_amount"],
            "next_expected": r["next_expected"],
            "days_overdue": days_overdue,
            "account_id": r["account_id"],
        })

    return results


def get_bills_summary(
    conn: sqlite3.Connection,
    days: int = 30,
    account_id: Optional[str] = None,
) -> dict:
    """Summary of upcoming bills for the dashboard.

    Returns:
      {upcoming_count, due_soon_count, overdue_count,
       total_upcoming_amount, next_bill}
    """
    bills = get_upcoming_bills(conn, days=days, account_id=account_id)

    upcoming = [b for b in bills if b["status"] == "upcoming"]
    due_soon = [b for b in bills if b["status"] == "due_soon"]
    overdue = [b for b in bills if b["status"] == "overdue"]

    total_amount = sum(
        (b["expected_amount"] or 0)
        for b in bills if b["expected_amount"]
    )

    # Next bill due
    non_overdue = [b for b in bills if b["days_until"] >= 0]
    next_bill = non_overdue[0] if non_overdue else None

    return {
        "upcoming_count": len(upcoming),
        "due_soon_count": len(due_soon),
        "overdue_count": len(overdue),
        "total_upcoming_amount": round(total_amount, 2),
        "next_bill": next_bill,
    }
