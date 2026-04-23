"""Pre-commit gate hook for Claude Code.

Wired into `.claude/settings.json` as a PreToolUse hook matching `Bash`.
Reads the hook JSON payload from stdin, no-ops unless the command starts
with `git commit`, and otherwise runs pytest then scripts/pii_scan.py.
Exit 2 blocks the commit and surfaces stderr back to Claude.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def _load_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def _resolve_cwd(payload: dict) -> str:
    return (
        payload.get("cwd")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    )


def _run(label: str, argv: list[str], cwd: str) -> int:
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        sys.stderr.write(
            f"[pre_commit_gate] cannot run {label}: {exc}. "
            f"Commit blocked so the failure is visible.\n"
        )
        return 2
    if result.returncode == 0:
        return 0
    sys.stderr.write(
        f"[pre_commit_gate] {label} failed (exit {result.returncode}). "
        f"Commit blocked.\n"
    )
    if result.stdout:
        sys.stderr.write("--- stdout ---\n")
        sys.stderr.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stderr.write("\n")
    if result.stderr:
        sys.stderr.write("--- stderr ---\n")
        sys.stderr.write(result.stderr)
        if not result.stderr.endswith("\n"):
            sys.stderr.write("\n")
    return 2


def main() -> int:
    payload = _load_payload()
    command = payload.get("tool_input", {}).get("command", "").strip()
    if not command.startswith("git commit"):
        return 0

    cwd = _resolve_cwd(payload)

    checks = [
        ("pytest", [sys.executable, "-m", "pytest", "-x", "--tb=short", "-q"]),
        ("pii_scan", [sys.executable, "scripts/pii_scan.py"]),
    ]
    for label, argv in checks:
        rc = _run(label, argv, cwd)
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
