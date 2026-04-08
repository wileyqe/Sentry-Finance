"""
dal/category_classifications.py — Single source of truth for category sets.

Every module in the DAL that needs to classify transactions as income, spending,
transfers, or exclusions MUST import from here.  Do NOT define local copies.

This file has ZERO imports from other DAL modules to avoid circular dependencies.
"""

import calendar

# ── Income Categories ────────────────────────────────────────────────────────
# Transactions in these categories with signed_amount > 0 count as income.

INCOME_CATEGORIES: frozenset[str] = frozenset({
    "Income",
    "Paychecks/Salary",
    "Rental Income",
    "Deposits",
    "Interest",
    "Investment Income",
    "Retirement Income",
    "Tax Refund",
    "Other Income",
    "Military Pension",
    "VA Benefits",
    "VA Education Benefits",
    "Officiating Income",
    "Non-Recurring Income",
})

# ── Excluded from Spending ───────────────────────────────────────────────────
# Not real spending — transfers, debt service payments, refunds.
# These should never appear on the "spending" side of reports.

EXCLUDED_FROM_SPEND: frozenset[str] = frozenset({
    "Transfers",
    "Transfer",
    "Credit Card Payments",
    "Refunds/Adjustments",
    "Mortgage",
    "Mortgages",
    "Auto Loan",
    "Loan Payments",
    "Loan Payment",
    "Student Loan",
})

# ── Derived Unions ───────────────────────────────────────────────────────────

# Everything that should be excluded from the spending side of a report.
ALL_EXCL_FROM_SPEND: frozenset[str] = EXCLUDED_FROM_SPEND | INCOME_CATEGORIES

# Categories that should NEVER appear as income even when signed_amount > 0.
# This set covers exactly two concerns:
#   1. Transfers and debt service (from EXCLUDED_FROM_SPEND) — these movements
#      of money between accounts or toward liabilities are not income.
#   2. Common spending categories — a positive amount in one of these is
#      almost always a refund, return, or chargeback and should be excluded
#      from the income total so refunds don't inflate income.
#
# NOTE: "Deposits" is intentionally NOT in this set. It belongs to
# INCOME_CATEGORIES as an income catch-all (direct bank deposits, ACH credits,
# etc.). Including it here would create a whitelist/blacklist contradiction
# and make Deposits income disappear from drill-down views.
#
# Both abstract category names (e.g. "Dining") AND the real category names
# emitted by the live categorizer (e.g. "Restaurants/Dining") are listed.
# A literal mismatch here is silent — refunds in the missing category
# would inflate income on every page that uses the canonical pattern.
INCOME_EXCL_FROM_INC: frozenset[str] = EXCLUDED_FROM_SPEND | frozenset({
    # Abstract / legacy aliases
    "Groceries",
    "Dining",
    "Shopping",
    "Entertainment",
    "Travel",
    "Utilities",
    "Auto",
    "Medical",
    "Insurance",
    "Home Improvement",
    # Real category names emitted by dal/categorization.py and the seeder
    "Restaurants/Dining",
    "General Merchandise",
    "Telephone Services",
    "Dues and Subscriptions",
    "Healthcare",
    "Personal Care",
    "Education",
    "Childcare",
    "Pets",
    "Gifts",
    "Cash & ATM",
    "Fees",
    "Taxes",
    "Rent",
})

# ── Transfer Detection ───────────────────────────────────────────────────────
# Categories that are almost always inter-account transfers.

TRANSFER_CATEGORIES: frozenset[str] = frozenset({
    "Transfers",
    "Transfer",
    "Credit Card Payments",
    "Savings",
})

# ── Loan Categories ──────────────────────────────────────────────────────────
# For linking recurring payments to loan accounts.

LOAN_CATEGORIES: frozenset[str] = frozenset({
    "Mortgage",
    "Mortgages",
    "Auto Loan",
    "Student Loan",
    "Credit Card Payments",
    "Loan Payment",
    "Loan Payments",
})

# ── Lifestyle Creep Exclusions ───────────────────────────────────────────────
# Non-discretionary categories that should not be flagged as lifestyle creep.

EXCLUDED_FROM_CREEP: frozenset[str] = frozenset({
    "Mortgage",
    "Mortgages",
    "Rent",
    "Auto Loan",
    "Loan Payments",
    "Loan Payment",
    "Student Loan",
    "Utilities",
    "Health Insurance",
    "Insurance",
    "Transfers",
    "Transfer",
    "Credit Card Payments",
    "Tax Refund",
    "Non-Recurring Income",
})

# ── Forecasting Exclusions ───────────────────────────────────────────────────
# Categories excluded from spending forecasts (not real expenditures).

EXCLUDED_FROM_FORECAST: frozenset[str] = frozenset({
    "Transfers",
    "Transfer",
    "Credit Card Payments",
    "Deposits",
    "Tax Refund",
    "Refunds/Adjustments",
    "Loan Payments",
    "Loan Payment",
    "Mortgage",
    "Mortgages",
    "Auto Loan",
    "Student Loan",
})

# Income categories that should NOT influence the projected income model.
# These are real, correctly-categorized — but not predictably recurring.
NON_PROJECTION_INCOME: frozenset[str] = frozenset({
    "Tax Refund",
    "Non-Recurring Income",
})


# ── Shared Calculation Utilities ─────────────────────────────────────────────


def savings_rate(income: float, spending: float) -> float:
    """Compute savings rate as a percentage.

    Returns 0.0 when income is zero or negative.
    """
    if income <= 0:
        return 0.0
    return round((income - spending) / income * 100, 1)


def pre_tax_savings_rate(
    gross_income: float,
    tax_withheld: float,
    spending: float,
) -> float:
    """Compute savings rate against gross (pre-tax) income.

    Formula: (gross_income - tax_withheld - spending) / gross_income × 100.

    This is the "truer" savings rate for retirees whose gross pension is
    eroded by federal/state withholding before it ever lands in checking.
    The standard `savings_rate()` operates on net income and therefore
    overstates the rate when withholding is high.

    Returns 0.0 when gross_income is zero or negative.
    """
    if gross_income <= 0:
        return 0.0
    return round((gross_income - tax_withheld - spending) / gross_income * 100, 1)


def month_range(year: int, month: int) -> tuple[str, str]:
    """Return (first_day, last_day) as 'YYYY-MM-DD' strings for a given month."""
    last_day = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"


def prev_month(year: int, month: int) -> tuple[int, int]:
    """Return (year, month) for the previous month.  Handles Jan → Dec rollover."""
    if month == 1:
        return year - 1, 12
    return year, month - 1
