"""
tests/test_acorns_investment_extractor.py — P15-T09 Acorns regex.

Page-text fixtures mirror what ``page.inner_text('body')`` returned
on the Acorns dashboard / Holdings panel. When Acorns reflows the
labels, these tests fail loudly instead of silently losing rows.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extractors.acorns_investment_details import (  # noqa: E402
    parse_account_level,
    parse_holdings_returns,
    parse_round_up_lifetime,
    parse_round_up_ytd,
)


# ── Dashboard round-up fixtures ────────────────────────────────────────

DASHBOARD_PAGE = (
    "Welcome back, Quintin\n"
    "Total Portfolio Value\n"
    "$2,840.21\n"
    "Round-Ups Invested (YTD)\n"
    "$48.20\n"
    "Round-Ups Invested (All Time)\n"
    "$1,250.40\n"
    "Recurring Investments\n"
    "$50.00 / week\n"
)


def test_round_up_ytd_basic():
    assert parse_round_up_ytd(DASHBOARD_PAGE) == "$48.20"


def test_round_up_lifetime_basic():
    assert parse_round_up_lifetime(DASHBOARD_PAGE) == "$1,250.40"


def test_round_up_lifetime_alternate_label():
    text = "Lifetime Round-Ups\n$2,500.00\n"
    assert parse_round_up_lifetime(text) == "$2,500.00"


def test_round_ups_missing_returns_none():
    text = "Total Portfolio Value\n$2,840.21\nRecurring Investments\n$50.00\n"
    assert parse_round_up_ytd(text) is None
    assert parse_round_up_lifetime(text) is None


def test_account_level_bundle_includes_both():
    out = parse_account_level(DASHBOARD_PAGE)
    assert out == {
        "round_up_ytd": "$48.20",
        "round_up_lifetime": "$1,250.40",
    }


def test_account_level_bundle_omits_missing_fields():
    """If only YTD is present, lifetime is omitted (writer skips empty)."""
    text = "Round-Ups Invested (YTD)\n$48.20\n"
    out = parse_account_level(text)
    assert out == {"round_up_ytd": "$48.20"}


# ── Holdings-panel per-ETF fixtures ───────────────────────────────────

HOLDINGS_PAGE = (
    "Holdings\n"
    "VOO\n"
    "Vanguard S&P 500 ETF\n"
    "$1,420.50\n"
    "+12.4%\n"
    "VEA\n"
    "Vanguard FTSE Developed Markets ETF\n"
    "$485.00\n"
    "+4.8%\n"
    "VWO\n"
    "Vanguard FTSE Emerging Markets ETF\n"
    "$220.10\n"
    "-2.1%\n"
    "IAGG\n"
    "iShares Core International Aggregate Bond ETF\n"
    "$315.40\n"
    "+1.2%\n"
)


def test_holdings_returns_basic():
    out = parse_holdings_returns(HOLDINGS_PAGE)
    assert out["VOO"] == {"ytd_return": "+12.4%"}
    assert out["VEA"] == {"ytd_return": "+4.8%"}


def test_holdings_returns_negative():
    out = parse_holdings_returns(HOLDINGS_PAGE)
    assert out["VWO"] == {"ytd_return": "-2.1%"}


def test_holdings_returns_count():
    out = parse_holdings_returns(HOLDINGS_PAGE)
    assert set(out.keys()) == {"VOO", "VEA", "VWO", "IAGG"}


def test_holdings_skips_two_letter_codes():
    """`US`, `IT`, etc. on their own line should not be treated as tickers."""
    text = (
        "Holdings\n"
        "US\n"
        "United States\n"
        "+10.0%\n"
        "VOO\n"
        "Vanguard S&P 500 ETF\n"
        "+12.4%\n"
    )
    out = parse_holdings_returns(text)
    assert "US" not in out
    assert out["VOO"] == {"ytd_return": "+12.4%"}


def test_holdings_skips_ticker_with_no_pct_in_window():
    """Ticker with no percent inside the lookahead window is skipped."""
    text = (
        "VOO\n"
        "Vanguard S&P 500 ETF\n"
        "$1,420.50\n"
        "Last close\n"
        "Volume\n"
        "Bid/Ask\n"
        "Day range\n"
        "52w range\n"  # 8 lines down — past the window
        "+12.4%\n"
    )
    out = parse_holdings_returns(text)
    assert out == {}
