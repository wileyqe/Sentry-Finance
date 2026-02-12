"""
validators/schema.py — Validates DataFrames against the standard schema.
"""
import pandas as pd
import logging
from normalizers.base import STANDARD_COLUMNS

log = logging.getLogger("antigravity")


class ValidationError(Exception):
    """Raised when a DataFrame fails schema validation."""
    pass


def validate(df: pd.DataFrame, strict: bool = False) -> list[str]:
    """Validate a DataFrame against the standard schema.

    Args:
        df: DataFrame to validate
        strict: If True, raises ValidationError on failure. If False, returns warnings.

    Returns:
        List of warning/error messages (empty if valid).
    """
    issues = []

    # Check for required columns
    missing = set(STANDARD_COLUMNS) - set(df.columns)
    if missing:
        issues.append(f"Missing columns: {sorted(missing)}")

    # Check for extra columns (warning only)
    extra = set(df.columns) - set(STANDARD_COLUMNS)
    if extra:
        issues.append(f"Extra columns (ignored): {sorted(extra)}")

    # Check for empty DataFrame
    if len(df) == 0:
        issues.append("DataFrame is empty")

    # Check date column is datetime
    if "date" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["date"]):
        issues.append(f"'date' column is {df['date'].dtype}, expected datetime64")

    # Check amount column is numeric
    if "amount" in df.columns and not pd.api.types.is_numeric_dtype(df["amount"]):
        issues.append(f"'amount' column is {df['amount'].dtype}, expected numeric")

    # Check signed_amount column is numeric
    if "signed_amount" in df.columns and not pd.api.types.is_numeric_dtype(df["signed_amount"]):
        issues.append(f"'signed_amount' column is {df['signed_amount'].dtype}, expected numeric")

    # Check for NaT dates
    if "date" in df.columns:
        nat_count = df["date"].isna().sum()
        if nat_count > 0:
            issues.append(f"{nat_count} NaT (missing) dates found")

    # Log and optionally raise
    for issue in issues:
        log.warning("Schema validation: %s", issue)

    if strict and issues:
        raise ValidationError("; ".join(issues))

    return issues
