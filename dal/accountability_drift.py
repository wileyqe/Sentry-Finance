"""
dal/accountability_drift.py — Phase 14 Phase D drift detectors.

The accountability scorecard (``dal.reports.get_accountability``) computes
an `unexplained_cents` residual between the net-worth delta and the sum
of Sankey-derived flow terms. This module names the contributors to that
residual so the drilldown modal can surface them, each with a
click-to-fix affordance where one exists.

Each detector is a small function returning ``list[DriftSource]`` — a
dict with the shape::

    {
        "id":              str,    # stable id, e.g. "uncategorized_transactions"
        "label":           str,    # human-readable single line
        "severity":        "warning" | "info",
        "fix_action":      str | None,  # routes frontend to the right page
        "fix_payload":     dict,        # shape depends on fix_action
        "magnitude_cents": int,    # estimated contribution to unexplained
    }

Detectors are intentionally independent of each other and of
``get_accountability``'s identity math — they surface *symptoms*, not
*causes*. A stale portfolio snapshot, for example, contributes to
unexplained via market_value_delta being wrong, but the detector
reports the staleness regardless of how much drift that causes.
Magnitudes are best-effort estimates to aid sorting.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

from dal.owners import build_account_filter

log = logging.getLogger("sentry.dal.accountability_drift")


# ── Thresholds ────────────────────────────────────────────────────────────────

_STALE_PORTFOLIO_DAYS = 2          # 2 calendar days ≈ 2 business days
_STALE_HOME_VALUATION_DAYS = 90    # quarterly refresh target
_CC_BOUNDARY_DAYS = 3              # last-N-days window for boundary detector


# ── Public entry point ────────────────────────────────────────────────────────


def detect_drift_sources(
    conn: sqlite3.Connection,
    *,
    start_date: str,
    end_date: str,
    owner_id: Optional[str] = None,
) -> list[dict]:
    """Run every detector and return the aggregated list sorted by
    magnitude descending, warnings before info within the same magnitude.
    """
    detectors = (
        _detect_uncategorized_transactions,
        _detect_stale_portfolio_snapshot,
        _detect_missing_payroll_snapshot,
        _detect_stale_home_valuation,
        _detect_cc_payment_boundary,
        _detect_vehicle_depreciation_unrecorded,
        _detect_real_estate_interpolated,
        _detect_contractor_tax_ambiguity,
    )
    out: list[dict] = []
    for fn in detectors:
        try:
            out.extend(fn(conn, start_date, end_date, owner_id))
        except sqlite3.OperationalError as exc:
            # Missing tables on older schemas — log and continue so a
            # partial scorecard still renders.
            log.debug("drift detector %s skipped: %s", fn.__name__, exc)

    # Sort: warnings first (0 < 1), then magnitude descending, then id.
    out.sort(key=lambda d: (
        0 if d["severity"] == "warning" else 1,
        -int(d.get("magnitude_cents") or 0),
        d["id"],
    ))
    return out


# ── Detector 1 — uncategorized transactions ───────────────────────────────────


def _detect_uncategorized_transactions(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    owner_id: Optional[str],
) -> list[dict]:
    """Flag transactions in the window with NULL or 'Uncategorized' category.

    These silently short the Sankey because `get_flow_data`'s spending /
    income aggregates filter by category — uncategorized rows simply
    never appear. Magnitude = sum of absolute amounts.
    """
    acct_filter, acct_params = build_account_filter(conn, owner_id, None)
    rows = conn.execute(
        f"""
        SELECT id, posting_date, description, signed_amount
          FROM transactions
         WHERE status = 'posted'
           AND transfer_tag IS NULL
           AND (category IS NULL OR category = 'Uncategorized')
           AND date(posting_date) >= date(?)
           AND date(posting_date) <= date(?)
           {acct_filter}
         ORDER BY ABS(signed_amount) DESC
         LIMIT 50
        """,
        [start_date, end_date] + acct_params,
    ).fetchall()

    if not rows:
        return []

    tx_ids = [r["id"] for r in rows]
    total_dollars = sum(abs(float(r["signed_amount"] or 0)) for r in rows)
    magnitude_cents = int(round(total_dollars * 100))
    count = len(tx_ids)

    label = (
        f"{count} uncategorized transaction"
        f"{'s' if count != 1 else ''}"
    )
    return [{
        "id": "uncategorized_transactions",
        "label": label,
        "severity": "warning",
        "fix_action": "recategorize",
        "fix_payload": {"transaction_ids": tx_ids},
        "magnitude_cents": magnitude_cents,
    }]


# ── Detector 2 — stale portfolio snapshot ─────────────────────────────────────


def _detect_stale_portfolio_snapshot(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    owner_id: Optional[str],
) -> list[dict]:
    """Flag investment accounts whose latest portfolio_snapshots row is
    older than ``_STALE_PORTFOLIO_DAYS`` before ``end_date``.
    """
    acct_filter, acct_params = build_account_filter(
        conn, owner_id, None, column="a.id"
    )
    # For each investment/retirement account, find the latest snapshot
    # timestamp <= end_date. Flag if older than the threshold.
    rows = conn.execute(
        f"""
        SELECT a.id AS account_id,
               a.name AS account_name,
               (SELECT MAX(date(ps.timestamp))
                  FROM portfolio_snapshots ps
                 WHERE ps.account_id = a.id
                   AND date(ps.timestamp) <= date(?)) AS latest_ts
          FROM accounts a
         WHERE a.type IN ('investment','retirement')
           AND a.is_active = 1
           {acct_filter}
        """,
        [end_date] + acct_params,
    ).fetchall()

    out: list[dict] = []
    try:
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return []

    for r in rows:
        if not r["latest_ts"]:
            # Never snapshot'd — treat as "effectively very stale"
            out.append({
                "id": f"stale_portfolio_snapshot::{r['account_id']}",
                "label": (
                    f"Portfolio snapshot missing for "
                    f"{r['account_name'] or r['account_id']}"
                ),
                "severity": "warning",
                "fix_action": "refresh_portfolio",
                "fix_payload": {"account_id": r["account_id"]},
                "magnitude_cents": 0,
            })
            continue
        latest = datetime.strptime(r["latest_ts"], "%Y-%m-%d").date()
        age_days = (end_d - latest).days
        if age_days > _STALE_PORTFOLIO_DAYS:
            out.append({
                "id": f"stale_portfolio_snapshot::{r['account_id']}",
                "label": (
                    f"Portfolio snapshot for "
                    f"{r['account_name'] or r['account_id']} is "
                    f"{age_days} day{'s' if age_days != 1 else ''} "
                    f"older than period end"
                ),
                "severity": "warning",
                "fix_action": "refresh_portfolio",
                "fix_payload": {"account_id": r["account_id"]},
                "magnitude_cents": 0,
            })
    return out


# ── Detector 3 — missing payroll snapshot ─────────────────────────────────────


def _detect_missing_payroll_snapshot(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    owner_id: Optional[str],
) -> list[dict]:
    """Flag months in the window where a paycheck-shaped deposit landed
    but no ``payroll_snapshots`` row exists. Without the RAS we can't
    decompose gross → net and the scorecard's "Dollars in" understates
    pension income by the federal/state/SBP withholdings.

    Heuristic for "paycheck-shaped": credit-direction transaction in a
    canonical payroll / pension category (Pension, Disability, Education
    Benefits) — covers the household's synthetic profile without overfit.
    """
    _PAYROLL_CATEGORIES = (
        "Pension", "Disability", "Education Benefits", "Salary",
        "Wages", "Payroll",
    )
    placeholders = ",".join("?" for _ in _PAYROLL_CATEGORIES)
    acct_filter, acct_params = build_account_filter(conn, owner_id, None)

    # Find months with paycheck-shaped deposits.
    deposit_rows = conn.execute(
        f"""
        SELECT DISTINCT strftime('%Y-%m', posting_date) AS month,
               category
          FROM transactions
         WHERE status = 'posted'
           AND signed_amount > 0
           AND transfer_tag IS NULL
           AND category IN ({placeholders})
           AND date(posting_date) >= date(?)
           AND date(posting_date) <= date(?)
           {acct_filter}
        """,
        list(_PAYROLL_CATEGORIES) + [start_date, end_date] + acct_params,
    ).fetchall()
    if not deposit_rows:
        return []

    # Pull payroll snapshot months that DO exist for this owner.
    try:
        snap_rows = conn.execute(
            """
            SELECT DISTINCT pay_period
              FROM payroll_snapshots
             WHERE (? IS NULL OR LOWER(owner_id) = LOWER(?))
            """,
            (owner_id, owner_id),
        ).fetchall()
        have_months = {r["pay_period"] for r in snap_rows}
    except sqlite3.OperationalError:
        have_months = set()

    out: list[dict] = []
    missing_months: list[tuple[str, str]] = []
    for r in deposit_rows:
        if r["month"] not in have_months:
            missing_months.append((r["month"], r["category"]))

    if not missing_months:
        return []

    # Group into a single entry with a list payload.
    months_str = ", ".join(m for m, _ in missing_months[:3])
    if len(missing_months) > 3:
        months_str += f" (+{len(missing_months) - 3} more)"
    return [{
        "id": "missing_payroll_snapshot",
        "label": (
            f"Paycheck-shaped deposit but no RAS uploaded for "
            f"{months_str}"
        ),
        "severity": "warning",
        "fix_action": "upload_ras",
        "fix_payload": {
            "missing_months": [m for m, _ in missing_months],
        },
        "magnitude_cents": 0,
    }]


# ── Detector 4 — stale home valuation ─────────────────────────────────────────


def _detect_stale_home_valuation(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    owner_id: Optional[str],
) -> list[dict]:
    """Flag real estate with a latest valuation older than the
    quarterly-refresh threshold.
    """
    try:
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return []

    sql = """
        SELECT name, MAX(as_of) AS latest_as_of
          FROM real_estate
         WHERE name NOT LIKE '%[%'
    """
    params: list = []
    if owner_id:
        sql += " AND LOWER(owner_id) = LOWER(?)"
        params.append(owner_id)
    sql += " GROUP BY name"

    out: list[dict] = []
    for r in conn.execute(sql, params).fetchall():
        if not r["latest_as_of"]:
            continue
        try:
            latest = datetime.strptime(
                r["latest_as_of"][:10], "%Y-%m-%d"
            ).date()
        except ValueError:
            continue
        age_days = (end_d - latest).days
        if age_days > _STALE_HOME_VALUATION_DAYS:
            out.append({
                "id": f"stale_home_valuation::{r['name']}",
                "label": (
                    f"Home valuation for "
                    f"{r['name']} is {age_days} days old"
                ),
                "severity": "warning",
                "fix_action": "update_valuation",
                "fix_payload": {"property_name": r["name"]},
                "magnitude_cents": 0,
            })
    return out


# ── Detector 5 — CC payment at period boundary ────────────────────────────────


def _detect_cc_payment_boundary(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    owner_id: Optional[str],
) -> list[dict]:
    """Informational: a credit-card payment in the last ``_CC_BOUNDARY_DAYS``
    of the window pays for spend that probably occurred before ``start``.
    This creates a phantom "STORED_ILLIQUID"-ish bump against a null
    spending term and distorts attributable bucket totals around the
    boundary. Named but not fixable — correcting it requires expanding
    the window.
    """
    try:
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return []
    boundary_start = (
        end_d - timedelta(days=_CC_BOUNDARY_DAYS - 1)
    ).strftime("%Y-%m-%d")

    acct_filter, acct_params = build_account_filter(conn, owner_id, None)

    # Look for credit-card payments (transfers TO a credit_card account)
    # in the last N days of the window.
    rows = conn.execute(
        f"""
        SELECT t.id, t.signed_amount, t.posting_date, a.name AS account_name
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
         WHERE t.status = 'posted'
           AND a.type = 'credit_card'
           AND t.signed_amount > 0
           AND t.transfer_tag IS NOT NULL
           AND date(t.posting_date) >= date(?)
           AND date(t.posting_date) <= date(?)
           {acct_filter.replace('account_id', 't.account_id') if acct_filter else ''}
        """,
        [boundary_start, end_date] + acct_params,
    ).fetchall()
    if not rows:
        return []

    total_c = int(round(
        sum(abs(float(r["signed_amount"] or 0)) for r in rows) * 100
    ))
    count = len(rows)
    return [{
        "id": "cc_payment_boundary",
        "label": (
            f"{count} credit-card payment"
            f"{'s' if count != 1 else ''} in the last "
            f"{_CC_BOUNDARY_DAYS} days of the window"
        ),
        "severity": "info",
        "fix_action": None,
        "fix_payload": {},
        "magnitude_cents": total_c,
    }]


# ── Detector 6 — vehicle depreciation unrecorded ──────────────────────────────


def _detect_vehicle_depreciation_unrecorded(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    owner_id: Optional[str],
) -> list[dict]:
    """Flag vehicles with no valuation row in the window (vehicles
    depreciate on a continuous schedule; no row means no bookkeeping).
    """
    try:
        conn.execute("SELECT 1 FROM vehicle_assets LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return []

    sql = """
        SELECT va.id, va.make, va.model
          FROM vehicle_assets va
         WHERE NOT EXISTS (
                SELECT 1 FROM vehicle_valuations vv
                 WHERE vv.vehicle_id = va.id
                   AND date(vv.valuation_date) >= date(?)
                   AND date(vv.valuation_date) <= date(?)
            )
    """
    params: list = [start_date, end_date]
    if owner_id:
        sql += " AND LOWER(va.owner_id) = LOWER(?)"
        params.append(owner_id)

    out: list[dict] = []
    for r in conn.execute(sql, params).fetchall():
        name = " ".join(
            s for s in (r["make"], r["model"]) if s
        ) or r["id"]
        out.append({
            "id": f"vehicle_depreciation_unrecorded::{r['id']}",
            "label": f"No vehicle valuation recorded in window for {name}",
            "severity": "info",
            "fix_action": "update_vehicle_value",
            "fix_payload": {"vehicle_id": r["id"]},
            "magnitude_cents": 0,
        })
    return out


# ── Detector 7 — real-estate valuation interpolated ───────────────────────────


def _detect_real_estate_interpolated(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    owner_id: Optional[str],
) -> list[dict]:
    """Informational: when the owner has fewer than 2 real-estate
    valuations in or around the window, the intra-window values are
    effectively a single flat line. Named so the user knows the RE-delta
    term has low resolution.
    """
    sql = """
        SELECT name, COUNT(*) AS n
          FROM real_estate
         WHERE name NOT LIKE '%[%'
           AND date(as_of) >= date(?, '-6 months')
           AND date(as_of) <= date(?)
    """
    params: list = [start_date, end_date]
    if owner_id:
        sql += " AND LOWER(owner_id) = LOWER(?)"
        params.append(owner_id)
    sql += " GROUP BY name"

    out: list[dict] = []
    for r in conn.execute(sql, params).fetchall():
        if r["n"] <= 1:
            out.append({
                "id": f"real_estate_interpolated::{r['name']}",
                "label": (
                    f"Real-estate valuation for {r['name']} "
                    f"has ≤1 data point in 6 months"
                ),
                "severity": "info",
                "fix_action": "update_valuation",
                "fix_payload": {"property_name": r["name"]},
                "magnitude_cents": 0,
            })
    return out


# ── Detector 8 — contractor-season tax ambiguity ──────────────────────────────


def _detect_contractor_tax_ambiguity(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    owner_id: Optional[str],
) -> list[dict]:
    """Flag contractor income received in window with no obvious tax-
    reconciliation event. Contractor pay has no source withholding —
    until the year-end 1099 lands and estimated-tax payments are
    modeled, a chunk of this income will be re-allocated from
    STORED_LIQUID to CONSUMED (quarterly taxes). Named so the user
    knows there's a phantom portion.
    """
    try:
        rows = conn.execute(
            """
            SELECT source_label, tax_treatment, match_rule_json
              FROM income_sources
             WHERE tax_treatment = 'contractor_no_withholding'
               AND (? IS NULL OR LOWER(owner_id) = LOWER(?))
               AND is_active = 1
            """,
            (owner_id, owner_id),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    if not rows:
        return []

    # Did any contractor category receive income in window?
    # Use a simple proxy: look for credit-direction transactions matching
    # the Officiating Income / Contract / 1099 category family.
    _CONTRACTOR_CATEGORIES = (
        "Officiating Income", "Contract Income", "1099 Income",
        "Freelance Income",
    )
    ph = ",".join("?" for _ in _CONTRACTOR_CATEGORIES)
    acct_filter, acct_params = build_account_filter(conn, owner_id, None)
    row = conn.execute(
        f"""
        SELECT SUM(signed_amount) AS total_dollars, COUNT(*) AS n
          FROM transactions
         WHERE status = 'posted'
           AND signed_amount > 0
           AND transfer_tag IS NULL
           AND category IN ({ph})
           AND date(posting_date) >= date(?)
           AND date(posting_date) <= date(?)
           {acct_filter}
        """,
        list(_CONTRACTOR_CATEGORIES) + [start_date, end_date] + acct_params,
    ).fetchone()

    if not row or not row["n"]:
        return []

    total_c = int(round(float(row["total_dollars"] or 0) * 100))
    return [{
        "id": "contractor_tax_ambiguity",
        "label": (
            f"Contractor income in window with no matched tax-"
            f"reconciliation event ({row['n']} transactions)"
        ),
        "severity": "info",
        "fix_action": None,
        "fix_payload": {},
        # Rough: ~22% effective marginal for self-employment.
        "magnitude_cents": int(round(total_c * 0.22)),
    }]
