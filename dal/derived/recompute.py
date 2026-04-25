"""
dal/derived.py — Scoped derived metric computation.

Recomputes summary metrics only for affected accounts/periods
after a refresh, avoiding full-world recalculation.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

# Attribution-aware month expression (mirrors dal/cash_flow.py)
_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"

log = logging.getLogger("sentry.dal.derived")

from dal.accounts_config import get_account_id
from dal.category_classifications import (
    INCOME_CATEGORIES as _INCOME_CATEGORIES,
    get_spend_exclusion_clause,
)
from dal.reports import get_net_worth_history
from dal.derived.metrics import (
    _affirm_hysa_id,
    compute_dti_ratio,
    compute_emergency_fund_months,
    compute_interest_cost,
    compute_net_worth_velocity,
)



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
        excl_placeholders, excl_cats = get_spend_exclusion_clause()

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


def recompute_net_worth(
    conn: sqlite3.Connection,
    owner_id: Optional[str] = None,
) -> float:
    """Recompute net worth from all asset and liability sources.

    Assets:
      - Banking (checking, savings) from balance_snapshots
      - Real estate from real_estate table
      - Vehicles from vehicle_valuations table
    Liabilities:
      - Credit cards, loans from balance_snapshots
      - BNPL contracts (active only) from balance_snapshots

    Investment and retirement accounts are NOT contributing to net worth
    during the P13 investments rebuild.  A future task will reintroduce
    them once the new read path is wired up.

    ``owner_id`` scopes by owner; ``None`` returns the household total.
    Real estate / vehicles attribute via their own owner_id columns;
    balance_snapshots attribute via the joined ``accounts.owner_id``.
    """
    from dal.owners import build_account_filter

    acct_filter, acct_params = build_account_filter(
        conn, owner_id, None, column="a.id"
    )

    # ── 1. Balance snapshots (banking, credit, loans) ────────────────
    rows = conn.execute(f"""
        SELECT a.id, a.type, a.is_active, bs.balance
        FROM balance_snapshots bs
        JOIN accounts a ON a.id = bs.account_id
        WHERE bs.id = (
            SELECT id FROM balance_snapshots b2
            WHERE b2.account_id = bs.account_id
            ORDER BY b2.as_of DESC LIMIT 1
        )
        {acct_filter}
    """, acct_params).fetchall()

    banking_asset_types = {"checking", "savings"}
    liability_types = {"credit_card", "loan", "bnpl", "mortgage"}

    assets = 0.0
    liabilities = 0.0  # signed-negative sum (CC/loan balances are stored negative)

    for r in rows:
        acct_type = r["type"]
        balance = r["balance"] or 0.0

        if acct_type in banking_asset_types:
            assets += balance
        elif acct_type in liability_types:
            # Only include active accounts (filters stale BNPL)
            if r["is_active"]:
                liabilities += balance
        # investment/retirement accounts intentionally skipped during
        # the P13 rebuild — no contribution to net worth.

    # ── 2. Real estate ───────────────────────────────────────────────
    # Get the latest valuation per property, excluding per-source
    # audit records (those have "[source]" in the name).
    if owner_id is None:
        re_row = conn.execute("""
            SELECT SUM(estimated_value) as total FROM real_estate
            WHERE name NOT LIKE '%[%'
              AND id IN (
                  SELECT MAX(id) FROM real_estate
                  WHERE name NOT LIKE '%[%'
                  GROUP BY name
              )
        """).fetchone()
    else:
        re_row = conn.execute("""
            SELECT SUM(estimated_value) as total FROM real_estate
            WHERE name NOT LIKE '%[%'
              AND LOWER(owner_id) = LOWER(?)
              AND id IN (
                  SELECT MAX(id) FROM real_estate
                  WHERE name NOT LIKE '%[%'
                    AND LOWER(owner_id) = LOWER(?)
                  GROUP BY name
              )
        """, (owner_id, owner_id)).fetchone()
    if re_row and re_row["total"]:
        assets += re_row["total"]

    # ── 3. Vehicles (latest valuation per vehicle) ───────────────────
    try:
        if owner_id is None:
            veh_row = conn.execute("""
                SELECT SUM(estimated_value) as total FROM vehicle_valuations vv
                WHERE vv.id = (
                    SELECT MAX(vv2.id) FROM vehicle_valuations vv2
                    WHERE vv2.vehicle_id = vv.vehicle_id
                )
            """).fetchone()
        else:
            veh_row = conn.execute("""
                SELECT SUM(vv.estimated_value) as total
                FROM vehicle_valuations vv
                JOIN vehicle_assets va ON va.id = vv.vehicle_id
                WHERE LOWER(va.owner_id) = LOWER(?)
                  AND vv.id = (
                      SELECT MAX(vv2.id) FROM vehicle_valuations vv2
                      WHERE vv2.vehicle_id = vv.vehicle_id
                  )
            """, (owner_id,)).fetchone()
        if veh_row and veh_row["total"]:
            assets += veh_row["total"]
    except sqlite3.OperationalError:
        # vehicle_valuations table missing — non-fatal
        pass

    # liabilities is a signed-negative sum (CC/loan balances stored negative).
    # Adding it to assets correctly subtracts the debt.
    net_worth = assets + liabilities

    scope = "global" if owner_id is None else f"owner:{owner_id}"
    conn.execute(
        """
        INSERT INTO derived_summaries (scope, metric, period, value,
                                       computed_at)
        VALUES (?, 'net_worth', NULL, ?, datetime('now'))
        ON CONFLICT(scope, metric) WHERE period IS NULL
        DO UPDATE SET value = excluded.value,
                      computed_at = excluded.computed_at
    """,
        (scope, net_worth),
    )

    log.info(
        "Net worth recomputed (%s): assets=$%.2f + liabilities=$%.2f = $%.2f",
        scope, assets, liabilities, net_worth,
    )

    return net_worth


def recompute_interest_earned(
    conn: sqlite3.Connection,
    owner_id: Optional[str] = None,
) -> None:
    """Compute total interest earned from Affirm HYSA.

    Sums all transactions with description 'Interest' for the
    Affirm HYSA account and stores as a derived metric.

    ``owner_id`` scopes the underlying query: only HYSA interest landing
    on accounts owned by ``owner_id`` is counted, and the row is written
    with ``scope=f'owner:{owner_id}'``. ``owner_id is None`` keeps the
    historical ``scope=f'account:{hysa_id}'`` shape.
    """
    from dal.owners import build_account_filter

    hysa_id = _affirm_hysa_id()

    if owner_id is None:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(signed_amount), 0) as total
            FROM transactions
            WHERE account_id = ?
              AND LOWER(description) = 'interest'
              AND status = 'posted'
            """,
            (hysa_id,),
        ).fetchone()
        scope = f"account:{hysa_id}"
    else:
        acct_filter, acct_params = build_account_filter(
            conn, owner_id, None, column="account_id"
        )
        row = conn.execute(
            f"""
            SELECT COALESCE(SUM(signed_amount), 0) as total
            FROM transactions
            WHERE account_id = ?
              AND LOWER(description) = 'interest'
              AND status = 'posted'
              {acct_filter}
            """,
            [hysa_id] + acct_params,
        ).fetchone()
        scope = f"owner:{owner_id}"

    total_interest = row["total"] if row else 0

    conn.execute(
        """
        INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
        VALUES (?, 'interest_earned', NULL, ?, datetime('now'))
        ON CONFLICT(scope, metric) WHERE period IS NULL
        DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
        """,
        (scope, total_interest),
    )
    log.info("HYSA interest earned (%s): $%.2f", scope, total_interest)


def recompute_for_institution(conn: sqlite3.Connection, institution_id: str) -> None:
    """Recompute all derived metrics for accounts of an institution.

    Called after a refresh completes for the institution.
    """
    from dal.owners import get_configured_owners

    accounts = conn.execute(
        "SELECT id FROM accounts WHERE institution_id = ?", (institution_id,)
    ).fetchall()

    for acct in accounts:
        recompute_account_metrics(conn, acct["id"])

    # Household / global aggregates first (scope='global').
    recompute_net_worth(conn)
    compute_emergency_fund_months(conn)
    compute_interest_cost(conn)
    compute_net_worth_velocity(conn)
    compute_dti_ratio(conn, months=2)
    recompute_interest_earned(conn)

    # Per-owner aggregates (scope='owner:<id>'). Same six metrics, same
    # writers — the per-owner branch in each writer narrows the underlying
    # query and writes a separate derived_summaries row.
    for owner in get_configured_owners():
        oid = owner["id"]
        recompute_net_worth(conn, owner_id=oid)
        compute_emergency_fund_months(conn, owner_id=oid)
        compute_interest_cost(conn, owner_id=oid)
        compute_net_worth_velocity(conn, owner_id=oid)
        compute_dti_ratio(conn, months=2, owner_id=oid)
        recompute_interest_earned(conn, owner_id=oid)

    # P13-T03: Acorns portfolio_snapshots are written directly by the
    # connector (delta-logging) and the seeder.  No derived computation
    # is needed — the net worth calculation in reports.py reads from
    # portfolio_snapshots directly.  The investment_link / transfer_tag
    # linkage between bank debits and positions_ledger is handled by
    # the post-commit pipeline in result_writer.py.

    log.info(
        "Recomputed derived metrics for %s (%d accounts)", institution_id, len(accounts)
    )
