"""One-off splitter: extract groups of methods from a single-class module
into mixin classes in separate files.

The original file becomes a slim shell:
    class FooConnector(MixinA, MixinB, MixinC, BaseClass):
        # only the @property declarations + class-level constants remain

Method ordering and `self`-based interactions are preserved verbatim;
mixins do not introduce any new state — they're pure method bags.

Usage:
    from scripts._split_class import split_class
    split_class(
        source="extractors/chase_connector.py",
        target_pkg="extractors/chase",
        class_name="ChaseConnector",
        keep_in_shell=["institution", "display_name", "export_url",
                        "login_url", "_is_session_valid"],
        groups={
            "_login_mixin.py": ("ChaseLoginMixin", ["_perform_login", ...]),
            "_export_mixin.py": ("ChaseExportMixin", [...]),
        },
    )
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path


def _method_ranges(class_node: ast.ClassDef, source_lines: list[str]):
    """Return [(name, start_line, end_line_exclusive)] for each method.

    start_line walks back over decorator lines and immediately preceding
    blank/comment-only lines so each method takes its section header
    with it. end_line_exclusive walks forward through trailing blank
    lines.
    """
    items = []
    for node in class_node.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = node.lineno
        # decorators
        if node.decorator_list:
            start = min(d.lineno for d in node.decorator_list)
        # walk back over blank/comment lines
        i = start - 2
        while i >= 0 and source_lines[i].strip().startswith(("# ", "#")):
            i -= 1
        start = i + 2
        end = (node.end_lineno or node.lineno)
        j = end
        while j < len(source_lines) and source_lines[j].strip() == "":
            j += 1
        items.append((node.name, start, j))
    return items


def split_class(
    *,
    source: str,
    target_pkg: str,
    class_name: str,
    keep_in_shell: list[str],
    groups: dict[str, tuple[str, list[str]]],
) -> None:
    src_path = Path(source)
    text = src_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)

    target_class = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            target_class = node
            break
    if not target_class:
        raise SystemExit(f"Class {class_name} not found in {source}")

    methods = _method_ranges(target_class, lines)
    by_name = {n: (s, e) for n, s, e in methods}

    # Sanity: every method must be either kept in shell or in a group.
    grouped_names = {n for _, names in groups.values() for n in names}
    accounted = set(keep_in_shell) | grouped_names
    method_names = {n for n, _, _ in methods}
    missing = grouped_names - method_names
    if missing:
        raise SystemExit(f"Group references methods not on {class_name}: {missing}")
    leftover = method_names - accounted
    if leftover:
        raise SystemExit(
            f"Methods not assigned to keep_in_shell or any group: {sorted(leftover)}"
        )

    # Determine header range: everything before the class def.
    header_end = target_class.lineno - 1  # exclusive
    # Walk back over a leading section comment immediately above class.
    i = header_end - 1
    while i >= 0 and lines[i].strip().startswith(("# ", "#")):
        i -= 1
    header_end = i + 1
    header_text = "".join(lines[:header_end])

    # Pull the class docstring (first statement of class body if a string).
    class_open_line = lines[target_class.lineno - 1]  # the "class Foo(...):" line
    class_doc_text = ""
    body_first = target_class.body[0] if target_class.body else None
    if (
        isinstance(body_first, ast.Expr)
        and isinstance(body_first.value, ast.Constant)
        and isinstance(body_first.value.value, str)
    ):
        ds_start = body_first.lineno
        ds_end = body_first.end_lineno or ds_start
        class_doc_text = "".join(lines[ds_start - 1 : ds_end])

    # Class-level assignments (e.g. constants) inside the class body.
    class_const_chunks = []
    for node in target_class.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            s = node.lineno
            e = node.end_lineno or s
            # walk back over comments
            ci = s - 2
            while ci >= 0 and lines[ci].strip().startswith(("# ", "#")):
                ci -= 1
            s = ci + 2
            class_const_chunks.append("".join(lines[s - 1 : e]))

    pkg_path = Path(target_pkg)
    pkg_path.mkdir(parents=True, exist_ok=True)

    mixin_class_names = []
    for fname, (mixin_class, names) in groups.items():
        method_chunks = []
        for n in names:
            s, e = by_name[n]
            method_chunks.append("".join(lines[s - 1 : e]))
        mixin_text = (
            header_text.rstrip()
            + "\n\n\n"
            + f"class {mixin_class}:\n"
            + f'    """Mixin extracted from {class_name}: {fname[:-3]} methods."""\n\n'
            + "".join(method_chunks).rstrip()
            + "\n"
        )
        (pkg_path / fname).write_text(mixin_text, encoding="utf-8")
        mixin_class_names.append((fname[:-3], mixin_class))

    # Build the slim shell file.
    keep_chunks = []
    for n in keep_in_shell:
        s, e = by_name[n]
        keep_chunks.append("".join(lines[s - 1 : e]))

    # Inheritance: original bases + mixins (mixins go FIRST so their
    # methods are visible; but Python MRO means the leftmost class's
    # methods take precedence. Here, original methods don't conflict
    # with mixins because each method lives in exactly one place.)
    orig_bases = []
    for b in target_class.bases:
        orig_bases.append(ast.unparse(b))
    new_bases = [m for _, m in mixin_class_names] + orig_bases
    bases_str = ", ".join(new_bases)

    mixin_imports = "\n".join(
        f"from {target_pkg.replace('/', '.')}.{stem} import {cls}"
        for stem, cls in mixin_class_names
    )

    shell_text_parts = [
        header_text.rstrip(),
        "\n",
        mixin_imports,
        "\n\n\n",
        f"class {class_name}({bases_str}):\n",
    ]
    if class_doc_text:
        shell_text_parts.append(class_doc_text)
    if class_const_chunks:
        shell_text_parts.append("\n")
        shell_text_parts.append("".join(class_const_chunks))
    if keep_chunks:
        shell_text_parts.append("\n")
        shell_text_parts.append("".join(keep_chunks).rstrip())
        shell_text_parts.append("\n")
    if not (class_doc_text or class_const_chunks or keep_chunks):
        shell_text_parts.append("    pass\n")

    backup = src_path.with_suffix(".py.bak")
    shutil.copy2(src_path, backup)
    src_path.write_text("".join(shell_text_parts), encoding="utf-8")

    print(f"Split {source} -> shell + {len(mixin_class_names)} mixins in {target_pkg}/")
    print(f"Backup at {backup}")
