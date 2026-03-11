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

# Categories excluded from spending reports (not real expenditures)
_INCOME_CATEGORIES = {
    "Paychecks/Salary",
    "Rental Income",
    "Deposits",
    "Interest",
    "Investment Income",
    "Retirement Income",
    "Tax Refund",
}

_EXCLUDED_FROM_SPEND = {
    "Transfers",
    "Credit Card Payments",
    "Refunds/Adjustments",
}


# ── Spending by Category ──────────────────────────────────────────────────────


def get_spending_by_category(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    account_ids: Optional[list[str]] = None,
    exclude_transfers: bool = True,
) -> list[dict]:
    """
    Spending breakdown by category for a date range.

    Returns a list sorted by total_spent descending:
      {category, total_spent, transaction_count, avg_transaction, pct_of_total}
    """
    excl = list(_EXCLUDED_FROM_SPEND) if exclude_transfers else []
    excl_placeholders = ", ".join("?" for _ in excl)

    params: list = [start_date, end_date] + excl

    acct_filter = ""
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        acct_filter = f" AND account_id IN ({placeholders})"
        params.extend(account_ids)

    excl_clause = f"AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})" if excl else ""

    rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Uncategorized') as category,
               SUM(amount) as total_spent,
               COUNT(*) as transaction_count,
               AVG(amount) as avg_transaction
        FROM transactions
        WHERE status = 'posted'
          AND direction = 'Debit'
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
) -> list[dict]:
    """
    Monthly cash flow: income vs. spending vs. net, for the last N months.

    Returns a list (oldest first) of:
      {month, income, spending, net, savings_rate}
    """
    excl = list(_EXCLUDED_FROM_SPEND | {"Deposits", "Tax Refund"})
    excl_placeholders = ", ".join("?" for _ in excl)
    params_base = excl + excl

    acct_filter = ""
    acct_params: list = []
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        acct_filter = f" AND account_id IN ({placeholders})"
        acct_params = account_ids

    rows = conn.execute(
        f"""
        SELECT
            strftime('%Y-%m', posting_date) as month,
            SUM(CASE WHEN direction = 'Credit'
                          AND transfer_tag IS NULL
                          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
                     THEN signed_amount ELSE 0 END) as income,
            SUM(CASE WHEN direction = 'Debit'
                          AND transfer_tag IS NULL
                          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
                     THEN amount ELSE 0 END) as spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND posting_date >= date('now', '-{months} months')
          {acct_filter}
        GROUP BY month
        ORDER BY month ASC
        """,
        params_base + acct_params,
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
) -> list[dict]:
    """
    Monthly net worth snapshots for the last N months, reconstructed from
    balance_snapshots + portfolio_snapshots + real_estate table.

    Returns oldest-first list of:
      {month, assets, liabilities, net_worth}
    """
    # Build monthly asset snapshots from balance_snapshots (banking accounts)
    banking_rows = conn.execute(
        f"""
        SELECT strftime('%Y-%m', bs.as_of) as month,
               SUM(CASE WHEN a.type IN ('checking', 'savings') THEN bs.balance ELSE 0 END) as banking,
               SUM(CASE WHEN a.type IN ('credit_card', 'loan', 'bnpl') AND a.is_active = 1
                        THEN ABS(bs.balance) ELSE 0 END) as liabilities
        FROM balance_snapshots bs
        JOIN accounts a ON a.id = bs.account_id
        WHERE bs.as_of >= date('now', '-{months} months')
          AND bs.id = (
              SELECT id FROM balance_snapshots b2
              WHERE b2.account_id = bs.account_id
                AND strftime('%Y-%m', b2.as_of) = strftime('%Y-%m', bs.as_of)
              ORDER BY b2.as_of DESC LIMIT 1
          )
        GROUP BY month
        ORDER BY month ASC
        """
    ).fetchall()

    # Portfolio monthly values (investment / retirement accounts)
    portfolio_rows = conn.execute(
        f"""
        SELECT strftime('%Y-%m', timestamp) as month,
               SUM(total_account_value) as portfolio
        FROM portfolio_snapshots
        WHERE timestamp >= date('now', '-{months} months')
          AND total_account_value IS NOT NULL
          AND id = (
              SELECT id FROM portfolio_snapshots p2
              WHERE p2.account_id = portfolio_snapshots.account_id
                AND strftime('%Y-%m', p2.timestamp) = strftime('%Y-%m', portfolio_snapshots.timestamp)
              ORDER BY p2.timestamp DESC LIMIT 1
          )
        GROUP BY month
        """
    ).fetchall()

    portfolio_map = {r["month"]: (r["portfolio"] or 0) for r in portfolio_rows}

    # Latest real estate value (static — not time-series yet)
    re_row = conn.execute("""
        SELECT SUM(estimated_value) as total FROM real_estate
        WHERE name NOT LIKE '%[%'
          AND id IN (
              SELECT MAX(id) FROM real_estate
              WHERE name NOT LIKE '%[%'
              GROUP BY name
          )
    """).fetchone()
    re_value = (re_row["total"] or 0) if re_row else 0

    result = []
    for r in banking_rows:
        month = r["month"]
        banking = r["banking"] or 0
        liabilities = r["liabilities"] or 0
        portfolio = portfolio_map.get(month, 0)
        assets = round(banking + portfolio + re_value, 2)
        net_worth = round(assets - liabilities, 2)

        result.append({
            "month": month,
            "banking_assets": round(banking, 2),
            "investment_assets": round(portfolio, 2),
            "real_estate_assets": round(re_value, 2),
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
) -> list[dict]:
    """
    Monthly spending trend for a single category.

    Returns oldest-first list of {month, total_spent, transaction_count}.
    """
    params: list = [category, months]
    acct_filter = ""
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        acct_filter = f" AND account_id IN ({placeholders})"
        params.extend(account_ids)

    rows = conn.execute(
        f"""
        SELECT strftime('%Y-%m', posting_date) as month,
               SUM(amount) as total_spent,
               COUNT(*) as transaction_count
        FROM transactions
        WHERE status = 'posted'
          AND direction = 'Debit'
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
) -> dict:
    """
    High-level summary for a date range: total income, spending, net,
    transaction count, top 3 categories.
    """
    spending = get_spending_by_category(conn, start_date, end_date, account_ids)
    cash_flow = get_cash_flow_report(conn, months=1, account_ids=account_ids)

    total_income = sum(m["income"] for m in cash_flow)
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
