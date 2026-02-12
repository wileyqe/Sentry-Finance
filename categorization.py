"""
categorization.py — Unified categorization pipeline.

Priority: category_map.json override > keyword match > CSV category > "Uncategorized"
"""
import json, pathlib, logging
import pandas as pd
from config import cfg

log = logging.getLogger("antigravity")

BASE = pathlib.Path(__file__).resolve().parent
CATEGORY_MAP_FILE = BASE / "category_map.json"


# ─── Persistence ─────────────────────────────────────────────────────────────

def load_category_map() -> dict:
    """Load manual category overrides from JSON."""
    if CATEGORY_MAP_FILE.exists():
        try:
            with open(CATEGORY_MAP_FILE, "r") as f:
                return json.load(f)
        except Exception:
            log.warning("Failed to load category_map.json, using empty map")
            return {}
    return {}


def save_category_map(mapping: dict):
    """Save manual category overrides to JSON."""
    with open(CATEGORY_MAP_FILE, "w") as f:
        json.dump(mapping, f, indent=2)


# ─── Keyword Matching ────────────────────────────────────────────────────────

def keyword_categorize(description: str) -> str | None:
    """Unified keyword matcher. Returns category or None."""
    desc_upper = str(description).upper()
    for key, cat in cfg.chase_keyword_map.items():
        if key in desc_upper:
            return cat
    return None


# ─── Pipeline ────────────────────────────────────────────────────────────────

def apply_categorization(df: pd.DataFrame) -> pd.DataFrame:
    """Apply full categorization pipeline to a DataFrame.

    1. Keyword match for generic categories
    2. Manual overrides from category_map.json
    """
    # Step 1: Keyword match for Uncategorized/General rows
    generic_mask = df["category"].isin(["Uncategorized", "General", ""])
    if generic_mask.any():
        keyword_cats = df.loc[generic_mask, "description"].apply(keyword_categorize)
        df.loc[generic_mask, "category"] = keyword_cats.fillna("Uncategorized")

    # Step 2: Manual overrides (highest priority)
    cat_map = load_category_map()
    overrides = df["description"].map(cat_map)
    df["category"] = overrides.fillna(df["category"])

    return df
