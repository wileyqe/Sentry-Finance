"""
dal/flow_aggregation.py — Unified period totals across Cash Flow & Reports.

Single source of truth for the headline numbers ("income", "spending",
"net", "savings_rate", "debt_service", "debt_accumulated",
"debt_paid_down", "net_debt_change") that both the Cash Flow page and
the Reports page surface for any window.

Why this module exists
----------------------

Pre-PR1 the Cash Flow page (`dal/cash_flow.py`) and the Reports page
(`dal/reports.py::get_flow_data`) each ran their own income/spending
SQL with the same INTENDED filter (`transfer_tag IS NULL AND category
NOT IN ALL_EXCL_FROM_SPEND`) but different surrounding context (date
columns, grouping, payroll integration). The result: "Last 30 Days"
on Reports vs. "April so far" on Cash Flow returned visibly different
income and spending totals for nearly identical windows.

Worse, the legacy filter strips ALL debt-service categories
(Mortgages, Loan Payments, Auto Loan, Credit Card Payments) from
spending. The user's mental model is the cash-out lens: "spending =
all the cash that left the household in the period." Under that lens,
mortgage and auto-loan payments ARE expenses, and so are credit-card
payments toward prior-period balances. The old filter made the
biggest cash outflows in a typical household invisible.

The architecture for the cash-out lens already exists in
`dal/flow_classification.py` (Phase 14 Phase B): the CONSUMED bucket
is the spending number under the cash-out lens. It just wasn't wired
into the headline numbers — only into the Sankey via
`dal/reports.py::_compute_bucket_totals`. This module exposes a clean
API (`compute_period_totals`) that both pages will consume in PR2.

The cash-out lens (D1=B)
------------------------

Decision D1 in the PR1 plan: count debt service from the
**checking-side cash debit**, not from the destination-side credit on
the liability account. This means:

- Mortgage payment hitting checking → counts as spending (split into
  CONSUMED interest+escrow and STORED_ILLIQUID principal via
  `loan_payment_splits`).
- CC payment hitting checking (paired transfer to CC account) →
  counts as spending (CONSUMED via the transfer-flow classifier with
  peer_account_type='credit_card').
- Auto loan payment hitting checking → counts as spending.
- CC merchant purchase on the CC account → does NOT count as spending
  (it creates a liability, not a cash event). It surfaces separately
  via `debt_accumulated_cents` so the user can see "what I bought on
  credit this period".

The double-count risk under the old bucket model was:
spend_cats included CC merchant purchases (since 'Groceries' isn't in
EXCLUDED_FROM_SPEND), AND the transfer-flow path added the CC payment
on top — $200 grocery purchase + $200 CC payment = $400 CONSUMED for
$200 of actual cash out. The fix: filter spend_cats to cash accounts
(checking/savings/money_market) only, so CC merchant purchases drop
out and the transfer-flow path is the single source for CC service.

The mortgage decomposition (D2=split)
-------------------------------------

`loan_payment_splits` (Finding 3 of the PR0 audit) populates
principal/interest/escrow per mortgage payment. The bucket model
already routes principal → STORED_ILLIQUID (a forced equity savings)
and interest+escrow → CONSUMED. We keep this behavior — it correctly
treats a $1,500 mortgage with $300 principal as $1,200 of spending +
$300 of savings, rather than $1,500 of spending.

Returns
-------

See `compute_period_totals` for the full return shape. All money is
returned in integer cents (consumers convert to dollars at the edge).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from typing import Optional

from dal.owners import build_account_filter
from dal.payroll import find_matching_deposit_tx_id, get_flow_contribution
from dal.flow_classification import (
    BucketLabel,
    brokerage_buy_matches_transfer,
)
from dal.category_classifications import (
    INCOME_EXCL_FROM_INC,
)

log = logging.getLogger("sentry.dal.flow_aggregation")

# Attribution-aware month expression (mirrors dal/cash_flow.py + dal/reports.py).
_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"

# Account types that hold the user's spendable cash. CC merchant purchases
# happen on credit_card accounts and must be excluded from "spending" under
# the cash-out lens — they're tracked separately via debt_accumulated_cents.
_CASH_ACCOUNT_TYPES: tuple[str, ...] = ("checking", "savings", "money_market")

# Cash-out lens spending exclusions. We strip income (refunds inflate income,
# not spending), explicit transfers, and mortgages (handled by the mortgage
# decomposition section in _compute_bucket_totals — including them here
# would double-count: $1,500 from spend_cats + $1,200 interest+escrow +
# $300 principal). Other debt-service categories (Loan Payments, Auto Loan,
# Student Loan) stay in this query — they don't have splits, so the full
# amount is consumed.
_SPEND_EXCLUDE_CATS: frozenset[str] = frozenset({
    "Transfers",
    "Transfer",
    # Income categories — refunds in these wouldn't be spending
    "Income",
    "Paychecks/Salary",
    "Rental Income",
    "Deposits",
    "Interest",
    "Investment Income",
    "Retirement Income",
    "Tax Refund",
    "Other Income",
    "Military Pension",
    "VA Benefits",
    "VA Education Benefits",
    "Officiating Income",
    "Non-Recurring Income",
    "Refunds/Adjustments",
    # Mortgages: handled by mortgage_splits decomposition (principal →
    # STORED_ILLIQUID, interest+escrow → CONSUMED). Synthesized into
    # spending_breakdown as "Mortgage Interest & Escrow" after the bucket call.
    "Mortgages",
    "Mortgage",
})


def compute_period_totals(
    conn: sqlite3.Connection,
    *,
    start_date: str,
    end_date: str,
    owner_id: Optional[str] = None,
    account_ids: Optional[list[str]] = None,
    include_payroll_grossup: bool = True,
) -> dict:
    """Unified headline aggregator for any window.

    Parameters
    ----------
    start_date, end_date : str
        ISO YYYY-MM-DD strings. Window is inclusive on both ends.
        Internally uses `_EM BETWEEN start_date[:7] AND end_date[:7]`
        so attribution-stamped rows land in the correct month.
    owner_id : str | None
        Scope to a single owner (e.g. 'quintin', 'amy'). None = household.
    account_ids : list[str] | None
        Optional subset of accounts. None = all in scope.
    include_payroll_grossup : bool
        When True (default), income reflects gross paychecks via
        `payroll_snapshots`: the matched deposit transaction is
        excluded and (gross − net) is added back. When False, income
        is the raw net deposit total.

    Returns
    -------
    dict with integer-cents money fields::

        {
            "income_cents":           int,   # gross income if grossup enabled
            "spending_cents":         int,   # = CONSUMED bucket
            "net_cents":              int,   # income - spending
            "savings_rate":           float | None,  # net/income*100; None if income == 0
            "stored_liquid_cents":    int,   # residual (income - consumed - illiquid)
            "stored_illiquid_cents":  int,   # mortgage principal + retirement + bypass + reinvest
            "debt_service_cents":     int,   # slice of CONSUMED that's debt service
            "debt_accumulated_cents": int,   # CC merchant purchases in period (NOT in spending)
            "debt_paid_down_cents":   int,   # CC payments + auto + mortgage principal
            "net_debt_change_cents":  int,   # accumulated - paid_down (signed; +=added, -=paid down)
            "income_breakdown":       [{category, total_cents, count}, ...],
            "spending_breakdown":     [{category, total_cents, count}, ...],
            "drift_cents":            int,   # bucket invariant residual; should be 0
            "start_date":             str,
            "end_date":               str,
            # Phase 14 passthrough for the Sankey
            "mortgage_splits":        [...],
            "transfer_flows":         [...],
            "bypass_flows":           [...],
            "reinvestment_flows":     [...],
        }
    """
    # ── Window setup ─────────────────────────────────────────────────────────
    start_em = start_date[:7]
    end_em = end_date[:7]
    date_filter = f"AND {_EM} BETWEEN ? AND ?"
    date_params: list = [start_em, end_em]

    acct_filter, acct_params = build_account_filter(conn, owner_id, account_ids)

    # ── Payroll gross-up (Phase 14 Phase A) ──────────────────────────────────
    # Two cases:
    #   - Matched: deposit transaction is in income_breakdown at NET. We add
    #     (gross - net) to income so the headline reads gross, and the
    #     deposit transaction is excluded from the income SQL to avoid
    #     double-counting. Withholdings flow to consumed as usual.
    #   - Unmatched: deposit transaction is invisible (untracked account, or
    #     source_label doesn't match any description). We add the FULL
    #     gross_cents to income so the inflow is recognized, and withholdings
    #     still go to consumed. The implied net deposit ($gross - $withholdings)
    #     becomes the residual STORED_LIQUID — which correctly says "we know
    #     this much landed somewhere even if we can't see the transaction."
    payroll_contrib = get_flow_contribution(
        conn, start_em, end_em, owner_id=owner_id
    )
    excluded_tx_ids: list[str] = []
    matched_gross_minus_net_cents = 0
    unmatched_gross_cents = 0
    contributing_payroll_rows: list[dict] = []
    if include_payroll_grossup:
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
                unmatched_gross_cents += prow["gross_cents"]
            contributing_payroll_rows.append(prow)

    # ── Income breakdown ─────────────────────────────────────────────────────
    income_excl = list(INCOME_EXCL_FROM_INC)
    income_excl_ph = ", ".join("?" for _ in income_excl)
    excluded_clause = ""
    excluded_params: list = []
    if excluded_tx_ids:
        excluded_clause = (
            "AND id NOT IN (" + ", ".join("?" for _ in excluded_tx_ids) + ")"
        )
        excluded_params = list(excluded_tx_ids)

    income_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Other Income') AS category,
               SUM(signed_amount) AS total,
               COUNT(*) AS count
          FROM transactions
         WHERE status = 'posted'
           AND signed_amount > 0
           AND transfer_tag IS NULL
           AND COALESCE(category, 'Other Income') NOT IN ({income_excl_ph})
           {excluded_clause}
           {date_filter}
           {acct_filter}
         GROUP BY category
         ORDER BY total DESC
        """,
        income_excl + excluded_params + date_params + acct_params,
    ).fetchall()

    income_breakdown = [
        {
            "category": r["category"],
            "total_cents": int(round(float(r["total"] or 0) * 100)),
            "count": r["count"],
        }
        for r in income_rows
    ]

    income_from_txns_cents = sum(c["total_cents"] for c in income_breakdown)
    if include_payroll_grossup:
        income_cents = (
            income_from_txns_cents
            + matched_gross_minus_net_cents  # bumps matched-deposit net up to gross
            + unmatched_gross_cents          # adds untraceable gross paychecks whole
        )
    else:
        income_cents = income_from_txns_cents

    # ── Spending breakdown (D1=B cash-out lens) ──────────────────────────────
    # Filter to checking/savings/money_market only — kills the CC merchant
    # double-count. Debt-service categories STAY in (mortgages, loan
    # payments, etc. on cash accounts ARE expenses under the cash-out lens).
    # Refunds and explicit transfers are excluded; CC payment paired transfers
    # come in via the transfer-flow path below, not here (transfer_tag IS
    # NULL filters them out).
    spend_excl = list(_SPEND_EXCLUDE_CATS)
    spend_excl_ph = ", ".join("?" for _ in spend_excl)
    cash_types_ph = ", ".join("?" for _ in _CASH_ACCOUNT_TYPES)

    spend_rows = conn.execute(
        f"""
        SELECT COALESCE(t.category, 'Uncategorized') AS category,
               SUM(-t.signed_amount) AS total,
               COUNT(*) AS count
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
         WHERE t.status = 'posted'
           AND t.signed_amount < 0
           AND t.transfer_tag IS NULL
           AND a.type IN ({cash_types_ph})
           AND COALESCE(t.category, 'Uncategorized') NOT IN ({spend_excl_ph})
           {date_filter}
           {acct_filter}
         GROUP BY category
         ORDER BY total DESC
        """,
        list(_CASH_ACCOUNT_TYPES) + spend_excl + date_params + acct_params,
    ).fetchall()

    spending_breakdown = [
        {
            "category": r["category"],
            "total_cents": int(round(float(r["total"] or 0) * 100)),
            "count": r["count"],
        }
        for r in spend_rows
    ]

    # ── Bucket totals (CONSUMED / STORED_LIQUID / STORED_ILLIQUID) ──────────
    # Reuses the existing Phase 14 helper; we feed it the D1=B-filtered
    # spend_cats so the CC double-count is gone before _compute_bucket_totals
    # adds the transfer-flow contributions.
    from dal.reports import _compute_bucket_totals

    # _compute_bucket_totals expects spend_cats as a list of dicts with
    # 'total' (dollars). Convert from our cents-based shape.
    spend_cats_for_bucket = [
        {"category": c["category"], "total": c["total_cents"] / 100.0, "count": c["count"]}
        for c in spending_breakdown
    ]
    income_cats_for_bucket = [
        {"category": c["category"], "total": c["total_cents"] / 100.0, "count": c["count"]}
        for c in income_breakdown
    ]

    # Pass all contributing payroll rows (matched + unmatched). Withholdings
    # contribute to consumed; the unmatched gross is folded into the bucket
    # function's matched_gross_minus_net parameter (which it adds to
    # total_inflow_cents). This keeps the bucket invariant balanced — the
    # implied unmatched net deposit lands as STORED_LIQUID residual.
    bucket_result = _compute_bucket_totals(
        conn,
        acct_filter=acct_filter,
        acct_params=acct_params,
        date_filter=date_filter,
        date_params=date_params,
        spend_cats=spend_cats_for_bucket,
        withholdings=contributing_payroll_rows if include_payroll_grossup else [],
        income_cats=income_cats_for_bucket,
        matched_gross_minus_net_cents=(
            matched_gross_minus_net_cents + unmatched_gross_cents
            if include_payroll_grossup else 0
        ),
        contrib_start=start_em,
        contrib_end=end_em,
        owner_id=owner_id,
        account_ids=account_ids,
    )

    spending_cents = bucket_result["consumed_cents"]
    stored_liquid_cents = bucket_result["liquid_cents"]
    stored_illiquid_cents = bucket_result["illiquid_cents"]

    # ── Capture debt-service contributions from RAW sources BEFORE synthesis ─
    # (Synthesis below mutates spending_breakdown by adding CC Payments /
    # Mortgage Interest / etc. entries, which would double-count if scanned.)
    _DEBT_SERVICE_CASH_CATEGORIES = {
        "Loan Payments", "Loan Payment",
        "Auto Loan", "Student Loan",
        "Credit Card Payments", "BNPL Payments",
    }
    raw_debt_cash_cents = 0
    for c in spending_breakdown:
        if c["category"] in _DEBT_SERVICE_CASH_CATEGORIES:
            raw_debt_cash_cents += c["total_cents"]
    _LIABILITY_PEER_TYPES = {"credit_card", "credit", "loan", "mortgage", "bnpl"}
    transfer_to_liability_cents = 0
    for tf in bucket_result["transfer_flows"]:
        peer = (tf.get("peer_account_type") or "").strip().lower()
        if peer in _LIABILITY_PEER_TYPES:
            transfer_to_liability_cents += int(tf.get("amount_cents", 0))
    mortgage_consumed_cents = sum(
        int(ms.get("interest_cents", 0)) + int(ms.get("escrow_cents", 0))
        for ms in bucket_result["mortgage_splits"]
    )
    mortgage_principal_cents = sum(
        int(ms.get("principal_cents", 0)) for ms in bucket_result["mortgage_splits"]
    )

    # ── Synthesize visible debt-service entries into spending_breakdown ──────
    # Mortgages were excluded from spend_cats so the mortgage_splits section
    # could be the single source. CC payments via paired transfer never enter
    # spend_cats (transfer_tag IS NULL filter). We synthesize both so the user
    # sees them as line items in the category breakdown.
    mortgage_payment_count = len(bucket_result["mortgage_splits"])
    if mortgage_consumed_cents > 0:
        spending_breakdown.insert(
            0,
            {
                "category": "Mortgage Interest & Escrow",
                "total_cents": mortgage_consumed_cents,
                "count": mortgage_payment_count,
            },
        )
    _CC_BNPL_PEERS = {"credit_card", "credit", "bnpl"}
    cc_payment_cents = 0
    cc_payment_count = 0
    loan_payment_via_transfer_cents = 0
    loan_payment_via_transfer_count = 0
    for tf in bucket_result["transfer_flows"]:
        peer = (tf.get("peer_account_type") or "").strip().lower()
        if peer in _CC_BNPL_PEERS:
            cc_payment_cents += int(tf.get("amount_cents", 0))
            cc_payment_count += 1
        elif peer in ("loan", "mortgage"):
            loan_payment_via_transfer_cents += int(tf.get("amount_cents", 0))
            loan_payment_via_transfer_count += 1
    if cc_payment_cents > 0:
        spending_breakdown.append({
            "category": "Credit Card Payments",
            "total_cents": cc_payment_cents,
            "count": cc_payment_count,
        })
    if loan_payment_via_transfer_cents > 0:
        spending_breakdown.append({
            "category": "Loan / Mortgage Transfers",
            "total_cents": loan_payment_via_transfer_cents,
            "count": loan_payment_via_transfer_count,
        })
    # Synthesize a Withholdings entry from payroll snapshots so the breakdown
    # shows the (often substantial) tax/benefits portion of spending. Without
    # this, Amy's spending = $X with an empty breakdown looks like a bug.
    if include_payroll_grossup:
        withholdings_cents = 0
        withholdings_count = 0
        for prow in contributing_payroll_rows:
            for w in prow.get("withholdings", []):
                if w.get("bucket") == BucketLabel.CONSUMED.value:
                    withholdings_cents += int(w.get("cents", 0))
                    withholdings_count += 1
        if withholdings_cents > 0:
            spending_breakdown.append({
                "category": "Taxes & Withholdings",
                "total_cents": withholdings_cents,
                "count": withholdings_count,
            })
    # Re-sort by total descending so the breakdown stays useful.
    spending_breakdown.sort(key=lambda c: c["total_cents"], reverse=True)

    # ── Debt-service slice of CONSUMED ───────────────────────────────────────
    # debt_service = what the user paid this period to service debt.
    # Three sources, captured pre-synthesis above:
    #   1. mortgage_consumed_cents — mortgage interest+escrow (CONSUMED part
    #      of mortgage payments via the split, or full unsplit fallback).
    #   2. transfer_to_liability_cents — paired-transfer debits to credit_card
    #      / loan / mortgage / bnpl peers.
    #   3. raw_debt_cash_cents — non-transfer debits on cash accounts whose
    #      category is a debt-service category (e.g. an auto loan paid by
    #      check, untagged). Mortgages excluded from spend_cats so they
    #      don't appear here.
    debt_service_cents = (
        mortgage_consumed_cents
        + transfer_to_liability_cents
        + raw_debt_cash_cents
    )

    # ── Debt accumulation (NEW under D1=B) ───────────────────────────────────
    # CC merchant purchases in the period — what the user bought on credit
    # but hasn't paid back yet. By design, these are NOT in spending under
    # D1=B; this surfaces them as a parallel signal.
    debt_acc_row = conn.execute(
        f"""
        SELECT COALESCE(SUM(-t.signed_amount), 0) AS total
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
         WHERE t.status = 'posted'
           AND t.signed_amount < 0
           AND t.transfer_tag IS NULL
           AND a.type IN ('credit_card', 'credit', 'bnpl')
           AND COALESCE(t.category, '') NOT IN ('Refunds/Adjustments', 'Transfers', 'Transfer',
                                                  'Credit Card Payments', 'Loan Payments',
                                                  'Mortgages', 'Auto Loan', 'Student Loan')
           {date_filter}
           {acct_filter}
        """,
        date_params + acct_params,
    ).fetchone()
    debt_accumulated_cents = int(round(float(debt_acc_row["total"] or 0) * 100))

    # debt_paid_down_cents — how much liability balance the user reduced.
    # Sources (also captured pre-synthesis):
    #   - mortgage_principal_cents — from loan_payment_splits.principal_cents
    #   - transfer_to_liability_cents — CC / loan / bnpl payments via
    #     paired transfer (treated as fully paying down balance, which is
    #     correct for CC/BNPL; slightly overstates auto-loan paid-down by
    #     the interest portion since we don't have auto-loan splits)
    #   - raw_debt_cash_cents — untagged cash-account debt payments
    debt_paid_down_cents = (
        mortgage_principal_cents
        + transfer_to_liability_cents
        + raw_debt_cash_cents
    )

    net_debt_change_cents = debt_accumulated_cents - debt_paid_down_cents

    # ── Net + savings rate ───────────────────────────────────────────────────
    net_cents = income_cents - spending_cents
    if income_cents > 0:
        savings_rate = round(net_cents / income_cents * 100, 1)
    else:
        savings_rate = None

    return {
        "income_cents": income_cents,
        "spending_cents": spending_cents,
        "net_cents": net_cents,
        "savings_rate": savings_rate,
        "stored_liquid_cents": stored_liquid_cents,
        "stored_illiquid_cents": stored_illiquid_cents,
        "debt_service_cents": debt_service_cents,
        "debt_accumulated_cents": debt_accumulated_cents,
        "debt_paid_down_cents": debt_paid_down_cents,
        "net_debt_change_cents": net_debt_change_cents,
        "income_breakdown": income_breakdown,
        "spending_breakdown": spending_breakdown,
        "drift_cents": bucket_result["drift_cents"],
        "start_date": start_date,
        "end_date": end_date,
        # Phase 14 passthrough for the Sankey caller
        "mortgage_splits": bucket_result["mortgage_splits"],
        "transfer_flows": bucket_result["transfer_flows"],
        "bypass_flows": bucket_result["bypass_flows"],
        "reinvestment_flows": bucket_result["reinvestment_flows"],
        "total_inflow_cents": bucket_result["total_inflow_cents"],
    }
