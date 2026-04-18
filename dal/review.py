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
    from dal.category_classifications import INCOME_CATEGORIES, get_spend_exclusion_clause

    excl_ph, excl_cats = get_spend_exclusion_clause()
    inc_cats = list(INCOME_CATEGORIES)
    inc_ph = ", ".join("?" for _ in inc_cats)

    # Honor None vs [] — when Amy owns zero accounts the helper returns
    # " AND 1=0" so the income/spending queries below return zeros instead
    # of leaking the primary owner's data. See dal/owners.build_account_filter.
    from dal.owners import build_account_filter
    acct_filter_spending, acct_params_spending = build_account_filter(
        conn, owner_id, None
    )

    def _month_income_spending(m_start: str, m_end: str) -> tuple[float, float]:
        """Compute income and spending for a date range using correct exclusions."""
        base_params = [m_start, m_end]
        # Income
        inc_row = conn.execute(
            f"""
            SELECT COALESCE(SUM(signed_amount), 0) as total
            FROM transactions
            WHERE status = 'posted' AND transfer_tag IS NULL
              AND signed_amount > 0
              AND category IN ({inc_ph})
              AND posting_date >= ? AND posting_date <= ?
              {acct_filter_spending}
            """,
            inc_cats + base_params + acct_params_spending,
        ).fetchone()
        income = round(inc_row["total"] or 0, 2)
        # Spending: exclude income cats, transfer cats, debt service, transfer-tagged
        sp_row = conn.execute(
            f"""
            SELECT COALESCE(SUM(-signed_amount), 0) as total
            FROM transactions
            WHERE status = 'posted' AND transfer_tag IS NULL
              AND signed_amount < 0
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
              AND posting_date >= ? AND posting_date <= ?
              {acct_filter_spending}
            """,
            excl_cats + base_params + acct_params_spending,
        ).fetchone()
        spending = round(sp_row["total"] or 0, 2)
        return income, spending

    income_total, spending_total = _month_income_spending(month_start, month_end)
    sr = round(((income_total - spending_total) / income_total) * 100, 1) if income_total > 0 else 0

    # Prior month
    prior_last_day_val = calendar.monthrange(prior_year, prior_mo)[1]
    prior_start_str = f"{prior_year}-{prior_mo:02d}-01"
    prior_end_str = f"{prior_year}-{prior_mo:02d}-{prior_last_day_val:02d}"
    prior_income, prior_spending = _month_income_spending(prior_start_str, prior_end_str)

    # Trailing 12-month averages
    trailing_incomes = []
    trailing_spendings = []
    ty, tm = year, mo
    for _ in range(12):
        tl = calendar.monthrange(ty, tm)[1]
        ts = f"{ty}-{tm:02d}-01"
        te = f"{ty}-{tm:02d}-{tl:02d}"
        ti, tsp = _month_income_spending(ts, te)
        if ti > 0:
            trailing_incomes.append(ti)
        if tsp > 0:
            trailing_spendings.append(tsp)
        tm -= 1
        if tm == 0:
            tm = 12
            ty -= 1

    avg_income_12 = round(sum(trailing_incomes) / len(trailing_incomes), 2) if trailing_incomes else 0
    avg_spending_12 = round(sum(trailing_spendings) / len(trailing_spendings), 2) if trailing_spendings else 0

    income_mom_pct = round(((income_total / prior_income) - 1) * 100, 1) if prior_income > 0 else 0
    spending_mom_pct = round(((spending_total / prior_spending) - 1) * 100, 1) if prior_spending > 0 else 0

    # ── 2. Net Worth Delta ───────────────────────────────────────────
    nw_delta = {"amount": 0, "pct": 0, "direction": "flat"}
    try:
        from dal.reports import get_net_worth_history
        # Request enough months to cover both target and prior month
        today = date.today()
        months_back = (today.year - prior_year) * 12 + (today.month - prior_mo) + 1
        nw_hist = get_net_worth_history(conn, months=max(months_back, 3), owner_id=owner_id)
        nw_map = {h["month"]: h.get("net_worth", h.get("net", 0)) for h in nw_hist}
        nw_current = nw_map.get(month)
        nw_prior = nw_map.get(prior_month)
        if nw_current is not None and nw_prior is not None and nw_prior != 0:
            nw_change = nw_current - nw_prior
            nw_pct = round((nw_change / abs(nw_prior)) * 100, 1)
            direction = "up" if nw_change > 0 else ("down" if nw_change < 0 else "flat")
            nw_delta = {"amount": round(nw_change, 2), "pct": nw_pct, "direction": direction}
    except Exception as e:
        log.warning("Net worth delta failed: %s", e)

    # ── 3. Budget Highlights ─────────────────────────────────────────
    budget_highlights = []
    try:
        from dal.budgets import get_budget_vs_actual
        # Budgets are household-only (V23) — actuals always reflect
        # the entire household, regardless of which owner view the
        # caller is rendering.
        bva = get_budget_vs_actual(conn, month)
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
        acct_filter, acct_params = build_account_filter(
            conn, owner_id, None, column="rt.account_id"
        )
        params = [month_start, month_end] + list(acct_params)

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
        removed_params = [prior_start, prior_end, month_start] + list(acct_params)
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
    large_transfers = []
    NOTABLE_THRESHOLD = 1000  # $1,000 minimum to be flagged
    try:
        acct_filter, notable_acct_params = build_account_filter(conn, owner_id, None)
        params = [month_start, month_end] + list(notable_acct_params)

        from dal.category_classifications import INCOME_CATEGORIES
        inc_cats = list(INCOME_CATEGORIES)
        ph = ", ".join("?" for _ in inc_cats)

        # Notable spending: non-transfer, non-income, large outflows
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
              AND ABS(signed_amount) >= {NOTABLE_THRESHOLD}
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

        # Large transfers: inter-account movements ≥ threshold
        transfer_params = [month_start, month_end, NOTABLE_THRESHOLD] + list(notable_acct_params)
        transfer_acct_filter = acct_filter
        xfer_rows = conn.execute(
            f"""
            SELECT id, posting_date, description,
                   COALESCE(canonical_merchant, '') as merchant,
                   COALESCE(category, 'Uncategorized') as category,
                   ABS(signed_amount) as amount,
                   transfer_tag
            FROM transactions
            WHERE status = 'posted'
              AND posting_date >= ? AND posting_date <= ?
              AND transfer_tag IS NOT NULL
              AND ABS(signed_amount) >= ?
              {transfer_acct_filter}
            ORDER BY ABS(signed_amount) DESC
            LIMIT 5
            """,
            transfer_params,
        ).fetchall()

        seen_tags: set = set()
        for r in xfer_rows:
            tag = r["transfer_tag"]
            if tag in seen_tags:
                continue
            seen_tags.add(tag)
            large_transfers.append({
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
        acct_filter, uncat_acct_params = build_account_filter(conn, owner_id, None)
        params = [month_start, month_end] + list(uncat_acct_params)
                
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

    # ── 9. Pre-Tax (Gross) Snapshot ──────────────────────────────────
    # Reads dal.payroll which sources from payroll_snapshots (myPay RAS).
    # If no snapshot for this month, pre_tax = None and the UI hides
    # the card.  As of v22, payroll snapshots are owner-scoped.
    pre_tax: dict | None = None
    try:
        from dal.payroll import get_gross_income_for_month
        from dal.category_classifications import pre_tax_savings_rate
        snap = get_gross_income_for_month(conn, year, mo, owner_id=owner_id)
        if snap is not None and snap["gross_pay"] > 0:
            tax_withheld = snap["federal_tax"] + snap["state_tax"]
            pre_tax = {
                "gross_income": snap["gross_pay"],
                "federal_tax": snap["federal_tax"],
                "state_tax": snap["state_tax"],
                "deductions": snap["deductions_total"],
                "net_pay": snap["net_pay"],
                "savings_rate_pct": pre_tax_savings_rate(
                    snap["gross_pay"], tax_withheld, spending_total
                ),
                "data_quality": "complete",
            }
    except Exception as e:
        log.warning("Pre-tax snapshot failed: %s", e)

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
        "large_transfers": large_transfers,
        "uncategorized_count": uncategorized_count,
        "lifestyle_flags": lifestyle_flags,
        "freshness": freshness,
        "pre_tax": pre_tax,
    }
