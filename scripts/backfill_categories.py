"""
scripts/backfill_categories.py — One-time backfill of uncategorized transactions.

Also callable from the API via POST /api/categorize/backfill.
Safe to re-run: only touches transactions where category = 'Uncategorized' or 'nan'.
"""

import logging
import sys
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.categorization import backfill_uncategorized

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-30s │ %(levelname)-7s │ %(message)s",
)
log = logging.getLogger("sentry.backfill_categories")


def main():
    log.info("Starting category backfill...")

    # Ensure schema is current
    init_db()

    with get_db() as conn:
        # Pre-backfill stats
        pre = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM transactions "
            "WHERE status != 'deleted' "
            "GROUP BY category ORDER BY cnt DESC"
        ).fetchall()

        print("\n── Before Backfill ──")
        for r in pre:
            print(f"  [{r['cnt']:5d}] {r['category']}")

        # Run backfill
        stats = backfill_uncategorized(conn)

        # Post-backfill stats
        post = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM transactions "
            "WHERE status != 'deleted' "
            "GROUP BY category ORDER BY cnt DESC"
        ).fetchall()

        print("\n── After Backfill ──")
        for r in post:
            print(f"  [{r['cnt']:5d}] {r['category']}")

        print(f"\n── Summary ──")
        print(f"  Matched:            {stats['matched']}")
        print(f"  Still uncategorized: {stats['still_uncategorized']}")
        print(f"  NaN cleaned:        {stats['cleaned_nan']}")


if __name__ == "__main__":
    main()
