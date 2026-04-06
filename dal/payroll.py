"""
dal/payroll.py — Payroll snapshot aggregation (myPay RAS data).

Single point of analytical access to the `payroll_snapshots` table populated
by `dal/parsers/mypay_ras.py`.  Provides gross-pay, withholding, and effective
tax-rate aggregates for the monthly review and yearly wrap-up consumers.

Owner-scoping limitation
------------------------
The `payroll_snapshots` table (v15 migration) does NOT have an `owner_id` or
`account_id` column.  In the current household, the myPay RAS is the
single-source-of-truth for the primary owner's military pension only — partner
payroll, if it ever lands, would require a schema migration to disambiguate.
Until that migration exists, every read here is implicitly scoped to the
primary owner.  When callers pass a partner `view`, they should treat a
`data_quality == "missing"` result as "no payroll data for this view" and hide
pre-tax UI affordances.

Do NOT add an owner column to `payroll_snapshots` here — that requires a
migration this module is not authorized to make.
"""

import logging
import sqlite3
from typing import Optional

log = logging.getLogger("sentry.dal.payroll")


# ── Internal helpers ─────────────────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a payroll_snapshots row into a plain dict with safe defaults."""
    return {
        "id": row["id"],
        "pay_period": row["pay_period"],
        "source": row["source"],
        "gross_pay": float(row["gross_pay"] or 0.0),
        "federal_tax": float(row["federal_tax"] or 0.0),
        "state_tax": float(row["state_tax"] or 0.0),
        "sbp_premium": float(row["sbp_premium"] or 0.0),
        "health_insurance": float(row["health_insurance"] or 0.0),
        "dental_vision": float(row["dental_vision"] or 0.0),
        "other_deductions": float(row["other_deductions"] or 0.0),
        "net_pay": float(row["net_pay"] or 0.0),
    }


def _total_deductions(row_dict: dict) -> float:
    """Sum SBP + health + dental + other deductions for a row dict."""
    return (
        row_dict["sbp_premium"]
        + row_dict["health_insurance"]
        + row_dict["dental_vision"]
        + row_dict["other_deductions"]
    )


# ── Public API ───────────────────────────────────────────────────────────────

def get_payroll_snapshots(
    conn: sqlite3.Connection,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> list[dict]:
    """Return payroll_snapshots rows ordered by pay_period ascending.

    Parameters
    ----------
    start, end : str | None
        Inclusive YYYY-MM bounds.  When both are None, returns all rows.
    """
    sql = (
        "SELECT id, pay_period, source, gross_pay, federal_tax, state_tax, "
        "sbp_premium, health_insurance, dental_vision, other_deductions, net_pay "
        "FROM payroll_snapshots"
    )
    clauses: list[str] = []
    params: list[str] = []
    if start is not None:
        clauses.append("pay_period >= ?")
        params.append(start)
    if end is not None:
        clauses.append("pay_period <= ?")
        params.append(end)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY pay_period ASC"

    cur = conn.execute(sql, params)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_gross_income_for_month(
    conn: sqlite3.Connection,
    year: int,
    month: int,
) -> Optional[dict]:
    """Return one month's payroll snapshot as a dict, or None if missing.

    If multiple sources exist for the same month (unlikely — UNIQUE
    constraint with ON CONFLICT REPLACE prevents it), the most recent
    one wins.
    """
    pay_period = f"{year:04d}-{month:02d}"
    cur = conn.execute(
        "SELECT id, pay_period, source, gross_pay, federal_tax, state_tax, "
        "sbp_premium, health_insurance, dental_vision, other_deductions, net_pay "
        "FROM payroll_snapshots "
        "WHERE pay_period = ? "
        "ORDER BY id DESC LIMIT 1",
        (pay_period,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    out = _row_to_dict(row)
    out["deductions_total"] = _total_deductions(out)
    return out


def get_gross_income_for_year(
    conn: sqlite3.Connection,
    year: int,
) -> dict:
    """Sum payroll fields across a calendar year.

    Returns a dict shaped like::

        {
            "year": 2025,
            "gross_pay": 96000.0,
            "federal_tax": 9800.0,
            "state_tax": 2400.0,
            "sbp_premium": 600.0,
            "health_insurance": 1200.0,
            "dental_vision": 360.0,
            "other_deductions": 240.0,
            "deductions_total": 2400.0,
            "net_pay": 81600.0,
            "months_covered": 12,
            "data_quality": "complete" | "partial" | "missing",
        }

    `data_quality` rules:
        complete  → 12 distinct months present
        partial   → 1..11 months present
        missing   → 0 months
    """
    start = f"{year:04d}-01"
    end = f"{year:04d}-12"
    rows = get_payroll_snapshots(conn, start=start, end=end)

    months_seen: set[str] = set()
    totals = {
        "gross_pay": 0.0,
        "federal_tax": 0.0,
        "state_tax": 0.0,
        "sbp_premium": 0.0,
        "health_insurance": 0.0,
        "dental_vision": 0.0,
        "other_deductions": 0.0,
        "net_pay": 0.0,
    }
    for r in rows:
        months_seen.add(r["pay_period"])
        for key in totals:
            totals[key] += r[key]

    months_covered = len(months_seen)
    if months_covered == 0:
        data_quality = "missing"
    elif months_covered == 12:
        data_quality = "complete"
    else:
        data_quality = "partial"

    return {
        "year": year,
        **totals,
        "deductions_total": (
            totals["sbp_premium"]
            + totals["health_insurance"]
            + totals["dental_vision"]
            + totals["other_deductions"]
        ),
        "months_covered": months_covered,
        "data_quality": data_quality,
    }


def get_effective_tax_rate(
    conn: sqlite3.Connection,
    year: int,
) -> dict:
    """Compute the effective income-tax rate for a calendar year.

    Effective rate = (federal_tax + state_tax) / gross_pay × 100.

    Returns a dict shaped like::

        {
            "year": 2025,
            "gross_income": 96000.0,
            "federal_tax": 9800.0,
            "state_tax": 2400.0,
            "total_tax": 12200.0,
            "effective_rate_pct": 12.7,
            "months_covered": 12,
            "data_quality": "complete" | "partial" | "missing",
        }

    When `data_quality == "missing"`, all numeric fields are 0.0 and the
    effective rate is 0.0.  Callers should branch on `data_quality` rather
    than treating 0% as a meaningful value.
    """
    summary = get_gross_income_for_year(conn, year)
    gross = summary["gross_pay"]
    federal = summary["federal_tax"]
    state = summary["state_tax"]
    total_tax = federal + state

    if gross > 0:
        effective_rate = round(total_tax / gross * 100, 1)
    else:
        effective_rate = 0.0

    return {
        "year": year,
        "gross_income": gross,
        "federal_tax": federal,
        "state_tax": state,
        "total_tax": total_tax,
        "effective_rate_pct": effective_rate,
        "months_covered": summary["months_covered"],
        "data_quality": summary["data_quality"],
    }
