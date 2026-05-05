"""
Shared SQL fragments for analytical transaction-window queries.

This module centralizes:
1) effective-month attribution expressions/windows, and
2) canonical income/spend predicate fragments.

Callers should compose these fragments with their module-specific filters
instead of hand-building local copies.
"""

from __future__ import annotations

from dal.category_classifications import (
    get_income_exclusion_clause,
    get_spend_exclusion_clause,
)


def effective_month_expr(*, txn_alias: str | None = None) -> str:
    """Return the canonical effective-month SQL expression."""
    prefix = f"{txn_alias}." if txn_alias else ""
    return (
        f"COALESCE({prefix}effective_month, "
        f"strftime('%Y-%m', {prefix}posting_date))"
    )


def effective_month_between_clause(
    *,
    start_date: str,
    end_date: str,
    txn_alias: str | None = None,
) -> tuple[str, list[str]]:
    """Return ``(<expr> BETWEEN ? AND ?, [start_em, end_em])``."""
    expr = effective_month_expr(txn_alias=txn_alias)
    return f"{expr} BETWEEN ? AND ?", [start_date[:7], end_date[:7]]


def canonical_spend_predicate(
    *,
    category_expr: str = "COALESCE(category, 'Uncategorized')",
    signed_amount_expr: str = "signed_amount",
    transfer_tag_expr: str = "transfer_tag",
) -> tuple[str, list[str]]:
    """Return canonical spending predicate SQL + params."""
    placeholders, params = get_spend_exclusion_clause()
    predicate = (
        f"{signed_amount_expr} < 0 "
        f"AND {transfer_tag_expr} IS NULL "
        f"AND {category_expr} NOT IN ({placeholders})"
    )
    return predicate, params


def canonical_income_predicate(
    *,
    category_expr: str = "COALESCE(category, 'Other Income')",
    signed_amount_expr: str = "signed_amount",
    transfer_tag_expr: str = "transfer_tag",
) -> tuple[str, list[str]]:
    """Return canonical income predicate SQL + params."""
    placeholders, params = get_income_exclusion_clause()
    predicate = (
        f"{signed_amount_expr} > 0 "
        f"AND {transfer_tag_expr} IS NULL "
        f"AND {category_expr} NOT IN ({placeholders})"
    )
    return predicate, params
