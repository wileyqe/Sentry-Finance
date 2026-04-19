"""
tests/test_chase_extractor.py — P15-T05 regex unit tests.

Phase A walkthrough captured the exact label shapes on Chase's Account
Details views: checking uses "Interest rate / Interest in {year} / Last
statement date" labels, credit card uses "Purchase APR / Total credit
limit / Minimum payment" with a value-first due-date embedded in the
minimum-payment line. These tests pin each field extraction against
fixture text taken verbatim from the Phase A DOM dumps, so regex drift
(Chase re-skinning the Account Details view) fails loudly instead of
silently losing fields.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extractors.chase_connector import ChaseConnector  # noqa: E402


def _extract(text: str, patterns: list[str]) -> str | None:
    return ChaseConnector._extract_field_value(text, patterns)


# ── Checking / Premier Plus (XXXX) fixtures ────────────────────────────
#
# Snippet mirrors what `page.inner_text('body')` returned on the
# Account Details view — label on one line, optional interposing
# timestamp line, value on the next.
CHK_PAGE = (
    "PREMIER PLUS CKG (...XXXX)\n"
    "Account Information\n"
    "Available balance\n"
    "as of 12:00 AM ET on 04/17/2026\n"
    "$4,172.97\n"
    "Present balance\n"
    "$4,172.97\n"
    "Interest rate\n"
    "0.01%\n"
    "Interest in 2026\n"
    "$0.03\n"
    "Last statement date\n"
    "Mar 18, 2026\n"
    "Overdraft Protection\n"
    "Overdraft protection\n"
    "Off\n"
)


def test_checking_available_balance_tolerates_interposing_timestamp():
    """The 'as of ...' line between label and value must not block the match."""
    assert _extract(CHK_PAGE, [r"Available\s+balance"]) == "$4,172.97"


def test_checking_present_balance():
    assert _extract(CHK_PAGE, [r"Present\s+balance"]) == "$4,172.97"


def test_checking_apy_chase_interest_rate_label():
    """Chase calls APY 'Interest rate' on deposit accounts."""
    assert (
        _extract(CHK_PAGE, [r"Interest\s+rate", r"APY"]) == "0.01%"
    )


def test_checking_ytd_interest_with_dynamic_year():
    """'Interest in 2026' — the year is dynamic and must not be pinned."""
    assert _extract(CHK_PAGE, [r"Interest\s+in\s+\d{4}"]) == "$0.03"


def test_checking_last_statement_date():
    assert (
        _extract(CHK_PAGE, [r"Last\s+statement\s+date"]) == "Mar 18, 2026"
    )


# ── Credit card / Slate Edge (XXXX) fixtures ───────────────────────────

CC_PAGE = (
    "Slate Edge (...XXXX)\n"
    "Account Information\n"
    "Current balance\n"
    "$0.00\n"
    "Pending charges\n"
    "Not available\n"
    "Available credit\n"
    "$6,800.00\n"
    "Total credit limit\n"
    "$6,800.00\n"
    "Next closing date\n"
    "Apr 20, 2026\n"
    "Balance on last statement\n"
    "$0.00 on Aug 20, 2025\n"
    "Remaining statement balance\n"
    "$0.00\n"
    "Recent Payment Activity\n"
    "Last payment\n"
    "$465.95 was paid on Sep 17, 2025\n"
    "Minimum payment\n"
    "$0.00 is due on Apr 17, 2026\n"
    "Automatic Payments\n"
    "On\n"
    "Cash Advance\n"
    "Cash advance balance\n"
    "$0.00\n"
    "Available for cash advance\n"
    "$1,360.00\n"
    "Cash advance limit\n"
    "$1,360.00\n"
    "APR as of Apr 19, 2026\n"
    "Purchase APR\n"
    "0.00%\n"
    "Cash advance APR\n"
    "28.49%\n"
)


def test_cc_purchase_apr():
    assert _extract(CC_PAGE, [r"Purchase\s+APR"]) == "0.00%"


def test_cc_cash_advance_apr():
    assert _extract(CC_PAGE, [r"Cash\s+advance\s+APR"]) == "28.49%"


def test_cc_total_credit_limit():
    assert (
        _extract(CC_PAGE, [r"Total\s+credit\s+limit", r"Credit\s+Limit"])
        == "$6,800.00"
    )


def test_cc_available_credit_word_boundary():
    """'Available credit' must not swallow 'Available for cash advance'."""
    assert _extract(CC_PAGE, [r"\bAvailable\s+credit\b"]) == "$6,800.00"


def test_cc_cash_advance_limit_not_confused_with_available():
    assert _extract(CC_PAGE, [r"Cash\s+advance\s+limit"]) == "$1,360.00"


def test_cc_cash_advance_available_distinct_from_limit():
    assert (
        _extract(CC_PAGE, [r"Available\s+for\s+cash\s+advance"]) == "$1,360.00"
    )


def test_cc_minimum_payment_captures_amount():
    """Label-first pattern grabs the dollar amount, even though the
    value line continues with ' is due on ...'."""
    assert _extract(CC_PAGE, [r"Minimum\s+payment"]) == "$0.00"


def test_cc_payment_due_date_value_first_capture():
    """Value-first capture group pulls the due date from the
    "$X.XX is due on <Month Day, Year>" line."""
    due_date_patterns = [
        r"\$[\d,]+\.\d{2}\s+is\s+due\s+on\s+"
        r"([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})",
    ]
    assert _extract(CC_PAGE, due_date_patterns) == "Apr 17, 2026"


def test_cc_statement_balance():
    """Matches '$0.00' from 'Balance on last statement' line — date
    portion stays on the full string, parsing deferred to downstream."""
    assert _extract(CC_PAGE, [r"Balance\s+on\s+last\s+statement"]) == "$0.00"


def test_cc_remaining_statement_balance():
    assert (
        _extract(CC_PAGE, [r"Remaining\s+statement\s+balance"]) == "$0.00"
    )


def test_cc_next_closing_date():
    assert _extract(CC_PAGE, [r"Next\s+closing\s+date"]) == "Apr 20, 2026"


def test_cc_automatic_payments_on_flag():
    """Flag regex branch of the assembled value pattern must match 'On'."""
    assert _extract(CC_PAGE, [r"Automatic\s+Payments?"]) == "On"


# ── Negative cases ──────────────────────────────────────────────────────


def test_unmatched_pattern_returns_none():
    assert _extract(CC_PAGE, [r"This\s+Label\s+Does\s+Not\s+Exist"]) is None


def test_apy_miss_when_no_interest_label_present():
    page = "Premier Plus\nAvailable balance\n$100.00\n"
    assert _extract(page, [r"Interest\s+rate", r"APY"]) is None
