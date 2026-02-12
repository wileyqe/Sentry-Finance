"""
storage/csv_writer.py — Writes normalized DataFrames to CSV with naming convention.
"""
import pathlib
from datetime import datetime
import pandas as pd
import logging

log = logging.getLogger("antigravity")


def write_csv(df: pd.DataFrame, institution: str, account: str,
              output_dir: pathlib.Path, timestamp: datetime | None = None) -> pathlib.Path:
    """Write a normalized DataFrame to CSV with a standardized filename.

    Naming convention: {institution}_{account}_{YYYYMMDD}.csv
    Example: Navy_Federal_Checking_20260212.csv

    Args:
        df: Normalized DataFrame to write
        institution: Institution name
        account: Account name
        output_dir: Directory to write to
        timestamp: Optional timestamp for the filename (defaults to now)

    Returns:
        Path to the written CSV file.
    """
    if timestamp is None:
        timestamp = datetime.now()

    # Sanitize names for filename
    safe_inst = institution.replace(" ", "_")
    safe_acct = account.replace(" ", "_")
    date_str = timestamp.strftime("%Y%m%d")

    filename = f"{safe_inst}_{safe_acct}_{date_str}.csv"
    output_path = output_dir / filename

    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(output_path, index=False)
    log.info("Wrote %d rows to %s", len(df), output_path.name)

    return output_path
