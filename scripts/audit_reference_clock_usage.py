"""Audit date-sensitive code for accidental direct wall-clock use.

This check is intentionally narrow. Live data still needs real timestamps for
events, refresh logs, notification age, and session TTLs. Reporting windows,
finance "today" defaults, and synthetic proof surfaces should instead flow
through the backend reference clock so trusted-seed and live modes share one
contract.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ClockPattern:
    name: str
    regex: re.Pattern[str]
    guidance: str


@dataclass(frozen=True)
class ClockViolation:
    path: str
    line: int
    pattern: str
    text: str
    guidance: str


FRONTEND_PATTERNS = (
    ClockPattern(
        name="empty-new-date",
        regex=re.compile(r"\bnew\s+Date\(\s*\)"),
        guidance="Use RuntimeContext.referenceDate for finance date defaults/windows.",
    ),
    ClockPattern(
        name="date-now",
        regex=re.compile(r"\bDate\.now\(\s*\)"),
        guidance="Use backend timestamps for finance freshness/window logic.",
    ),
    ClockPattern(
        name="iso-today-slice",
        regex=re.compile(r"\.toISOString\(\)\.slice\(\s*0\s*,\s*10\s*\)"),
        guidance="Use RuntimeContext.referenceDate for YYYY-MM-DD finance defaults.",
    ),
)

PYTHON_PATTERNS = (
    ClockPattern(
        name="date-today",
        regex=re.compile(r"\bdate\.today\(\s*\)"),
        guidance="Use dal.clock.reference_date(conn) in date-sensitive DAL/router code.",
    ),
    ClockPattern(
        name="datetime-now",
        regex=re.compile(r"\bdatetime\.now\("),
        guidance="Use dal.clock.reference_datetime(conn) in date-sensitive DAL/router code.",
    ),
    ClockPattern(
        name="datetime-utcnow",
        regex=re.compile(r"\bdatetime\.utcnow\("),
        guidance="Use dal.clock.reference_datetime(conn) in date-sensitive DAL/router code.",
    ),
    ClockPattern(
        name="sqlite-date-now",
        regex=re.compile(r"date\(\s*['\"]now['\"]\s*\)"),
        guidance="Use an explicit reference date parameter in date-sensitive SQL.",
    ),
)

# Client-local state and display concerns may use the browser clock. These are
# not finance-date authorities.
ALLOWED_FRONTEND_WALL_CLOCK_FILES = {
    "frontend/src/components/DocumentNudge.tsx": "local dismiss-until-midnight TTL",
    "frontend/src/components/Notifications/NotificationPopover.tsx": "relative notification age display",
    "frontend/src/context/RuntimeContext.tsx": "fallback while backend runtime context loads",
    "frontend/src/hooks/useSessionState.ts": "session-storage TTL",
    "frontend/src/lib/dateUtils.ts": "single fallback helper for runtime context",
}

# These files define finance windows or defaults and should not reach directly
# for the machine clock. Keep this list small and high-value.
REFERENCE_SENSITIVE_PYTHON_FILES = (
    "backend/routers/cash_flow.py",
    "backend/routers/reports.py",
    "dal/bills.py",
    "dal/cash_flow.py",
    "dal/documents.py",
    "dal/freshness.py",
    "dal/reports/flow.py",
    "dal/reports/net_worth.py",
    "dal/reports/spending.py",
)


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _scan_file(
    path: Path,
    root: Path,
    patterns: Iterable[ClockPattern],
) -> list[ClockViolation]:
    violations: list[ClockViolation] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return violations

    rel = _rel(path, root)
    for line_no, line in enumerate(lines, start=1):
        for pattern in patterns:
            if pattern.regex.search(line):
                violations.append(
                    ClockViolation(
                        path=rel,
                        line=line_no,
                        pattern=pattern.name,
                        text=line.strip(),
                        guidance=pattern.guidance,
                    )
                )
    return violations


def find_violations(root: Path = ROOT) -> list[ClockViolation]:
    root = root.resolve()
    violations: list[ClockViolation] = []

    frontend_root = root / "frontend" / "src"
    if frontend_root.exists():
        for path in sorted(
            p for p in frontend_root.rglob("*") if p.suffix in {".ts", ".tsx"}
        ):
            rel = _rel(path, root)
            if rel in ALLOWED_FRONTEND_WALL_CLOCK_FILES:
                continue
            violations.extend(_scan_file(path, root, FRONTEND_PATTERNS))

    for rel in REFERENCE_SENSITIVE_PYTHON_FILES:
        path = root / rel
        if path.exists():
            violations.extend(_scan_file(path, root, PYTHON_PATTERNS))

    return violations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit reference-clock-sensitive code for direct wall-clock drift."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root to scan. Defaults to this checkout.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    violations = find_violations(args.root)

    if args.json:
        payload = {
            "status": "fail" if violations else "pass",
            "violations": [asdict(v) for v in violations],
        }
        print(json.dumps(payload, indent=2))
    elif violations:
        print("Reference clock usage audit failed:", file=sys.stderr)
        for v in violations:
            print(
                f"- {v.path}:{v.line} [{v.pattern}] {v.text}\n"
                f"  {v.guidance}",
                file=sys.stderr,
            )
    else:
        print("Reference clock usage audit passed.")

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
