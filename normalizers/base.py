"""
normalizers/base.py — Schema normalization for extracted financial data.

Ensures all DataFrames match the standard schema before storage.
"""
import pandas as pd
import logging

log = logging.getLogger("antigravity")

# Standard column schema for normalized financial transactions
STANDARD_COLUMNS = [
    "date",           # datetime64
    "txn_date",       # datetime64 (transaction date, may differ from posting)
    "amount",         # float64 (absolute value)
    "signed_amount",  # float64 (positive=credit, negative=debit)
    "direction",      # str ("Credit" or "Debit")
    "description",    # str
    "category",       # str
    "institution",    # str
    "account",        # str
]


def normalize(df: pd.DataFrame, institution: str, account: str) -> pd.DataFrame:
    """Normalize a DataFrame to the standard schema.

    - Fills missing columns with sensible defaults
    - Converts types
    - Sorts by date

    Returns a new DataFrame with exactly STANDARD_COLUMNS.
    """
    out = pd.DataFrame()

    # Required date column
    if "date" in df.columns:
        out["date"] = pd.to_datetime(df["date"], format="mixed", errors="coerce")
    else:
        log.warning("Missing 'date' column in %s/%s, using NaT", institution, account)
        out["date"] = pd.NaT

    # Optional txn_date, fall back to date
    if "txn_date" in df.columns:
        out["txn_date"] = pd.to_datetime(df["txn_date"], format="mixed", errors="coerce")
    else:
        out["txn_date"] = out["date"]

    # Amount
    if "amount" in df.columns:
        out["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).abs()
    else:
        out["amount"] = 0.0

    if "signed_amount" in df.columns:
        out["signed_amount"] = pd.to_numeric(df["signed_amount"], errors="coerce").fillna(0)
    else:
        out["signed_amount"] = 0.0

    # Direction
    if "direction" in df.columns:
        out["direction"] = df["direction"].astype(str)
    else:
        out["direction"] = out["signed_amount"].apply(lambda x: "Credit" if x >= 0 else "Debit")

    # Text fields
    out["description"] = df["description"].astype(str) if "description" in df.columns else ""
    out["category"] = df["category"].astype(str) if "category" in df.columns else "Uncategorized"
    out["institution"] = institution
    out["account"] = account

    return out.sort_values("date").reset_index(drop=True)
