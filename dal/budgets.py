"""
dal/budgets.py — Household-level budget management and tracking.

Set monthly spending limits per category and track actuals against
targets. Budgets are a household concept — there is exactly one row
per (category, month) and edits from any view affect the same row.
Per-owner attribution was an architectural mistake from early planning
(see V23 migration).

Budget lifecycle:
  1. Defaults come from config/budgets.yaml (used as a fallback for
     months that have no rows yet — first-run convenience).
  2. Users can override per-month via API.
  3. Budget-vs-actual is computed on the fly from transactions.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("sentry.dal.budgets")

# Attribution-aware month expression (mirrors dal/cash_flow.py)
_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"

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
) -> list[dict]:
    """Get all household budget entries for a given month.

    If no entries exist for that month, returns the defaults from
    budgets.yaml (without persisting them) so first-run installs see
    sensible placeholders.
    """
    rows = conn.execute(
        "SELECT * FROM budgets WHERE month = ? ORDER BY category",
        (month,),
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
            "owner_id": None,
            "is_default": True,
        }
        for cat, amt in sorted(defaults.items())
    ]


def set_budget_target(
    conn: sqlite3.Connection,
    category: str,
    month: str,
    target_amount: float,
) -> None:
    """Set or update a household budget target for a category/month.

    Uses an UPDATE-then-INSERT pattern instead of ``ON CONFLICT`` because
    SQLite treats multiple NULLs in a UNIQUE constraint as distinct, so
    the original ``UNIQUE(category, month, owner_id)`` constraint can't
    catch duplicates when ``owner_id`` is always NULL. The V23 partial
    unique index enforces single-row-per-month as defense-in-depth.
    """
    cursor = conn.execute(
        """
        UPDATE budgets
        SET target_amount = ?, updated_at = datetime('now')
        WHERE category = ? AND month = ? AND owner_id IS NULL
        """,
        (target_amount, category, month),
    )
    if cursor.rowcount == 0:
        conn.execute(
            """
            INSERT INTO budgets (category, month, target_amount, owner_id)
            VALUES (?, ?, ?, NULL)
            """,
            (category, month, target_amount),
        )


def initialize_month(
    conn: sqlite3.Connection,
    month: str,
) -> int:
    """Initialize household budget entries for a month from defaults.

    Returns the number of entries created. Skips categories that
    already have a budget entry for this month.
    """
    defaults = get_defaults()
    created = 0
    for category, target in defaults.items():
        existing = conn.execute(
            "SELECT id FROM budgets WHERE category = ? AND month = ? "
            "AND owner_id IS NULL",
            (category, month),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO budgets (category, month, target_amount, owner_id) "
                "VALUES (?, ?, ?, NULL)",
                (category, month, target),
            )
            created += 1
    return created


def delete_budget(
    conn: sqlite3.Connection,
    category: str,
    month: str,
) -> None:
    """Delete a household budget entry."""
    conn.execute(
        "DELETE FROM budgets WHERE category = ? AND month = ? "
        "AND owner_id IS NULL",
        (category, month),
    )


# ── Budget vs. Actual ────────────────────────────────────────────────────────


def get_budget_vs_actual(
    conn: sqlite3.Connection,
    month: str,
    account_ids: Optional[list[str]] = None,
) -> list[dict]:
    """Compare household budgeted amounts vs. actual spending for a month.

    Returns a list of dicts, each with:
      category, target, actual, remaining, pct_used, status

    Uses the canonical sign + transfer + blacklist pattern (see
    docs/ARCHITECTURE.md §4.6) so refunds reduce actuals correctly,
    transfers are excluded, and the categories the user sees are
    consistent with the Cash Flow page.

    Actuals are household-wide (sum across every owner's accounts).
    The optional ``account_ids`` parameter is preserved for callers
    that want to scope to a specific set of accounts; passing an
    empty list yields zero actuals.
    """
    from dal.category_classifications import get_spend_exclusion_clause

    # Get budget targets (from DB or defaults)
    targets_list = get_budget(conn, month)
    targets = {t["category"]: t["target_amount"] for t in targets_list}

    # Canonical exclusion: spend blacklist | income whitelist.  This
    # mirrors dal/cash_flow.py and dal/reports.py — Budgets must NOT
    # define its own blacklist, otherwise the totals drift from Cash
    # Flow and a refund leaks into the actuals.
    excluded_placeholders, excluded = get_spend_exclusion_clause()

    query = f"""
        SELECT COALESCE(category, 'Uncategorized') as cat,
               SUM(-signed_amount) as spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND signed_amount < 0
          AND transfer_tag IS NULL
          AND {_EM} = ?
          AND COALESCE(category, 'Uncategorized') NOT IN ({excluded_placeholders})
    """
    params: list = [month] + excluded

    # Optional account-scoped actuals (for callers that want to filter
    # to a specific set of accounts). An empty list returns zero
    # actuals; ``None`` returns household totals.
    if account_ids is not None:
        if not account_ids:
            query += " AND 1=0"
        else:
            placeholders = ", ".join("?" for _ in account_ids)
            query += f" AND account_id IN ({placeholders})"
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

        # ``target_amount`` / ``spent`` are aliases of ``target`` / ``actual``
        # so the frontend stops having to normalize the response shape
        # (previously: ``b.target || b.target_amount`` everywhere). The
        # original names are preserved for backward-compat with existing
        # backend tests and DAL callers.
        results.append({
            "category": cat,
            "target": round(target, 2),
            "target_amount": round(target, 2),
            "actual": round(actual, 2),
            "spent": round(actual, 2),
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
    account_ids: Optional[list[str]] = None,
) -> dict:
    """High-level household budget summary for a month.

    Returns:
      {month, total_budget, total_spent, total_remaining,
       pct_used, over_budget_count, categories_tracked}
    """
    details = get_budget_vs_actual(conn, month, account_ids)

    total_budget = sum(d["target"] for d in details)
    total_spent = sum(d["actual"] for d in details)
    total_remaining = total_budget - total_spent
    pct_used = (total_spent / total_budget * 100) if total_budget > 0 else 0
    over_count = sum(1 for d in details if d["status"] == "over")

    return {
        "month": month,
        # ``total_budgeted`` alias for ``total_budget`` so the frontend's
        # normalization shim in DashboardPage.tsx is no longer load-bearing.
        "total_budget": round(total_budget, 2),
        "total_budgeted": round(total_budget, 2),
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

    # Canonical sign convention: signed_amount < 0 is spending.
    # Explicit transfer_tag filter catches reconciled transfers that keep
    # their original category (reconciliation tags but doesn't recategorize).
    query = f"""
        SELECT COALESCE(category, 'Uncategorized') as cat,
               {_EM} as month,
               SUM(CASE WHEN signed_amount < 0
                             AND transfer_tag IS NULL
                        THEN -signed_amount ELSE 0 END) as spending
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
