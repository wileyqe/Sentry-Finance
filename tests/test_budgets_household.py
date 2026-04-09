"""
tests/test_budgets_household.py — Regression suite for the household-only
budget contract (V23 migration + dal/budgets.py rewrite).

These tests assert that:

  * The V23 migration deduplicates rows that share (category, month)
    and backfills every remaining row's owner_id to NULL.
  * `get_budget` returns DB rows when present and only falls back to
    YAML defaults when the month is empty.
  * `set_budget_target` upserts a single household row (UPDATE-then-
    INSERT pattern, no UNIQUE constraint violation on repeated calls).
  * `initialize_month` is idempotent.
  * `get_budget_vs_actual` returns household actuals — the sum of
    every owner's spending in the month, regardless of any per-owner
    state on accounts.
  * `delete_budget` removes the household row and the YAML fallback
    becomes active again.
  * The V23 partial unique index prevents direct duplicate inserts of
    household rows.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db  # noqa: E402
from dal.budgets import (  # noqa: E402
    delete_budget,
    get_budget,
    get_budget_summary,
    get_budget_vs_actual,
    initialize_month,
    set_budget_target,
)


def _temp_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


@pytest.fixture
def db():
    """Fresh, fully-migrated DB for each test. Cleaned up after."""
    path = _temp_db()
    init_db(path)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


# ── Migration backfill ───────────────────────────────────────────────────────


def test_v23_migration_backfill_and_dedupe():
    """V23 should dedupe by (category, month) and NULL out owner_id."""
    path = _temp_db()
    try:
        # Bootstrap with the schema BEFORE V23. We do this by running
        # the full migrator (which is harmless — V23 is idempotent on a
        # post-V23 db) and then manually re-inserting per-owner rows
        # the way P12-T01 used to.
        init_db(path)

        with get_db(path) as conn:
            # Wipe and seed with the OLD per-owner shape, including a
            # duplicate row that V23 should dedupe.
            conn.execute("DELETE FROM budgets")
            # Owners must exist for the FK on budgets.owner_id.
            conn.execute(
                "INSERT OR IGNORE INTO owners (id, display_name) VALUES ('quintin', 'Quintin')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO owners (id, display_name) VALUES ('amy', 'Amy')"
            )
            conn.execute(
                "INSERT INTO budgets (category, month, target_amount, owner_id) "
                "VALUES ('Groceries', '2026-04', 500, 'quintin')"
            )
            conn.execute(
                "INSERT INTO budgets (category, month, target_amount, owner_id) "
                "VALUES ('Groceries', '2026-04', 700, 'amy')"  # duplicate (cat, mo)
            )
            conn.execute(
                "INSERT INTO budgets (category, month, target_amount, owner_id) "
                "VALUES ('Auto', '2026-04', 250, 'quintin')"
            )
            conn.commit()

            # Re-run the V23 migration manually so we can verify its
            # effects regardless of where the schema version is. The
            # migration is idempotent so calling run() directly is safe.
            from dal.migrations.v23_budgets_household_only import run as v23_run
            v23_run(conn)
            conn.commit()

            # All remaining rows have owner_id IS NULL.
            distinct_owners = [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT owner_id FROM budgets"
                ).fetchall()
            ]
            assert distinct_owners == [None], (
                f"expected only NULL owners, got {distinct_owners}"
            )

            # Dedupe ran: only one row per (category, month).
            rows = conn.execute(
                "SELECT category, month, COUNT(*) "
                "FROM budgets GROUP BY category, month"
            ).fetchall()
            for cat, month, count in rows:
                assert count == 1, (
                    f"{cat}/{month} should have 1 row, got {count}"
                )

            # The partial unique index exists.
            idx = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_budgets_household_unique'"
            ).fetchone()
            assert idx is not None, "partial unique index missing after V23"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ── get_budget() — DB rows vs YAML fallback ──────────────────────────────────


def test_get_budget_returns_db_rows_when_month_has_data(db):
    """When DB rows exist for a month, the YAML fallback must NOT fire."""
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO budgets (category, month, target_amount, owner_id) "
            "VALUES ('Groceries', '2026-04', 600, NULL)"
        )
        conn.commit()

        result = get_budget(conn, "2026-04")

        assert len(result) == 1, f"expected 1 row, got {len(result)}"
        row = result[0]
        assert row["category"] == "Groceries"
        assert row["target_amount"] == 600
        assert row.get("owner_id") is None
        # Critically: no is_default flag — these are real DB rows.
        assert "is_default" not in row or row["is_default"] is False, (
            "DB rows must not be flagged as defaults"
        )


def test_get_budget_falls_back_to_yaml_when_month_empty(db):
    """An empty month should yield the YAML defaults flagged is_default=True."""
    with get_db(db) as conn:
        result = get_budget(conn, "2026-04")

        assert len(result) > 0, "YAML should provide defaults"
        for row in result:
            assert row.get("is_default") is True, (
                f"{row['category']} should be flagged as default"
            )
            assert row.get("owner_id") is None


# ── set_budget_target() — household upsert ───────────────────────────────────


def test_set_budget_target_upserts_single_row(db):
    """Calling set_budget_target twice for the same (cat, month) should
    leave exactly one row, with the second amount."""
    with get_db(db) as conn:
        set_budget_target(conn, "Groceries", "2026-04", 500)
        conn.commit()
        set_budget_target(conn, "Groceries", "2026-04", 750)
        conn.commit()

        rows = conn.execute(
            "SELECT target_amount, owner_id FROM budgets "
            "WHERE category = ? AND month = ?",
            ("Groceries", "2026-04"),
        ).fetchall()

        assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
        assert rows[0]["target_amount"] == 750
        assert rows[0]["owner_id"] is None


def test_set_budget_target_handles_many_repeated_writes(db):
    """Stress the UPDATE-then-INSERT path to confirm no UNIQUE violations."""
    with get_db(db) as conn:
        for i in range(10):
            set_budget_target(conn, "Auto", "2026-04", 100 + i * 25)
            conn.commit()

        rows = conn.execute(
            "SELECT target_amount FROM budgets "
            "WHERE category = ? AND month = ?",
            ("Auto", "2026-04"),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["target_amount"] == 325  # 100 + 9*25


# ── initialize_month() — idempotency ─────────────────────────────────────────


def test_initialize_month_is_idempotent(db):
    """Calling initialize_month twice should not duplicate rows."""
    with get_db(db) as conn:
        first = initialize_month(conn, "2026-05")
        conn.commit()
        second = initialize_month(conn, "2026-05")
        conn.commit()

        assert first > 0, "first call should create entries"
        assert second == 0, f"second call should be a no-op, got {second}"

        rows = conn.execute(
            "SELECT category, COUNT(*) FROM budgets "
            "WHERE month = ? GROUP BY category",
            ("2026-05",),
        ).fetchall()
        for cat, count in rows:
            assert count == 1, f"{cat} should have 1 row, got {count}"


# ── get_budget_vs_actual() — household actuals ───────────────────────────────


def test_get_budget_vs_actual_sums_actuals_across_owners(db):
    """Two accounts owned by different people, both spending in the same
    category and month, should both contribute to the household actuals."""
    with get_db(db) as conn:
        # Owners
        conn.execute(
            "INSERT INTO owners (id, display_name) VALUES ('quintin', 'Quintin')"
        )
        conn.execute(
            "INSERT INTO owners (id, display_name) VALUES ('amy', 'Amy')"
        )

        # Two accounts on the same institution, one per owner
        conn.execute(
            "INSERT INTO institutions (id, display_name) VALUES ('bank', 'Bank')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, type, last4, owner_id) "
            "VALUES ('acct_q', 'bank', 'Quintin Checking', 'checking', '1111', 'quintin')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, type, last4, owner_id) "
            "VALUES ('acct_a', 'bank', 'Amy Checking', 'checking', '2222', 'amy')"
        )

        # Spending: $200 from Quintin's account, $300 from Amy's account,
        # both posted to Groceries in 2026-04.
        conn.execute(
            "INSERT INTO transactions (id, account_id, institution_id, "
            "posting_date, amount, signed_amount, direction, description, "
            "category, status) VALUES "
            "('tx_q', 'acct_q', 'bank', '2026-04-05', 200, -200, 'Debit', "
            "'KROGER', 'Groceries', 'posted')"
        )
        conn.execute(
            "INSERT INTO transactions (id, account_id, institution_id, "
            "posting_date, amount, signed_amount, direction, description, "
            "category, status) VALUES "
            "('tx_a', 'acct_a', 'bank', '2026-04-12', 300, -300, 'Debit', "
            "'WHOLE FOODS', 'Groceries', 'posted')"
        )

        # Set a household budget for Groceries
        set_budget_target(conn, "Groceries", "2026-04", 600)
        conn.commit()

        bva = get_budget_vs_actual(conn, "2026-04")
        groceries = next((r for r in bva if r["category"] == "Groceries"), None)
        assert groceries is not None, "Groceries row missing"
        assert groceries["actual"] == 500, (
            f"household actual should be 200+300=500, got {groceries['actual']}"
        )
        assert groceries["target"] == 600


def test_get_budget_summary_uses_household_actuals(db):
    """Sanity: the summary aggregator inherits the household-actual fix."""
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO institutions (id, display_name) VALUES ('bank', 'Bank')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, type, last4) "
            "VALUES ('acct1', 'bank', 'Acct', 'checking', '1111')"
        )
        conn.execute(
            "INSERT INTO transactions (id, account_id, institution_id, "
            "posting_date, amount, signed_amount, direction, description, "
            "category, status) VALUES "
            "('tx1', 'acct1', 'bank', '2026-04-05', 150, -150, 'Debit', "
            "'STORE', 'Groceries', 'posted')"
        )
        set_budget_target(conn, "Groceries", "2026-04", 500)
        conn.commit()

        summary = get_budget_summary(conn, "2026-04")
        assert summary["month"] == "2026-04"
        assert summary["total_spent"] == 150
        assert summary["total_budget"] >= 500


# ── delete_budget() ──────────────────────────────────────────────────────────


def test_delete_budget_restores_yaml_fallback(db):
    """After deleting the only DB row for a month, get_budget should
    return YAML defaults again."""
    with get_db(db) as conn:
        set_budget_target(conn, "Groceries", "2026-04", 500)
        conn.commit()

        before = get_budget(conn, "2026-04")
        assert any(
            r["category"] == "Groceries" and r["target_amount"] == 500
            for r in before
        )
        # Single DB row → no YAML fallback
        assert all(not r.get("is_default") for r in before)

        delete_budget(conn, "Groceries", "2026-04")
        conn.commit()

        after = get_budget(conn, "2026-04")
        # The month is now empty → YAML fallback fires.
        assert len(after) > 0
        assert all(r.get("is_default") is True for r in after)


# ── Partial unique index defense ─────────────────────────────────────────────


def test_partial_unique_index_blocks_duplicate_household_rows(db):
    """The V23 partial unique index should reject a second direct
    INSERT for the same (category, month) when owner_id IS NULL."""
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO budgets (category, month, target_amount, owner_id) "
            "VALUES ('Groceries', '2026-04', 500, NULL)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO budgets (category, month, target_amount, owner_id) "
                "VALUES ('Groceries', '2026-04', 700, NULL)"
            )
