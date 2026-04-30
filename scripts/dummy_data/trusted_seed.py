"""Canonical synthetic seed contract.

This module is intentionally tiny and dependency-free so both scripts and
backend helpers can agree on the single trusted fixture without importing the
large seeder.
"""

from __future__ import annotations

from datetime import date, datetime, time

TRUSTED_SEED_VERSION = "trusted-2026-04-27-v1"
TRUSTED_SEED_END_DATE = date(2026, 4, 27)
TRUSTED_REFERENCE_DATE = date(2026, 4, 28)
TRUSTED_SEED_YEARS = 3

TRUSTED_REFERENCE_DATETIME = datetime.combine(
    TRUSTED_REFERENCE_DATE,
    time(0, 0, 0),
).replace(microsecond=0)

