"""Reporting, data export, forecasting, and metrics endpoints."""

from fastapi import APIRouter, Query
from fastapi.responses import Response
from typing import Optional

from dal.database import get_db
from dal.derived import get_summary_metrics
from dal.forecasting import get_cash_flow_forecast
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
)

router = APIRouter(tags=["reports"])


# ── Metrics Endpoint ─────────────────────────────────────────────────────────


@router.get("/api/metrics/summary")
def metrics_summary(view: str = Query("ours")):
    """Get derived summary metrics, optionally scoped to a view."""
    with get_db() as conn:
        metrics = get_summary_metrics(conn)
    return {"metrics": metrics, "view": view}


# ── Forecast Endpoint ────────────────────────────────────────────────────────


@router.get("/api/forecast")
def cash_flow_forecast(
    months: int = Query(6, ge=1, le=24),
    history_months: int = Query(3, ge=1, le=12),
):
    """Project cash flow for the next N months.

    Uses recurring baselines + rolling historical average to project
    monthly income, spending, net, and running balance.
    """
    with get_db() as conn:
        forecast = get_cash_flow_forecast(
            conn, months=months, history_months=history_months
        )
    return forecast


# ── Report Endpoints ─────────────────────────────────────────────────────────


@router.get("/api/reports/spending")
def report_spending(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    account_id: Optional[str] = Query(None),
):
    """Spending breakdown by category for a date range."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_spending_by_category(conn, start_date, end_date, account_ids)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "categories": data,
        "total": round(sum(c["total_spent"] for c in data), 2),
    }


@router.get("/api/reports/cash-flow")
def report_cash_flow(
    months: int = Query(12, ge=1, le=120),
    account_id: Optional[str] = Query(None),
):
    """Monthly income vs. spending vs. net for the last N months."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_cash_flow_report(conn, months=months, account_ids=account_ids)
    return {"months": data, "count": len(data)}


@router.get("/api/reports/net-worth-history")
def report_net_worth_history(
    months: int = Query(24, ge=1, le=120),
):
    """Monthly net worth history: assets, liabilities, net."""
    with get_db() as conn:
        data = get_net_worth_history(conn, months=months)
    return {"history": data, "count": len(data)}


@router.get("/api/reports/category-trend")
def report_category_trend(
    category: str = Query(...),
    months: int = Query(12, ge=1, le=60),
    account_id: Optional[str] = Query(None),
):
    """Monthly spending trend for a specific category."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_category_trend(conn, category, months=months, account_ids=account_ids)
    return {"category": category, "trend": data}


@router.get("/api/reports/summary")
def report_period_summary(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    account_id: Optional[str] = Query(None),
):
    """High-level period summary: income, spending, net, top categories."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        summary = get_period_summary(conn, start_date, end_date, account_ids)
    return summary


@router.get("/api/reports/flow")
def report_flow(
    months: int = Query(1, ge=1, le=120),
    account_id: Optional[str] = Query(None),
):
    """Income + spending by category for Sankey diagram."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_flow_data(conn, months=months, account_ids=account_ids)
    return data


@router.get("/api/reports/merchants")
def report_merchants(
    months: int = Query(6, ge=1, le=120),
    limit: int = Query(50, ge=1, le=200),
    account_id: Optional[str] = Query(None),
):
    """Ranked merchant list with per-month totals for sparklines."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_merchant_list(conn, months=months, limit=limit, account_ids=account_ids)
    return {"merchants": data, "months": months, "count": len(data)}


@router.get("/api/reports/merchant-flow")
def report_merchant_flow(
    months: int = Query(6, ge=1, le=120),
    merchants: str = Query("", description="Comma-separated canonical merchant names"),
    account_id: Optional[str] = Query(None),
):
    """Sankey-shaped income + merchant spending data for Custom Reports."""
    selected = [m.strip() for m in merchants.split(",") if m.strip()] if merchants else None
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_merchant_flow_data(
            conn, months=months, selected_merchants=selected, account_ids=account_ids
        )
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
