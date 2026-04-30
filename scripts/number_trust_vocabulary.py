"""Generated vocabulary source for the number-trust audit oracle."""

from __future__ import annotations

from typing import Any

from dal.category_classifications import (
    ALL_EXCL_FROM_SPEND,
    EXCLUDED_FROM_SPEND,
    INCOME_CATEGORIES,
    INCOME_EXCL_FROM_INC,
)


CASH_ACCOUNT_TYPES: frozenset[str] = frozenset({
    "checking",
    "savings",
    "money_market",
})

LIABILITY_TYPES: frozenset[str] = frozenset({
    "credit_card",
    "credit",
    "loan",
    "mortgage",
    "bnpl",
})

CASHOUT_SPEND_EXCLUDE: frozenset[str] = INCOME_CATEGORIES | frozenset({
    "Transfers",
    "Transfer",
    "Refunds/Adjustments",
    "Mortgages",
    "Mortgage",
})

DEBT_CASH_CATEGORIES: frozenset[str] = frozenset({
    "Loan Payments",
    "Loan Payment",
    "Auto Loan",
    "Student Loan",
    "Credit Card Payments",
    "BNPL Payments",
})

DEBT_ACCUMULATED_EXCLUDE: frozenset[str] = frozenset({
    "Refunds/Adjustments",
    "Transfers",
    "Transfer",
    "Credit Card Payments",
    "Loan Payments",
    "Mortgages",
    "Auto Loan",
    "Student Loan",
})


def _sorted_values(values: frozenset[str]) -> list[str]:
    return sorted(values)


def build_oracle_vocabulary() -> dict[str, Any]:
    """Return the committed neutral vocabulary payload for the audit oracle."""
    return {
        "version": 1,
        "cash_account_types": _sorted_values(CASH_ACCOUNT_TYPES),
        "liability_types": _sorted_values(LIABILITY_TYPES),
        "income_categories": _sorted_values(INCOME_CATEGORIES),
        "all_excl_from_spend": _sorted_values(ALL_EXCL_FROM_SPEND),
        "excluded_from_spend": _sorted_values(EXCLUDED_FROM_SPEND),
        "income_excl_from_inc": _sorted_values(INCOME_EXCL_FROM_INC),
        "cashout_spend_exclude": _sorted_values(CASHOUT_SPEND_EXCLUDE),
        "debt_cash_categories": _sorted_values(DEBT_CASH_CATEGORIES),
        "debt_accumulated_exclude": _sorted_values(DEBT_ACCUMULATED_EXCLUDE),
    }
