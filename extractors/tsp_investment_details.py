"""
extractors/tsp_investment_details.py — P15-T09 TSP fund-return parsing.

The TSP Angular SPA at ``api.rk.tsp.gov`` already renders fund cards
in a deterministic text order (validated 2026-04 in
``TSPConnector._parse_investments_page``)::

    [Fund Name](PDF)
    $[Balance]
    Gain/Loss
    $[amount]
    ...
    Units
    [count]
    Fund Return
    [%]
    Fund Price
    $[price]

The existing ``_parse_investments_page`` extracts balance / units /
NAV but stops short of the YTD return. This module is a parallel,
read-only second pass that rescans the same body text for the
``Fund Return`` cell and returns ``{ticker: {ytd_return, fund_name}}``.

Keeping the logic in a separate module lets the connector continue
calling ``_parse_investments_page`` unchanged (no balance-scrape
regression risk) and gives a small, fixture-testable surface for the
return-rate extraction.
"""

from __future__ import annotations

import re

from dal.parsers.tsp_statement import _fund_to_ticker

# Static funds + L-vintages. Anchors the start of a fund block so the
# forward scan knows where to look for the "Fund Return" line.
_FUND_NAME_RE = re.compile(
    r"^(L\s+\d{4}|L\s+Income|[GCFSI]\s+Fund)$", re.IGNORECASE
)


def parse_fund_returns(body_text: str) -> dict[str, dict[str, str]]:
    """Return ``{ticker: {ytd_return, fund_name}}`` for the body text.

    Walks the text top-to-bottom. When a fund-name line is found,
    scans forward up to ~25 lines for a ``Fund Return`` line and
    treats the next non-empty line as the YTD percentage. Empty or
    missing returns silently skip the fund.

    Tickers come from ``dal.parsers.tsp_statement._fund_to_ticker``
    so the on-disk + scrape paths agree on naming
    (``TSP_C`` / ``TSP_S`` / ``TSP_L2050`` / etc.).
    """
    lines = [l.strip() for l in body_text.split("\n") if l.strip()]
    out: dict[str, dict[str, str]] = {}

    for i, line in enumerate(lines):
        if not _FUND_NAME_RE.match(line):
            continue
        fund_name = line.strip()
        ticker = _fund_to_ticker(fund_name)

        # Scan forward for the "Fund Return" label, then the next
        # percentage-shaped line.
        for j in range(i + 1, min(i + 25, len(lines))):
            if lines[j].lower() == "fund return":
                for k in range(j + 1, min(j + 4, len(lines))):
                    pct = re.match(
                        r"^([+\-−]?\d+(?:\.\d+)?\s*%)$", lines[k]
                    )
                    if pct:
                        out[ticker] = {
                            "ytd_return": pct.group(1).strip(),
                            "fund_name": fund_name,
                        }
                        break
                break

    return out
