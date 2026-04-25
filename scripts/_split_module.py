"""One-off splitter: extract groups of top-level functions from a source module
into separate files, leaving the original module as a re-exporting facade.

Usage (programmatic):
    from scripts._split_module import split_module
    split_module(
        source="dal/reports.py",
        target_pkg="dal/reports",
        groups={
            "spending.py": ["get_spending_by_category", "get_category_trend", ...],
            "cash_flow.py": ["get_cash_flow_report", "get_period_summary"],
            ...
        },
        header_lines=46,  # how many leading lines (imports, constants) are shared
    )

Each new submodule file contains:
  • The shared header (imports + module-level constants) verbatim.
  • The target functions (and any *private* helpers they exclusively use).

The original module file is REWRITTEN to a tiny facade that re-exports
every public symbol from the submodules so callers don't have to change.
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path
from typing import Iterable


def _func_ranges(tree: ast.Module, source_lines: list[str]) -> list[tuple[str, int, int]]:
    """Return [(name, start_line, end_line), ...] for every top-level def/class.

    end_line is INCLUSIVE and walks forward to consume any trailing blank
    lines or comment-only lines so the next slice starts on a fresh
    section header.
    """
    items: list[tuple[str, int, int]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = node.lineno
        # Walk back over decorator lines and any leading "# section" comments.
        i = start - 2
        while i >= 0 and source_lines[i].strip().startswith(("# ", "#")):
            i -= 1
        start = i + 2
        end = node.end_lineno or node.lineno
        # Walk forward through trailing blank lines (but not the next def).
        j = end
        while j < len(source_lines) and source_lines[j].strip() == "":
            j += 1
        end = j  # exclusive end (next def's start)
        items.append((node.name, start, end))
    return items


def split_module(
    *,
    source: str,
    target_pkg: str,
    groups: dict[str, list[str]],
    header_through: str | None = None,
    extra_imports: dict[str, list[str]] | None = None,
) -> None:
    src_path = Path(source)
    pkg_path = Path(target_pkg)
    text = src_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)

    ranges = _func_ranges(tree, lines)
    by_name = {n: (s, e) for n, s, e in ranges}

    # Determine header range: everything before the FIRST listed function in
    # ANY group, OR if header_through is provided, up to that function's start.
    all_grouped_names = [n for names in groups.values() for n in names]
    missing = [n for n in all_grouped_names if n not in by_name]
    if missing:
        raise SystemExit(f"Functions not found in {source}: {missing}")

    if header_through:
        header_end = by_name[header_through][0] - 1
    else:
        first_grouped_start = min(by_name[n][0] for n in all_grouped_names)
        header_end = first_grouped_start - 1
    header_text = "".join(lines[: header_end])

    # Sanity check: every top-level def/class must be covered by exactly one group.
    top_level_names = [n for n, _, _ in ranges]
    uncovered = [n for n in top_level_names if n not in all_grouped_names]
    if uncovered:
        raise SystemExit(
            f"Uncovered top-level defs in {source}: {uncovered}\n"
            "Add them to a group or they will be dropped."
        )

    pkg_path.mkdir(parents=True, exist_ok=True)

    # Per-group submodule write
    public_exports: list[str] = []
    submodule_for: dict[str, str] = {}
    for fname, names in groups.items():
        body_chunks: list[str] = []
        for n in names:
            s, e = by_name[n]
            body_chunks.append("".join(lines[s - 1 : e]))
            stem = fname[:-3] if fname.endswith(".py") else fname
            submodule_for[n] = stem
            if not n.startswith("_"):
                public_exports.append(n)
        sub_text = header_text.rstrip() + "\n\n\n" + "".join(body_chunks).rstrip() + "\n"
        # Apply extra imports if requested
        if extra_imports and fname in extra_imports:
            extra = "\n".join(extra_imports[fname]) + "\n"
            # Insert after the existing imports block — append to header end is fine.
            sub_text = sub_text.replace(
                header_text.rstrip(),
                header_text.rstrip() + "\n" + extra,
                1,
            )
        (pkg_path / fname).write_text(sub_text, encoding="utf-8")

    # Build the facade __init__.py
    facade: list[str] = ['"""', f"Re-export facade for the {target_pkg.replace('/', '.')} package.", "", "Originally a single module; split for maintainability. Public API is", "preserved — callers can still ``from dal.reports import X``.", '"""', ""]
    # Group imports by submodule
    by_mod: dict[str, list[str]] = {}
    for n, mod in submodule_for.items():
        by_mod.setdefault(mod, []).append(n)
    for mod in sorted(by_mod):
        names = sorted(by_mod[mod])
        facade.append(f"from .{mod} import (")
        for n in names:
            facade.append(f"    {n},")
        facade.append(")")
    facade.append("")
    facade.append("__all__ = [")
    for n in sorted(public_exports):
        facade.append(f'    "{n}",')
    facade.append("]")
    facade.append("")

    # Backup the original then delete it (we replace it with a package).
    backup = src_path.with_suffix(".py.bak")
    shutil.copy2(src_path, backup)
    src_path.unlink()
    (pkg_path / "__init__.py").write_text("\n".join(facade), encoding="utf-8")

    print(f"Split {source} -> {target_pkg}/ ({len(by_mod)} submodules)")
    print(f"Backup at {backup}")
