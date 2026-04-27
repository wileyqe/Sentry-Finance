"""
tests/test_fidelity_investment_extractor.py — P15-T09 Fidelity regex unit tests.

Exercises the per-position parsers without a browser. Page-text
fixtures mirror what ``page.inner_text('body')`` returned on the
Fidelity Positions detail panel for SPAXX (SEC yield) and a generic
ETF position (YTD return). When Fidelity re-skins the panel and the
labels drift, these tests fail loudly instead of silently losing
rows.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extractors.fidelity_investment_details import (  # noqa: E402
    build_position_fields,
    parse_position_ytd_return,
    parse_spaxx_yield,
)


# ── SPAXX (cash sweep) detail fixture ──────────────────────────────────

SPAXX_PAGE = (
    "FIDELITY GOVERNMENT MONEY MARKET FUND (SPAXX)\n"
    "Money Market Fund\n"
    "NAV\n"
    "$1.00\n"
    "7-Day Yield (SEC)\n"
    "4.32%\n"
    "Expense Ratio\n"
    "0.42%\n"
    "Quantity\n"
    "8,243.21\n"
)


def test_spaxx_sec_yield_label_first_form():
    assert parse_spaxx_yield(SPAXX_PAGE) == "4.32%"


def test_spaxx_sec_yield_alternate_label():
    """Some Fidelity views show '7-Day SEC Yield' (no parens)."""
    text = "7-Day SEC Yield\n3.97%\nExpense Ratio\n0.42%\n"
    assert parse_spaxx_yield(text) == "3.97%"


def test_spaxx_sec_yield_missing_returns_none():
    """If the panel has no yield row at all (loading state), return None."""
    text = "FIDELITY GOVERNMENT MONEY MARKET FUND (SPAXX)\nNAV\n$1.00\n"
    assert parse_spaxx_yield(text) is None


def test_build_fields_for_spaxx_uses_sec_yield():
    """Dispatcher: SPAXX → sec_yield key (not ytd_return)."""
    fields = build_position_fields("SPAXX", SPAXX_PAGE)
    assert fields == {"sec_yield": "4.32%"}


# ── Equity / ETF detail fixture ────────────────────────────────────────

VTI_PAGE = (
    "VANGUARD TOTAL STOCK MARKET ETF (VTI)\n"
    "ETF · US Equity\n"
    "Last Price\n"
    "$285.41\n"
    "Day Change\n"
    "+1.23 (+0.43%)\n"
    "YTD Return\n"
    "+12.4%\n"
    "1-Year Return\n"
    "+18.7%\n"
)


def test_vti_ytd_return_signed():
    assert parse_position_ytd_return(VTI_PAGE) == "+12.4%"


def test_vti_ytd_alternate_label_year_to_date():
    text = "Year-to-Date Return\n+8.1%\nVolume\n3.2M\n"
    assert parse_position_ytd_return(text) == "+8.1%"


def test_negative_ytd_return_captured():
    text = "YTD Return\n-2.1%\nVolume\n3.2M\n"
    assert parse_position_ytd_return(text) == "-2.1%"


def test_build_fields_for_etf_uses_ytd_return():
    """Dispatcher: anything other than SPAXX → ytd_return key."""
    fields = build_position_fields("VTI", VTI_PAGE)
    assert fields == {"ytd_return": "+12.4%"}


def test_build_fields_for_lowercase_ticker_still_treated_as_equity():
    """The ticker case-insensitivity check uses upper(); mixed-case ok."""
    fields = build_position_fields("vti", VTI_PAGE)
    assert fields == {"ytd_return": "+12.4%"}


def test_build_fields_for_spaxx_with_missing_yield_returns_empty():
    """Empty page → empty dict; result_writer skips empty payloads."""
    text = "FIDELITY GOVERNMENT MONEY MARKET FUND (SPAXX)\nNAV\n$1.00\n"
    assert build_position_fields("SPAXX", text) == {}


def test_label_first_tolerates_subtitle_line():
    """A subtitle row between label and value (e.g. 'as of HH:MM ET')
    must not block the YTD value from being captured."""
    text = (
        "YTD Return\n"
        "as of 04:00 PM ET on 04/26/2026\n"
        "+12.4%\n"
    )
    assert parse_position_ytd_return(text) == "+12.4%"
