# P0-T04: Data Freshness Indicators (Backend)

## Context

You are working on Sentry Finance, a local-first personal finance app.
The system aggregates data from multiple financial institutions, each
refreshed at different intervals. The user needs to know how fresh
their data is — especially for TSP, which is the largest account and
may go weeks without an update.

This task builds the backend API for data freshness indicators.

## Starting State

- `institution_refresh_status` table tracks `last_success`, `last_failure`,
  `consecutive_failures` per institution
- `balance_snapshots` table has `as_of` timestamps per account
- `portfolio_snapshots` table has `timestamp` per investment account
- `refresh_events` table logs per-institution refresh outcomes
- TSP currently bypasses the orchestrator (script-only), so it may
  have no `institution_refresh_status` entry at all
- `config/refresh_policy.yaml` defines expected refresh intervals

## Task

### 1. New DAL Function

Create a new file `dal/freshness.py`:

```python
"""
dal/freshness.py — Data freshness tracking and staleness detection.

Computes per-institution and system-wide data freshness metrics.
Used by the dashboard to show freshness badges (green/yellow/red)
and by the notification system to trigger document drop nudges.
"""

def get_institution_freshness(conn) -> list[dict]:
    """
    Returns freshness status for every active institution.

    For each institution:
    {
        "institution_id": str,
        "display_name": str,
        "last_data_timestamp": str | None,  # most recent data point (any source)
        "hours_since_update": float | None,
        "staleness": "fresh" | "stale" | "critical" | "no_data",
        "expected_refresh_hours": int,
        "account_count": int,
    }

    Staleness thresholds:
      fresh:    <= expected_refresh_hours
      stale:    > expected_refresh_hours but <= 3x
      critical: > 3x expected_refresh_hours
      no_data:  no data points exist for this institution
    """
```

The function must check multiple data sources for the "last_data_timestamp":
1. `institution_refresh_status.last_success` (most common)
2. `balance_snapshots.as_of` for accounts in that institution (fallback
   for script-only institutions like TSP)
3. `portfolio_snapshots.timestamp` for investment accounts (fallback)

Use the MOST RECENT timestamp across all sources.

```python
def get_net_worth_data_age(conn) -> dict:
    """
    Returns the oldest data point contributing to the current net worth.

    This answers: "how old is the least-fresh piece of my net worth?"

    Returns:
    {
        "oldest_institution": str,
        "oldest_timestamp": str,
        "hours_since_oldest": float,
        "all_institutions_fresh": bool,
    }
    """
```

```python
def get_document_drop_status(conn) -> list[dict]:
    """
    Returns status for Tier 3 (document-drop) institutions.

    For each Tier 3 institution, check if a document has been
    ingested for the current month. Used by the nudge toast system.

    Returns:
    [
        {
            "institution_id": "tsp",
            "display_name": "TSP",
            "current_month_updated": bool,
            "last_document_date": str | None,
            "nudge_active": bool,  # True if past the 5th and no update
        }
    ]
    """
```

### 2. Read Refresh Policy

The function needs to know expected refresh intervals. Read from
`config/refresh_policy.yaml`. If the file doesn't define an institution,
use sensible defaults:

- CDP-based connectors: 24 hours (daily)
- Script-only (TSP): 720 hours (30 days — monthly document expected)
- Document-drop: 720 hours (30 days)

### 3. API Endpoints

Add these endpoints to an existing or new router:

- `GET /api/freshness` — returns `get_institution_freshness()` result
- `GET /api/freshness/net-worth-age` — returns `get_net_worth_data_age()`
- `GET /api/freshness/document-status` — returns `get_document_drop_status()`

### 4. Tier Classification

Add a tier classification to the institutions data. This can be a
simple dict in `dal/freshness.py`:

```python
# Ingestion tier per institution (see ARCHITECTURE.md Section 3.3)
INSTITUTION_TIERS = {
    "nfcu": 1,      # Full automation
    "chase": 1,
    "fidelity": 1,
    "acorns": 1,
    "affirm": 1,
    "tsp": 3,       # Document drop (will become Tier 2 when connector built)
    "mypay": 3,     # Document drop (future)
}
```

## Files to Create

1. `dal/freshness.py` — new DAL module
2. `backend/routers/freshness.py` — new API router (or add to existing
   dashboard router if one exists — check first)

## Files to Modify

1. `backend/api_server.py` — register the new router

## Files NOT to Modify

- `dal/derived.py`
- `dal/reports.py`
- `institution_refresh_status` table — read only, don't change schema
- Any connector files
- Any frontend files

## Constraints

- Read-only queries — this module never writes to the database
- Use `from dal.connection import get_db` for database access in routes
- Follow existing logging pattern: `log = logging.getLogger("sentry.dal.freshness")`
- Follow existing router patterns in `backend/routers/`
- Handle the case where `refresh_policy.yaml` doesn't exist (use defaults)
- Handle the case where an institution has no data at all (return "no_data")
- All timestamps should be compared in UTC

## Done Checklist

- [ ] `dal/freshness.py` exists with all 3 functions
- [ ] Freshness checks multiple data sources (refresh_status, balance_snapshots, portfolio_snapshots)
- [ ] Staleness thresholds implemented (fresh/stale/critical/no_data)
- [ ] Net worth data age returns the oldest contributing institution
- [ ] Document drop status checks current month for Tier 3 institutions
- [ ] API endpoints registered and functional
- [ ] Institution tier classification defined
- [ ] Works correctly when TSP has no refresh_status entry

## Verification

After completion, Claude will:
1. Read all created/modified files
2. Verify the freshness logic handles missing data gracefully
3. Verify API endpoints follow existing router patterns
4. Check that the tier classification matches ARCHITECTURE.md
5. Run a basic import check: `python -c "from dal.freshness import *"`
