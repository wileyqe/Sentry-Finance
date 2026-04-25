"""Reports group audit — read-only checks against dal.reports.get_flow_data and get_accountability."""
import json
import sys
from pathlib import Path

REPO = r"C:\Users\chang\OneDrive\Desktop\Projects\Personal Finance Project"
sys.path.insert(0, REPO)

from dal.connection import get_db
from dal.owners import build_account_filter
from dal.reports import get_flow_data, get_accountability
from dal.category_classifications import (
    INCOME_EXCL_FROM_INC,
    ALL_EXCL_FROM_SPEND,
)

START = "2026-01-01"
END = "2026-04-24"
OWNER = "quintin"

results = []


def add(invariant_id, description, status, expected, actual, tolerance, script, notes=""):
    results.append({
        "invariant_id": invariant_id,
        "page": "ReportsPage.tsx",
        "description": description,
        "status": status,
        "expected": expected,
        "actual": actual,
        "tolerance": tolerance,
        "query_or_script": script,
        "notes": notes,
    })


with get_db() as conn:
    # Pre-fetch the canonical flow once
    flow = get_flow_data(conn, owner_id=OWNER, start_date=START, end_date=END)

    # ── rep_001: total_income == canonical income aggregate over [start,end] ──
    # Canonical income aggregate, hand-rolled, mirroring the DAL
    income_excl = list(INCOME_EXCL_FROM_INC)
    income_ph = ", ".join("?" for _ in income_excl)
    acct_filter, acct_params = build_account_filter(conn, OWNER, None)
    EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"
    start_em = START[:7]
    end_em = END[:7]

    # Note: rep_001 must account for Phase14 payroll gross adjustment.
    # For an independent recompute, we replicate the DAL's logic: sum positive
    # signed_amounts (transfer_tag NULL, status posted, not in income_excl)
    # over the window EXCEPT excluded payroll deposit txn ids, then add
    # matched_gross_minus_net delta.
    excluded_ids = list(flow["payroll_decomposition"].get("excluded_transaction_ids", []))
    excluded_clause = ""
    excluded_params = []
    if excluded_ids:
        excluded_clause = "AND id NOT IN (" + ", ".join("?" for _ in excluded_ids) + ")"
        excluded_params = list(excluded_ids)

    txn_income_sql = f"""
        SELECT COALESCE(SUM(signed_amount), 0) AS total
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount > 0
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Other Income') NOT IN ({income_ph})
          {excluded_clause}
          AND {EM} BETWEEN ? AND ?
          {acct_filter}
    """
    params = income_excl + excluded_params + [start_em, end_em] + acct_params
    txn_income = conn.execute(txn_income_sql, params).fetchone()[0] or 0
    matched_gross_minus_net_cents = sum(
        (p["gross_cents"] - p["net_cents"])
        for p in flow["payroll_decomposition"]["payroll_rows"]
        if p.get("matched_txn_id") is not None
    )
    expected_income = round(txn_income + matched_gross_minus_net_cents / 100.0, 2)
    actual_income = flow["total_income"]
    ok = abs(expected_income - actual_income) <= 0.01
    add("rep_001_flow_total_income_canonical",
        "get_flow_data().total_income equals canonical income aggregate over [start_date, end_date]",
        "pass" if ok else "fail",
        expected_income, actual_income, 0.01,
        "see _run_reports_audit.py rep_001 block")

    # ── rep_002: total_spending == canonical spending aggregate ──
    spend_excl = list(ALL_EXCL_FROM_SPEND)
    spend_ph = ", ".join("?" for _ in spend_excl)
    spend_sql = f"""
        SELECT COALESCE(SUM(-signed_amount), 0) AS total
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount < 0
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') NOT IN ({spend_ph})
          AND {EM} BETWEEN ? AND ?
          {acct_filter}
    """
    sp_params = spend_excl + [start_em, end_em] + acct_params
    expected_spend = round(conn.execute(spend_sql, sp_params).fetchone()[0] or 0, 2)
    actual_spend = flow["total_spending"]
    ok = abs(expected_spend - actual_spend) <= 0.01
    add("rep_002_flow_total_spending_canonical",
        "get_flow_data().total_spending equals canonical spending aggregate over [start_date, end_date]",
        "pass" if ok else "fail",
        expected_spend, actual_spend, 0.01,
        "canonical SUM(-signed_amount) WHERE signed_amount<0 AND transfer_tag IS NULL AND category NOT IN ALL_EXCL_FROM_SPEND")

    # ── rep_003: net == income - spending ──
    expected_net = round(flow["total_income"] - flow["total_spending"], 2)
    actual_net = flow["net"]
    ok = abs(expected_net - actual_net) <= 0.01
    add("rep_003_flow_net_equals_income_minus_spending",
        "get_flow_data().net == total_income - total_spending exactly",
        "pass" if ok else "fail",
        expected_net, actual_net, 0.01,
        "flow['net'] vs flow['total_income'] - flow['total_spending']")

    # ── rep_004: savings_rate formula ──
    inc = flow["total_income"]
    if inc <= 0:
        expected_sr = 0
    else:
        expected_sr = round(flow["net"] / inc * 100, 1)
    actual_sr = flow["savings_rate"]
    ok = abs(expected_sr - actual_sr) <= 0.0001
    add("rep_004_flow_savings_rate_formula",
        "get_flow_data().savings_rate == (net / total_income * 100); 0 when income<=0",
        "pass" if ok else "fail",
        expected_sr, actual_sr, 0.0001,
        "rounded to 1 decimal per DAL impl")

    # ── rep_005: sum income_categories[].total == total_income ──
    sum_inc_cats = round(sum(c["total"] for c in flow["income_categories"]), 2)
    # Note: DAL's total_income = txn-side income + matched_gross_delta (payroll)
    # so income_categories may sum to LESS than total_income by exactly matched_gross_delta.
    matched_gross_delta = round(matched_gross_minus_net_cents / 100.0, 2)
    expected_sum = round(flow["total_income"] - matched_gross_delta, 2)
    ok = abs(sum_inc_cats - expected_sum) <= 0.01
    add("rep_005_income_categories_sum",
        "Sum of income_categories[].total equals total_income (minus payroll gross-up adjustment)",
        "pass" if ok else "fail",
        expected_sum, sum_inc_cats, 0.01,
        f"matched_gross_delta={matched_gross_delta} excluded from income_categories sum vs total_income")

    # ── rep_006: sum spending_categories[].total == total_spending ──
    sum_sp_cats = round(sum(c["total"] for c in flow["spending_categories"]), 2)
    actual_total_spend = flow["total_spending"]
    ok = abs(sum_sp_cats - actual_total_spend) <= 0.01
    add("rep_006_spending_categories_sum",
        "Sum of spending_categories[].total equals total_spending",
        "pass" if ok else "fail",
        actual_total_spend, sum_sp_cats, 0.01,
        "")

    # ── rep_007: |bucket_invariant_drift_cents| <= 100 ──
    drift = flow.get("bucket_invariant_drift_cents", 0)
    ok = abs(drift) <= 100
    add("rep_007_bucket_invariant_drift",
        "abs(bucket_invariant_drift_cents) <= 100",
        "pass" if ok else "fail",
        "|drift| <= 100", drift, 100,
        "")

    # ── rep_008: buckets sum to inflow ──
    btc = flow["bucket_totals_cents"]
    bucket_sum = btc["CONSUMED"] + btc["STORED_LIQUID"] + btc["STORED_ILLIQUID"]
    inflow = flow["total_inflow_cents"]
    diff_cents = abs(bucket_sum - inflow)
    ok = diff_cents <= 100  # $1 tolerance per invariant text
    add("rep_008_buckets_sum_to_inflow",
        "CONSUMED + STORED_LIQUID + STORED_ILLIQUID == total_inflow_cents within $1",
        "pass" if ok else "fail",
        inflow, bucket_sum, 100,
        f"diff_cents={diff_cents}")

    # ── rep_009: mortgage splits sum check (skip method=='unsplit') ──
    splits = flow.get("mortgage_splits", []) or []
    mismatches = []
    checked = 0
    for s in splits:
        method = s.get("method")
        if method == "unsplit":
            continue
        principal = s.get("principal_cents", 0) or 0
        interest = s.get("interest_cents", 0) or 0
        escrow = s.get("escrow_cents", 0) or 0
        # Find total — the field name varies. Look for total or amount_cents.
        total = s.get("total_cents") or s.get("amount_cents") or s.get("payment_cents")
        if total is None:
            # try transaction lookup by id
            tx_id = s.get("transaction_id") or s.get("txn_id")
            if tx_id is not None:
                row = conn.execute(
                    "SELECT signed_amount FROM transactions WHERE id = ?", (tx_id,)
                ).fetchone()
                if row is not None:
                    total = int(round(abs(row["signed_amount"]) * 100))
        if total is None:
            mismatches.append({"split": s, "issue": "no total found"})
            continue
        s_sum = principal + interest + escrow
        checked += 1
        if abs(s_sum - total) > 1:
            mismatches.append({
                "txn_id": s.get("transaction_id") or s.get("txn_id"),
                "method": method,
                "p+i+e": s_sum,
                "total": total,
                "diff": s_sum - total,
            })
    if checked == 0:
        methods_present = sorted({(s.get("method") or "<none>") for s in splits})
        add("rep_009_mortgage_split_components_sum",
            "For each mortgage_split: principal+interest+escrow == total (where method != 'unsplit')",
            "could_not_verify",
            None, None, 1.0,
            "see _run_reports_audit.py rep_009 block",
            f"All {len(splits)} mortgage_splits in window have method='unsplit' (methods_present={methods_present}); "
            f"per task instructions these are excluded from the sum invariant. "
            f"No splittable mortgage payments in [2026-01-01, 2026-04-24] for owner=quintin.")
    else:
        ok = len(mismatches) == 0
        add("rep_009_mortgage_split_components_sum",
            "For each mortgage_split: principal+interest+escrow == total (where method != 'unsplit')",
            "pass" if ok else "fail",
            f"all {checked} sums match", f"{len(mismatches)} mismatches out of {checked}",
            1.0,
            "principal_cents+interest_cents+escrow_cents vs total_cents (or txn signed_amount*100)",
            json.dumps(mismatches[:5]) if mismatches else "")

    # ── rep_010: get_accountability rejects unbounded windows ──
    # Verified by router definition: start_date is Query(..., ...) (required).
    # Also call DAL directly with empty start to see behavior. The DAL
    # itself takes start_date as a required positional arg, so the type
    # signature enforces it.
    import inspect
    sig = inspect.signature(get_accountability)
    start_param = sig.parameters.get("start_date")
    has_default = start_param.default is not inspect.Parameter.empty
    # Also confirm router declares Query(...) -> required
    router_path = Path(REPO) / "backend" / "routers" / "reports.py"
    router_text = router_path.read_text(encoding="utf-8")
    router_requires = "start_date: str = Query(..." in router_text
    ok = (not has_default) and router_requires
    add("rep_010_accountability_window_required",
        "get_accountability rejects unbounded windows (no start_date)",
        "pass" if ok else "fail",
        "start_date required (no default in DAL, Query(...) in router)",
        f"DAL has_default={has_default}, router_Query_required={router_requires}",
        None,
        "DAL signature + router Query(...) declaration",
        "")

    # ── rep_011: identity holds ──
    acc = get_accountability(conn, START, END, owner_id=OWNER)
    nwd = acc["net_worth_delta_cents"]
    t = acc["identity_terms"]
    accounted = (
        t["dollars_in_cents"]
        - t["dollars_spent_cents"]
        + t["market_value_delta_cents"]
        + t["real_estate_delta_cents"]
        + t["vehicle_delta_cents"]
    )
    expected = nwd
    actual = accounted + acc["unexplained_cents"]
    ok = abs(expected - actual) <= 1  # 1 cent tol
    add("rep_011_accountability_identity",
        "net_worth_delta_cents = dollars_in - dollars_spent + market_value_delta + RE_delta + vehicle_delta + unexplained",
        "pass" if ok else "fail",
        expected, actual, 1.0,
        "sum identity terms + unexplained must == nw_delta_cents",
        "")

    # ── rep_012: accounted_for_pct in [0, 1.5] ──
    pct = acc["accounted_for_pct"]
    ok = 0.0 <= pct <= 1.5
    add("rep_012_accountability_pct_bounds",
        "accounted_for_pct is in [0, 1.5]",
        "pass" if ok else "fail",
        "[0.0, 1.5]", pct, 0,
        "",
        "")

    # ── rep_013: payroll gross - net == sum withholdings per row ──
    pdec = flow["payroll_decomposition"]
    rows = pdec.get("payroll_rows", [])
    bad = []
    for r in rows:
        gross = r.get("gross_cents", 0) or 0
        net = r.get("net_cents", 0) or 0
        wh_list = r.get("withholdings", []) or []
        wh_sum = sum((w.get("cents") or w.get("amount_cents") or 0) for w in wh_list)
        diff = (gross - net) - wh_sum
        if abs(diff) > 1:
            bad.append({
                "snapshot_id": r.get("id") or r.get("snapshot_id"),
                "gross": gross, "net": net, "wh_sum": wh_sum, "diff": diff,
                "wh_keys": list(wh_list[0].keys()) if wh_list else [],
            })
    if not rows:
        add("rep_013_payroll_gross_minus_net_equals_withheld",
            "payroll_decomposition: total_gross_cents - total_net_cents == sum(withholdings.cents) per row",
            "could_not_verify", None, None, 1.0,
            "iterate payroll_rows and compare (gross-net) to sum(withholdings.cents)",
            "no payroll_rows in window")
    else:
        ok = len(bad) == 0
        add("rep_013_payroll_gross_minus_net_equals_withheld",
            "payroll_decomposition: total_gross_cents - total_net_cents == sum(withholdings.cents) per row",
            "pass" if ok else "fail",
            f"all {len(rows)} rows balance",
            f"{len(bad)} mismatches",
            1.0,
            "iterate payroll_rows; sum withholdings list",
            json.dumps(bad[:3]) if bad else "")

    # ── rep_014: total_spending excludes transfer_tag IS NOT NULL ──
    # Recompute spending WITHOUT transfer_tag IS NULL filter and
    # confirm the difference equals SUM of (-signed_amount) of transfer rows
    # in the same canonical-spending shape.
    no_tt_filter_sql = f"""
        SELECT COALESCE(SUM(-signed_amount), 0) AS total
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount < 0
          AND COALESCE(category, 'Uncategorized') NOT IN ({spend_ph})
          AND {EM} BETWEEN ? AND ?
          {acct_filter}
    """
    no_tt_params = spend_excl + [start_em, end_em] + acct_params
    spend_no_tt = conn.execute(no_tt_filter_sql, no_tt_params).fetchone()[0] or 0
    transfer_only_sql = f"""
        SELECT COALESCE(SUM(-signed_amount), 0) AS total
        FROM transactions
        WHERE status = 'posted'
          AND signed_amount < 0
          AND transfer_tag IS NOT NULL
          AND COALESCE(category, 'Uncategorized') NOT IN ({spend_ph})
          AND {EM} BETWEEN ? AND ?
          {acct_filter}
    """
    transfer_only = conn.execute(transfer_only_sql, no_tt_params).fetchone()[0] or 0
    diff = round(spend_no_tt - flow["total_spending"], 2)
    expected = round(transfer_only, 2)
    ok = abs(diff - expected) <= 0.01
    add("rep_014_no_transfer_tag_in_total_spending",
        "total_spending excludes transfer_tag IS NOT NULL (verified by recomputing without filter)",
        "pass" if ok else "fail",
        expected, diff, 0.01,
        "spend_no_tt - flow.total_spending == sum of transfer-tagged spending",
        f"spend_no_tt={spend_no_tt:.2f}, total_spending={flow['total_spending']:.2f}, transfer_only={transfer_only:.2f}")


out = Path(REPO) / "docs" / "audits" / "files" / "results-reports.json"
out.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
print(f"WROTE {out}: {len(results)} results")
for r in results:
    print(f"  {r['invariant_id']}: {r['status']}")
