"""
dal/derived.py — Scoped derived metric computation.

Recomputes summary metrics only for affected accounts/periods
after a refresh, avoiding full-world recalculation.
"""

import logging
import sqlite3
from datetime import datetime, timezone

# Attribution-aware month expression (mirrors dal/cash_flow.py)
_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"

log = logging.getLogger("sentry.dal.derived")

from dal.reports import _EXCLUDED_FROM_SPEND, _INCOME_CATEGORIES, get_net_worth_history


def recompute_account_metrics(conn: sqlite3.Connection, account_id: str) -> None:
    """Recompute derived metrics scoped to a single account.

    Computes:
      - Total balance (latest snapshot)
      - Monthly spending (current + previous month)
      - Monthly income (current + previous month)
      - Transaction count
    """
    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")
    prev_month_dt = now.replace(day=1)
    # Simple previous month calc
    if prev_month_dt.month == 1:
        prev_month = f"{prev_month_dt.year - 1}-12"
    else:
        prev_month = f"{prev_month_dt.year}-{prev_month_dt.month - 1:02d}"

    scope = f"account:{account_id}"

    for period in [current_month, prev_month]:
        month_start = f"{period}-01"
        # Compute month end (crude but correct)
        parts = period.split("-")
        year, month = int(parts[0]), int(parts[1])
        if month == 12:
            month_end = f"{year + 1}-01-01"
        else:
            month_end = f"{year}-{month + 1:02d}-01"

        # Spending (sum of negative signed_amount, excluding transfers)
        excl_cats = list(_EXCLUDED_FROM_SPEND | _INCOME_CATEGORIES)
        excl_placeholders = ", ".join("?" for _ in excl_cats)

        row = conn.execute(
            f"""
            SELECT COALESCE(SUM(-signed_amount), 0) as total
            FROM transactions
            WHERE account_id = ? AND status = 'posted'
              AND posting_date >= ? AND posting_date < ?
              AND signed_amount < 0
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
              AND transfer_tag IS NULL
        """,
            (account_id, month_start, month_end) + tuple(excl_cats),
        ).fetchone()
        spending = row["total"] if row else 0

        conn.execute(
            """
            INSERT INTO derived_summaries (scope, metric, period, value,
                                           computed_at)
            VALUES (?, 'monthly_spending', ?, ?, datetime('now'))
            ON CONFLICT(scope, metric, period)
            DO UPDATE SET value = excluded.value,
                          computed_at = excluded.computed_at
        """,
            (scope, period, spending),
        )

        # Income (sum of positive signed_amount, excluding transfers)
        inc_cats = list(_INCOME_CATEGORIES | {"Other Income"})
        inc_placeholders = ", ".join("?" for _ in inc_cats)

        row = conn.execute(
            f"""
            SELECT COALESCE(SUM(signed_amount), 0) as total
            FROM transactions
            WHERE account_id = ? AND status = 'posted'
              AND posting_date >= ? AND posting_date < ?
              AND signed_amount > 0
              AND COALESCE(category, 'Other Income') IN ({inc_placeholders})
              AND transfer_tag IS NULL
        """,
            (account_id, month_start, month_end) + tuple(inc_cats),
        ).fetchone()
        income = row["total"] if row else 0

        conn.execute(
            """
            INSERT INTO derived_summaries (scope, metric, period, value,
                                           computed_at)
            VALUES (?, 'monthly_income', ?, ?, datetime('now'))
            ON CONFLICT(scope, metric, period)
            DO UPDATE SET value = excluded.value,
                          computed_at = excluded.computed_at
        """,
            (scope, period, income),
        )


def recompute_net_worth(conn: sqlite3.Connection) -> float:
    """Recompute net worth from all asset and liability sources.

    Assets:
      - Banking (checking, savings) from balance_snapshots
      - Investment / retirement accounts from portfolio_snapshots
        (preferred) or balance_snapshots (fallback)
      - Real estate from real_estate table
    Liabilities:
      - Credit cards, loans from balance_snapshots
      - BNPL contracts (active only) from balance_snapshots
    """
    # ── 1. Balance snapshots (banking, credit, loans) ────────────────
    rows = conn.execute("""
        SELECT a.id, a.type, a.is_active, bs.balance
        FROM balance_snapshots bs
        JOIN accounts a ON a.id = bs.account_id
        WHERE bs.id = (
            SELECT id FROM balance_snapshots b2
            WHERE b2.account_id = bs.account_id
            ORDER BY b2.as_of DESC LIMIT 1
        )
    """).fetchall()

    banking_asset_types = {"checking", "savings"}
    liability_types = {"credit_card", "loan", "bnpl"}
    investment_types = {"investment", "retirement"}

    assets = 0.0
    liabilities = 0.0
    investment_account_ids = set()

    for r in rows:
        acct_type = r["type"]
        balance = r["balance"] or 0.0

        if acct_type in banking_asset_types:
            assets += balance
        elif acct_type in liability_types:
            # Only include active accounts (filters stale BNPL)
            if r["is_active"]:
                liabilities += balance
        elif acct_type in investment_types:
            investment_account_ids.add(r["id"])

    # ── 2. Investment accounts — prefer portfolio_snapshots ──────────
    for acct_id in investment_account_ids:
        # Try portfolio_snapshots first (has total_account_value)
        ps = conn.execute(
            """
            SELECT total_account_value FROM portfolio_snapshots
            WHERE account_id = ?
            ORDER BY timestamp DESC LIMIT 1
        """,
            (acct_id,),
        ).fetchone()

        if ps and ps["total_account_value"]:
            assets += ps["total_account_value"]
            continue

        # Try investment_holdings (sum of market_value for latest date)
        ih = conn.execute(
            """
            SELECT SUM(market_value) as total FROM investment_holdings
            WHERE account_id = ? AND date = (
                SELECT MAX(date) FROM investment_holdings WHERE account_id = ?
            )
        """,
            (acct_id, acct_id),
        ).fetchone()

        if ih and ih["total"]:
            # Add cash balance if available
            cash = conn.execute(
                """
                SELECT cash_balance FROM portfolio_snapshots
                WHERE account_id = ? ORDER BY timestamp DESC LIMIT 1
            """,
                (acct_id,),
            ).fetchone()
            assets += ih["total"] + (cash["cash_balance"] if cash else 0)
            continue

        # Final fallback: use balance_snapshots
        bs = conn.execute(
            """
            SELECT balance FROM balance_snapshots
            WHERE account_id = ? ORDER BY as_of DESC LIMIT 1
        """,
            (acct_id,),
        ).fetchone()
        if bs:
            assets += bs["balance"]

    # ── 3. Real estate ───────────────────────────────────────────────
    # Get the latest valuation per property, excluding per-source
    # audit records (those have "[source]" in the name).
    re_row = conn.execute("""
        SELECT SUM(estimated_value) as total FROM real_estate
        WHERE name NOT LIKE '%[%'
          AND id IN (
              SELECT MAX(id) FROM real_estate
              WHERE name NOT LIKE '%[%'
              GROUP BY name
          )
    """).fetchone()
    if re_row and re_row["total"]:
        assets += re_row["total"]

    net_worth = assets - liabilities

    conn.execute(
        """
        INSERT INTO derived_summaries (scope, metric, period, value,
                                       computed_at)
        VALUES ('global', 'net_worth', NULL, ?, datetime('now'))
        ON CONFLICT(scope, metric, period)
        DO UPDATE SET value = excluded.value,
                      computed_at = excluded.computed_at
    """,
        (net_worth,),
    )

    log.info(
        "Net worth recomputed: assets=$%.2f - liabilities=$%.2f = $%.2f",
        assets,
        liabilities,
        net_worth,
    )

    return net_worth


def recompute_interest_earned(conn: sqlite3.Connection) -> None:
    """Compute total interest earned from Affirm HYSA.

    Sums all transactions with description 'Interest' for the
    affirm_HYSA account and stores as a derived metric.
    """
    row = conn.execute("""
        SELECT COALESCE(SUM(signed_amount), 0) as total
        FROM transactions
        WHERE account_id = 'affirm_HYSA'
          AND LOWER(description) = 'interest'
          AND status = 'posted'
    """).fetchone()

    total_interest = row["total"] if row else 0

    conn.execute(
        """
        INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
        VALUES ('account:affirm_HYSA', 'interest_earned', NULL, ?, datetime('now'))
        ON CONFLICT(scope, metric, period)
        DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
    """,
        (total_interest,),
    )
    log.info("Affirm HYSA interest earned: $%.2f", total_interest)


def compute_emergency_fund_months(conn: sqlite3.Connection) -> dict:
    """
    Compute emergency fund runway: liquid_balance / avg_monthly_spending.

    Liquid balance = sum of latest balance_snapshots for all active
    checking + savings accounts.

    Avg monthly spending = average of the last 6 complete calendar months
    of non-transfer, non-income spending.
    """
    # ── 1. Liquid Balance ──────────────────────────────────────────────
    rows = conn.execute("""
        SELECT a.id, a.name, bs.balance
        FROM balance_snapshots bs
        JOIN accounts a ON a.id = bs.account_id
        WHERE a.type IN ('checking', 'savings') AND a.is_active = 1
          AND bs.id = (
              SELECT id FROM balance_snapshots b2
              WHERE b2.account_id = bs.account_id
              ORDER BY b2.as_of DESC LIMIT 1
          )
    """).fetchall()

    liquid_balance = 0.0
    liquid_accounts = []
    for r in rows:
        bal = round(r["balance"] or 0.0, 2)
        liquid_balance += bal
        liquid_accounts.append({
            "account_id": r["id"],
            "name": r["name"],
            "balance": bal
        })

    # ── 2. Average Monthly Spending (last 6 complete months) ───────────
    excl_cats = list(_EXCLUDED_FROM_SPEND | _INCOME_CATEGORIES)
    excl_placeholders = ", ".join("?" for _ in excl_cats)

    spend_rows = conn.execute(
        f"""
        SELECT {_EM} as month, SUM(-signed_amount) as total
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount < 0
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
          AND posting_date >= date('now', 'start of month', '-6 months')
          AND posting_date < date('now', 'start of month')
        GROUP BY month
        ORDER BY month DESC
        """,
        excl_cats
    ).fetchall()

    avg_monthly_spending = 0.0
    months_count = len(spend_rows)
    if months_count > 0:
        total_spend = sum(r["total"] or 0.0 for r in spend_rows)
        avg_monthly_spending = total_spend / months_count
    
    avg_monthly_spending = round(avg_monthly_spending, 2)
    liquid_balance = round(liquid_balance, 2)

    # ── 3. Runway Computation ──────────────────────────────────────────
    months_of_runway = None
    if avg_monthly_spending > 0:
        months_of_runway = round(liquid_balance / avg_monthly_spending, 1)

    # Store in derived_summaries
    if months_of_runway is not None:
        conn.execute("""
            INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
            VALUES ('global', 'emergency_fund_months', NULL, ?, datetime('now'))
            ON CONFLICT(scope, metric, period)
            DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
        """, (months_of_runway,))

    return {
        "liquid_balance": liquid_balance,
        "avg_monthly_spending": avg_monthly_spending,
        "months_of_runway": months_of_runway,
        "liquid_accounts": liquid_accounts,
    }


def compute_dti_ratio(conn: sqlite3.Connection, months: int = 12) -> list[dict]:
    """
    Compute monthly DTI ratio for the last N months.
    """
    inc_cats = list(_INCOME_CATEGORIES)
    inc_placeholders = ", ".join("?" for _ in inc_cats)

    debt_cats = ['Mortgage', 'Auto Loan', 'Credit Card Payments']
    debt_placeholders = ", ".join("?" for _ in debt_cats)

    params = inc_cats + debt_cats

    rows = conn.execute(
        f"""
        SELECT 
            {_EM} as month,
            SUM(CASE 
                WHEN t.transfer_tag IS NULL 
                 AND t.signed_amount > 0 
                 AND COALESCE(t.category, 'Other Income') IN ({inc_placeholders})
                THEN t.signed_amount 
                ELSE 0 END) as gross_income,
            SUM(CASE
                WHEN t.transfer_tag IS NULL
                 AND t.signed_amount < 0
                 AND COALESCE(t.category, '') IN ({debt_placeholders})
                THEN ABS(t.signed_amount)
                ELSE 0 END) as debt_payments
        FROM transactions t
        WHERE t.status = 'posted'
          AND t.posting_date >= date('now', 'start of month', '-{{months}} months')
          AND t.posting_date < date('now', 'start of month')
        GROUP BY month
        ORDER BY month ASC
        """.format(months=months),
        params
    ).fetchall()

    result = []
    latest_month = None
    latest_dti = None

    for r in rows:
        month = r["month"]
        income = round(r["gross_income"] or 0.0, 2)
        debt = round(r["debt_payments"] or 0.0, 2)

        dti = None
        status = None
        if income > 0:
            dti = round((debt / income) * 100, 1)
            if dti <= 28.0:
                status = "healthy"
            elif dti <= 36.0:
                status = "moderate"
            elif dti <= 43.0:
                status = "high"
            else:
                status = "critical"

        result.append({
            "month": month,
            "debt_payments": debt,
            "gross_income": income,
            "dti_ratio": dti,
            "status": status,
        })
        
        latest_month = month
        if dti is not None:
            latest_dti = dti

    # Store each month's DTI so the time series is cached
    for item in result:
        if item["dti_ratio"] is not None:
            conn.execute("""
                INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
                VALUES ('global', 'dti_ratio', ?, ?, datetime('now'))
                ON CONFLICT(scope, metric, period)
                DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
            """, (item["month"], item["dti_ratio"]))

    return result


def compute_interest_cost(conn: sqlite3.Connection) -> dict:
    """
    Aggregate total interest paid across all liabilities.

    Sources (checked in priority order per account):
    1. loan_details field: 'ytd_interest' or 'Interest Paid YTD'
       (latest as_of for the current year)
    2. Transaction-based: sum of interest-charge transactions
       for credit cards (category contains 'Interest' or 'Fee')

    Returns:
    {
        "ytd_total": float,
        "by_account": list,
        "monthly_breakdown": list,
        "interest_earned": float,
        "net_interest": float,
    }
    """
    current_year = datetime.now(timezone.utc).strftime("%Y")
    
    # 1. Base list of all active liability accounts
    liability_accounts = conn.execute("""
        SELECT id, name, type 
        FROM accounts 
        WHERE is_active = 1 AND type IN ('credit_card', 'loan', 'bnpl')
    """).fetchall()

    by_account = []
    ytd_total = 0.0

    for acct in liability_accounts:
        acct_id = acct["id"]
        
        # Try loan_details first
        row_ld = conn.execute("""
            SELECT field_value 
            FROM loan_details 
            WHERE account_id = ? 
              AND (LOWER(field_name) LIKE '%interest%ytd%' 
                   OR LOWER(field_name) IN ('ytd_interest', 'interest paid ytd', 'ytd interest paid'))
              AND strftime('%Y', as_of) = ?
            ORDER BY as_of DESC 
            LIMIT 1
        """, (acct_id, current_year)).fetchone()

        ytd_val = 0.0
        source = None

        if row_ld and row_ld["field_value"]:
            val_str = str(row_ld["field_value"]).replace('$', '').replace(',', '').replace('%', '').strip()
            try:
                ytd_val = float(val_str)
                source = "loan_details"
            except ValueError:
                pass

        # Fallback to transactions
        if source is None:
            row_tx = conn.execute("""
                SELECT SUM(ABS(signed_amount)) as total
                FROM transactions
                WHERE account_id = ? 
                  AND status = 'posted'
                  AND (LOWER(category) LIKE '%interest%' OR LOWER(category) LIKE '%finance charge%')
                  AND strftime('%Y', posting_date) = ?
            """, (acct_id, current_year)).fetchone()

            if row_tx and row_tx["total"] is not None:
                ytd_val = float(row_tx["total"])
                source = "transactions"
            else:
                source = "transactions"

        ytd_val = round(ytd_val, 2)
        ytd_total += ytd_val
        
        by_account.append({
            "account_id": acct_id,
            "account_name": acct["name"],
            "account_type": acct["type"],
            "ytd_interest": ytd_val,
            "source": source
        })

    # Monthly breakdown across all liability accounts
    mb_rows = conn.execute("""
        SELECT strftime('%Y-%m', t.posting_date) as month, SUM(ABS(t.signed_amount)) as total_interest
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE t.status = 'posted'
          AND a.type IN ('credit_card', 'loan', 'bnpl')
          AND (LOWER(t.category) LIKE '%interest%' OR LOWER(t.category) LIKE '%finance charge%')
          AND strftime('%Y', t.posting_date) = ?
        GROUP BY month
        ORDER BY month ASC
    """, (current_year,)).fetchall()

    monthly_breakdown = [
        {"month": r["month"], "total_interest": round(r["total_interest"] or 0.0, 2)}
        for r in mb_rows
    ]

    # Interest earned (YTD)
    earned_row = conn.execute("""
        SELECT COALESCE(SUM(signed_amount), 0) as total
        FROM transactions
        WHERE (account_id = 'affirm_HYSA' OR LOWER(category) LIKE '%interest%' OR LOWER(description) = 'interest')
          AND signed_amount > 0
          AND status = 'posted'
          AND strftime('%Y', posting_date) = ?
    """, (current_year,)).fetchone()
    
    interest_earned = round(earned_row["total"] or 0.0, 2)
    net_interest = round(interest_earned - ytd_total, 2)

    # Store in derived_summaries
    conn.execute("""
        INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
        VALUES ('global', 'ytd_interest_cost', ?, ?, datetime('now'))
        ON CONFLICT(scope, metric, period)
        DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
    """, (current_year, ytd_total))

    return {
        "ytd_total": round(ytd_total, 2),
        "by_account": by_account,
        "monthly_breakdown": monthly_breakdown,
        "interest_earned": interest_earned,
        "net_interest": net_interest,
    }


def compute_net_worth_velocity(conn: sqlite3.Connection) -> dict:
    """
    Compute rate of net worth change across multiple timeframes.
    """
    history = get_net_worth_history(conn, months=24)
    
    velocity_history = []
    
    for i, month_data in enumerate(history):
        item = {
            "month": month_data["month"],
            "net_worth": month_data["net_worth"],
            "mom_change": None,
            "mom_pct": None,
        }
        if i > 0:
            prev_nw = history[i-1]["net_worth"]
            mom_change = item["net_worth"] - prev_nw
            item["mom_change"] = round(mom_change, 2)
            if prev_nw != 0:
                item["mom_pct"] = round((mom_change / abs(prev_nw)) * 100, 1)
        velocity_history.append(item)

    current_net_worth = 0.0
    mom_change = None
    mom_pct = None
    rolling_3m_change = None
    rolling_3m_avg = None
    rolling_12m_change = None
    rolling_12m_avg = None

    if len(velocity_history) > 0:
        current_net_worth = velocity_history[-1]["net_worth"]
        mom_change = velocity_history[-1]["mom_change"]
        mom_pct = velocity_history[-1]["mom_pct"]

    # Rolling 3m
    if len(velocity_history) >= 4:
        nw_3m_ago = velocity_history[-4]["net_worth"]
        rolling_3m_change = current_net_worth - nw_3m_ago
        rolling_3m_avg = round(rolling_3m_change / 3, 2)
        rolling_3m_change = round(rolling_3m_change, 2)

    # Rolling 12m
    if len(velocity_history) >= 13:
        nw_12m_ago = velocity_history[-13]["net_worth"]
        rolling_12m_change = current_net_worth - nw_12m_ago
        rolling_12m_avg = round(rolling_12m_change / 12, 2)
        rolling_12m_change = round(rolling_12m_change, 2)

    trend = "insufficient_data"
    if rolling_3m_avg is not None:
        if rolling_3m_avg < 0:
            trend = "declining"
        elif rolling_12m_avg is not None:
            if rolling_3m_avg > 0 and rolling_12m_avg > 0:
                lower = rolling_12m_avg * 0.8
                upper = rolling_12m_avg * 1.2
                if rolling_3m_avg > upper:
                    trend = "accelerating"
                elif rolling_3m_avg < lower:
                    trend = "decelerating"
                else:
                    trend = "steady"
            else:
                if rolling_3m_avg > rolling_12m_avg:
                    trend = "accelerating"
                else:
                    trend = "decelerating"

    for metric, value in [
        ('nw_mom_change', mom_change),
        ('nw_rolling_3m_avg', rolling_3m_avg),
        ('nw_rolling_12m_avg', rolling_12m_avg),
    ]:
        if value is not None:
            conn.execute("""
                INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
                VALUES ('global', ?, NULL, ?, datetime('now'))
                ON CONFLICT(scope, metric, period)
                DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
            """, (metric, value))

    return {
        "current_net_worth": round(current_net_worth, 2),
        "mom_change": mom_change,
        "mom_pct": mom_pct,
        "rolling_3m_change": rolling_3m_change,
        "rolling_3m_monthly_avg": rolling_3m_avg,
        "rolling_12m_change": rolling_12m_change,
        "rolling_12m_monthly_avg": rolling_12m_avg,
        "trend": trend,
        "history": velocity_history,
    }


def get_summary_metrics(conn: sqlite3.Connection) -> dict:
    """Get all current derived metrics for the dashboard."""
    rows = conn.execute("""
        SELECT scope, metric, period, value, computed_at
        FROM derived_summaries
        ORDER BY scope, metric, period
    """).fetchall()

    metrics = {}
    for row in rows:
        key = f"{row['scope']}:{row['metric']}"
        if row["period"]:
            key += f":{row['period']}"
        metrics[key] = {
            "value": row["value"],
            "computed_at": row["computed_at"],
        }
    return metrics


def recompute_for_institution(conn: sqlite3.Connection, institution_id: str) -> None:
    """Recompute all derived metrics for accounts of an institution.

    Called after a refresh completes for the institution.
    """
    accounts = conn.execute(
        "SELECT id FROM accounts WHERE institution_id = ?", (institution_id,)
    ).fetchall()

    for acct in accounts:
        recompute_account_metrics(conn, acct["id"])

    recompute_net_worth(conn)
    compute_emergency_fund_months(conn)
    compute_interest_cost(conn)
    compute_net_worth_velocity(conn)
    compute_dti_ratio(conn, months=2)
    recompute_interest_earned(conn)

    # For Acorns: backfill daily portfolio snapshots using the latest share
    # counts and live market prices.
    if institution_id == "acorns":
        from dal.investments import compute_acorns_portfolio_snapshots
        compute_acorns_portfolio_snapshots(conn, days=90)

    log.info(
        "Recomputed derived metrics for %s (%d accounts)", institution_id, len(accounts)
    )
