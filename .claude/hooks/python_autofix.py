"""PostToolUse hook that runs `ruff check --fix` on edited Python files.

Never blocks. No-ops on non-Python paths, missing files, or when ruff is
not installed. Wired into `.claude/settings.json` matching Edit|Write|MultiEdit.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path or not file_path.endswith(".py"):
        return 0

    path = Path(file_path)
    if not path.is_absolute():
        cwd = (
            payload.get("cwd")
            or os.environ.get("CLAUDE_PROJECT_DIR")
            or os.getcwd()
        )
        path = Path(cwd) / path
    if not path.exists():
        return 0

    try:
        subprocess.run(
            ["ruff", "check", "--fix", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
