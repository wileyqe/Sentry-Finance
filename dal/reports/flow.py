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

from dal.clock import reference_date
from dal.owners import build_account_filter
from dal.payroll import find_matching_deposit_tx_id, get_flow_contribution
from dal.flow_classification import (
    BucketLabel,
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


def get_flow_data(
    conn: sqlite3.Connection,
    months: int = 1,
    account_ids: Optional[list[str]] = None,
    owner_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Income by category + spending by category for a period.

    As of PR2 of the spending-semantics overhaul, this delegates to
    ``compute_period_totals`` for the headline numbers and category
    breakdowns. Identical lens semantics as the Cash Flow page — for
    the same window, ``get_flow_data`` and
    ``dal.cash_flow.get_period_detail`` MUST agree to the cent on
    income, spending, net, savings_rate, and debt_service. The parity
    is enforced by ``tests/test_cashflow_reports_parity.py``.

    Window: explicit ``start_date`` / ``end_date`` are preferred. The
    legacy ``months`` int falls back to ``today - N months → today``.

    Returns the same JSON shape as before (preserving the Sankey-side
    fields ``payroll_decomposition``, ``bucket_totals``,
    ``mortgage_splits``, ``transfer_flows``, ``bypass_flows``,
    ``reinvestment_flows``, ``total_inflow_cents``,
    ``bucket_invariant_drift_cents``) plus four new debt-* fields:
    ``debt_service``, ``debt_accumulated``, ``debt_paid_down``,
    ``net_debt_change``.
    """
    from dal.flow_aggregation import compute_period_totals

    # Resolve the window. Explicit dates win; legacy months int falls back.
    if start_date and end_date:
        sd, ed = start_date, end_date
    else:
        today = reference_date(conn)
        ed = today.strftime("%Y-%m-%d")
        sd_dt = today - timedelta(days=months * 31)
        sd = sd_dt.strftime("%Y-%m-%d")

    r = compute_period_totals(
        conn,
        start_date=sd,
        end_date=ed,
        owner_id=owner_id,
        account_ids=account_ids,
    )

    # Convert to the legacy (dollars) shape consumers expect.
    income_cats = [
        {
            "category": c["category"],
            "total": round(c["total_cents"] / 100.0, 2),
            "count": c["count"],
        }
        for c in r["income_breakdown"]
    ]
    spend_cats = [
        {
            "category": c["category"],
            "total": round(c["total_cents"] / 100.0, 2),
            "count": c["count"],
            # Legacy field — every spending row in the cash-out lens is
            # CONSUMED by definition.
            "bucket": BucketLabel.CONSUMED.value,
        }
        for c in r["spending_breakdown"]
    ]
    total_income = round(r["income_cents"] / 100.0, 2)
    total_spending = round(r["spending_cents"] / 100.0, 2)
    net = round(r["net_cents"] / 100.0, 2)
    savings_rate = round(r["savings_rate"], 1) if r["savings_rate"] is not None else 0

    # Replay the payroll-decomposition payload for the Sankey UI. The
    # aggregator already ran this path internally; we re-call to surface
    # the matched_txn_id annotations and the excluded_transaction_ids
    # list that the Sankey draws as crossed-out rows.
    contrib_start = sd[:7]
    contrib_end = ed[:7]
    payroll_contrib = get_flow_contribution(
        conn, contrib_start, contrib_end, owner_id=owner_id
    )
    excluded_tx_ids: list[str] = []
    for prow in payroll_contrib["payroll_rows"]:
        match_id = find_matching_deposit_tx_id(
            conn,
            source_label=prow["source_label"] or "",
            pay_period=prow["pay_period"],
            owner_id=owner_id,
        )
        if match_id is not None and match_id not in excluded_tx_ids:
            excluded_tx_ids.append(match_id)
            prow["matched_txn_id"] = match_id
        else:
            prow["matched_txn_id"] = None
    payroll_decomposition = dict(payroll_contrib)
    payroll_decomposition["excluded_transaction_ids"] = list(excluded_tx_ids)

    # Bucket totals and Sankey fields come from the aggregator's passthrough.
    consumed_cents = r["spending_cents"]
    liquid_cents = r["stored_liquid_cents"]
    illiquid_cents = r["stored_illiquid_cents"]

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
            "CONSUMED":        round(consumed_cents / 100.0, 2),
            "STORED_LIQUID":   round(liquid_cents / 100.0, 2),
            "STORED_ILLIQUID": round(illiquid_cents / 100.0, 2),
        },
        "bucket_totals_cents": {
            "CONSUMED":        consumed_cents,
            "STORED_LIQUID":   liquid_cents,
            "STORED_ILLIQUID": illiquid_cents,
        },
        "total_inflow_cents": r["total_inflow_cents"],
        "bucket_invariant_drift_cents": r["drift_cents"],
        "mortgage_splits": r["mortgage_splits"],
        "transfer_flows": r["transfer_flows"],
        "bypass_flows": r["bypass_flows"],
        "reinvestment_flows": r["reinvestment_flows"],
        # ── PR2 new debt-* fields (parallel to Cash Flow page) ──
        "debt_service": round(r["debt_service_cents"] / 100.0, 2),
        "debt_accumulated": round(r["debt_accumulated_cents"] / 100.0, 2),
        "debt_paid_down": round(r["debt_paid_down_cents"] / 100.0, 2),
        "net_debt_change": round(r["net_debt_change_cents"] / 100.0, 2),
    }


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
    #
    #    Two shapes of money flow between the user's own accounts:
    #
    #      Shape A — both sides emit a transactions row (mortgage payment,
    #      CC payment, bank-to-bank transfer). Resolved via the
    #      ``transactions ↔ transactions`` self-join on shared
    #      ``transfer_tag``.
    #
    #      Shape B — bank emits a transactions row; brokerage emits
    #      ``positions_ledger`` rows (Acorns, Fidelity EFT, future TSP and
    #      taxable broker). A brokerage's feed is share movements, not
    #      currency movements; there is no "second transactions row" to
    #      pair against in live data. Resolved via
    #      ``transactions.id = positions_ledger.bank_txn_id`` — the
    #      canonical link the post-commit linker
    #      (``backend/result_writer.py:_link_acorns_bank_debits``) and
    #      AI-010's seeder pass already populate.
    #
    #    Both shapes union into a single ``transfer_flows`` list with the
    #    same row schema; downstream consumers don't care which shape
    #    sourced an entry.
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

    # Shape A — paired transactions, transfer_tag self-join.
    transfer_rows = conn.execute(
        f"""
        SELECT t1.id, t1.signed_amount, t1.posting_date, t1.account_id,
               t1.category,
               t2.account_id AS peer_account_id, a2.type AS peer_type
        FROM transactions t1
        JOIN accounts a1 ON a1.id = t1.account_id
        JOIN transactions t2
             ON t1.transfer_tag = t2.transfer_tag AND t1.id != t2.id
        JOIN accounts a2 ON a2.id = t2.account_id
        WHERE t1.status = 'posted'
          AND t1.signed_amount < 0
          AND t1.transfer_tag IS NOT NULL
          AND a1.type IN ('checking', 'savings', 'money_market')
          {t1_date_filter}
          {t1_acct_filter}
        """,
        date_params + t1_acct_params,
    ).fetchall()

    # Shape B — bank cash leg linked to brokerage activity via bank_txn_id.
    # The post-commit linker sets bank_txn_id on exactly one primary ledger
    # row per cash leg, so this JOIN is 1:1 by construction; the GROUP BY
    # is belt-and-suspenders against any future writer that loosens that.
    shape_b_rows = conn.execute(
        f"""
        SELECT t1.id, t1.signed_amount, t1.posting_date, t1.account_id,
               t1.category,
               pl.account_id AS peer_account_id, a2.type AS peer_type
        FROM transactions t1
        JOIN positions_ledger pl ON pl.bank_txn_id = t1.id
        JOIN accounts a2 ON a2.id = pl.account_id
        WHERE t1.status = 'posted'
          AND t1.signed_amount < 0
          {t1_date_filter}
          {t1_acct_filter}
        GROUP BY t1.id
        """,
        date_params + t1_acct_params,
    ).fetchall()

    transfer_flows: list[dict] = []
    seen_t1_ids: set[int] = set()
    # Dedup: each transfer has two legs but we want to count the outflow only.
    # signed_amount < 0 filter already selects the debit leg. The seen set
    # also guards against the (currently impossible) case of a single cash
    # leg matching both shapes.
    for r in transfer_rows:
        if r["id"] in seen_t1_ids:
            continue
        seen_t1_ids.add(r["id"])

        amt_cents = int(round(abs(float(r["signed_amount"])) * 100))
        peer = (r["peer_type"] or "").strip().lower()

        bucket = BucketLabel.CONSUMED
        try:
            # Shape A never reaches a brokerage peer in current data
            # (brokerages don't emit paired transactions rows). If a
            # future Shape A brokerage transfer ever appears, the
            # classifier defaults it to STORED_LIQUID — most-conservative
            # fallback for "cash arrived in brokerage as cash, not yet
            # deployed."
            bucket = _classify_transfer(peer_type=peer)
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
            "shape": "A",
            "bucket": bucket.value,
        })

    for r in shape_b_rows:
        if r["id"] in seen_t1_ids:
            continue
        seen_t1_ids.add(r["id"])

        amt_cents = int(round(abs(float(r["signed_amount"])) * 100))
        peer = (r["peer_type"] or "").strip().lower()

        # Shape B's existence — a positions_ledger row pointing back at
        # this transactions row via bank_txn_id — IS the proof that the
        # cash bought shares (or arrived in the brokerage and was tracked
        # by a ledger row, which is the same outcome for flow accounting).
        # Always STORED_ILLIQUID; no window heuristic needed.
        bucket = BucketLabel.STORED_ILLIQUID
        illiquid_cents += amt_cents

        transfer_flows.append({
            "transaction_id": r["id"],
            "posting_date": r["posting_date"][:10],
            "amount_cents": amt_cents,
            "peer_account_id": r["peer_account_id"],
            "peer_account_type": peer,
            "shape": "B",
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


def _classify_transfer(peer_type: str) -> BucketLabel:
    """Thin wrapper around ``dal.flow_classification.classify`` with
    is_transfer=True pre-set — keeps the caller site tidy.

    No brokerage-buy-match heuristic — Shape B cash legs (the only
    Acorns/Fidelity-shaped transfers) bypass this function entirely
    and are classified STORED_ILLIQUID by construction in the caller.
    """
    from dal.flow_classification import classify
    return classify(
        category=None,
        account_type=None,
        transfer_peer_account_type=peer_type,
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
