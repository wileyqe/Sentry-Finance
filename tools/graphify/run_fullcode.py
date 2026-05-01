"""Run graphify across the full code surface (backend + frontend + dal + extractors).

Pure AST extraction, zero LLM cost. Skips tests (boilerplate noise), scripts
(seeders), docs (would need semantic extraction). Cross-stack: Python AST +
TypeScript AST in one graph.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from graphify.analyze import god_nodes, suggest_questions, surprising_connections
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.export import to_html, to_json
from graphify.extract import collect_files, extract
from graphify.report import generate


def _resolve_project_root() -> Path:
    env = os.environ.get("GRAPHIFY_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if out:
            return Path(out).resolve()
    except Exception:
        pass
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _resolve_project_root()
INPUT_DIRS = [
    PROJECT_ROOT / "backend",
    PROJECT_ROOT / "frontend" / "src",
    PROJECT_ROOT / "dal",
    PROJECT_ROOT / "extractors",
]
OUT_DIR = Path("graphify-out-fullcode")
DIRECTED = True

CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx"}
SENSITIVE_NAME_PATTERNS = (
    re.compile(r"credential", re.I),
    re.compile(r"secret", re.I),
    re.compile(r"\.env"),
)

STOP = {
    "the", "and", "for", "with", "from", "this", "that", "are", "was", "were",
    "has", "have", "had", "not", "but", "out", "any", "all", "one", "two",
    "now", "new", "old", "use", "uses", "set", "get", "got", "put", "post",
    "delete", "patch", "head", "options", "run", "runs", "ran", "return",
    "returns", "returned", "list", "lists", "listed", "endpoint", "endpoints",
    "router", "routers", "request", "requests", "response", "responses",
    "param", "params", "payload", "data", "value", "values", "result", "results",
    "type", "types", "name", "names", "info", "true", "false", "none", "null",
    "callable", "instance", "class", "method", "function", "func", "var", "vars",
    "init", "main", "self", "cls", "obj", "key", "keys", "default", "defaults",
    "opt", "opts", "option", "props", "react", "tsx", "ts", "py",
    "sentry", "finance", "backend", "frontend",
    "json", "html", "yaml", "yml",
    "api", "fastapi", "pydantic", "model", "schema",
    "yes", "ok", "if", "else", "when", "where", "what", "how", "why",
    "see", "section", "above", "below",
    "imp", "impl", "impls", "test", "tests",
}

TOK_RE = re.compile(r"[a-z][a-z0-9]+")


def _label_tokens(text: str) -> list[str]:
    return [
        t for t in TOK_RE.findall(text.lower())
        if len(t) >= 4 and t not in STOP
    ]


def _is_sensitive(p: Path) -> bool:
    return any(pat.search(p.name) for pat in SENSITIVE_NAME_PATTERNS)


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)

    # Step 1: enumerate code files across all input dirs
    all_code: list[Path] = []
    skipped: list[Path] = []
    for d in INPUT_DIRS:
        if not d.exists():
            print(f"[detect] missing: {d}")
            continue
        for f in collect_files(d):
            if f.suffix.lower() not in CODE_EXTS:
                continue
            if _is_sensitive(f):
                skipped.append(f)
                continue
            all_code.append(f)

    by_ext: Counter[str] = Counter(p.suffix.lower() for p in all_code)
    print(f"[detect] {len(all_code)} code files across {len(INPUT_DIRS)} dirs")
    for ext, n in sorted(by_ext.items()):
        print(f"          {ext}: {n}")
    if skipped:
        print(f"[detect] skipped {len(skipped)} sensitive: {[p.name for p in skipped]}")

    if not all_code:
        print("[detect] no code files found, aborting")
        return 1

    # Synthesize a detection dict shaped like graphify.detect.detect() output
    detection = {
        "total_files": len(all_code),
        "total_words": sum(
            len(p.read_text(encoding="utf-8", errors="ignore").split())
            for p in all_code
        ),
        "files": {"code": [str(p) for p in all_code]},
        "skipped_sensitive": [str(p) for p in skipped],
        "needs_graph": True,
        "warning": None,
    }
    (OUT_DIR / ".graphify_detect.json").write_text(json.dumps(detection))

    # Step 3A: AST extraction
    print(f"[ast] tree-sitter extraction on {len(all_code)} files")
    ast_result = extract(all_code, cache_root=Path("."))
    print(f"[ast] {len(ast_result['nodes'])} nodes, {len(ast_result['edges'])} edges")

    extraction = {
        "nodes": ast_result["nodes"],
        "edges": ast_result["edges"],
        "hyperedges": [],
        "input_tokens": 0,
        "output_tokens": 0,
    }
    (OUT_DIR / ".graphify_extract.json").write_text(json.dumps(extraction))

    # Step 4: build, cluster, analyze
    print(f"[build] directed={DIRECTED}")
    G = build_from_json(extraction, directed=DIRECTED)
    if G.number_of_nodes() == 0:
        print("[build] graph is empty, aborting")
        return 1
    print(f"[build] {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    print("[cluster] louvain community detection")
    communities = cluster(G)
    cohesion = score_all(G, communities)
    print(f"[cluster] {len(communities)} communities")

    print("[analyze] god nodes, surprising connections")
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)

    # Auto-label communities with stoplist
    labels: dict[int, str] = {}
    for cid, members in communities.items():
        bag: Counter[str] = Counter()
        for nid in members:
            label = G.nodes[nid].get("label", nid)
            for tok in _label_tokens(str(label)):
                bag[tok] += 1
        top = [t for t, _ in bag.most_common(6)]
        labels[cid] = " · ".join(top[:3]) if top else f"Community {cid}"

    questions = suggest_questions(G, communities, labels)
    tokens = {"input": 0, "output": 0}

    report = generate(
        G,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        detection,
        tokens,
        str(PROJECT_ROOT),
        suggested_questions=questions,
    )
    (OUT_DIR / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    to_json(G, communities, str(OUT_DIR / "graph.json"))

    if G.number_of_nodes() > 5000:
        print(f"[html] graph has {G.number_of_nodes()} nodes — too large for HTML viz")
    else:
        to_html(
            G,
            communities,
            str(OUT_DIR / "graph.html"),
            community_labels=labels,
        )
        print(f"[html] {OUT_DIR / 'graph.html'}")

    # Summary
    print()
    print("=" * 70)
    print("FULL-CODE SUMMARY")
    print("=" * 70)
    print(f"  files processed:  {len(all_code)}")
    print(f"  nodes:            {G.number_of_nodes()}")
    print(f"  edges:            {G.number_of_edges()}")
    print(f"  communities:      {len(communities)}")
    print(f"  god nodes:        {len(gods)}")
    print(f"  surprises:        {len(surprises)}")
    print(f"  llm tokens used:  0  (AST-only path)")
    print()
    print("Top 15 god nodes (most-connected concepts across the stack):")
    for i, gn in enumerate(gods[:15], 1):
        # gods is a list of dicts; print label + degree
        lbl = gn.get("label") if isinstance(gn, dict) else str(gn)
        deg = gn.get("degree") if isinstance(gn, dict) else "?"
        src = gn.get("source_file", "") if isinstance(gn, dict) else ""
        # short source
        if isinstance(src, str) and "Personal Finance Project" in src:
            src = src.split("Personal Finance Project", 1)[-1].lstrip("\\/")
        print(f"  {i:>2}. {lbl}  ({deg} edges)  {src}")
    print()
    print("Communities (sorted by size):")
    for cid in sorted(communities, key=lambda c: -len(communities[c])):
        n = len(communities[cid])
        print(f"  [{cid:>2}] {labels[cid]:<55} ({n} nodes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
