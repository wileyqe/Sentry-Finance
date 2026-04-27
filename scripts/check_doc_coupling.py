"""check_doc_coupling.py — block commits that change structural code
without updating the docs that describe that structure.

Invoked from `.git/hooks/pre-commit` (installed by
`scripts/install_hooks.sh`). Reads the staged diff via `git diff
--cached` and applies a small set of coupling rules. Each rule names:

  - a **trigger** (some change in the staged set)
  - a **required companion** (a doc path that must also be staged)
  - the **rationale** (what doc section will go stale otherwise)

If a rule fires and no companion is staged, the script prints which
trigger fired and which doc must be touched, then exits 1 to block
the commit. Rules are intentionally narrow: they fire on changes that
*always* affect the named doc section, not on judgment-call changes.

Bypass via `SKIP_DOCS_CHECK="<reason>" git commit ...` — the env var
is honored by the pre-commit hook before this script runs.

Exit codes:
  0 — all triggered rules have a matching companion staged (or no rules fired).
  1 — at least one rule fired without its companion.
  2 — internal error (git invocation failed).
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    triggers: tuple[str, ...]
    trigger_filter: str  # "ACMR" any change, "A" added-only
    companions: tuple[str, ...]
    rationale: str
    excludes: tuple[str, ...] = ()  # paths matching these prefixes don't count as triggers


RULES: tuple[Rule, ...] = (
    Rule(
        name="migration → ARCHITECTURE or lineage YAML",
        triggers=("dal/migrations/v",),
        trigger_filter="ACMR",
        companions=("docs/ARCHITECTURE.md", "docs/data-lineage/"),
        rationale=(
            "A new or changed migration alters schema. Update "
            "ARCHITECTURE.md §4.2 (Schema Overview) or the relevant "
            "data-lineage YAML so consumers know what changed."
        ),
    ),
    Rule(
        name="new DAL or extractor module → data-lineage events.yaml",
        triggers=("dal/", "extractors/"),
        trigger_filter="A",  # added-only
        companions=("docs/data-lineage/events.yaml",),
        excludes=("dal/migrations/",),  # migrations have their own rule
        rationale=(
            "A new module under dal/ or extractors/ likely introduces a "
            "new event source. Add it to docs/data-lineage/events.yaml "
            "so the lineage map covers it."
        ),
    ),
    Rule(
        name="post-ingestion pipeline → ARCHITECTURE",
        triggers=("backend/result_writer.py",),
        trigger_filter="ACMR",
        companions=("docs/ARCHITECTURE.md",),
        rationale=(
            "ARCHITECTURE.md §3.4 lists the post-ingestion pipeline "
            "steps. Any change to result_writer.py risks drifting the "
            "doc — re-read §3.4 and update if step order or step names "
            "changed."
        ),
    ),
    Rule(
        name="new frontend page → ARCHITECTURE",
        triggers=("frontend/src/pages/",),
        trigger_filter="A",
        companions=("docs/ARCHITECTURE.md",),
        rationale=(
            "ARCHITECTURE.md §6.2 lists every page. New pages must be "
            "added to that table."
        ),
    ),
)


def _staged(diff_filter: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", f"--diff-filter={diff_filter}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(
            f"check_doc_coupling: git diff failed (exit {proc.returncode}).\n"
            f"{proc.stderr}"
        )
        sys.exit(2)
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _matches(
    paths: list[str],
    prefixes: tuple[str, ...],
    excludes: tuple[str, ...] = (),
) -> list[str]:
    return [
        p for p in paths
        if any(p.startswith(prefix) for prefix in prefixes)
        and not any(p.startswith(ex) for ex in excludes)
    ]


def _staged_satisfies(paths: list[str], companions: tuple[str, ...]) -> bool:
    for c in companions:
        if c.endswith("/"):
            if any(p.startswith(c) for p in paths):
                return True
        else:
            if c in paths:
                return True
    return False


def main() -> int:
    staged_any = _staged("ACMR")
    staged_added = _staged("A")
    if not staged_any:
        return 0

    failures: list[Rule] = []
    triggered_files: dict[str, list[str]] = {}

    for rule in RULES:
        source = staged_added if rule.trigger_filter == "A" else staged_any
        hits = _matches(source, rule.triggers, rule.excludes)
        if not hits:
            continue
        if _staged_satisfies(staged_any, rule.companions):
            continue
        failures.append(rule)
        triggered_files[rule.name] = hits

    if not failures:
        return 0

    sys.stderr.write(
        "\ncheck_doc_coupling: ERROR — staged changes require doc updates.\n\n"
    )
    for rule in failures:
        sys.stderr.write(f"  Rule: {rule.name}\n")
        sys.stderr.write("  Triggered by:\n")
        for f in triggered_files[rule.name]:
            sys.stderr.write(f"    - {f}\n")
        sys.stderr.write("  Required (any one):\n")
        for c in rule.companions:
            sys.stderr.write(f"    - {c}\n")
        sys.stderr.write(f"  Why: {rule.rationale}\n\n")

    sys.stderr.write(
        "Stage the doc update and re-commit. To bypass deliberately:\n"
        '  SKIP_DOCS_CHECK="<reason>" git commit ...\n'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
