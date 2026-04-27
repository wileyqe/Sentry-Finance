"""
extractors/_investment_extract.py — P15-T09 shared regex helpers.

Per-position / per-fund DOM scrapes for Fidelity, TSP, and Acorns all
need the same label-first / value-first regex extraction shape. This
module hosts the shared helper and the value-shape alternation
(currency / signed percent / plain number) so each institution module
imports one function instead of re-deriving the regex.

Mirrors ``extractors/chase/_balances_mixin.py::_extract_field_value``
but targets investment value shapes — Chase's helper bakes in slash
dates and "On / Off / Enrolled" flags that aren't relevant here, while
investments need signed-percent matching.
"""

from __future__ import annotations

import re


def _pattern_has_capture(pattern: str) -> bool:
    """True iff ``pattern`` declares at least one capturing group.

    Compiles the pattern and reads ``.groups`` rather than scanning for
    raw ``(`` so escaped parens (``\\(SEC\\)``) and non-capturing
    groups (``(?:...)``) don't false-trigger the value-first branch.
    """
    try:
        return re.compile(pattern).groups > 0
    except re.error:
        return False


# Currency and signed-percent only. Plain integer/decimal is intentional
# for Acorns "Total Round-Ups" raw counts. No date or flag matching.
_VALUE_ALTERNATION = (
    r"\$[\d,]+\.?\d*"           # $1,234.56
    r"|[+\-−]?[\d,]+\.\d+\s*%"  # +12.4%, -2.1%, 4.32%
    r"|[+\-−]?\d+\s*%"          # 5%
    r"|[+\-−]?\$[\d,]+\.?\d*"   # -$48.20 (signed)
    r"|[\d,]+"                  # 1,234 (plain int)
)


def extract_field(page_text: str, patterns: list[str]) -> str | None:
    """Run ``patterns`` against ``page_text`` and return the first match.

    Two pattern shapes are supported, matching the Chase / NFCU helper
    convention:

    * **Label-first** (no capture group in the pattern): the pattern is
      treated as a label prefix; the assembled regex matches the label,
      tolerates an optional subtitle line, and captures the value on
      the next non-empty line. Suitable for live DOM dumps from
      ``page.inner_text("body")``.
    * **Value-first** (pattern contains its own capture group): the
      pattern is run verbatim and ``group(1)`` is returned. Suitable
      for inline shapes like
      ``r"Round-Ups Invested[^\\n]*YTD\\s*(\\$[\\d,.]+)"``.

    Strips trailing whitespace from the returned value but preserves
    the inner formatting (currency symbol, percent sign, sign prefix)
    so the downstream formatter sees the raw scrape.
    """
    for pattern in patterns:
        if _pattern_has_capture(pattern):
            full_regex = pattern
        else:
            # Label on one line, optional subtitle (no $ or % to avoid
            # eating the value line), value on the next non-empty line.
            full_regex = (
                rf"{pattern}[^\n]*\n(?:[^\n$%]*\n)?\s*"
                rf"({_VALUE_ALTERNATION})"
            )
        match = re.search(full_regex, page_text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return None
