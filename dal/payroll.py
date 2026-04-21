"""
dal/payroll.py — Payroll snapshot aggregation (myPay RAS data).

Single point of analytical access to the `payroll_snapshots` table populated
by `dal/parsers/mypay_ras.py`.  Provides gross-pay, withholding, and effective
tax-rate aggregates for the monthly review and yearly wrap-up consumers.

Owner scoping
-------------
As of migration v22 the `payroll_snapshots` table has an `owner_id` column.
Every public function here accepts an optional ``owner_id`` filter; when set,
the query restricts to that owner's snapshots. When ``owner_id`` is None the
query returns all rows (the household / "ours" view).

The myPay parser writes new rows attributed to the configured primary owner.
Multi-owner ingestion would store rows under each owner's id; this module
fans them out per the caller's scope.
"""

import logging
import sqlite3
from typing import Optional

log = logging.getLogger("sentry.dal.payroll")


# ── Withholding-field → Sankey-bucket map (Phase 14 Phase A) ─────────────────
#
# Phase A routes every withholding to the CONSUMED bucket — including
# `other_deductions`, which often carries TSP / 401k contributions in the
# real world. Phase B introduces the income-source registry and reroutes
# retirement contributions to STORED_ILLIQUID via match_rule_json.
_WITHHOLDING_FIELDS: tuple[tuple[str, str, str], ...] = (
    # (snapshot_column,    flow_kind,         phase_a_bucket)
    ("federal_tax",        "federal_tax",     "CONSUMED"),
    ("state_tax",          "state_tax",       "CONSUMED"),
    ("sbp_premium",        "sbp_premium",     "CONSUMED"),
    ("health_insurance",   "health",          "CONSUMED"),
    ("dental_vision",      "dental_vision",   "CONSUMED"),
    ("other_deductions",   "other",           "CONSUMED"),
)


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
    owner_id: Optional[str] = None,
) -> list[dict]:
    """Return payroll_snapshots rows ordered by pay_period ascending.

    Parameters
    ----------
    start, end : str | None
        Inclusive YYYY-MM bounds.  When both are None, returns all rows.
    owner_id : str | None
        When set, restrict to rows attributed to that owner. None returns
        all rows (household / "ours" view).
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
    if owner_id is not None:
        clauses.append("LOWER(owner_id) = LOWER(?)")
        params.append(owner_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY pay_period ASC"

    cur = conn.execute(sql, params)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_gross_income_for_month(
    conn: sqlite3.Connection,
    year: int,
    month: int,
    owner_id: Optional[str] = None,
) -> Optional[dict]:
    """Return one month's payroll snapshot as a dict, or None if missing.

    If multiple sources exist for the same month (unlikely — UNIQUE
    constraint with ON CONFLICT REPLACE prevents it), the most recent
    one wins.

    When ``owner_id`` is set, restricts to that owner's snapshots.
    """
    pay_period = f"{year:04d}-{month:02d}"
    sql = (
        "SELECT id, pay_period, source, gross_pay, federal_tax, state_tax, "
        "sbp_premium, health_insurance, dental_vision, other_deductions, net_pay "
        "FROM payroll_snapshots "
        "WHERE pay_period = ?"
    )
    params: list = [pay_period]
    if owner_id is not None:
        sql += " AND LOWER(owner_id) = LOWER(?)"
        params.append(owner_id)
    sql += " ORDER BY id DESC LIMIT 1"

    cur = conn.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    out = _row_to_dict(row)
    out["deductions_total"] = _total_deductions(out)
    return out


def get_gross_income_for_year(
    conn: sqlite3.Connection,
    year: int,
    owner_id: Optional[str] = None,
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
    rows = get_payroll_snapshots(conn, start=start, end=end, owner_id=owner_id)

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
    owner_id: Optional[str] = None,
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
    summary = get_gross_income_for_year(conn, year, owner_id=owner_id)
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


# ── Phase 14 Phase A: Sankey flow contribution ───────────────────────────────


def _to_cents(dollars: float) -> int:
    """Round dollars to the nearest cent and return as int."""
    return int(round(float(dollars or 0.0) * 100))


def get_flow_contribution(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    owner_id: Optional[str] = None,
) -> dict:
    """
    Roll up payroll_snapshots into Sankey flow contributions for a window.

    The window is given as ISO date or YYYY-MM strings. Both bounds are
    inclusive and operate on the snapshot's `pay_period` (YYYY-MM bucket).

    Returns
    -------
    dict
        {
            "payroll_rows": [
                {
                    "snapshot_id": int,
                    "owner_id": str | None,
                    "source_label": str,
                    "pay_period": "YYYY-MM",
                    "gross_cents": int,
                    "net_cents": int,
                    "withholdings": [
                        {"kind": "federal_tax",    "cents": int, "bucket": "CONSUMED"},
                        {"kind": "state_tax",      "cents": int, "bucket": "CONSUMED"},
                        {"kind": "sbp_premium",    "cents": int, "bucket": "CONSUMED"},
                        {"kind": "health",         "cents": int, "bucket": "CONSUMED"},
                        {"kind": "dental_vision",  "cents": int, "bucket": "CONSUMED"},
                        {"kind": "other",          "cents": int, "bucket": "CONSUMED"},
                    ],
                },
                ...
            ],
            "total_gross_cents": int,
            "total_net_cents": int,
        }

    Notes
    -----
    - Zero-valued withholding fields are omitted from each row's
      `withholdings` list — a snapshot with no dental/vision deduction
      will not produce a `dental_vision` entry.
    - All buckets default to ``"CONSUMED"`` in Phase A. Phase B's
      income-source registry will reroute retirement portions of
      `other_deductions` to ``"STORED_ILLIQUID"``.
    - This function does not consult the `transactions` table — it
      reports the gross/withholding picture from `payroll_snapshots`
      alone. See `find_matching_deposit_tx_id` for the dedup helper
      consumed by `dal.reports.get_flow_data`.
    """
    start_em = (start or "")[:7]
    end_em = (end or "")[:7]

    sql = (
        "SELECT id, pay_period, source, owner_id, "
        "gross_pay, federal_tax, state_tax, "
        "sbp_premium, health_insurance, dental_vision, other_deductions, net_pay "
        "FROM payroll_snapshots "
        "WHERE pay_period BETWEEN ? AND ?"
    )
    params: list = [start_em, end_em]
    if owner_id is not None:
        sql += " AND LOWER(owner_id) = LOWER(?)"
        params.append(owner_id)
    sql += " ORDER BY pay_period ASC, id ASC"

    rows = conn.execute(sql, params).fetchall()

    payroll_rows: list[dict] = []
    total_gross_cents = 0
    total_net_cents = 0

    for r in rows:
        gross_cents = _to_cents(r["gross_pay"])
        net_cents = _to_cents(r["net_pay"])
        total_gross_cents += gross_cents
        total_net_cents += net_cents

        withholdings: list[dict] = []
        for col, kind, bucket in _WITHHOLDING_FIELDS:
            cents = _to_cents(r[col])
            if cents <= 0:
                continue
            withholdings.append({"kind": kind, "cents": cents, "bucket": bucket})

        payroll_rows.append({
            "snapshot_id": r["id"],
            "owner_id": r["owner_id"],
            "source_label": r["source"],
            "pay_period": r["pay_period"],
            "gross_cents": gross_cents,
            "net_cents": net_cents,
            "withholdings": withholdings,
        })

    return {
        "payroll_rows": payroll_rows,
        "total_gross_cents": total_gross_cents,
        "total_net_cents": total_net_cents,
    }


def find_matching_deposit_tx_id(
    conn: sqlite3.Connection,
    *,
    source_label: str,
    pay_period: str,
    owner_id: Optional[str] = None,
) -> Optional[str]:
    """
    Find a positive-amount transaction in `pay_period` whose merchant or
    description contains `source_label` as a case-insensitive substring.

    Returns the txn id (string primary key) of the largest-amount such
    transaction, or None.

    The match key is `(owner_id, month, source_label_substring)` — amount
    is *not* part of the match key (deductions drift across pay periods,
    so net deposit will not equal gross). Amount only breaks ties when
    multiple transactions match.

    A ``source_label`` shorter than 3 characters is treated as ambiguous
    and never matches — guards against `_` or `tsp`-style snapshot
    sources accidentally matching every transaction in the period.
    """
    if not source_label or len(source_label.strip()) < 3:
        return None

    pattern = f"%{source_label.strip().lower()}%"

    sql = """
        SELECT t.id
        FROM transactions t
        LEFT JOIN accounts a ON a.id = t.account_id
        WHERE t.status = 'posted'
          AND t.signed_amount > 0
          AND t.transfer_tag IS NULL
          AND substr(COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)), 1, 7) = ?
          AND (LOWER(COALESCE(t.merchant, '')) LIKE ?
               OR LOWER(COALESCE(t.description, '')) LIKE ?)
    """
    params: list = [pay_period, pattern, pattern]
    if owner_id is not None:
        sql += " AND LOWER(COALESCE(a.owner_id, '')) = LOWER(?)"
        params.append(owner_id)
    sql += " ORDER BY t.signed_amount DESC, t.id ASC LIMIT 1"

    row = conn.execute(sql, params).fetchone()
    return row["id"] if row else None
