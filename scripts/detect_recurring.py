"""
scripts/detect_recurring.py — Scan transaction history for recurring patterns.

Safe to re-run. Creates/updates recurring_transactions entries, detects
price mutations, and deactivates cancelled items.
"""

import logging
import sys
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.recurring import detect_recurring, get_recurring, get_monthly_recurring_total

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
)
log = logging.getLogger("sentry.detect_recurring")


def main():
    log.info("Starting recurring transaction detection...")

    # Ensure schema is current
    init_db()

    with get_db() as conn:
        # Run detection
        stats = detect_recurring(conn)

        print(f"\n-- Scan Results --")
        print(f"  Created:     {stats['created']}")
        print(f"  Updated:     {stats['updated']}")
        print(f"  Deactivated: {stats['deactivated']}")

        # Show active recurring
        active = get_recurring(conn, status="active")
        inactive = get_recurring(conn, status="inactive")

        print(f"\n-- Active Recurring ({len(active)}) --")
        for r in active:
            stable = "$" + f"{r['expected_amount']:.2f}" if r["expected_amount"] else "varies"
            print(
                f"  {r['frequency']:10s} | {stable:>12s} | "
                f"{r['category'] or 'N/A':25s} | {r['merchant'][:40]}"
            )

        if inactive:
            print(f"\n-- Inactive ({len(inactive)}) --")
            for r in inactive:
                print(f"  {r['frequency']:10s} | {r['merchant'][:40]} | last: {r['last_date']}")

        # Monthly totals
        totals = get_monthly_recurring_total(conn)
        print(f"\n-- Monthly Recurring Total: ${totals['total']:.2f} --")
        for cat, amt in sorted(totals["by_category"].items(), key=lambda x: -x[1]):
            print(f"  ${amt:>8.2f}  {cat}")


if __name__ == "__main__":
    main()
