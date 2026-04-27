"""check_action_item_refs.py — block commits that move an AI-NNN
between Open and Resolved in `docs/data-lineage/ACTION_ITEMS.md`
without staging the cross-references that mention it.

Invoked from `.git/hooks/pre-commit` (installed by
`scripts/install_hooks.sh`). Closes the drift class surfaced by
the AI-009 closeout sweep (commit f9932ba): the existing
`check_freshness.py` only hash-compares generated artifacts, and
`check_doc_coupling.py` has no rule that fires on
`ACTION_ITEMS.md` changes, so stale prose like "AI-NNN tracks
the resulting test gap" or "completely untested" inside
lineage `notes:` fields slid through silently.

The check is narrow on purpose:

  - Trigger: `docs/data-lineage/ACTION_ITEMS.md` is in the staged
    diff AND at least one AI-NNN id moved between the `## Open`
    and `## Resolved` sections.
  - Companion: every file under `docs/data-lineage/events.yaml`
    or `docs/data-lineage/lineage/*.yaml` that mentions the moved
    AI-NNN must also be in the staged diff.

Bypass via `SKIP_DOCS_CHECK="<reason>" git commit ...` — the env
var is honored by the pre-commit hook before this script runs
(same as the other docs checks).

Exit codes:
  0 — no AI-NNN moved, or every cross-ref file is staged.
  1 — at least one moved AI-NNN has unstaged cross-ref files.
  2 — internal error (git invocation failed).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ACTION_ITEMS_PATH = "docs/data-lineage/ACTION_ITEMS.md"
LINEAGE_DIR = "docs/data-lineage/lineage"
EVENTS_PATH = "docs/data-lineage/events.yaml"

_AI_HEADING = re.compile(r"^### (AI-\d{3})\b")
_H2 = re.compile(r"^## (.+?)\s*$")


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(
            f"check_action_item_refs: git {' '.join(args)} failed "
            f"(exit {proc.returncode}).\n{proc.stderr}"
        )
        sys.exit(2)
    return proc.stdout


def _staged_paths() -> set[str]:
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return {line.strip() for line in out.splitlines() if line.strip()}


def _parse_sections(text: str) -> dict[str, set[str]]:
    """Walk H2/H3 hierarchy. Return {section_name: {AI-NNN, ...}}.

    Section names are normalised: only `Open` and `Resolved` are
    relevant; anything else (`Adding new items`, `How to use this
    file`, `Severity legend`) is ignored.
    """
    sections: dict[str, set[str]] = {"Open": set(), "Resolved": set()}
    current: str | None = None
    for line in text.splitlines():
        m_h2 = _H2.match(line)
        if m_h2:
            name = m_h2.group(1).strip()
            current = name if name in sections else None
            continue
        if current is None:
            continue
        m_id = _AI_HEADING.match(line)
        if m_id:
            sections[current].add(m_id.group(1))
    return sections


def _read_before() -> str:
    return _git("show", f"HEAD:{ACTION_ITEMS_PATH}")


def _read_staged() -> str:
    """Read the STAGED-INDEX version of ACTION_ITEMS.md, not the
    working tree. This way partial stages work cleanly: only the
    portion the author chose to include in this commit is checked.
    """
    return _git("show", f":{ACTION_ITEMS_PATH}")


def _scan_refs(ai_id: str, repo_root: Path) -> set[str]:
    """Return the set of repo-relative file paths under
    `docs/data-lineage/{events.yaml, lineage/*.yaml}` that mention
    the given AI-NNN id. Generated artifacts (`inverse-index.yaml`,
    `diagrams/*.mmd`) are not scanned.
    """
    hits: set[str] = set()

    candidates: list[Path] = []
    events = repo_root / EVENTS_PATH
    if events.is_file():
        candidates.append(events)
    lineage_dir = repo_root / LINEAGE_DIR
    if lineage_dir.is_dir():
        candidates.extend(sorted(lineage_dir.glob("*.yaml")))

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if ai_id in text:
            rel = path.relative_to(repo_root).as_posix()
            hits.add(rel)
    return hits


def main() -> int:
    repo_root = Path(_git("rev-parse", "--show-toplevel").strip())

    staged = _staged_paths()
    if ACTION_ITEMS_PATH not in staged:
        return 0

    try:
        before = _parse_sections(_read_before())
    except SystemExit:
        # ACTION_ITEMS.md may not exist yet in HEAD (first time
        # introduction). Treat HEAD as having empty sections.
        before = {"Open": set(), "Resolved": set()}
    after = _parse_sections(_read_staged())

    moved_to_resolved = before["Open"] & after["Resolved"]
    moved_to_open = before["Resolved"] & after["Open"]
    moved = moved_to_resolved | moved_to_open
    if not moved:
        return 0

    failures: dict[str, tuple[str, set[str]]] = {}
    for ai_id in sorted(moved):
        ref_files = _scan_refs(ai_id, repo_root)
        unstaged = ref_files - staged
        if not unstaged:
            continue
        new_status = "Resolved" if ai_id in moved_to_resolved else "Open"
        failures[ai_id] = (new_status, unstaged)

    if not failures:
        return 0

    sys.stderr.write(
        "\ncheck_action_item_refs: ERROR — ACTION_ITEMS.md moved "
        "AI-NNN between Open/Resolved, but cross-references in "
        "these files were not updated:\n\n"
    )
    for ai_id, (new_status, files) in failures.items():
        sys.stderr.write(f"  {ai_id} (now {new_status}):\n")
        for f in sorted(files):
            sys.stderr.write(f"    - {f}\n")
        sys.stderr.write("\n")
    sys.stderr.write(
        "Either:\n"
        "  - Stage edits to those files in this commit, OR\n"
        "  - Set SKIP_DOCS_CHECK=\"<reason>\" to bypass deliberately.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
