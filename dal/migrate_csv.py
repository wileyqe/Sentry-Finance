"""
dal/migrate_csv.py — One-time migration of existing CSV data into SQLite.

Reads the flat CSV files from data/extracted/ and upserts them into the
SQLite database, preserving all existing transaction data.

Usage:
    python -m dal.migrate_csv          # Migrate all CSVs
    python -m dal.migrate_csv --dry-run  # Preview without writing
"""
import argparse
import logging
import pathlib
import sys

import pandas as pd

# Add project root to path
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db, seed_institutions
from dal.transactions import upsert_transactions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sentry")

# ── Institution → account mapping (guessed from filenames) ───────────────────

_ACCOUNT_MAP = {
    # Navy Federal
    ("Navy Federal", "Checking"):            "nfcu_1167",
    ("Navy Federal", "Mortgage Checking"):    "nfcu_0459",
    ("Navy_Federal", "Checking"):             "nfcu_1167",
    ("Navy_Federal", "Mortgage_Checking"):    "nfcu_0459",
    ("Navy_Federal", "Auto_Loan"):            "nfcu_3533",
    ("Navy_Federal", "Credit_Card"):          "nfcu_0837",
    ("Navy Federal", "Auto Loan"):            "nfcu_3533",
    ("Navy Federal", "Credit Card"):          "nfcu_0837",
    # Chase
    ("Chase", "Checking"):                    "chase_8973",
    ("Chase", "Credit Card"):                 "chase_8115",
    ("Chase", "Credit_Card"):                 "chase_8115",
}

_INST_MAP = {
    "Navy Federal": "nfcu",
    "Navy_Federal": "nfcu",
    "Chase":        "chase",
}


def _resolve_account(institution: str, account: str) -> tuple[str, str]:
    """Resolve institution and account IDs from CSV metadata."""
    account_id = _ACCOUNT_MAP.get((institution, account))
    institution_id = _INST_MAP.get(institution, institution.lower())

    if not account_id:
        # Try with underscored names
        inst_clean = institution.replace(" ", "_")
        acct_clean = account.replace(" ", "_")
        account_id = _ACCOUNT_MAP.get((inst_clean, acct_clean))

    if not account_id:
        # Generate a fallback ID
        safe = account.replace(" ", "_").lower()[:10]
        account_id = f"{institution_id}_{safe}"
        log.warning("Could not resolve account for %s/%s, "
                    "using fallback: %s", institution, account,
                    account_id)

    return institution_id, account_id


def migrate_csv_file(csv_path: pathlib.Path,
                     conn, dry_run: bool = False) -> dict:
    """Migrate a single CSV file into the database.

    Expects the CSV to have the standard normalized schema columns:
    date, txn_date, amount, signed_amount, direction, description,
    category, institution, account
    """
    df = pd.read_csv(csv_path)
    if df.empty:
        log.info("  ⚠  Empty CSV: %s", csv_path.name)
        return {"file": csv_path.name, "rows": 0,
                "inserted": 0, "updated": 0}

    # Detect institution/account from CSV content
    institution = df["institution"].iloc[0] if "institution" in df.columns else "Unknown"
    account = df["account"].iloc[0] if "account" in df.columns else "Unknown"

    institution_id, account_id = _resolve_account(institution, account)

    # Build transaction dicts
    txns = []
    for _, row in df.iterrows():
        posting_date = str(row.get("date", ""))[:10]  # YYYY-MM-DD
        txn_date = str(row.get("txn_date", ""))[:10] if pd.notna(
            row.get("txn_date")) else None

        txns.append({
            "account_id": account_id,
            "institution_id": institution_id,
            "posting_date": posting_date,
            "transaction_date": txn_date,
            "amount": abs(float(row.get("amount", 0))),
            "signed_amount": float(row.get("signed_amount", 0)),
            "direction": str(row.get("direction", "Debit")),
            "description": str(row.get("description", "")),
            "category": str(row.get("category", "Uncategorized")),
            "status": "posted",
            "raw_description": str(row.get("description", "")),
        })

    if dry_run:
        log.info("  📋  [DRY RUN] %s: %d rows → %s/%s",
                 csv_path.name, len(txns), institution_id,
                 account_id)
        return {"file": csv_path.name, "rows": len(txns),
                "inserted": 0, "updated": 0, "dry_run": True}

    stats = upsert_transactions(conn, txns)
    log.info("  ✔  %s: %d rows → %d inserted, %d updated, "
             "%d unchanged",
             csv_path.name, len(txns), stats["inserted"],
             stats["updated"], stats["unchanged"])

    return {
        "file": csv_path.name,
        "rows": len(txns),
        **stats,
    }


def migrate_all(dry_run: bool = False) -> list[dict]:
    """Migrate all CSVs from data/extracted/ into SQLite."""
    csv_dir = ROOT / "data" / "extracted"
    if not csv_dir.exists():
        log.error("No data/extracted/ directory found")
        return []

    csv_files = sorted(csv_dir.glob("*.csv"))
    if not csv_files:
        log.warning("No CSV files found in %s", csv_dir)
        return []

    print(f"\n  📦  CSV → SQLite Migration")
    print(f"  📂  Source: {csv_dir}")
    print(f"  📊  Files:  {len(csv_files)}")
    if dry_run:
        print(f"  🔍  Mode:   DRY RUN\n")
    else:
        print()

    # Ensure DB is initialized and seeded
    init_db()
    seed_institutions()

    results = []
    with get_db() as conn:
        for csv_path in csv_files:
            try:
                result = migrate_csv_file(csv_path, conn,
                                          dry_run=dry_run)
                results.append(result)
            except Exception as e:
                log.error("  ✗  Failed to migrate %s: %s",
                          csv_path.name, e)
                results.append({
                    "file": csv_path.name, "error": str(e)
                })

        if not dry_run:
            conn.commit()
            log.info("Migration committed to database")

    # Summary
    total_rows = sum(r.get("rows", 0) for r in results)
    total_inserted = sum(r.get("inserted", 0) for r in results)
    total_updated = sum(r.get("updated", 0) for r in results)
    print(f"\n  {'─' * 50}")
    print(f"  ✅  Migration complete: {total_rows:,} rows "
          f"({total_inserted:,} inserted, {total_updated:,} updated)")
    print()

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate CSV data into SQLite"
    )
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Preview without writing")
    args = parser.parse_args()
    migrate_all(dry_run=args.dry_run)

