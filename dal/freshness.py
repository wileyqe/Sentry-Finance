"""
dal/freshness.py — Data freshness tracking and staleness detection.

Computes per-institution and system-wide data freshness metrics.
Used by the dashboard to show freshness badges (green/yellow/red)
and by the notification system to trigger document drop nudges.
"""

import functools
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

log = logging.getLogger("sentry.dal.freshness")

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

@functools.lru_cache(maxsize=1)
def _get_refresh_policy():
    """Return the parsed refresh-policy YAML, cached at module level.

    The file doesn't change between restarts; tests that mutate the YAML
    should call ``_get_refresh_policy.cache_clear()``.
    """
    import yaml
    policy_path = Path("config/refresh_policy.yaml")
    if policy_path.exists():
        try:
            with open(policy_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}

def _get_expected_refresh_hours(institution_id: str, policy: dict) -> int:
    # Check policy file first
    if policy and "institutions" in policy:
        inst_policy = policy["institutions"].get(institution_id)
        if inst_policy and "expected_refresh_hours" in inst_policy:
            return int(inst_policy["expected_refresh_hours"])
            
    # Fallbacks based on tier
    tier = INSTITUTION_TIERS.get(institution_id, 1)
    if tier == 3:
        return 720
    return 24

def get_institution_freshness(conn: sqlite3.Connection, owner_id: str | None = None) -> list[dict]:
    """
    Returns freshness status for every active institution.
    """
    policy = _get_refresh_policy()
    
    # We want active institutions, so let's check accounts.
    from dal.owners import build_account_filter
    acct_filter, acct_params = build_account_filter(conn, owner_id, None, column="id")
    params = list(acct_params)
            
    rows = conn.execute(f"SELECT DISTINCT institution_id FROM accounts WHERE is_active = 1{acct_filter}", params).fetchall()
    active_institutions = {row["institution_id"] for row in rows}
    
    # Also include any tier 3 institutions that might not have accounts yet but we want to track
    for inst, tier in INSTITUTION_TIERS.items():
        if tier == 3:
            active_institutions.add(inst)
            
    # Include all from refresh_status
    try:
        status_rows = conn.execute("SELECT institution_id FROM institution_refresh_status").fetchall()
        for r in status_rows:
            active_institutions.add(r["institution_id"])
    except sqlite3.OperationalError:
        pass
        
    results = []
    now = datetime.now(timezone.utc)
    
    for inst in active_institutions:
        max_ts = None
        
        # 1. Check refresh_status
        try:
            row = conn.execute(
                "SELECT last_success FROM institution_refresh_status WHERE institution_id = ?",
                (inst,)
            ).fetchone()
            if row and row["last_success"]:
                max_ts = row["last_success"]
        except sqlite3.OperationalError:
            pass
            
        # 2. Check balance_snapshots
        row = conn.execute(f"""
            SELECT MAX(as_of) as latest FROM balance_snapshots 
            WHERE account_id IN (SELECT id FROM accounts WHERE institution_id = ?{acct_filter})
        """, [inst] + params).fetchone()
        if row and row["latest"]:
            if max_ts is None or row["latest"] > max_ts:
                max_ts = row["latest"]
                
        # 3. Check portfolio_snapshots
        row = conn.execute(f"""
            SELECT MAX(timestamp) as latest FROM portfolio_snapshots
            WHERE account_id IN (SELECT id FROM accounts WHERE institution_id = ?{acct_filter})
        """, [inst] + params).fetchone()
        if row and row["latest"]:
            if max_ts is None or row["latest"] > max_ts:
                max_ts = row["latest"]
                
        # Calculate staleness
        hours_since = None
        staleness = "no_data"
        expected = _get_expected_refresh_hours(inst, policy)
        
        if max_ts:
            try:
                # Bare-date strings (e.g. "2026-04-06") used to be parsed
                # as midnight UTC, which made "yesterday's data" look 24-48
                # hours stale and the dashboard pill render "Updated 2d ago".
                # Treat bare dates as end-of-day local so the user-perceived
                # age matches the calendar day difference.
                if "T" not in max_ts and " " not in max_ts:
                    # Bare date — anchor at end-of-day local
                    ts = datetime.fromisoformat(max_ts + "T23:59:59").astimezone(
                        timezone.utc
                    )
                else:
                    ts = datetime.fromisoformat(max_ts.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                diff = now - ts
                hours_since = diff.total_seconds() / 3600.0
                if hours_since < 0:
                    hours_since = 0.0
                
                # Check thresholds
                if hours_since <= expected:
                    staleness = "fresh"
                elif hours_since <= expected * 3:
                    staleness = "stale"
                else:
                    staleness = "critical"
            except ValueError:
                pass
                
        # Get account count for the institution
        acc = conn.execute(f"SELECT COUNT(*) as c FROM accounts WHERE institution_id = ?{acct_filter}", [inst] + params).fetchone()
        acc_count = acc["c"] if acc else 0
        
        display_name = inst.upper() if len(inst) <= 4 else inst.capitalize()
        
        results.append({
            "institution_id": inst,
            "display_name": display_name,
            "last_data_timestamp": max_ts,
            "hours_since_update": hours_since,
            "staleness": staleness,
            "expected_refresh_hours": expected,
            "account_count": acc_count,
        })
        
    return results

def get_net_worth_data_age(conn: sqlite3.Connection, owner_id: str | None = None) -> dict:
    """
    Returns the oldest data point contributing to the current net worth.
    This answers: "how old is the least-fresh piece of my net worth?"
    """
    freshness = get_institution_freshness(conn, owner_id=owner_id)
    if not freshness:
        return {
            "oldest_institution": None,
            "oldest_timestamp": None,
            "hours_since_oldest": None,
            "all_institutions_fresh": False,
        }
        
    # Filter out institutions with no_data
    with_data = [f for f in freshness if f["staleness"] != "no_data" and f["hours_since_update"] is not None]
    
    if not with_data:
        return {
            "oldest_institution": None,
            "oldest_timestamp": None,
            "hours_since_oldest": None,
            "all_institutions_fresh": False,
        }
        
    oldest = max(with_data, key=lambda f: f["hours_since_update"])
    all_fresh = all(f["staleness"] == "fresh" for f in with_data)
    
    return {
        "oldest_institution": oldest["institution_id"],
        "oldest_timestamp": oldest["last_data_timestamp"],
        "hours_since_oldest": oldest["hours_since_update"],
        "all_institutions_fresh": all_fresh,
    }

def get_document_drop_status(conn: sqlite3.Connection, owner_id: str | None = None) -> list[dict]:
    """
    Returns status for Tier 3 (document-drop) institutions.
    For each Tier 3 institution, check if a document has been
    ingested for the current month. Used by the nudge toast system.
    """
    results = []
    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")
    day_of_month = now.day
    
    freshness = get_institution_freshness(conn, owner_id=owner_id)
    freshness_map = {f["institution_id"]: f for f in freshness}
    
    for inst, tier in INSTITUTION_TIERS.items():
        if tier != 3:
            continue
            
        f = freshness_map.get(inst)
        last_date = f["last_data_timestamp"] if f else None
        
        current_month_updated = False
        if last_date and last_date.startswith(current_month):
            current_month_updated = True
            
        nudge_active = False
        if day_of_month > 5 and not current_month_updated:
            nudge_active = True
            
        display_name = inst.upper() if len(inst) <= 4 else inst.capitalize()
            
        results.append({
            "institution_id": inst,
            "display_name": display_name,
            "current_month_updated": current_month_updated,
            "last_document_date": last_date,
            "nudge_active": nudge_active,
        })
        
    return results
