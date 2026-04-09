"""
tests/test_phase6.py — Phase 6 unit tests.

Tests for:
  T04: Lifestyle creep detection
  T05: Contributions vs. performance decomposition
  T01: Monthly review assembler
  T02: Yearly wrap-up (preliminary)
  T03: Yearly wrap-up (revised / tax doc overlay)
"""

import sqlite3
import tempfile
import os
import sys
import json
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db


# ── Helpers ──────────────────────────────────────────────────────────────────


_passed = 0
_failed = 0
_errors = []


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


def _seed_base(conn):
    """Seed institution + accounts for testing."""
    conn.execute("INSERT INTO institutions (id, display_name) VALUES ('test', 'Test Bank')")
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('test_chk', 'test', 'Checking', '1234', 'checking', 1)"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('test_inv', 'test', 'Investment', '5678', 'investment', 1)"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('test_cc', 'test', 'Credit Card', '9999', 'credit_card', 1)"
    )
    conn.commit()


def _insert_txn(conn, acct_id, posting_date, amount, direction, category,
                transfer_tag=None, status="posted", desc="Test"):
    """Insert a single transaction."""
    signed = amount if direction == "Credit" else -amount
    import hashlib
    txn_id = hashlib.sha256(f"{acct_id}:{posting_date}:{amount}:{desc}:{category}".encode()).hexdigest()[:16]
    conn.execute(
        """
        INSERT OR IGNORE INTO transactions
        (id, account_id, institution_id, posting_date, amount, signed_amount,
         direction, description, category, status, transfer_tag, created_at, updated_at)
        VALUES (?, ?, 'test', ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (txn_id, acct_id, posting_date, amount, signed, direction, desc, category, status, transfer_tag),
    )


def _insert_balance_snapshot(conn, acct_id, balance, as_of):
    conn.execute(
        "INSERT INTO balance_snapshots (account_id, balance, as_of) VALUES (?, ?, ?)",
        (acct_id, balance, as_of),
    )


# ── T04: Lifestyle Creep ─────────────────────────────────────────────────────


def test_lifestyle_creep():
    print("\n─── T04: Lifestyle Creep ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)

            # Test 1: Insufficient data returns graceful result
            from dal.lifestyle import get_lifestyle_creep
            result = get_lifestyle_creep(conn)
            _check("T04.1: Insufficient data flag", result.get("insufficient_data") is True)
            _check("T04.2: Categories empty on insufficient data", result["categories"] == [])
            _check("T04.3: Flagged count is 0", result["flagged_count"] == 0)

            # Test 2: Seed 24+ months of data
            today = date.today()
            for months_ago in range(30):  # 30 months of data
                m = today.month - months_ago
                y = today.year
                while m <= 0:
                    m += 12
                    y -= 1
                posting_date = f"{y}-{m:02d}-15"

                # Income: grows from $6000 to $6600 (10% over 30 months)
                income_amt = 6000 + (30 - months_ago) * 20
                _insert_txn(conn, "test_chk", posting_date, income_amt, "Credit", "Military Pension", desc=f"Income_{months_ago}")

                # Dining: grows from $300 to $420 (40% — should flag)
                dining_amt = 300 + (30 - months_ago) * 4
                _insert_txn(conn, "test_chk", posting_date, dining_amt, "Debit", "Restaurants/Dining", desc=f"Dining_{months_ago}")

                # Groceries: stays flat at $400 (0% — should not flag)
                _insert_txn(conn, "test_chk", posting_date, 400, "Debit", "Groceries", desc=f"Grocery_{months_ago}")

                # Utilities: flat $200 (excluded from creep)
                _insert_txn(conn, "test_chk", posting_date, 200, "Debit", "Utilities", desc=f"Utils_{months_ago}")

                # Small category: $40/mo (below $500 annual threshold — should not flag even with growth)
                small_amt = 30 + months_ago
                _insert_txn(conn, "test_chk", posting_date, small_amt, "Debit", "Pet Care", desc=f"Pet_{months_ago}")

            conn.commit()

            result2 = get_lifestyle_creep(conn, lookback_years=2)
            _check("T04.4: Not insufficient after seeding", result2.get("insufficient_data") is not True)
            _check("T04.5: Income growth is a number", result2["income_growth_pct"] is not None)
            _check("T04.6: Categories list populated",
                   len(result2["categories"]) > 0,
                   f"got {len(result2['categories'])}")

            # Check that flagged categories are sorted first
            if result2["flagged_count"] > 0:
                _check("T04.7: First category is flagged",
                       result2["categories"][0]["flagged"] is True)

            # Excluded categories should never be flagged
            excluded_flagged = [c for c in result2["categories"]
                               if c["category"] in ("Utilities", "Mortgage", "Transfers")
                               and c["flagged"]]
            _check("T04.8: Excluded categories not flagged", len(excluded_flagged) == 0)

    finally:
        os.unlink(db)


# ── T05: Contributions vs. Performance ────────────────────────────────────────
# Removed in P13 investments rebuild.  The `decompose_contributions_vs_performance`
# function lived in the deleted dal.performance module.


# ── T01: Monthly Review ──────────────────────────────────────────────────────


def test_monthly_review():
    print("\n─── T01: Monthly Review ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)

            # Seed some transactions for prior month
            today = date.today()
            if today.month == 1:
                test_year, test_month = today.year - 1, 12
            else:
                test_year, test_month = today.year, today.month - 1

            # Build at least 18 months of data
            for i in range(20):
                m = today.month - i
                y = today.year
                while m <= 0:
                    m += 12
                    y -= 1
                posting = f"{y}-{m:02d}-10"
                _insert_txn(conn, "test_chk", posting, 5000, "Credit", "Military Pension", desc=f"Pay_{i}")
                _insert_txn(conn, "test_chk", posting, 300, "Debit", "Groceries", desc=f"Groc_{i}")
                _insert_txn(conn, "test_chk", posting, 100, "Debit", "Uncategorized", desc=f"Unk_{i}")
            conn.commit()

            from dal.review import get_monthly_review
            month_str = f"{test_year}-{test_month:02d}"
            review = get_monthly_review(conn, month_str)

            # Check all 8 required keys
            required_keys = [
                "month", "income", "spending", "savings_rate",
                "net_worth_delta", "budget_highlights",
                "subscription_changes", "notable_transactions",
                "uncategorized_count", "lifestyle_flags", "freshness",
            ]
            missing = [k for k in required_keys if k not in review]
            _check("T01.1: All required keys present",
                   len(missing) == 0,
                   f"missing: {missing}")

            _check("T01.2: Month matches", review["month"] == month_str)
            _check("T01.3: Income is a dict with total",
                   isinstance(review["income"], dict) and "total" in review["income"])
            _check("T01.4: Spending is a dict with total",
                   isinstance(review["spending"], dict) and "total" in review["spending"])
            _check("T01.5: Budget highlights is a list",
                   isinstance(review["budget_highlights"], list))
            _check("T01.6: Notable transactions is a list",
                   isinstance(review["notable_transactions"], list))
            _check("T01.7: Uncategorized count >= 0",
                   review["uncategorized_count"] >= 0)
            _check("T01.8: Lifestyle flags is a list (graceful fallback)",
                   isinstance(review["lifestyle_flags"], list))
            _check("T01.9: Freshness is a list",
                   isinstance(review["freshness"], list))

            # ── Phase 9: pre_tax block ────────────────────────────────
            _check("T01.10: pre_tax key present",
                   "pre_tax" in review)
            _check("T01.11: pre_tax is None when no payroll snapshot",
                   review["pre_tax"] is None,
                   f"got {review['pre_tax']}")

            # Insert a payroll snapshot for the target month and re-run
            conn.execute(
                """
                INSERT INTO payroll_snapshots
                (pay_period, source, gross_pay, federal_tax, state_tax,
                 sbp_premium, health_insurance, dental_vision,
                 other_deductions, net_pay, raw_json)
                VALUES (?, 'mypay_ras', 8000, 800, 200, 50, 100, 30, 20, 6800, '{}')
                """,
                (month_str,),
            )
            conn.commit()

            review2 = get_monthly_review(conn, month_str)
            _check("T01.12: pre_tax populated when snapshot exists",
                   review2["pre_tax"] is not None)
            if review2["pre_tax"]:
                pt = review2["pre_tax"]
                _check("T01.13: pre_tax.gross_income == 8000",
                       pt["gross_income"] == 8000.0,
                       f"got {pt['gross_income']}")
                _check("T01.14: pre_tax.federal_tax == 800",
                       pt["federal_tax"] == 800.0)
                _check("T01.15: pre_tax has savings_rate_pct field",
                       "savings_rate_pct" in pt)

    finally:
        os.unlink(db)


# ── T02: Yearly Wrap-Up (Preliminary) ────────────────────────────────────────


def test_yearly_wrapup_preliminary():
    print("\n─── T02: Yearly Wrap-Up (Preliminary) ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)

            year = date.today().year - 1

            # Seed transactions for that year
            for m in range(1, 13):
                posting = f"{year}-{m:02d}-15"
                _insert_txn(conn, "test_chk", posting, 5000, "Credit", "Military Pension", desc=f"Pension_{m}")
                _insert_txn(conn, "test_chk", posting, 1000, "Credit", "VA Benefits", desc=f"VA_{m}")
                _insert_txn(conn, "test_chk", posting, 400, "Debit", "Groceries", desc=f"Groc_{m}")
                _insert_txn(conn, "test_chk", posting, 200, "Debit", "Restaurants/Dining", desc=f"Dine_{m}")

            # Seed investment snapshots
            _insert_balance_snapshot(conn, "test_inv", 50000, f"{year}-01-10")
            _insert_balance_snapshot(conn, "test_inv", 55000, f"{year}-12-20")
            conn.commit()

            from dal.yearly_wrapup import get_yearly_wrapup

            wrapup = get_yearly_wrapup(conn, year)

            # Check top-level keys
            required_keys = [
                "year", "status", "income_by_stream", "total_income",
                "total_spending", "savings_rate", "spending_by_category",
                "net_worth_trajectory", "interest", "investment_performance",
                "debt_progress", "recurring_changes", "goals_progress",
                "contributions_vs_performance", "lifestyle_flags",
            ]
            missing = [k for k in required_keys if k not in wrapup]
            _check("T02.1: All required keys present",
                   len(missing) == 0,
                   f"missing: {missing}")

            _check("T02.2: Year matches", wrapup["year"] == year)

            # Status check — should be preliminary if no tax docs in DB
            _check("T02.3: Status is preliminary",
                   wrapup["status"] == "preliminary",
                   f"got: {wrapup['status']}")

            # Income streams
            pension_stream = [s for s in wrapup["income_by_stream"]
                            if s["stream"] == "Military Pension"]
            _check("T02.4: Military Pension stream present",
                   len(pension_stream) == 1)
            if pension_stream:
                _check("T02.5: Income total > 0",
                       pension_stream[0]["total"] > 0,
                       f"got {pension_stream[0]['total']}")

            va_stream = [s for s in wrapup["income_by_stream"]
                        if s["stream"] == "VA Benefits"]
            _check("T02.6: VA Benefits stream present", len(va_stream) == 1)

            _check("T02.7: Total income > 0",
                   wrapup["total_income"] > 0,
                   f"got {wrapup['total_income']}")
            _check("T02.8: Total spending > 0",
                   wrapup["total_spending"] > 0,
                   f"got {wrapup['total_spending']}")

            # Graceful degradation
            _check("T02.9: Lifestyle flags is list (graceful)",
                   isinstance(wrapup["lifestyle_flags"], list))
            _check("T02.10: Contributions vs perf is list (graceful)",
                   isinstance(wrapup["contributions_vs_performance"], list))

            # ── Phase 9: pre_tax + effective_tax blocks ───────────────
            _check("T02.11: pre_tax key present", "pre_tax" in wrapup)
            _check("T02.12: pre_tax is None when no payroll data",
                   wrapup["pre_tax"] is None)
            _check("T02.13: effective_tax key present",
                   "effective_tax" in wrapup)
            _check("T02.14: effective_tax data_quality == missing",
                   wrapup["effective_tax"]["data_quality"] == "missing",
                   f"got {wrapup['effective_tax']['data_quality']}")
            _check("T02.15: effective_tax effective_rate_pct == 0.0",
                   wrapup["effective_tax"]["effective_rate_pct"] == 0.0)

            # Seed full year of payroll snapshots and re-run
            for m in range(1, 13):
                conn.execute(
                    """
                    INSERT INTO payroll_snapshots
                    (pay_period, source, gross_pay, federal_tax, state_tax,
                     sbp_premium, health_insurance, dental_vision,
                     other_deductions, net_pay, raw_json)
                    VALUES (?, 'mypay_ras', 8000, 800, 200, 50, 100, 30, 20, 6800, '{}')
                    """,
                    (f"{year}-{m:02d}",),
                )
            conn.commit()

            wrapup2 = get_yearly_wrapup(conn, year)
            _check("T02.16: pre_tax populated after seeding",
                   wrapup2["pre_tax"] is not None)
            if wrapup2["pre_tax"]:
                _check("T02.17: pre_tax.gross_income == 96000",
                       wrapup2["pre_tax"]["gross_income"] == 96000.0,
                       f"got {wrapup2['pre_tax']['gross_income']}")
                _check("T02.18: pre_tax.data_quality == complete",
                       wrapup2["pre_tax"]["data_quality"] == "complete")
            _check("T02.19: effective_tax data_quality == complete",
                   wrapup2["effective_tax"]["data_quality"] == "complete")
            # (9600 + 2400) / 96000 = 12.5%
            _check("T02.20: effective_rate_pct == 12.5",
                   wrapup2["effective_tax"]["effective_rate_pct"] == 12.5,
                   f"got {wrapup2['effective_tax']['effective_rate_pct']}")
            _check("T02.21: validation slot present (None pre-overlay)",
                   "validation" in wrapup2["effective_tax"])

    finally:
        os.unlink(db)


# ── T03: Yearly Wrap-Up Revised (Tax Integration) ────────────────────────────


def test_yearly_wrapup_revised():
    print("\n─── T03: Yearly Wrap-Up Revised ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)

            # Ensure document_drops table exists (matches v14 migration schema)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS document_drops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_name    TEXT NOT NULL,
                    parser_type  TEXT NOT NULL,
                    file_size    INTEGER,
                    dropped_at   TEXT DEFAULT (datetime('now')),
                    committed_at TEXT,
                    summary_json TEXT
                )
            """)
            conn.commit()

            year = 2025

            # Seed transactions
            for m in range(1, 13):
                posting = f"{year}-{m:02d}-15"
                _insert_txn(conn, "test_chk", posting, 5000, "Credit", "Military Pension", desc=f"Pay_{m}")
            _insert_balance_snapshot(conn, "test_inv", 50000, f"{year}-01-10")
            _insert_balance_snapshot(conn, "test_inv", 55000, f"{year}-12-20")
            conn.commit()

            from dal.yearly_wrapup import get_tax_doc_checklist, overlay_tax_documents, get_yearly_wrapup

            # Test 1: All 5 pending on empty DB
            checklist = get_tax_doc_checklist(conn, year)
            _check("T03.1: 5 documents in checklist",
                   len(checklist["documents"]) == 5,
                   f"got {len(checklist['documents'])}")
            _check("T03.2: All pending (not received)",
                   all(not d["received"] for d in checklist["documents"]))
            _check("T03.3: all_received is False", checklist["all_received"] is False)

            # Test 2: Insert one document → received
            conn.execute(
                "INSERT INTO document_drops (file_name, parser_type, summary_json, committed_at) "
                "VALUES (?, ?, ?, datetime('now'))",
                ("dfas_2025.pdf", "dfas_1099r",
                 json.dumps({
                     "tax_year": "2025",
                     "gross_distribution": 62000,
                     "federal_tax_withheld": 8500,
                     "state_tax_withheld": 3200,
                 })),
            )
            conn.commit()

            checklist2 = get_tax_doc_checklist(conn, year)
            dfas_doc = [d for d in checklist2["documents"] if d["parser_type"] == "dfas_1099r"][0]
            _check("T03.4: DFAS doc received", dfas_doc["received"] is True)
            _check("T03.5: all_received still False", checklist2["all_received"] is False)

            # Test 3: Status transitions
            wrapup = get_yearly_wrapup(conn, year)
            _check("T03.6: Status is 'revised' with 1 doc",
                   wrapup["status"] == "revised",
                   f"got {wrapup['status']}")

            # Test 4: Tax override recorded
            _check("T03.7: Tax overrides dict exists",
                   isinstance(wrapup.get("tax_overrides"), dict))
            if wrapup.get("tax_overrides"):
                _check("T03.8: military_pension_gross override recorded",
                       "military_pension_gross" in wrapup["tax_overrides"])

            # ── Phase 9: 1099-R cross-validation hook ─────────────────
            # No payroll data → validation block compares 8500 vs 0
            eff = wrapup.get("effective_tax", {})
            val = eff.get("validation")
            _check("T03.8a: validation block populated post-1099R",
                   val is not None and val.get("source") == "dfas_1099r")
            if val:
                _check("T03.8b: federal_tax_1099r recorded",
                       val.get("federal_tax_1099r") == 8500.0)
                _check("T03.8c: matches=False when payroll empty",
                       val.get("matches") is False)
                _check("T03.8d: delta == 8500 (1099R - 0)",
                       val.get("delta") == 8500.0)

            # Now seed full year of payroll matching the 1099-R and re-run
            for m in range(1, 13):
                # 12 × 708.33 ≈ 8500
                conn.execute(
                    """
                    INSERT INTO payroll_snapshots
                    (pay_period, source, gross_pay, federal_tax, state_tax,
                     sbp_premium, health_insurance, dental_vision,
                     other_deductions, net_pay, raw_json)
                    VALUES (?, 'mypay_ras', 5166.67, 708.33, 266.67, 0, 0, 0, 0, 4191.67, '{}')
                    """,
                    (f"{year}-{m:02d}",),
                )
            conn.commit()
            wrapup_match = get_yearly_wrapup(conn, year)
            val2 = wrapup_match.get("effective_tax", {}).get("validation")
            _check("T03.8e: matches=True when payroll equals 1099-R",
                   val2 is not None and val2.get("matches") is True,
                   f"got delta={val2.get('delta') if val2 else None}")

            # Test 5: Insert all remaining docs → final
            for parser_type, label in [
                ("fidelity_1099", "fid.pdf"),
                ("acorns_1099", "acorns.pdf"),
                ("affirm_1099int", "affirm.pdf"),
                ("nfcu_1098", "nfcu.pdf"),
            ]:
                conn.execute(
                    "INSERT INTO document_drops (file_name, parser_type, summary_json, committed_at) "
                    "VALUES (?, ?, ?, datetime('now'))",
                    (label, parser_type,
                     json.dumps({"tax_year": "2025"})),
                )
            conn.commit()

            wrapup_final = get_yearly_wrapup(conn, year)
            _check("T03.9: Status is 'final' with all 5 docs",
                   wrapup_final["status"] == "final",
                   f"got {wrapup_final['status']}")

            # Test 6: Deep copy safety
            from dal.yearly_wrapup import _build_preliminary
            original = _build_preliminary(conn, year)
            original_income = original["total_income"]
            _ = overlay_tax_documents(conn, year, original)
            _check("T03.10: Original dict not mutated (deep copy safety)",
                   original["total_income"] == original_income)

    finally:
        os.unlink(db)


# ── Main ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    test_lifestyle_creep()
    # test_contributions_vs_performance removed in P13 investments rebuild
    test_monthly_review()
    test_yearly_wrapup_preliminary()
    test_yearly_wrapup_revised()

    print(f"\n{'═' * 60}")
    print(f"  Phase 6 Tests: {_passed} passed, {_failed} failed")
    if _errors:
        print(f"  Failed: {', '.join(_errors)}")
    print(f"{'═' * 60}")
    sys.exit(1 if _failed else 0)
