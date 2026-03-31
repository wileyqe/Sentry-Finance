"""
tests/test_attribution.py — Comprehensive tests for income attribution engine.

Tests cover:
  - Core date math (normal, edge, year-rollover, leap year)
  - Rule CRUD operations
  - Attribution application (single + batch)
  - Backfill idempotency
  - Query integration with COALESCE(effective_month, ...)
  - Edge cases: deactivated rules, wrong direction, missing data
"""

import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

class AttributionTestBase(unittest.TestCase):
    """Base class that sets up an ephemeral DB with V19 schema."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def tearDown(self):
        self.conn.close()
        try:
            Path(self.db_path).unlink()
        except Exception:
            pass

    def _create_schema(self):
        """Create minimal schema: transactions + V19 attribution tables."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                account_id TEXT,
                institution_id TEXT,
                posting_date TEXT,
                transaction_date TEXT,
                amount REAL,
                signed_amount REAL,
                direction TEXT DEFAULT 'Debit',
                description TEXT,
                category TEXT,
                status TEXT DEFAULT 'posted',
                transfer_tag TEXT,
                raw_description TEXT,
                institution_txn_id TEXT,
                merchant TEXT,
                created_at TEXT,
                updated_at TEXT,
                refresh_run_id TEXT,
                effective_month TEXT
            );

            CREATE TABLE IF NOT EXISTS income_attribution_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name TEXT NOT NULL,
                match_category TEXT NOT NULL,
                match_direction TEXT DEFAULT 'Credit',
                schedule_type TEXT NOT NULL DEFAULT 'monthly_fixed',
                target_day INTEGER NOT NULL DEFAULT 1,
                lookahead_days INTEGER NOT NULL DEFAULT 5,
                owner TEXT DEFAULT 'self',
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_txn_effective_month
                ON transactions(effective_month);
        """)

    def _insert_txn(self, txn_id, posting_date, category, direction="Credit",
                    amount=3000.0, account_id="acct1"):
        """Helper to insert a test transaction."""
        signed = amount if direction == "Credit" else -amount
        self.conn.execute("""
            INSERT INTO transactions
                (id, account_id, institution_id, posting_date, amount,
                 signed_amount, direction, description, category, status)
            VALUES (?, ?, 'nfcu', ?, ?, ?, ?, 'Test', ?, 'posted')
        """, (txn_id, account_id, posting_date, amount, signed, direction, category))

    def _insert_rule(self, category, target_day=1, lookahead=5, active=1):
        """Insert a test attribution rule."""
        from dal.attribution import create_attribution_rule
        rule_id = create_attribution_rule(
            self.conn,
            rule_name=f"{category} (1st)",
            match_category=category,
            target_day=target_day,
            lookahead_days=lookahead,
        )
        if not active:
            self.conn.execute(
                "UPDATE income_attribution_rules SET is_active = 0 WHERE id = ?",
                (rule_id,),
            )
        return rule_id


# ═════════════════════════════════════════════════════════════════════════════
# 1. Core Date Math
# ═════════════════════════════════════════════════════════════════════════════

class TestComputeEffectiveMonth(unittest.TestCase):
    """Pure date math tests — no DB needed."""

    def test_normal_shift_feb27_to_march(self):
        """Feb 27 with target=1, lookahead=5 → March (2 days before Mar 1)."""
        from dal.attribution import _compute_effective_month
        result = _compute_effective_month(date(2026, 2, 27), target_day=1, lookahead_days=5)
        self.assertEqual(result, "2026-03")

    def test_normal_shift_feb28_to_march(self):
        """Feb 28 → March (1 day before Mar 1)."""
        from dal.attribution import _compute_effective_month
        result = _compute_effective_month(date(2026, 2, 28), target_day=1, lookahead_days=5)
        self.assertEqual(result, "2026-03")

    def test_no_shift_feb22(self):
        """Feb 22 → 7 days before Mar 1 → exceeds lookahead=5 → no shift."""
        from dal.attribution import _compute_effective_month
        result = _compute_effective_month(date(2026, 2, 22), target_day=1, lookahead_days=5)
        self.assertIsNone(result)

    def test_no_shift_feb15(self):
        """Mid-month pension should not be shifted."""
        from dal.attribution import _compute_effective_month
        result = _compute_effective_month(date(2026, 2, 15), target_day=1, lookahead_days=5)
        self.assertIsNone(result)

    def test_on_target_day_no_shift(self):
        """Mar 1 (target day itself): 0 days until NEXT month target → no shift."""
        from dal.attribution import _compute_effective_month
        result = _compute_effective_month(date(2026, 3, 1), target_day=1, lookahead_days=5)
        self.assertIsNone(result)

    def test_year_rollover_dec28_to_jan(self):
        """Dec 28 → Jan 1 of next year (4 days) → '2027-01'."""
        from dal.attribution import _compute_effective_month
        result = _compute_effective_month(date(2026, 12, 28), target_day=1, lookahead_days=5)
        self.assertEqual(result, "2027-01")

    def test_year_rollover_dec30_to_jan(self):
        """Dec 30 → Jan 1 (2 days) → shift to next year."""
        from dal.attribution import _compute_effective_month
        result = _compute_effective_month(date(2026, 12, 30), target_day=1, lookahead_days=5)
        self.assertEqual(result, "2027-01")

    def test_year_rollover_dec25_no_shift(self):
        """Dec 25 → Jan 1 is 7 days → exceeds lookahead=5 → no shift."""
        from dal.attribution import _compute_effective_month
        result = _compute_effective_month(date(2026, 12, 25), target_day=1, lookahead_days=5)
        self.assertIsNone(result)

    def test_leap_year_feb29(self):
        """Feb 29 in a leap year → 1 day before Mar 1 → shift."""
        from dal.attribution import _compute_effective_month
        result = _compute_effective_month(date(2028, 2, 29), target_day=1, lookahead_days=5)
        self.assertEqual(result, "2028-03")

    def test_target_day_15(self):
        """Target day=15, lookahead=3: Jan 13 → 2 days before Jan 15 → Jan."""
        from dal.attribution import _compute_effective_month
        # Jan 13 with target=15 means next_month_target = Feb 15
        # days_until = 33 → exceeds lookahead=3 → no shift
        result = _compute_effective_month(date(2026, 1, 13), target_day=15, lookahead_days=3)
        self.assertIsNone(result)

    def test_exact_lookahead_boundary(self):
        """Exactly on the lookahead boundary (5 days before) → should shift."""
        from dal.attribution import _compute_effective_month
        # Feb 24: Mar 1 is 5 days away → 5 <= 5 → shift
        result = _compute_effective_month(date(2026, 2, 24), target_day=1, lookahead_days=5)
        self.assertEqual(result, "2026-03")

    def test_one_day_past_boundary(self):
        """One day past lookahead boundary → no shift."""
        from dal.attribution import _compute_effective_month
        # Feb 23: Mar 1 is 6 days away → 6 > 5 → no shift
        result = _compute_effective_month(date(2026, 2, 23), target_day=1, lookahead_days=5)
        self.assertIsNone(result)


# ═════════════════════════════════════════════════════════════════════════════
# 2. Rule CRUD
# ═════════════════════════════════════════════════════════════════════════════

class TestRuleCRUD(AttributionTestBase):
    """Test creating, reading, updating, and deleting rules."""

    def test_create_and_list(self):
        from dal.attribution import get_attribution_rules, create_attribution_rule
        create_attribution_rule(self.conn, "Test Rule", "Military Pension")
        rules = get_attribution_rules(self.conn)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["match_category"], "Military Pension")
        self.assertEqual(rules[0]["target_day"], 1)
        self.assertEqual(rules[0]["lookahead_days"], 5)

    def test_delete_rule(self):
        from dal.attribution import get_attribution_rules, create_attribution_rule, delete_attribution_rule
        rid = create_attribution_rule(self.conn, "Test", "VA Benefits")
        self.assertTrue(delete_attribution_rule(self.conn, rid))
        self.assertEqual(len(get_attribution_rules(self.conn)), 0)

    def test_delete_nonexistent(self):
        from dal.attribution import delete_attribution_rule
        self.assertFalse(delete_attribution_rule(self.conn, 9999))

    def test_update_rule(self):
        from dal.attribution import create_attribution_rule, update_attribution_rule, get_attribution_rules
        rid = create_attribution_rule(self.conn, "Test", "Military Pension")
        updated = update_attribution_rule(self.conn, rid, lookahead_days=7)
        self.assertTrue(updated)
        rules = get_attribution_rules(self.conn)
        self.assertEqual(rules[0]["lookahead_days"], 7)

    def test_seed_defaults_idempotent(self):
        from dal.attribution import seed_default_rules
        first = seed_default_rules(self.conn)
        second = seed_default_rules(self.conn)
        self.assertEqual(first, 3)
        self.assertEqual(second, 0)  # Already seeded


# ═════════════════════════════════════════════════════════════════════════════
# 3. Attribution Application
# ═════════════════════════════════════════════════════════════════════════════

class TestApplyAttribution(AttributionTestBase):
    """Test applying attribution rules to transactions."""

    def test_single_attribution_stamps(self):
        """A pension posting Feb 27 should be stamped to March."""
        from dal.attribution import apply_attribution_single
        self._insert_rule("Military Pension")
        self._insert_txn("txn1", "2026-02-27", "Military Pension", "Credit")
        result = apply_attribution_single(
            self.conn, "txn1", "Military Pension", "2026-02-27", "Credit"
        )
        self.assertEqual(result, "2026-03")
        row = self.conn.execute("SELECT effective_month FROM transactions WHERE id = 'txn1'").fetchone()
        self.assertEqual(row["effective_month"], "2026-03")

    def test_single_no_match(self):
        """A grocery debit should NOT be attributed."""
        from dal.attribution import apply_attribution_single
        self._insert_rule("Military Pension")
        self._insert_txn("txn2", "2026-02-27", "Groceries", "Debit")
        result = apply_attribution_single(
            self.conn, "txn2", "Groceries", "2026-02-27", "Debit"
        )
        self.assertIsNone(result)

    def test_single_wrong_direction_skipped(self):
        """A debit with pension category should NOT be attributed (direction mismatch)."""
        from dal.attribution import apply_attribution_single
        self._insert_rule("Military Pension")
        self._insert_txn("txn3", "2026-02-27", "Military Pension", "Debit")
        result = apply_attribution_single(
            self.conn, "txn3", "Military Pension", "2026-02-27", "Debit"
        )
        self.assertIsNone(result)

    def test_batch_attribution(self):
        """Batch attribution stamps multiple matching transactions."""
        from dal.attribution import apply_attribution
        self._insert_rule("Military Pension")
        self._insert_rule("VA Benefits")
        self._insert_txn("txn_p", "2026-02-27", "Military Pension", "Credit")
        self._insert_txn("txn_v", "2026-02-28", "VA Benefits", "Credit")
        self._insert_txn("txn_g", "2026-02-15", "Groceries", "Debit")
        stats = apply_attribution(self.conn)
        self.assertEqual(stats["attributed"], 2)

    def test_inactive_rule_ignored(self):
        """An inactive rule should not match."""
        from dal.attribution import apply_attribution
        self._insert_rule("Military Pension", active=0)
        self._insert_txn("txn1", "2026-02-27", "Military Pension", "Credit")
        stats = apply_attribution(self.conn)
        self.assertEqual(stats["attributed"], 0)


# ═════════════════════════════════════════════════════════════════════════════
# 4. Backfill
# ═════════════════════════════════════════════════════════════════════════════

class TestBackfill(AttributionTestBase):
    """Test backfill idempotency and correctness."""

    def test_backfill_stamps_historical(self):
        """Backfill should stamp all historical matching transactions."""
        from dal.attribution import backfill_attribution
        self._insert_rule("Military Pension")
        # 3 pensions across 3 months, all posting on the 27th-28th
        self._insert_txn("jan_p", "2025-12-28", "Military Pension", "Credit")
        self._insert_txn("feb_p", "2026-01-28", "Military Pension", "Credit")
        self._insert_txn("mar_p", "2026-02-27", "Military Pension", "Credit")
        stats = backfill_attribution(self.conn)
        self.assertEqual(stats["attributed"], 3)
        # Check the months
        for txn_id, expected in [("jan_p", "2026-01"), ("feb_p", "2026-02"), ("mar_p", "2026-03")]:
            row = self.conn.execute("SELECT effective_month FROM transactions WHERE id = ?", (txn_id,)).fetchone()
            self.assertEqual(row["effective_month"], expected, f"Bad month for {txn_id}")

    def test_backfill_idempotent(self):
        """Running backfill twice should produce the same results."""
        from dal.attribution import backfill_attribution
        self._insert_rule("Military Pension")
        self._insert_txn("txn1", "2026-02-27", "Military Pension", "Credit")
        stats1 = backfill_attribution(self.conn)
        stats2 = backfill_attribution(self.conn)
        self.assertEqual(stats1["attributed"], 1)
        self.assertEqual(stats2["attributed"], 1)  # Same stamp, same count
        # Value should still be the same
        row = self.conn.execute("SELECT effective_month FROM transactions WHERE id = 'txn1'").fetchone()
        self.assertEqual(row["effective_month"], "2026-03")

    def test_backfill_clears_no_longer_matching(self):
        """A transaction that was attributed but no longer falls in lookahead gets cleared."""
        from dal.attribution import backfill_attribution
        self._insert_rule("Military Pension")
        # Feb 10: 19 days before Mar 1 → NOT in lookahead → should be cleared
        self._insert_txn("txn_mid", "2026-02-10", "Military Pension", "Credit")
        # Manually stamp it first
        self.conn.execute("UPDATE transactions SET effective_month = '2026-03' WHERE id = 'txn_mid'")
        stats = backfill_attribution(self.conn)
        self.assertEqual(stats["cleared"], 1)
        row = self.conn.execute("SELECT effective_month FROM transactions WHERE id = 'txn_mid'").fetchone()
        self.assertIsNone(row["effective_month"])


# ═════════════════════════════════════════════════════════════════════════════
# 5. Query Integration — COALESCE pattern
# ═════════════════════════════════════════════════════════════════════════════

class TestQueryIntegration(AttributionTestBase):
    """Test that COALESCE(effective_month, strftime(...)) groups correctly."""

    def _setup_schema_extras(self):
        """Add additional tables needed for cash flow queries."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                institution_id TEXT,
                name TEXT,
                type TEXT DEFAULT 'checking',
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS balance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT,
                balance REAL,
                as_of TEXT
            );
        """)
        self.conn.execute(
            "INSERT INTO accounts (id, institution_id, name, type) VALUES ('acct1', 'nfcu', 'Checking', 'checking')"
        )

    def test_month_grouping_with_effective_month(self):
        """Transactions with effective_month should group by that month, not posting_date month."""
        # Insert a Feb-posted transaction stamped to March
        self._insert_txn("txn_pension", "2026-02-27", "Military Pension", "Credit", 3000)
        self.conn.execute(
            "UPDATE transactions SET effective_month = '2026-03' WHERE id = 'txn_pension'"
        )
        # Insert a normal March expense
        self._insert_txn("txn_rent", "2026-03-05", "Housing", "Debit", 1500)

        # Query with COALESCE pattern — pension should appear in March
        _EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"
        rows = self.conn.execute(f"""
            SELECT {_EM} as month,
                   SUM(CASE WHEN direction = 'Credit' THEN signed_amount ELSE 0 END) as income,
                   SUM(CASE WHEN direction = 'Debit' THEN -signed_amount ELSE 0 END) as spending
            FROM transactions
            WHERE status = 'posted'
            GROUP BY month
            ORDER BY month
        """).fetchall()

        results = {r["month"]: r for r in rows}
        # February should have $0 income (pension shifted away)
        self.assertNotIn("2026-02", results)
        # March should have $3000 income (pension + rent)
        self.assertIn("2026-03", results)
        self.assertEqual(results["2026-03"]["income"], 3000)
        self.assertEqual(results["2026-03"]["spending"], 1500)

    def test_null_effective_month_uses_posting_date(self):
        """Transactions without effective_month should group by posting_date month."""
        self._insert_txn("txn_normal", "2026-04-15", "Groceries", "Debit", 200)
        _EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"
        rows = self.conn.execute(f"""
            SELECT {_EM} as month FROM transactions WHERE id = 'txn_normal'
        """).fetchall()
        self.assertEqual(rows[0]["month"], "2026-04")


# ═════════════════════════════════════════════════════════════════════════════
# 6. Edge Cases
# ═════════════════════════════════════════════════════════════════════════════

class TestEdgeCases(AttributionTestBase):
    """Edge cases for robustness."""

    def test_no_rules_does_nothing(self):
        """With no rules, attribution should be a no-op."""
        from dal.attribution import apply_attribution
        self._insert_txn("txn1", "2026-02-27", "Military Pension", "Credit")
        stats = apply_attribution(self.conn)
        self.assertEqual(stats["attributed"], 0)
        self.assertEqual(stats["rules_matched"], 0)

    def test_deleted_status_skipped(self):
        """Soft-deleted transactions should not be attributed."""
        from dal.attribution import apply_attribution
        self._insert_rule("Military Pension")
        self._insert_txn("txn_del", "2026-02-27", "Military Pension", "Credit")
        self.conn.execute("UPDATE transactions SET status = 'deleted' WHERE id = 'txn_del'")
        stats = apply_attribution(self.conn)
        self.assertEqual(stats["attributed"], 0)

    def test_invalid_date_format(self):
        """Invalid posting_date formats should be handled gracefully."""
        from dal.attribution import apply_attribution_single
        self._insert_rule("Military Pension")
        result = apply_attribution_single(
            self.conn, "txn_bad", "Military Pension", "not-a-date", "Credit"
        )
        self.assertIsNone(result)

    def test_multiple_rules_different_categories(self):
        """Multiple rules matching different categories work independently."""
        from dal.attribution import backfill_attribution
        self._insert_rule("Military Pension")
        self._insert_rule("VA Benefits")
        self._insert_txn("p1", "2026-02-27", "Military Pension", "Credit", 2500)
        self._insert_txn("v1", "2026-02-28", "VA Benefits", "Credit", 1800)
        self._insert_txn("g1", "2026-02-27", "Groceries", "Debit", 400)
        stats = backfill_attribution(self.conn)
        self.assertEqual(stats["attributed"], 2)  # pension + VA
        # Grocery should have NULL effective_month
        row = self.conn.execute("SELECT effective_month FROM transactions WHERE id = 'g1'").fetchone()
        self.assertIsNone(row["effective_month"])

    def test_specific_transaction_ids_filter(self):
        """apply_attribution with specific IDs only processes those."""
        from dal.attribution import apply_attribution
        self._insert_rule("Military Pension")
        self._insert_txn("txn_a", "2026-02-27", "Military Pension", "Credit")
        self._insert_txn("txn_b", "2026-02-28", "Military Pension", "Credit")
        stats = apply_attribution(self.conn, transaction_ids=["txn_a"])
        self.assertEqual(stats["attributed"], 1)
        # txn_b should NOT have been attributed
        row = self.conn.execute("SELECT effective_month FROM transactions WHERE id = 'txn_b'").fetchone()
        self.assertIsNone(row["effective_month"])


# ═════════════════════════════════════════════════════════════════════════════
# Run
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Pretty output format
    print("=" * 60)
    print("  Income Attribution Test Suite")
    print("=" * 60)

    passed = 0
    failed = 0
    errors = []

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__))

    for test_group in suite:
        for test in test_group:
            test_name = str(test).split(" ")[0]
            try:
                test.debug()
                print(f"  ✔  {test_name}")
                passed += 1
            except Exception as e:
                print(f"  ✘  {test_name}: {e}")
                failed += 1
                errors.append((test_name, e))

    print()
    print("=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed:
        print("\nFailures:")
        for name, err in errors:
            print(f"  - {name}: {err}")
        exit(1)
