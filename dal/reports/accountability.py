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
    match_rule_matches,
)
from dal import income_sources as income_sources_dal
from dal.reports.flow import get_flow_data

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
    # Owner-scope via real_estate.owner_id (added v22). Single-query
    # window-function fetch replaces a per-row SELECT loop (was N+1,
    # user-blocking on every dashboard net-worth render).
    re_owner_clause = "AND LOWER(owner_id) = LOWER(?)" if owner_id else ""
    re_sql = f"""
        SELECT estimated_value FROM (
            SELECT estimated_value,
                   ROW_NUMBER() OVER (
                     PARTITION BY name
                     ORDER BY as_of DESC, rowid DESC
                   ) AS rn
              FROM real_estate
             WHERE name NOT LIKE '%[%'
               AND date(as_of) <= date(?)
               {re_owner_clause}
        ) ranked
         WHERE rn = 1
           AND estimated_value IS NOT NULL
    """
    re_params: list = [as_of]
    if owner_id:
        re_params.append(owner_id)
    re_total = sum(
        float(row["estimated_value"])
        for row in conn.execute(re_sql, re_params).fetchall()
    )

    # Vehicles: latest per-vehicle valuation on or before as_of.
    # Owner-scope via vehicle_assets.owner_id (added v22). Same
    # N+1 → single-query rewrite as real_estate above.
    veh_total = 0.0
    try:
        if owner_id:
            veh_sql = """
                SELECT estimated_value FROM (
                    SELECT vv.estimated_value,
                           ROW_NUMBER() OVER (
                             PARTITION BY vv.vehicle_id
                             ORDER BY vv.valuation_date DESC, vv.id DESC
                           ) AS rn
                      FROM vehicle_valuations vv
                      JOIN vehicle_assets va ON va.id = vv.vehicle_id
                     WHERE date(vv.valuation_date) <= date(?)
                       AND LOWER(va.owner_id) = LOWER(?)
                ) ranked
                 WHERE rn = 1
                   AND estimated_value IS NOT NULL
            """
            veh_params: list = [as_of, owner_id]
        else:
            veh_sql = """
                SELECT estimated_value FROM (
                    SELECT estimated_value,
                           ROW_NUMBER() OVER (
                             PARTITION BY vehicle_id
                             ORDER BY valuation_date DESC, id DESC
                           ) AS rn
                      FROM vehicle_valuations
                     WHERE date(valuation_date) <= date(?)
                ) ranked
                 WHERE rn = 1
                   AND estimated_value IS NOT NULL
            """
            veh_params = [as_of]
        veh_total = sum(
            float(row["estimated_value"])
            for row in conn.execute(veh_sql, veh_params).fetchall()
        )
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
    window — covers both money-flow shapes documented in
    ``dal/reports/flow.py``.

    Shape A — paired transactions, transfer_tag self-join. The bank-side
    cash leg's amount counts when its peer's ``accounts.type`` is
    investment / brokerage / retirement / hsa.

    Shape B — bank cash leg linked to a brokerage's
    ``positions_ledger`` row via ``positions_ledger.bank_txn_id``
    (Acorns, Fidelity EFT, future TSP / taxable-broker).

    Both shapes UNION on ``transactions.id`` so a cash leg matched in
    both paths counts once. Intra-account credits (dividend reinvestment,
    employer match) and downstream allocation rows (the per-ETF Acorns
    rows whose bank_txn_id is NULL because the linker only sets it on
    the primary ledger row) do NOT match either shape and are excluded
    by construction.

    The accountability identity uses this term to subtract user-funded
    growth out of the investment-balance delta, isolating "pure market
    movement" in ``market_value_delta_cents``.
    """
    t1_acct_filter, t1_acct_params = build_account_filter(
        conn, owner_id, None, column="t1.account_id",
    )
    t_acct_filter, t_acct_params = build_account_filter(
        conn, owner_id, None, column="t.account_id",
    )
    row = conn.execute(
        f"""
        SELECT SUM(amt) AS total_dollars FROM (
            -- Shape A: paired transactions, peer is investment-type.
            SELECT t1.id AS tx_id, ABS(t1.signed_amount) AS amt
              FROM transactions t1
              JOIN transactions t2
                   ON t1.transfer_tag = t2.transfer_tag AND t1.id != t2.id
              JOIN accounts a2 ON a2.id = t2.account_id
             WHERE t1.status = 'posted'
               AND t1.signed_amount < 0
               AND t1.transfer_tag IS NOT NULL
               AND a2.type IN ('investment', 'brokerage', 'retirement', 'hsa')
               AND date(t1.posting_date) >= date(?)
               AND date(t1.posting_date) <= date(?)
               {t1_acct_filter}
            UNION
            -- Shape B: bank cash leg linked via positions_ledger.bank_txn_id.
            SELECT t.id AS tx_id, ABS(t.signed_amount) AS amt
              FROM transactions t
              JOIN positions_ledger pl ON pl.bank_txn_id = t.id
             WHERE t.status = 'posted'
               AND t.signed_amount < 0
               AND date(t.posting_date) >= date(?)
               AND date(t.posting_date) <= date(?)
               {t_acct_filter}
        )
        """,
        [start_date, end_date] + t1_acct_params
        + [start_date, end_date] + t_acct_params,
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
