"""
dal/budgets.py — Budget management and tracking.

Set monthly spending limits per category and track actuals against targets.
Supports ownership-aware budgets (mine/theirs/ours).

Budget lifecycle:
  1. Defaults come from config/budgets.yaml
  2. Users can override per-month via API
  3. Budget-vs-actual computed on the fly from transactions
"""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("sentry.dal.budgets")

# ── Config Loading ───────────────────────────────────────────────────────────

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "budgets.yaml"
_config_cache: dict | None = None


def _load_config() -> dict:
    """Load budget defaults from YAML config."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f) or {}
        log.debug("Budget config loaded: %d defaults", len(_config_cache.get("defaults", {})))
    except FileNotFoundError:
        log.warning("Budget config not found at %s, using empty defaults", _CONFIG_PATH)
        _config_cache = {"defaults": {}, "excluded_categories": []}
    return _config_cache


def reload_config() -> None:
    """Force reload of budget config (for testing)."""
    global _config_cache
    _config_cache = None
    _load_config()


def get_defaults() -> dict[str, float]:
    """Return default budget targets by category."""
    config = _load_config()
    return dict(config.get("defaults", {}))


def get_excluded_categories() -> list[str]:
    """Return list of categories excluded from budgeting."""
    config = _load_config()
    return list(config.get("excluded_categories", []))


# ── Budget CRUD ──────────────────────────────────────────────────────────────


def get_budget(
    conn: sqlite3.Connection,
    month: str,
    owner_id: Optional[str] = None,
) -> list[dict]:
    """Get all budget entries for a given month.

    If no entries exist for that month, returns the defaults
    from budgets.yaml (without persisting them).
    """
    clauses = ["month = ?"]
    params: list = [month]

    if owner_id:
        clauses.append("owner_id = ?")
        params.append(owner_id)
    else:
        clauses.append("owner_id IS NULL")

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT * FROM budgets WHERE {where} ORDER BY category",
        params,
    ).fetchall()

    if rows:
        return [dict(r) for r in rows]

    # No entries for this month — return defaults
    defaults = get_defaults()
    return [
        {
            "category": cat,
            "month": month,
            "target_amount": amt,
            "owner_id": owner_id,
            "is_default": True,
        }
        for cat, amt in sorted(defaults.items())
    ]


def set_budget_target(
    conn: sqlite3.Connection,
    category: str,
    month: str,
    target_amount: float,
    owner_id: Optional[str] = None,
) -> None:
    """Set or update a budget target for a specific category and month."""
    conn.execute(
        """
        INSERT INTO budgets (category, month, target_amount, owner_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(category, month, owner_id) DO UPDATE SET
            target_amount = excluded.target_amount,
            updated_at = datetime('now')
        """,
        (category, month, target_amount, owner_id),
    )


def initialize_month(
    conn: sqlite3.Connection,
    month: str,
    owner_id: Optional[str] = None,
) -> int:
    """Initialize budget entries for a month from defaults.

    Returns the number of entries created. Skips categories that
    already have a budget entry for this month.
    """
    defaults = get_defaults()
    created = 0
    for category, target in defaults.items():
        existing = conn.execute(
            "SELECT id FROM budgets WHERE category = ? AND month = ? "
            "AND owner_id IS ?",
            (category, month, owner_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO budgets (category, month, target_amount, owner_id) "
                "VALUES (?, ?, ?, ?)",
                (category, month, target, owner_id),
            )
            created += 1
    return created


def delete_budget(
    conn: sqlite3.Connection,
    category: str,
    month: str,
    owner_id: Optional[str] = None,
) -> None:
    """Delete a budget entry."""
    conn.execute(
        "DELETE FROM budgets WHERE category = ? AND month = ? "
        "AND owner_id IS ?",
        (category, month, owner_id),
    )


# ── Budget vs. Actual ────────────────────────────────────────────────────────


def get_budget_vs_actual(
    conn: sqlite3.Connection,
    month: str,
    owner_id: Optional[str] = None,
    account_ids: Optional[list[str]] = None,
) -> list[dict]:
    """Compare budgeted amounts vs. actual spending for a month.

    Returns a list of dicts, each with:
      category, target, actual, remaining, pct_used, status
    """
    # Get budget targets (from DB or defaults)
    targets_list = get_budget(conn, month, owner_id=owner_id)
    targets = {t["category"]: t["target_amount"] for t in targets_list}

    # Get actual spending for the month
    excluded = get_excluded_categories()
    excluded_placeholders = ", ".join("?" for _ in excluded)

    query = f"""
        SELECT COALESCE(category, 'Uncategorized') as cat,
               SUM(CASE WHEN signed_amount < 0 THEN -signed_amount ELSE 0 END) as spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND strftime('%Y-%m', posting_date) = ?
          AND COALESCE(category, 'Uncategorized') NOT IN ({excluded_placeholders})
    """
    params: list = [month] + excluded

    if account_ids:
        acct_placeholders = ", ".join("?" for _ in account_ids)
        query += f" AND account_id IN ({acct_placeholders})"
        params.extend(account_ids)

    query += " GROUP BY cat"
    actuals_rows = conn.execute(query, params).fetchall()
    actuals = {r["cat"]: r["spending"] or 0 for r in actuals_rows}

    # Merge: include every category that has either a target or actual
    all_cats = set(targets.keys()) | set(actuals.keys())
    results = []

    for cat in sorted(all_cats):
        target = targets.get(cat, 0)
        actual = actuals.get(cat, 0)
        remaining = target - actual
        pct_used = (actual / target * 100) if target > 0 else (100 if actual > 0 else 0)

        if pct_used >= 100:
            status = "over"
        elif pct_used >= 80:
            status = "warning"
        elif pct_used >= 50:
            status = "on_track"
        else:
            status = "under"

        results.append({
            "category": cat,
            "target": round(target, 2),
            "actual": round(actual, 2),
            "remaining": round(remaining, 2),
            "pct_used": round(pct_used, 1),
            "status": status,
        })

    # Sort by pct_used descending (most overbudget first)
    results.sort(key=lambda x: -x["pct_used"])
    return results


def get_budget_summary(
    conn: sqlite3.Connection,
    month: str,
    owner_id: Optional[str] = None,
    account_ids: Optional[list[str]] = None,
) -> dict:
    """High-level budget summary for a month.

    Returns:
      {month, total_budget, total_spent, total_remaining,
       pct_used, over_budget_count, categories_tracked}
    """
    details = get_budget_vs_actual(conn, month, owner_id, account_ids)

    total_budget = sum(d["target"] for d in details)
    total_spent = sum(d["actual"] for d in details)
    total_remaining = total_budget - total_spent
    pct_used = (total_spent / total_budget * 100) if total_budget > 0 else 0
    over_count = sum(1 for d in details if d["status"] == "over")

    return {
        "month": month,
        "total_budget": round(total_budget, 2),
        "total_spent": round(total_spent, 2),
        "total_remaining": round(total_remaining, 2),
        "pct_used": round(pct_used, 1),
        "over_budget_count": over_count,
        "categories_tracked": len(details),
    }


# ── Budget Suggestions ───────────────────────────────────────────────────────


def suggest_budget_targets(
    conn: sqlite3.Connection,
    months_back: int = 3,
    account_ids: Optional[list[str]] = None,
) -> list[dict]:
    """Compute suggested budget targets from historical spending.

    Algorithm:
      1. Average monthly spending per category over the last N months
      2. Add 10% buffer
      3. Round up to nearest $25
      4. Flag categories with recurring baseline

    Returns a list of dicts:
      {category, avg_monthly, suggested_target, recurring_baseline,
       has_recurring, months_with_data}

    This powers the guided budget setup flow in the UI.
    """
    import math
    from collections import defaultdict

    excluded = get_excluded_categories()
    excluded_placeholders = ", ".join("?" for _ in excluded)

    query = f"""
        SELECT COALESCE(category, 'Uncategorized') as cat,
               strftime('%Y-%m', posting_date) as month,
               SUM(CASE WHEN direction = 'Debit' THEN amount ELSE 0 END) as spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND posting_date >= date('now', '-{months_back} months')
          AND COALESCE(category, 'Uncategorized') NOT IN ({excluded_placeholders})
        GROUP BY cat, month ORDER BY cat
    """
    rows = conn.execute(query, excluded).fetchall()

    # Aggregate by category
    cat_data: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["month"] is not None:
            cat_data[r["cat"]].append(r["spending"] or 0)

    # Get recurring baselines
    MONTHLY_FACTORS = {
        "weekly": 4.33, "biweekly": 2.17, "monthly": 1.0,
        "bimonthly": 0.5, "quarterly": 0.333, "semiannual": 0.167, "annual": 0.083,
    }
    rec_rows = conn.execute(
        "SELECT category, frequency, expected_amount FROM recurring_transactions "
        "WHERE status = 'active' AND amount_stable = 1 AND expected_amount IS NOT NULL"
    ).fetchall()

    rec_baseline: dict[str, float] = defaultdict(float)
    for r in rec_rows:
        cat = r["category"] or "Uncategorized"
        factor = MONTHLY_FACTORS.get(r["frequency"], 1.0)
        rec_baseline[cat] += (r["expected_amount"] or 0) * factor

    # Build suggestions
    results = []
    all_cats = set(cat_data.keys()) | set(rec_baseline.keys())

    for cat in sorted(all_cats):
        monthly_vals = cat_data.get(cat, [])
        nonzero = [v for v in monthly_vals if v > 0]
        avg = sum(nonzero) / len(nonzero) if nonzero else 0

        # Add 10% buffer, round up to nearest $25
        buffered = avg * 1.10
        suggested = math.ceil(buffered / 25) * 25 if buffered > 0 else 0

        # Ensure suggested >= recurring baseline
        rec = round(rec_baseline.get(cat, 0), 2)
        if rec > suggested:
            suggested = math.ceil(rec / 25) * 25

        if suggested == 0 and rec == 0:
            continue  # Skip categories with zero history

        results.append({
            "category": cat,
            "avg_monthly": round(avg, 2),
            "suggested_target": suggested,
            "recurring_baseline": rec,
            "has_recurring": rec > 0,
            "months_with_data": len(nonzero),
        })

    results.sort(key=lambda x: -x["suggested_target"])
    return results
