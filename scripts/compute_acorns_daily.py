"""
scripts/compute_acorns_daily.py — DEPRECATED SHIM.

The Acorns daily portfolio computation has been moved into
`dal/derived.py` as `compute_acorns_portfolio_snapshots()`,
which is automatically called by the orchestrator after each
successful Acorns refresh via `recompute_for_institution()`.

This script now delegates to that function for backward
compatibility (e.g. manual one-off backfills from the CLI).

Usage:
    python scripts/compute_acorns_daily.py
    python scripts/compute_acorns_daily.py --days 30
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.derived import compute_acorns_portfolio_snapshots

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill Acorns daily portfolio snapshots (delegates to dal/derived.py)"
    )
    parser.add_argument(
        "--days", type=int, default=90, help="Number of days to backfill (default: 90)"
    )
    args = parser.parse_args()

    print(f"\n  📊  Acorns Portfolio Backfill ({args.days} days)")
    print("  ℹ️   Logic lives in dal/derived.compute_acorns_portfolio_snapshots()\n")

    init_db()
    with get_db() as conn:
        inserted = compute_acorns_portfolio_snapshots(conn, days=args.days)
        conn.commit()

    print(f"\n  ✔  Done — inserted {inserted} new portfolio snapshot(s)")
