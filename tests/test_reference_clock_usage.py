from pathlib import Path

from scripts.audit_reference_clock_usage import find_violations


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
