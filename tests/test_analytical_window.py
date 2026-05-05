"""
Unit tests for ``dal/analytical_window.py``.

The module is a thin SQL-fragment helper composed by analytical callers
(budgets, forecasting, merchant reports). Tests assert on the **shape**
of returned SQL strings + param lists rather than executing against a DB
— integration coverage already lives in the call-site tests (cashflow
invariants, budgets household, attribution, owner scoping).

The contract this file locks down:
- effective-month expression, with and without table alias
- effective-month BETWEEN clause string boundary handling
- canonical spend predicate composition + exclusion params
- canonical income predicate composition + exclusion params
- pluggable column expressions for joined-query callers

Mirrors the style of ``tests/test_owner_scoping.py::test_build_account_filter``.
"""

from __future__ import annotations

import sqlite3

from dal.analytical_window import (
    canonical_income_predicate,
    canonical_spend_predicate,
    effective_month_between_clause,
    effective_month_expr,
)
from dal.category_classifications import (
    get_income_exclusion_clause,
    get_spend_exclusion_clause,
)


# ── effective_month_expr ─────────────────────────────────────────────────────


def test_effective_month_expr_no_alias():
    sql = effective_month_expr()
    assert sql == "COALESCE(effective_month, strftime('%Y-%m', posting_date))"


def test_effective_month_expr_with_alias():
    sql = effective_month_expr(txn_alias="t")
    assert sql == "COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date))"


def test_effective_month_expr_alias_none_equivalent_to_unset():
    assert effective_month_expr(txn_alias=None) == effective_month_expr()


# ── effective_month_between_clause ───────────────────────────────────────────


def test_effective_month_between_clause_truncates_to_yyyy_mm():
    sql, params = effective_month_between_clause(
        start_date="2026-01-15", end_date="2026-12-04"
    )
    assert "BETWEEN ? AND ?" in sql
    assert sql.startswith("COALESCE(effective_month")
    assert params == ["2026-01", "2026-12"]


def test_effective_month_between_clause_single_month_window():
    sql, params = effective_month_between_clause(
        start_date="2026-05-01", end_date="2026-05-31"
    )
    assert params == ["2026-05", "2026-05"], "single-month window collapses to same key"
    assert "BETWEEN ? AND ?" in sql


def test_effective_month_between_clause_with_alias():
    sql, _ = effective_month_between_clause(
        start_date="2026-01-01", end_date="2026-03-31", txn_alias="t"
    )
    assert "t.effective_month" in sql
    assert "t.posting_date" in sql


# ── canonical_spend_predicate ────────────────────────────────────────────────


def test_canonical_spend_predicate_default():
    sql, params = canonical_spend_predicate()
    assert "signed_amount < 0" in sql
    assert "transfer_tag IS NULL" in sql
    assert "COALESCE(category, 'Uncategorized') NOT IN (" in sql
    # params must come from the canonical exclusion clause and have
    # matching placeholder count
    _, expected_params = get_spend_exclusion_clause()
    assert params == expected_params
    assert sql.count("?") == len(params)


def test_canonical_spend_predicate_custom_category_expr():
    """merchant.py uses COALESCE(category, '') — predicate must honor that."""
    sql, _ = canonical_spend_predicate(category_expr="COALESCE(category, '')")
    assert "COALESCE(category, '') NOT IN (" in sql
    assert "Uncategorized" not in sql, (
        "custom category_expr must not leak the default value into the SQL"
    )


def test_canonical_spend_predicate_custom_amount_and_transfer_columns():
    """Joined queries need to alias signed_amount/transfer_tag."""
    sql, _ = canonical_spend_predicate(
        signed_amount_expr="t.signed_amount",
        transfer_tag_expr="t.transfer_tag",
    )
    assert "t.signed_amount < 0" in sql
    assert "t.transfer_tag IS NULL" in sql


# ── canonical_income_predicate ───────────────────────────────────────────────


def test_canonical_income_predicate_default():
    sql, params = canonical_income_predicate()
    assert "signed_amount > 0" in sql
    assert "transfer_tag IS NULL" in sql
    assert "COALESCE(category, 'Other Income') NOT IN (" in sql
    _, expected_params = get_income_exclusion_clause()
    assert params == expected_params
    assert sql.count("?") == len(params)


def test_canonical_income_predicate_excludes_transfers_and_loan_payments():
    """Sanity: the income exclusion list must contain known transfer-y categories.

    Guards against accidental shrinkage of INCOME_EXCL_FROM_INC that would
    leak transfers/loans into income aggregates.
    """
    _, params = canonical_income_predicate()
    param_set = set(params)
    assert "Transfer" in param_set
    assert "Transfers" in param_set
    assert "Credit Card Payments" in param_set
    assert "Loan Payments" in param_set


def test_canonical_income_predicate_custom_category_expr():
    sql, _ = canonical_income_predicate(category_expr="COALESCE(category, '')")
    assert "COALESCE(category, '') NOT IN (" in sql
    assert "Other Income" not in sql


# ── Spend ⊥ Income disjointness sanity ───────────────────────────────────────


def test_spend_and_income_predicates_are_mutually_exclusive_on_sign():
    """A single transaction row cannot satisfy both predicates.

    Spend requires signed_amount < 0; income requires signed_amount > 0.
    """
    spend_sql, _ = canonical_spend_predicate()
    income_sql, _ = canonical_income_predicate()
    assert "signed_amount < 0" in spend_sql
    assert "signed_amount > 0" in income_sql


# ── SQL syntax integration smoke test ────────────────────────────────────────


def test_predicates_are_valid_sqlite_syntax():
    """Compose a real query and let SQLite parse + run it on an empty table.

    Catches accidental syntax errors in the helper output without requiring
    seeded data — schema-light integration check.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY,
            posting_date TEXT,
            effective_month TEXT,
            category TEXT,
            signed_amount INTEGER,
            transfer_tag TEXT,
            status TEXT
        )
        """
    )

    spend_sql, spend_params = canonical_spend_predicate()
    income_sql, income_params = canonical_income_predicate()
    em_expr = effective_month_expr()

    # Spend rollup query
    rows = conn.execute(
        f"SELECT SUM(-signed_amount) AS total FROM transactions WHERE {spend_sql}",
        spend_params,
    ).fetchall()
    assert rows[0]["total" if False else 0] is None  # empty table → NULL sum

    # Income-by-month query
    rows = conn.execute(
        f"SELECT {em_expr} AS m, SUM(signed_amount) FROM transactions "
        f"WHERE {income_sql} GROUP BY m",
        income_params,
    ).fetchall()
    assert rows == []

    # BETWEEN clause query
    between_sql, between_params = effective_month_between_clause(
        start_date="2026-01-01", end_date="2026-12-31"
    )
    rows = conn.execute(
        f"SELECT COUNT(*) FROM transactions WHERE {between_sql}",
        between_params,
    ).fetchall()
    assert rows[0][0] == 0

    conn.close()
