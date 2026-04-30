"""Stage A: detect + AST extract code, partition doc corpus into chunks for subagent dispatch.

Outputs (in graphify-out-full/):
  .graphify_detect.json       - corpus inventory
  .graphify_ast.json          - tree-sitter extraction over code (free)
  chunks/chunk_NN.json        - per-chunk file lists for subagents
  chunks/manifest.json        - {total_chunks, deep_mode, output_dir}
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from math import ceil
from pathlib import Path

from graphify.detect import (
    CODE_EXTENSIONS,
    DOC_EXTENSIONS,
    PAPER_EXTENSIONS,
    classify_file,
    _is_sensitive,
)
from graphify.extract import collect_files, extract

PROJECT_ROOT = Path(
    r"C:\Users\chang\OneDrive\Desktop\Projects\Personal Finance Project"
)
OUT_DIR = Path("graphify-out-full")
CHUNK_DIR = OUT_DIR / "chunks"
CHUNK_SIZE = 22
DEEP_MODE = True

# Treat these as documents for semantic extraction even though graphify's
# default classifier ignores them. Lineage YAMLs are the whole point of this run.
DOC_LIKE_EXTRA = {".yaml", ".yml", ".json", ".cfg", ".toml", ".ini"}

CODE_DIRS = ["backend", "frontend/src", "dal", "extractors", "scripts", "tests"]
DOC_DIRS = ["docs", "data-lineage"]
TOP_LEVEL_DOCS = ["CLAUDE.md", "AGENTS.md", "README.md", "ROADMAP.md", "ROADMAP_ARCHIVE.md"]

SKIP_DIR_PATTERNS = re.compile(
    r"(^|[\\/])(node_modules|__pycache__|\.git|\.venv|venv|dist|build|\.next|out|coverage|\.cache)([\\/]|$)"
)


def _walk(root: Path):
    """Walk a tree, skipping noise dirs and sensitive files."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if SKIP_DIR_PATTERNS.search(str(path)):
            continue
        if _is_sensitive(path):
            continue
        yield path


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    CHUNK_DIR.mkdir(exist_ok=True)

    code_files: list[Path] = []
    doc_files: list[Path] = []      # markdown + yaml + json + cfg
    paper_files: list[Path] = []

    # Walk code directories (AST-eligible)
    for rel in CODE_DIRS:
        d = PROJECT_ROOT / rel
        if not d.exists():
            print(f"[skip] missing dir {d}")
            continue
        for f in _walk(d):
            ext = f.suffix.lower()
            if ext in CODE_EXTENSIONS:
                code_files.append(f)
            elif ext in DOC_LIKE_EXTRA or ext in DOC_EXTENSIONS:
                doc_files.append(f)

    # Walk doc directories (semantic-eligible)
    for rel in DOC_DIRS:
        d = PROJECT_ROOT / rel
        if not d.exists():
            print(f"[skip] missing dir {d}")
            continue
        for f in _walk(d):
            ext = f.suffix.lower()
            if ext in CODE_EXTENSIONS:
                code_files.append(f)        # 4 .py files in docs/
            elif ext in DOC_LIKE_EXTRA:
                doc_files.append(f)
            elif ext in DOC_EXTENSIONS:
                ftype = classify_file(f)
                if ftype and ftype.value == "paper":
                    paper_files.append(f)
                else:
                    doc_files.append(f)
            elif ext in PAPER_EXTENSIONS:
                paper_files.append(f)

    # Top-level docs
    for name in TOP_LEVEL_DOCS:
        f = PROJECT_ROOT / name
        if f.exists() and not _is_sensitive(f):
            doc_files.append(f)

    # Dedup
    code_files = sorted(set(code_files))
    doc_files = sorted(set(doc_files))
    paper_files = sorted(set(paper_files))

    print(f"[detect] code:     {len(code_files)} files")
    print(f"[detect] docs:     {len(doc_files)} files")
    print(f"[detect] papers:   {len(paper_files)} files")

    by_ext_code: dict[str, int] = defaultdict(int)
    for f in code_files:
        by_ext_code[f.suffix.lower()] += 1
    print(f"[detect]   code by ext: {dict(by_ext_code)}")

    by_ext_doc: dict[str, int] = defaultdict(int)
    for f in doc_files:
        by_ext_doc[f.suffix.lower()] += 1
    print(f"[detect]   doc by ext:  {dict(by_ext_doc)}")

    detection = {
        "total_files": len(code_files) + len(doc_files) + len(paper_files),
        "total_words": sum(
            len(f.read_text(encoding="utf-8", errors="ignore").split())
            for f in code_files + doc_files
        ),
        "files": {
            "code": [str(p) for p in code_files],
            "document": [str(p) for p in doc_files],
            "paper": [str(p) for p in paper_files],
        },
        "skipped_sensitive": [],
        "needs_graph": True,
        "warning": None,
    }
    (OUT_DIR / ".graphify_detect.json").write_text(json.dumps(detection))
    print(f"[detect] total_files={detection['total_files']}, total_words={detection['total_words']:,}")

    # AST extraction (code only, free)
    if code_files:
        print(f"[ast] tree-sitter extraction on {len(code_files)} code files")
        ast_result = extract(code_files, cache_root=Path("."))
        print(f"[ast] {len(ast_result['nodes'])} nodes, {len(ast_result['edges'])} edges")
        (OUT_DIR / ".graphify_ast.json").write_text(
            json.dumps(
                {
                    "nodes": ast_result["nodes"],
                    "edges": ast_result["edges"],
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            )
        )

    # Chunk doc + paper files for subagents.
    # Group files by directory so related artifacts land in same chunk.
    semantic_files = doc_files + paper_files
    by_dir: dict[str, list[Path]] = defaultdict(list)
    for f in semantic_files:
        by_dir[str(f.parent)].append(f)

    chunks: list[list[Path]] = []
    current: list[Path] = []
    for d in sorted(by_dir):
        for f in sorted(by_dir[d]):
            current.append(f)
            if len(current) >= CHUNK_SIZE:
                chunks.append(current)
                current = []
    if current:
        chunks.append(current)

    total_chunks = len(chunks)
    print(f"[chunks] {total_chunks} chunks of up to {CHUNK_SIZE} files each")

    for i, files in enumerate(chunks, 1):
        chunk_payload = {
            "chunk_num": i,
            "total_chunks": total_chunks,
            "files": [str(f) for f in files],
            "deep_mode": DEEP_MODE,
            "output_path": str((CHUNK_DIR / f"chunk_{i:02d}_result.json").resolve()),
        }
        (CHUNK_DIR / f"chunk_{i:02d}.json").write_text(json.dumps(chunk_payload, indent=2))

    manifest = {
        "total_chunks": total_chunks,
        "deep_mode": DEEP_MODE,
        "chunk_size": CHUNK_SIZE,
        "out_dir": str(OUT_DIR.resolve()),
        "chunk_dir": str(CHUNK_DIR.resolve()),
        "code_count": len(code_files),
        "doc_count": len(doc_files),
        "paper_count": len(paper_files),
    }
    (CHUNK_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print()
    print("=" * 70)
    print("STAGE A COMPLETE")
    print("=" * 70)
    print(f"  detect, AST done. {total_chunks} chunks ready in {CHUNK_DIR.resolve()}")
    print(f"  next: dispatch {total_chunks} parallel Agent calls, then run merge_full.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
