"""
tests/test_payroll.py — Phase 9 unit tests for dal/payroll.py.

Covers the new payroll-snapshot aggregation module that surfaces myPay RAS
data into the monthly review and yearly wrap-up.
"""

import sqlite3
import tempfile
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.payroll import (
    get_payroll_snapshots,
    get_gross_income_for_month,
    get_gross_income_for_year,
    get_effective_tax_rate,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


_passed = 0
_failed = 0
_errors: list[str] = []


def _check(name: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✔  {name}")
    else:
        _failed += 1
        msg = f"  ✗  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        _errors.append(name)


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


def _insert_payroll(
    conn,
    pay_period: str,
    *,
    gross: float = 8000.0,
    federal: float = 800.0,
    state: float = 200.0,
    sbp: float = 50.0,
    health: float = 100.0,
    dental: float = 30.0,
    other: float = 20.0,
    source: str = "mypay_ras",
):
    net = gross - federal - state - sbp - health - dental - other
    conn.execute(
        """
        INSERT INTO payroll_snapshots
        (pay_period, source, gross_pay, federal_tax, state_tax,
         sbp_premium, health_insurance, dental_vision, other_deductions,
         net_pay, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
        """,
        (pay_period, source, gross, federal, state, sbp, health, dental, other, net),
    )


# ── Tests ────────────────────────────────────────────────────────────────────


def test_empty_table():
    print("\n─── T01.1: Empty payroll_snapshots ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:

            rows = get_payroll_snapshots(conn)
            _check("empty: get_payroll_snapshots returns []", rows == [])

            month = get_gross_income_for_month(conn, 2025, 6)
            _check("empty: get_gross_income_for_month returns None", month is None)

            year = get_gross_income_for_year(conn, 2025)
            _check("empty: year data_quality == missing",
                   year["data_quality"] == "missing",
                   f"got {year['data_quality']}")
            _check("empty: year months_covered == 0",
                   year["months_covered"] == 0)
            _check("empty: year gross_pay == 0",
                   year["gross_pay"] == 0.0)

            etr = get_effective_tax_rate(conn, 2025)
            _check("empty: effective_rate_pct == 0.0",
                   etr["effective_rate_pct"] == 0.0)
            _check("empty: total_tax == 0.0",
                   etr["total_tax"] == 0.0)
            _check("empty: data_quality == missing",
                   etr["data_quality"] == "missing")
    finally:
        os.unlink(db)


def test_single_month():
    print("\n─── T01.2: Single-month snapshot ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _insert_payroll(conn, "2025-06",
                            gross=8000.0, federal=800.0, state=200.0,
                            sbp=50.0, health=100.0, dental=30.0, other=20.0)
            conn.commit()

            month = get_gross_income_for_month(conn, 2025, 6)
            _check("single: month returned", month is not None)
            _check("single: gross_pay == 8000",
                   month["gross_pay"] == 8000.0,
                   f"got {month['gross_pay']}")
            _check("single: federal_tax == 800",
                   month["federal_tax"] == 800.0)
            _check("single: deductions_total == 200",
                   month["deductions_total"] == 200.0,
                   f"got {month['deductions_total']}")

            # Wrong month → None
            other = get_gross_income_for_month(conn, 2025, 7)
            _check("single: other month is None", other is None)

            # Year aggregate is partial (1 / 12 months)
            year = get_gross_income_for_year(conn, 2025)
            _check("single: year months_covered == 1",
                   year["months_covered"] == 1)
            _check("single: year data_quality == partial",
                   year["data_quality"] == "partial",
                   f"got {year['data_quality']}")
            _check("single: year gross_pay == 8000",
                   year["gross_pay"] == 8000.0)

            etr = get_effective_tax_rate(conn, 2025)
            # (800 + 200) / 8000 * 100 = 12.5
            _check("single: effective_rate_pct == 12.5",
                   etr["effective_rate_pct"] == 12.5,
                   f"got {etr['effective_rate_pct']}")
            _check("single: total_tax == 1000",
                   etr["total_tax"] == 1000.0)
    finally:
        os.unlink(db)


def test_full_year():
    print("\n─── T01.3: Full 12-month year ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            for m in range(1, 13):
                _insert_payroll(conn, f"2025-{m:02d}",
                                gross=8000.0, federal=800.0, state=200.0,
                                sbp=50.0, health=100.0, dental=30.0, other=20.0)
            conn.commit()

            year = get_gross_income_for_year(conn, 2025)
            _check("full: months_covered == 12",
                   year["months_covered"] == 12)
            _check("full: data_quality == complete",
                   year["data_quality"] == "complete")
            _check("full: gross_pay == 96000",
                   year["gross_pay"] == 96000.0,
                   f"got {year['gross_pay']}")
            _check("full: federal_tax == 9600",
                   year["federal_tax"] == 9600.0)
            _check("full: state_tax == 2400",
                   year["state_tax"] == 2400.0)
            _check("full: deductions_total == 2400",
                   year["deductions_total"] == 2400.0,
                   f"got {year['deductions_total']}")

            etr = get_effective_tax_rate(conn, 2025)
            # (9600 + 2400) / 96000 * 100 = 12.5
            _check("full: effective_rate_pct == 12.5",
                   etr["effective_rate_pct"] == 12.5,
                   f"got {etr['effective_rate_pct']}")
            _check("full: total_tax == 12000",
                   etr["total_tax"] == 12000.0)

            # range query bounds
            all_rows = get_payroll_snapshots(conn)
            _check("full: all_rows length == 12", len(all_rows) == 12)
            ordered = [r["pay_period"] for r in all_rows]
            _check("full: rows ordered ascending",
                   ordered == sorted(ordered))

            q1 = get_payroll_snapshots(conn, start="2025-01", end="2025-03")
            _check("full: Q1 range returns 3 rows",
                   len(q1) == 3,
                   f"got {len(q1)}")
    finally:
        os.unlink(db)


def test_missing_month_gap():
    print("\n─── T01.4: Year with mid-year gap ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            # Insert all months except July
            for m in range(1, 13):
                if m == 7:
                    continue
                _insert_payroll(conn, f"2025-{m:02d}",
                                gross=8000.0, federal=800.0, state=200.0)
            conn.commit()

            year = get_gross_income_for_year(conn, 2025)
            _check("gap: months_covered == 11",
                   year["months_covered"] == 11)
            _check("gap: data_quality == partial",
                   year["data_quality"] == "partial",
                   f"got {year['data_quality']}")
            _check("gap: gross_pay == 88000",
                   year["gross_pay"] == 88000.0)

            # July specifically returns None
            july = get_gross_income_for_month(conn, 2025, 7)
            _check("gap: July returns None", july is None)

            # June still has data
            june = get_gross_income_for_month(conn, 2025, 6)
            _check("gap: June still present",
                   june is not None and june["gross_pay"] == 8000.0)
    finally:
        os.unlink(db)


def test_partial_year_at_start():
    print("\n─── T01.5: Partial year (only first 3 months) ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            for m in range(1, 4):
                _insert_payroll(conn, f"2025-{m:02d}",
                                gross=10000.0, federal=1500.0, state=500.0,
                                sbp=0.0, health=0.0, dental=0.0, other=0.0)
            conn.commit()

            year = get_gross_income_for_year(conn, 2025)
            _check("partial: months_covered == 3",
                   year["months_covered"] == 3)
            _check("partial: data_quality == partial",
                   year["data_quality"] == "partial")
            _check("partial: gross_pay == 30000",
                   year["gross_pay"] == 30000.0)

            etr = get_effective_tax_rate(conn, 2025)
            # (4500 + 1500) / 30000 * 100 = 20.0
            _check("partial: effective_rate_pct == 20.0",
                   etr["effective_rate_pct"] == 20.0,
                   f"got {etr['effective_rate_pct']}")
            _check("partial: data_quality bubbles up == partial",
                   etr["data_quality"] == "partial")

            # Year before has nothing
            prior = get_gross_income_for_year(conn, 2024)
            _check("partial: prior year missing",
                   prior["data_quality"] == "missing")
    finally:
        os.unlink(db)


# ── Main ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    test_empty_table()
    test_single_month()
    test_full_year()
    test_missing_month_gap()
    test_partial_year_at_start()

    print(f"\n{'═' * 60}")
    print(f"  Payroll Tests: {_passed} passed, {_failed} failed")
    if _errors:
        print(f"  Failed: {', '.join(_errors)}")
    print(f"{'═' * 60}")
    sys.exit(1 if _failed else 0)
