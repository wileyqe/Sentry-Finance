"""Dev-mode utilities exposed to the dashboard.

These endpoints exist to make local development with synthetic data
ergonomic. They are local-first and never reach the network — but
they should NOT be exposed in any deployed build.

Currently:
  POST /api/dev/advance-dummy-data
    Re-runs the rolling dummy-data seeder with end_date pushed one
    day forward from the current max transaction date. Useful when
    a long dev session crosses midnight on yesterday's data and you
    want to nudge the dataset forward without restarting the server.
"""

import logging
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException

from dal.database import get_db
from backend.events import broadcast_event

log = logging.getLogger("sentry.backend.api.dev")

router = APIRouter(tags=["dev"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SEED_SCRIPT = _PROJECT_ROOT / "scripts" / "seed_dummy_data.py"


def _current_max_data_date() -> date | None:
    """Return the latest posting_date currently in the transactions table."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT MAX(posting_date) AS max_date FROM transactions"
        ).fetchone()
    if not row or not row["max_date"]:
        return None
    try:
        return datetime.strptime(row["max_date"], "%Y-%m-%d").date()
    except ValueError:
        return None


@router.post("/api/dev/advance-dummy-data")
def advance_dummy_data():
    """Push the synthetic dataset one day forward.

    Computes the next end_date as max(current data date, today's
    yesterday) + 1, capped at today, then re-runs the rolling seeder
    with that as --end-date. The seeder regenerates the trailing
    3-year window so balances, transactions, recurring patterns,
    credit scores, and snapshots all advance together.
    """
    if not _SEED_SCRIPT.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Seeder script not found at {_SEED_SCRIPT}",
        )

    today = date.today()
    current_max = _current_max_data_date() or (today - timedelta(days=2))

    # Always advance by at least one day. Cap at today so we don't
    # generate "future" data the user can't intuit.
    new_end = min(current_max + timedelta(days=1), today)
    if new_end <= current_max:
        # Already at the cap — nothing to do, but the click should
        # still feel responsive. Re-broadcast so the UI refetches.
        broadcast_event("refresh_complete", {
            "trigger": "dev_advance_dummy_data",
            "advanced_to": current_max.isoformat(),
            "previous_max": current_max.isoformat(),
            "no_op": True,
        })
        return {
            "ok": True,
            "advanced_to": current_max.isoformat(),
            "previous_max": current_max.isoformat(),
            "no_op": True,
        }

    log.info(
        "Dev advance: re-seeding rolling window with end_date=%s "
        "(was %s)",
        new_end.isoformat(),
        current_max.isoformat(),
    )

    cmd = [
        sys.executable,
        str(_SEED_SCRIPT),
        "--end-date",
        new_end.isoformat(),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        log.error(
            "Dev advance seeder failed (rc=%s)\nSTDOUT:\n%s\nSTDERR:\n%s",
            proc.returncode,
            proc.stdout[-2000:],
            proc.stderr[-2000:],
        )
        raise HTTPException(
            status_code=500,
            detail=f"Seeder failed with exit code {proc.returncode}",
        )

    broadcast_event("refresh_complete", {
        "trigger": "dev_advance_dummy_data",
        "advanced_to": new_end.isoformat(),
        "previous_max": current_max.isoformat(),
    })

    return {
        "ok": True,
        "advanced_to": new_end.isoformat(),
        "previous_max": current_max.isoformat(),
    }
