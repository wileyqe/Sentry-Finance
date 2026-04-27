"""
tests/test_tsp_investment_extractor.py — P15-T09 TSP fund-return regex.

Page-text fixtures mirror what
``page.evaluate('document.body.innerText')`` returned on the
``api.rk.tsp.gov`` Angular SPA's "Investment details" view (validated
2026-04). When TSP re-skins the SPA and the labels drift, these
tests fail loudly instead of silently losing fund-return rows.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extractors.tsp_investment_details import parse_fund_returns  # noqa: E402


# Realistic fund-card layout: name, balance, gain/loss, units, return,
# fund price. Two static funds + one L-vintage in the same body.
TSP_PAGE = (
    "Investment details\n"
    "Your Current Mix\n"
    "$182,450.00\n"
    "G Fund\n"
    "$28,140.50\n"
    "Gain/Loss\n"
    "$523.10\n"
    "Units\n"
    "1,234.5678\n"
    "Fund Return\n"
    "+4.05%\n"
    "Fund Price\n"
    "$22.79\n"
    "C Fund\n"
    "$112,300.75\n"
    "Gain/Loss\n"
    "$8,431.92\n"
    "Units\n"
    "1,592.4123\n"
    "Fund Return\n"
    "+12.40%\n"
    "Fund Price\n"
    "$70.52\n"
    "L 2050\n"
    "$42,008.75\n"
    "Gain/Loss\n"
    "$2,114.38\n"
    "Units\n"
    "974.6311\n"
    "Fund Return\n"
    "+8.91%\n"
    "Fund Price\n"
    "$43.10\n"
)


def test_parses_static_funds():
    """G + C funds round-trip to TSP_G / TSP_C tickers with their YTDs."""
    out = parse_fund_returns(TSP_PAGE)
    assert out["TSP_G"]["ytd_return"] == "+4.05%"
    assert out["TSP_G"]["fund_name"] == "G Fund"
    assert out["TSP_C"]["ytd_return"] == "+12.40%"
    assert out["TSP_C"]["fund_name"] == "C Fund"


def test_parses_lifecycle_fund_with_year():
    """L 2050 → TSP_L2050 ticker."""
    out = parse_fund_returns(TSP_PAGE)
    assert out["TSP_L2050"]["ytd_return"] == "+8.91%"
    assert out["TSP_L2050"]["fund_name"] == "L 2050"


def test_handles_negative_fund_return():
    """Negative YTD percentages survive the regex with sign intact."""
    text = (
        "C Fund\n"
        "$10,000.00\n"
        "Gain/Loss\n"
        "-$1,200.00\n"
        "Units\n"
        "150.00\n"
        "Fund Return\n"
        "-12.10%\n"
        "Fund Price\n"
        "$66.66\n"
    )
    out = parse_fund_returns(text)
    assert out["TSP_C"]["ytd_return"] == "-12.10%"


def test_skips_fund_with_no_return_line():
    """A fund whose 'Fund Return' is missing (loading state) is skipped."""
    text = (
        "G Fund\n"
        "$10,000.00\n"
        "Units\n"
        "440.00\n"
        "Fund Price\n"
        "$22.73\n"
    )
    out = parse_fund_returns(text)
    assert "TSP_G" not in out


def test_l_income_fund():
    """L Income → TSP-side ticker via _fund_to_ticker normalisation."""
    text = (
        "L Income\n"
        "$5,400.00\n"
        "Gain/Loss\n"
        "$0.00\n"
        "Units\n"
        "260.00\n"
        "Fund Return\n"
        "+3.10%\n"
        "Fund Price\n"
        "$20.77\n"
    )
    out = parse_fund_returns(text)
    # _fund_to_ticker produces a canonical key; only verify return + label.
    assert len(out) == 1
    only = next(iter(out.values()))
    assert only["ytd_return"] == "+3.10%"
    assert only["fund_name"] == "L Income"


def test_empty_text_returns_empty_dict():
    assert parse_fund_returns("") == {}
