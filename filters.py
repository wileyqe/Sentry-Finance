"""
filters.py — Data filtering for income/expense calculations.
"""
import pandas as pd
from config import cfg


def filter_data(all_data: pd.DataFrame, months_available: list,
                month_range: list, institution: str, account: str,
                cat_filter: list | None = None):
    """Apply all filters and return (filtered, expenses, income) DataFrames.

    Args:
        cat_filter: Optional list of categories to include. If None, all shown.
    """
    m_start = months_available[month_range[0]]
    m_end   = months_available[month_range[1]]
    mask = (all_data["month"] >= m_start) & (all_data["month"] <= m_end)
    if institution != "ALL":
        mask &= all_data["institution"] == institution
    if account != "ALL":
        mask &= all_data["account"] == account

    # Apply category filter early (#11) — before computing inc/exp
    if cat_filter:
        mask &= all_data["category"].isin(cat_filter)

    filtered = all_data[mask]

    # Exclude internal moves from Income/Expense to avoid double counting
    exc_cats = cfg.excluded_categories

    exp = filtered[(filtered["signed_amount"] < 0) & (~filtered["category"].isin(exc_cats))].copy()
    exp["abs_amount"] = exp["amount"]

    inc = filtered[(filtered["signed_amount"] > 0) & (~filtered["category"].isin(exc_cats))].copy()

    return filtered, exp, inc
