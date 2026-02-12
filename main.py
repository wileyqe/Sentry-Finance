"""
main.py — CLI entry point for the extraction pipeline.

Usage:
    python main.py                  # Run all extractors
    python main.py --institution nfcu   # Run only NFCU
    python main.py --dry-run        # Show what would be extracted
"""
import argparse
import logging
import pathlib
import sys
from datetime import datetime

from extractors.nfcu import NFCUExtractor
from extractors.chase import ChaseExtractor
from extractors.nfcu_browser import NFCUBrowserExtractor
from normalizers.base import normalize
from validators.schema import validate
from storage.csv_writer import write_csv

# ─── Setup ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("antigravity")

BASE = pathlib.Path(__file__).resolve().parent
OUTPUT_DIR = BASE / "data" / "extracted"

# Registry of available extractors
EXTRACTORS = {
    "nfcu": NFCUExtractor,
    "chase": ChaseExtractor,
    "nfcu-browser": NFCUBrowserExtractor,
}


def run_pipeline(institutions: list[str] | None = None, dry_run: bool = False):
    """Run the full extraction → normalize → validate → store pipeline."""

    targets = institutions or list(EXTRACTORS.keys())
    total_rows = 0
    total_files = 0

    print(f"\n  🚀  Extraction Pipeline — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  📋  Targets: {', '.join(targets)}")
    print(f"  📂  Output:  {OUTPUT_DIR}\n")

    for key in targets:
        if key not in EXTRACTORS:
            log.warning("Unknown institution: %s (available: %s)", key, list(EXTRACTORS.keys()))
            continue

        extractor = EXTRACTORS[key]()
        print(f"  ── {extractor.institution} {'─' * (40 - len(extractor.institution))}")

        # 1. Extract
        try:
            if "browser" in key:
                results = extractor.extract()
            else:
                results = extractor.extract(base_path=BASE)
        except Exception as e:
            log.error("  ✗ Extraction failed for %s: %s", key, e)
            continue

        if not results:
            print(f"  ⚠  No data found for {extractor.institution}")
            continue

        for result in results:
            # 2. Normalize
            normalized = normalize(result.df, result.institution, result.account)

            # 3. Validate
            issues = validate(normalized)
            critical = [i for i in issues if "Missing" in i]
            if critical:
                log.warning("  ⚠ Validation issues for %s/%s: %s",
                            result.institution, result.account, critical)

            if dry_run:
                print(f"  📊  [DRY RUN] {result.account}: {result.row_count} rows")
                continue

            # 4. Store
            path = write_csv(normalized, result.institution, result.account,
                             OUTPUT_DIR, result.timestamp)
            print(f"  ✔  {result.account}: {result.row_count} rows → {path.name}")
            total_rows += result.row_count
            total_files += 1

    print(f"\n  {'─' * 50}")
    if dry_run:
        print(f"  📋  Dry run complete — no files written")
    else:
        print(f"  ✅  Done: {total_rows:,} rows across {total_files} files")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Project Antigravity — Financial Data Extraction Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--institution", "-i",
        choices=list(EXTRACTORS.keys()),
        nargs="+",
        help="Specific institution(s) to extract (default: all)",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be extracted without writing files",
    )
    parser.add_argument(
        "--browser", "-b",
        action="store_true",
        help="Use browser-based extractors instead of CSV-based",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_extractors",
        help="List available extractors and exit",
    )
    args = parser.parse_args()

    if args.list_extractors:
        print("\nAvailable extractors:")
        for key, cls in EXTRACTORS.items():
            ext = cls()
            print(f"  {key:10s} → {ext.institution}")
        print()
        sys.exit(0)

    # If --browser flag, swap CSV extractors for browser variants
    institutions = args.institution
    if args.browser and not institutions:
        institutions = [k for k in EXTRACTORS if "browser" in k]
    elif args.browser and institutions:
        institutions = [f"{i}-browser" if f"{i}-browser" in EXTRACTORS else i
                        for i in institutions]

    run_pipeline(institutions=institutions, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
