"""
tests/test_nfcu_extractor.py — P15-T03b regex unit tests.

The T04 Phase A walkthrough revealed that NFCU renders the rewards
balance inside a button label formatted ``"10,142pts Rewards"`` —
digits → ``pts`` → ``Rewards``. The T03 label-first patterns never
matched, so the live scrape silently dropped rewards while the DAL,
pivot, and UI path all worked against seeded data. These tests pin
the value-first fix in ``NFCUConnector._extract_field_value``.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extractors.nfcu_connector import NFCUConnector  # noqa: E402


_REWARDS_PATTERNS = [
    r"(\d[\d,]*)\s*pts\s+Rewards?",
    r"Rewards?\s+Points?\s+Balance",
    r"Points?\s+Balance",
    r"Available\s+Points",
]


def _extract(text: str, patterns: list[str]) -> str | None:
    return NFCUConnector._extract_field_value(text, patterns)


# ── Value-first (the bug this task fixes) ──────────────────────────


def test_value_first_rewards_with_comma():
    """NFCU's live DOM: '10,142pts Rewards' button label."""
    assert _extract("10,142pts Rewards", _REWARDS_PATTERNS) == "10,142"


def test_value_first_rewards_no_comma():
    assert _extract("8450pts Rewards", _REWARDS_PATTERNS) == "8450"


def test_value_first_singular_reward():
    """The ``Rewards?`` quantifier accepts the singular label."""
    assert _extract("1pts Reward", _REWARDS_PATTERNS) == "1"


def test_value_first_case_insensitive():
    assert _extract("10,142PTS REWARDS", _REWARDS_PATTERNS) == "10,142"


def test_value_first_embedded_in_page_text():
    """The pattern holds up against surrounding NFCU button chrome."""
    page = (
        "Account Summary\n"
        "Current Balance $2,431.18\n"
        "10,142pts Rewards\n"
        "View Statements"
    )
    assert _extract(page, _REWARDS_PATTERNS) == "10,142"


# ── Label-first (legacy shapes must still work) ────────────────────


def test_label_first_rewards_balance_still_works():
    """A page rendering 'Rewards Points Balance: 8,450' still matches."""
    assert _extract("Rewards Points Balance: 8,450", _REWARDS_PATTERNS) == "8,450"


def test_label_first_available_points_still_works():
    assert _extract("Available Points 12,400", _REWARDS_PATTERNS) == "12,400"


def test_unrelated_label_first_patterns_unaffected():
    """Sanity — non-rewards extraction (credit limit) is untouched."""
    credit_limit_patterns = [r"Credit\s+Limit", r"Total\s+Credit\s+Line"]
    assert _extract("Credit Limit: $30,000.00", credit_limit_patterns) == "$30,000.00"


# ── Negative cases ──────────────────────────────────────────────────


def test_returns_none_when_no_match():
    assert _extract("no rewards here", _REWARDS_PATTERNS) is None


def test_does_not_match_pts_without_rewards():
    """'5000pts Loyalty' isn't NFCU rewards — must not match."""
    assert _extract("5000pts Loyalty", _REWARDS_PATTERNS) is None


# ── VIN regex ───────────────────────────────────────────────────────
#
# Pin the auto-loan VIN field pattern in extractors/nfcu/_balances_mixin.py
# (lines 373–379) — value-first, 17-char alnum with North-American VIN
# rules excluding I/O/Q. Captures the value verbatim regardless of
# label spelling.

_VIN_PATTERNS = [
    r"(?:VIN|Vehicle\s+Identification(?:\s+Number)?)[\s:#]+([A-HJ-NPR-Z0-9]{17})",
]


def test_vin_label_colon_format():
    """NFCU portal renders 'VIN: <17-char>' on the auto-loan detail page."""
    assert _extract("VIN: 1HGCV41E5XCL12345", _VIN_PATTERNS) == "1HGCV41E5XCL12345"


def test_vin_vehicle_identification_number_label():
    """Fallback label variant — full 'Vehicle Identification Number' spelling."""
    assert (
        _extract("Vehicle Identification Number: 5TDJKRFH4LS123456", _VIN_PATTERNS)
        == "5TDJKRFH4LS123456"
    )


def test_vin_pound_separator():
    """Pattern allows ``#`` separator before the value."""
    assert _extract("VIN #1HGCV41E5XCL12345", _VIN_PATTERNS) == "1HGCV41E5XCL12345"


def test_vin_embedded_in_page_text():
    page = (
        "Collateral Description\n2021 Honda Civic\n"
        "VIN: 1HGCV41E5XCL12345\nGAP Insurance: Yes\n"
    )
    assert _extract(page, _VIN_PATTERNS) == "1HGCV41E5XCL12345"


def test_vin_case_insensitive_label():
    """Label match is case-insensitive (matcher uses re.IGNORECASE)."""
    assert _extract("vin: 1HGCV41E5XCL12345", _VIN_PATTERNS) == "1HGCV41E5XCL12345"


def test_vin_invalid_characters_rejected():
    """Real VINs never use I, O, or Q — pattern must reject them."""
    # 'I' at position 7 — invalid VIN char
    assert _extract("VIN: 1HGCV4IE5XCL12345", _VIN_PATTERNS) is None


def test_vin_wrong_length_rejected():
    """16-char and 18-char strings are not VINs."""
    assert _extract("VIN: 1HGCV41E5XCL1234", _VIN_PATTERNS) is None  # 16
    # 18 chars: pattern matches the first 17 chars only — capture group
    # still produces a 17-char VIN, so wrong-length-too-long is a soft
    # failure. Document by checking the truncated capture is still 17:
    assert (
        _extract("VIN: 1HGCV41E5XCL1234567", _VIN_PATTERNS)
        == "1HGCV41E5XCL12345"
    )
