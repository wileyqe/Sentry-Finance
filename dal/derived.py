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


def _affirm_hysa_id() -> str:
    """Affirm HYSA account_id from accounts.yaml; fallback template."""
    return get_account_id("affirm", account_type="savings") or "affirm_XXXX"


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


def compute_emergency_fund_months(
    conn: sqlite3.Connection,
    owner_id: Optional[str] = None,
) -> dict:
    """
    Compute emergency fund runway: liquid_balance / avg_monthly_spending.

    Liquid balance = sum of latest balance_snapshots for all active
    checking + savings accounts.

    Avg monthly spending = average of the last 6 complete calendar months
    of non-transfer, non-income spending.

    If owner_id is provided, restricts both calculations to accounts
    owned by that owner (resolved via dal.owners.build_account_filter).
    """
    # ── Owner scoping: resolve to a SQL fragment ──────────────────────
    # build_account_filter returns ("", []) for no filter, (" AND 1=0", [])
    # for an owner who owns no accounts, and (" AND col IN (...)", ids)
    # otherwise — the short-circuit branch collapses to zero rows at the
    # planner level without a manual if/else around every query.
    from dal.owners import build_account_filter
    acct_filter_a, acct_params_a = build_account_filter(
        conn, owner_id, None, column="a.id"
    )
    acct_filter_tx, acct_params_tx = build_account_filter(
        conn, owner_id, None, column="account_id"
    )

    # ── 1. Liquid Balance ──────────────────────────────────────────────
    rows = conn.execute(
        f"""
        SELECT a.id, a.name, bs.balance
        FROM balance_snapshots bs
        JOIN accounts a ON a.id = bs.account_id
        WHERE a.type IN ('checking', 'savings') AND a.is_active = 1
          {acct_filter_a}
          AND bs.id = (
              SELECT id FROM balance_snapshots b2
              WHERE b2.account_id = bs.account_id
              ORDER BY b2.as_of DESC LIMIT 1
          )
        """,
        acct_params_a,
    ).fetchall()

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
    excl_placeholders, excl_cats = get_spend_exclusion_clause()

    spend_rows = conn.execute(
        f"""
        SELECT {_EM} as month, SUM(-signed_amount) as total
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount < 0
          AND transfer_tag IS NULL
          {acct_filter_tx}
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
          AND posting_date >= date('now', 'start of month', '-6 months')
          AND posting_date < date('now', 'start of month')
        GROUP BY month
        ORDER BY month DESC
        """,
        list(acct_params_tx) + excl_cats,
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

    # Store in derived_summaries (per-owner namespace when scoped).
    if months_of_runway is not None:
        scope = "global" if owner_id is None else f"owner:{owner_id}"
        conn.execute("""
            INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
            VALUES (?, 'emergency_fund_months', NULL, ?, datetime('now'))
            ON CONFLICT(scope, metric) WHERE period IS NULL
            DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
        """, (scope, months_of_runway))

    return {
        "liquid_balance": liquid_balance,
        "avg_monthly_spending": avg_monthly_spending,
        "months_of_runway": months_of_runway,
        "liquid_accounts": liquid_accounts,
    }


def compute_dti_ratio(
    conn: sqlite3.Connection,
    months: int = 12,
    owner_id: str | None = None,
) -> list[dict]:
    """
    Compute monthly DTI ratio for the last N months.

    DTI is the *flow* ratio — monthly debt payments ÷ monthly gross
    income — matching the lender thresholds (28/36/43%). It is NOT a
    balance ratio.

    Debt service is measured from the **cash-account (checking/savings)
    debit side** so the full payment counts (P+I+E for mortgages, full
    statement payment for credit cards), not just the principal portion
    that reduces the liability balance. The account-type filter ensures
    paired transfers are counted exactly once (the source debit, not the
    destination credit). Transfer-tag exclusion is therefore intentionally
    NOT applied to the debt side — most CC and auto-loan service is
    recorded as paired transfers between checking and the liability
    account.

    Income side keeps the canonical transfer-tag exclusion; internal
    money movement should not inflate gross income.

    ``owner_id`` scopes by owner; ``None`` returns the household series.
    When scoped, ``derived_summaries`` rows are written with
    ``scope=f'owner:{owner_id}'`` instead of ``'global'``.
    """
    from dal.owners import build_account_filter

    inc_cats = list(_INCOME_CATEGORIES)
    inc_placeholders = ", ".join("?" for _ in inc_cats)

    # Categories that represent *outbound debt service* on the source
    # (cash-account) side. 'Credit Card Payments' is included defensively
    # — current data routes CC payments through 'Loan Payments' on the
    # checking side and 'Credit Card Payments' on the destination side,
    # but the cash-account filter below makes the latter a no-op.
    debt_cats = ['Mortgages', 'Loan Payments', 'Credit Card Payments', 'BNPL Payments']
    debt_placeholders = ", ".join("?" for _ in debt_cats)

    owner_filter, owner_params = build_account_filter(
        conn, owner_id, None, column="t.account_id"
    )

    params = inc_cats + debt_cats + owner_params

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
                WHEN t.signed_amount < 0
                 AND a.type IN ('checking', 'savings')
                 AND COALESCE(t.category, '') IN ({debt_placeholders})
                THEN ABS(t.signed_amount)
                ELSE 0 END) as debt_payments
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE t.status = 'posted'
          AND t.posting_date >= date('now', 'start of month', '-{{months}} months')
          AND t.posting_date < date('now', 'start of month')
          {owner_filter}
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
    scope = "global" if owner_id is None else f"owner:{owner_id}"
    for item in result:
        if item["dti_ratio"] is not None:
            conn.execute("""
                INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
                VALUES (?, 'dti_ratio', ?, ?, datetime('now'))
                ON CONFLICT(scope, metric, period)
                DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
            """, (scope, item["month"], item["dti_ratio"]))

    return result


def compute_interest_cost(
    conn: sqlite3.Connection,
    year: int | str | None = None,
    owner_id: str | None = None,
) -> dict:
    """
    Aggregate total interest paid across all liabilities for a given year.

    ``year`` defaults to the current calendar year (UTC).  Pass an explicit
    ``year`` to compute historical figures (e.g. from the Yearly Wrap-Up).
    ``owner_id`` scopes by owner; ``None`` returns the household total.
    When scoped, the ``derived_summaries`` row is written with
    ``scope=f'owner:{owner_id}'`` instead of ``'global'``.

    Sources (checked in priority order per account):
    1. loan_details field: 'ytd_interest' or 'Interest Paid YTD'
       (latest as_of for the requested year)
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
    from dal.owners import build_account_filter

    if year is None:
        current_year = datetime.now(timezone.utc).strftime("%Y")
    else:
        current_year = f"{int(year):04d}"

    # 1. Base list of all active liability accounts that actually have data.
    # Filtering against balance_snapshots / transactions / loan_details
    # hides the empty institution stubs that seed_institutions creates on
    # every backend startup; otherwise the wrap-up by_account list shows
    # ghost rows.  loan_details is included so a mortgage that only has
    # KV-shaped data (no transactions, no snapshots) still surfaces.
    owner_filter, owner_params = build_account_filter(
        conn, owner_id, None, column="id"
    )
    liability_accounts = conn.execute(f"""
        SELECT id, name, type
        FROM accounts
        WHERE is_active = 1
          AND type IN ('credit_card', 'loan', 'bnpl', 'mortgage')
          AND id IN (
              SELECT DISTINCT account_id FROM balance_snapshots
              UNION
              SELECT DISTINCT account_id FROM transactions
              UNION
              SELECT DISTINCT account_id FROM loan_details
          )
          {owner_filter}
    """, owner_params).fetchall()

    by_account = []
    ytd_total = 0.0

    # Pre-fetch both YTD sources in one pass each, then resolve per
    # account in Python. Previously the loop ran 1–2 SELECTs per
    # liability account (10–30 accounts typical).
    acct_ids = [a["id"] for a in liability_accounts]
    loan_details_by_acct: dict[str, str] = {}
    tx_totals_by_acct: dict[str, float] = {}
    if acct_ids:
        placeholders = ", ".join("?" for _ in acct_ids)
        # For each account, keep the most recent YTD-interest loan_detail
        # row. ROW_NUMBER with ORDER BY as_of DESC mirrors the per-account
        # ``ORDER BY as_of DESC LIMIT 1`` the old loop did.
        for r in conn.execute(
            f"""
            SELECT account_id, field_value FROM (
                SELECT account_id, field_value,
                       ROW_NUMBER() OVER (
                         PARTITION BY account_id ORDER BY as_of DESC
                       ) AS rn
                  FROM loan_details
                 WHERE account_id IN ({placeholders})
                   AND (LOWER(field_name) LIKE '%interest%ytd%'
                        OR LOWER(field_name) IN ('ytd_interest', 'interest paid ytd', 'ytd interest paid'))
                   AND strftime('%Y', as_of) = ?
            ) ranked
             WHERE rn = 1
               AND field_value IS NOT NULL
            """,
            acct_ids + [current_year],
        ).fetchall():
            loan_details_by_acct[r["account_id"]] = r["field_value"]

        for r in conn.execute(
            f"""
            SELECT account_id, SUM(ABS(signed_amount)) AS total
              FROM transactions
             WHERE account_id IN ({placeholders})
               AND status = 'posted'
               AND (LOWER(category) LIKE '%interest%' OR LOWER(category) LIKE '%finance charge%')
               AND strftime('%Y', posting_date) = ?
             GROUP BY account_id
            """,
            acct_ids + [current_year],
        ).fetchall():
            if r["total"] is not None:
                tx_totals_by_acct[r["account_id"]] = float(r["total"])

    for acct in liability_accounts:
        acct_id = acct["id"]
        ytd_val = 0.0
        source: str | None = None

        ld_val = loan_details_by_acct.get(acct_id)
        if ld_val:
            val_str = str(ld_val).replace('$', '').replace(',', '').replace('%', '').strip()
            try:
                ytd_val = float(val_str)
                source = "loan_details"
            except ValueError:
                pass

        if source is None:
            tx_total = tx_totals_by_acct.get(acct_id)
            if tx_total is not None:
                ytd_val = tx_total
            source = "transactions"

        ytd_val = round(ytd_val, 2)
        ytd_total += ytd_val

        by_account.append({
            "account_id": acct_id,
            "account_name": acct["name"],
            "account_type": acct["type"],
            "ytd_interest": ytd_val,
            "source": source,
        })

    # Monthly breakdown across all liability accounts
    mb_owner_filter, mb_owner_params = build_account_filter(
        conn, owner_id, None, column="t.account_id"
    )
    mb_rows = conn.execute(f"""
        SELECT strftime('%Y-%m', t.posting_date) as month, SUM(ABS(t.signed_amount)) as total_interest
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE t.status = 'posted'
          AND a.type IN ('credit_card', 'loan', 'bnpl')
          AND (LOWER(t.category) LIKE '%interest%' OR LOWER(t.category) LIKE '%finance charge%')
          AND strftime('%Y', t.posting_date) = ?
          {mb_owner_filter}
        GROUP BY month
        ORDER BY month ASC
    """, [current_year] + mb_owner_params).fetchall()

    monthly_breakdown = [
        {"month": r["month"], "total_interest": round(r["total_interest"] or 0.0, 2)}
        for r in mb_rows
    ]

    # Interest earned (YTD).  Household view keeps the legacy OR-pattern
    # (HYSA explicit + any interest-categorised credit anywhere); per-owner
    # view scopes strictly to the owner's accounts (under the principle:
    # interest income is owned by the account it lands in).
    hysa_id = _affirm_hysa_id()
    earned_filter, earned_params = build_account_filter(
        conn, owner_id, None, column="account_id"
    )
    if owner_id is None:
        earned_row = conn.execute("""
            SELECT COALESCE(SUM(signed_amount), 0) as total
            FROM transactions
            WHERE (account_id = ? OR LOWER(category) LIKE '%interest%' OR LOWER(description) = 'interest')
              AND signed_amount > 0
              AND status = 'posted'
              AND strftime('%Y', posting_date) = ?
        """, (hysa_id, current_year)).fetchone()
    else:
        earned_row = conn.execute(f"""
            SELECT COALESCE(SUM(signed_amount), 0) as total
            FROM transactions
            WHERE signed_amount > 0
              AND status = 'posted'
              AND strftime('%Y', posting_date) = ?
              AND (account_id = ? OR LOWER(category) LIKE '%interest%' OR LOWER(description) = 'interest')
              {earned_filter}
        """, [current_year, hysa_id] + earned_params).fetchone()

    interest_earned = round(earned_row["total"] or 0.0, 2)
    net_interest = round(interest_earned - ytd_total, 2)

    # Store in derived_summaries (per-owner namespace when scoped).
    scope = "global" if owner_id is None else f"owner:{owner_id}"
    conn.execute("""
        INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
        VALUES (?, 'ytd_interest_cost', ?, ?, datetime('now'))
        ON CONFLICT(scope, metric, period)
        DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
    """, (scope, current_year, ytd_total))

    return {
        "ytd_total": round(ytd_total, 2),
        "by_account": by_account,
        "monthly_breakdown": monthly_breakdown,
        "interest_earned": interest_earned,
        "net_interest": net_interest,
    }


def compute_net_worth_velocity(
    conn: sqlite3.Connection,
    owner_id: Optional[str] = None,
) -> dict:
    """
    Compute rate of net worth change across multiple timeframes.

    If owner_id is provided, the underlying net-worth history is
    restricted to that owner's accounts (delegated to
    dal.reports.get_net_worth_history which already supports owner
    scoping).
    """
    history = get_net_worth_history(conn, months=24, owner_id=owner_id)
    
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

    scope = "global" if owner_id is None else f"owner:{owner_id}"
    for metric, value in [
        ('nw_mom_change', mom_change),
        ('nw_rolling_3m_avg', rolling_3m_avg),
        ('nw_rolling_12m_avg', rolling_12m_avg),
    ]:
        if value is not None:
            conn.execute("""
                INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
                VALUES (?, ?, NULL, ?, datetime('now'))
                ON CONFLICT(scope, metric) WHERE period IS NULL
                DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
            """, (scope, metric, value))

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


def get_summary_metrics(
    conn: sqlite3.Connection,
    owner_id: Optional[str] = None,
) -> dict:
    """Get all current derived metrics for the dashboard.

    ``owner_id=None`` returns every row (every scope) — the historical
    behaviour preserved for callers that select scopes themselves.

    When ``owner_id`` is set, returns rows where ``scope='owner:<id>'``
    OR ``scope='global'`` (forgiving fallback — household metrics still
    surface for any aggregator that hasn't been per-owner-ified yet) plus
    any ``scope='account:<id>'`` rows for accounts owned by that owner.
    """
    if owner_id is None:
        rows = conn.execute("""
            SELECT scope, metric, period, value, computed_at
            FROM derived_summaries
            ORDER BY scope, metric, period
        """).fetchall()
    else:
        owner_scope = f"owner:{owner_id}"
        owner_account_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM accounts WHERE LOWER(owner_id) = LOWER(?)",
                (owner_id,),
            ).fetchall()
        ]
        account_scopes = [f"account:{aid}" for aid in owner_account_ids]
        in_clause = ", ".join("?" for _ in ([owner_scope, "global"] + account_scopes))
        rows = conn.execute(
            f"""
            SELECT scope, metric, period, value, computed_at
            FROM derived_summaries
            WHERE scope IN ({in_clause})
            ORDER BY scope, metric, period
            """,
            [owner_scope, "global"] + account_scopes,
        ).fetchall()

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
