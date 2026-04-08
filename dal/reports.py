"""
dal/reports.py — Parameterized report queries for the Sentry Finance dashboard.

Provides structured data for:
  - Spending by category (period, account, owner)
  - Cash flow (income vs. expense by month)
  - Net worth history (monthly snapshots)
  - CSV transaction export

All queries are read-only and ownership-aware.
"""

import csv
import io
import logging
import sqlite3
from typing import Optional

log = logging.getLogger("sentry.dal.reports")

# Attribution-aware month expression (mirrors dal/cash_flow.py)
_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"

# ── Category sets — imported from canonical single source of truth ────────────
from dal.category_classifications import (
    INCOME_CATEGORIES as _INCOME_CATEGORIES,
    EXCLUDED_FROM_SPEND as _EXCLUDED_FROM_SPEND,
    INCOME_EXCL_FROM_INC as _INCOME_EXCL_FROM_INC,
)


# ── Spending by Category ──────────────────────────────────────────────────────


def get_spending_by_category(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    account_ids: Optional[list[str]] = None,
    exclude_transfers: bool = True,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Spending breakdown by category for a date range.

    Returns a list sorted by total_spent descending:
      {category, total_spent, transaction_count, avg_transaction, pct_of_total}
    """
    excl = list(_EXCLUDED_FROM_SPEND | _INCOME_CATEGORIES) if exclude_transfers else list(_INCOME_CATEGORIES)
    excl_placeholders = ", ".join("?" for _ in excl)

    params: list = [start_date, end_date] + excl

    acct_filter = ""
    if not account_ids and owner_id:
        from dal.owners import resolve_account_ids_for_view
        resolved = resolve_account_ids_for_view(conn, owner_id)
        if resolved is not None:
            account_ids = list(resolved)
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        acct_filter = f" AND account_id IN ({placeholders})"
        params.extend(account_ids)

    excl_clause = f"AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})" if excl else ""

    rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Uncategorized') as category,
               SUM(-signed_amount) as total_spent,
               COUNT(*) as transaction_count,
               AVG(-signed_amount) as avg_transaction
        FROM transactions
        WHERE status = 'posted'
          AND transfer_tag IS NULL
          AND posting_date >= ?
          AND posting_date <= ?
          {excl_clause}
          {acct_filter}
        GROUP BY category
        ORDER BY total_spent DESC
        """,
        params,
    ).fetchall()

    total = sum(r["total_spent"] or 0 for r in rows)
    result = []
    for r in rows:
        spent = round(r["total_spent"] or 0, 2)
        result.append({
            "category": r["category"],
            "total_spent": spent,
            "transaction_count": r["transaction_count"],
            "avg_transaction": round(r["avg_transaction"] or 0, 2),
            "pct_of_total": round(spent / total * 100, 1) if total > 0 else 0,
        })

    return result


# ── Monthly Cash Flow ──────────────────────────────────────────────────────────


def get_cash_flow_report(
    conn: sqlite3.Connection,
    months: int = 12,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """
    Monthly cash flow: income vs. spending vs. net for a date window.

    Two ways to specify the window:
      1. Explicit ``start_date`` / ``end_date`` (YYYY-MM-DD).  Preferred.
         Anchored in local time on the frontend, no UTC drift.
      2. Legacy ``months`` int — UTC-anchored ``date('now', '-N months')``.
         Kept for backwards compat.  When both are supplied, the explicit
         dates win.

    Returns a list (oldest first) of:
      {month, income, spending, net, savings_rate}
    """
    # Canonical pattern (matches dal/cash_flow.py and get_flow_data):
    # income = positive signed_amount in any non-spend, non-transfer category;
    # spending = negative signed_amount in any non-income, non-transfer category.
    # Both sides drop transfer_tag rows.  Whitelist-based income filters
    # silently miss any new income category — switched to blacklist for
    # consistency with sibling endpoints.
    from dal.category_classifications import INCOME_EXCL_FROM_INC as _INCOME_EXCL_FROM_INC
    income_excl = list(_INCOME_EXCL_FROM_INC)
    inc_excl_placeholders = ", ".join("?" for _ in income_excl)

    excl = list(_EXCLUDED_FROM_SPEND | _INCOME_CATEGORIES)
    excl_placeholders = ", ".join("?" for _ in excl)

    params_base = income_excl + excl

    acct_filter = ""
    acct_params: list = []
    if not account_ids and owner_id:
        from dal.owners import resolve_account_ids_for_view
        resolved = resolve_account_ids_for_view(conn, owner_id)
        if resolved is not None:
            account_ids = list(resolved)
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        acct_filter = f" AND account_id IN ({placeholders})"
        acct_params = account_ids

    # Resolve window — explicit dates win over legacy months int.
    if start_date and end_date:
        start_em = start_date[:7]
        end_em = end_date[:7]
        date_filter = f"AND {_EM} BETWEEN ? AND ?"
        date_params: list = [start_em, end_em]
    else:
        date_filter = f"AND posting_date >= date('now', '-{months} months')"
        date_params = []

    rows = conn.execute(
        f"""
        SELECT
            {_EM} as month,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND signed_amount > 0
                          AND COALESCE(category, 'Other Income') NOT IN ({inc_excl_placeholders})
                     THEN signed_amount ELSE 0 END) as income,
            SUM(CASE WHEN transfer_tag IS NULL
                          AND signed_amount < 0
                          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
                     THEN -signed_amount ELSE 0 END) as spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          {date_filter}
          {acct_filter}
        GROUP BY month
        ORDER BY month ASC
        """,
        params_base + date_params + acct_params,
    ).fetchall()

    result = []
    for r in rows:
        income = round(r["income"] or 0, 2)
        spending = round(r["spending"] or 0, 2)
        net = round(income - spending, 2)
        savings_rate = round(net / income * 100, 1) if income > 0 else 0
        result.append({
            "month": r["month"],
            "income": income,
            "spending": spending,
            "net": net,
            "savings_rate": savings_rate,
        })

    return result


# ── Net Worth History ─────────────────────────────────────────────────────────


def get_net_worth_history(
    conn: sqlite3.Connection,
    months: int = 24,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Monthly net worth snapshots for the last N months, reconstructed from
    balance_snapshots + portfolio_snapshots + real_estate table.

    Returns oldest-first list of:
      {month, assets, liabilities, net_worth}
    """
    # Resolve owner filter to account IDs
    acct_filter = ""
    acct_filter_and = ""
    acct_params: list = []
    if owner_id:
        from dal.owners import resolve_owner_account_ids
        resolved = resolve_owner_account_ids(conn, owner_id)
        if resolved:
            ph = ",".join("?" for _ in resolved)
            acct_filter = f"WHERE a.id IN ({ph})"
            acct_filter_and = f"AND a.id IN ({ph})"
            acct_params = list(resolved)

    # Build monthly asset snapshots from balance_snapshots (banking accounts)
    banking_rows = conn.execute(
        f"""
        WITH RECURSIVE month_series AS (
            SELECT date(date('now', 'start of month'), '-{months - 1} months') as m_date
            UNION ALL
            SELECT date(m_date, '+1 month')
            FROM month_series
            WHERE m_date < date('now', 'start of month')
        ),
        latest_balances AS (
            SELECT ms.m_date, a.id as account_id, a.type, a.is_active,
                   (SELECT bs.balance 
                    FROM balance_snapshots bs
                    WHERE bs.account_id = a.id
                      AND bs.as_of < date(ms.m_date, '+1 month')
                    ORDER BY bs.as_of DESC LIMIT 1) as balance
            FROM month_series ms
            CROSS JOIN accounts a
            {acct_filter}
        )
        SELECT strftime('%Y-%m', m_date) as month,
               SUM(CASE WHEN type IN ('checking', 'savings') THEN balance ELSE 0 END) as banking,
               SUM(CASE WHEN type IN ('credit_card', 'loan', 'bnpl', 'mortgage') AND is_active = 1
                        THEN balance ELSE 0 END) as liabilities
        FROM latest_balances
        WHERE balance IS NOT NULL
        GROUP BY month
        ORDER BY month ASC
        """,
        acct_params,
    ).fetchall()

    # Portfolio monthly values (investment / retirement accounts)
    portfolio_rows = conn.execute(
        f"""
        WITH RECURSIVE month_series AS (
            SELECT date(date('now', 'start of month'), '-{months - 1} months') as m_date
            UNION ALL
            SELECT date(m_date, '+1 month')
            FROM month_series
            WHERE m_date < date('now', 'start of month')
        ),
        latest_portfolios AS (
            SELECT ms.m_date, a.id as account_id,
                   (SELECT ps.total_account_value
                    FROM portfolio_snapshots ps
                    WHERE ps.account_id = a.id
                      AND ps.timestamp < date(ms.m_date, '+1 month')
                    ORDER BY ps.timestamp DESC LIMIT 1) as total_account_value
            FROM month_series ms
            CROSS JOIN accounts a
            WHERE a.type IN ('investment', 'retirement')
            {acct_filter_and}
        )
        SELECT strftime('%Y-%m', m_date) as month,
               SUM(total_account_value) as portfolio
        FROM latest_portfolios
        WHERE total_account_value IS NOT NULL
        GROUP BY month
        """,
        acct_params,
    ).fetchall()

    portfolio_map = {r["month"]: (r["portfolio"] or 0) for r in portfolio_rows}

    # Build time-aware real estate values per month
    re_rows = conn.execute("""
        SELECT name, estimated_value, as_of
        FROM real_estate
        WHERE name NOT LIKE '%[%'
        ORDER BY name, as_of ASC
    """).fetchall()

    from collections import defaultdict
    re_timeline: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in re_rows:
        re_timeline[r["name"]].append((r["as_of"][:7], r["estimated_value"]))

    re_by_month: dict[str, float] = {}
    for r in banking_rows:
        month_str = r["month"]
        total = 0.0
        for prop_name, valuations in re_timeline.items():
            latest = None
            for val_month, val_amount in valuations:
                if val_month <= month_str:
                    latest = val_amount
                else:
                    break
            if latest is not None:
                total += latest
        re_by_month[month_str] = total

    # Build time-aware vehicle values per month
    veh_by_month: dict[str, float] = {}
    try:
        vehicle_rows = conn.execute("""
            SELECT vehicle_id as name, estimated_value, valuation_date as as_of
            FROM vehicle_valuations
            ORDER BY name, as_of ASC
        """).fetchall()

        veh_timeline: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for r in vehicle_rows:
            veh_timeline[r["name"]].append((r["as_of"][:7], r["estimated_value"]))

        for r in banking_rows:
            month_str = r["month"]
            total = 0.0
            for veh_name, valuations in veh_timeline.items():
                latest = None
                for val_month, val_amount in valuations:
                    if val_month <= month_str:
                        latest = val_amount
                    else:
                        break
                if latest is not None:
                    total += latest
            veh_by_month[month_str] = total
    except sqlite3.OperationalError:
        pass

    result = []
    for r in banking_rows:
        month = r["month"]
        banking = r["banking"] or 0
        liabilities = r["liabilities"] or 0
        portfolio = portfolio_map.get(month, 0)
        re_value_for_month = re_by_month.get(month, 0.0)
        veh_value_for_month = veh_by_month.get(month, 0.0)
        
        assets = round(banking + portfolio + re_value_for_month + veh_value_for_month, 2)
        net_worth = round(assets + liabilities, 2)  # liabilities are already negative

        result.append({
            "month": month,
            "banking_assets": round(banking, 2),
            "investment_assets": round(portfolio, 2),
            "real_estate_assets": round(re_value_for_month, 2),
            "vehicle_assets": round(veh_value_for_month, 2),
            "assets": assets,
            "liabilities": round(liabilities, 2),
            "net_worth": net_worth,
        })

    return result


# ── Spending Over Time (per category, by month) ───────────────────────────────


def get_category_trend(
    conn: sqlite3.Connection,
    category: str,
    months: int = 12,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Monthly spending trend for a single category.

    Returns oldest-first list of {month, total_spent, transaction_count}.
    """
    params: list = [category, months]
    acct_filter = ""
    if not account_ids and owner_id:
        from dal.owners import resolve_account_ids_for_view
        resolved = resolve_account_ids_for_view(conn, owner_id)
        if resolved is not None:
            account_ids = list(resolved)
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        acct_filter = f" AND account_id IN ({placeholders})"
        params.extend(account_ids)

    rows = conn.execute(
        f"""
        SELECT {_EM} as month,
               SUM(-signed_amount) as total_spent,
               COUNT(*) as transaction_count
        FROM transactions
        WHERE status = 'posted'
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') = ?
          AND posting_date >= date('now', '-? months')
          {acct_filter}
        GROUP BY month
        ORDER BY month ASC
        """,
        params,
    ).fetchall()

    return [
        {
            "month": r["month"],
            "total_spent": round(r["total_spent"] or 0, 2),
            "transaction_count": r["transaction_count"],
        }
        for r in rows
    ]


# ── CSV Export ────────────────────────────────────────────────────────────────


def export_transactions_csv(
    conn: sqlite3.Connection,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_ids: Optional[list[str]] = None,
    institution_id: Optional[str] = None,
    owner_id: str | None = None,
) -> str:
    """
    Export transactions to a CSV string.

    Columns: date, description, category, amount, direction, account_id,
             institution_id, status
    """
    clauses = ["status != 'deleted'"]
    params: list = []

    if start_date:
        clauses.append("posting_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("posting_date <= ?")
        params.append(end_date)
    if institution_id:
        clauses.append("institution_id = ?")
        params.append(institution_id)
    if not account_ids and owner_id:
        from dal.owners import resolve_account_ids_for_view
        resolved = resolve_account_ids_for_view(conn, owner_id)
        if resolved is not None:
            account_ids = list(resolved)
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        clauses.append(f"account_id IN ({placeholders})")
        params.extend(account_ids)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT posting_date, description, category, amount, signed_amount,
               direction, account_id, institution_id, status
        FROM transactions
        WHERE {where}
        ORDER BY posting_date DESC, created_at DESC
        """,
        params,
    ).fetchall()

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "date", "description", "category", "amount", "signed_amount",
            "direction", "account_id", "institution_id", "status",
        ],
    )
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "date": r["posting_date"],
            "description": r["description"] or "",
            "category": r["category"] or "Uncategorized",
            "amount": r["amount"],
            "signed_amount": r["signed_amount"],
            "direction": r["direction"],
            "account_id": r["account_id"],
            "institution_id": r["institution_id"],
            "status": r["status"],
        })

    return output.getvalue()


# ── Summary Stats ─────────────────────────────────────────────────────────────


def get_period_summary(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> dict:
    """
    High-level summary for a date range: total income, spending, net,
    transaction count, top 3 categories.
    """
    spending = get_spending_by_category(conn, start_date, end_date, account_ids, owner_id=owner_id)

    # Income: direct query using actual date range (not months=1)
    income_cats = list(_INCOME_CATEGORIES)
    ic_ph = ", ".join("?" for _ in income_cats)
    income_params: list = income_cats + [start_date, end_date]

    inc_acct_filter = ""
    inc_account_ids = account_ids
    if not inc_account_ids and owner_id:
        from dal.owners import resolve_account_ids_for_view
        resolved = resolve_account_ids_for_view(conn, owner_id)
        if resolved is not None:
            inc_account_ids = list(resolved)
    if inc_account_ids:
        a_ph = ", ".join("?" for _ in inc_account_ids)
        inc_acct_filter = f" AND account_id IN ({a_ph})"
        income_params.extend(inc_account_ids)

    inc_row = conn.execute(
        f"""
        SELECT COALESCE(SUM(signed_amount), 0) as total
        FROM transactions
        WHERE status = 'posted' AND transfer_tag IS NULL
          AND signed_amount > 0
          AND category IN ({ic_ph})
          AND posting_date >= ? AND posting_date <= ?
          {inc_acct_filter}
        """,
        income_params,
    ).fetchone()
    total_income = round(inc_row["total"] or 0, 2)
    total_spending = sum(c["total_spent"] for c in spending)
    top_categories = spending[:3]

    return {
        "period": {"start": start_date, "end": end_date},
        "total_income": round(total_income, 2),
        "total_spending": round(total_spending, 2),
        "net": round(total_income - total_spending, 2),
        "top_categories": top_categories,
        "categories_with_spend": len(spending),
    }


# ── Flow Data (Sankey) ────────────────────────────────────────────────────────


def get_flow_data(
    conn: sqlite3.Connection,
    months: int = 1,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """
    Income by category + spending by category for a period.

    Two ways to specify the window — see ``get_cash_flow_report`` for
    the same contract.  Explicit ``start_date`` / ``end_date`` are
    preferred so the frontend can anchor presets like "Year to Date" or
    "Last 30 Days" in local time without UTC drift.

    Used to build a Sankey diagram: income sources → Income → spending
    categories.

    Returns:
      income_categories: [{category, total, count}]
      spending_categories: [{category, total, count}]
      total_income, total_spending, net, savings_rate, start_date, end_date
    """
    # Canonical exclusion: spend blacklist | income whitelist
    # (mirrors dal/cash_flow.py).  An ad-hoc set used to live here and
    # missed 12 income categories — any debit in those categories would
    # silently leak into the spending breakdown of the Sankey.
    excl = list(_EXCLUDED_FROM_SPEND | _INCOME_CATEGORIES)
    excl_placeholders = ", ".join("?" for _ in excl)

    # For income, use the canonical exclusion set
    income_excl = list(_INCOME_EXCL_FROM_INC)

    acct_filter = ""
    acct_params: list = []
    if not account_ids and owner_id:
        from dal.owners import resolve_account_ids_for_view
        resolved = resolve_account_ids_for_view(conn, owner_id)
        if resolved is not None:
            account_ids = list(resolved)
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        acct_filter = f" AND account_id IN ({placeholders})"
        acct_params = list(account_ids)

    # Resolve window — explicit dates win over legacy months int.
    if start_date and end_date:
        start_em = start_date[:7]
        end_em = end_date[:7]
        date_filter = f"AND {_EM} BETWEEN ? AND ?"
        date_params: list = [start_em, end_em]
    else:
        date_filter = f"AND posting_date >= date('now', '-{months} months')"
        date_params = []

    # ── Income by category ────────────────────────────────────────────────
    income_excl_placeholders = ", ".join("?" for _ in income_excl)
    income_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Other Income') as category,
               SUM(signed_amount) as total,
               COUNT(*) as count
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount > 0
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Other Income') NOT IN ({income_excl_placeholders})
          {date_filter}
          {acct_filter}
        GROUP BY category
        ORDER BY total DESC
        """,
        income_excl + date_params + acct_params,
    ).fetchall()

    # ── Spending by category ──────────────────────────────────────────────
    spend_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Uncategorized') as category,
               SUM(-signed_amount) as total,
               COUNT(*) as count
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount < 0
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
          {date_filter}
          {acct_filter}
        GROUP BY category
        ORDER BY total DESC
        """,
        excl + date_params + acct_params,
    ).fetchall()

    income_cats = [
        {"category": r["category"], "total": round(r["total"] or 0, 2), "count": r["count"]}
        for r in income_rows
    ]
    spend_cats = [
        {"category": r["category"], "total": round(r["total"] or 0, 2), "count": r["count"]}
        for r in spend_rows
    ]

    total_income = round(sum(c["total"] for c in income_cats), 2)
    total_spending = round(sum(c["total"] for c in spend_cats), 2)
    net = round(total_income - total_spending, 2)
    savings_rate = round(net / total_income * 100, 1) if total_income > 0 else 0

    return {
        "income_categories": income_cats,
        "spending_categories": spend_cats,
        "total_income": total_income,
        "total_spending": total_spending,
        "net": net,
        "savings_rate": savings_rate,
        "start_date": start_date,
        "end_date": end_date,
    }


# ── Merchant List ─────────────────────────────────────────────────────────────


def get_merchant_list(
    conn: sqlite3.Connection,
    months: int = 6,
    limit: int = 50,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Return ranked merchants by spend for the period with per-month totals.

    Each entry:
      { merchant, total, tx_count, category, monthly: [{month, total}, ...] }
    """
    acct_filter = ""
    acct_params: list = []
    if not account_ids and owner_id:
        from dal.owners import resolve_account_ids_for_view
        resolved = resolve_account_ids_for_view(conn, owner_id)
        if resolved is not None:
            account_ids = list(resolved)
    if account_ids:
        placeholders = ",".join("?" for _ in account_ids)
        acct_filter = f"AND account_id IN ({placeholders})"
        acct_params = list(account_ids)

    excl = list(_INCOME_CATEGORIES | _EXCLUDED_FROM_SPEND)
    excl_ph = ",".join("?" for _ in excl)

    # Ranked totals — real spend only: no income, no transfers
    rank_rows = conn.execute(
        f"""
        SELECT
            COALESCE(merchant, description) AS merchant,
            SUM(ABS(signed_amount))         AS total,
            COUNT(*)                        AS tx_count,
            MAX(category)                   AS category
        FROM transactions
        WHERE signed_amount < 0
          AND transfer_tag IS NULL
          AND COALESCE(category, '') NOT IN ({excl_ph})
          AND posting_date >= date('now', '-{months} months')
          {acct_filter}
          AND merchant IS NOT NULL
        GROUP BY COALESCE(merchant, description)
        ORDER BY total DESC
        LIMIT ?
        """,
        excl + acct_params + [limit],
    ).fetchall()

    if not rank_rows:
        return []

    merchant_names = [r["merchant"] for r in rank_rows]
    placeholders_m = ",".join("?" for _ in merchant_names)

    # Monthly breakdown per merchant
    monthly_rows = conn.execute(
        f"""
        SELECT
            COALESCE(merchant, description) AS merchant,
            {_EM} AS month,
            SUM(ABS(signed_amount))         AS total
        FROM transactions
        WHERE signed_amount < 0
          AND transfer_tag IS NULL
          AND COALESCE(category, '') NOT IN ({excl_ph})
          AND posting_date >= date('now', '-{months} months')
          AND COALESCE(merchant, description) IN ({placeholders_m})
          {acct_filter}
        GROUP BY COALESCE(merchant, description), {_EM}
        ORDER BY month
        """,
        excl + merchant_names + acct_params,
    ).fetchall()

    # Index monthly data by merchant
    from collections import defaultdict
    monthly_map: dict[str, list] = defaultdict(list)
    for r in monthly_rows:
        monthly_map[r["merchant"]].append(
            {"month": r["month"], "total": round(r["total"] or 0, 2)}
        )

    result = []
    for r in rank_rows:
        result.append({
            "merchant": r["merchant"],
            "total": round(r["total"] or 0, 2),
            "tx_count": r["tx_count"],
            "category": r["category"],
            "monthly": monthly_map.get(r["merchant"], []),
        })
    return result


# ── Merchant Flow (Sankey shape) ──────────────────────────────────────────────


def get_merchant_flow_data(
    conn: sqlite3.Connection,
    months: int = 6,
    selected_merchants: Optional[list[str]] = None,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> dict:
    """
    Return Sankey-shaped data with selected merchants as spending nodes.

    If selected_merchants is None/empty → auto-select top 10.
    Unselected merchants are collapsed into "Other".

    Returns same shape as get_flow_data() for drop-in chart compatibility.
    """
    acct_filter = ""
    acct_params: list = []
    if not account_ids and owner_id:
        from dal.owners import resolve_account_ids_for_view
        resolved = resolve_account_ids_for_view(conn, owner_id)
        if resolved is not None:
            account_ids = list(resolved)
    if account_ids:
        ph = ",".join("?" for _ in account_ids)
        acct_filter = f"AND account_id IN ({ph})"
        acct_params = list(account_ids)

    # Income side — uses canonical exclusion set
    income_excl = list(_INCOME_EXCL_FROM_INC | {"Uncategorized"})
    income_excl_ph = ",".join("?" for _ in income_excl)

    income_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Other Income') AS category,
               SUM(signed_amount)                 AS total,
               COUNT(*)                           AS count
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount > 0
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Other Income') NOT IN ({income_excl_ph})
          AND posting_date >= date('now', '-{months} months')
          {acct_filter}
        GROUP BY category ORDER BY total DESC
        """,
        income_excl + acct_params,
    ).fetchall()

    total_income = round(sum(r["total"] or 0 for r in income_rows), 2)
    income_cats = [
        {"category": r["category"], "total": round(r["total"] or 0, 2), "count": r["count"]}
        for r in income_rows
    ]

    # Spending side — real spend only: signed_amount < 0, no transfers
    spend_excl = list(_INCOME_CATEGORIES | _EXCLUDED_FROM_SPEND)
    spend_excl_ph = ",".join("?" for _ in spend_excl)

    # All spending by merchant
    all_spend = conn.execute(
        f"""
        SELECT
            COALESCE(merchant, description) AS merchant,
            SUM(ABS(signed_amount))         AS total,
            COUNT(*)                        AS count
        FROM transactions
        WHERE signed_amount < 0
          AND transfer_tag IS NULL
          AND COALESCE(category, '') NOT IN ({spend_excl_ph})
          AND posting_date >= date('now', '-{months} months')
          {acct_filter}
          AND merchant IS NOT NULL
        GROUP BY COALESCE(merchant, description)
        ORDER BY total DESC
        """,
        spend_excl + acct_params,
    ).fetchall()

    # Auto-select top 10 if no selection provided
    if not selected_merchants:
        selected_merchants = [r["merchant"] for r in all_spend[:10]]

    selected_set = set(selected_merchants)
    selected_totals: dict[str, float] = {}
    other_total = 0.0

    for r in all_spend:
        m = r["merchant"]
        t = r["total"] or 0
        if m in selected_set:
            selected_totals[m] = round(t, 2)
        else:
            other_total += t

    # Build spending nodes in selection order
    spend_cats = [
        {"category": m, "total": selected_totals.get(m, 0), "count": 0}
        for m in selected_merchants
        if m in selected_totals
    ]
    if other_total > 0.01:
        spend_cats.append({"category": "Other", "total": round(other_total, 2), "count": 0})

    total_spending = round(sum(c["total"] for c in spend_cats), 2)
    net = round(total_income - total_spending, 2)
    savings_rate = round(net / total_income * 100, 1) if total_income > 0 else 0

    return {
        "income_categories": income_cats,
        "spending_categories": spend_cats,
        "total_income": total_income,
        "total_spending": total_spending,
        "net": net,
        "savings_rate": savings_rate,
        "available_merchants": [r["merchant"] for r in all_spend],
        "selected_merchants": selected_merchants,
    }


# ── Spending Comparison ───────────────────────────────────────────────────────


def get_spending_comparison(
    conn: sqlite3.Connection,
    reference_date: str,
    timeframe: str = "month_vs_last_month",
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Cumulative spending comparison for different timeframes.
    Timeframes: month_vs_last_month, month_vs_last_year, month_vs_avg_month, year_vs_last_year
    """
    from datetime import datetime, timezone
    import calendar
    from dateutil.relativedelta import relativedelta

    ref_dt = datetime.strptime(reference_date, "%Y-%m-%d")
    current_day = ref_dt.day
    current_month = ref_dt.month
    
    excl = list(_EXCLUDED_FROM_SPEND | _INCOME_CATEGORIES)
    excl_ph = ",".join("?" for _ in excl)
    
    acct_filter = ""
    acct_params: list = []
    if not account_ids and owner_id:
        from dal.owners import resolve_account_ids_for_view
        resolved = resolve_account_ids_for_view(conn, owner_id)
        if resolved is not None:
            account_ids = list(resolved)
    if account_ids:
        ph = ",".join("?" for _ in account_ids)
        acct_filter = f"AND account_id IN ({ph})"
        acct_params = list(account_ids)

    if timeframe == "year_vs_last_year":
        this_year = ref_dt.year
        last_year = this_year - 1
        
        ty_rows = conn.execute(
            f"""
            SELECT cast(strftime('%m', posting_date) as integer) as month, SUM(-signed_amount) as spent
            FROM transactions
            WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
              AND strftime('%Y', posting_date) = ?
              {acct_filter}
            GROUP BY month
            """,
            excl + [str(this_year)] + acct_params
        ).fetchall()
        
        ly_rows = conn.execute(
            f"""
            SELECT cast(strftime('%m', posting_date) as integer) as month, SUM(-signed_amount) as spent
            FROM transactions
            WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
              AND strftime('%Y', posting_date) = ?
              {acct_filter}
            GROUP BY month
            """,
            excl + [str(last_year)] + acct_params
        ).fetchall()
        
        ty_map = {r["month"]: float(r["spent"] or 0) for r in ty_rows}
        ly_map = {r["month"]: float(r["spent"] or 0) for r in ly_rows}
        
        months_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        
        result = []
        cum_ty = 0.0
        cum_ly = 0.0
        
        for m in range(1, 13):
            cum_ly += ly_map.get(m, 0.0)
            data_point = {
                "period": months_names[m-1],
                "Previous": round(cum_ly, 2)
            }
            if ref_dt.year < datetime.now(timezone.utc).year or m <= current_month:
                cum_ty += ty_map.get(m, 0.0)
                data_point["Current"] = round(cum_ty, 2)
            result.append(data_point)
            
        return result

    # Monthly timeframes
    this_month_start = ref_dt.replace(day=1)
    _, last_day_this_month = calendar.monthrange(ref_dt.year, ref_dt.month)
    this_month_end = ref_dt.replace(day=last_day_this_month)
    
    this_month_rows = conn.execute(
        f"""
        SELECT cast(strftime('%d', posting_date) as integer) as day, SUM(-signed_amount) as daily_spent
        FROM transactions
        WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
          AND posting_date >= ? AND posting_date <= ?
          {acct_filter}
        GROUP BY day
        """,
        excl + [this_month_start.strftime("%Y-%m-%d"), this_month_end.strftime("%Y-%m-%d")] + acct_params,
    ).fetchall()
    this_month_map = {r["day"]: float(r["daily_spent"] or 0) for r in this_month_rows}
    
    prev_map = {}
    max_days = last_day_this_month
    last_day_prev = 31

    if timeframe == "month_vs_last_month":
        last_month_start = this_month_start - relativedelta(months=1)
        _, last_day_prev = calendar.monthrange(last_month_start.year, last_month_start.month)
        last_month_end = last_month_start.replace(day=last_day_prev)
        max_days = max(max_days, last_day_prev, 31)
        
        prev_rows = conn.execute(
            f"""
            SELECT cast(strftime('%d', posting_date) as integer) as day, SUM(-signed_amount) as daily_spent
            FROM transactions
            WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
              AND posting_date >= ? AND posting_date <= ?
              {acct_filter}
            GROUP BY day
            """,
            excl + [last_month_start.strftime("%Y-%m-%d"), last_month_end.strftime("%Y-%m-%d")] + acct_params,
        ).fetchall()
        prev_map = {r["day"]: float(r["daily_spent"] or 0) for r in prev_rows}

    elif timeframe == "month_vs_last_year":
        last_year_start = this_month_start - relativedelta(years=1)
        _, last_day_prev = calendar.monthrange(last_year_start.year, last_year_start.month)
        last_year_end = last_year_start.replace(day=last_day_prev)
        max_days = max(max_days, last_day_prev, 31)
        
        prev_rows = conn.execute(
            f"""
            SELECT cast(strftime('%d', posting_date) as integer) as day, SUM(-signed_amount) as daily_spent
            FROM transactions
            WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
              AND posting_date >= ? AND posting_date <= ?
              {acct_filter}
            GROUP BY day
            """,
            excl + [last_year_start.strftime("%Y-%m-%d"), last_year_end.strftime("%Y-%m-%d")] + acct_params,
        ).fetchall()
        prev_map = {r["day"]: float(r["daily_spent"] or 0) for r in prev_rows}

    elif timeframe == "month_vs_avg_month":
        avg_end = this_month_start - relativedelta(days=1)
        avg_start = this_month_start - relativedelta(months=6)
        max_days = max(max_days, 31)
        last_day_prev = 31
        
        prev_rows = conn.execute(
            f"""
            SELECT cast(strftime('%d', posting_date) as integer) as day, SUM(-signed_amount) as daily_spent
            FROM transactions
            WHERE status = 'posted' AND signed_amount < 0 AND transfer_tag IS NULL
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
              AND posting_date >= ? AND posting_date <= ?
              {acct_filter}
            GROUP BY day
            """,
            excl + [avg_start.strftime("%Y-%m-%d"), avg_end.strftime("%Y-%m-%d")] + acct_params,
        ).fetchall()
        prev_map = {r["day"]: float(r["daily_spent"] or 0) / 6.0 for r in prev_rows}

    result = []
    cum_this = 0.0
    cum_prev = 0.0

    for day in range(1, max_days + 1):
        if day <= last_day_prev:
            cum_prev += prev_map.get(day, 0.0)
            
        data_point: dict = {
            "period": f"Day {day}",
            "Previous": round(cum_prev, 2)
        }
        
        if day <= current_day and day <= last_day_this_month:
            cum_this += this_month_map.get(day, 0.0)
            data_point["Current"] = round(cum_this, 2)
            
        result.append(data_point)
        
    return result

