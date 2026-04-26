"""check_freshness.py — fail if the generated lineage artifacts are stale.

Hashes `inverse-index.yaml` and every `diagrams/*.mmd`, regenerates
both via `build_inverse_index.py` + `build_diagrams.py`, then re-hashes.
Any hash that changes — or any new file produced — is drift. The script
prints the affected paths and exits non-zero so the pre-commit hook
can block.

Designed to be invoked from a git pre-commit hook (see
`scripts/install_hooks.sh`). Safe to run manually:

  python docs/data-lineage/check_freshness.py

Exit codes:
  0 — generated artifacts already match the source YAMLs
  1 — drift detected; regenerated files are now in the working tree
      (re-stage and re-commit, or revert the YAML edit)
  2 — internal error (a generator failed)
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

LINEAGE_DIR = Path(__file__).parent
DIAGRAMS_DIR = LINEAGE_DIR / "diagrams"
INDEX_PATH = LINEAGE_DIR / "inverse-index.yaml"


def hash_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot() -> dict[str, str | None]:
    """Hash every generated artifact. Missing files hash to None so
    creation is also detected as drift. Keys use posix separators so
    the error output is portable across Windows + macOS + Linux."""
    snap: dict[str, str | None] = {}
    snap[INDEX_PATH.relative_to(LINEAGE_DIR).as_posix()] = hash_file(INDEX_PATH)
    if DIAGRAMS_DIR.exists():
        for p in sorted(DIAGRAMS_DIR.glob("*.mmd")):
            snap[p.relative_to(LINEAGE_DIR).as_posix()] = hash_file(p)
    return snap


def run_generator(name: str) -> bool:
    script = LINEAGE_DIR / name
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(LINEAGE_DIR),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"check_freshness: {name} failed (exit {proc.returncode})\n")
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        return False
    return True


def main() -> int:
    before = snapshot()

    if not run_generator("build_inverse_index.py"):
        return 2
    if not run_generator("build_diagrams.py"):
        return 2

    after = snapshot()

    drifted = sorted(
        path for path in (set(before) | set(after))
        if before.get(path) != after.get(path)
    )

    if drifted:
        sys.stderr.write(
            "\nERROR: generated lineage artifacts are stale.\n"
            "       Regeneration changed the following files:\n\n"
        )
        for p in drifted[:20]:
            sys.stderr.write(f"         docs/data-lineage/{p}\n")
        if len(drifted) > 20:
            sys.stderr.write(f"         … and {len(drifted) - 20} more\n")
        sys.stderr.write(
            "\n       The regenerated files are now in your working tree.\n"
            "       Re-stage them and re-commit:\n\n"
            "         git add docs/data-lineage/inverse-index.yaml docs/data-lineage/diagrams/\n"
            "         git commit\n\n"
            "       (Or revert if your YAML edit was unintentional.)\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
