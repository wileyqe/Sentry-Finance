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
from datetime import date, timedelta
from typing import Optional

from dal.owners import build_account_filter
from dal.payroll import find_matching_deposit_tx_id, get_flow_contribution
from dal.flow_classification import (
    BucketLabel,
    brokerage_buy_matches_transfer,
    match_rule_matches,
)
from dal import income_sources as income_sources_dal

log = logging.getLogger("sentry.dal.reports")

# ── Phase 14 Phase B — bucket invariant tolerance ─────────────────────────────
# Rounding drift between integer-cents splits and float signed_amount can
# accumulate to ~50¢ over a busy month. A $1 tolerance is the published
# contract; wider drift emits a structured warning.
_BUCKET_INVARIANT_TOLERANCE_CENTS: int = 100

# Attribution-aware month expression (mirrors dal/cash_flow.py)
_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"

# ── Category sets — imported from canonical single source of truth ────────────
from dal.category_classifications import (
    INCOME_CATEGORIES as _INCOME_CATEGORIES,
    INCOME_EXCL_FROM_INC as _INCOME_EXCL_FROM_INC,
    get_income_exclusion_clause,
    get_spend_exclusion_clause,
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
    if exclude_transfers:
        excl_placeholders, excl = get_spend_exclusion_clause()
    else:
        excl = list(_INCOME_CATEGORIES)
        excl_placeholders = ", ".join("?" for _ in excl)

    params: list = [start_date, end_date] + excl

    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)
    params.extend(acct_params)

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
    inc_excl_placeholders, income_excl = get_income_exclusion_clause()
    excl_placeholders, excl = get_spend_exclusion_clause()

    params_base = income_excl + excl

    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)

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
        if resolved is not None:
            if not resolved:
                # Owner exists but has zero accounts (e.g. Amy with no
                # synthetic data) — short-circuit to an empty history so
                # we don't accidentally fall through to "all accounts".
                return []
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

    # Build time-aware real estate values per month.
    # When owner-scoped, restrict to that owner's properties (added in v22).
    re_sql = """
        SELECT name, estimated_value, as_of
        FROM real_estate
        WHERE name NOT LIKE '%[%'
    """
    re_params: list = []
    if owner_id:
        re_sql += " AND LOWER(owner_id) = LOWER(?)"
        re_params.append(owner_id)
    re_sql += " ORDER BY name, as_of ASC"
    re_rows = conn.execute(re_sql, re_params).fetchall()

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

    # Build time-aware vehicle values per month.
    # When owner-scoped, restrict via vehicle_assets.owner_id (added in v22).
    veh_by_month: dict[str, float] = {}
    try:
        veh_sql = """
            SELECT vv.vehicle_id as name, vv.estimated_value,
                   vv.valuation_date as as_of
            FROM vehicle_valuations vv
        """
        veh_params: list = []
        if owner_id:
            veh_sql += """
                JOIN vehicle_assets va ON va.id = vv.vehicle_id
                WHERE LOWER(va.owner_id) = LOWER(?)
            """
            veh_params.append(owner_id)
        veh_sql += " ORDER BY name, as_of ASC"
        vehicle_rows = conn.execute(veh_sql, veh_params).fetchall()

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
    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)
    params.extend(acct_params)

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
    # This function composes its WHERE via a `clauses` list rather than a
    # single string, so we strip the leading " AND " the helper prepends.
    acct_sql, acct_params = build_account_filter(conn, owner_id, account_ids)
    if acct_sql:
        clauses.append(acct_sql.lstrip()[4:])
        params.extend(acct_params)

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

    inc_acct_filter, inc_acct_params = build_account_filter(conn, owner_id, account_ids)
    income_params.extend(inc_acct_params)

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
      payroll_decomposition: gross-pay decomposition for any
        `payroll_snapshots` rows in the window. See "Phase 14 — gross
        paycheck decomposition" notes below.

    Phase 14 — gross paycheck decomposition (Phase A)
    -------------------------------------------------
    When `payroll_snapshots` rows exist for the window, the response
    gains a `payroll_decomposition` block (see `dal.payroll.get_flow_contribution`)
    plus an `excluded_transaction_ids` list. For each payroll row, a
    matching positive-amount deposit transaction is searched for on
    `(owner_id, month, source_label substring)`. If found, that
    transaction is excluded from `income_categories` and `total_income`
    is bumped by the gross-vs-net delta — so total_income reflects the
    gross-pay picture for matched rows. Unmatched payroll rows appear in
    `payroll_decomposition` for downstream visibility (Phase D
    accountability scorecard) but do not change income totals.
    """
    # Canonical exclusion: spend blacklist | income whitelist
    # (mirrors dal/cash_flow.py).  An ad-hoc set used to live here and
    # missed 12 income categories — any debit in those categories would
    # silently leak into the spending breakdown of the Sankey.
    excl_placeholders, excl = get_spend_exclusion_clause()

    # For income, use the canonical exclusion set
    income_excl = list(_INCOME_EXCL_FROM_INC)

    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)

    # Resolve window — explicit dates win over legacy months int.
    if start_date and end_date:
        start_em = start_date[:7]
        end_em = end_date[:7]
        date_filter = f"AND {_EM} BETWEEN ? AND ?"
        date_params: list = [start_em, end_em]
        contrib_start, contrib_end = start_em, end_em
    else:
        date_filter = f"AND posting_date >= date('now', '-{months} months')"
        date_params = []
        # Approximate the window for payroll lookup (payroll uses YYYY-MM
        # buckets; legacy months arg is a relative window from today).
        today = date.today()
        approx_start = (today - timedelta(days=months * 31)).strftime("%Y-%m")
        contrib_start, contrib_end = approx_start, today.strftime("%Y-%m")

    # ── Phase 14 Phase A: payroll decomposition + deposit-match dedup ─────
    payroll_contrib = get_flow_contribution(
        conn, contrib_start, contrib_end, owner_id=owner_id
    )
    excluded_tx_ids: list[str] = []
    matched_gross_minus_net_cents = 0
    for prow in payroll_contrib["payroll_rows"]:
        match_id = find_matching_deposit_tx_id(
            conn,
            source_label=prow["source_label"] or "",
            pay_period=prow["pay_period"],
            owner_id=owner_id,
        )
        if match_id is not None and match_id not in excluded_tx_ids:
            excluded_tx_ids.append(match_id)
            matched_gross_minus_net_cents += (
                prow["gross_cents"] - prow["net_cents"]
            )
            prow["matched_txn_id"] = match_id
        else:
            prow["matched_txn_id"] = None

    # ── Income by category (with matched-deposit exclusion) ───────────────
    income_excl_placeholders = ", ".join("?" for _ in income_excl)
    excluded_clause = ""
    excluded_params: list = []
    if excluded_tx_ids:
        excluded_clause = (
            "AND id NOT IN (" + ", ".join("?" for _ in excluded_tx_ids) + ")"
        )
        excluded_params = list(excluded_tx_ids)

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
          {excluded_clause}
          {date_filter}
          {acct_filter}
        GROUP BY category
        ORDER BY total DESC
        """,
        income_excl + excluded_params + date_params + acct_params,
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

    total_income_from_txns = round(sum(c["total"] for c in income_cats), 2)
    # For matched rows, bump total_income by (gross - net) so it reflects
    # gross pay, not net deposit. Net was already excluded by NOT IN above.
    matched_gross_delta = round(matched_gross_minus_net_cents / 100.0, 2)
    total_income = round(total_income_from_txns + matched_gross_delta, 2)
    total_spending = round(sum(c["total"] for c in spend_cats), 2)
    net = round(total_income - total_spending, 2)
    savings_rate = round(net / total_income * 100, 1) if total_income > 0 else 0

    payroll_decomposition = dict(payroll_contrib)
    payroll_decomposition["excluded_transaction_ids"] = list(excluded_tx_ids)

    # ── Phase 14 Phase B — three-bucket terminal classification ──────────
    #
    # Every dollar in the period must land in exactly one of CONSUMED /
    # STORED_LIQUID / STORED_ILLIQUID. Invariant: sum(bucket_totals) ==
    # total_inflow_cents ± _BUCKET_INVARIANT_TOLERANCE_CENTS. Emit a
    # structured warning when drift exceeds the tolerance; expose the
    # totals either way so callers can render.
    bucket_result = _compute_bucket_totals(
        conn,
        acct_filter=acct_filter,
        acct_params=acct_params,
        date_filter=date_filter,
        date_params=date_params,
        spend_cats=spend_cats,
        withholdings=payroll_contrib["payroll_rows"],
        income_cats=income_cats,
        matched_gross_minus_net_cents=matched_gross_minus_net_cents,
        contrib_start=contrib_start,
        contrib_end=contrib_end,
        owner_id=owner_id,
        account_ids=account_ids,
    )

    # Attach bucket to each spending category node (spend rows are all
    # non-transfer debits → CONSUMED by definition).
    for c in spend_cats:
        c["bucket"] = BucketLabel.CONSUMED.value

    return {
        "income_categories": income_cats,
        "spending_categories": spend_cats,
        "total_income": total_income,
        "total_spending": total_spending,
        "net": net,
        "savings_rate": savings_rate,
        "start_date": start_date,
        "end_date": end_date,
        "payroll_decomposition": payroll_decomposition,
        # ── Phase 14 Phase B fields ──
        "bucket_totals": {
            "CONSUMED":        round(bucket_result["consumed_cents"] / 100.0, 2),
            "STORED_LIQUID":   round(bucket_result["liquid_cents"] / 100.0, 2),
            "STORED_ILLIQUID": round(bucket_result["illiquid_cents"] / 100.0, 2),
        },
        "bucket_totals_cents": {
            "CONSUMED":        bucket_result["consumed_cents"],
            "STORED_LIQUID":   bucket_result["liquid_cents"],
            "STORED_ILLIQUID": bucket_result["illiquid_cents"],
        },
        "total_inflow_cents": bucket_result["total_inflow_cents"],
        "bucket_invariant_drift_cents": bucket_result["drift_cents"],
        "mortgage_splits": bucket_result["mortgage_splits"],
        "transfer_flows": bucket_result["transfer_flows"],
        "bypass_flows": bucket_result["bypass_flows"],
        "reinvestment_flows": bucket_result["reinvestment_flows"],
    }


# ── Phase 14 Phase B — bucket-totals helper ───────────────────────────────────


def _compute_bucket_totals(
    conn: sqlite3.Connection,
    *,
    acct_filter: str,
    acct_params: list,
    date_filter: str,
    date_params: list,
    spend_cats: list[dict],
    withholdings: list[dict],
    income_cats: list[dict],
    matched_gross_minus_net_cents: int,
    contrib_start: str,
    contrib_end: str,
    owner_id: str | None,
    account_ids: Optional[list[str]] = None,
) -> dict:
    """Roll every outflow in the window into CONSUMED / STORED_LIQUID /
    STORED_ILLIQUID totals and verify the Phase B invariant.

    The five contributors to the bucket totals:

      1. Ordinary non-transfer spending (``spend_cats``) → CONSUMED.
      2. Payroll withholdings (``withholdings``) → CONSUMED in Phase B.
      3. Mortgage payments → split via ``loan_payment_splits``:
         principal → STORED_ILLIQUID, interest + escrow → CONSUMED.
      4. Transfer-tagged debits → classifier keyed on peer account type
         (retirement/HSA → illiquid; checking/savings → liquid;
         brokerage → illiquid when a matching buy exists within 5 days,
         else liquid).
      5. Employer-match bypass pseudo-flows from the ``income_sources``
         registry (``bypass_cash_routing=1``) → STORED_ILLIQUID and bump
         ``total_inflow_cents`` (they have no cash leg, so they don't
         appear in ``income_categories``).

    Returns
    -------
    dict with integer-cents fields::

        {
            "consumed_cents": int,
            "liquid_cents": int,
            "illiquid_cents": int,
            "total_inflow_cents": int,
            "drift_cents": int,  # signed: positive when buckets exceed inflow
            "mortgage_splits": [...],
            "transfer_flows":  [...],
            "bypass_flows":    [...],
        }
    """
    consumed_cents = 0
    liquid_cents = 0
    illiquid_cents = 0

    # 1. Ordinary spending → CONSUMED.
    consumed_cents += int(round(sum(c["total"] for c in spend_cats) * 100))

    # 2. Withholdings → CONSUMED (Phase B keeps Phase A's all-CONSUMED default;
    # retirement-portion routing lives in the bypass_flows path instead).
    for prow in withholdings:
        for w in prow.get("withholdings", []):
            if w.get("bucket") == BucketLabel.CONSUMED.value:
                consumed_cents += int(w.get("cents", 0))
            elif w.get("bucket") == BucketLabel.STORED_ILLIQUID.value:
                illiquid_cents += int(w.get("cents", 0))
            elif w.get("bucket") == BucketLabel.STORED_LIQUID.value:
                liquid_cents += int(w.get("cents", 0))

    # 3. Mortgage payments — pull the EXCLUDED_FROM_SPEND rows separately
    #    and attach decomposition when available. Non-transfer rows only;
    #    transfer-tagged mortgage payments are handled by the transfer path.
    mortgage_rows = conn.execute(
        f"""
        SELECT t.id, t.signed_amount, t.posting_date, t.account_id,
               t.category, s.principal_cents, s.interest_cents,
               s.escrow_cents, s.method
        FROM transactions t
        LEFT JOIN loan_payment_splits s ON s.transaction_id = t.id
        WHERE t.status = 'posted'
          AND t.signed_amount < 0
          AND t.transfer_tag IS NULL
          AND t.category IN ('Mortgage', 'Mortgages')
          {date_filter}
          {acct_filter}
        ORDER BY t.posting_date
        """,
        date_params + acct_params,
    ).fetchall()

    mortgage_splits: list[dict] = []
    for r in mortgage_rows:
        total_cents = int(round(abs(float(r["signed_amount"])) * 100))
        if r["principal_cents"] is not None:
            principal = int(r["principal_cents"])
            interest = int(r["interest_cents"])
            escrow = int(r["escrow_cents"])
            illiquid_cents += principal
            consumed_cents += interest + escrow
            mortgage_splits.append({
                "transaction_id": r["id"],
                "posting_date": r["posting_date"][:10],
                "principal_cents": principal,
                "interest_cents": interest,
                "escrow_cents": escrow,
                "method": r["method"],
            })
        else:
            # Unsplit mortgage payment — fall back to all-CONSUMED so the
            # invariant still holds. The pipeline step will compute a split
            # on the next refresh.
            consumed_cents += total_cents
            mortgage_splits.append({
                "transaction_id": r["id"],
                "posting_date": r["posting_date"][:10],
                "principal_cents": 0,
                "interest_cents": total_cents,
                "escrow_cents": 0,
                "method": "unsplit",
            })

    # 4. Transfer-tagged debits — classify via peer account type.
    #    NOTE ON ACCOUNTING: STORED_LIQUID absorbs residuals (inflow not
    #    otherwise accounted for), so transfers to a liquid peer do NOT
    #    add to ``liquid_cents`` here — they are implicit in the residual.
    #    Transfers to illiquid peers DO add to ``illiquid_cents`` because
    #    illiquid is fully explicit. ``transfer_flows`` still records
    #    every leg for UI visibility.
    # Build an aliased date+account filter so the JOIN is unambiguous.
    t1_em = "COALESCE(t1.effective_month, strftime('%Y-%m', t1.posting_date))"
    if date_params:
        t1_date_filter = f"AND {t1_em} BETWEEN ? AND ?"
    else:
        # Relative-months window: relies on an exact swap from the legacy branch.
        t1_date_filter = date_filter.replace("posting_date", "t1.posting_date")

    t1_acct_filter, t1_acct_params = build_account_filter(
        conn, owner_id, account_ids, column="t1.account_id",
    )

    transfer_rows = conn.execute(
        f"""
        SELECT t1.id, t1.signed_amount, t1.posting_date, t1.account_id,
               t1.category,
               t2.account_id AS peer_account_id, a2.type AS peer_type
        FROM transactions t1
        JOIN transactions t2
             ON t1.transfer_tag = t2.transfer_tag AND t1.id != t2.id
        JOIN accounts a2 ON a2.id = t2.account_id
        WHERE t1.status = 'posted'
          AND t1.signed_amount < 0
          AND t1.transfer_tag IS NOT NULL
          {t1_date_filter}
          {t1_acct_filter}
        """,
        date_params + t1_acct_params,
    ).fetchall()

    transfer_flows: list[dict] = []
    # Dedup: each transfer has two legs but we want to count the outflow only.
    # signed_amount < 0 filter already selects the debit leg.
    for r in transfer_rows:
        amt_cents = int(round(abs(float(r["signed_amount"])) * 100))
        peer = (r["peer_type"] or "").strip().lower()

        brokerage_matched = False
        if peer in ("investment", "brokerage"):
            brokerage_matched = brokerage_buy_matches_transfer(
                conn, r["peer_account_id"], r["posting_date"][:10], window_days=5,
            )

        bucket = BucketLabel.CONSUMED
        try:
            bucket = _classify_transfer(
                peer_type=peer,
                brokerage_buy_matched=brokerage_matched,
            )
        except Exception as e:
            log.warning("bucket classifier raised on transfer %s: %s", r["id"], e)

        if bucket == BucketLabel.STORED_ILLIQUID:
            illiquid_cents += amt_cents
        elif bucket == BucketLabel.STORED_LIQUID:
            # Implicit in the residual — do not double-count.
            pass
        else:
            consumed_cents += amt_cents

        transfer_flows.append({
            "transaction_id": r["id"],
            "posting_date": r["posting_date"][:10],
            "amount_cents": amt_cents,
            "peer_account_id": r["peer_account_id"],
            "peer_account_type": peer,
            "brokerage_buy_matched": brokerage_matched,
            "bucket": bucket.value,
        })

    # 5. Employer-match bypass pseudo-flows from the income_sources registry.
    #    These have no cash leg — they add to both inflow and illiquid totals.
    #    Monthly amount is read from match_rule_json's optional
    #    `monthly_amount_cents` field; multiplied by the number of months
    #    in the window. Missing / zero → no pseudo-flow.
    bypass_flows = _compute_bypass_pseudo_flows(
        conn, contrib_start=contrib_start, contrib_end=contrib_end, owner_id=owner_id,
    )
    for bf in bypass_flows:
        illiquid_cents += bf["amount_cents"]

    # 6. Phase 14 Phase C — reinvested-dividend two-leg flows.
    #    A dividend transaction (category 'Investment Income') paired with a
    #    same-account same-ticker positions_ledger buy/reinvest row within
    #    2 calendar days and matching amount (±$1) becomes an illiquid flow
    #    equal to the dividend amount. The cash never sits as liquid.
    reinvestment_flows = _compute_reinvestment_flows(
        conn,
        date_filter=date_filter,
        date_params=date_params,
        acct_filter=acct_filter,
        acct_params=acct_params,
    )
    for rf in reinvestment_flows:
        illiquid_cents += rf["amount_cents"]

    # ── STORED_LIQUID as residual + invariant check ─────────────────────
    #
    # total_inflow = income-side flows.
    # Phase A: income_from_txns + matched gross-minus-net delta.
    # Phase B: + bypass pseudoflows.
    income_cents = int(round(sum(c["total"] for c in income_cats) * 100))
    bypass_cents = sum(bf["amount_cents"] for bf in bypass_flows)
    total_inflow_cents = income_cents + matched_gross_minus_net_cents + bypass_cents

    # STORED_LIQUID absorbs the residual so the Phase B invariant holds by
    # construction: cash that arrived but wasn't consumed or routed to an
    # illiquid destination sits in checking / HYSA / brokerage cash. A
    # negative residual means consumption outran inflow — the user spent
    # from prior savings. We still record that as the liquid bucket's
    # total (negative), and the magnitude shows up as invariant "drift"
    # against the explicit-sum fallback that prior Phase B drafts used.
    liquid_residual = total_inflow_cents - consumed_cents - illiquid_cents
    liquid_cents = liquid_residual  # overrides the explicit accumulator

    bucket_sum = consumed_cents + liquid_cents + illiquid_cents
    drift_cents = bucket_sum - total_inflow_cents

    # Under the residual model drift should always be 0 — the identity is
    # mathematical. Kept the log-warning for belt-and-suspenders: if a
    # future refactor reintroduces explicit liquid accumulation without
    # updating the identity, this fires loud.
    if abs(drift_cents) > _BUCKET_INVARIANT_TOLERANCE_CENTS:
        log.warning(
            "Phase B bucket invariant drift: buckets sum to %d cents, "
            "total_inflow=%d cents, drift=%+d cents (tolerance ±%d). "
            "Window=%s..%s owner=%s",
            bucket_sum, total_inflow_cents, drift_cents,
            _BUCKET_INVARIANT_TOLERANCE_CENTS,
            contrib_start, contrib_end, owner_id,
        )

    return {
        "consumed_cents": consumed_cents,
        "liquid_cents": liquid_cents,
        "illiquid_cents": illiquid_cents,
        "total_inflow_cents": total_inflow_cents,
        "drift_cents": drift_cents,
        "mortgage_splits": mortgage_splits,
        "transfer_flows": transfer_flows,
        "bypass_flows": bypass_flows,
        "reinvestment_flows": reinvestment_flows,
    }


def _classify_transfer(
    peer_type: str,
    brokerage_buy_matched: bool,
) -> BucketLabel:
    """Thin wrapper around ``dal.flow_classification.classify`` with
    is_transfer=True pre-set — keeps the caller site tidy."""
    from dal.flow_classification import classify
    return classify(
        category=None,
        account_type=None,
        transfer_peer_account_type=peer_type,
        brokerage_buy_matched=brokerage_buy_matched,
        is_transfer=True,
    )


def _compute_reinvestment_flows(
    conn: sqlite3.Connection,
    *,
    date_filter: str,
    date_params: list,
    acct_filter: str,
    acct_params: list,
    window_days: int = 2,
    amount_tolerance_cents: int = 100,
) -> list[dict]:
    """Detect reinvested dividends in the window.

    A reinvested dividend pairs a cash-side dividend transaction
    (``category = 'Investment Income'``, ``signed_amount > 0``) with a
    positions_ledger row whose ``transaction_type IN ('REINVESTMENT', 'BUY')``
    and ``share_delta > 0``, on the **same account**, **same ticker**
    (``transactions.merchant == positions_ledger.ticker``), within
    ``window_days`` calendar days, and with amounts agreeing to within
    ``amount_tolerance_cents``.

    Returns a list of dicts — one per matched pair — for the caller to
    add to ``illiquid_cents`` and for the frontend to draw as a two-leg
    flow (dividend income → account → STORED_ILLIQUID)::

        [
            {
                "transaction_id":  str,   # the dividend cash transaction
                "ledger_id":       int,   # the positions_ledger reinvest row
                "account_id":      str,
                "posting_date":    "YYYY-MM-DD",
                "ticker":          str,
                "amount_cents":    int,   # dividend amount (the flow size)
                "bucket":          "STORED_ILLIQUID",
            },
            ...
        ]

    Matching is best-effort: when the same dividend could match multiple
    ledger rows (e.g. a REINVESTMENT and a near-same-day BUY), the first
    match wins via SQL ORDER BY ledger timestamp. Unmatched dividends stay
    on the income side only and accumulate as residual liquid, which is
    the correct semantic ("dividend cash that wasn't reinvested sits in
    brokerage cash").
    """
    # Pair the dividend tx to its reinvestment ledger row in one pass. The
    # join has to run on the cash tx's rowid since `id` is TEXT in this
    # schema; date math uses sqlite's calendar-day `+N days` modifier.
    amt_acct_clause = acct_filter.replace("account_id", "t.account_id") if acct_filter else ""
    t_date_filter = date_filter.replace("posting_date", "t.posting_date") if date_filter else ""

    rows = conn.execute(
        f"""
        SELECT
            t.id          AS transaction_id,
            t.account_id  AS account_id,
            t.posting_date AS posting_date,
            pl.ticker     AS ticker,
            CAST(ROUND(ABS(t.signed_amount) * 100) AS INTEGER) AS amount_cents,
            pl.id         AS ledger_id,
            pl.timestamp  AS ledger_ts,
            pl.cost_basis_dec AS ledger_cost
        FROM transactions t
        JOIN positions_ledger pl
          ON pl.account_id = t.account_id
         AND UPPER(t.description) LIKE UPPER(pl.ticker) || ' %'
         AND pl.share_delta > 0
         AND pl.transaction_type IN ('REINVESTMENT', 'BUY')
         AND date(pl.timestamp) BETWEEN date(t.posting_date, ?)
                                   AND date(t.posting_date, ?)
         AND ABS(
               CAST(ROUND(CAST(COALESCE(pl.cost_basis_dec, '0') AS REAL) * 100) AS INTEGER)
             - CAST(ROUND(ABS(t.signed_amount) * 100) AS INTEGER)
             ) <= ?
        WHERE t.status = 'posted'
          AND t.signed_amount > 0
          AND t.transfer_tag IS NULL
          AND t.category = 'Investment Income'
          AND t.description IS NOT NULL
          {t_date_filter}
          {amt_acct_clause}
        ORDER BY t.posting_date, pl.timestamp
        """,
        [
            f"-{int(window_days)} days",
            f"+{int(window_days)} days",
            int(amount_tolerance_cents),
        ]
        + date_params
        + acct_params,
    ).fetchall()

    # Dedup: each dividend transaction matches at most once; prefer REINVEST
    # rows over BUY rows when both match. Since SQL ordering by timestamp
    # keeps the earliest match, a first-wins set on transaction_id is
    # sufficient for Phase C scale (five dividend-paying tickers).
    seen_tx: set[str] = set()
    out: list[dict] = []
    for r in rows:
        tx_id = r["transaction_id"]
        if tx_id in seen_tx:
            continue
        seen_tx.add(tx_id)
        out.append({
            "transaction_id": tx_id,
            "ledger_id": int(r["ledger_id"]),
            "account_id": r["account_id"],
            "posting_date": (r["posting_date"] or "")[:10],
            "ticker": r["ticker"],
            "amount_cents": int(r["amount_cents"] or 0),
            "bucket": BucketLabel.STORED_ILLIQUID.value,
        })
    return out


def _compute_bypass_pseudo_flows(
    conn: sqlite3.Connection,
    *,
    contrib_start: str,
    contrib_end: str,
    owner_id: str | None,
) -> list[dict]:
    """Emit pseudo-flows for active income_sources with ``bypass_cash_routing=1``.

    Each source's ``match_rule_json`` may include an optional
    ``monthly_amount_cents`` integer. The pseudo-flow amount for the
    window is ``monthly_amount_cents * months_in_window``. Sources without
    a ``monthly_amount_cents`` emit nothing — the registry is informational
    only in that case, a future parser will compute the real amount.

    The list shape::

        [
            {
                "source_id":      str,
                "display_label":  str,
                "owner_id":       str,
                "tax_treatment":  str,
                "amount_cents":   int,
                "monthly_amount_cents": int,
                "months": int,
                "bucket":         "STORED_ILLIQUID",
            },
            ...
        ]
    """
    # How many months overlap the window? contrib_* are YYYY-MM strings.
    def _em_to_months(em: str) -> int:
        try:
            y, m = em.split("-")
            return int(y) * 12 + int(m)
        except Exception:
            return 0

    start_months = _em_to_months(contrib_start)
    end_months = _em_to_months(contrib_end)
    month_count = max(1, end_months - start_months + 1) if start_months and end_months else 1

    if owner_id:
        sources = income_sources_dal.list_for_owner(
            conn, owner_id, include_inactive=False
        )
    else:
        sources = income_sources_dal.list_all(conn, include_inactive=False)

    out: list[dict] = []
    for s in sources:
        if not s.get("bypass_cash_routing"):
            continue
        try:
            import json
            rule = json.loads(s["match_rule_json"])
        except (TypeError, ValueError):
            continue

        monthly = int(rule.get("monthly_amount_cents") or 0)
        if monthly <= 0:
            continue

        out.append({
            "source_id": s["id"],
            "display_label": s["display_label"],
            "owner_id": s["owner_id"],
            "tax_treatment": s["tax_treatment"],
            "monthly_amount_cents": monthly,
            "months": month_count,
            "amount_cents": monthly * month_count,
            "bucket": BucketLabel.STORED_ILLIQUID.value,
        })
    return out


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
    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)

    excl_ph, excl = get_spend_exclusion_clause()

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
    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)

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
    spend_excl_ph, spend_excl = get_spend_exclusion_clause()

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
    
    excl_ph, excl = get_spend_exclusion_clause()

    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)

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


# ── Phase 14 Phase D — accountability scorecard ───────────────────────────────


def _to_cents(value) -> int:
    """Convert a float dollar value (or None) to integer cents, rounded."""
    if value is None:
        return 0
    return int(round(float(value) * 100))


def _net_worth_at_date(
    conn: sqlite3.Connection,
    as_of: str,
    owner_id: str | None,
) -> dict:
    """Point-in-time net-worth snapshot as of ``as_of`` (YYYY-MM-DD).

    For each account / property / vehicle, picks the most recent snapshot
    with timestamp ``<= as_of``. Liabilities (credit_card / loan / bnpl /
    mortgage) are stored with negative signs in ``balance_snapshots``, so
    summing them directly gives the net-worth contribution.

    Returns integer cents keyed by component::

        {
          "banking_cents":      int,  # checking + savings (assets)
          "investment_cents":   int,  # sum of portfolio_snapshots totals
          "real_estate_cents":  int,  # most-recent per-property valuations
          "vehicle_cents":      int,  # most-recent per-vehicle valuations
          "liabilities_cents":  int,  # negative — already signed
          "net_worth_cents":    int,
        }

    Owner scoping: when ``owner_id`` is provided and the owner owns zero
    accounts, every component returns ``0``. The caller should treat this
    as a valid empty-state rather than a division-by-zero.
    """
    from dal.owners import resolve_account_ids_for_view

    # Resolve owner → account filter ONCE; short-circuit the zero-accounts
    # case to an empty snapshot (matches get_net_worth_history behaviour).
    acct_ids: list[str] | None = None
    if owner_id:
        resolved = resolve_account_ids_for_view(conn, owner_id)
        if resolved is not None:
            if not resolved:
                return {
                    "banking_cents": 0,
                    "investment_cents": 0,
                    "real_estate_cents": 0,
                    "vehicle_cents": 0,
                    "liabilities_cents": 0,
                    "net_worth_cents": 0,
                }
            acct_ids = list(resolved)

    acct_in = ""
    acct_params: list = []
    if acct_ids is not None:
        ph = ",".join("?" for _ in acct_ids)
        acct_in = f"AND a.id IN ({ph})"
        acct_params = list(acct_ids)

    # Banking (checking + savings) and liabilities (negative balances)
    bank_row = conn.execute(
        f"""
        WITH latest_bal AS (
            SELECT a.id, a.type, a.is_active,
                   (SELECT bs.balance
                      FROM balance_snapshots bs
                     WHERE bs.account_id = a.id
                       AND date(bs.as_of) <= date(?)
                     ORDER BY bs.as_of DESC
                     LIMIT 1) AS balance
              FROM accounts a
             WHERE 1=1 {acct_in}
        )
        SELECT
          SUM(CASE WHEN type IN ('checking','savings') THEN balance ELSE 0 END) AS banking,
          SUM(CASE WHEN type IN ('credit_card','loan','bnpl','mortgage')
                    AND is_active = 1 THEN balance ELSE 0 END) AS liabilities
          FROM latest_bal
         WHERE balance IS NOT NULL
        """,
        [as_of] + acct_params,
    ).fetchone()
    banking = (bank_row["banking"] if bank_row else 0) or 0
    liabilities = (bank_row["liabilities"] if bank_row else 0) or 0

    # Investment value: latest portfolio_snapshots per investment/retirement
    # account on or before as_of.
    port_row = conn.execute(
        f"""
        WITH latest_port AS (
            SELECT a.id,
                   (SELECT ps.total_account_value
                      FROM portfolio_snapshots ps
                     WHERE ps.account_id = a.id
                       AND date(ps.timestamp) <= date(?)
                     ORDER BY ps.timestamp DESC
                     LIMIT 1) AS total
              FROM accounts a
             WHERE a.type IN ('investment','retirement')
               {acct_in}
        )
        SELECT SUM(total) AS portfolio
          FROM latest_port
         WHERE total IS NOT NULL
        """,
        [as_of] + acct_params,
    ).fetchone()
    investment = (port_row["portfolio"] if port_row else 0) or 0

    # Real estate: latest per-property valuation on or before as_of.
    # Owner-scope via real_estate.owner_id (added v22).
    re_sql = """
        SELECT name, MAX(as_of) AS latest_as_of
          FROM real_estate
         WHERE name NOT LIKE '%[%'
           AND date(as_of) <= date(?)
    """
    re_params: list = [as_of]
    if owner_id:
        re_sql += " AND LOWER(owner_id) = LOWER(?)"
        re_params.append(owner_id)
    re_sql += " GROUP BY name"

    re_total = 0.0
    for row in conn.execute(re_sql, re_params).fetchall():
        val_row = conn.execute(
            """
            SELECT estimated_value FROM real_estate
             WHERE name = ? AND as_of = ?
             ORDER BY rowid DESC
             LIMIT 1
            """,
            (row["name"], row["latest_as_of"]),
        ).fetchone()
        if val_row and val_row["estimated_value"] is not None:
            re_total += float(val_row["estimated_value"])

    # Vehicles: latest per-vehicle valuation on or before as_of.
    # Owner-scope via vehicle_assets.owner_id (added v22).
    veh_total = 0.0
    try:
        veh_sql = """
            SELECT vv.vehicle_id AS name, MAX(vv.valuation_date) AS latest_as_of
              FROM vehicle_valuations vv
        """
        veh_params: list = []
        if owner_id:
            veh_sql += """
                JOIN vehicle_assets va ON va.id = vv.vehicle_id
                WHERE date(vv.valuation_date) <= date(?)
                  AND LOWER(va.owner_id) = LOWER(?)
            """
            veh_params.extend([as_of, owner_id])
        else:
            veh_sql += " WHERE date(vv.valuation_date) <= date(?)"
            veh_params.append(as_of)
        veh_sql += " GROUP BY vv.vehicle_id"

        for row in conn.execute(veh_sql, veh_params).fetchall():
            val_row = conn.execute(
                """
                SELECT estimated_value FROM vehicle_valuations
                 WHERE vehicle_id = ? AND valuation_date = ?
                 ORDER BY id DESC LIMIT 1
                """,
                (row["name"], row["latest_as_of"]),
            ).fetchone()
            if val_row and val_row["estimated_value"] is not None:
                veh_total += float(val_row["estimated_value"])
    except sqlite3.OperationalError:
        # Vehicle tables absent on pre-v18 databases.
        pass

    banking_c = _to_cents(banking)
    investment_c = _to_cents(investment)
    re_c = _to_cents(re_total)
    veh_c = _to_cents(veh_total)
    liab_c = _to_cents(liabilities)

    return {
        "banking_cents": banking_c,
        "investment_cents": investment_c,
        "real_estate_cents": re_c,
        "vehicle_cents": veh_c,
        "liabilities_cents": liab_c,
        "net_worth_cents": banking_c + investment_c + re_c + veh_c + liab_c,
    }


def _user_contributions_in_window(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    owner_id: str | None,
) -> int:
    """Sum of cents the user transferred into investment accounts in the
    window, via `v_investment_contributions` (Phase C).

    `classification = 'user_contribution'` filters to rows whose cash-side
    transfer was reconciled; intra-account credits (dividend reinvestments,
    employer match) are excluded because they were already counted in
    dollars_in via the income side of the Sankey.
    """
    acct_filter, acct_params = build_account_filter(conn, owner_id, None)
    row = conn.execute(
        f"""
        SELECT SUM(ABS(matched_tx_signed_amount)) AS total_dollars
          FROM v_investment_contributions
         WHERE classification = 'user_contribution'
           AND date(timestamp) >= date(?)
           AND date(timestamp) <= date(?)
           {acct_filter}
        """,
        [start_date, end_date] + acct_params,
    ).fetchone()
    return _to_cents(row["total_dollars"] if row else 0)


def _home_improvement_capex_in_window(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    owner_id: str | None,
) -> int:
    """Sum of cents spent on 'Home Improvement' category transactions in
    the window. Subtracted from the real-estate valuation delta so that
    term reflects PURE market appreciation (not capex-driven bumps).
    """
    acct_filter, acct_params = build_account_filter(conn, owner_id, None)
    row = conn.execute(
        f"""
        SELECT SUM(-signed_amount) AS capex_dollars
          FROM transactions
         WHERE status = 'posted'
           AND signed_amount < 0
           AND transfer_tag IS NULL
           AND category = 'Home Improvement'
           AND date(posting_date) >= date(?)
           AND date(posting_date) <= date(?)
           {acct_filter}
        """,
        [start_date, end_date] + acct_params,
    ).fetchone()
    return _to_cents(row["capex_dollars"] if row else 0)


def get_accountability(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    owner_id: str | None = None,
) -> dict:
    """Phase 14 Phase D — accountability scorecard.

    Reconciles the Phase A–C Sankey flows and independently-computed
    valuation deltas against ``get_net_worth_history`` over the window
    ``[start_date, end_date]``. Answers: "what % of the net-worth change
    have we accounted for?"

    Identity::

        Δ NetWorth = (Dollars in)
                   − (Dollars spent)
                   ± (Market value Δ on owned positions)
                   ± (Real-estate valuation Δ, ex-capex)
                   ± (Vehicle valuation Δ)
                   + unexplained

    The "unexplained" residual is the product of the scorecard: named
    drift sources (see ``dal.accountability_drift``) are attached so the
    user can click-to-fix each contributor.

    Returns integer cents for every monetary field plus a float
    ``accounted_for_pct`` in ``[0.0, 1.0]``. An empty-state owner (owns
    zero accounts) gets ``net_worth_delta_cents=0`` and
    ``accounted_for_pct=1.0`` — there's nothing to account for.
    """
    # ── Step 1: net-worth snapshots bookending the window ──
    nw_start = _net_worth_at_date(conn, start_date, owner_id)
    nw_end = _net_worth_at_date(conn, end_date, owner_id)

    nw_start_c = nw_start["net_worth_cents"]
    nw_end_c = nw_end["net_worth_cents"]
    nw_delta_c = nw_end_c - nw_start_c

    # ── Step 2: cash flow terms from the Phase 14 bucket totals ──
    # Reuse get_flow_data so income_sources/bypass/reinvestment handling
    # stays consistent with the Sankey. Phase C: total_inflow_cents already
    # includes dividends + interest as income.
    flow = get_flow_data(
        conn,
        start_date=start_date,
        end_date=end_date,
        owner_id=owner_id,
    )
    dollars_in_c = int(flow.get("total_inflow_cents") or 0)
    dollars_spent_c = int(flow.get("bucket_totals_cents", {}).get("CONSUMED") or 0)

    # ── Step 3: valuation-delta terms (market / RE / vehicle) ──
    user_contrib_c = _user_contributions_in_window(
        conn, start_date, end_date, owner_id
    )
    # Market-value delta on already-owned positions = change in investment
    # account values minus user contributions (already counted in dollars_in
    # via Phase C income). What remains is pure market movement.
    market_value_delta_c = (
        nw_end["investment_cents"]
        - nw_start["investment_cents"]
        - user_contrib_c
    )

    # Real-estate delta: valuation change minus capex on the home. Capex
    # is already CONSUMED (it left the bank), so subtracting it here keeps
    # the identity balanced and isolates PURE market appreciation for the
    # "valuation stale" drift detector.
    capex_c = _home_improvement_capex_in_window(
        conn, start_date, end_date, owner_id
    )
    real_estate_delta_c = (
        nw_end["real_estate_cents"]
        - nw_start["real_estate_cents"]
        - capex_c
    )

    vehicle_delta_c = nw_end["vehicle_cents"] - nw_start["vehicle_cents"]

    # ── Step 4: solve for unexplained ──
    accounted_c = (
        dollars_in_c
        - dollars_spent_c
        + market_value_delta_c
        + real_estate_delta_c
        + vehicle_delta_c
    )
    unexplained_c = nw_delta_c - accounted_c

    # ── Step 5: percentage accounted for ──
    if nw_delta_c == 0:
        # Empty window / no NW change → vacuously 100% accounted for.
        accounted_pct = 1.0
    else:
        accounted_pct = max(
            0.0,
            1.0 - abs(unexplained_c) / abs(nw_delta_c),
        )

    # ── Step 6: drift sources (named contributors to unexplained) ──
    # Lazy import to avoid a circular dependency (accountability_drift
    # pulls from reports for helpers).
    from dal.accountability_drift import detect_drift_sources
    drift_sources = detect_drift_sources(
        conn,
        start_date=start_date,
        end_date=end_date,
        owner_id=owner_id,
    )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "net_worth_start_cents": nw_start_c,
        "net_worth_end_cents": nw_end_c,
        "net_worth_delta_cents": nw_delta_c,
        "identity_terms": {
            "dollars_in_cents": dollars_in_c,
            "dollars_spent_cents": dollars_spent_c,
            "market_value_delta_cents": market_value_delta_c,
            "real_estate_delta_cents": real_estate_delta_c,
            "vehicle_delta_cents": vehicle_delta_c,
        },
        "unexplained_cents": unexplained_c,
        "accounted_for_pct": round(accounted_pct, 4),
        "drift_sources": drift_sources,
    }

