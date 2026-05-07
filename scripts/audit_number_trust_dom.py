"""Browser DOM audit for first-pass number-trust values.

This script extends the raw-fact/API/second-language audit with a selector-
backed rendered UI check for every registered value/view context on the
scoped number-trust pages (Dashboard, Transactions, Cash Flow, Reports,
Accounts, Budgets, Reviews, and Investments).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import audit_number_trust as api_audit  # noqa: E402
from scripts.number_trust_dom_rules import (  # noqa: E402
    DomExpectation,
    ROUTE_ORDER,
    VIEW_TO_FRONTEND_VALUE,
    _actual,
    _checks_by_id,
    _credit_score_selector,
    _default_field,
    _dom_expectation,
    _field_value,
    _format_registry_value,
    _scoped_id,
    _text_hash,
    _test_id_part,
    build_rule_expectations,
    default_dom_builder,
    format_currency,
    format_freshness_states,
    format_percent,
    format_reports_signed_cents,
    format_signed_currency,
    join_text,
    normalize_text,
)

REPORT_DIR = ROOT / "docs" / "audits" / "number-trust" / "reports"
DEFAULT_FRONTEND_URL = "http://127.0.0.1:1420"

DomBuilder = Callable[[dict[str, Any], Any, str, dict[str, dict[str, Any]]], list[DomExpectation]]


def _default_builder_adapter(
    registry_entry: dict[str, Any],
    api_value: Any,
    view_state_id: str,
    _checks: dict[str, dict[str, Any]],
) -> list[DomExpectation]:
    return default_dom_builder(registry_entry, api_value, view_state_id)


def _build_net_worth_detail_disclosure(
    registry_entry: dict[str, Any],
    api_value: Any,
    view_state_id: str,
    _checks: dict[str, dict[str, Any]],
) -> list[DomExpectation]:
    field = _default_field(registry_entry)
    value = _field_value(api_value, field)
    if registry_entry.get("id") == "dashboard.net_worth.liabilities":
        value = abs(float(value or 0))
    expectation = _dom_expectation(
        registry_entry,
        view_state_id,
        field=field or "value",
        expected_text=_format_registry_value(registry_entry, value),
        setup="dashboard_net_worth_details_open",
    )
    return [expectation] if expectation else []


def _build_dashboard_dti_pill(
    registry_entry: dict[str, Any],
    api_value: Any,
    view_state_id: str,
    _checks: dict[str, dict[str, Any]],
) -> list[DomExpectation]:
    if api_value:
        field = "dashboard_dti"
        expected_text = format_percent(api_value.get("dti_ratio"))
    else:
        field = "dashboard_dti_empty"
        expected_text = "No DTI data"
    expectation = _dom_expectation(registry_entry, view_state_id, field=field, expected_text=expected_text)
    return [expectation] if expectation else []


def _build_emergency_runway_summary(
    registry_entry: dict[str, Any],
    api_value: Any,
    view_state_id: str,
    _checks: dict[str, dict[str, Any]],
) -> list[DomExpectation]:
    runway = api_value or {}
    if runway.get("months_of_runway") is None:
        expectation = _dom_expectation(
            registry_entry,
            view_state_id,
            field="months_of_runway_empty",
            expected_text="\u2014",
        )
        return [expectation] if expectation else []

    expectations = default_dom_builder(registry_entry, api_value, view_state_id)
    expectations.append(
        DomExpectation(
            id=f"{registry_entry['check_id']}.avg_monthly_spending@{view_state_id}",
            check_id=registry_entry["check_id"],
            value_id=None,
            route=registry_entry["route"],
            view_state_id=view_state_id,
            label="Dashboard runway average monthly spend",
            expected_text=format_currency(runway.get("avg_monthly_spending")),
            selector="[data-testid='dashboard-runway-avg-spend']",
        )
    )
    return expectations


def _build_dashboard_net_debt_change(
    registry_entry: dict[str, Any],
    api_value: Any,
    view_state_id: str,
    checks: dict[str, dict[str, Any]],
) -> list[DomExpectation]:
    expectations: list[DomExpectation] = []
    net_debt_change = (api_value or {}).get("net_debt_change") if isinstance(api_value, dict) else None
    if net_debt_change is not None and abs(float(net_debt_change or 0)) >= 10:
        expectation = _dom_expectation(
            registry_entry,
            view_state_id,
            field="net_debt_change",
            expected_text=format_signed_currency(net_debt_change),
        )
    else:
        expectation = _dom_expectation(
            registry_entry,
            view_state_id,
            field="net_debt_change_empty",
            expected_text="+$0.00 debt",
        )
    if expectation:
        expectations.append(expectation)

    rolling_latest = _actual(checks, "cash_flow.rolling.latest_month", view_state_id) or {}
    rolling_change = rolling_latest.get("net_debt_change")
    if rolling_change is not None and abs(float(rolling_change or 0)) >= 10:
        rolling_expectation = _dom_expectation(
            registry_entry,
            view_state_id,
            check_id="cash_flow.rolling.latest_month",
            field="dashboard_net_debt_change",
            expected_text=format_signed_currency(rolling_change),
        )
        if rolling_expectation:
            expectations.append(rolling_expectation)
    return expectations


def _build_credit_score_multiselect(
    registry_entry: dict[str, Any],
    api_value: Any,
    view_state_id: str,
    _checks: dict[str, dict[str, Any]],
) -> list[DomExpectation]:
    expectations: list[DomExpectation] = []
    credit_scores = api_value or []
    if credit_scores:
        for idx, score in enumerate(credit_scores[:2], start=1):
            expectation = _dom_expectation(
                registry_entry,
                view_state_id,
                field=f"score_{idx}",
                expected_text=str(score.get("score")),
                selector=_credit_score_selector(score),
            )
            if expectation:
                expectations.append(expectation)
    else:
        expectation = _dom_expectation(
            registry_entry,
            view_state_id,
            field="empty_state",
            expected_text="No scores available",
            selector="[data-testid='dashboard-credit-score-empty']",
        )
        if expectation:
            expectations.append(expectation)
    return expectations


def _build_freshness_state_summary(
    registry_entry: dict[str, Any],
    api_value: Any,
    view_state_id: str,
    _checks: dict[str, dict[str, Any]],
) -> list[DomExpectation]:
    expectation = _dom_expectation(
        registry_entry,
        view_state_id,
        field="state_labels",
        expected_text=format_freshness_states(api_value or []),
        selector="[data-testid='dashboard-freshness-state-labels']",
    )
    return [expectation] if expectation else []


def _build_dashboard_supporting_metric(*args: Any) -> list[DomExpectation]:
    return build_rule_expectations(*args)


def _build_transactions_table_metric(*args: Any) -> list[DomExpectation]:
    return build_rule_expectations(*args)


def _build_cash_flow_metric(*args: Any) -> list[DomExpectation]:
    return build_rule_expectations(*args)


def _build_reports_metric(*args: Any) -> list[DomExpectation]:
    return build_rule_expectations(*args)


def _build_accounts_metric(*args: Any) -> list[DomExpectation]:
    return build_rule_expectations(*args)


def _build_investments_metric(*args: Any) -> list[DomExpectation]:
    return build_rule_expectations(*args)


def _build_budgets_metric(*args: Any) -> list[DomExpectation]:
    return build_rule_expectations(*args)


def _build_monthly_review_metric(*args: Any) -> list[DomExpectation]:
    return build_rule_expectations(*args)


def _build_yearly_review_metric(*args: Any) -> list[DomExpectation]:
    return build_rule_expectations(*args)


_dom_builders: dict[str, DomBuilder] = {
    "default": _default_builder_adapter,
    "accounts_metric": _build_accounts_metric,
    "budgets_metric": _build_budgets_metric,
    "cash_flow_metric": _build_cash_flow_metric,
    "credit_score_multiselect": _build_credit_score_multiselect,
    "dashboard_dti_pill": _build_dashboard_dti_pill,
    "dashboard_net_debt_change": _build_dashboard_net_debt_change,
    "dashboard_supporting_metric": _build_dashboard_supporting_metric,
    "emergency_runway_summary": _build_emergency_runway_summary,
    "freshness_state_summary": _build_freshness_state_summary,
    "investments_metric": _build_investments_metric,
    "monthly_review_metric": _build_monthly_review_metric,
    "net_worth_detail_disclosure": _build_net_worth_detail_disclosure,
    "reports_metric": _build_reports_metric,
    "transactions_table_metric": _build_transactions_table_metric,
    "yearly_review_metric": _build_yearly_review_metric,
}


def referenced_dom_builders(registry: dict[str, Any] | None = None) -> set[str]:
    registry = registry or api_audit._load_registry()
    return {
        value["dom_builder"]
        for surface in registry.get("surfaces") or []
        for value in surface.get("values") or []
        if value.get("audit_stage") == "api_oracle" and value.get("dom_builder")
    }


def orphan_dom_builders(registry: dict[str, Any] | None = None) -> list[str]:
    referenced = referenced_dom_builders(registry)
    return sorted(set(_dom_builders) - {"default"} - referenced)


def _registry_surface_entries(surface_id: str, view_state_id: str) -> list[dict[str, Any]]:
    registry = api_audit._load_registry()
    entries: list[dict[str, Any]] = []
    for surface in registry.get("surfaces") or []:
        if surface.get("id") != surface_id:
            continue
        for value in surface.get("values") or []:
            if value.get("audit_stage") != "api_oracle":
                continue
            if view_state_id not in (value.get("view_states") or []):
                continue
            entries.append({
                **value,
                "surface_id": surface.get("id"),
                "page": surface.get("page"),
                "route": surface.get("route"),
            })
    return entries


def _build_registry_surface_dom_expectations(
    surface_id: str,
    checks: dict[str, dict[str, Any]],
    view_state_id: str,
) -> list[DomExpectation]:
    expectations: list[DomExpectation] = []
    for entry in _registry_surface_entries(surface_id, view_state_id):
        builder_name = entry.get("dom_builder") or "default"
        builder = _dom_builders.get(builder_name)
        if not builder:
            raise RuntimeError(f"unknown DOM builder {builder_name!r} for {entry.get('id')}")
        expectations.extend(
            builder(entry, _actual(checks, entry["check_id"], view_state_id), view_state_id, checks)
        )
    return expectations


def build_dom_expectations(api_report: dict[str, Any]) -> list[DomExpectation]:
    """Build selector-backed DOM expectations from registry-declared builders."""

    checks = _checks_by_id(api_report)
    view_states = [
        state["id"]
        for state in (api_report.get("registry") or {}).get("view_states", [])
        if state.get("id") in VIEW_TO_FRONTEND_VALUE
    ]
    registry = api_audit._load_registry()
    surface_ids = [surface.get("id") for surface in registry.get("surfaces") or []]
    expectations: list[DomExpectation] = []

    for view_state_id in view_states:
        for surface_id in surface_ids:
            if surface_id:
                expectations.extend(
                    _build_registry_surface_dom_expectations(surface_id, checks, view_state_id)
                )

    route_index = {route: idx for idx, route in enumerate(ROUTE_ORDER)}
    view_index = {view: idx for idx, view in enumerate(VIEW_TO_FRONTEND_VALUE)}
    setup_index = {
        None: 0,
        "dashboard_net_worth_details_open": 1,
        "accounts_summary_totals": 1,
        "accounts_summary_percent": 2,
        "investments_overview_all": 0,
        "investments_tab_holdings": 1,
        "investments_tab_allocation": 2,
    }
    return sorted(
        expectations,
        key=lambda item: (
            route_index.get(item.route, 99),
            view_index.get(item.view_state_id, 99),
            setup_index.get(item.setup, 0),
            item.id,
        ),
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


def _click_pressed_control(page: Any, selector: str, timeout_ms: int) -> None:
    page.locator(selector).click(timeout=timeout_ms)
    page.wait_for_function(
        """selector => {
            const el = document.querySelector(selector);
            return el && el.getAttribute("aria-pressed") === "true";
        }""",
        arg=selector,
        timeout=timeout_ms,
    )


def _wait_for_expectation_selector(
    page: Any,
    expectation: DomExpectation,
    timeout_ms: int,
) -> None:
    if not expectation.selector:
        return
    locator = page.locator(expectation.selector)
    if expectation.selector_all:
        if expectation.expected_text:
            locator.first.wait_for(timeout=min(timeout_ms, 8_000))
        return
    locator.wait_for(timeout=min(timeout_ms, 8_000))
    if expectation.expected_text:
        page.wait_for_function(
            """({ selector, expected }) => {
                const el = document.querySelector(selector);
                if (!el) return false;
                const text = (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim();
                return text.includes(expected);
            }""",
            arg={"selector": expectation.selector, "expected": expectation.expected_text},
            timeout=min(timeout_ms, 8_000),
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
    elif expectation.setup == "investments_overview_all":
        _click_pressed_control(page, "[data-testid='investments-tab-overview']", timeout_ms)
        _click_pressed_control(page, "[data-testid='investments-timeframe-all']", timeout_ms)
        _wait_for_expectation_selector(page, expectation, timeout_ms)
    elif expectation.setup == "investments_tab_holdings":
        _click_pressed_control(page, "[data-testid='investments-tab-holdings']", timeout_ms)
        _wait_for_expectation_selector(page, expectation, timeout_ms)
    elif expectation.setup == "investments_tab_allocation":
        _click_pressed_control(page, "[data-testid='investments-tab-allocation']", timeout_ms)
        _wait_for_expectation_selector(page, expectation, timeout_ms)


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
                "across the scoped pages (Dashboard, Transactions, Cash Flow, Reports, Accounts, Investments, Budgets, Reviews)."
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

    orphans = orphan_dom_builders()
    if orphans:
        print(f"Unreferenced DOM builders: {', '.join(orphans)}", file=sys.stderr)
        return 1

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
