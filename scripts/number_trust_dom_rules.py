"""Shared DOM expectation builders for the number-trust browser audit."""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import audit_number_trust as api_audit  # noqa: E402

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
    "/investments",
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


def format_parenthesized_percent(value: float | int | None) -> str:
    return f"({format_percent(value)})"


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


def format_quantity(value: float | int | None) -> str:
    formatted = f"{float(value or 0):,.5f}"
    whole, fraction = formatted.split(".")
    fraction = fraction.rstrip("0")
    if len(fraction) < 2:
        fraction = fraction.ljust(2, "0")
    return f"{whole}.{fraction}"


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


DEFAULT_VALUE_FIELDS = {
    "dashboard.net_worth.latest": "net_worth",
    "dashboard.monthly_net_flow": "net",
    "dashboard.emergency_runway": "months_of_runway",
    "dashboard.net_worth.assets": "assets",
    "dashboard.net_worth.liabilities": "liabilities",
    "dashboard.net_worth.velocity_amount": "velocity_amount",
    "dashboard.net_worth.delta_amount": "delta_amount",
    "dashboard.net_worth.delta_percent": "delta_percent",
    "dashboard.monthly_net_flow.savings_rate": "savings_rate",
    "dashboard.monthly_net_flow.dti": "dti_ratio",
    "dashboard.monthly_net_flow.net_debt_change": "net_debt_change",
}


def _rounded_display_value(value: Any, display_precision: float | int | None) -> Any:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or display_precision is None:
        return value
    return api_audit._round_to_display_precision(value, display_precision)


def _field_value(api_value: Any, field: str | None) -> Any:
    if not field:
        return api_value
    if isinstance(api_value, dict):
        return api_value.get(field)
    return None


def _default_field(registry_entry: dict[str, Any]) -> str | None:
    value_id = registry_entry.get("id")
    if value_id in DEFAULT_VALUE_FIELDS:
        return DEFAULT_VALUE_FIELDS[value_id]
    check_id = registry_entry.get("check_id")
    if check_id and value_id and value_id.startswith(f"{check_id}."):
        return value_id[len(check_id) + 1:].replace(".", "_")
    return None


def _format_registry_value(registry_entry: dict[str, Any], value: Any) -> str | None:
    formatter = registry_entry.get("formatter")
    display_value = _rounded_display_value(value, registry_entry.get("display_precision"))
    if display_value is None:
        if formatter == "months_one_decimal":
            return "\u2014"
        if registry_entry.get("empty_state") == "no_data":
            return "No data"
    if formatter == "currency":
        return format_currency(display_value)
    if formatter == "signed_currency":
        return format_signed_currency(display_value)
    if formatter == "currency_per_month":
        return f"{format_currency(display_value)}/mo"
    if formatter == "percent_one_decimal":
        return format_percent(display_value)
    if formatter == "signed_percent_one_decimal":
        return format_signed_percent(display_value)
    if formatter == "months_one_decimal":
        return f"{float(display_value):.1f}"
    if formatter == "integer":
        return str(int(display_value))
    if formatter == "label":
        return str(display_value)
    return str(display_value)


def _dom_expectation(
    registry_entry: dict[str, Any],
    view_state_id: str,
    *,
    field: str,
    expected_text: str | None,
    check_id: str | None = None,
    selector: str | None = None,
    setup: str | None = None,
    selector_all: bool = False,
) -> DomExpectation | None:
    if expected_text is None:
        return None
    resolved_check_id = check_id or registry_entry["check_id"]
    return DomExpectation(
        id=f"{resolved_check_id}.{field}@{view_state_id}",
        check_id=resolved_check_id,
        value_id=registry_entry.get("id"),
        route=registry_entry["route"],
        view_state_id=view_state_id,
        label=registry_entry.get("label") or registry_entry.get("id") or resolved_check_id,
        expected_text=expected_text,
        selector=selector or registry_entry.get("selector"),
        setup=setup,
        selector_all=selector_all,
    )


def default_dom_builder(
    registry_entry: dict[str, Any],
    api_value: Any,
    view_state_id: str,
) -> list[DomExpectation]:
    """Build one selector-backed DOM expectation from declarative registry metadata."""

    field = _default_field(registry_entry)
    expectation = _dom_expectation(
        registry_entry,
        view_state_id,
        field=field or "value",
        expected_text=_format_registry_value(registry_entry, _field_value(api_value, field)),
    )
    return [expectation] if expectation else []


Rule = dict[str, Any]


def _rule(
    field: str | None = None,
    *,
    kind: str = "single",
    format_as: str | None = None,
    selector: str | None = None,
    selector_all: bool = False,
    setup: str | None = None,
    limit: int | None = None,
    item_field: str | None = None,
    slug_field: str | None = None,
    slug_values: str | None = None,
    selector_template: str | None = None,
    empty_text: str | None = None,
    empty_selector: str | None = None,
    skip_if_none: bool = False,
    skip_if_false: str | None = None,
    skip_if_zero: bool = False,
    category_kind: str | None = None,
) -> Rule:
    return {
        key: value
        for key, value in {
            "field": field,
            "kind": kind,
            "format_as": format_as,
            "selector": selector,
            "selector_all": selector_all,
            "setup": setup,
            "limit": limit,
            "item_field": item_field,
            "slug_field": slug_field,
            "slug_values": slug_values,
            "selector_template": selector_template,
            "empty_text": empty_text,
            "empty_selector": empty_selector,
            "skip_if_none": skip_if_none,
            "skip_if_false": skip_if_false,
            "skip_if_zero": skip_if_zero,
            "category_kind": category_kind,
        }.items()
        if value is not None and value is not False
    }


DOM_VALUE_RULES: dict[str, Rule] = {
    "dashboard.spending.current_month_total": _rule("current_month_total"),
    "dashboard.spending.delta_amount": _rule("delta_amount", format_as="currency_abs"),
    "dashboard.spending.delta_percent": _rule("delta_percent", format_as="percent_abs"),
    "dashboard.spending.projected_eom": _rule("projected_eom"),
    "dashboard.spending.per_day": _rule("per_day"),
    "dashboard.budget.spent": _rule("total_spent"),
    "dashboard.budget.total": _rule("total_budgeted"),
    "dashboard.budget.remaining": _rule("total_remaining"),
    "dashboard.budget.progress_percent": _rule("pct_used"),
    "dashboard.budget.top_category_amounts": _rule(
        "categories",
        kind="list_items",
        item_field="spent",
        slug_field="category",
        limit=4,
        selector_template="[data-testid='dashboard-budget-category-amount-{slug}']",
    ),
    "dashboard.recurring.monthly_total": _rule("monthly_total", format_as="currency_per_month_caps"),
    "dashboard.recurring.item_amounts": _rule(
        "item_amounts",
        kind="paired_items",
        slug_values="item_ids",
        selector_template="[data-testid='dashboard-recurring-item-amount-{slug}']",
        empty_text="No recurring bills detected",
        empty_selector="[data-testid='dashboard-recurring-items-empty']",
    ),
    "dashboard.recent_transactions.amounts": _rule(
        kind="indexed_list",
        format_as="signed_currency",
        limit=8,
        selector_template="[data-testid='dashboard-recent-transaction-amount-{idx}']",
        empty_text="No transactions yet",
        empty_selector="[data-testid='dashboard-recent-transactions-empty']",
    ),
    "transactions.table.row_amounts": _rule(
        "row_amounts",
        kind="indexed_list",
        format_as="signed_currency",
        limit=5,
        selector_template="[data-testid='transactions-row-amount-{idx}']",
        empty_text="No transactions found",
        empty_selector="[data-testid='transactions-empty-state']",
    ),
    "transactions.table.row_dates": _rule(
        "row_dates",
        kind="indexed_list",
        format_as="transaction_date",
        limit=3,
        selector_template="[data-testid='transactions-row-date-{idx}']",
        empty_text="No transactions found",
        empty_selector="[data-testid='transactions-empty-state']",
    ),
    "transactions.table.filtered_count": _rule(
        "filtered_count", selector="[data-testid='transactions-filtered-count']"
    ),
    "transactions.table.total_count": _rule(format_as="transactions_pagination"),
    "transactions.pagination.range_start": _rule("range_start"),
    "transactions.pagination.range_end": _rule("range_end"),
    "transactions.filters.active_count": _rule(
        "active_filter_count", selector="[data-testid='transactions-active-filter-count']"
    ),
    "cash_flow.rolling.latest_month": _rule(
        format_as="chart_point_summary",
        selector="[data-testid='cash-flow-rolling-latest-month']",
        skip_if_none=True,
    ),
    "cash_flow.current_month.debt_service_percent": _rule(format_as="debt_service_percent"),
    "cash_flow.current_month.net_debt_change": _rule("net_debt_change", format_as="currency_abs"),
    "cash_flow.categories.income_amounts": _rule(
        kind="cash_flow_categories",
        category_kind="income",
        format_as="currency",
        selector_template="[data-testid='cash-flow-income-category-amount-{slug}']",
    ),
    "cash_flow.categories.income_percents": _rule(
        kind="cash_flow_categories",
        category_kind="income",
        format_as="percent_one_decimal",
        selector_template="[data-testid='cash-flow-income-category-percent-{slug}']",
    ),
    "cash_flow.categories.spending_amounts": _rule(
        kind="cash_flow_categories",
        category_kind="spending",
        format_as="currency",
        selector_template="[data-testid='cash-flow-spending-category-amount-{slug}']",
    ),
    "cash_flow.categories.spending_percents": _rule(
        kind="cash_flow_categories",
        category_kind="spending",
        format_as="percent_one_decimal",
        selector_template="[data-testid='cash-flow-spending-category-percent-{slug}']",
    ),
    "cash_flow.dti.latest_percent": _rule(
        "dti_ratio",
        empty_text="No debt service activity in the trailing window.",
        empty_selector="[data-testid='cash-flow-dti-empty-state']",
    ),
    "cash_flow.dti.debt_payments": _rule(
        "debt_payments",
        empty_text="No debt service activity in the trailing window.",
        empty_selector="[data-testid='cash-flow-dti-empty-state']",
    ),
    "cash_flow.dti.gross_income": _rule(
        "gross_income",
        empty_text="No debt service activity in the trailing window.",
        empty_selector="[data-testid='cash-flow-dti-empty-state']",
    ),
    "cash_flow.chart.monthly_points": _rule(
        kind="collection",
        format_as="chart_point",
        selector="[data-testid='cash-flow-chart-monthly-points']",
        skip_if_none=True,
    ),
    "reports.summary.total_income": _rule("total_income"),
    "reports.summary.total_expenses": _rule("total_spending"),
    "reports.summary.net_income": _rule("net"),
    "reports.summary.savings_rate": _rule("savings_rate"),
    "reports.accountability.accounted_for_percent": _rule(
        "accounted_for_pct",
        format_as="accounted_percent",
        selector="[data-testid='reports-accountability-accounted-for-percent']",
    ),
    "reports.accountability.net_worth_delta": _rule(
        "net_worth_delta_cents",
        format_as="reports_signed_cents",
        selector="[data-testid='reports-accountability-net-worth-delta']",
    ),
    "reports.accountability.unexplained_amount": _rule(
        "unexplained_cents",
        format_as="reports_signed_cents",
        selector="[data-testid='reports-accountability-unexplained-amount']",
        skip_if_zero=True,
    ),
    "reports.accountability.drift_source_count": _rule(
        "drift_source_count",
        selector="[data-testid='reports-accountability-drift-source-count']",
    ),
    "reports.sankey.total_income": _rule("total_income"),
    "reports.sankey.total_spending": _rule("total_spending"),
    "reports.sankey.bucket_totals": _rule(
        "bucket_totals",
        kind="dict_items",
        format_as="currency",
        selector_template="[data-testid='reports-bucket-total-{slug}']",
    ),
    "reports.sankey.bucket_percents": _rule(
        "bucket_percents",
        kind="dict_items",
        format_as="percent_one_decimal",
        selector_template="[data-testid='reports-bucket-percent-{slug}']",
    ),
    "reports.transactions.visible_amounts": _rule(
        kind="indexed_list",
        format_as="signed_currency",
        limit=10,
        selector_template="[data-testid='reports-transaction-amount-{idx}']",
        empty_text="No matching transactions",
        empty_selector="[data-testid='reports-transactions-empty']",
    ),
    "accounts.header.display_total": _rule("display_total"),
    "accounts.header.trend_percent": _rule("trend_percent", format_as="account_trend_percent"),
    "accounts.header.data_through": _rule(
        "data_through",
        format_as="accounts_data_through",
        selector="[data-testid='accounts-header-data-through']",
    ),
    "accounts.groups.totals": _rule(
        "group_totals",
        kind="dict_items",
        format_as="currency",
        selector_template="[data-testid='accounts-group-total-{slug}']",
        empty_text="No accounts in this view",
        empty_selector="[data-testid='accounts-groups-empty']",
    ),
    "accounts.rows.balances": _rule(
        "row_balances",
        kind="collection",
        format_as="currency",
        selector="[data-testid^='accounts-row-balance-']:not([data-testid^='accounts-row-balance-as-of-'])",
        selector_all=True,
        empty_text="No accounts in this view",
        empty_selector="[data-testid='accounts-groups-empty']",
    ),
    "accounts.rows.balance_as_of": _rule(
        "row_balance_as_of",
        kind="collection",
        format_as="short_date",
        selector="[data-testid^='accounts-row-balance-as-of-']",
        selector_all=True,
        empty_text="No accounts in this view",
        empty_selector="[data-testid='accounts-groups-empty']",
    ),
    "accounts.rows.apr": _rule(
        "apr",
        kind="collection_or_empty_selector",
        format_as="apr",
        selector="[data-testid^='accounts-row-apr-']",
    ),
    "accounts.rows.rewards_points": _rule(
        "rewards_points",
        kind="collection_or_empty_selector",
        format_as="rewards_points",
        selector="[data-testid^='accounts-row-rewards-points-']",
    ),
    "accounts.rows.installment_paid_percent": _rule(
        "installment_paid_percent",
        kind="collection_or_empty_selector",
        format_as="installment_percent",
        selector="[data-testid^='accounts-row-installment-paid-percent-']",
    ),
    "accounts.rows.credit_utilization_percent": _rule(
        "credit_utilization_percent",
        kind="collection_or_empty_selector",
        format_as="percent_zero_decimal",
        selector="[data-testid^='accounts-row-credit-utilization-percent-']",
    ),
    "accounts.summary.assets_total": _rule("summary.assets_total"),
    "accounts.summary.liabilities_total": _rule("summary.liabilities_total"),
    "accounts.summary.bucket_totals": _rule(
        "summary.bucket_totals",
        kind="dict_items",
        format_as="currency",
        selector_template="[data-testid='accounts-summary-bucket-{slug}']",
        setup="accounts_summary_totals",
        empty_text="No asset buckets",
        empty_selector="[data-testid='accounts-summary-buckets-empty']",
    ),
    "accounts.summary.bucket_percents": _rule(
        "summary.bucket_percents",
        kind="dict_items",
        format_as="percent_one_decimal",
        selector_template="[data-testid='accounts-summary-bucket-{slug}']",
        setup="accounts_summary_percent",
        empty_text="No asset buckets",
        empty_selector="[data-testid='accounts-summary-buckets-empty']",
    ),
    "investments.overview.total_value": _rule("total_value", setup="investments_overview_all"),
    "investments.overview.change_abs": _rule(
        "change_abs", format_as="currency_abs", setup="investments_overview_all"
    ),
    "investments.overview.change_pct": _rule("change_pct", setup="investments_overview_all"),
    "investments.overview.asset_class_count": _rule("asset_class_count", setup="investments_overview_all"),
    "investments.overview.asset_class_amounts": _rule(
        "asset_class_amounts", kind="collection", format_as="currency", selector_all=True, setup="investments_overview_all"
    ),
    "investments.overview.asset_class_pcts": _rule(
        "asset_class_pcts", kind="collection", format_as="percent_one_decimal", selector_all=True, setup="investments_overview_all"
    ),
    "investments.overview.tax_treatment_amounts": _rule(
        "tax_treatment_amounts", kind="collection", format_as="currency", selector_all=True, setup="investments_overview_all"
    ),
    "investments.overview.tax_treatment_pcts": _rule(
        "tax_treatment_pcts", kind="collection", format_as="parenthesized_percent", selector_all=True, setup="investments_overview_all"
    ),
    "investments.overview.performance_empty": _rule(
        "performance_empty",
        format_as="constant:No performance data available",
        setup="investments_overview_all",
        skip_if_false="performance_empty",
    ),
    "investments.holdings.prices": _rule("prices", kind="collection", format_as="currency", selector_all=True, setup="investments_tab_holdings"),
    "investments.holdings.quantities": _rule("quantities", kind="collection", format_as="quantity", selector_all=True, setup="investments_tab_holdings"),
    "investments.holdings.values": _rule("values", kind="collection", format_as="currency", selector_all=True, setup="investments_tab_holdings"),
    "investments.holdings.portfolio_pcts": _rule("portfolio_pcts", kind="collection", format_as="percent_one_decimal", selector_all=True, setup="investments_tab_holdings"),
    "investments.holdings.empty_state": _rule(
        "empty",
        format_as="constant:No positions found for this account filter.",
        setup="investments_tab_holdings",
        skip_if_false="empty",
    ),
    "investments.allocation.total_value": _rule("total_value", setup="investments_tab_allocation"),
    "investments.allocation.asset_class_amounts": _rule("asset_class_amounts", kind="collection", format_as="currency", selector_all=True, setup="investments_tab_allocation"),
    "investments.allocation.asset_class_pcts": _rule("asset_class_pcts", kind="collection", format_as="percent_one_decimal", selector_all=True, setup="investments_tab_allocation"),
    "investments.allocation.sector_amounts": _rule("sector_amounts", kind="collection", format_as="currency", selector_all=True, setup="investments_tab_allocation"),
    "investments.allocation.sector_pcts": _rule("sector_pcts", kind="collection", format_as="percent_one_decimal", selector_all=True, setup="investments_tab_allocation"),
    "investments.allocation.geography_amounts": _rule("geography_amounts", kind="collection", format_as="currency", selector_all=True, setup="investments_tab_allocation"),
    "investments.allocation.geography_pcts": _rule("geography_pcts", kind="collection", format_as="percent_one_decimal", selector_all=True, setup="investments_tab_allocation"),
    "investments.allocation.market_cap_amounts": _rule("market_cap_amounts", kind="collection", format_as="currency", selector_all=True, setup="investments_tab_allocation"),
    "investments.allocation.market_cap_pcts": _rule("market_cap_pcts", kind="collection", format_as="percent_one_decimal", selector_all=True, setup="investments_tab_allocation"),
    "investments.allocation.empty_state": _rule(
        "empty",
        format_as="constant:No allocation data available",
        setup="investments_tab_allocation",
        skip_if_false="empty",
    ),
    "budgets.summary.safe_to_spend": _rule("total_remaining"),
    "budgets.summary.total_assigned": _rule("total_assigned"),
    "budgets.summary.total_spent": _rule("total_spent"),
    "budgets.summary.percent_used": _rule("pct_used"),
    "budgets.summary.days_left": _rule("days_left"),
    "budgets.summary.daily_allowance": _rule("daily_allowance"),
    "budgets.summary.active_count": _rule("active_count"),
    "budgets.categories.row_spent": _rule(
        kind="list_items", item_field="actual", slug_field="category", selector_template="[data-testid='budgets-category-spent-{slug}']", empty_text="No budgets for", empty_selector=None
    ),
    "budgets.categories.row_target": _rule(
        kind="list_items", item_field="target", slug_field="category", selector_template="[data-testid='budgets-category-target-{slug}']", empty_text="No budgets for", empty_selector=None
    ),
    "budgets.categories.row_remaining": _rule(
        kind="list_items", format_as="budget_remaining", slug_field="category", selector_template="[data-testid='budgets-category-remaining-{slug}']", empty_text="No budgets for", empty_selector=None
    ),
    "review.monthly.income_total": _rule("income_total"),
    "review.monthly.spending_total": _rule("spending_total"),
    "review.monthly.savings_rate": _rule("savings_rate"),
    "review.monthly.net_worth_delta_amount": _rule("net_worth_delta.amount", format_as="review_signed_currency"),
    "review.monthly.net_worth_delta_percent": _rule("net_worth_delta.pct", format_as="review_signed_percent"),
    "review.monthly.cash_surplus": _rule("cash_surplus", format_as="review_signed_currency"),
    "review.monthly.uncategorized_count": _rule("uncategorized_count", format_as="integer_or_all_categorized"),
    "review.monthly.pretax.gross_income": _rule("pre_tax.gross_income", skip_if_none=True),
    "review.monthly.pretax.federal_tax": _rule("pre_tax.federal_tax", format_as="pretax_negative_compact", skip_if_none=True),
    "review.monthly.pretax.state_tax": _rule("pre_tax.state_tax", format_as="pretax_negative_compact", skip_if_none=True),
    "review.monthly.pretax.net_pay": _rule("pre_tax.net_pay", skip_if_none=True),
    "review.monthly.pretax.savings_rate": _rule("pre_tax.savings_rate_pct", skip_if_none=True),
    "review.monthly.budget_highlights": _rule("budget_highlight_actuals", kind="collection", format_as="currency", selector_all=True),
    "review.monthly.notable_transactions": _rule(
        "notable_transaction_amounts",
        kind="indexed_list",
        format_as="currency",
        selector_template="[data-testid='monthly-review-notable-transaction-amount-{idx}']",
    ),
    "review.yearly.total_income": _rule("total_income"),
    "review.yearly.total_spending": _rule("total_spending"),
    "review.yearly.savings_rate": _rule("savings_rate"),
    "review.yearly.net_interest_cost": _rule("interest_net_cost"),
    "review.yearly.status": _rule("status", format_as="wrapup_status"),
    "review.yearly.tax_doc_count": _rule(format_as="tax_doc_count", skip_if_false="tax_doc_expected"),
    "review.yearly.effective.gross_income": _rule("effective_tax.gross_income", skip_if_none=True),
    "review.yearly.effective.federal_tax": _rule("effective_tax.federal_tax", skip_if_none=True),
    "review.yearly.effective.state_tax": _rule("effective_tax.state_tax", skip_if_none=True),
    "review.yearly.effective.rate_pct": _rule("effective_tax.effective_rate_pct", skip_if_none=True),
    "review.yearly.interest.paid": _rule("interest_paid"),
    "review.yearly.interest.earned": _rule("interest_earned"),
    "review.yearly.interest.net_cost": _rule("interest_net_cost"),
    "review.yearly.income_by_stream": _rule("income_by_stream_amounts", kind="collection", format_as="currency", selector_all=True),
    "review.yearly.spending_by_category": _rule("spending_by_category_amounts", kind="collection", format_as="currency", selector_all=True),
}


def _get_path(value: Any, field: str | None) -> Any:
    if field is None:
        return value
    current = value
    for part in field.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _format_rule_value(formatter: str, value: Any, source: Any, rule: Rule) -> str:
    if formatter.startswith("constant:"):
        return formatter.split(":", 1)[1]
    if formatter == "currency":
        return format_currency(value)
    if formatter == "signed_currency":
        return format_signed_currency(value)
    if formatter == "currency_abs":
        return format_currency(abs(float(value or 0)))
    if formatter == "currency_per_day":
        return format_currency(value)
    if formatter == "currency_per_month":
        return f"{format_currency(value)}/mo"
    if formatter == "currency_per_month_caps":
        return f"{format_currency(value)} /MO"
    if formatter == "compact_currency":
        return format_compact_currency(value)
    if formatter == "pretax_negative_compact":
        return format_pretax_negative_compact(value)
    if formatter == "review_signed_currency":
        return format_review_signed_currency(value)
    if formatter == "percent_one_decimal":
        return format_percent(value)
    if formatter == "percent_abs":
        return format_percent(abs(float(value or 0)))
    if formatter == "percent_zero_decimal":
        return format_percent_zero(value)
    if formatter == "signed_percent_one_decimal":
        return format_signed_percent(value)
    if formatter == "review_signed_percent":
        return format_review_signed_percent(value)
    if formatter == "parenthesized_percent":
        return format_parenthesized_percent(value)
    if formatter == "integer":
        return str(int(value or 0))
    if formatter == "integer_or_all_categorized":
        return "All transactions categorized" if not value else str(int(value))
    if formatter == "label":
        return str(value)
    if formatter == "quantity":
        return format_quantity(value)
    if formatter == "transaction_date":
        return format_transaction_date(str(value))
    if formatter == "transactions_pagination":
        return (
            f"Showing {(source or {}).get('range_start', 0)}-"
            f"{(source or {}).get('range_end', 0)} of "
            f"{(source or {}).get('total_count', 0)} transactions"
        )
    if formatter == "short_date":
        return format_short_date(value)
    if formatter == "chart_point":
        return format_chart_point(value)
    if formatter == "chart_point_summary":
        return format_chart_point({"label": "Latest", **(source or {})}).replace("Latest: ", "")
    if formatter == "debt_service_percent":
        spending = float((source or {}).get("spending") or 0)
        debt_service = float((source or {}).get("debt_service") or 0)
        return format_percent(round((debt_service / spending) * 100, 1) if spending else 0.0)
    if formatter == "accounted_percent":
        return format_percent(float(value or 0) * 100)
    if formatter == "reports_signed_cents":
        return format_reports_signed_cents(value)
    if formatter == "account_trend_percent":
        if (source or {}).get("display_total") or (source or {}).get("trend_percent"):
            return format_signed_percent(value)
        return "+0.0%"
    if formatter == "accounts_data_through":
        return "AS OF LAST REFRESH" if not value else str(value)
    if formatter == "apr":
        return f"{float(value):g}% APR"
    if formatter == "rewards_points":
        return f"redeem {int(value):,} pts"
    if formatter == "installment_percent":
        return f"{int(value)}% paid off"
    if formatter == "budget_remaining":
        return "Over budget" if (value or {}).get("status") == "over" else f"{format_currency(abs(float((value or {}).get('remaining') or 0)))} left"
    if formatter == "wrapup_status":
        status = value or "preliminary"
        return WRAPUP_STATUS_LABELS.get(status, str(status).title())
    if formatter == "tax_doc_count":
        return f"{(source or {}).get('tax_doc_received', 0)}/{(source or {}).get('tax_doc_expected', 0)}"
    return str(value)


def _formatter_for(entry: dict[str, Any], rule: Rule) -> str:
    formatter = rule.get("format_as") or entry.get("formatter") or "label"
    return str(formatter).removesuffix("_collection")


def _expectation_for_rule(
    entry: dict[str, Any],
    view_state_id: str,
    rule: Rule,
    *,
    field: str,
    expected_text: str | None,
    selector: str | None = None,
    selector_all: bool | None = None,
) -> DomExpectation | None:
    return _dom_expectation(
        entry,
        view_state_id,
        field=field,
        expected_text=expected_text,
        selector=selector if selector is not None else rule.get("selector"),
        setup=rule.get("setup"),
        selector_all=rule.get("selector_all", False) if selector_all is None else selector_all,
    )


def _empty_expectation(entry: dict[str, Any], view_state_id: str, rule: Rule, field: str) -> list[DomExpectation]:
    if "empty_text" not in rule:
        return []
    expectation = _expectation_for_rule(
        entry,
        view_state_id,
        rule,
        field=field,
        expected_text=rule["empty_text"],
        selector=rule.get("empty_selector"),
        selector_all=False,
    )
    return [expectation] if expectation else []


def build_rule_expectations(
    registry_entry: dict[str, Any],
    api_value: Any,
    view_state_id: str,
    _checks: dict[str, dict[str, Any]],
) -> list[DomExpectation]:
    rule = DOM_VALUE_RULES.get(registry_entry["id"])
    if not rule:
        field = _default_field(registry_entry)
        if not field:
            raise RuntimeError(f"missing DOM value rule for {registry_entry['id']}")
        rule = _rule(field)
    if rule.get("skip_if_false") and not _get_path(api_value, rule["skip_if_false"]):
        return []

    kind = rule.get("kind", "single")
    formatter = _formatter_for(registry_entry, rule)
    source = _get_path(api_value, rule.get("field"))
    if rule.get("skip_if_none") and source is None:
        return []
    if rule.get("skip_if_zero") and not source:
        return []

    if kind == "collection":
        values = source or []
        if not values:
            empty = _empty_expectation(registry_entry, view_state_id, rule, "empty_state")
            if empty:
                return empty
        expected = join_text([_format_rule_value(formatter, value, api_value, rule) for value in values])
        expectation = _expectation_for_rule(
            registry_entry,
            view_state_id,
            rule,
            field=str(rule.get("field") or "collection"),
            expected_text=expected,
        )
        return [expectation] if expectation else []

    if kind == "collection_or_empty_selector":
        values = source or []
        if values:
            expected = join_text([_format_rule_value(formatter, value, api_value, rule) for value in values])
            selector = rule.get("selector")
        else:
            expected = "No accounts in this view" if not (api_value or {}).get("row_balances") else ""
            selector = "[data-testid='accounts-groups-empty']" if not (api_value or {}).get("row_balances") else rule.get("selector")
        expectation = _expectation_for_rule(
            registry_entry,
            view_state_id,
            rule,
            field=str(rule.get("field") or "collection"),
            expected_text=expected,
            selector=selector,
            selector_all=bool(values or (api_value or {}).get("row_balances")),
        )
        return [expectation] if expectation else []

    if kind == "indexed_list":
        values = source if rule.get("field") else api_value
        values = list(values or [])[: rule.get("limit") or len(values or [])]
        if not values:
            return _empty_expectation(registry_entry, view_state_id, rule, "empty_state")
        expectations: list[DomExpectation] = []
        for idx, value in enumerate(values, start=1):
            expectation = _expectation_for_rule(
                registry_entry,
                view_state_id,
                rule,
                field=f"{rule.get('field') or 'item'}_{idx}",
                expected_text=_format_rule_value(formatter, value, api_value, rule),
                selector=str(rule["selector_template"]).format(idx=idx),
                selector_all=False,
            )
            if expectation:
                expectations.append(expectation)
        return expectations

    if kind == "paired_items":
        values = list(_get_path(api_value, rule.get("field")) or [])
        slugs = list(_get_path(api_value, rule.get("slug_values")) or [])
        if not values:
            return _empty_expectation(registry_entry, view_state_id, rule, "empty_state")
        expectations = []
        for idx, (value, item_id) in enumerate(zip(values, slugs, strict=False), start=1):
            expectation = _expectation_for_rule(
                registry_entry,
                view_state_id,
                rule,
                field=f"item_{idx}",
                expected_text=_format_rule_value(formatter, value, api_value, rule),
                selector=str(rule["selector_template"]).format(slug=_test_id_part(item_id)),
                selector_all=False,
            )
            if expectation:
                expectations.append(expectation)
        return expectations

    if kind == "list_items":
        rows_source = source if rule.get("field") else api_value
        rows = list(rows_source or [])
        rows = rows[: rule.get("limit") or len(rows)]
        if not rows:
            return _empty_expectation(registry_entry, view_state_id, rule, "empty_state")
        expectations = []
        for row in rows:
            slug = _test_id_part(row.get(rule.get("slug_field") or "category"))
            value = row if formatter == "budget_remaining" else row.get(rule.get("item_field"))
            expectation = _expectation_for_rule(
                registry_entry,
                view_state_id,
                rule,
                field=f"{registry_entry['id']}.{slug}",
                expected_text=_format_rule_value(formatter, value, api_value, rule),
                selector=str(rule["selector_template"]).format(slug=slug),
                selector_all=False,
            )
            if expectation:
                expectations.append(expectation)
        return expectations

    if kind == "dict_items":
        values = source or {}
        if not values:
            return _empty_expectation(registry_entry, view_state_id, rule, "empty_state")
        expectations = []
        for key, value in values.items():
            slug = _test_id_part(key)
            expectation = _expectation_for_rule(
                registry_entry,
                view_state_id,
                rule,
                field=f"{rule.get('field')}.{slug}",
                expected_text=_format_rule_value(formatter, value, api_value, rule),
                selector=str(rule["selector_template"]).format(slug=slug),
                selector_all=False,
            )
            if expectation:
                expectations.append(expectation)
        return expectations

    if kind == "cash_flow_categories":
        category_kind = rule["category_kind"]
        total = float((api_value or {}).get(category_kind) or 0)
        expectations = []
        for category in (api_value or {}).get(f"{category_kind}_categories") or []:
            amount = float(category.get("total") or 0)
            value = round((amount / total) * 100, 1) if formatter == "percent_one_decimal" and total else amount
            if formatter == "percent_one_decimal" and not total:
                value = float(category.get("pct") or 0)
            slug = _test_id_part(category.get("category"))
            expectation = _expectation_for_rule(
                registry_entry,
                view_state_id,
                rule,
                field=f"{category_kind}.{slug}",
                expected_text=_format_rule_value(formatter, value, api_value, rule),
                selector=str(rule["selector_template"]).format(slug=slug),
                selector_all=False,
            )
            if expectation:
                expectations.append(expectation)
        return expectations

    if api_value is None and "empty_text" in rule:
        return _empty_expectation(registry_entry, view_state_id, rule, "empty_state")

    expected = _format_rule_value(formatter, source, api_value, rule)
    expectation = _expectation_for_rule(
        registry_entry,
        view_state_id,
        rule,
        field=str(rule.get("field") or "value"),
        expected_text=expected,
    )
    return [expectation] if expectation else []


