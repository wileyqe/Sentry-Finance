"""
dal/category_classifications.py — Single source of truth for category sets.

Every module in the DAL that needs to classify transactions as income, spending,
transfers, or exclusions MUST import from here.  Do NOT define local copies.

This file has ZERO imports from other DAL modules to avoid circular dependencies.
"""

import calendar

# ── Income Categories ────────────────────────────────────────────────────────
# Transactions in these categories with signed_amount > 0 count as income.
#
# Synthetic-mode coverage gap (AI-011, see events.yaml > synthetic_gaps):
# the seeder emits transactions for only 5 of these (Paychecks/Salary,
# Interest, Investment Income, Retirement Income via TSP, and Deposits
# implicit). The other 9 — Officiating, Military Pension, VA Benefits,
# VA Education Benefits, Tax Refund, Non-Recurring Income, Other Income,
# Rental Income, and "Income" — have classifier rules and exclusion-set
# memberships that are dead code in synthetic mode. Live ingestion is
# expected to exercise the rest; document-drop / connector test fixtures
# may want to include each one to round-trip the income side end-to-end.
#
# Canonical category for CC rewards redemptions (AI-004 closed
# 2026-04-27): a cashback / points-redemption row classifies as
# 'Other Income' — counted on the Sankey income side, but excluded
# from projected-income forecasts via NON_PROJECTION_INCOME (so a
# one-off windfall doesn't inflate the forward model). When a real
# rewards-redemption parser is written, it must remap any
# bank-specific label ('Cashback Redemption', 'Refunds/Adjustments',
# etc.) to 'Other Income' on commit.

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
# Open product question (AI-002): there's no UI affordance today to mark a
# specific Deposits row as a *redeposit* (e.g. selling something offline and
# returning the cash to checking) and exclude it from the income side. If
# such an affordance ever lands, prefer per-transaction exclusion (a flag /
# transfer_tag-style marker) over moving the whole "Deposits" category here,
# because most "Deposits" rows are genuine income.
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

# ── Subscription vs Utility Decision Rule ────────────────────────────────────
# Household decision rule (P17-T24):
#   • UTILITY-like services CANNOT generally be turned off without disrupting
#     daily life. They are basic household infrastructure: electricity, water,
#     gas, internet, and phone/cell service. Treat them as non-discretionary
#     for lifestyle-creep flagging — a 5% YoY rise in the power bill is mostly
#     rate inflation, not a behavior change.
#   • OPTIONAL-SUBSCRIPTION services can generally be turned off. Streaming,
#     music, audiobooks, Prime, Patreon, gym memberships, optional apps —
#     these REMAIN eligible for lifestyle-creep flags so the household can
#     review trim candidates.
#
# Why both sets are explicit (not just one):
#   Future authors editing keyword rules in `config/categories.yaml` need to
#   answer "is this category utility-like or subscription-like?" without
#   re-deriving the rule. Each canonical category that touches the boundary
#   must appear in exactly one of these sets.
#
# How to apply:
#   - When a new utility-like category is added (e.g. a hypothetical
#     "Internet Services" split-out), add it to UTILITY_LIKE_CATEGORIES and
#     EXCLUDED_FROM_CREEP. The regression in tests/test_subscription_utility_boundary.py
#     enforces that linkage.
#   - When a new optional-subscription category is added, add it to
#     OPTIONAL_SUBSCRIPTION_CATEGORIES and DO NOT add it to EXCLUDED_FROM_CREEP.
#   - Do not blanket-add `Dues and Subscriptions` to creep exclusions — that
#     defeats the lifestyle-creep review the user explicitly wants on those.

UTILITY_LIKE_CATEGORIES: frozenset[str] = frozenset({
    "Utilities",          # power, water, natural gas
    "Telephone Services", # internet, landline, cell — turning these off breaks
                          # remote work, banking 2FA, school comms
})

OPTIONAL_SUBSCRIPTION_CATEGORIES: frozenset[str] = frozenset({
    "Dues and Subscriptions",  # streaming, music, Prime, gym, Patreon, etc.
})


# ── Lifestyle Creep Exclusions ───────────────────────────────────────────────
# Non-discretionary categories that should not be flagged as lifestyle creep.
# UTILITY_LIKE_CATEGORIES are unioned in to keep the utility/subscription
# boundary above as the single source of truth.

EXCLUDED_FROM_CREEP: frozenset[str] = UTILITY_LIKE_CATEGORIES | frozenset({
    "Mortgage",
    "Mortgages",
    "Rent",
    "Auto Loan",
    "Loan Payments",
    "Loan Payment",
    "Student Loan",
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
# "Other Income" is the catch-all bucket for bonuses, gifts, and unclassified
# credits; treating it as projection-eligible would inflate the forecast.
NON_PROJECTION_INCOME: frozenset[str] = frozenset({
    "Tax Refund",
    "Non-Recurring Income",
    "Other Income",
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


def get_spend_exclusion_clause() -> tuple[str, list[str]]:
    """Return ``(placeholder_string, params)`` for the canonical spending-exclusion NOT IN clause.

    Callers splice ``placeholder_string`` into ``COALESCE(category,'Uncategorized')
    NOT IN (...)`` and extend their SQL params with the returned list. Replaces the
    ~25 inline ``list(ALL_EXCL_FROM_SPEND)`` + placeholder-string sites across the DAL.
    """
    params = list(ALL_EXCL_FROM_SPEND)
    placeholders = ", ".join("?" for _ in params)
    return placeholders, params


def get_income_exclusion_clause() -> tuple[str, list[str]]:
    """Return ``(placeholder_string, params)`` for the canonical income-exclusion NOT IN clause.

    Mirrors :func:`get_spend_exclusion_clause` but against ``INCOME_EXCL_FROM_INC`` —
    the set that keeps refunds and transfer credits out of income totals.
    """
    params = list(INCOME_EXCL_FROM_INC)
    placeholders = ", ".join("?" for _ in params)
    return placeholders, params


def month_range(year: int, month: int) -> tuple[str, str]:
    """Return (first_day, last_day) as 'YYYY-MM-DD' strings for a given month."""
    last_day = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"


def prev_month(year: int, month: int) -> tuple[int, int]:
    """Return (year, month) for the previous month.  Handles Jan → Dec rollover."""
    if month == 1:
        return year - 1, 12
    return year, month - 1
