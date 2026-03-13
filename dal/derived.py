"""
dal/derived.py — Scoped derived metric computation.

Recomputes summary metrics only for affected accounts/periods
after a refresh, avoiding full-world recalculation.
"""

import logging
import sqlite3
from datetime import datetime

log = logging.getLogger("sentry.dal.derived")

from dal.reports import _EXCLUDED_FROM_SPEND, _INCOME_CATEGORIES


def recompute_account_metrics(conn: sqlite3.Connection, account_id: str) -> None:
    """Recompute derived metrics scoped to a single account.

    Computes:
      - Total balance (latest snapshot)
      - Monthly spending (current + previous month)
      - Monthly income (current + previous month)
      - Transaction count
    """
    now = datetime.utcnow()
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
        row = conn.execute(
            """
            SELECT COALESCE(SUM(-signed_amount), 0) as total
            FROM transactions
            WHERE account_id = ? AND status = 'posted'
              AND posting_date >= ? AND posting_date < ?
              AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
              AND transfer_tag IS NULL
        """,
            (account_id, month_start, month_end),
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
        row = conn.execute(
            """
            SELECT COALESCE(SUM(signed_amount), 0) as total
            FROM transactions
            WHERE account_id = ? AND status = 'posted'
              AND posting_date >= ? AND posting_date < ?
              AND COALESCE(category, 'Other Income') IN ({inc_placeholders})
              AND transfer_tag IS NULL
        """,
            (account_id, month_start, month_end),
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
    recompute_interest_earned(conn)

    # For Acorns: backfill daily portfolio snapshots using the latest share
    # counts and live market prices.
    if institution_id == "acorns":
        from dal.investments import compute_acorns_portfolio_snapshots
        compute_acorns_portfolio_snapshots(conn, days=90)

    log.info(
        "Recomputed derived metrics for %s (%d accounts)", institution_id, len(accounts)
    )
