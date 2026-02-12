"""
loaders.py — CSV data loading and normalization for all institutions.

Provides load_nfcu() and load_chase() which produce standardized DataFrames.
"""
import pathlib, logging
import pandas as pd
from config import cfg

log = logging.getLogger("antigravity")


# ─── Column Helpers ──────────────────────────────────────────────────────────

def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace and stray quotes from column names."""
    df.columns = (
        df.columns.str.strip()
                  .str.strip("'\"")
                  .str.strip()
    )
    return df


def _find_col(df: pd.DataFrame, *candidates: str) -> str | None:
    """Return the first column name that exists (case-insensitive)."""
    lower_map = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def _require_col(df: pd.DataFrame, context: str, *candidates: str) -> str | None:
    """Like _find_col but logs a warning if the column is missing."""
    col = _find_col(df, *candidates)
    if col is None:
        log.warning("%s: expected one of %s, found columns: %s",
                    context, candidates, list(df.columns))
    return col


# ─── Institution Loaders ─────────────────────────────────────────────────────

def load_nfcu(path: pathlib.Path, institution: str, account: str) -> pd.DataFrame:
    df = _clean_columns(pd.read_csv(path))

    date_col = _require_col(df, path.name, "Posting Date")
    txn_date_col = _find_col(df, "Transaction Date")
    amount_col = _require_col(df, path.name, "Amount")
    dir_col = _find_col(df, "Credit Debit Indicator")
    desc_col = _require_col(df, path.name, "Description")
    cat_col = _find_col(df, "Category")

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[date_col], format="mixed")
    out["txn_date"] = pd.to_datetime(df[txn_date_col] if txn_date_col else df[date_col], format="mixed")
    out["amount"] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0)
    direction = df[dir_col].astype(str).str.strip().str.lower() if dir_col else "debit"
    out["signed_amount"] = out["amount"].where(direction == "credit", -out["amount"])
    out["direction"] = direction.str.title() if dir_col else "Debit"
    out["description"] = df[desc_col].astype(str) if desc_col else ""
    out["category"] = df[cat_col].astype(str) if cat_col else "Uncategorized"
    out["institution"] = institution
    out["account"] = account
    return out


def load_chase(path: pathlib.Path, institution: str, account: str) -> pd.DataFrame:
    df = _clean_columns(pd.read_csv(path))

    date_col = _require_col(df, path.name, "Posting Date", "Post Date")
    txn_date_col = _find_col(df, "Transaction Date") or date_col
    amount_col = _require_col(df, path.name, "Amount")
    desc_col = _require_col(df, path.name, "Description")
    type_col = _find_col(df, "Type")
    details_col = _find_col(df, "Details")

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[date_col], format="mixed")
    out["txn_date"] = pd.to_datetime(df[txn_date_col], format="mixed")
    out["amount"] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0)

    if details_col:
        # Chase Checking: amounts already signed (negative = debit)
        out["signed_amount"] = out["amount"]
    else:
        # Chase CC: amounts positive, "Payment" type → credit, else debit
        types = df[type_col].astype(str).str.strip().str.lower() if type_col else "sale"
        out["signed_amount"] = out["amount"].where(types == "payment", -out["amount"])

    out["amount"] = out["amount"].abs()
    out["direction"] = out["signed_amount"].apply(lambda x: "Credit" if x >= 0 else "Debit")
    out["description"] = df[desc_col].astype(str) if desc_col else ""
    out["category"] = "Uncategorized"  # Filled by categorization pipeline
    out["institution"] = institution
    out["account"] = account
    return out


# ─── Loader Registry ────────────────────────────────────────────────────────

LOADERS = {"nfcu": load_nfcu, "chase": load_chase}


def load_all(base_path: pathlib.Path) -> pd.DataFrame:
    """Load all CSVs from config, concatenate, and return sorted DataFrame."""
    frames = []
    for src in cfg.data_sources:
        path = base_path / src["path"]
        loader = LOADERS[src["loader"]]
        if not path.exists():
            print(f"  ⚠  Skipped (not found): {path.name}")
            continue
        try:
            df = loader(path, src["institution"], src["account"])
            frames.append(df)
            print(f"  ✔  {path.name}  →  {len(df)} rows")
        except Exception as e:
            log.error("Failed to load %s: %s", path.name, e)

    if not frames:
        raise RuntimeError("No CSV files loaded. Check config.yaml data_sources.")

    return pd.concat(frames, ignore_index=True).sort_values("date")
