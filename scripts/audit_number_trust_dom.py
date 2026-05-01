"""Browser DOM audit for first-pass number-trust values.

This script extends the raw-fact/API/second-language audit with a selector-
backed rendered UI check for every registered value/view context on the
scoped number-trust pages (Dashboard, Transactions, Cash Flow, Reports,
Accounts, and Budgets).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import audit_number_trust as api_audit  # noqa: E402

REPORT_DIR = ROOT / "docs" / "audits" / "number-trust" / "reports"
DEFAULT_FRONTEND_URL = "http://127.0.0.1:1420"

VIEW_TO_FRONTEND_VALUE = {
    "household": "ours",
    "owner.quintin": "quintin",
    "owner.amy": "amy",
}
ROUTE_ORDER = [
    "/dashboard",
    "/transactions",
    "/cash-flow",
    "/reports",
    "/accounts",
    "/budgets",
    "/review/monthly",
    "/review/yearly",
]
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WRAPUP_STATUS_LABELS = {
    "preliminary": "Preliminary",
    "revised": "Revised",
    "final": "Final",
}


@dataclass(frozen=True)
class DomExpectation:
    id: str
    check_id: str
    value_id: str | None
    route: str
    view_state_id: str
    label: str
    expected_text: str
    selector: str | None = None
    setup: str | None = None
    selector_all: bool = False


def format_currency(amount: float | int | None) -> str:
    if amount is None:
        amount = 0
    value = float(amount)
    formatted = f"{abs(value):,.2f}"
    if value < 0:
        return f"-${formatted}"
    return f"${formatted}"


def format_signed_currency(amount: float | int | None) -> str:
    value = float(amount or 0)
    prefix = "+" if value >= 0 else ""
    return f"{prefix}{format_currency(value)}"


def format_percent(value: float | int | None) -> str:
    return f"{float(value or 0):.1f}%"


def format_percent_zero(value: float | int | None) -> str:
    return f"{float(value or 0):.0f}%"


def format_signed_percent(value: float | int | None) -> str:
    number = float(value or 0)
    prefix = "+" if number >= 0 else ""
    return f"{prefix}{number:.1f}%"


def format_review_signed_percent(value: float | int | None) -> str:
    """Match the page's `fmtPct` helper: only positive values get a '+' prefix."""
    if value is None:
        return "—"
    number = float(value)
    prefix = "+" if number > 0 else ""
    return f"{prefix}{number:.1f}%"


def format_compact_currency(amount: float | int | None) -> str:
    """Mirror frontend/src/lib/formatCompactCurrency.ts."""
    if amount is None:
        return "$0"
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return "$0"
    abs_value = abs(value)
    sign = "-" if value < 0 else ""
    if abs_value >= 1_000_000_000:
        return f"{sign}${abs_value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{sign}${abs_value / 1_000_000:.1f}M"
    if abs_value >= 10_000:
        return f"{sign}${abs_value / 1_000:.1f}K"
    return f"{sign}${int(round(abs_value)):,}"


def format_pretax_negative_compact(amount: float | int | None) -> str:
    """Pre-tax federal/state cells render as '−$X' — minus prefix on the absolute value."""
    if amount is None or float(amount) == 0:
        return f"−{format_compact_currency(0)}"
    return f"−{format_compact_currency(abs(float(amount)))}"


def format_review_signed_currency(amount: float | int | None) -> str:
    """Hero/cash-surplus pattern: explicit '+'/'−' prefix on the absolute value."""
    value = float(amount or 0)
    if value < 0:
        return f"−{format_currency(abs(value))}"
    return f"+{format_currency(abs(value))}"


def format_reports_signed_cents(cents: float | int | None) -> str:
    value = float(cents or 0)
    prefix = "-" if value < 0 else "+" if value > 0 else ""
    return f"{prefix}{format_currency(abs(value) / 100)}"


def format_chart_point(point: dict[str, Any]) -> str:
    net = float(point.get("net") or 0)
    return (
        f"{point.get('label')}: income {format_currency(point.get('income'))}; "
        f"expenses {format_currency(point.get('spending'))}; "
        f"net {'+' if net >= 0 else ''}{format_currency(net)}; "
        f"savings {format_percent(point.get('savings_rate'))}"
    )


def format_freshness_states(rows: list[dict[str, Any]]) -> str:
    return " | ".join(
        f"{row.get('institution_id')}:{row.get('staleness')}"
        for row in sorted(rows, key=lambda item: str(item.get("institution_id")))
    )


def join_text(parts: list[str]) -> str:
    return " | ".join(parts)


def format_transaction_date(iso_date: str) -> str:
    year, month, day = iso_date.split("-")
    return f"{MONTH_ABBR[int(month) - 1]} {int(day)}, {year}"


def format_short_date(iso_date: str | None) -> str:
    if not iso_date:
        return "Pending"
    year, month, day = iso_date.split("-")
    return f"{int(month)}/{int(day)}/{year}"


def normalize_text(text: str) -> str:
    normalized = (
        text.replace("\xa0", " ")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _test_id_part(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "unknown").lower()).strip("-")
    return slug or "unknown"


def _credit_score_selector(score: dict[str, Any]) -> str:
    source = score.get("institution_id") or score.get("source")
    score_type = score.get("score_type")
    return f"[data-testid='dashboard-credit-score-{_test_id_part(source)}-{_test_id_part(score_type)}']"


def _scoped_id(check_id: str, view_state_id: str) -> str:
    return f"{check_id}@{view_state_id}"


def _checks_by_id(api_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {check["id"]: check for check in api_report.get("checks") or []}


def _actual(checks: dict[str, dict[str, Any]], check_id: str, view_state_id: str) -> Any:
    check = checks.get(_scoped_id(check_id, view_state_id))
    if not check:
        return None
    return check.get("actual")


def _add(
    expectations: list[DomExpectation],
    *,
    check_id: str,
    value_id: str | None = None,
    route: str,
    view_state_id: str,
    field: str,
    label: str,
    expected_text: str | None,
    selector: str | None = None,
    setup: str | None = None,
    selector_all: bool = False,
) -> None:
    if expected_text is None:
        return
    expectations.append(
        DomExpectation(
            id=f"{check_id}.{field}@{view_state_id}",
            check_id=check_id,
            value_id=value_id,
            route=route,
            view_state_id=view_state_id,
            label=label,
            expected_text=expected_text,
            selector=selector,
            setup=setup,
            selector_all=selector_all,
        )
    )


def build_dom_expectations(api_report: dict[str, Any]) -> list[DomExpectation]:
    """Build the first selector-backed DOM proof slice from audited API values."""

    checks = _checks_by_id(api_report)
    view_states = [
        state["id"]
        for state in (api_report.get("registry") or {}).get("view_states", [])
        if state.get("id") in VIEW_TO_FRONTEND_VALUE
    ]
    expectations: list[DomExpectation] = []

    for view_state_id in view_states:
        # Dashboard: top KPI row and credit-score state.
        net_worth = _actual(checks, "dashboard.net_worth.latest", view_state_id)
        _add(
            expectations,
            check_id="dashboard.net_worth.latest",
            value_id="dashboard.net_worth.latest",
            route="/dashboard",
            view_state_id=view_state_id,
            field="net_worth",
            label="Dashboard net worth",
            expected_text=format_currency((net_worth or {}).get("net_worth")),
            selector="[data-testid='dashboard-net-worth-latest']",
        )

        net_worth_details = _actual(checks, "dashboard.net_worth.details", view_state_id) or {}
        net_worth_velocity = _actual(checks, "dashboard.net_worth.velocity", view_state_id) or {}
        has_net_worth_chart_delta = len(net_worth_velocity.get("history") or []) > 1
        for field, value_id, label, formatter, selector in [
            ("assets", "dashboard.net_worth.assets", "Dashboard net worth assets", format_currency, "[data-testid='dashboard-net-worth-assets']"),
            (
                "liabilities",
                "dashboard.net_worth.liabilities",
                "Dashboard net worth liabilities",
                lambda value: format_currency(abs(float(value or 0))),
                "[data-testid='dashboard-net-worth-liabilities']",
            ),
            ("velocity_amount", "dashboard.net_worth.velocity_amount", "Dashboard net worth monthly pace", lambda value: f"{format_currency(value)}/mo", "[data-testid='dashboard-net-worth-velocity-amount']"),
            ("delta_amount", "dashboard.net_worth.delta_amount", "Dashboard net worth change", format_signed_currency, "[data-testid='dashboard-net-worth-delta-amount']"),
            ("delta_percent", "dashboard.net_worth.delta_percent", "Dashboard net worth change percent", format_signed_percent, "[data-testid='dashboard-net-worth-delta-percent']"),
        ]:
            if field in {"velocity_amount", "delta_amount", "delta_percent"} and not has_net_worth_chart_delta:
                continue
            _add(
                expectations,
                check_id="dashboard.net_worth.details",
                value_id=value_id,
                route="/dashboard",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=formatter(net_worth_details.get(field)),
                selector=selector,
                setup="dashboard_net_worth_details_open" if field in {"assets", "liabilities"} else None,
            )
        if not has_net_worth_chart_delta:
            for field, value_id, label, expected_text, selector in [
                ("velocity_amount", "dashboard.net_worth.velocity_amount", "Dashboard net worth monthly pace empty state", "$0.00/mo", "[data-testid='dashboard-net-worth-velocity-amount']"),
                ("delta_amount", "dashboard.net_worth.delta_amount", "Dashboard net worth change empty state", "+$0.00", "[data-testid='dashboard-net-worth-delta-amount']"),
                ("delta_percent", "dashboard.net_worth.delta_percent", "Dashboard net worth change percent empty state", "+0.0%", "[data-testid='dashboard-net-worth-delta-percent']"),
            ]:
                _add(
                    expectations,
                    check_id="dashboard.net_worth.details",
                    value_id=value_id,
                    route="/dashboard",
                    view_state_id=view_state_id,
                    field=f"{field}_empty",
                    label=label,
                    expected_text=expected_text,
                    selector=selector,
                )

        freshness = _actual(checks, "dashboard.freshness.state_labels", view_state_id) or []
        _add(
            expectations,
            check_id="dashboard.freshness.state_labels",
            value_id="dashboard.freshness.state_labels",
            route="/dashboard",
            view_state_id=view_state_id,
            field="state_labels",
            label="Dashboard freshness state labels",
            expected_text=format_freshness_states(freshness),
            selector="[data-testid='dashboard-freshness-state-labels']",
        )

        monthly_flow = _actual(checks, "dashboard.monthly_net_flow", view_state_id) or {}
        _add(
            expectations,
            check_id="dashboard.monthly_net_flow",
            value_id="dashboard.monthly_net_flow",
            route="/dashboard",
            view_state_id=view_state_id,
            field="net",
            label="Dashboard monthly net flow",
            expected_text=format_signed_currency(monthly_flow.get("net")),
            selector="[data-testid='dashboard-monthly-net-flow']",
        )
        _add(
            expectations,
            check_id="dashboard.monthly_net_flow",
            value_id="dashboard.monthly_net_flow.savings_rate",
            route="/dashboard",
            view_state_id=view_state_id,
            field="savings_rate",
            label="Dashboard savings rate",
            expected_text=format_percent(monthly_flow.get("savings_rate")),
            selector="[data-testid='dashboard-monthly-savings-rate']",
        )

        dti_latest = _actual(checks, "cash_flow.dti.latest", view_state_id)
        if dti_latest:
            _add(
                expectations,
                check_id="cash_flow.dti.latest",
                value_id="dashboard.monthly_net_flow.dti",
                route="/dashboard",
                view_state_id=view_state_id,
                field="dashboard_dti",
                label="Dashboard DTI pill",
                expected_text=format_percent(dti_latest.get("dti_ratio")),
                selector="[data-testid='dashboard-monthly-dti']",
            )
        else:
            _add(
                expectations,
                check_id="cash_flow.dti.latest",
                value_id="dashboard.monthly_net_flow.dti",
                route="/dashboard",
                view_state_id=view_state_id,
                field="dashboard_dti_empty",
                label="Dashboard DTI empty state",
                expected_text="No DTI data",
                selector="[data-testid='dashboard-monthly-dti']",
            )
        if monthly_flow.get("net_debt_change") is not None and abs(float(monthly_flow.get("net_debt_change") or 0)) >= 10:
            _add(
                expectations,
                check_id="dashboard.monthly_net_flow",
                value_id="dashboard.monthly_net_flow.net_debt_change",
                route="/dashboard",
                view_state_id=view_state_id,
                field="net_debt_change",
                label="Dashboard net debt change",
                expected_text=format_signed_currency(monthly_flow.get("net_debt_change")),
                selector="[data-testid='dashboard-monthly-net-debt-change']",
            )
        else:
            _add(
                expectations,
                check_id="dashboard.monthly_net_flow",
                value_id="dashboard.monthly_net_flow.net_debt_change",
                route="/dashboard",
                view_state_id=view_state_id,
                field="net_debt_change_empty",
                label="Dashboard net debt change empty state",
                expected_text="+$0.00 debt",
                selector="[data-testid='dashboard-monthly-net-debt-change']",
            )

        runway = _actual(checks, "dashboard.emergency_runway", view_state_id) or {}
        if runway.get("months_of_runway") is not None:
            _add(
                expectations,
                check_id="dashboard.emergency_runway",
                value_id="dashboard.emergency_runway",
                route="/dashboard",
                view_state_id=view_state_id,
                field="months_of_runway",
                label="Dashboard emergency runway months",
                expected_text=f"{float(runway['months_of_runway']):.1f}",
                selector="[data-testid='dashboard-runway-months']",
            )
            _add(
                expectations,
                check_id="dashboard.emergency_runway",
                value_id=None,
                route="/dashboard",
                view_state_id=view_state_id,
                field="avg_monthly_spending",
                label="Dashboard runway average monthly spend",
                expected_text=format_currency(runway.get("avg_monthly_spending")),
                selector="[data-testid='dashboard-runway-avg-spend']",
            )
        else:
            _add(
                expectations,
                check_id="dashboard.emergency_runway",
                value_id="dashboard.emergency_runway",
                route="/dashboard",
                view_state_id=view_state_id,
                field="months_of_runway_empty",
                label="Dashboard emergency runway empty state",
                expected_text="—",
                selector="[data-testid='dashboard-runway-months']",
            )

        credit_scores = _actual(checks, "dashboard.credit_scores.latest", view_state_id) or []
        if credit_scores:
            for idx, score in enumerate(credit_scores[:2], start=1):
                _add(
                    expectations,
                    check_id="dashboard.credit_scores.latest",
                    value_id="dashboard.credit_scores.latest",
                    route="/dashboard",
                    view_state_id=view_state_id,
                    field=f"score_{idx}",
                    label="Dashboard credit score",
                    expected_text=str(score.get("score")),
                    selector=_credit_score_selector(score),
                )
        else:
            _add(
                expectations,
                check_id="dashboard.credit_scores.latest",
                value_id="dashboard.credit_scores.latest",
                route="/dashboard",
                view_state_id=view_state_id,
                field="empty_state",
                label="Dashboard credit-score empty state",
                expected_text="No scores available",
                selector="[data-testid='dashboard-credit-score-empty']",
            )

        rolling_latest = _actual(checks, "cash_flow.rolling.latest_month", view_state_id) or {}
        net_debt_change = rolling_latest.get("net_debt_change")
        if net_debt_change is not None and abs(float(net_debt_change or 0)) >= 10:
            _add(
                expectations,
                check_id="cash_flow.rolling.latest_month",
                value_id="dashboard.monthly_net_flow.net_debt_change",
                route="/dashboard",
                view_state_id=view_state_id,
                field="dashboard_net_debt_change",
                label="Dashboard net debt change",
                expected_text=format_signed_currency(net_debt_change),
                selector="[data-testid='dashboard-monthly-net-debt-change']",
            )

        spending = _actual(checks, "dashboard.spending.hero", view_state_id) or {}
        for field, value_id, label, formatter, selector in [
            ("current_month_total", "dashboard.spending.current_month_total", "Dashboard spending current month", format_currency, "[data-testid='dashboard-spending-current-month-total']"),
            ("delta_amount", "dashboard.spending.delta_amount", "Dashboard spending delta", lambda value: format_currency(abs(float(value or 0))), "[data-testid='dashboard-spending-delta-amount']"),
            ("delta_percent", "dashboard.spending.delta_percent", "Dashboard spending delta percent", lambda value: format_percent(abs(float(value or 0))), "[data-testid='dashboard-spending-delta-percent']"),
            ("projected_eom", "dashboard.spending.projected_eom", "Dashboard projected EOM spending", format_currency, "[data-testid='dashboard-spending-projected-eom']"),
            ("per_day", "dashboard.spending.per_day", "Dashboard spending per day", format_currency, "[data-testid='dashboard-spending-per-day']"),
        ]:
            _add(
                expectations,
                check_id="dashboard.spending.hero",
                value_id=value_id,
                route="/dashboard",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=formatter(spending.get(field)),
                selector=selector,
            )

        budget = _actual(checks, "dashboard.budget.summary", view_state_id) or {}
        for field, value_id, label, formatter, selector in [
            ("total_spent", "dashboard.budget.spent", "Dashboard budget spent", format_currency, "[data-testid='dashboard-budget-spent']"),
            ("total_budgeted", "dashboard.budget.total", "Dashboard budget total", format_currency, "[data-testid='dashboard-budget-total']"),
            ("total_remaining", "dashboard.budget.remaining", "Dashboard budget remaining", format_currency, "[data-testid='dashboard-budget-remaining']"),
            ("pct_used", "dashboard.budget.progress_percent", "Dashboard budget progress", format_percent_zero, "[data-testid='dashboard-budget-progress-percent']"),
        ]:
            _add(
                expectations,
                check_id="dashboard.budget.summary",
                value_id=value_id,
                route="/dashboard",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=formatter(budget.get(field)),
                selector=selector,
            )
        for category in (budget.get("categories") or [])[:4]:
            slug = _test_id_part(category.get("category"))
            _add(
                expectations,
                check_id="dashboard.budget.summary",
                value_id="dashboard.budget.top_category_amounts",
                route="/dashboard",
                view_state_id=view_state_id,
                field=f"category_amount.{slug}",
                label="Dashboard budget category amount",
                expected_text=format_currency(category.get("spent")),
                selector=f"[data-testid='dashboard-budget-category-amount-{slug}']",
            )

        recurring = _actual(checks, "dashboard.recurring.summary", view_state_id) or {}
        _add(
            expectations,
            check_id="dashboard.recurring.summary",
            value_id="dashboard.recurring.monthly_total",
            route="/dashboard",
            view_state_id=view_state_id,
            field="monthly_total",
            label="Dashboard recurring monthly total",
            expected_text=f"{format_currency(recurring.get('monthly_total'))} /MO",
            selector="[data-testid='dashboard-recurring-monthly-total']",
        )
        for idx, (amount, item_id) in enumerate(zip(
            recurring.get("item_amounts") or [],
            recurring.get("item_ids") or [],
            strict=False,
        ), start=1):
            _add(
                expectations,
                check_id="dashboard.recurring.summary",
                value_id="dashboard.recurring.item_amounts",
                route="/dashboard",
                view_state_id=view_state_id,
                field=f"item_amount_{idx}",
                label="Dashboard recurring item amount",
                expected_text=format_currency(amount),
                selector=f"[data-testid='dashboard-recurring-item-amount-{_test_id_part(item_id)}']",
            )
        if not (recurring.get("item_amounts") or []):
            _add(
                expectations,
                check_id="dashboard.recurring.summary",
                value_id="dashboard.recurring.item_amounts",
                route="/dashboard",
                view_state_id=view_state_id,
                field="item_amounts_empty",
                label="Dashboard recurring empty state",
                expected_text="No recurring bills detected",
                selector="[data-testid='dashboard-recurring-items-empty']",
            )

        recent_amounts = _actual(checks, "dashboard.recent_transactions", view_state_id) or []
        if recent_amounts:
            for idx, amount in enumerate(recent_amounts[:8], start=1):
                _add(
                    expectations,
                    check_id="dashboard.recent_transactions",
                    value_id="dashboard.recent_transactions.amounts",
                    route="/dashboard",
                    view_state_id=view_state_id,
                    field=f"amount_{idx}",
                    label="Dashboard recent transaction amount",
                    expected_text=format_signed_currency(amount),
                    selector=f"[data-testid='dashboard-recent-transaction-amount-{idx}']",
                )
        else:
            _add(
                expectations,
                check_id="dashboard.recent_transactions",
                value_id="dashboard.recent_transactions.amounts",
                route="/dashboard",
                view_state_id=view_state_id,
                field="amounts_empty",
                label="Dashboard recent transactions empty state",
                expected_text="No transactions yet",
                selector="[data-testid='dashboard-recent-transactions-empty']",
            )

        # Cash Flow: current active period KPI row.
        cash_flow = _actual(checks, "cash_flow.current_month", view_state_id) or {}
        rolling_latest_month = _actual(checks, "cash_flow.rolling.latest_month", view_state_id) or {}
        if rolling_latest_month:
            latest_summary = format_chart_point({"label": "Latest", **rolling_latest_month}).replace("Latest: ", "")
            _add(
                expectations,
                check_id="cash_flow.rolling.latest_month",
                value_id="cash_flow.rolling.latest_month",
                route="/cash-flow",
                view_state_id=view_state_id,
                field="summary",
                label="Cash Flow rolling latest month summary",
                expected_text=latest_summary,
                selector="[data-testid='cash-flow-rolling-latest-month']",
            )

        monthly_points = _actual(checks, "cash_flow.chart.monthly_points", view_state_id) or []
        if monthly_points:
            _add(
                expectations,
                check_id="cash_flow.chart.monthly_points",
                value_id="cash_flow.chart.monthly_points",
                route="/cash-flow",
                view_state_id=view_state_id,
                field="monthly_points",
                label="Cash Flow monthly chart points",
                expected_text=join_text([format_chart_point(point) for point in monthly_points]),
                selector="[data-testid='cash-flow-chart-monthly-points']",
            )

        for field, value_id, label, formatter, selector in [
            ("income", "cash_flow.current_month.income", "Cash Flow income", format_currency, "[data-testid='cash-flow-current-income']"),
            ("spending", "cash_flow.current_month.spending", "Cash Flow expenses", format_currency, "[data-testid='cash-flow-current-spending']"),
            ("net", "cash_flow.current_month.net", "Cash Flow net savings", format_signed_currency, "[data-testid='cash-flow-current-net']"),
            ("savings_rate", "cash_flow.current_month.savings_rate", "Cash Flow savings rate", format_percent, "[data-testid='cash-flow-current-savings-rate']"),
            ("debt_service", "cash_flow.current_month.debt_service", "Cash Flow debt service", format_currency, "[data-testid='cash-flow-current-debt-service']"),
        ]:
            _add(
                expectations,
                check_id="cash_flow.current_month",
                value_id=value_id,
                route="/cash-flow",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=formatter(cash_flow.get(field)),
                selector=selector,
            )
        debt_service_percent = (
            round((float(cash_flow.get("debt_service") or 0) / float(cash_flow.get("spending") or 0)) * 100, 1)
            if cash_flow.get("spending")
            else 0.0
        )
        _add(
            expectations,
            check_id="cash_flow.current_month",
            value_id="cash_flow.current_month.debt_service_percent",
            route="/cash-flow",
            view_state_id=view_state_id,
            field="debt_service_percent",
            label="Cash Flow debt service percent",
            expected_text=format_percent(debt_service_percent),
            selector="[data-testid='cash-flow-current-debt-service-percent']",
        )
        for field, value_id, label, formatter, selector in [
            ("debt_accumulated", "cash_flow.current_month.debt_accumulated", "Cash Flow purchased on credit", format_currency, "[data-testid='cash-flow-debt-accumulated']"),
            ("debt_paid_down", "cash_flow.current_month.debt_paid_down", "Cash Flow paid toward debt", format_currency, "[data-testid='cash-flow-debt-paid-down']"),
            ("net_debt_change", "cash_flow.current_month.net_debt_change", "Cash Flow net debt change", lambda value: format_currency(abs(float(value or 0))), "[data-testid='cash-flow-net-debt-change']"),
        ]:
            if cash_flow.get("debt_accumulated") or cash_flow.get("debt_paid_down"):
                _add(
                    expectations,
                    check_id="cash_flow.current_month",
                    value_id=value_id,
                    route="/cash-flow",
                    view_state_id=view_state_id,
                    field=field,
                    label=label,
                    expected_text=formatter(cash_flow.get(field)),
                    selector=selector,
                )
            else:
                _add(
                    expectations,
                    check_id="cash_flow.current_month",
                    value_id=value_id,
                    route="/cash-flow",
                    view_state_id=view_state_id,
                    field=f"{field}_empty",
                    label=f"{label} empty state",
                    expected_text="$0.00",
                    selector=selector,
                )

        for category_kind, value_amount_id, value_percent_id in [
            ("income", "cash_flow.categories.income_amounts", "cash_flow.categories.income_percents"),
            ("spending", "cash_flow.categories.spending_amounts", "cash_flow.categories.spending_percents"),
        ]:
            total = float(cash_flow.get(category_kind) or 0)
            for category in (cash_flow.get(f"{category_kind}_categories") or [])[:6]:
                slug = _test_id_part(category.get("category"))
                amount = float(category.get("total") or 0)
                percent = round((amount / total) * 100, 1) if total else float(category.get("pct") or 0)
                _add(
                    expectations,
                    check_id="cash_flow.current_month",
                    value_id=value_amount_id,
                    route="/cash-flow",
                    view_state_id=view_state_id,
                    field=f"{category_kind}_category_amount.{slug}",
                    label=f"Cash Flow {category_kind} category amount",
                    expected_text=format_currency(amount),
                    selector=f"[data-testid='cash-flow-{category_kind}-category-amount-{slug}']",
                )
                _add(
                    expectations,
                    check_id="cash_flow.current_month",
                    value_id=value_percent_id,
                    route="/cash-flow",
                    view_state_id=view_state_id,
                    field=f"{category_kind}_category_percent.{slug}",
                    label=f"Cash Flow {category_kind} category percent",
                    expected_text=format_percent(percent),
                    selector=f"[data-testid='cash-flow-{category_kind}-category-percent-{slug}']",
                )

        if dti_latest:
            for field, value_id, label, formatter, selector in [
                ("dti_ratio", "cash_flow.dti.latest_percent", "Cash Flow DTI latest percent", format_percent, "[data-testid='cash-flow-dti-latest-percent']"),
                ("debt_payments", "cash_flow.dti.debt_payments", "Cash Flow DTI debt payments", format_currency, "[data-testid='cash-flow-dti-debt-payments']"),
                ("gross_income", "cash_flow.dti.gross_income", "Cash Flow DTI gross income", format_currency, "[data-testid='cash-flow-dti-gross-income']"),
            ]:
                _add(
                    expectations,
                    check_id="cash_flow.dti.latest",
                    value_id=value_id,
                    route="/cash-flow",
                    view_state_id=view_state_id,
                    field=field,
                    label=label,
                    expected_text=formatter(dti_latest.get(field)),
                    selector=selector,
                )
        else:
            for field, value_id in [
                ("dti_ratio_empty", "cash_flow.dti.latest_percent"),
                ("debt_payments_empty", "cash_flow.dti.debt_payments"),
                ("gross_income_empty", "cash_flow.dti.gross_income"),
            ]:
                _add(
                    expectations,
                    check_id="cash_flow.dti.latest",
                    value_id=value_id,
                    route="/cash-flow",
                    view_state_id=view_state_id,
                    field=field,
                    label="Cash Flow DTI empty state",
                    expected_text="No debt service activity in the trailing window.",
                    selector="[data-testid='cash-flow-dti-empty-state']",
                )

        # Transactions: visible pagination plus the first page's amount/date
        # cells. The full row set remains API-audited; this confirms the table
        # is rendering the current scoped slice.
        transactions = _actual(checks, "transactions.table", view_state_id) or {}
        _add(
            expectations,
            check_id="transactions.table",
            value_id="transactions.table.total_count",
            route="/transactions",
            view_state_id=view_state_id,
            field="pagination",
            label="Transactions pagination",
            expected_text=(
                f"Showing {transactions.get('range_start', 0)}-"
                f"{transactions.get('range_end', 0)} of "
                f"{transactions.get('total_count', 0)} transactions"
            ),
            selector="[data-testid='transactions-pagination-summary']",
        )
        for field, value_id, label, selector in [
            ("range_start", "transactions.pagination.range_start", "Transactions pagination range start", "[data-testid='transactions-pagination-range-start']"),
            ("range_end", "transactions.pagination.range_end", "Transactions pagination range end", "[data-testid='transactions-pagination-range-end']"),
            ("filtered_count", "transactions.table.filtered_count", "Transactions filtered count", "[data-testid='transactions-filtered-count']"),
            ("active_filter_count", "transactions.filters.active_count", "Transactions active filter count", "[data-testid='transactions-active-filter-count']"),
        ]:
            _add(
                expectations,
                check_id="transactions.table",
                value_id=value_id,
                route="/transactions",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=str(transactions.get(field, 0)),
                selector=selector,
            )
        if transactions.get("row_amounts"):
            for idx, amount in enumerate(transactions["row_amounts"][:5], start=1):
                _add(
                    expectations,
                    check_id="transactions.table",
                    value_id="transactions.table.row_amounts",
                    route="/transactions",
                    view_state_id=view_state_id,
                    field=f"row_amount_{idx}",
                    label="Transactions visible row amount",
                    expected_text=format_signed_currency(amount),
                    selector=f"[data-testid='transactions-row-amount-{idx}']",
                )
            for idx, posting_date in enumerate((transactions.get("row_dates") or [])[:3], start=1):
                _add(
                    expectations,
                    check_id="transactions.table",
                    value_id="transactions.table.row_dates",
                    route="/transactions",
                    view_state_id=view_state_id,
                    field=f"row_date_{idx}",
                    label="Transactions visible row date",
                    expected_text=format_transaction_date(posting_date),
                    selector=f"[data-testid='transactions-row-date-{idx}']",
                )
        else:
            _add(
                expectations,
                check_id="transactions.table",
                value_id="transactions.table.row_amounts",
                route="/transactions",
                view_state_id=view_state_id,
                field="empty_state",
                label="Transactions empty state",
                expected_text="No transactions found",
                selector="[data-testid='transactions-empty-state']",
            )
            _add(
                expectations,
                check_id="transactions.table",
                value_id="transactions.table.row_dates",
                route="/transactions",
                view_state_id=view_state_id,
                field="row_dates_empty_state",
                label="Transactions row dates empty state",
                expected_text="No transactions found",
                selector="[data-testid='transactions-empty-state']",
            )

        # Reports: current-month summary cards.
        reports_flow = _actual(checks, "reports.flow", view_state_id) or {}
        for field, value_id, label, formatter, selector in [
            ("total_income", "reports.summary.total_income", "Reports total income", format_currency, "[data-testid='reports-summary-total-income']"),
            ("total_spending", "reports.summary.total_expenses", "Reports total expenses", format_currency, "[data-testid='reports-summary-total-expenses']"),
            ("net", "reports.summary.net_income", "Reports total net income", format_signed_currency, "[data-testid='reports-summary-net-income']"),
            ("savings_rate", "reports.summary.savings_rate", "Reports savings rate", format_percent, "[data-testid='reports-summary-savings-rate']"),
        ]:
            _add(
                expectations,
                check_id="reports.flow",
                value_id=value_id,
                route="/reports",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=formatter(reports_flow.get(field)),
                selector=selector,
            )
        for field, value_id, label, formatter, selector in [
            ("total_income", "reports.sankey.total_income", "Reports Sankey total income", format_currency, "[data-testid='reports-summary-total-income']"),
            ("total_spending", "reports.sankey.total_spending", "Reports Sankey total spending", format_currency, "[data-testid='reports-summary-total-expenses']"),
        ]:
            _add(
                expectations,
                check_id="reports.flow",
                value_id=value_id,
                route="/reports",
                view_state_id=view_state_id,
                field=f"sankey_{field}",
                label=label,
                expected_text=formatter(reports_flow.get(field)),
                selector=selector,
            )
        for key, amount in (reports_flow.get("bucket_totals") or {}).items():
            slug = _test_id_part(key)
            _add(
                expectations,
                check_id="reports.flow",
                value_id="reports.sankey.bucket_totals",
                route="/reports",
                view_state_id=view_state_id,
                field=f"bucket_total.{slug}",
                label="Reports bucket total",
                expected_text=format_currency(amount),
                selector=f"[data-testid='reports-bucket-total-{slug}']",
            )
        for key, percent in (reports_flow.get("bucket_percents") or {}).items():
            slug = _test_id_part(key)
            _add(
                expectations,
                check_id="reports.flow",
                value_id="reports.sankey.bucket_percents",
                route="/reports",
                view_state_id=view_state_id,
                field=f"bucket_percent.{slug}",
                label="Reports bucket percent",
                expected_text=format_percent(percent),
                selector=f"[data-testid='reports-bucket-percent-{slug}']",
            )

        accountability = _actual(checks, "reports.accountability", view_state_id) or {}
        _add(
            expectations,
            check_id="reports.accountability",
            value_id="reports.accountability.accounted_for_percent",
            route="/reports",
            view_state_id=view_state_id,
            field="accounted_for_percent",
            label="Reports accounted-for percent",
            expected_text=format_percent(float(accountability.get("accounted_for_pct") or 0) * 100),
            selector="[data-testid='reports-accountability-accounted-for-percent']",
        )
        _add(
            expectations,
            check_id="reports.accountability",
            value_id="reports.accountability.net_worth_delta",
            route="/reports",
            view_state_id=view_state_id,
            field="net_worth_delta",
            label="Reports net worth delta",
            expected_text=format_reports_signed_cents(accountability.get("net_worth_delta_cents")),
            selector="[data-testid='reports-accountability-net-worth-delta']",
        )
        if accountability.get("unexplained_cents"):
            _add(
                expectations,
                check_id="reports.accountability",
                value_id="reports.accountability.unexplained_amount",
                route="/reports",
                view_state_id=view_state_id,
                field="unexplained_amount",
                label="Reports unexplained amount",
                expected_text=format_reports_signed_cents(accountability.get("unexplained_cents")),
                selector="[data-testid='reports-accountability-unexplained-amount']",
            )
        _add(
            expectations,
            check_id="reports.accountability",
            value_id="reports.accountability.drift_source_count",
            route="/reports",
            view_state_id=view_state_id,
            field="drift_source_count",
            label="Reports drift source count",
            expected_text=str(accountability.get("drift_source_count") or 0),
            selector="[data-testid='reports-accountability-drift-source-count']",
        )

        reports_tx_amounts = _actual(checks, "reports.transactions.visible", view_state_id) or []
        for idx, amount in enumerate(reports_tx_amounts[:10], start=1):
            _add(
                expectations,
                check_id="reports.transactions.visible",
                value_id="reports.transactions.visible_amounts",
                route="/reports",
                view_state_id=view_state_id,
                field=f"amount_{idx}",
                label="Reports visible transaction amount",
                expected_text=format_signed_currency(amount),
                selector=f"[data-testid='reports-transaction-amount-{idx}']",
            )
        if not reports_tx_amounts:
            _add(
                expectations,
                check_id="reports.transactions.visible",
                value_id="reports.transactions.visible_amounts",
                route="/reports",
                view_state_id=view_state_id,
                field="amounts_empty",
                label="Reports transactions empty state",
                expected_text="No matching transactions",
                selector="[data-testid='reports-transactions-empty']",
            )

        # Accounts: header total and expanded group totals.
        accounts = _actual(checks, "accounts.snapshot", view_state_id) or {}
        _add(
            expectations,
            check_id="accounts.snapshot",
            value_id="accounts.header.display_total",
            route="/accounts",
            view_state_id=view_state_id,
            field="display_total",
            label="Accounts displayed total",
            expected_text=format_currency(accounts.get("display_total")),
            selector="[data-testid='accounts-display-total']",
        )
        _add(
            expectations,
            check_id="accounts.snapshot",
            value_id="accounts.header.data_through",
            route="/accounts",
            view_state_id=view_state_id,
            field="data_through",
            label="Accounts header data-through state",
            expected_text="AS OF LAST REFRESH" if not accounts.get("data_through") else str(accounts.get("data_through")),
            selector="[data-testid='accounts-header-data-through']",
        )
        if accounts.get("display_total") or accounts.get("trend_percent"):
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.header.trend_percent",
                route="/accounts",
                view_state_id=view_state_id,
                field="trend_percent",
                label="Accounts header trend percent",
                expected_text=format_signed_percent(accounts.get("trend_percent")),
                selector="[data-testid='accounts-header-trend-percent']",
            )
        else:
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.header.trend_percent",
                route="/accounts",
                view_state_id=view_state_id,
                field="trend_percent_empty",
                label="Accounts header trend percent empty state",
                expected_text="+0.0%",
                selector="[data-testid='accounts-header-trend-percent']",
            )
        for group_name, group_total in (accounts.get("group_totals") or {}).items():
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.groups.totals",
                route="/accounts",
                view_state_id=view_state_id,
                field=f"group_total.{group_name}",
                label=f"Accounts group total: {group_name}",
                expected_text=format_currency(group_total),
                selector=f"[data-testid='accounts-group-total-{_test_id_part(group_name)}']",
            )
        if not (accounts.get("group_totals") or {}):
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.groups.totals",
                route="/accounts",
                view_state_id=view_state_id,
                field="group_totals_empty",
                label="Accounts group totals empty state",
                expected_text="No accounts in this view",
                selector="[data-testid='accounts-groups-empty']",
            )

        row_balances = accounts.get("row_balances") or []
        if row_balances:
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.rows.balances",
                route="/accounts",
                view_state_id=view_state_id,
                field="row_balances",
                label="Accounts row balances",
                expected_text=join_text([format_currency(value) for value in row_balances]),
                selector="[data-testid^='accounts-row-balance-']:not([data-testid^='accounts-row-balance-as-of-'])",
                selector_all=True,
            )
        else:
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.rows.balances",
                route="/accounts",
                view_state_id=view_state_id,
                field="row_balances_empty",
                label="Accounts row balances empty state",
                expected_text="No accounts in this view",
                selector="[data-testid='accounts-groups-empty']",
            )

        row_balance_as_of = accounts.get("row_balance_as_of") or []
        if row_balance_as_of:
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.rows.balance_as_of",
                route="/accounts",
                view_state_id=view_state_id,
                field="row_balance_as_of",
                label="Accounts row balance as-of dates",
                expected_text=join_text([format_short_date(value) for value in row_balance_as_of]),
                selector="[data-testid^='accounts-row-balance-as-of-']",
                selector_all=True,
            )
        else:
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.rows.balance_as_of",
                route="/accounts",
                view_state_id=view_state_id,
                field="row_balance_as_of_empty",
                label="Accounts row as-of empty state",
                expected_text="No accounts in this view",
                selector="[data-testid='accounts-groups-empty']",
            )

        for field, value_id, label, formatter, selector in [
            ("apr", "accounts.rows.apr", "Accounts APR values", lambda values: join_text([f"{float(value):g}% APR" for value in values]), "[data-testid^='accounts-row-apr-']"),
            ("rewards_points", "accounts.rows.rewards_points", "Accounts rewards points", lambda values: join_text([f"redeem {int(value):,} pts" for value in values]), "[data-testid^='accounts-row-rewards-points-']"),
            ("installment_paid_percent", "accounts.rows.installment_paid_percent", "Accounts installment paid-off percents", lambda values: join_text([f"{int(value)}% paid off" for value in values]), "[data-testid^='accounts-row-installment-paid-percent-']"),
            ("credit_utilization_percent", "accounts.rows.credit_utilization_percent", "Accounts credit utilization percents", lambda values: join_text([f"{int(value)}%" for value in values]), "[data-testid^='accounts-row-credit-utilization-percent-']"),
        ]:
            values = accounts.get(field) or []
            if values:
                _add(
                    expectations,
                    check_id="accounts.snapshot",
                    value_id=value_id,
                    route="/accounts",
                    view_state_id=view_state_id,
                    field=field,
                    label=label,
                    expected_text=formatter(values),
                    selector=selector,
                    selector_all=True,
                )
            else:
                _add(
                    expectations,
                    check_id="accounts.snapshot",
                    value_id=value_id,
                    route="/accounts",
                    view_state_id=view_state_id,
                    field=f"{field}_empty",
                    label=f"{label} empty state",
                    expected_text="No accounts in this view" if not row_balances else "",
                    selector="[data-testid='accounts-groups-empty']" if not row_balances else selector,
                    selector_all=bool(row_balances),
                )
        summary = accounts.get("summary") or {}
        _add(
            expectations,
            check_id="accounts.snapshot",
            value_id="accounts.summary.assets_total",
            route="/accounts",
            view_state_id=view_state_id,
            field="summary.assets_total",
            label="Accounts summary assets total",
            expected_text=format_currency(summary.get("assets_total")),
            selector="[data-testid='accounts-summary-assets-total']",
        )
        _add(
            expectations,
            check_id="accounts.snapshot",
            value_id="accounts.summary.liabilities_total",
            route="/accounts",
            view_state_id=view_state_id,
            field="summary.liabilities_total",
            label="Accounts summary liabilities total",
            expected_text=format_currency(summary.get("liabilities_total")),
            selector="[data-testid='accounts-summary-liabilities-total']",
        )
        for bucket_name, amount in (summary.get("bucket_totals") or {}).items():
            slug = _test_id_part(bucket_name)
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.summary.bucket_totals",
                route="/accounts",
                view_state_id=view_state_id,
                field=f"summary.bucket_total.{slug}",
                label="Accounts summary bucket total",
                expected_text=format_currency(amount),
                selector=f"[data-testid='accounts-summary-bucket-{slug}']",
                setup="accounts_summary_totals",
            )
        if not (summary.get("bucket_totals") or {}):
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.summary.bucket_totals",
                route="/accounts",
                view_state_id=view_state_id,
                field="summary.bucket_totals_empty",
                label="Accounts summary bucket totals empty state",
                expected_text="No asset buckets",
                selector="[data-testid='accounts-summary-buckets-empty']",
                setup="accounts_summary_totals",
            )
        for bucket_name, percent in (summary.get("bucket_percents") or {}).items():
            slug = _test_id_part(bucket_name)
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.summary.bucket_percents",
                route="/accounts",
                view_state_id=view_state_id,
                field=f"summary.bucket_percent.{slug}",
                label="Accounts summary bucket percent",
                expected_text=format_percent(percent),
                selector=f"[data-testid='accounts-summary-bucket-{slug}']",
                setup="accounts_summary_percent",
            )
        if not (summary.get("bucket_percents") or {}):
            _add(
                expectations,
                check_id="accounts.snapshot",
                value_id="accounts.summary.bucket_percents",
                route="/accounts",
                view_state_id=view_state_id,
                field="summary.bucket_percents_empty",
                label="Accounts summary bucket percents empty state",
                expected_text="No asset buckets",
                selector="[data-testid='accounts-summary-buckets-empty']",
                setup="accounts_summary_percent",
            )

        # Budgets: household-only headline metrics and visible category rows.
        # Same numbers must render under household, owner.quintin, and
        # owner.amy view states — budgets are a household-only concept and
        # the page intentionally ignores the active owner.
        budgets_summary = _actual(checks, "budgets.page.summary", view_state_id) or {}
        for field, value_id, label, formatter, selector in [
            ("total_remaining", "budgets.summary.safe_to_spend", "Budgets safe-to-spend", format_currency, "[data-testid='budgets-safe-to-spend']"),
            ("total_assigned", "budgets.summary.total_assigned", "Budgets total assigned", format_currency, "[data-testid='budgets-total-assigned']"),
            ("total_spent", "budgets.summary.total_spent", "Budgets total spent", format_currency, "[data-testid='budgets-total-spent']"),
            ("pct_used", "budgets.summary.percent_used", "Budgets percent used", format_percent_zero, "[data-testid='budgets-percent-used']"),
            ("days_left", "budgets.summary.days_left", "Budgets days left", lambda value: str(int(value or 0)), "[data-testid='budgets-days-left']"),
            ("daily_allowance", "budgets.summary.daily_allowance", "Budgets daily allowance", format_currency, "[data-testid='budgets-daily-allowance']"),
            ("active_count", "budgets.summary.active_count", "Budgets active count", lambda value: str(int(value or 0)), "[data-testid='budgets-active-count']"),
        ]:
            _add(
                expectations,
                check_id="budgets.page.summary",
                value_id=value_id,
                route="/budgets",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=formatter(budgets_summary.get(field)),
                selector=selector,
            )

        budgets_categories = _actual(checks, "budgets.page.categories", view_state_id) or []
        if budgets_categories:
            for category in budgets_categories:
                slug = _test_id_part(category.get("category"))
                _add(
                    expectations,
                    check_id="budgets.page.categories",
                    value_id="budgets.categories.row_spent",
                    route="/budgets",
                    view_state_id=view_state_id,
                    field=f"category_spent.{slug}",
                    label="Budgets category spent",
                    expected_text=format_currency(category.get("actual")),
                    selector=f"[data-testid='budgets-category-spent-{slug}']",
                )
                _add(
                    expectations,
                    check_id="budgets.page.categories",
                    value_id="budgets.categories.row_target",
                    route="/budgets",
                    view_state_id=view_state_id,
                    field=f"category_target.{slug}",
                    label="Budgets category target",
                    expected_text=format_currency(category.get("target")),
                    selector=f"[data-testid='budgets-category-target-{slug}']",
                )
                if category.get("status") == "over":
                    remaining_text = "Over budget"
                else:
                    remaining_text = f"{format_currency(abs(float(category.get('remaining') or 0)))} left"
                _add(
                    expectations,
                    check_id="budgets.page.categories",
                    value_id="budgets.categories.row_remaining",
                    route="/budgets",
                    view_state_id=view_state_id,
                    field=f"category_remaining.{slug}",
                    label="Budgets category remaining label",
                    expected_text=remaining_text,
                    selector=f"[data-testid='budgets-category-remaining-{slug}']",
                )
        else:
            for value_id, field, label in [
                ("budgets.categories.row_spent", "category_spent_empty", "Budgets categories empty state"),
                ("budgets.categories.row_target", "category_target_empty", "Budgets categories empty state"),
                ("budgets.categories.row_remaining", "category_remaining_empty", "Budgets categories empty state"),
            ]:
                _add(
                    expectations,
                    check_id="budgets.page.categories",
                    value_id=value_id,
                    route="/budgets",
                    view_state_id=view_state_id,
                    field=field,
                    label=label,
                    expected_text="No budgets for",
                    selector=None,
                )

        # Monthly Review: KPIs, pre-tax block (when payroll snapshot exists),
        # budget highlights, and notable transactions.
        review_monthly = _actual(checks, "review.monthly", view_state_id) or {}
        for field, value_id, label, formatter, selector in [
            ("income_total", "review.monthly.income_total", "Monthly review income total", format_compact_currency, "[data-testid='monthly-review-income-total']"),
            ("spending_total", "review.monthly.spending_total", "Monthly review spending total", format_compact_currency, "[data-testid='monthly-review-spending-total']"),
            ("savings_rate", "review.monthly.savings_rate", "Monthly review savings rate", format_percent, "[data-testid='monthly-review-savings-rate']"),
        ]:
            _add(
                expectations,
                check_id="review.monthly",
                value_id=value_id,
                route="/review/monthly",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=formatter(review_monthly.get(field)),
                selector=selector,
            )
        net_worth_delta = review_monthly.get("net_worth_delta") or {}
        _add(
            expectations,
            check_id="review.monthly",
            value_id="review.monthly.net_worth_delta_amount",
            route="/review/monthly",
            view_state_id=view_state_id,
            field="net_worth_delta_amount",
            label="Monthly review net worth delta amount",
            expected_text=format_review_signed_currency(net_worth_delta.get("amount")),
            selector="[data-testid='monthly-review-net-worth-delta-amount']",
        )
        _add(
            expectations,
            check_id="review.monthly",
            value_id="review.monthly.net_worth_delta_percent",
            route="/review/monthly",
            view_state_id=view_state_id,
            field="net_worth_delta_percent",
            label="Monthly review net worth delta percent",
            expected_text=format_review_signed_percent(net_worth_delta.get("pct")),
            selector="[data-testid='monthly-review-net-worth-delta-percent']",
        )
        _add(
            expectations,
            check_id="review.monthly",
            value_id="review.monthly.cash_surplus",
            route="/review/monthly",
            view_state_id=view_state_id,
            field="cash_surplus",
            label="Monthly review cash surplus",
            expected_text=format_review_signed_currency(review_monthly.get("cash_surplus")),
            selector="[data-testid='monthly-review-cash-surplus']",
        )
        uncat = review_monthly.get("uncategorized_count")
        if uncat is None or int(uncat) == 0:
            _add(
                expectations,
                check_id="review.monthly",
                value_id="review.monthly.uncategorized_count",
                route="/review/monthly",
                view_state_id=view_state_id,
                field="uncategorized_count_zero",
                label="Monthly review uncategorized empty state",
                expected_text="All transactions categorized",
                selector="[data-testid='monthly-review-uncategorized-count']",
            )
        else:
            _add(
                expectations,
                check_id="review.monthly",
                value_id="review.monthly.uncategorized_count",
                route="/review/monthly",
                view_state_id=view_state_id,
                field="uncategorized_count",
                label="Monthly review uncategorized count",
                expected_text=str(int(uncat)),
                selector="[data-testid='monthly-review-uncategorized-count']",
            )

        pre_tax = review_monthly.get("pre_tax")
        if pre_tax:
            _add(
                expectations,
                check_id="review.monthly",
                value_id="review.monthly.pretax.gross_income",
                route="/review/monthly",
                view_state_id=view_state_id,
                field="pretax_gross_income",
                label="Monthly review pre-tax gross income",
                expected_text=format_compact_currency(pre_tax.get("gross_income")),
                selector="[data-testid='monthly-review-pretax-gross-income']",
            )
            _add(
                expectations,
                check_id="review.monthly",
                value_id="review.monthly.pretax.federal_tax",
                route="/review/monthly",
                view_state_id=view_state_id,
                field="pretax_federal_tax",
                label="Monthly review pre-tax federal tax",
                expected_text=format_pretax_negative_compact(pre_tax.get("federal_tax")),
                selector="[data-testid='monthly-review-pretax-federal-tax']",
            )
            _add(
                expectations,
                check_id="review.monthly",
                value_id="review.monthly.pretax.state_tax",
                route="/review/monthly",
                view_state_id=view_state_id,
                field="pretax_state_tax",
                label="Monthly review pre-tax state tax",
                expected_text=format_pretax_negative_compact(pre_tax.get("state_tax")),
                selector="[data-testid='monthly-review-pretax-state-tax']",
            )
            _add(
                expectations,
                check_id="review.monthly",
                value_id="review.monthly.pretax.net_pay",
                route="/review/monthly",
                view_state_id=view_state_id,
                field="pretax_net_pay",
                label="Monthly review pre-tax net pay",
                expected_text=format_compact_currency(pre_tax.get("net_pay")),
                selector="[data-testid='monthly-review-pretax-net-pay']",
            )
            _add(
                expectations,
                check_id="review.monthly",
                value_id="review.monthly.pretax.savings_rate",
                route="/review/monthly",
                view_state_id=view_state_id,
                field="pretax_savings_rate",
                label="Monthly review pre-tax savings rate",
                expected_text=format_percent(pre_tax.get("savings_rate_pct")),
                selector="[data-testid='monthly-review-pretax-savings-rate']",
            )

        budget_highlight_actuals = review_monthly.get("budget_highlight_actuals") or []
        if budget_highlight_actuals:
            _add(
                expectations,
                check_id="review.monthly",
                value_id="review.monthly.budget_highlights",
                route="/review/monthly",
                view_state_id=view_state_id,
                field="budget_highlights",
                label="Monthly review budget highlight actuals",
                expected_text=join_text([format_currency(amount) for amount in budget_highlight_actuals]),
                selector="[data-testid^='monthly-review-budget-actual-']",
                selector_all=True,
            )

        notable_amounts = review_monthly.get("notable_transaction_amounts") or []
        for idx, amount in enumerate(notable_amounts, start=1):
            _add(
                expectations,
                check_id="review.monthly",
                value_id="review.monthly.notable_transactions",
                route="/review/monthly",
                view_state_id=view_state_id,
                field=f"notable_transaction_amount_{idx}",
                label="Monthly review notable transaction amount",
                expected_text=format_currency(amount),
                selector=f"[data-testid='monthly-review-notable-transaction-amount-{idx}']",
            )

        # Yearly Wrap-Up: KPIs, status pill, tax doc count, effective-tax block,
        # interest summary, income-by-stream and spending-by-category amounts.
        review_yearly = _actual(checks, "review.yearly", view_state_id) or {}
        for field, value_id, label, formatter, selector in [
            ("total_income", "review.yearly.total_income", "Yearly wrap-up total income", format_compact_currency, "[data-testid='yearly-wrapup-total-income']"),
            ("total_spending", "review.yearly.total_spending", "Yearly wrap-up total spending", format_compact_currency, "[data-testid='yearly-wrapup-total-spending']"),
            ("savings_rate", "review.yearly.savings_rate", "Yearly wrap-up savings rate", format_percent, "[data-testid='yearly-wrapup-savings-rate']"),
            ("interest_net_cost", "review.yearly.net_interest_cost", "Yearly wrap-up net interest cost", format_compact_currency, "[data-testid='yearly-wrapup-net-interest-cost']"),
        ]:
            _add(
                expectations,
                check_id="review.yearly",
                value_id=value_id,
                route="/review/yearly",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=formatter(review_yearly.get(field)),
                selector=selector,
            )
        status = review_yearly.get("status") or "preliminary"
        _add(
            expectations,
            check_id="review.yearly",
            value_id="review.yearly.status",
            route="/review/yearly",
            view_state_id=view_state_id,
            field="status",
            label="Yearly wrap-up status label",
            expected_text=WRAPUP_STATUS_LABELS.get(status, status.title()),
            selector="[data-testid='yearly-wrapup-status']",
        )
        if review_yearly.get("tax_doc_expected"):
            _add(
                expectations,
                check_id="review.yearly",
                value_id="review.yearly.tax_doc_count",
                route="/review/yearly",
                view_state_id=view_state_id,
                field="tax_doc_count",
                label="Yearly wrap-up tax document count",
                expected_text=f"{review_yearly.get('tax_doc_received', 0)}/{review_yearly.get('tax_doc_expected', 0)}",
                selector="[data-testid='yearly-wrapup-tax-doc-count']",
            )
        eff = review_yearly.get("effective_tax")
        if eff:
            _add(
                expectations,
                check_id="review.yearly",
                value_id="review.yearly.effective.gross_income",
                route="/review/yearly",
                view_state_id=view_state_id,
                field="effective_gross_income",
                label="Yearly wrap-up effective gross income",
                expected_text=format_compact_currency(eff.get("gross_income")),
                selector="[data-testid='yearly-wrapup-effective-gross-income']",
            )
            _add(
                expectations,
                check_id="review.yearly",
                value_id="review.yearly.effective.federal_tax",
                route="/review/yearly",
                view_state_id=view_state_id,
                field="effective_federal_tax",
                label="Yearly wrap-up effective federal tax",
                expected_text=format_compact_currency(eff.get("federal_tax")),
                selector="[data-testid='yearly-wrapup-effective-federal-tax']",
            )
            _add(
                expectations,
                check_id="review.yearly",
                value_id="review.yearly.effective.state_tax",
                route="/review/yearly",
                view_state_id=view_state_id,
                field="effective_state_tax",
                label="Yearly wrap-up effective state tax",
                expected_text=format_compact_currency(eff.get("state_tax")),
                selector="[data-testid='yearly-wrapup-effective-state-tax']",
            )
            _add(
                expectations,
                check_id="review.yearly",
                value_id="review.yearly.effective.rate_pct",
                route="/review/yearly",
                view_state_id=view_state_id,
                field="effective_rate_pct",
                label="Yearly wrap-up effective rate",
                expected_text=format_percent(eff.get("effective_rate_pct")),
                selector="[data-testid='yearly-wrapup-effective-rate']",
            )

        for field, value_id, label, formatter, selector in [
            ("interest_paid", "review.yearly.interest.paid", "Yearly wrap-up interest paid", format_currency, "[data-testid='yearly-wrapup-interest-paid']"),
            ("interest_earned", "review.yearly.interest.earned", "Yearly wrap-up interest earned", format_currency, "[data-testid='yearly-wrapup-interest-earned']"),
            ("interest_net_cost", "review.yearly.interest.net_cost", "Yearly wrap-up interest net cost", format_currency, "[data-testid='yearly-wrapup-interest-net-cost']"),
        ]:
            _add(
                expectations,
                check_id="review.yearly",
                value_id=value_id,
                route="/review/yearly",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=formatter(review_yearly.get(field)),
                selector=selector,
            )

        income_stream_amounts = review_yearly.get("income_by_stream_amounts") or []
        if income_stream_amounts:
            _add(
                expectations,
                check_id="review.yearly",
                value_id="review.yearly.income_by_stream",
                route="/review/yearly",
                view_state_id=view_state_id,
                field="income_by_stream",
                label="Yearly wrap-up income by stream amounts",
                expected_text=join_text([format_currency(amount) for amount in income_stream_amounts]),
                selector="[data-testid^='yearly-wrapup-income-stream-']",
                selector_all=True,
            )

        spend_cat_amounts = review_yearly.get("spending_by_category_amounts") or []
        if spend_cat_amounts:
            _add(
                expectations,
                check_id="review.yearly",
                value_id="review.yearly.spending_by_category",
                route="/review/yearly",
                view_state_id=view_state_id,
                field="spending_by_category",
                label="Yearly wrap-up spending category amounts",
                expected_text=join_text([format_currency(amount) for amount in spend_cat_amounts]),
                selector="[data-testid^='yearly-wrapup-spending-category-']",
                selector_all=True,
            )

    route_index = {route: idx for idx, route in enumerate(ROUTE_ORDER)}
    view_index = {view: idx for idx, view in enumerate(VIEW_TO_FRONTEND_VALUE)}
    return sorted(
        expectations,
        key=lambda item: (route_index.get(item.route, 99), view_index.get(item.view_state_id, 99), item.id),
    )


def _expectations_by_route_view(
    expectations: list[DomExpectation],
) -> dict[tuple[str, str], list[DomExpectation]]:
    grouped: dict[tuple[str, str], list[DomExpectation]] = {}
    for expectation in expectations:
        grouped.setdefault((expectation.route, expectation.view_state_id), []).append(expectation)
    return grouped


def _set_view(page: Any, view_state_id: str, timeout_ms: int) -> None:
    view_value = VIEW_TO_FRONTEND_VALUE[view_state_id]
    selector = f"[data-testid='view-selector-{view_value}']"
    page.locator(selector).click(timeout=timeout_ms)
    page.wait_for_function(
        """selector => {
            const el = document.querySelector(selector);
            return el && el.getAttribute("aria-pressed") === "true";
        }""",
        arg=selector,
        timeout=timeout_ms,
    )


def _prepare_expectation(page: Any, expectation: DomExpectation, timeout_ms: int) -> None:
    if expectation.setup == "dashboard_net_worth_details_open":
        toggle = page.locator("[data-testid='dashboard-net-worth-details-toggle']")
        if toggle.count() == 1 and toggle.get_attribute("aria-expanded") != "true":
            toggle.click(timeout=timeout_ms)
            page.wait_for_timeout(250)
    elif expectation.setup == "accounts_summary_totals":
        page.locator("[data-testid='accounts-summary-mode-totals']").click(timeout=timeout_ms)
        page.wait_for_timeout(150)
    elif expectation.setup == "accounts_summary_percent":
        page.locator("[data-testid='accounts-summary-mode-percent']").click(timeout=timeout_ms)
        page.wait_for_timeout(150)


def _body_contains(body: str, expected_text: str) -> bool:
    normalized_body = normalize_text(body)
    normalized_expected = normalize_text(expected_text)
    return normalized_expected in normalized_body


def run_dom_audit(
    *,
    db_path: Path,
    frontend_url: str = DEFAULT_FRONTEND_URL,
    headless: bool = True,
    timeout_ms: int = 15_000,
    settle_ms: int = 1_000,
) -> dict[str, Any]:
    api_report = api_audit.run(db_path)
    expectations = build_dom_expectations(api_report)
    grouped = _expectations_by_route_view(expectations)
    checks: list[dict[str, Any]] = []
    diffs: list[dict[str, Any]] = []

    if api_report.get("diff_count"):
        diffs.append({
            "id": "api_audit.zero_diff_prerequisite",
            "route": None,
            "view_state": None,
            "expected": "0 API/oracle diffs",
            "actual": api_report.get("diff_count"),
            "classification": "API/DAL logic bug",
        })

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "Python Playwright is required for DOM audit. Install it or run the API audit only."
        ) from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1100})
            context.add_init_script("window.localStorage.clear(); window.sessionStorage.clear();")
            page = context.new_page()
            for route in ROUTE_ORDER:
                for view_state_id in VIEW_TO_FRONTEND_VALUE:
                    route_expectations = grouped.get((route, view_state_id), [])
                    if not route_expectations:
                        continue
                    url = frontend_url.rstrip("/") + route
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.locator("[data-testid='view-selector']").wait_for(timeout=timeout_ms)
                    _set_view(page, view_state_id, timeout_ms)
                    try:
                        first = route_expectations[0]
                        if first.selector:
                            first_locator = page.locator(first.selector)
                            if first.selector_all:
                                if first.expected_text:
                                    first_locator.first.wait_for(timeout=min(timeout_ms, 8_000))
                            else:
                                first_locator.wait_for(timeout=min(timeout_ms, 8_000))
                        else:
                            page.wait_for_function(
                                """expected => document.body && document.body.innerText.includes(expected)""",
                                arg=first.expected_text,
                                timeout=min(timeout_ms, 8_000),
                            )
                    except PlaywrightTimeoutError:
                        # Capture the page anyway so every missing value is
                        # reported in one pass instead of stopping at the first.
                        pass
                    page.wait_for_timeout(settle_ms)
                    body = page.locator("body").inner_text(timeout=timeout_ms)
                    for expectation in route_expectations:
                        _prepare_expectation(page, expectation, timeout_ms)
                        selector_target_count = None
                        rendered_text = body
                        if expectation.selector:
                            locator = page.locator(expectation.selector)
                            selector_target_count = locator.count()
                            if expectation.selector_all:
                                rendered_text = join_text(locator.all_inner_texts())
                                found = normalize_text(rendered_text) == normalize_text(expectation.expected_text)
                            elif selector_target_count == 1:
                                rendered_text = locator.inner_text(timeout=timeout_ms)
                                found = _body_contains(rendered_text, expectation.expected_text)
                            else:
                                found = False
                        else:
                            found = _body_contains(body, expectation.expected_text)
                        checks.append({
                            "id": expectation.id,
                            "check_id": expectation.check_id,
                            "value_id": expectation.value_id,
                            "route": expectation.route,
                            "view_state": expectation.view_state_id,
                            "label": expectation.label,
                            "selector": expectation.selector,
                            "setup": expectation.setup,
                            "selector_all": expectation.selector_all,
                            "selector_backed": expectation.selector is not None,
                            "selector_target_count": selector_target_count,
                            "expected_text_hash": _text_hash(expectation.expected_text),
                            "found": found,
                        })
                        if not found:
                            if expectation.selector and selector_target_count != 1:
                                actual = f"selector target count {selector_target_count}"
                            elif expectation.selector:
                                actual = "selector text mismatch"
                            else:
                                actual = "not found in rendered body text"
                            diffs.append({
                                "id": expectation.id,
                                "route": expectation.route,
                                "view_state": expectation.view_state_id,
                                "expected": expectation.expected_text,
                                "actual": actual,
                                "classification": "frontend wiring bug",
                            })
        finally:
            browser.close()

    registered_contexts = (api_report.get("registry") or {}).get("value_contexts") or []
    registered_context_set = {
        _scoped_id(context.get("value_id"), (context.get("view_state") or {}).get("id"))
        for context in registered_contexts
        if context.get("value_id") and (context.get("view_state") or {}).get("id")
    }
    covered_check_contexts = {
        _scoped_id(expectation.check_id, expectation.view_state_id)
        for expectation in expectations
    }
    covered_value_contexts = {
        _scoped_id(expectation.value_id, expectation.view_state_id)
        for expectation in expectations
        if expectation.value_id
    } & registered_context_set
    uncovered_value_contexts = sorted(registered_context_set - covered_value_contexts)
    route_counts: dict[str, int] = {}
    view_counts: dict[str, int] = {}
    for expectation in expectations:
        route_counts[expectation.route] = route_counts.get(expectation.route, 0) + 1
        view_counts[expectation.view_state_id] = view_counts.get(expectation.view_state_id, 0) + 1
    selector_backed_count = sum(1 for expectation in expectations if expectation.selector)

    return {
        "seed_version": api_report.get("seed_version"),
        "reference_date": api_report.get("reference_date"),
        "database_fingerprint": api_report.get("database_fingerprint"),
        "frontend_url": frontend_url,
        "api_diff_count": api_report.get("diff_count"),
        "dom_check_count": len(checks),
        "dom_diff_count": len(diffs),
        "diff_count": len(diffs),
        "coverage": {
            "scope": "full_registered_selector_backed",
            "claim": (
                "Selector-backed rendered text and accessibility-state proof for every registered value/view context "
                "across the scoped pages (Dashboard, Transactions, Cash Flow, Reports, Accounts, Budgets)."
            ),
            "registered_value_contexts": len(registered_contexts),
            "distinct_check_contexts_touched": len(covered_check_contexts),
            "distinct_registered_value_contexts_touched": len(covered_value_contexts),
            "uncovered_registered_value_contexts": len(uncovered_value_contexts),
            "uncovered_registered_value_context_ids": uncovered_value_contexts,
            "selector_backed_dom_checks": selector_backed_count,
            "routes": route_counts,
            "view_states": view_counts,
        },
        "diffs": diffs,
        "checks": checks,
    }


def _artifact_payload(report: dict[str, Any]) -> dict[str, Any]:
    payload = dict(report)
    payload["checks"] = [
        {
            "id": check["id"],
            "check_id": check["check_id"],
            "value_id": check.get("value_id"),
            "route": check["route"],
            "view_state": check["view_state"],
            "label": check["label"],
            "selector": check.get("selector"),
            "setup": check.get("setup"),
            "selector_all": check.get("selector_all"),
            "selector_backed": check.get("selector_backed"),
            "selector_target_count": check.get("selector_target_count"),
            "expected_text_hash": check["expected_text_hash"],
            "found": check["found"],
        }
        for check in report.get("checks") or []
    ]
    payload["artifact_policy"] = "passing_dom_text_values_hashed"
    return payload


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_DIR / f"number-trust-dom-{stamp}.json"
    md_path = REPORT_DIR / f"number-trust-dom-{stamp}.md"
    json_path.write_text(json.dumps(_artifact_payload(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    coverage = report["coverage"]
    lines = [
        "# Number Trust DOM Audit",
        "",
        f"- Seed version: `{report['seed_version']}`",
        f"- Reference date: `{report['reference_date']}`",
        f"- Database fingerprint: `{report['database_fingerprint']}`",
        f"- Frontend URL: `{report['frontend_url']}`",
        f"- API/oracle prerequisite diff count: `{report['api_diff_count']}`",
        f"- DOM check count: `{report['dom_check_count']}`",
        f"- DOM diff count: `{report['dom_diff_count']}`",
        f"- Registered value/view contexts: `{coverage['registered_value_contexts']}`",
        f"- Distinct check/view contexts touched by DOM audit: `{coverage['distinct_check_contexts_touched']}`",
        f"- Distinct registered value/view contexts touched by DOM audit: `{coverage['distinct_registered_value_contexts_touched']}`",
        f"- Uncovered registered value/view contexts: `{coverage['uncovered_registered_value_contexts']}`",
        f"- Selector-backed DOM checks: `{coverage['selector_backed_dom_checks']}`",
        f"- Coverage scope: `{coverage['scope']}`",
        f"- Coverage claim: {coverage['claim']}",
        "",
        "## Route Coverage",
        "",
    ]
    for route, count in coverage["routes"].items():
        lines.append(f"- `{route}`: `{count}` rendered text checks")
    lines.extend(["", "## Owner/View Coverage", ""])
    for state, count in coverage["view_states"].items():
        lines.append(f"- `{state}`: `{count}` rendered text checks")
    lines.append("")
    if report["diffs"]:
        lines.append("## Diffs")
        lines.append("")
        for diff in report["diffs"]:
            lines.extend([
                f"### {diff['id']}",
                "",
                f"- Route: `{diff['route']}`",
                f"- View state: `{diff['view_state']}`",
                f"- Classification: `{diff['classification']}`",
                f"- Expected: `{diff['expected']}`",
                f"- Actual: `{diff['actual']}`",
                "",
            ])
    else:
        lines.append("No DOM diffs found.")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit rendered UI text against audited trusted-seed values")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--frontend-url", default=DEFAULT_FRONTEND_URL)
    parser.add_argument("--headed", action="store_true", help="Run Chromium with a visible browser window")
    parser.add_argument("--timeout-ms", type=int, default=15_000)
    parser.add_argument("--settle-ms", type=int, default=1_000)
    args = parser.parse_args()

    db_path = args.db
    if db_path is None and os.environ.get("SENTRY_DB_PATH"):
        db_path = Path(os.environ["SENTRY_DB_PATH"])
    if db_path is None:
        parser.error("--db or SENTRY_DB_PATH is required; there is no implicit audit database")

    report = run_dom_audit(
        db_path=db_path,
        frontend_url=args.frontend_url,
        headless=not args.headed,
        timeout_ms=args.timeout_ms,
        settle_ms=args.settle_ms,
    )
    json_path, md_path = write_reports(report)
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    print(f"DOM diff count: {report['dom_diff_count']}")
    return 1 if report["diff_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
