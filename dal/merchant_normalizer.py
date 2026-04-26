"""
dal/merchant_normalizer.py

Normalizes raw transaction descriptions into canonical brand names.

Pipeline:
  description (raw) → normalize() → merchant (canonical)

Usage:
  backfill_merchant_column(conn)   — fills transactions.merchant for all rows

(Historical note: a `rebuild_merchant_snapshots(conn)` writer used to
live in this module and rebuild the `merchant_snapshots` aggregation
table at seed time. After the deprecated `scripts/seed_dummy_db.py`
seeder was deleted (AI-013, 2026-04-26), the function had zero
callers anywhere in the repo, and the readers it was meant to feed
(`dal.reports.merchant.get_merchant_list`,
`dal.reports.merchant.get_merchant_flow_data`) had always read
`transactions.merchant` directly via `COALESCE(merchant,
description)`. The function was removed under AI-023 on 2026-04-26.
The `merchant_snapshots` table itself remains in the schema —
dropping it requires a new migration; flag for a future
schema-cleanup pass.)
"""

import re
import sqlite3
import logging

log = logging.getLogger("sentry.dal.merchant_normalizer")

# ── Normalization rules ───────────────────────────────────────────────────────
# Ordered list of (compiled_regex, canonical_name).
# First match wins — put more specific patterns BEFORE more general ones.

_RULES: list[tuple[re.Pattern, str]] = [
    # ── E-commerce / Delivery ────────────────────────────────────────────────
    (re.compile(r"amazon|amzn|amz\b", re.I), "Amazon"),
    (re.compile(r"amazon\s*fresh|whole\s*foods", re.I), "Whole Foods"),

    # ── Streaming / Subscriptions ────────────────────────────────────────────
    (re.compile(r"netflix", re.I), "Netflix"),
    (re.compile(r"spotify", re.I), "Spotify"),
    (re.compile(r"hulu", re.I), "Hulu"),
    (re.compile(r"disney\+?|disney\s*plus", re.I), "Disney+"),
    (re.compile(r"apple\s*(tv|music|icloud|one|arcade|\+)", re.I), "Apple Services"),
    (re.compile(r"apple", re.I), "Apple"),
    (re.compile(r"google\s*(one|play|storage)", re.I), "Google"),
    (re.compile(r"youtube\s*(premium|tv)?", re.I), "YouTube"),
    (re.compile(r"microsoft|xbox", re.I), "Microsoft"),
    (re.compile(r"max\s*\(|hbo\s*max|hbomax", re.I), "Max (HBO)"),
    (re.compile(r"paramount\+?", re.I), "Paramount+"),
    (re.compile(r"sirius\s*xm|siriusxm", re.I), "SiriusXM"),
    (re.compile(r"audible", re.I), "Audible"),

    # ── Groceries ────────────────────────────────────────────────────────────
    (re.compile(r"kroger", re.I), "Kroger"),
    (re.compile(r"trader\s*joe", re.I), "Trader Joe's"),
    (re.compile(r"meijer", re.I), "Meijer"),
    (re.compile(r"fresh\s*thyme", re.I), "Fresh Thyme"),
    (re.compile(r"aldi", re.I), "Aldi"),
    (re.compile(r"whole\s*foods", re.I), "Whole Foods"),
    (re.compile(r"publix", re.I), "Publix"),
    (re.compile(r"safeway", re.I), "Safeway"),
    (re.compile(r"giant\s*eagle", re.I), "Giant Eagle"),
    (re.compile(r"target", re.I), "Target"),
    (re.compile(r"costco", re.I), "Costco"),
    (re.compile(r"walmart|wal-mart|wal mart", re.I), "Walmart"),
    (re.compile(r"sam'?s\s*club", re.I), "Sam's Club"),

    # ── Dining / Food delivery ───────────────────────────────────────────────
    (re.compile(r"chipotle", re.I), "Chipotle"),
    (re.compile(r"panera", re.I), "Panera Bread"),
    (re.compile(r"mcdonald'?s?|mcdonalds", re.I), "McDonald's"),
    (re.compile(r"starbucks", re.I), "Starbucks"),
    (re.compile(r"chick.fil.a|chickfila", re.I), "Chick-fil-A"),
    (re.compile(r"taco\s*bell", re.I), "Taco Bell"),
    (re.compile(r"burger\s*king", re.I), "Burger King"),
    (re.compile(r"wendy'?s", re.I), "Wendy's"),
    (re.compile(r"subway", re.I), "Subway"),
    (re.compile(r"domino'?s", re.I), "Domino's"),
    (re.compile(r"pizza\s*hut", re.I), "Pizza Hut"),
    (re.compile(r"olive\s*garden", re.I), "Olive Garden"),
    (re.compile(r"applebee'?s", re.I), "Applebee's"),
    (re.compile(r"longhorn\s*steak", re.I), "LongHorn Steakhouse"),
    (re.compile(r"texas\s*roadhouse", re.I), "Texas Roadhouse"),
    (re.compile(r"cracker\s*barrel", re.I), "Cracker Barrel"),
    (re.compile(r"ihop", re.I), "IHOP"),
    (re.compile(r"dunkin|dunkin'?\s*donuts", re.I), "Dunkin'"),
    (re.compile(r"five\s*guys", re.I), "Five Guys"),
    (re.compile(r"amc\b", re.I), "AMC Theatres"),
    (re.compile(r"uber\s*eats|ubereats", re.I), "Uber Eats"),
    (re.compile(r"doordash", re.I), "DoorDash"),
    (re.compile(r"grubhub", re.I), "Grubhub"),
    (re.compile(r"instacart", re.I), "Instacart"),

    # ── Transportation / Auto ────────────────────────────────────────────────
    (re.compile(r"uber", re.I), "Uber"),
    (re.compile(r"lyft", re.I), "Lyft"),
    (re.compile(r"speedway", re.I), "Speedway"),
    (re.compile(r"\bbp\b|bp\s*#|\bbp\s+", re.I), "BP"),
    (re.compile(r"shell", re.I), "Shell"),
    (re.compile(r"exxon|esso", re.I), "Exxon"),
    (re.compile(r"chevron", re.I), "Chevron"),
    (re.compile(r"sunoco", re.I), "Sunoco"),
    (re.compile(r"marathon", re.I), "Marathon"),
    (re.compile(r"meijer\s*gas|meijer\s*fuel", re.I), "Meijer"),
    (re.compile(r"crew\s*carwash|crew\s*car\s*wash", re.I), "Crew Carwash"),
    (re.compile(r"jiffy\s*lube", re.I), "Jiffy Lube"),
    (re.compile(r"autozone", re.I), "AutoZone"),
    (re.compile(r"o'reilly|oreilly\s*auto", re.I), "O'Reilly Auto"),

    # ── Retail / Shopping ────────────────────────────────────────────────────
    (re.compile(r"best\s*buy", re.I), "Best Buy"),
    (re.compile(r"home\s*depot", re.I), "Home Depot"),
    (re.compile(r"lowe'?s", re.I), "Lowe's"),
    (re.compile(r"ikea", re.I), "IKEA"),
    (re.compile(r"tj\s*maxx|tjmaxx|t\.j\.maxx", re.I), "TJ Maxx"),
    (re.compile(r"marshall'?s", re.I), "Marshalls"),
    (re.compile(r"ross\b", re.I), "Ross"),
    (re.compile(r"old\s*navy", re.I), "Old Navy"),
    (re.compile(r"gap\b", re.I), "Gap"),
    (re.compile(r"h\s*&\s*m|h&m", re.I), "H&M"),
    (re.compile(r"zara", re.I), "Zara"),
    (re.compile(r"hobby\s*lobby", re.I), "Hobby Lobby"),
    (re.compile(r"michael'?s", re.I), "Michaels"),
    (re.compile(r"bath\s*&?\s*body", re.I), "Bath & Body Works"),
    (re.compile(r"sephora", re.I), "Sephora"),
    (re.compile(r"ulta", re.I), "Ulta Beauty"),
    (re.compile(r"dick'?s\s*sporting|dicks\s*sporting", re.I), "Dick's Sporting"),
    (re.compile(r"rei\b", re.I), "REI"),
    (re.compile(r"petco", re.I), "Petco"),
    (re.compile(r"petsmart", re.I), "PetSmart"),
    (re.compile(r"chewy", re.I), "Chewy"),
    (re.compile(r"wayfair", re.I), "Wayfair"),

    # ── Healthcare / Pharmacy ─────────────────────────────────────────────────
    (re.compile(r"cvs", re.I), "CVS"),
    (re.compile(r"walgreen'?s|walgreens", re.I), "Walgreens"),
    (re.compile(r"rite\s*aid", re.I), "Rite Aid"),
    (re.compile(r"cvs\s*health|minuteclinic", re.I), "CVS"),

    # ── Utilities / Bills ─────────────────────────────────────────────────────
    (re.compile(r"citizens\s*gas", re.I), "Citizens Gas"),
    (re.compile(r"comcast|xfinity", re.I), "Comcast/Xfinity"),
    (re.compile(r"at&t|att\b", re.I), "AT&T"),
    (re.compile(r"verizon", re.I), "Verizon"),
    (re.compile(r"t-mobile|tmobile", re.I), "T-Mobile"),
    (re.compile(r"spectrum", re.I), "Spectrum"),
    (re.compile(r"cox\s*comm", re.I), "Cox"),

    # ── Finance / Transfers ───────────────────────────────────────────────────
    (re.compile(r"rocket\s*mortgage", re.I), "Rocket Mortgage"),
    (re.compile(r"nfcu|navy\s*federal", re.I), "Navy Federal"),
    (re.compile(r"acorns", re.I), "Acorns"),
    (re.compile(r"fidelity", re.I), "Fidelity"),
    (re.compile(r"paypal", re.I), "PayPal"),
    (re.compile(r"venmo", re.I), "Venmo"),
    (re.compile(r"zelle", re.I), "Zelle"),

    # ── Income ───────────────────────────────────────────────────────────────
    (re.compile(r"acme\s*corp\s*payroll|payroll", re.I), "Payroll"),

    # ── Gym / Fitness ────────────────────────────────────────────────────────
    (re.compile(r"planet\s*fitness", re.I), "Planet Fitness"),
    (re.compile(r"crunch\s*fitness", re.I), "Crunch Fitness"),
    (re.compile(r"equinox", re.I), "Equinox"),
    (re.compile(r"gold'?s\s*gym", re.I), "Gold's Gym"),
    (re.compile(r"peloton", re.I), "Peloton"),
]

# ── Noise patterns to strip from unmatched descriptions ─────────────────────
_NOISE = re.compile(
    r"\s+#\d+|\s*\d{3,}\s*|\s+(LLC|INC|CORP|CO\.?)\b"
    r"|\b(SEATTLE|CHICAGO|NEW\s*YORK|WA|IL|NY|IN|OH|CA)\b"
    r"|\s+\d{4,}",
    re.I,
)


def normalize(description: str) -> str:
    """Return canonical merchant name for a raw transaction description."""
    if not description:
        return "Unknown"
    desc = description.strip()
    for pattern, canonical in _RULES:
        if pattern.search(desc):
            return canonical
    # No match — strip noise and title-case the remainder
    cleaned = _NOISE.sub("", desc).strip().title()
    return cleaned if cleaned else desc.title()


# ── Backfill ──────────────────────────────────────────────────────────────────


def backfill_merchant_column(conn: sqlite3.Connection) -> int:
    """Set transactions.merchant for all rows using normalize().

    Returns number of rows updated.
    """
    rows = conn.execute(
        "SELECT id, description FROM transactions WHERE merchant IS NULL OR merchant = ''"
    ).fetchall()

    updated = 0
    for row in rows:
        merchant = normalize(row["description"] or "")
        conn.execute(
            "UPDATE transactions SET merchant = ? WHERE id = ?",
            (merchant, row["id"]),
        )
        updated += 1

    conn.commit()
    log.info(f"Backfilled merchant column for {updated} transactions")
    return updated


# ── Snapshot rebuild ──────────────────────────────────────────────────────────
#
# `rebuild_merchant_snapshots` was removed under AI-023 (2026-04-26).
# It was the only writer for the `merchant_snapshots` table, and after
# the AI-013 deletion of `scripts/seed_dummy_db.py` it had zero
# callers. See module docstring for the full removal note. The
# `INCOME_CATEGORIES` / `EXCLUDED_FROM_SPEND` imports it relied on
# were also dropped at the same time.
