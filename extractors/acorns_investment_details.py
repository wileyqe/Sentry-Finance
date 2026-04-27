"""
extractors/acorns_investment_details.py — P15-T09 Acorns scrape.

Two captures from the Acorns dashboard:

* **Account-level round-ups** (``fund_ticker IS NULL``): YTD total +
  lifetime total of round-up dollars batched into the portfolio.
  Acorns-unique data — not derivable from transactions because round-
  ups are batched into normal-shaped deposits before they hit the
  Acorns cash leg.
* **Per-ETF YTD return** (``fund_ticker = 'VOO' / 'VEA' / ...``):
  Each holding card on the Investments → Holdings panel exposes a
  YTD return % adjacent to the ticker. Captured one row per held
  ETF so per-ticker performance lands in the Account Details drawer.

The connector handles live navigation. This module is purely text-in
/ fields-out so it unit-tests against fixture page-text dumps without
a browser.
"""

from __future__ import annotations

import re
from typing import Optional

from extractors._investment_extract import extract_field


# Round-up totals: Acorns labels them "Round-Ups Invested" with a YTD
# scope chip and a separate "All Time" / "Lifetime" presentation.
ROUND_UP_YTD_PATTERNS = [
    r"Round[- ]?Ups?\s+Invested[^\n]*\(YTD\)",
    r"Round[- ]?Ups?\s+\(YTD\)",
    r"YTD\s+Round[- ]?Ups",
]

ROUND_UP_LIFETIME_PATTERNS = [
    r"Round[- ]?Ups?\s+Invested[^\n]*\(All\s+Time\)",
    r"Round[- ]?Ups?\s+\(All\s+Time\)",
    r"Round[- ]?Ups?\s+\(Lifetime\)",
    r"Lifetime\s+Round[- ]?Ups",
]

# ETF holding card: ticker on one line, name + percentage cluster on
# the next few lines. Acorns shows the YTD return next to the holding
# in the "Holdings" tab.
_HOLDING_TICKER_RE = re.compile(r"^([A-Z]{2,5})$")
_HOLDING_PCT_RE = re.compile(r"^([+\-−]?\d+(?:\.\d+)?\s*%)$")


def parse_round_up_ytd(page_text: str) -> Optional[str]:
    """Round-ups invested year-to-date. ``"$48.20"`` or None."""
    return extract_field(page_text, ROUND_UP_YTD_PATTERNS)


def parse_round_up_lifetime(page_text: str) -> Optional[str]:
    """Round-ups invested all-time. ``"$1,250.40"`` or None."""
    return extract_field(page_text, ROUND_UP_LIFETIME_PATTERNS)


def parse_account_level(page_text: str) -> dict[str, str]:
    """Bundle the two account-level fields into one dict.

    Empty-result fields are omitted (writer would skip them anyway,
    but the contract is cleaner upstream).
    """
    out: dict[str, str] = {}
    ytd = parse_round_up_ytd(page_text)
    if ytd:
        out["round_up_ytd"] = ytd
    lifetime = parse_round_up_lifetime(page_text)
    if lifetime:
        out["round_up_lifetime"] = lifetime
    return out


def parse_holdings_returns(
    page_text: str,
) -> dict[str, dict[str, str]]:
    """Walk the Holdings panel and pair each ticker with its YTD return.

    Acorns renders each holding as a card with the ticker on its own
    line, followed by a name line and a few metric lines. The YTD %
    appears as a percentage-shaped line within ~6 lines of the ticker.

    Returns ``{ticker: {ytd_return: value}}``. Tickers that don't have
    a matching percent inside the lookahead window are silently
    skipped.
    """
    lines = [l.strip() for l in page_text.split("\n") if l.strip()]
    out: dict[str, dict[str, str]] = {}

    for i, line in enumerate(lines):
        m = _HOLDING_TICKER_RE.match(line)
        if not m:
            continue
        ticker = m.group(1)
        # Skip generic 2-letter words / month abbreviations / state
        # codes that Acorns might surface in the same panel. The known
        # Acorns ETF tickers are at least 3 chars.
        if len(ticker) < 3:
            continue
        for j in range(i + 1, min(i + 8, len(lines))):
            pct = _HOLDING_PCT_RE.match(lines[j])
            if pct:
                out[ticker] = {"ytd_return": pct.group(1).strip()}
                break

    return out
