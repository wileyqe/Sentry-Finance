"""
extractors/fidelity_investment_details.py — P15-T09 Fidelity scrape.

Provides the regex-based extractors invoked by
``FidelityConnector._scrape_investment_details``. Two products:

* SPAXX 7-day SEC yield, captured from the SPAXX position detail page
  and stamped under ``fund_ticker='SPAXX'``.
* Per-ETF YTD return, captured from each non-cash position page,
  stamped under the ticker symbol.

Live navigation (clicking each position row, waiting for the modal,
dumping ``page.inner_text("body")``) lives on the connector. This
module is purely text-in / fields-out so it can be unit-tested
against fixture page-text dumps without a browser.
"""

from __future__ import annotations

from typing import Optional

from extractors._investment_extract import extract_field


# 7-day SEC yield (SPAXX). The yield label appears under "Money Market"
# fund detail and is the value Fidelity reports as the SEC-standardized
# yield. Includes both the "(SEC)" and bare "7-day yield" shapes the
# portal has used historically.
SEC_YIELD_PATTERNS = [
    r"7-Day\s+Yield\s*\(SEC\)",
    r"7-Day\s+SEC\s+Yield",
    r"7\s*Day\s+Yield",
]

# Year-to-date total return on an equity / ETF position. Fidelity
# alternates "YTD Return" and "Year-to-Date" in the detail panel.
YTD_RETURN_PATTERNS = [
    r"YTD\s+Return",
    r"YTD\s+Total\s+Return",
    r"Year[\s\-]to[\s\-]Date\s+Return",
]


def parse_spaxx_yield(page_text: str) -> Optional[str]:
    """Return SPAXX SEC yield (e.g. ``"4.32%"``) or None if not found."""
    return extract_field(page_text, SEC_YIELD_PATTERNS)


def parse_position_ytd_return(page_text: str) -> Optional[str]:
    """Return YTD total return for an equity position, or None."""
    return extract_field(page_text, YTD_RETURN_PATTERNS)


def build_position_fields(
    ticker: str, page_text: str
) -> dict[str, str]:
    """Build the per-fund field dict for one Fidelity position page.

    SPAXX gets the SEC-yield row; everything else gets YTD return.
    Empty-result fields are omitted (``record_investment_details`` would
    skip them anyway, but the contract is cleaner upstream).
    """
    fields: dict[str, str] = {}
    if ticker.upper() == "SPAXX":
        sec = parse_spaxx_yield(page_text)
        if sec is not None:
            fields["sec_yield"] = sec
    else:
        ytd = parse_position_ytd_return(page_text)
        if ytd is not None:
            fields["ytd_return"] = ytd
    return fields
