"""
dal/yearly_wrapup.py — Annual wrap-up assembler.

Calls existing DAL functions to build a comprehensive year-end review.
Labeled 'preliminary' until tax documents are received (P6-T03).
"""

import sqlite3
import logging
import calendar
import copy
from datetime import date

log = logging.getLogger("sentry.dal.yearly_wrapup")

# Income categories — from canonical single source of truth
from dal.category_classifications import INCOME_CATEGORIES as _INCOME_CATEGORIES
_INCOME_STREAMS = sorted(_INCOME_CATEGORIES)

# Expected tax documents for P6-T03
_EXPECTED_TAX_DOCS = [
    ("dfas_1099r",     "DFAS 1099-R (Military Pension)"),
    ("fidelity_1099",  "Fidelity Consolidated 1099"),
    ("acorns_1099",    "Acorns 1099"),
    ("affirm_1099int", "Affirm 1099-INT"),
    ("nfcu_1098",      "NFCU 1098"),
]


def _build_preliminary(conn: sqlite3.Connection, year: int, owner_id: str | None = None) -> dict:
    """Build the preliminary (pre-tax-doc) yearly wrap-up."""
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"
    prior_year = year - 1
    prior_start = f"{prior_year}-01-01"
    prior_end = f"{prior_year}-12-31"

    # ── 1. Income by Stream ──────────────────────────────────────────
    income_by_stream = []
    total_income = 0.0

    acct_filter = ""
    params_extra = []
    if owner_id:
        from dal.owners import resolve_owner_account_ids
        o_acct_ids = resolve_owner_account_ids(conn, owner_id)
        if o_acct_ids:
            ph = ", ".join("?" for _ in o_acct_ids)
            acct_filter = f" AND account_id IN ({ph})"
            params_extra.extend(o_acct_ids)

    for stream in _INCOME_STREAMS:
        # Current year — `signed_amount > 0` keeps refunds / chargebacks
        # categorized into an income stream (e.g. "Deposits") from
        # silently subtracting from the stream total.
        row = conn.execute(
            f"""
            SELECT COALESCE(SUM(signed_amount), 0) as total
            FROM transactions
            WHERE status = 'posted' AND transfer_tag IS NULL
              AND signed_amount > 0
              AND category = ?
              AND posting_date >= ? AND posting_date <= ?
              {acct_filter}
            """,
            [stream, year_start, year_end] + params_extra,
        ).fetchone()
        current = round(row["total"] or 0, 2)

        # Prior year
        prow = conn.execute(
            f"""
            SELECT COALESCE(SUM(signed_amount), 0) as total
            FROM transactions
            WHERE status = 'posted' AND transfer_tag IS NULL
              AND signed_amount > 0
              AND category = ?
              AND posting_date >= ? AND posting_date <= ?
              {acct_filter}
            """,
            [stream, prior_start, prior_end] + params_extra,
        ).fetchone()
        prior = round(prow["total"] or 0, 2)

        yoy = round(((current / prior) - 1) * 100, 1) if prior > 0 else None

        income_by_stream.append({
            "stream": stream,
            "total": current,
            "prior_year": prior if prior > 0 else None,
            "yoy_change_pct": yoy,
        })
        total_income += current

    # ── 2. Spending by Category ──────────────────────────────────────
    from dal.category_classifications import INCOME_CATEGORIES, EXCLUDED_FROM_SPEND
    excl = list(INCOME_CATEGORIES | EXCLUDED_FROM_SPEND)
    excl_ph = ", ".join("?" for _ in excl)

    spend_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Uncategorized') as cat,
               SUM(-signed_amount) as total
        FROM transactions
        WHERE status = 'posted' AND transfer_tag IS NULL
          AND signed_amount < 0
          AND posting_date >= ? AND posting_date <= ?
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
          {acct_filter}
        GROUP BY cat ORDER BY total DESC
        """,
        [year_start, year_end] + excl + params_extra,
    ).fetchall()

    total_spending = sum(r["total"] or 0 for r in spend_rows)

    # Prior year spending by category
    prior_spend = {}
    pspend_rows = conn.execute(
        f"""
        SELECT COALESCE(category, 'Uncategorized') as cat,
               SUM(-signed_amount) as total
        FROM transactions
        WHERE status = 'posted' AND transfer_tag IS NULL
          AND signed_amount < 0
          AND posting_date >= ? AND posting_date <= ?
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_ph})
          {acct_filter}
        GROUP BY cat
        """,
        [prior_start, prior_end] + excl + params_extra,
    ).fetchall()
    for r in pspend_rows:
        prior_spend[r["cat"]] = round(r["total"] or 0, 2)

    spending_by_category = []
    for r in spend_rows:
        cat = r["cat"]
        total = round(r["total"] or 0, 2)
        pct = round(total / total_spending * 100, 1) if total_spending > 0 else 0
        py = prior_spend.get(cat)
        yoy = round(((total / py) - 1) * 100, 1) if py and py > 0 else None
        spending_by_category.append({
            "category": cat,
            "total": total,
            "pct_of_spending": pct,
            "prior_year": py,
            "yoy_change_pct": yoy,
        })

    savings_rate = round((total_income - total_spending) / total_income * 100, 1) if total_income > 0 else 0

    # ── 3. Net Worth Trajectory ──────────────────────────────────────
    net_worth_trajectory = []
    try:
        from dal.reports import get_net_worth_history
        nw = get_net_worth_history(conn, months=24, owner_id=owner_id)
        for row in nw:
            if row.get("month", "").startswith(str(year)):
                net_worth_trajectory.append({
                    "month": row["month"],
                    "net_worth": row.get("net_worth", row.get("net", 0)),
                })
    except Exception as e:
        log.warning("Net worth trajectory failed: %s", e)

    # ── 4. Interest ──────────────────────────────────────────────────
    interest = {"total_paid": 0, "total_earned": 0, "net_cost": 0, "by_account": []}
    try:
        from dal.derived import compute_interest_cost
        # Phase C fix: pass `year` so historic years can be requested.
        # The function signature does not accept owner_id; the swallowed
        # TypeError used to leave interest at $0 across the board.
        ic = compute_interest_cost(conn, year=year)
        # `compute_interest_cost` returns ytd_total / interest_earned /
        # net_interest — the prior wrap-up code looked up the wrong
        # field names so the panel was effectively never populated even
        # if the call succeeded.
        interest = {
            "total_paid": ic.get("ytd_total", 0),
            "total_earned": ic.get("interest_earned", 0),
            "net_cost": ic.get("net_interest", 0),
            "by_account": ic.get("by_account", []),
        }
    except Exception as e:
        log.warning("Interest cost failed: %s", e)

    # ── 5. Investment Performance ────────────────────────────────────
    investment_performance = []
    try:
        inv_acct_filter = ""
        inv_params = []
        if owner_id:
            from dal.owners import resolve_owner_account_ids
            o_acct_ids = resolve_owner_account_ids(conn, owner_id)
            if o_acct_ids:
                ph = ", ".join("?" for _ in o_acct_ids)
                inv_acct_filter = f" AND a.id IN ({ph})"
                inv_params.extend(o_acct_ids)
                
        accounts = conn.execute(
            f"""
            SELECT a.id, a.name FROM accounts a
            WHERE a.type IN ('investment', 'retirement') AND a.is_active = 1
            {inv_acct_filter}
            """,
            inv_params
        ).fetchall()

        # Use the proper Simple Dietz decomposition from dal/performance.py
        # instead of naive (end/start - 1) which ignores contributions.
        from dal.performance import decompose_contributions_vs_performance
        acct_ids = [a["id"] for a in accounts]
        decomposed = decompose_contributions_vs_performance(
            conn, year, account_ids=acct_ids, owner_id=owner_id
        )
        for d in decomposed:
            investment_performance.append({
                "account_id": d["account_id"],
                "name": d["account_name"],
                "start_value": d["start_value"] or 0,
                "end_value": d["end_value"] or 0,
                "total_return_pct": d["performance_return_pct"],
                "contributions": d["net_contributions"],
                "performance_gain": d["performance_gain"],
            })
    except Exception as e:
        log.warning("Investment performance failed: %s", e)

    # ── 6. Debt Progress ─────────────────────────────────────────────
    debt_progress = []
    try:
        from dal.debt import get_debt_summary
        debt = get_debt_summary(conn, owner_id=owner_id)
        for d in debt.get("debts", []):
            # Jan 1 balance
            jan_snap = conn.execute(
                "SELECT balance FROM balance_snapshots WHERE account_id = ? AND as_of <= ? ORDER BY as_of DESC LIMIT 1",
                (d["account_id"], f"{year}-01-15"),
            ).fetchone()
            jan_bal = round(abs(jan_snap["balance"] or 0), 2) if jan_snap else 0

            debt_progress.append({
                "account_id": d["account_id"],
                "name": d["name"],
                "balance_jan1": jan_bal,
                "balance_dec31": d["balance"],
                "principal_paid": round(jan_bal - d["balance"], 2) if jan_bal > 0 else 0,
                "months_remaining": None,
                "apr": d.get("apr"),
            })
    except Exception as e:
        log.warning("Debt progress failed: %s", e)

    # ── 7. Recurring Changes ─────────────────────────────────────────
    recurring_changes = {"new": [], "removed": [], "price_changes": []}
    try:
        # New
        new_subs = conn.execute(
            "SELECT merchant, expected_amount, first_seen FROM recurring_transactions WHERE first_seen >= ? AND first_seen <= ? AND status = 'active'",
            (year_start, year_end),
        ).fetchall()
        for ns in new_subs:
            recurring_changes["new"].append({
                "merchant": ns["merchant"],
                "amount": round(ns["expected_amount"] or 0, 2),
                "first_seen": ns["first_seen"],
            })

        # Removed
        removed = conn.execute(
            "SELECT merchant, expected_amount, last_seen FROM recurring_transactions WHERE last_seen >= ? AND last_seen <= ? AND status = 'inactive'",
            (year_start, year_end),
        ).fetchall()
        for rm in removed:
            recurring_changes["removed"].append({
                "merchant": rm["merchant"],
                "last_amount": round(rm["expected_amount"] or 0, 2),
                "last_seen": rm["last_seen"],
            })

        # Price changes
        mutations = conn.execute(
            """
            SELECT rt.merchant, rm.old_amount, rm.new_amount,
                   (rm.new_amount - rm.old_amount) as delta
            FROM recurring_mutations rm
            JOIN recurring_transactions rt ON rt.id = rm.recurring_id
            WHERE rm.detected_at >= ? AND rm.detected_at <= ?
            """,
            (year_start, year_end),
        ).fetchall()
        for m in mutations:
            delta = round(m["delta"] or 0, 2)
            recurring_changes["price_changes"].append({
                "merchant": m["merchant"],
                "old_amount": round(m["old_amount"] or 0, 2),
                "new_amount": round(m["new_amount"] or 0, 2),
                "delta": delta,
                "annualized_delta": round(delta * 12, 2),
            })
    except Exception as e:
        log.warning("Recurring changes failed: %s", e)

    # ── 8. Goals Progress ────────────────────────────────────────────
    # Include any goal that was active during the year, not just goals
    # currently active today.  Filtering on status='active' silently
    # dropped completed goals from prior years even though they were
    # funded throughout that year.
    goals_progress = []
    try:
        from dal.goals import list_goals
        all_goals = list_goals(conn)
        for g in all_goals:
            # Skip goals created entirely after the requested year ended.
            created = g.get("created_at") or ""
            if created and created[:4] > str(year):
                continue
            # Skip goals completed entirely before the year began.
            completed = g.get("completed_at") or ""
            if completed and completed[:4] < str(year):
                continue

            target = g.get("target_amount", 0)
            current = g.get("current_amount", 0)
            pct = round(current / target * 100, 1) if target > 0 else 0
            goals_progress.append({
                "name": g.get("name", ""),
                "target": target,
                "current": current,
                "pct_funded": pct,
                "on_track": g.get("trajectory") == "on_track",
                "status": g.get("status"),
            })
    except Exception as e:
        log.warning("Goals progress failed: %s", e)

    # ── 9. Contributions vs. Performance (P6-T05) ────────────────────
    contributions_vs_performance = []
    try:
        from dal.performance import decompose_contributions_vs_performance
        decomp = decompose_contributions_vs_performance(conn, year)
        for d in decomp:
            if d.get("has_sufficient_data"):
                contributions_vs_performance.append({
                    "account_id": d["account_id"],
                    "name": d["account_name"],
                    "net_contributions": d["net_contributions"],
                    "performance_gain": d["performance_gain"],
                    "total_gain": d["total_gain"],
                })
    except (ImportError, AttributeError) as e:
        log.warning("Contributions vs performance not available: %s", e)
    except Exception as e:
        log.warning("Contributions vs performance failed: %s", e)

    # Also merge into investment_performance if available
    if contributions_vs_performance:
        decomp_map = {d["account_id"]: d for d in contributions_vs_performance}
        for ip in investment_performance:
            dm = decomp_map.get(ip["account_id"])
            if dm:
                ip["contributions"] = dm["net_contributions"]
                ip["performance_gain"] = dm["performance_gain"]

    # ── 10. Lifestyle Flags (P6-T04) ─────────────────────────────────
    lifestyle_flags = []
    try:
        from dal.lifestyle import get_lifestyle_creep
        creep = get_lifestyle_creep(conn)
        if not creep.get("insufficient_data"):
            for c in creep.get("categories", []):
                if c.get("flagged"):
                    lifestyle_flags.append({
                        "category": c["category"],
                        "category_growth_pct": c["annualized_growth_pct"],
                        "income_growth_pct": c["income_growth_pct"],
                        "excess_pct": c["excess_pct"],
                    })
    except (ImportError, AttributeError) as e:
        log.warning("Lifestyle module not available: %s", e)
    except Exception as e:
        log.warning("Lifestyle flags failed: %s", e)

    # ── 11. Pre-Tax (Gross) Snapshot + Effective Tax Rate ────────────
    # Reads dal/payroll.py which sources from payroll_snapshots
    # (myPay RAS).  Both blocks share the same yearly aggregate.
    pre_tax: dict | None = None
    effective_tax = {
        "year": year,
        "gross_income": 0.0,
        "federal_tax": 0.0,
        "state_tax": 0.0,
        "total_tax": 0.0,
        "effective_rate_pct": 0.0,
        "months_covered": 0,
        "data_quality": "missing",
        "validation": None,
    }
    try:
        from dal.payroll import (
            get_gross_income_for_year,
            get_effective_tax_rate,
        )
        from dal.category_classifications import pre_tax_savings_rate

        gross_year = get_gross_income_for_year(conn, year, owner_id=owner_id)
        if gross_year["data_quality"] != "missing":
            tax_withheld = gross_year["federal_tax"] + gross_year["state_tax"]
            pre_tax = {
                "gross_income": gross_year["gross_pay"],
                "federal_tax": gross_year["federal_tax"],
                "state_tax": gross_year["state_tax"],
                "deductions": gross_year["deductions_total"],
                "net_pay": gross_year["net_pay"],
                "savings_rate_pct": pre_tax_savings_rate(
                    gross_year["gross_pay"], tax_withheld, total_spending
                ),
                "months_covered": gross_year["months_covered"],
                "data_quality": gross_year["data_quality"],
            }

        etr = get_effective_tax_rate(conn, year, owner_id=owner_id)
        # Preserve the validation slot for overlay_tax_documents to fill.
        etr["validation"] = None
        effective_tax = etr
    except Exception as e:
        log.warning("Pre-tax / effective-tax block failed: %s", e)

    return {
        "year": year,
        "status": "preliminary",
        "income_by_stream": income_by_stream,
        "total_income": round(total_income, 2),
        "total_spending": round(total_spending, 2),
        "savings_rate": savings_rate,
        "spending_by_category": spending_by_category,
        "net_worth_trajectory": net_worth_trajectory,
        "interest": interest,
        "investment_performance": investment_performance,
        "debt_progress": debt_progress,
        "recurring_changes": recurring_changes,
        "goals_progress": goals_progress,
        "contributions_vs_performance": contributions_vs_performance,
        "lifestyle_flags": lifestyle_flags,
        "pre_tax": pre_tax,
        "effective_tax": effective_tax,
    }


def get_yearly_wrapup(conn: sqlite3.Connection, year: int, owner_id: str | None = None) -> dict:
    """
    Assemble the annual wrap-up for the given calendar year.
    Attempts to overlay tax document figures if available (P6-T03).
    """
    wrapup = _build_preliminary(conn, year, owner_id=owner_id)
    wrapup = overlay_tax_documents(conn, year, wrapup)
    return wrapup


# ── P6-T03: Tax Document Integration ────────────────────────────────────────


def get_tax_doc_checklist(conn: sqlite3.Connection, year: int) -> dict:
    """
    Check which expected tax documents have been received for the year.
    """
    documents = []
    for parser_type, label in _EXPECTED_TAX_DOCS:
        row = conn.execute(
            """
            SELECT summary_json, committed_at, dropped_at
            FROM document_drops
            WHERE parser_type = ?
              AND json_extract(summary_json, '$.tax_year') = ?
              AND committed_at IS NOT NULL
            ORDER BY committed_at DESC LIMIT 1
            """,
            (parser_type, str(year)),
        ).fetchone()

        received = row is not None
        import json
        key_fields = json.loads(row["summary_json"]) if row and row["summary_json"] else None

        documents.append({
            "parser_type": parser_type,
            "label": label,
            "received": received,
            "committed_at": row["committed_at"] if row else None,
            "key_fields": key_fields,
        })

    all_received = all(d["received"] for d in documents)

    return {
        "year": year,
        "all_received": all_received,
        "documents": documents,
    }


def overlay_tax_documents(
    conn: sqlite3.Connection,
    year: int,
    wrapup: dict,
) -> dict:
    """
    Takes the preliminary wrapup dict and overlays authoritative tax
    document figures where available. Returns a modified copy.
    """
    wrapup = copy.deepcopy(wrapup)

    try:
        checklist = get_tax_doc_checklist(conn, year)
    except Exception as e:
        log.warning("Tax doc checklist failed (table may not exist): %s", e)
        wrapup["tax_doc_checklist"] = None
        wrapup["tax_overrides"] = {}
        return wrapup

    wrapup["tax_doc_checklist"] = checklist
    tax_overrides = {}
    received_count = sum(1 for d in checklist["documents"] if d["received"])

    # Build a map of received docs
    doc_map = {d["parser_type"]: d for d in checklist["documents"] if d["received"]}

    # ── DFAS 1099-R ──────────────────────────────────────────────────
    if "dfas_1099r" in doc_map:
        fields = doc_map["dfas_1099r"]["key_fields"] or {}
        gross = fields.get("gross_distribution")
        if gross is not None:
            for stream in wrapup.get("income_by_stream", []):
                if stream["stream"] == "Military Pension":
                    old_val = stream["total"]
                    stream["total"] = gross
                    tax_overrides["military_pension_gross"] = {
                        "preliminary": old_val,
                        "authoritative": gross,
                        "source": "dfas_1099r",
                    }
                    break

        fed_tax = fields.get("federal_tax_withheld")
        if fed_tax is not None:
            wrapup["federal_tax_withheld"] = fed_tax
            tax_overrides["federal_tax_withheld"] = {
                "preliminary": None,
                "authoritative": fed_tax,
                "source": "dfas_1099r",
            }
        state_tax = fields.get("state_tax_withheld")
        if state_tax is not None:
            wrapup["state_tax_withheld"] = state_tax
            tax_overrides["state_tax_withheld"] = {
                "preliminary": None,
                "authoritative": state_tax,
                "source": "dfas_1099r",
            }

        # Cross-check the payroll_snapshots federal-tax sum against the
        # authoritative 1099-R figure.  Any drift > $1 is surfaced as a
        # `validation` block on `effective_tax` for the UI to flag.
        eff = wrapup.get("effective_tax")
        if eff and isinstance(eff, dict) and fed_tax is not None:
            payroll_fed = float(eff.get("federal_tax") or 0.0)
            delta = round(float(fed_tax) - payroll_fed, 2)
            eff["validation"] = {
                "source": "dfas_1099r",
                "federal_tax_1099r": float(fed_tax),
                "federal_tax_payroll": payroll_fed,
                "matches": abs(delta) <= 1.0,
                "delta": delta,
            }

    # ── Fidelity 1099 ────────────────────────────────────────────────
    if "fidelity_1099" in doc_map:
        fields = doc_map["fidelity_1099"]["key_fields"] or {}
        for ip in wrapup.get("investment_performance", []):
            if "fidelity" in (ip.get("name", "") + ip.get("account_id", "")).lower():
                ip["investment_income"] = {
                    "ordinary_dividends": fields.get("ordinary_dividends"),
                    "qualified_dividends": fields.get("qualified_dividends"),
                    "capital_gain_distributions": fields.get("capital_gain_distributions"),
                    "total_proceeds": fields.get("total_proceeds"),
                    "total_cost_basis": fields.get("total_cost_basis"),
                }
                break

    # ── Acorns 1099 ──────────────────────────────────────────────────
    if "acorns_1099" in doc_map:
        fields = doc_map["acorns_1099"]["key_fields"] or {}
        for ip in wrapup.get("investment_performance", []):
            if "acorns" in (ip.get("name", "") + ip.get("account_id", "")).lower():
                ip["investment_income"] = {
                    "ordinary_dividends": fields.get("ordinary_dividends"),
                    "qualified_dividends": fields.get("qualified_dividends"),
                    "capital_gain_distributions": fields.get("capital_gain_distributions"),
                    "total_proceeds": fields.get("total_proceeds"),
                    "total_cost_basis": fields.get("total_cost_basis"),
                }
                break

    # ── Affirm 1099-INT ──────────────────────────────────────────────
    if "affirm_1099int" in doc_map:
        fields = doc_map["affirm_1099int"]["key_fields"] or {}
        interest_income = fields.get("interest_income")
        if interest_income is not None:
            old_earned = wrapup.get("interest", {}).get("total_earned", 0)
            wrapup["interest"]["total_earned"] = interest_income
            wrapup["interest"]["net_cost"] = wrapup["interest"].get("total_paid", 0) - interest_income
            tax_overrides["interest_earned"] = {
                "preliminary": old_earned,
                "authoritative": interest_income,
                "source": "affirm_1099int",
            }

    # ── NFCU 1098 ────────────────────────────────────────────────────
    if "nfcu_1098" in doc_map:
        fields = doc_map["nfcu_1098"]["key_fields"] or {}
        mtg_interest = fields.get("mortgage_interest_received")
        if mtg_interest is not None:
            old_paid = wrapup.get("interest", {}).get("total_paid", 0)
            wrapup["interest"]["total_paid"] = mtg_interest
            wrapup["interest"]["net_cost"] = mtg_interest - wrapup["interest"].get("total_earned", 0)
            tax_overrides["mortgage_interest_paid"] = {
                "preliminary": old_paid,
                "authoritative": mtg_interest,
                "source": "nfcu_1098",
            }
        mtg_insurance = fields.get("mortgage_insurance_premiums")
        if mtg_insurance is not None:
            wrapup["interest"]["mortgage_insurance_premiums"] = mtg_insurance
        prop_taxes = fields.get("property_taxes")
        if prop_taxes is not None:
            wrapup["interest"]["property_taxes"] = prop_taxes

    # ── Set status ───────────────────────────────────────────────────
    if received_count >= len(_EXPECTED_TAX_DOCS):
        wrapup["status"] = "final"
    elif received_count > 0:
        wrapup["status"] = "revised"
    # else remains "preliminary"

    wrapup["tax_overrides"] = tax_overrides
    return wrapup
