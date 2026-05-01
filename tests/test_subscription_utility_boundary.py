"""tests/test_subscription_utility_boundary.py — P17-T24.

Codifies the household decision rule:

  • Utility-like services (power, water, gas, internet, phone) cannot
    generally be turned off without disrupting daily life. They MUST NOT
    be flagged as lifestyle creep.
  • Optional subscriptions (streaming, music, Prime, gym, Patreon, etc.)
    can be turned off and MUST remain eligible for lifestyle-creep review.

These tests exist so a future agent editing keyword rules in
``config/categories.yaml`` or canonical sets in
``dal/category_classifications.py`` cannot silently blur the boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal import categorization
from dal.category_classifications import (
    EXCLUDED_FROM_CREEP,
    INCOME_EXCL_FROM_INC,
    OPTIONAL_SUBSCRIPTION_CATEGORIES,
    UTILITY_LIKE_CATEGORIES,
)


# ── Boundary: the two sets are disjoint and named ────────────────────────────


def test_utility_and_subscription_sets_are_disjoint():
    """A category cannot simultaneously be utility-like AND optional-subscription.
    The household decision rule is binary: turn-off-able or not."""
    overlap = UTILITY_LIKE_CATEGORIES & OPTIONAL_SUBSCRIPTION_CATEGORIES
    assert not overlap, (
        f"UTILITY_LIKE_CATEGORIES and OPTIONAL_SUBSCRIPTION_CATEGORIES "
        f"must not overlap — got {sorted(overlap)}"
    )


def test_utility_like_categories_are_excluded_from_creep():
    """Every utility-like category MUST appear in EXCLUDED_FROM_CREEP.
    Power, water, gas, internet, and phone are non-discretionary —
    flagging them as lifestyle creep generates noise the household cannot
    act on (rate inflation is not a behavior change)."""
    missing = UTILITY_LIKE_CATEGORIES - EXCLUDED_FROM_CREEP
    assert not missing, (
        f"Utility-like categories missing from EXCLUDED_FROM_CREEP: "
        f"{sorted(missing)}. Add them to the set in "
        f"dal/category_classifications.py."
    )


def test_optional_subscription_categories_are_creep_eligible():
    """`Dues and Subscriptions` MUST stay out of EXCLUDED_FROM_CREEP. The
    household uses the lifestyle-creep panel to review optional-subscription
    growth — moving these into the exclusion set would defeat the review."""
    leaked = OPTIONAL_SUBSCRIPTION_CATEGORIES & EXCLUDED_FROM_CREEP
    assert not leaked, (
        f"Optional-subscription categories leaked into EXCLUDED_FROM_CREEP: "
        f"{sorted(leaked)}. They must remain eligible for lifestyle-creep "
        f"review per the household decision rule."
    )


def test_boundary_categories_excluded_from_income():
    """Both utility-like and subscription categories are spending categories.
    A positive `signed_amount` in any of them is a refund and must be filtered
    out of income totals via INCOME_EXCL_FROM_INC."""
    boundary = UTILITY_LIKE_CATEGORIES | OPTIONAL_SUBSCRIPTION_CATEGORIES
    missing = boundary - INCOME_EXCL_FROM_INC
    assert not missing, (
        f"Boundary categories missing from INCOME_EXCL_FROM_INC: "
        f"{sorted(missing)}. A refund in any of these would inflate income."
    )


# ── Classifier behavior: utility-like merchants ──────────────────────────────


def _categorize(description: str) -> str:
    """Run the keyword-rule layer of the classifier (no DB, no overrides)."""
    return categorization.categorize(description)


def test_electric_water_gas_classify_as_utilities():
    """Power/water/gas merchants must route to `Utilities`."""
    for desc in (
        "DUKE ENERGY ONLINE",
        "OHIO ELECTRIC COOP",
        "CITY WATER UTIL",
        "REGIONAL GAS UTIL",
    ):
        assert _categorize(desc) == "Utilities", (
            f"{desc!r} should classify as Utilities, got {_categorize(desc)!r}"
        )


def test_internet_and_cell_classify_as_utility_like_telephone_services():
    """Internet/cable/cell merchants must route to `Telephone Services`,
    NOT to `Dues and Subscriptions`. Internet and phone are utility-like
    infrastructure (remote work, banking 2FA, school comms)."""
    for desc in (
        "SPECTRUM INTERNET",
        "COMCAST XFINITY",
        "AT&T MOBILITY",
        "T-MOBILE AUTOPAY",
        "VERIZON WIRELESS",
        "MINT MOBILE PMT",
    ):
        cat = _categorize(desc)
        assert cat == "Telephone Services", (
            f"{desc!r} must classify as Telephone Services (utility-like), "
            f"got {cat!r}"
        )
        assert cat in UTILITY_LIKE_CATEGORIES, (
            f"{desc!r} resolved to {cat!r} which is not in "
            f"UTILITY_LIKE_CATEGORIES — boundary violated."
        )


# ── Classifier behavior: optional subscriptions ──────────────────────────────


def test_streaming_classifies_as_subscription():
    """Streaming services route to `Dues and Subscriptions` — the household
    can drop any of them without disrupting daily life."""
    for desc in (
        "NETFLIX.COM",
        "HULU LLC",
        "DISNEY PLUS",
        "HBO MAX",
        "PARAMOUNT+",
        "PEACOCK PREMIUM",
        "APPLE TV+",
        "YOUTUBE PREMIUM",
    ):
        cat = _categorize(desc)
        assert cat == "Dues and Subscriptions", (
            f"{desc!r} must classify as Dues and Subscriptions, got {cat!r}"
        )
        assert cat in OPTIONAL_SUBSCRIPTION_CATEGORIES


def test_music_audiobook_prime_classify_as_subscription():
    """Music/audiobook/Prime are optional even when used daily."""
    for desc in (
        "SPOTIFY PREMIUM",
        "AUDIBLE.COM",
        "KINDLE UNLIMITED",
        "AMAZON PRIME RENEWAL",
    ):
        cat = _categorize(desc)
        assert cat == "Dues and Subscriptions", (
            f"{desc!r} must classify as Dues and Subscriptions, got {cat!r}"
        )


# ── Integration: lifestyle-creep filter respects the boundary ────────────────


def test_lifestyle_creep_excludes_telephone_services():
    """Regression for the original violation: prior to P17-T24,
    `Telephone Services` was missing from EXCLUDED_FROM_CREEP, so a
    rate-inflation bump on internet/phone bills could trip a creep flag.
    Lock that in."""
    assert "Telephone Services" in EXCLUDED_FROM_CREEP


def test_lifestyle_creep_does_not_exclude_dues_and_subscriptions():
    """Regression for the inverse mistake: blanket-adding
    `Dues and Subscriptions` to creep exclusions would defeat the review."""
    assert "Dues and Subscriptions" not in EXCLUDED_FROM_CREEP


# ── Seeder/recurring consistency ─────────────────────────────────────────────


def test_seeder_recurring_categories_respect_boundary():
    """Every recurring row in dummy_data/recurring_transactions.json that
    sits in the utility/subscription space must use one of the canonical
    boundary categories — not invent a new label that bypasses the
    classification sets."""
    import json

    recurring = json.loads(
        (ROOT / "dummy_data" / "recurring_transactions.json").read_text(
            encoding="utf-8"
        )
    )

    # Merchant tokens that signal the row is utility-like or subscription-like.
    utility_tokens = ("DUKE", "ELECTRIC", "WATER", "GAS", "SPECTRUM", "T-MOBILE",
                      "VERIZON", "AT&T", "MINT MOBILE")
    subscription_tokens = ("NETFLIX", "SPOTIFY", "HULU", "DISNEY", "AMAZON PRIME",
                           "PLANET FITNESS", "AUDIBLE")

    for row in recurring:
        merchant = (row.get("merchant") or "").upper()
        cat = row.get("category")
        if any(tok in merchant for tok in utility_tokens):
            assert cat in UTILITY_LIKE_CATEGORIES, (
                f"Recurring row {merchant!r} looks utility-like but is "
                f"categorized as {cat!r} — should be in "
                f"UTILITY_LIKE_CATEGORIES ({sorted(UTILITY_LIKE_CATEGORIES)})."
            )
        if any(tok in merchant for tok in subscription_tokens):
            assert cat in OPTIONAL_SUBSCRIPTION_CATEGORIES, (
                f"Recurring row {merchant!r} looks subscription-like but is "
                f"categorized as {cat!r} — should be in "
                f"OPTIONAL_SUBSCRIPTION_CATEGORIES "
                f"({sorted(OPTIONAL_SUBSCRIPTION_CATEGORIES)})."
            )
