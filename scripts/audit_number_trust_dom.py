"""Browser DOM audit for first-pass number-trust values.

This script extends the raw-fact/API/second-language audit with a selector-
backed rendered UI check. It intentionally starts with high-signal,
always-visible values on the five scoped pages. It does not yet claim per-value
selector coverage for every registered number; the report records that
distinction explicitly.
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
ROUTE_ORDER = ["/dashboard", "/transactions", "/cash-flow", "/reports", "/accounts"]
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass(frozen=True)
class DomExpectation:
    id: str
    check_id: str
    route: str
    view_state_id: str
    label: str
    expected_text: str
    selector: str | None = None


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


def format_transaction_date(iso_date: str) -> str:
    year, month, day = iso_date.split("-")
    return f"{MONTH_ABBR[int(month) - 1]} {int(day)}, {year}"


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
    route: str,
    view_state_id: str,
    field: str,
    label: str,
    expected_text: str | None,
    selector: str | None = None,
) -> None:
    if expected_text is None:
        return
    expectations.append(
        DomExpectation(
            id=f"{check_id}.{field}@{view_state_id}",
            check_id=check_id,
            route=route,
            view_state_id=view_state_id,
            label=label,
            expected_text=expected_text,
            selector=selector,
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
            route="/dashboard",
            view_state_id=view_state_id,
            field="net_worth",
            label="Dashboard net worth",
            expected_text=format_currency((net_worth or {}).get("net_worth")),
            selector="[data-testid='dashboard-net-worth-latest']",
        )

        monthly_flow = _actual(checks, "dashboard.monthly_net_flow", view_state_id) or {}
        _add(
            expectations,
            check_id="dashboard.monthly_net_flow",
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
            route="/dashboard",
            view_state_id=view_state_id,
            field="savings_rate",
            label="Dashboard savings rate",
            expected_text=format_percent(monthly_flow.get("savings_rate")),
            selector="[data-testid='dashboard-monthly-savings-rate']",
        )

        runway = _actual(checks, "dashboard.emergency_runway", view_state_id) or {}
        if runway.get("months_of_runway") is not None:
            _add(
                expectations,
                check_id="dashboard.emergency_runway",
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
                route="/dashboard",
                view_state_id=view_state_id,
                field="avg_monthly_spending",
                label="Dashboard runway average monthly spend",
                expected_text=format_currency(runway.get("avg_monthly_spending")),
                selector="[data-testid='dashboard-runway-avg-spend']",
            )

        credit_scores = _actual(checks, "dashboard.credit_scores.latest", view_state_id) or []
        if credit_scores:
            for idx, score in enumerate(credit_scores[:2], start=1):
                _add(
                    expectations,
                    check_id="dashboard.credit_scores.latest",
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
                route="/dashboard",
                view_state_id=view_state_id,
                field="empty_state",
                label="Dashboard credit-score empty state",
                expected_text="No scores available",
                selector="[data-testid='dashboard-credit-score-empty']",
            )

        # Cash Flow: current active period KPI row.
        cash_flow = _actual(checks, "cash_flow.current_month", view_state_id) or {}
        for field, label, formatter, selector in [
            ("income", "Cash Flow income", format_currency, "[data-testid='cash-flow-current-income']"),
            ("spending", "Cash Flow expenses", format_currency, "[data-testid='cash-flow-current-spending']"),
            ("net", "Cash Flow net savings", format_signed_currency, "[data-testid='cash-flow-current-net']"),
            ("savings_rate", "Cash Flow savings rate", format_percent, "[data-testid='cash-flow-current-savings-rate']"),
            ("debt_service", "Cash Flow debt service", format_currency, "[data-testid='cash-flow-current-debt-service']"),
        ]:
            _add(
                expectations,
                check_id="cash_flow.current_month",
                route="/cash-flow",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=formatter(cash_flow.get(field)),
                selector=selector,
            )

        # Transactions: visible pagination plus the first page's amount/date
        # cells. The full row set remains API-audited; this confirms the table
        # is rendering the current scoped slice.
        transactions = _actual(checks, "transactions.table", view_state_id) or {}
        _add(
            expectations,
            check_id="transactions.table",
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
        if transactions.get("row_amounts"):
            for idx, amount in enumerate(transactions["row_amounts"][:5], start=1):
                _add(
                    expectations,
                    check_id="transactions.table",
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
                route="/transactions",
                view_state_id=view_state_id,
                field="empty_state",
                label="Transactions empty state",
                expected_text="No transactions found",
                selector="[data-testid='transactions-empty-state']",
            )

        # Reports: current-month summary cards.
        reports_flow = _actual(checks, "reports.flow", view_state_id) or {}
        for field, label, formatter, selector in [
            ("total_income", "Reports total income", format_currency, "[data-testid='reports-summary-total-income']"),
            ("total_spending", "Reports total expenses", format_currency, "[data-testid='reports-summary-total-expenses']"),
            ("net", "Reports total net income", format_signed_currency, "[data-testid='reports-summary-net-income']"),
            ("savings_rate", "Reports savings rate", format_percent, "[data-testid='reports-summary-savings-rate']"),
        ]:
            _add(
                expectations,
                check_id="reports.flow",
                route="/reports",
                view_state_id=view_state_id,
                field=field,
                label=label,
                expected_text=formatter(reports_flow.get(field)),
                selector=selector,
            )

        # Accounts: header total and expanded group totals.
        accounts = _actual(checks, "accounts.snapshot", view_state_id) or {}
        _add(
            expectations,
            check_id="accounts.snapshot",
            route="/accounts",
            view_state_id=view_state_id,
            field="display_total",
            label="Accounts displayed total",
            expected_text=format_currency(accounts.get("display_total")),
            selector="[data-testid='accounts-display-total']",
        )
        for group_name, group_total in (accounts.get("group_totals") or {}).items():
            _add(
                expectations,
                check_id="accounts.snapshot",
                route="/accounts",
                view_state_id=view_state_id,
                field=f"group_total.{group_name}",
                label=f"Accounts group total: {group_name}",
                expected_text=format_currency(group_total),
                selector=f"[data-testid='accounts-group-total-{_test_id_part(group_name)}']",
            )
        summary = accounts.get("summary") or {}
        _add(
            expectations,
            check_id="accounts.snapshot",
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
            route="/accounts",
            view_state_id=view_state_id,
            field="summary.liabilities_total",
            label="Accounts summary liabilities total",
            expected_text=format_currency(summary.get("liabilities_total")),
            selector="[data-testid='accounts-summary-liabilities-total']",
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
                            page.locator(first.selector).wait_for(timeout=min(timeout_ms, 8_000))
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
                        selector_target_count = None
                        rendered_text = body
                        if expectation.selector:
                            locator = page.locator(expectation.selector)
                            selector_target_count = locator.count()
                            if selector_target_count == 1:
                                rendered_text = locator.inner_text(timeout=timeout_ms)
                                found = _body_contains(rendered_text, expectation.expected_text)
                            else:
                                found = False
                        else:
                            found = _body_contains(body, expectation.expected_text)
                        checks.append({
                            "id": expectation.id,
                            "check_id": expectation.check_id,
                            "route": expectation.route,
                            "view_state": expectation.view_state_id,
                            "label": expectation.label,
                            "selector": expectation.selector,
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
    covered_contexts = {
        _scoped_id(expectation.check_id, expectation.view_state_id)
        for expectation in expectations
    }
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
            "scope": "first_selector_backed_visible_slice",
            "claim": (
                "Selector-backed rendered text proof for high-signal visible values across the five scoped pages; "
                "not yet full registry selector coverage."
            ),
            "registered_value_contexts": len(registered_contexts),
            "distinct_registered_contexts_touched": len(covered_contexts),
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
            "route": check["route"],
            "view_state": check["view_state"],
            "label": check["label"],
            "selector": check.get("selector"),
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
        f"- Distinct registered contexts touched by DOM slice: `{coverage['distinct_registered_contexts_touched']}`",
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
