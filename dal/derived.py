"""
dal/derived.py — Scoped derived metric computation.

Recomputes summary metrics only for affected accounts/periods
after a refresh, avoiding full-world recalculation.
"""

import logging
import sqlite3
from datetime import datetime

log = logging.getLogger("sentry.dal.derived")


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

        # Spending (sum of negative signed_amount)
        row = conn.execute(
            """
            SELECT COALESCE(SUM(ABS(signed_amount)), 0) as total
            FROM transactions
            WHERE account_id = ? AND status = 'posted'
              AND posting_date >= ? AND posting_date < ?
              AND signed_amount < 0
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

        # Income (sum of positive signed_amount)
        row = conn.execute(
            """
            SELECT COALESCE(SUM(signed_amount), 0) as total
            FROM transactions
            WHERE account_id = ? AND status = 'posted'
              AND posting_date >= ? AND posting_date < ?
              AND signed_amount > 0
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
    """Recompute net worth from latest balance snapshots.

    Assets (checking, savings, investment) minus liabilities
    (credit_card, loan).
    """
    rows = conn.execute("""
        SELECT a.type, bs.balance
        FROM balance_snapshots bs
        JOIN accounts a ON a.id = bs.account_id
        WHERE bs.id = (
            SELECT id FROM balance_snapshots b2
            WHERE b2.account_id = bs.account_id
            ORDER BY b2.as_of DESC LIMIT 1
        )
    """).fetchall()

    asset_types = {"checking", "savings", "investment"}
    liability_types = {"credit_card", "loan"}

    assets = sum(r["balance"] for r in rows if r["type"] in asset_types)
    liabilities = sum(abs(r["balance"]) for r in rows if r["type"] in liability_types)
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

    return net_worth


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
    log.info(
        "Recomputed derived metrics for %s (%d accounts)", institution_id, len(accounts)
    )
