"""
dal/review.py — Monthly review assembler.

Calls existing DAL functions and stitches results into a single
structured summary for the monthly review page.
"""

import sqlite3
from datetime import date
import logging
import calendar

log = logging.getLogger("sentry.dal.review")


def get_monthly_review(conn: sqlite3.Connection, month: str, owner_id: str | None = None) -> dict:
    """
    Assemble the monthly review for a given YYYY-MM month string.

    Pulls from: cash_flow, reports, budgets, recurring, transactions,
    derived metrics, freshness. Does NOT recompute anything — reads
    from derived_summaries or calls existing DAL functions directly.
    """
    year = int(month[:4])
    mo = int(month[5:7])

    # Prior month
    if mo == 1:
        prior_year, prior_mo = year - 1, 12
    else:
        prior_year, prior_mo = year, mo - 1
    prior_month = f"{prior_year}-{prior_mo:02d}"

    # Date range for the target month
    last_day = calendar.monthrange(year, mo)[1]
    month_start = f"{year}-{mo:02d}-01"
    month_end = f"{year}-{mo:02d}-{last_day:02d}"

    # ── 1. Income / Spending / Savings Rate ──────────────────────────
    from dal.cash_flow import get_monthly_rolling_cash_flow

    rolling = get_monthly_rolling_cash_flow(conn, months=18, owner_id=owner_id)
    # Find target month and prior month
    target_data = None
    prior_data = None
    trailing_incomes = []
    trailing_spendings = []

    for row in rolling:
        row_month = f"{row['year']}-{row['month']:02d}"
        if row_month == month:
            target_data = row
        if row_month == prior_month:
            prior_data = row
        # Collect trailing 12 months ending at target month
        # We'll filter after finding the target

    # Build trailing 12m average
    target_idx = None
    for i, row in enumerate(rolling):
        row_month = f"{row['year']}-{row['month']:02d}"
        if row_month == month:
            target_idx = i
            break

    if target_idx is not None:
        start_idx = max(0, target_idx - 11)
        trailing_rows = rolling[start_idx:target_idx + 1]
        trailing_incomes = [r["income"] for r in trailing_rows if r["income"] > 0]
        trailing_spendings = [r["spending"] for r in trailing_rows if r["spending"] > 0]

    income_total = target_data["income"] if target_data else 0
    spending_total = target_data["spending"] if target_data else 0
    sr = target_data["savings_rate"] if target_data else 0
    prior_income = prior_data["income"] if prior_data else 0
    prior_spending = prior_data["spending"] if prior_data else 0

    avg_income_12 = round(sum(trailing_incomes) / len(trailing_incomes), 2) if trailing_incomes else 0
    avg_spending_12 = round(sum(trailing_spendings) / len(trailing_spendings), 2) if trailing_spendings else 0

    income_mom_pct = round(((income_total / prior_income) - 1) * 100, 1) if prior_income > 0 else 0
    spending_mom_pct = round(((spending_total / prior_spending) - 1) * 100, 1) if prior_spending > 0 else 0

    # ── 2. Net Worth Delta ───────────────────────────────────────────
    nw_delta = {"amount": 0, "pct": 0, "direction": "flat"}
    try:
        from dal.reports import get_net_worth_history
        nw_hist = get_net_worth_history(conn, months=3, owner_id=owner_id)
        nw_map = {h["month"]: h.get("net_worth", h.get("net", 0)) for h in nw_hist}
        nw_current = nw_map.get(month, 0)
        nw_prior = nw_map.get(prior_month, 0)
        if nw_prior:
            nw_change = nw_current - nw_prior
            nw_pct = round((nw_change / abs(nw_prior)) * 100, 1) if nw_prior != 0 else 0
            direction = "up" if nw_change > 0 else ("down" if nw_change < 0 else "flat")
            nw_delta = {"amount": round(nw_change, 2), "pct": nw_pct, "direction": direction}
    except Exception as e:
        log.warning("Net worth delta failed: %s", e)

    # ── 3. Budget Highlights ─────────────────────────────────────────
    budget_highlights = []
    try:
        from dal.budgets import get_budget_vs_actual
        bva = get_budget_vs_actual(conn, month, owner_id=owner_id)
        over_budget = [
            {
                "category": b["category"],
                "budgeted": b["target"],
                "actual": b["actual"],
                "variance": round(b["actual"] - b["target"], 2),
                "pct_used": b["pct_used"],
            }
            for b in bva if b["actual"] > b["target"] and b["target"] > 0
        ]
        over_budget.sort(key=lambda x: x["variance"], reverse=True)

        improved = [
            {
                "category": b["category"],
                "budgeted": b["target"],
                "actual": b["actual"],
                "variance": round(b["actual"] - b["target"], 2),
                "pct_used": b["pct_used"],
            }
            for b in bva if b["actual"] <= b["target"] and b["target"] > 0
        ]
        improved.sort(key=lambda x: x["variance"])

        budget_highlights = over_budget[:5] + improved[:3]
    except Exception as e:
        log.warning("Budget highlights failed: %s", e)

    # ── 4. Subscription Changes ──────────────────────────────────────
    subscription_changes = []
    try:
        acct_filter = ""
        params = [month_start, month_end]
        if owner_id:
            from dal.owners import resolve_owner_account_ids
            o_acct_ids = resolve_owner_account_ids(conn, owner_id)
            if o_acct_ids:
                ph = ", ".join("?" for _ in o_acct_ids)
                acct_filter = f" AND rt.account_id IN ({ph})"
                params.extend(o_acct_ids)

        # Price changes (recurring_mutations)
        mutations = conn.execute(
            f"""
            SELECT rt.merchant, rm.old_amount, rm.new_amount,
                   (rm.new_amount - rm.old_amount) as delta
            FROM recurring_mutations rm
            JOIN recurring_transactions rt ON rt.id = rm.recurring_id
            WHERE rm.detected_at >= ? AND rm.detected_at <= ?
            {acct_filter}
            """,
            params,
        ).fetchall()
        for m in mutations:
            subscription_changes.append({
                "merchant": m["merchant"],
                "change_type": "price_change",
                "old_amount": round(m["old_amount"] or 0, 2),
                "new_amount": round(m["new_amount"] or 0, 2),
                "delta": round(m["delta"] or 0, 2),
            })

        # New subscriptions
        new_subs = conn.execute(
            f"""
            SELECT merchant, expected_amount
            FROM recurring_transactions
            WHERE first_seen >= ? AND first_seen <= ?
              AND status = 'active'
              {acct_filter.replace("rt.account_id", "account_id")}
            """,
            params,
        ).fetchall()
        for ns in new_subs:
            subscription_changes.append({
                "merchant": ns["merchant"],
                "change_type": "new",
                "old_amount": None,
                "new_amount": round(ns["expected_amount"] or 0, 2),
                "delta": None,
            })

        # Removed subscriptions (last_seen in prior month, no activity this month)
        prior_last_day = calendar.monthrange(prior_year, prior_mo)[1]
        prior_start = f"{prior_year}-{prior_mo:02d}-01"
        prior_end = f"{prior_year}-{prior_mo:02d}-{prior_last_day:02d}"
        removed_params = [prior_start, prior_end, month_start]
        if owner_id:
            from dal.owners import resolve_owner_account_ids
            o_acct_ids = resolve_owner_account_ids(conn, owner_id)
            if o_acct_ids:
                removed_params.extend(o_acct_ids)
        removed = conn.execute(
            f"""
            SELECT merchant, expected_amount
            FROM recurring_transactions
            WHERE last_seen >= ? AND last_seen <= ?
              AND last_seen < ?
              AND status = 'inactive'
              {acct_filter.replace("rt.account_id", "account_id")}
            """,
            removed_params,
        ).fetchall()
        for rm in removed:
            subscription_changes.append({
                "merchant": rm["merchant"],
                "change_type": "removed",
                "old_amount": round(rm["expected_amount"] or 0, 2),
                "new_amount": None,
                "delta": None,
            })
    except Exception as e:
        log.warning("Subscription changes failed: %s", e)

    # ── 5. Notable Transactions ──────────────────────────────────────
    notable_transactions = []
    try:
        acct_filter = ""
        params = [month_start, month_end]
        if owner_id:
            from dal.owners import resolve_owner_account_ids
            o_acct_ids = resolve_owner_account_ids(conn, owner_id)
            if o_acct_ids:
                ph = ", ".join("?" for _ in o_acct_ids)
                acct_filter = f" AND account_id IN ({ph})"
                params.extend(o_acct_ids)
                
        from dal.cash_flow import _INCOME_CATEGORIES
        inc_cats = list(_INCOME_CATEGORIES)
        ph = ", ".join("?" for _ in inc_cats)
        rows = conn.execute(
            f"""
            SELECT id, posting_date, description,
                   COALESCE(canonical_merchant, '') as merchant,
                   COALESCE(category, 'Uncategorized') as category,
                   -signed_amount as amount
            FROM transactions
            WHERE status = 'posted'
              AND posting_date >= ? AND posting_date <= ?
              AND transfer_tag IS NULL
              AND signed_amount < 0
              {acct_filter}
              AND COALESCE(category, 'Uncategorized') NOT IN ({ph})
            ORDER BY ABS(signed_amount) DESC
            LIMIT 5
            """,
            params + inc_cats,
        ).fetchall()
        for r in rows:
            notable_transactions.append({
                "id": r["id"],
                "date": r["posting_date"],
                "description": r["description"],
                "merchant": r["merchant"] or None,
                "category": r["category"],
                "amount": round(r["amount"] or 0, 2),
            })
    except Exception as e:
        log.warning("Notable transactions failed: %s", e)

    # ── 6. Uncategorized Count ───────────────────────────────────────
    uncategorized_count = 0
    try:
        acct_filter = ""
        params = [month_start, month_end]
        if owner_id:
            from dal.owners import resolve_owner_account_ids
            o_acct_ids = resolve_owner_account_ids(conn, owner_id)
            if o_acct_ids:
                ph = ", ".join("?" for _ in o_acct_ids)
                acct_filter = f" AND account_id IN ({ph})"
                params.extend(o_acct_ids)
                
        uc = conn.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM transactions
            WHERE status = 'posted'
              AND posting_date >= ? AND posting_date <= ?
              AND COALESCE(category, 'Uncategorized') = 'Uncategorized'
              AND transfer_tag IS NULL
              {acct_filter}
            """,
            params,
        ).fetchone()
        uncategorized_count = uc["cnt"] if uc else 0
    except Exception as e:
        log.warning("Uncategorized count failed: %s", e)

    # ── 7. Lifestyle Flags ───────────────────────────────────────────
    lifestyle_flags = []
    try:
        from dal.lifestyle import get_lifestyle_creep
        creep = get_lifestyle_creep(conn, owner_id=owner_id)
        if not creep.get("insufficient_data"):
            for c in creep.get("categories", []):
                if c.get("flagged"):
                    lifestyle_flags.append({
                        "category": c["category"],
                        "category_growth_pct": c["annualized_growth_pct"],
                        "income_growth_pct": c["income_growth_pct"],
                        "excess_pct": c["excess_pct"],
                    })
    except (ImportError, AttributeError) as e:
        log.warning("Lifestyle module not available: %s", e)
    except Exception as e:
        log.warning("Lifestyle creep analysis failed: %s", e)

    # ── 8. Data Freshness ────────────────────────────────────────────
    freshness = []
    try:
        from dal.freshness import get_institution_freshness
        raw_freshness = get_institution_freshness(conn, owner_id=owner_id)
        for f in raw_freshness:
            freshness.append({
                "institution": f.get("display_name", f.get("institution_id", "")),
                "status": f.get("staleness", "no_data"),
                "hours_since_update": round(f["hours_since_update"], 1) if f.get("hours_since_update") else None,
            })
    except Exception as e:
        log.warning("Freshness check failed: %s", e)

    return {
        "month": month,
        "income": {
            "total": income_total,
            "prior_month": prior_income,
            "trailing_12m_avg": avg_income_12,
            "mom_change_pct": income_mom_pct,
        },
        "spending": {
            "total": spending_total,
            "prior_month": prior_spending,
            "trailing_12m_avg": avg_spending_12,
            "mom_change_pct": spending_mom_pct,
        },
        "savings_rate": sr,
        "net_worth_delta": nw_delta,
        "budget_highlights": budget_highlights,
        "subscription_changes": subscription_changes,
        "notable_transactions": notable_transactions,
        "uncategorized_count": uncategorized_count,
        "lifestyle_flags": lifestyle_flags,
        "freshness": freshness,
    }
