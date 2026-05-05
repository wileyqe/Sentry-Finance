from pathlib import Path

from scripts.audit_reference_clock_usage import (
    REFERENCE_SENSITIVE_PYTHON_FILES,
    find_violations,
)


def test_reference_clock_usage_allows_current_repo():
    assert find_violations() == []


def test_reference_clock_usage_flags_frontend_direct_today(tmp_path: Path):
    page = tmp_path / "frontend" / "src" / "pages" / "BadPage.tsx"
    page.parent.mkdir(parents=True)
    page.write_text(
        "export function BadPage() {\n"
        "  const today = new Date().toISOString().slice(0, 10);\n"
        "  return today;\n"
        "}\n",
        encoding="utf-8",
    )

    violations = find_violations(tmp_path)

    assert [(v.path, v.pattern) for v in violations] == [
        ("frontend/src/pages/BadPage.tsx", "empty-new-date"),
        ("frontend/src/pages/BadPage.tsx", "iso-today-slice"),
    ]


def test_reference_clock_usage_flags_python_reference_sensitive_wall_clock(
    tmp_path: Path,
):
    module = tmp_path / "dal" / "cash_flow.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from datetime import date\n"
        "def current_month():\n"
        "    return date.today().month\n",
        encoding="utf-8",
    )

    violations = find_violations(tmp_path)

    assert [(v.path, v.pattern) for v in violations] == [
        ("dal/cash_flow.py", "date-today"),
    ]


def test_inline_refclock_allow_suppresses_violation(tmp_path: Path):
    """Lines annotated with ``# refclock-allow:`` are not flagged."""
    module = tmp_path / "dal" / "budgets.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "import sqlite3\n"
        "def update(conn):\n"
        "    conn.execute(\"UPDATE t SET updated_at = datetime('now')\")  "
        "# refclock-allow: audit timestamp\n"
        "    conn.execute(\"SELECT * FROM t WHERE d >= date('now', '-3 months')\")\n",
        encoding="utf-8",
    )

    violations = find_violations(tmp_path)

    # Only the un-annotated line should be flagged
    assert len(violations) == 1
    assert violations[0].line == 4
    assert violations[0].pattern == "sqlite-date-now"


def test_merchant_budgets_forecasting_in_sensitive_files():
    """The three finance-window modules are covered by the audit."""
    sensitive = set(REFERENCE_SENSITIVE_PYTHON_FILES)
    assert "dal/reports/merchant.py" in sensitive
    assert "dal/budgets.py" in sensitive
    assert "dal/forecasting.py" in sensitive


def test_flags_sqlite_date_now_in_new_sensitive_files(tmp_path: Path):
    """Regression: SQL ``date('now', ...)`` in merchant/budget/forecast
    modules must be caught if the reference-clock fix is ever reverted."""
    for rel in ("dal/reports/merchant.py", "dal/budgets.py", "dal/forecasting.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "def bad(conn):\n"
            "    conn.execute(\"SELECT * FROM t WHERE d >= date('now', '-6 months')\")\n",
            encoding="utf-8",
        )

    violations = find_violations(tmp_path)

    flagged_files = {v.path for v in violations}
    assert "dal/reports/merchant.py" in flagged_files
    assert "dal/budgets.py" in flagged_files
    assert "dal/forecasting.py" in flagged_files
