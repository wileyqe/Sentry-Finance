"""Reporting, data export, forecasting, and metrics endpoints."""

import sqlite3
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response
from typing import Optional
from pydantic import BaseModel

from dal.database import get_db
from backend.events import is_refresh_active
from dal.derived import get_summary_metrics, compute_emergency_fund_months, compute_dti_ratio, compute_interest_cost, compute_net_worth_velocity
from dal.forecasting import get_cash_flow_forecast, build_seasonal_income_model
from dal.reports import (
    get_spending_by_category,
    get_cash_flow_report,
    get_net_worth_history,
    get_category_trend,
    export_transactions_csv,
    get_period_summary,
    get_flow_data,
    get_merchant_list,
    get_merchant_flow_data,
    get_spending_comparison,
    get_accountability,
)
from dal.credit_scores import get_latest_credit_scores, get_credit_score_history
from dal.vehicles import list_vehicles, get_vehicle_equity_history

router = APIRouter(tags=["reports"])


# ── Pydantic Models ──────────────────────────────────────────────────────────


class ScenarioEvent(BaseModel):
    type: str  # income_change, expense_change, one_time, loan_payoff, investment_return
    description: str = ""
    amount: float = 0.0
    month: Optional[str] = None        # For one_time and loan_payoff
    start_month: Optional[str] = None  # For ongoing changes
    end_month: Optional[str] = None    # For temporary changes
    account_id: Optional[str] = None   # For loan_payoff
    annual_rate: Optional[float] = None  # For investment_return
    affects: str = "liquid_balance"     # For one_time: liquid_balance or net_worth


class ScenarioRequest(BaseModel):
    events: list[ScenarioEvent]
    months: int = 60
    use_seasonal: bool = True


# ── Metrics Endpoint ─────────────────────────────────────────────────────────


@router.get("/api/metrics/summary")
def metrics_summary(view: str = Query("ours")):
    """Get derived summary metrics, optionally scoped to a view."""
    with get_db() as conn:
        metrics = get_summary_metrics(conn)
    return {"metrics": metrics, "view": view, "refresh_in_progress": is_refresh_active()}


@router.get("/api/metrics/emergency-fund")
def get_emergency_fund(owner_id: Optional[str] = Query(None)):
    with get_db() as conn:
        return compute_emergency_fund_months(conn, owner_id=owner_id)


@router.get("/api/metrics/dti")
def get_dti_ratio(months: int = Query(12, ge=1, le=60)):
    with get_db() as conn:
        return compute_dti_ratio(conn, months=months)


@router.get("/api/metrics/interest-cost")
def get_interest_cost():
    with get_db() as conn:
        return compute_interest_cost(conn)


@router.get("/api/metrics/net-worth-velocity")
def get_net_worth_velocity(owner_id: Optional[str] = Query(None)):
    with get_db() as conn:
        return compute_net_worth_velocity(conn, owner_id=owner_id)


@router.get("/api/accounts/{account_id}/details")
def account_details(account_id: str):
    """Return loan_details fields for an account (APR, APY, etc.)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT field_name, field_value, as_of
               FROM loan_details
               WHERE account_id = ?
               ORDER BY as_of DESC""",
            (account_id,),
        ).fetchall()

    # Deduplicate: latest value per field
    seen = {}
    for r in rows:
        if r["field_name"] not in seen:
            seen[r["field_name"]] = {
                "value": r["field_value"],
                "as_of": r["as_of"],
            }

    return {"account_id": account_id, "details": seen}


@router.get("/api/metrics/credit-scores")
def get_credit_scores(
    history_months: Optional[int] = None,
    owner_id: Optional[str] = Query(None),
):
    """Return the latest credit scores, and optionally history."""
    with get_db() as conn:
        latest = get_latest_credit_scores(conn, owner_id=owner_id)

        result = {"latest": latest}
        if history_months:
            result["history"] = get_credit_score_history(
                conn, months=history_months, owner_id=owner_id
            )

        return result


@router.get("/api/vehicles")
def get_vehicles(owner_id: Optional[str] = Query(None)):
    """List all tracked vehicle assets, optionally scoped to one owner."""
    with get_db() as conn:
        try:
            return list_vehicles(conn, owner_id=owner_id)
        except sqlite3.OperationalError:
            return []


@router.get("/api/metrics/vehicle-equity")
def get_vehicle_equity(
    months: int = Query(12, ge=1, le=120),
    owner_id: Optional[str] = Query(None),
):
    """Return historical vehicle equity over time, optionally per owner."""
    with get_db() as conn:
        try:
            return get_vehicle_equity_history(conn, months, owner_id=owner_id)
        except sqlite3.OperationalError:
            return []


# ── Forecast Endpoint ────────────────────────────────────────────────────────


@router.get("/api/forecast")
def cash_flow_forecast(
    months: int = Query(6, ge=1, le=24),
    history_months: int = Query(3, ge=1, le=12),
    seasonal: bool = Query(False, description="Use seasonal income model"),
):
    """Project cash flow for the next N months.

    Uses recurring baselines + rolling historical average to project
    monthly income, spending, net, and running balance.
    Pass seasonal=true for per-month income variation.
    """
    with get_db() as conn:
        forecast = get_cash_flow_forecast(
            conn, months=months, history_months=history_months,
            use_seasonal=seasonal,
        )
    forecast["refresh_in_progress"] = is_refresh_active()
    return forecast


# ── Seasonal Income Model (P3-T01) ──────────────────────────────────────────


@router.get("/api/income/seasonal-model")
def seasonal_income_model(
    lookback_years: int = Query(2, ge=1, le=5),
):
    """Return the 4-stream seasonal income model.

    Streams: pension (flat), disability (flat), education (episodic),
    officiating (seasonal). Excludes lump-sum non-recurring income and
    outliers.
    """
    with get_db() as conn:
        model = build_seasonal_income_model(conn, lookback_years=lookback_years)
    return model


# ── Scenario Projection (P3-T03) ────────────────────────────────────────────


@router.post("/api/scenarios/project")
def scenario_project(body: ScenarioRequest):
    """Project a what-if scenario over the baseline trajectory.

    Accepts a list of events (income changes, expense changes, one-time
    transactions, loan payoffs, investment return overrides) and returns
    both baseline and scenario month-by-month projections.
    """
    from dal.scenarios import project_scenario

    events_raw = [e.model_dump() for e in body.events]
    with get_db() as conn:
        result = project_scenario(
            conn,
            events=events_raw,
            months=body.months,
            use_seasonal=body.use_seasonal,
        )
    return result


# ── Report Endpoints ─────────────────────────────────────────────────────────


@router.get("/api/reports/spending")
def report_spending(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    account_id: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
):
    """Spending breakdown by category for a date range."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_spending_by_category(conn, start_date, end_date, account_ids, owner_id=owner_id)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "categories": data,
        "total": round(sum(c["total_spent"] for c in data), 2),
        "refresh_in_progress": is_refresh_active(),
    }


@router.get("/api/reports/cash-flow")
def report_cash_flow(
    months: int = Query(12, ge=1, le=120),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD; preferred over months"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD; preferred over months"),
    account_id: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
):
    """Monthly income vs. spending vs. net for a date window.

    Pass explicit ``start_date`` / ``end_date`` (anchored in local time
    on the frontend) to avoid the UTC drift inherent in the legacy
    ``months`` int.  When both are supplied, dates win.
    """
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_cash_flow_report(
            conn,
            months=months,
            account_ids=account_ids,
            owner_id=owner_id,
            start_date=start_date,
            end_date=end_date,
        )
    return {"months": data, "count": len(data), "refresh_in_progress": is_refresh_active()}


@router.get("/api/reports/net-worth-history")
def report_net_worth_history(
    months: int = Query(24, ge=1, le=120),
    owner_id: Optional[str] = Query(None),
):
    """Monthly net worth history: assets, liabilities, net."""
    with get_db() as conn:
        data = get_net_worth_history(conn, months=months, owner_id=owner_id)
    return {"history": data, "count": len(data), "refresh_in_progress": is_refresh_active()}


@router.get("/api/reports/category-trend")
def report_category_trend(
    category: str = Query(...),
    months: int = Query(12, ge=1, le=60),
    account_id: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
):
    """Monthly spending trend for a specific category."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_category_trend(conn, category, months=months, account_ids=account_ids, owner_id=owner_id)
    return {"category": category, "trend": data, "refresh_in_progress": is_refresh_active()}


@router.get("/api/reports/summary")
def report_period_summary(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    account_id: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
):
    """High-level period summary: income, spending, net, top categories."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        summary = get_period_summary(conn, start_date, end_date, account_ids, owner_id=owner_id)
    summary["refresh_in_progress"] = is_refresh_active()
    return summary


@router.get("/api/reports/flow")
def report_flow(
    months: int = Query(1, ge=1, le=120),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD; preferred over months"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD; preferred over months"),
    account_id: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
):
    """Income + spending by category for Sankey diagram.

    Pass explicit ``start_date`` / ``end_date`` to avoid UTC drift.
    """
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_flow_data(
            conn,
            months=months,
            account_ids=account_ids,
            owner_id=owner_id,
            start_date=start_date,
            end_date=end_date,
        )
    data["refresh_in_progress"] = is_refresh_active()
    return data


@router.get("/api/reports/accountability")
def report_accountability(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    owner_id: Optional[str] = Query(None),
):
    """Phase 14 Phase D — accountability scorecard.

    Computes the identity
    ``Δ NetWorth = (Dollars in) − (Dollars spent) ± Market Δ ± RE Δ ±
    Vehicle Δ + unexplained`` and returns the percentage of the period's
    net-worth change accounted for, plus a list of named drift sources
    for the drilldown modal.
    """
    with get_db() as conn:
        data = get_accountability(
            conn,
            start_date=start_date,
            end_date=end_date,
            owner_id=owner_id,
        )
    data["refresh_in_progress"] = is_refresh_active()
    return data


@router.get("/api/reports/merchants")
def report_merchants(
    months: int = Query(6, ge=1, le=120),
    limit: int = Query(50, ge=1, le=200),
    account_id: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
):
    """Ranked merchant list with per-month totals for sparklines."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_merchant_list(conn, months=months, limit=limit, account_ids=account_ids, owner_id=owner_id)
    return {"merchants": data, "months": months, "count": len(data), "refresh_in_progress": is_refresh_active()}


@router.get("/api/reports/merchant-flow")
def report_merchant_flow(
    months: int = Query(6, ge=1, le=120),
    merchants: str = Query("", description="Comma-separated canonical merchant names"),
    account_id: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
):
    """Sankey-shaped income + merchant spending data for Custom Reports."""
    selected = [m.strip() for m in merchants.split(",") if m.strip()] if merchants else None
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_merchant_flow_data(
            conn, months=months, selected_merchants=selected, account_ids=account_ids, owner_id=owner_id
        )
    data["refresh_in_progress"] = is_refresh_active()
    return data


@router.get("/api/export/transactions")
def export_transactions(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    account_id: Optional[str] = Query(None),
    institution_id: Optional[str] = Query(None),
):
    """Export transactions as CSV."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        csv_content = export_transactions_csv(
            conn,
            start_date=start_date,
            end_date=end_date,
            account_ids=account_ids,
            institution_id=institution_id,
        )
    filename = f"sentry_transactions_{start_date or 'all'}_to_{end_date or 'today'}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/reports/spending-comparison")
def report_spending_comparison(
    reference_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    timeframe: str = Query("month_vs_last_month", description="Comparison timeframe"),
    account_id: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
):
    """Cumulative daily spending for a given month vs the previous month."""
    account_ids = [account_id] if account_id else None
    
    # default to today's date if not provided
    if not reference_date:
        from datetime import datetime, timezone
        reference_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with get_db() as conn:
        data = get_spending_comparison(conn, reference_date, timeframe=timeframe, account_ids=account_ids, owner_id=owner_id)
    
    return {"data": data, "refresh_in_progress": is_refresh_active()}


# ── Income Attribution Rules ─────────────────────────────────────────────────


@router.get("/api/attribution-rules")
def list_attribution_rules():
    """List all income attribution rules (active and inactive)."""
    from dal.attribution import get_attribution_rules
    with get_db() as conn:
        rules = get_attribution_rules(conn)
    return {"rules": rules, "count": len(rules)}


class AttributionRuleCreate(BaseModel):
    rule_name: str
    match_category: str
    schedule_type: str = "monthly_fixed"
    target_day: int = 1
    lookahead_days: int = 5
    match_direction: str = "Credit"
    owner: str = "self"


@router.post("/api/attribution-rules")
def create_attribution_rule_endpoint(body: AttributionRuleCreate):
    """Create a new income attribution rule."""
    from dal.attribution import create_attribution_rule
    with get_db() as conn:
        rule_id = create_attribution_rule(
            conn,
            rule_name=body.rule_name,
            match_category=body.match_category,
            schedule_type=body.schedule_type,
            target_day=body.target_day,
            lookahead_days=body.lookahead_days,
            match_direction=body.match_direction,
            owner=body.owner,
        )
        conn.commit()
    return {"id": rule_id, "status": "created"}


@router.delete("/api/attribution-rules/{rule_id}")
def delete_attribution_rule_endpoint(rule_id: int):
    """Delete an income attribution rule."""
    from dal.attribution import delete_attribution_rule
    with get_db() as conn:
        deleted = delete_attribution_rule(conn, rule_id)
        conn.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return {"status": "deleted"}


@router.post("/api/attribution/backfill")
def backfill_attribution_endpoint():
    """One-time backfill: stamp all historical transactions matching rules."""
    from dal.attribution import backfill_attribution
    with get_db() as conn:
        stats = backfill_attribution(conn)
        conn.commit()
    return stats


# ── Lifestyle Creep (P6-T04) ─────────────────────────────────────────────────


@router.get("/api/lifestyle/creep")
def lifestyle_creep(
    lookback_years: int = Query(2, ge=2, le=5),
    flag_threshold_pct: float = Query(5.0, ge=0, le=50),
):
    """
    Returns lifestyle creep analysis across spending categories.

    Query params:
      lookback_years (int, default 2): Rolling 12-month periods to compare.
      flag_threshold_pct (float, default 5.0): Excess growth % to flag.
    """
    from dal.lifestyle import get_lifestyle_creep
    with get_db() as conn:
        return get_lifestyle_creep(
            conn,
            lookback_years=max(2, min(lookback_years, 5)),
            flag_threshold_pct=flag_threshold_pct,
        )


# ── Monthly Review (P6-T01) ──────────────────────────────────────────────────


@router.get("/api/review/monthly")
def monthly_review(
    month: str | None = None,
    owner_id: Optional[str] = Query(None),
):
    """
    Returns the assembled monthly review for the given month.
    Defaults to the prior calendar month if no month is specified.
    Month format: YYYY-MM.
    """
    if month is None:
        from datetime import date as _date
        from dateutil.relativedelta import relativedelta
        today = _date.today()
        first_of_month = today.replace(day=1)
        prior = first_of_month - relativedelta(months=1)
        month = prior.strftime("%Y-%m")

    from dal.review import get_monthly_review
    with get_db() as conn:
        return get_monthly_review(conn, month, owner_id=owner_id)


# ── Yearly Wrap-Up (P6-T02 / P6-T03) ─────────────────────────────────────────


@router.get("/api/review/yearly")
def yearly_review(
    year: int | None = None,
    owner_id: Optional[str] = Query(None),
):
    """
    Returns the assembled yearly wrap-up for the given calendar year.
    Defaults to the prior calendar year.
    """
    if year is None:
        from datetime import date as _date
        year = _date.today().year - 1

    from dal.yearly_wrapup import get_yearly_wrapup
    with get_db() as conn:
        return get_yearly_wrapup(conn, year, owner_id=owner_id)


@router.get("/api/review/yearly/tax-checklist")
def yearly_tax_checklist(year: int | None = None):
    """
    Returns the tax document receipt checklist for the given year.
    """
    if year is None:
        from datetime import date as _date
        year = _date.today().year - 1

    from dal.yearly_wrapup import get_tax_doc_checklist
    with get_db() as conn:
        return get_tax_doc_checklist(conn, year)
