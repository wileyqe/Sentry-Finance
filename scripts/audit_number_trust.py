"""Number-trust audit for the canonical synthetic seed.

The audit intentionally does not call production DAL report helpers for oracle
values.  It reads raw tables, applies independent formulas, calls the public
API, and writes JSON/Markdown diffs under docs/audits/number-trust/reports.
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sqlite3
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MANIFEST_PATH = ROOT / "data" / "trusted_seed_manifest.json"
REPORT_DIR = ROOT / "docs" / "audits" / "number-trust" / "reports"

from dal.category_classifications import (
    ALL_EXCL_FROM_SPEND,
    INCOME_CATEGORIES,
    INCOME_EXCL_FROM_INC,
)

CASH_ACCOUNT_TYPES = {"checking", "savings", "money_market"}
CASHOUT_SPEND_EXCLUDE = set(INCOME_CATEGORIES) | {
    "Transfers",
    "Transfer",
    "Refunds/Adjustments",
    "Mortgages",
    "Mortgage",
}
DEBT_CASH_CATEGORIES = {
    "Loan Payments",
    "Loan Payment",
    "Auto Loan",
    "Student Loan",
    "Credit Card Payments",
    "BNPL Payments",
}
DEBT_ACCUMULATED_EXCLUDE = {
    "Refunds/Adjustments",
    "Transfers",
    "Transfer",
    "Credit Card Payments",
    "Loan Payments",
    "Mortgages",
    "Auto Loan",
    "Student Loan",
}
LIABILITY_TYPES = {"credit_card", "credit", "loan", "mortgage", "bnpl"}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _manifest(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = 'trusted_seed_manifest'"
    ).fetchone()
    if row:
        return json.loads(row["value"])
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    raise RuntimeError("trusted seed manifest not found")


def _round2(value: float | int | None) -> float:
    return round(float(value or 0), 2)


def _cents(value: float | int | None) -> int:
    return int(round(float(value or 0) * 100))


def _month_bounds(ref: date) -> tuple[str, str]:
    last = calendar.monthrange(ref.year, ref.month)[1]
    return f"{ref.year}-{ref.month:02d}-01", f"{ref.year}-{ref.month:02d}-{last:02d}"


def _api_get(path: str) -> Any:
    from fastapi.testclient import TestClient
    from backend.api_server import app

    with TestClient(app) as client:
        res = client.get(path)
        if res.status_code >= 400:
            raise RuntimeError(f"API {path} failed: {res.status_code} {res.text}")
        return res.json()


def raw_report_summary(conn: sqlite3.Connection, start: str, end: str) -> dict[str, Any]:
    cashout = raw_cashout_period(conn, start, end)
    top_categories = [
        {
            "category": row["category"],
            "total_spent": row["total"],
            "transaction_count": row["count"],
            "pct_of_total": row["pct"],
        }
        for row in cashout["spending_categories"][:3]
    ]
    return {
        "total_income": cashout["income"],
        "total_spending": cashout["spending"],
        "net": cashout["net"],
        "top_categories": top_categories,
        "categories_with_spend": len(cashout["spending_categories"]),
    }


def raw_latest_net_worth(conn: sqlite3.Connection, ref: date) -> dict[str, Any]:
    month_end = f"{ref.year}-{ref.month:02d}-{calendar.monthrange(ref.year, ref.month)[1]:02d}"
    banking = 0.0
    liabilities = 0.0
    for acct in conn.execute(
        "SELECT id, type, is_active FROM accounts"
    ).fetchall():
        bal = conn.execute(
            """
            SELECT balance FROM balance_snapshots
             WHERE account_id = ? AND as_of <= ?
             ORDER BY as_of DESC LIMIT 1
            """,
            (acct["id"], month_end),
        ).fetchone()
        if not bal:
            continue
        if acct["type"] in {"checking", "savings"}:
            banking += float(bal["balance"] or 0)
        elif acct["type"] in {"credit_card", "loan", "bnpl", "mortgage"} and acct["is_active"]:
            liabilities += float(bal["balance"] or 0)

    portfolio = 0.0
    for acct in conn.execute(
        "SELECT id FROM accounts WHERE type IN ('investment', 'retirement')"
    ).fetchall():
        row = conn.execute(
            """
            SELECT total_account_value FROM portfolio_snapshots
             WHERE account_id = ? AND timestamp < date(?, '+1 month')
             ORDER BY timestamp DESC LIMIT 1
            """,
            (acct["id"], month_end[:7] + "-01"),
        ).fetchone()
        if row:
            portfolio += float(row["total_account_value"] or 0)

    real_estate = 0.0
    for row in conn.execute(
        """
        SELECT name, estimated_value FROM real_estate r
         WHERE name NOT LIKE '%[%'
           AND as_of = (
             SELECT MAX(as_of) FROM real_estate r2
              WHERE r2.name = r.name AND r2.as_of <= ?
           )
        """,
        (month_end,),
    ).fetchall():
        real_estate += float(row["estimated_value"] or 0)

    vehicles = 0.0
    for row in conn.execute(
        """
        SELECT vehicle_id, estimated_value FROM vehicle_valuations vv
         WHERE valuation_date = (
           SELECT MAX(valuation_date) FROM vehicle_valuations vv2
            WHERE vv2.vehicle_id = vv.vehicle_id AND vv2.valuation_date <= ?
         )
        """,
        (month_end,),
    ).fetchall():
        vehicles += float(row["estimated_value"] or 0)

    assets = _round2(banking + portfolio + real_estate + vehicles)
    return {
        "month": month_end[:7],
        "assets": assets,
        "liabilities": _round2(liabilities),
        "net_worth": _round2(assets + liabilities),
    }


def _payroll_adjustment(
    conn: sqlite3.Connection,
    start: str,
    end: str,
) -> tuple[int, int, int, set[str], list[dict[str, Any]]]:
    start_em, end_em = start[:7], end[:7]
    rows = conn.execute(
        """
        SELECT * FROM payroll_snapshots
         WHERE pay_period BETWEEN ? AND ?
         ORDER BY pay_period ASC, id ASC
        """,
        (start_em, end_em),
    ).fetchall()
    income_add_cents = 0
    withholding_cents = 0
    withholding_count = 0
    excluded_tx_ids: set[str] = set()
    income_categories: list[dict[str, Any]] = []
    for r in rows:
        gross = _cents(r["gross_pay"])
        for col in [
            "federal_tax",
            "state_tax",
            "sbp_premium",
            "health_insurance",
            "dental_vision",
            "other_deductions",
        ]:
            cents = _cents(r[col])
            if cents:
                withholding_cents += cents
                withholding_count += 1
        source = (r["source"] or "").strip().lower()
        match = None
        if len(source) >= 3:
            pattern = f"%{source}%"
            match = conn.execute(
                """
                SELECT id FROM transactions
                 WHERE status = 'posted'
                   AND signed_amount > 0
                   AND transfer_tag IS NULL
                   AND substr(COALESCE(effective_month, strftime('%Y-%m', posting_date)), 1, 7) = ?
                   AND (LOWER(COALESCE(merchant, '')) LIKE ?
                        OR LOWER(COALESCE(description, '')) LIKE ?)
                 ORDER BY signed_amount DESC, id ASC LIMIT 1
                """,
                (r["pay_period"], pattern, pattern),
            ).fetchone()
        if match and match["id"] not in excluded_tx_ids:
            excluded_tx_ids.add(match["id"])
            income_add_cents += gross
            label = "Paycheck (gross)"
        else:
            income_add_cents += gross
            label = "Paycheck (no deposit matched)"
        if gross > 0:
            income_categories.append({
                "category": label,
                "total_cents": gross,
                "count": 1,
            })
    return (
        income_add_cents,
        withholding_cents,
        withholding_count,
        excluded_tx_ids,
        income_categories,
    )


def raw_cashout_period(conn: sqlite3.Connection, start: str, end: str) -> dict[str, Any]:
    start_em, end_em = start[:7], end[:7]
    (
        _payroll_income_add,
        payroll_withholding,
        payroll_withholding_count,
        excluded_tx_ids,
        payroll_income_categories,
    ) = _payroll_adjustment(conn, start, end)

    excluded_clause = ""
    excluded_params: list[Any] = []
    if excluded_tx_ids:
        excluded_clause = "AND id NOT IN (" + ",".join("?" for _ in excluded_tx_ids) + ")"
        excluded_params = sorted(excluded_tx_ids)

    ph_income_excl = ",".join("?" for _ in INCOME_EXCL_FROM_INC)
    income_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Other Income') AS category,
               COALESCE(SUM(signed_amount), 0) AS total,
               COUNT(*) AS count
          FROM transactions
         WHERE status = 'posted'
           AND signed_amount > 0
           AND transfer_tag IS NULL
           AND COALESCE(category, 'Other Income') NOT IN ({ph_income_excl})
           {excluded_clause}
           AND COALESCE(effective_month, strftime('%Y-%m', posting_date)) BETWEEN ? AND ?
         GROUP BY category
        """,
        [*INCOME_EXCL_FROM_INC, *excluded_params, start_em, end_em],
    ).fetchall()
    income_categories = [
        {
            "category": r["category"],
            "total_cents": _cents(r["total"]),
            "count": r["count"],
        }
        for r in income_rows
    ]
    income_categories.extend(payroll_income_categories)
    income_categories.sort(key=lambda row: row["total_cents"], reverse=True)
    income_cents = sum(row["total_cents"] for row in income_categories)

    ph_cash_types = ",".join("?" for _ in CASH_ACCOUNT_TYPES)
    ph_spend_excl = ",".join("?" for _ in CASHOUT_SPEND_EXCLUDE)
    spend_rows = conn.execute(
        f"""
        SELECT COALESCE(t.category, 'Uncategorized') AS category,
               SUM(-t.signed_amount) AS total,
               COUNT(*) AS count
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
         WHERE t.status = 'posted'
           AND t.signed_amount < 0
           AND t.transfer_tag IS NULL
           AND a.type IN ({ph_cash_types})
           AND COALESCE(t.category, 'Uncategorized') NOT IN ({ph_spend_excl})
           AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
         GROUP BY category
        """,
        [*CASH_ACCOUNT_TYPES, *CASHOUT_SPEND_EXCLUDE, start_em, end_em],
    ).fetchall()
    ordinary_spend_cents = sum(_cents(r["total"]) for r in spend_rows)
    spending_categories = [
        {
            "category": r["category"],
            "total_cents": _cents(r["total"]),
            "count": r["count"],
        }
        for r in spend_rows
    ]
    raw_debt_cash_cents = sum(
        _cents(r["total"]) for r in spend_rows if r["category"] in DEBT_CASH_CATEGORIES
    )

    mortgage = conn.execute(
        """
        SELECT t.id, t.signed_amount, s.principal_cents, s.interest_cents, s.escrow_cents
          FROM transactions t
          LEFT JOIN loan_payment_splits s ON s.transaction_id = t.id
         WHERE t.status = 'posted'
           AND t.signed_amount < 0
           AND t.transfer_tag IS NULL
           AND t.category IN ('Mortgage', 'Mortgages')
           AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
        """,
        (start_em, end_em),
    ).fetchall()
    mortgage_consumed_cents = 0
    mortgage_principal_cents = 0
    for r in mortgage:
        total = _cents(abs(float(r["signed_amount"] or 0)))
        if r["principal_cents"] is None:
            mortgage_consumed_cents += total
        else:
            mortgage_principal_cents += int(r["principal_cents"] or 0)
            mortgage_consumed_cents += int(r["interest_cents"] or 0) + int(r["escrow_cents"] or 0)

    transfer_to_liability_cents = 0
    cc_payment_cents = 0
    cc_payment_count = 0
    loan_payment_via_transfer_cents = 0
    loan_payment_via_transfer_count = 0
    transfer_rows = conn.execute(
        """
        SELECT t.id, t.transfer_tag, t.account_id, t.signed_amount
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
         WHERE t.status = 'posted'
           AND t.signed_amount < 0
           AND t.transfer_tag IS NOT NULL
           AND a.type IN ('checking', 'savings', 'money_market')
           AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
        """,
        (start_em, end_em),
    ).fetchall()
    for t in transfer_rows:
        peer = conn.execute(
            """
            SELECT a.type FROM transactions p
              JOIN accounts a ON a.id = p.account_id
             WHERE p.transfer_tag = ?
               AND p.id != ?
               AND p.signed_amount > 0
             ORDER BY p.posting_date LIMIT 1
            """,
            (t["transfer_tag"], t["id"]),
        ).fetchone()
        peer_type = (peer["type"] or "").lower() if peer else ""
        if peer_type in LIABILITY_TYPES:
            amount_cents = _cents(abs(float(t["signed_amount"] or 0)))
            transfer_to_liability_cents += amount_cents
            if peer_type in {"credit_card", "credit", "bnpl"}:
                cc_payment_cents += amount_cents
                cc_payment_count += 1
            elif peer_type in {"loan", "mortgage"}:
                loan_payment_via_transfer_cents += amount_cents
                loan_payment_via_transfer_count += 1

    ph_debt_accumulated_excl = ",".join("?" for _ in DEBT_ACCUMULATED_EXCLUDE)
    debt_accumulated_row = conn.execute(
        f"""
        SELECT COALESCE(SUM(-t.signed_amount), 0) AS total
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
         WHERE t.status = 'posted'
           AND t.signed_amount < 0
           AND t.transfer_tag IS NULL
           AND a.type IN ('credit_card', 'credit', 'bnpl')
           AND COALESCE(t.category, '') NOT IN ({ph_debt_accumulated_excl})
           AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
        """,
        [*DEBT_ACCUMULATED_EXCLUDE, start_em, end_em],
    ).fetchone()
    debt_accumulated_cents = _cents(debt_accumulated_row["total"])

    spending_cents = ordinary_spend_cents + payroll_withholding + mortgage_consumed_cents + transfer_to_liability_cents
    debt_service_cents = mortgage_consumed_cents + transfer_to_liability_cents + raw_debt_cash_cents
    debt_paid_down_cents = mortgage_principal_cents + transfer_to_liability_cents + raw_debt_cash_cents
    net_cents = income_cents - spending_cents
    savings_rate = round((net_cents / income_cents) * 100, 1) if income_cents else 0.0

    if mortgage_consumed_cents > 0:
        spending_categories.append({
            "category": "Mortgage Interest & Escrow",
            "total_cents": mortgage_consumed_cents,
            "count": len(mortgage),
        })
    if cc_payment_cents > 0:
        spending_categories.append({
            "category": "Credit Card Payments",
            "total_cents": cc_payment_cents,
            "count": cc_payment_count,
        })
    if loan_payment_via_transfer_cents > 0:
        spending_categories.append({
            "category": "Loan / Mortgage Transfers",
            "total_cents": loan_payment_via_transfer_cents,
            "count": loan_payment_via_transfer_count,
        })
    if payroll_withholding > 0:
        spending_categories.append({
            "category": "Taxes & Withholdings",
            "total_cents": payroll_withholding,
            "count": payroll_withholding_count,
        })
    spending_categories.sort(key=lambda row: row["total_cents"], reverse=True)

    def _to_breakdown(rows: list[dict[str, Any]], total_cents: int) -> list[dict[str, Any]]:
        return [
            {
                "category": row["category"],
                "total": round(row["total_cents"] / 100, 2),
                "count": row["count"],
                "pct": round(row["total_cents"] / total_cents * 100, 1)
                if total_cents
                else 0.0,
            }
            for row in rows
            if row["total_cents"] > 0
        ]

    return {
        "income": round(income_cents / 100, 2),
        "spending": round(spending_cents / 100, 2),
        "net": round(net_cents / 100, 2),
        "savings_rate": savings_rate,
        "debt_service": round(debt_service_cents / 100, 2),
        "debt_accumulated": round(debt_accumulated_cents / 100, 2),
        "debt_paid_down": round(debt_paid_down_cents / 100, 2),
        "net_debt_change": round((debt_accumulated_cents - debt_paid_down_cents) / 100, 2),
        "income_categories": _to_breakdown(income_categories, income_cents),
        "spending_categories": _to_breakdown(spending_categories, spending_cents),
    }


def raw_emergency_fund(conn: sqlite3.Connection, ref: date) -> dict[str, Any]:
    liquid = conn.execute(
        """
        SELECT COALESCE(SUM(latest.balance), 0) AS total
          FROM accounts a
          JOIN (
            SELECT bs.account_id, bs.balance
              FROM balance_snapshots bs
              JOIN (
                SELECT account_id, MAX(as_of) AS max_as_of
                  FROM balance_snapshots GROUP BY account_id
              ) mx ON mx.account_id = bs.account_id AND mx.max_as_of = bs.as_of
          ) latest ON latest.account_id = a.id
         WHERE a.type IN ('checking', 'savings') AND a.is_active = 1
        """
    ).fetchone()["total"]

    current_month = ref.replace(day=1)
    start_month_index = current_month.year * 12 + current_month.month - 1 - 6
    start = date(start_month_index // 12, start_month_index % 12 + 1, 1).isoformat()
    end = current_month.isoformat()
    ph = ",".join("?" for _ in ALL_EXCL_FROM_SPEND)
    rows = conn.execute(
        f"""
        SELECT COALESCE(effective_month, strftime('%Y-%m', posting_date)) AS month,
               SUM(-signed_amount) AS total
          FROM transactions
         WHERE status = 'posted'
           AND signed_amount < 0
           AND transfer_tag IS NULL
           AND COALESCE(category, 'Uncategorized') NOT IN ({ph})
           AND posting_date >= ?
           AND posting_date < ?
         GROUP BY month
        """,
        [*ALL_EXCL_FROM_SPEND, start, end],
    ).fetchall()
    avg = sum(float(r["total"] or 0) for r in rows) / len(rows) if rows else 0.0
    return {
        "liquid_balance": _round2(liquid),
        "avg_monthly_spending": _round2(avg),
        "months_of_runway": round(float(liquid or 0) / avg, 1) if avg else None,
    }


def raw_latest_credit_scores(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT cs.score, cs.score_type, cs.source, cs.institution_id,
               cs.score_date, cs.owner_id
          FROM credit_scores cs
          JOIN (
            SELECT owner_id, institution_id, source, MAX(score_date) AS max_date
              FROM credit_scores
             GROUP BY owner_id, institution_id, source
          ) latest ON cs.owner_id IS latest.owner_id
                   AND cs.institution_id = latest.institution_id
                   AND cs.source = latest.source
                   AND cs.score_date = latest.max_date
         ORDER BY cs.owner_id, cs.score_date DESC
        """
    ).fetchall()
    return [{**dict(r), "factors": []} for r in rows]


def raw_freshness(conn: sqlite3.Connection, ref: date) -> list[dict[str, Any]]:
    now = datetime.combine(ref, time.min, tzinfo=timezone.utc)
    active_rows = conn.execute(
        "SELECT DISTINCT institution_id FROM accounts WHERE is_active = 1"
    ).fetchall()
    active_institutions = {r["institution_id"] for r in active_rows}
    active_institutions.update({"tsp", "mypay"})
    try:
        active_institutions.update(
            r["institution_id"]
            for r in conn.execute("SELECT institution_id FROM institution_refresh_status")
        )
    except sqlite3.OperationalError:
        pass

    refresh_last = {}
    try:
        refresh_last = {
            r["institution_id"]: r["last_success"]
            for r in conn.execute(
                "SELECT institution_id, last_success FROM institution_refresh_status"
            ).fetchall()
            if r["last_success"]
        }
    except sqlite3.OperationalError:
        pass

    balance_last = {
        r["institution_id"]: r["latest"]
        for r in conn.execute(
            """
            SELECT a.institution_id, MAX(bs.as_of) AS latest
              FROM balance_snapshots bs
              JOIN accounts a ON a.id = bs.account_id
             GROUP BY a.institution_id
            """
        ).fetchall()
        if r["latest"]
    }
    portfolio_last = {
        r["institution_id"]: r["latest"]
        for r in conn.execute(
            """
            SELECT a.institution_id, MAX(ps.timestamp) AS latest
              FROM portfolio_snapshots ps
              JOIN accounts a ON a.id = ps.account_id
             GROUP BY a.institution_id
            """
        ).fetchall()
        if r["latest"]
    }
    apy_last = {}
    try:
        apy_last = {
            r["institution_id"]: r["latest"]
            for r in conn.execute(
                """
                SELECT a.institution_id, MAX(ah.as_of) AS latest
                  FROM apy_history ah
                  JOIN accounts a ON a.id = ah.account_id
                 GROUP BY a.institution_id
                """
            ).fetchall()
            if r["latest"]
        }
    except sqlite3.OperationalError:
        pass

    result = []
    for inst in active_institutions:
        ts_raw = max(
            (
                ts
                for ts in [
                    refresh_last.get(inst),
                    balance_last.get(inst),
                    portfolio_last.get(inst),
                    apy_last.get(inst),
                ]
                if ts
            ),
            default=None,
        )
        expected_hours = 720 if inst in {"tsp", "mypay"} else 24
        staleness = "no_data"
        if ts_raw:
            if "T" not in ts_raw and " " not in ts_raw:
                ts = datetime.fromisoformat(ts_raw[:10] + "T23:59:59").replace(tzinfo=timezone.utc)
            else:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            hours_since = max((now - ts).total_seconds() / 3600, 0)
            if hours_since <= expected_hours:
                staleness = "fresh"
            elif hours_since <= expected_hours * 3:
                staleness = "stale"
            else:
                staleness = "critical"
        result.append({"institution_id": inst, "staleness": staleness})
    return sorted(result, key=lambda x: x["institution_id"])

def _compare(name: str, expected: Any, actual: Any, diffs: list[dict[str, Any]], classification: str = "API/DAL logic bug") -> None:
    if expected != actual:
        diffs.append({
            "id": name,
            "expected": expected,
            "actual": actual,
            "classification": classification,
        })


def _compare_money_cents(
    name: str,
    expected: float | int | None,
    actual: float | int | None,
    diffs: list[dict[str, Any]],
    classification: str = "API/DAL logic bug",
) -> None:
    _compare(name, _cents(expected), _cents(actual), diffs, classification=classification)


def _check_partition(
    name: str,
    rows: list[dict[str, Any]],
    total: float | int | None,
    diffs: list[dict[str, Any]],
) -> None:
    row_total_cents = sum(_cents(row.get("total")) for row in rows)
    total_cents = _cents(total)
    _compare(
        f"{name}.category_total_matches_headline",
        total_cents,
        row_total_cents,
        diffs,
        classification="invariant violation",
    )
    if total_cents:
        pct_sum = round(sum(float(row.get("pct") or 0) for row in rows), 1)
        expected_pct = 100.0 if row_total_cents else 0.0
        if abs(pct_sum - expected_pct) > 0.5:
            diffs.append({
                "id": f"{name}.category_pct_sum",
                "expected": expected_pct,
                "actual": pct_sum,
                "classification": "invariant violation",
            })


def run(db_path: Path) -> dict[str, Any]:
    os.environ["SENTRY_DB_PATH"] = str(db_path)
    os.environ.setdefault("SENTRY_DB_MODE", "trusted")
    conn = _connect(db_path)
    try:
        manifest = _manifest(conn)
        ref = date.fromisoformat(manifest["reference_date"])
        start, end = _month_bounds(ref)

        diffs: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []

        nw_expected = raw_latest_net_worth(conn, ref)
        nw_api = _api_get("/api/reports/net-worth-history?months=6")
        nw_actual = (nw_api.get("history") or [])[-1]
        _compare_money_cents(
            "dashboard.net_worth.latest",
            nw_expected["net_worth"],
            nw_actual.get("net_worth"),
            diffs,
        )
        checks.append({"id": "dashboard.net_worth.latest", "expected": nw_expected, "actual": nw_actual})

        summary_expected = raw_report_summary(conn, start, end)
        summary_api = _api_get(f"/api/reports/summary?start_date={start}&end_date={end}")
        for field in ["total_income", "total_spending", "net"]:
            _compare_money_cents(
                f"dashboard.monthly_net_flow.{field}",
                summary_expected[field],
                summary_api.get(field),
                diffs,
            )
        _compare(
            "dashboard.monthly_net_flow.categories_with_spend",
            summary_expected["categories_with_spend"],
            summary_api.get("categories_with_spend"),
            diffs,
        )
        checks.append({"id": "dashboard.monthly_net_flow", "expected": summary_expected, "actual": summary_api})

        emergency_expected = raw_emergency_fund(conn, ref)
        emergency_api = _api_get("/api/metrics/emergency-fund")
        for field in ["liquid_balance", "avg_monthly_spending"]:
            _compare_money_cents(
                f"dashboard.emergency_runway.{field}",
                emergency_expected[field],
                emergency_api.get(field),
                diffs,
            )
        _compare(
            "dashboard.emergency_runway.months_of_runway",
            emergency_expected["months_of_runway"],
            emergency_api.get("months_of_runway"),
            diffs,
        )
        checks.append({"id": "dashboard.emergency_runway", "expected": emergency_expected, "actual": emergency_api})

        credit_expected = raw_latest_credit_scores(conn)
        credit_api = _api_get("/api/metrics/credit-scores").get("latest") or []
        _compare("dashboard.credit_scores.latest", credit_expected, credit_api, diffs)
        checks.append({"id": "dashboard.credit_scores.latest", "expected": credit_expected, "actual": credit_api})

        fresh_expected = raw_freshness(conn, ref)
        fresh_api = sorted(
            [{"institution_id": r["institution_id"], "staleness": r["staleness"]} for r in _api_get("/api/freshness")],
            key=lambda x: x["institution_id"],
        )
        _compare("dashboard.freshness.state_labels", fresh_expected, fresh_api, diffs, classification="label mismatch")
        checks.append({"id": "dashboard.freshness.state_labels", "expected": fresh_expected, "actual": fresh_api})

        cash_expected = raw_cashout_period(conn, start, end)
        cash_api = _api_get(f"/api/cash-flow/period?start={start}&end={end}")
        for field in ["income", "spending", "net", "debt_service", "debt_accumulated", "debt_paid_down", "net_debt_change"]:
            _compare_money_cents(
                f"cash_flow.current_month.{field}",
                cash_expected[field],
                cash_api.get(field),
                diffs,
            )
        _compare(
            "cash_flow.current_month.savings_rate",
            cash_expected["savings_rate"],
            _round2(cash_api.get("savings_rate")),
            diffs,
        )
        _check_partition(
            "cash_flow.current_month.income",
            cash_api.get("income_categories") or [],
            cash_api.get("income"),
            diffs,
        )
        _check_partition(
            "cash_flow.current_month.spending",
            cash_api.get("spending_categories") or [],
            cash_api.get("spending"),
            diffs,
        )
        for summary_field, cash_field in [
            ("total_income", "income"),
            ("total_spending", "spending"),
            ("net", "net"),
        ]:
            _compare_money_cents(
                f"reports_summary.matches_cash_flow.{summary_field}",
                summary_api.get(summary_field),
                cash_api.get(cash_field),
                diffs,
                classification="API/DAL logic bug",
            )
        checks.append({"id": "cash_flow.current_month", "expected": cash_expected, "actual": cash_api})

        rolling_api = _api_get("/api/cash-flow/monthly-rolling")
        latest = (rolling_api.get("months") or [])[-1]
        rolling_actual = {k: _round2(latest.get(k)) for k in ["income", "spending", "net", "savings_rate", "debt_service", "debt_accumulated", "debt_paid_down", "net_debt_change"]}
        rolling_expected = {k: cash_expected[k] for k in rolling_actual}
        for field in ["income", "spending", "net", "debt_service", "debt_accumulated", "debt_paid_down", "net_debt_change"]:
            _compare_money_cents(
                f"cash_flow.rolling.latest_month.{field}",
                rolling_expected[field],
                rolling_actual[field],
                diffs,
            )
        _compare(
            "cash_flow.rolling.latest_month.savings_rate",
            rolling_expected["savings_rate"],
            rolling_actual["savings_rate"],
            diffs,
        )
        checks.append({"id": "cash_flow.rolling.latest_month", "expected": rolling_expected, "actual": rolling_actual})

        return {
            "seed_version": manifest.get("seed_version"),
            "database_fingerprint": manifest.get("database_fingerprint"),
            "reference_date": manifest.get("reference_date"),
            "diff_count": len(diffs),
            "diffs": diffs,
            "checks": checks,
        }
    finally:
        conn.close()


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_DIR / f"number-trust-{stamp}.json"
    md_path = REPORT_DIR / f"number-trust-{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Number Trust Audit",
        "",
        f"- Seed version: `{report['seed_version']}`",
        f"- Reference date: `{report['reference_date']}`",
        f"- Database fingerprint: `{report['database_fingerprint']}`",
        f"- Diff count: `{report['diff_count']}`",
        "",
    ]
    if report["diffs"]:
        lines.append("## Diffs")
        lines.append("")
        for diff in report["diffs"]:
            lines.extend([
                f"### {diff['id']}",
                "",
                f"- Classification: `{diff['classification']}`",
                f"- Expected: `{diff['expected']}`",
                f"- Actual: `{diff['actual']}`",
                "",
            ])
    else:
        lines.append("No diffs found.")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit UI numbers against raw trusted-seed facts")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()
    db_path = args.db
    if db_path is None and os.environ.get("SENTRY_DB_PATH"):
        db_path = Path(os.environ["SENTRY_DB_PATH"])
    if db_path is None:
        parser.error("--db or SENTRY_DB_PATH is required; there is no implicit audit database")
    report = run(db_path)
    json_path, md_path = write_reports(report)
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    print(f"Diff count: {report['diff_count']}")
    return 1 if report["diff_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
