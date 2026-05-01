"""Stage C: merge AST + recovered semantic chunks, build/cluster/render.

Gracefully handles missing chunks (e.g., from rate-limit / usage-limit failures).
Reports coverage gap explicitly.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from graphify.analyze import god_nodes, suggest_questions, surprising_connections
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify import export as graphify_export
from graphify.export import to_html, to_json
graphify_export.MAX_NODES_FOR_VIZ = 20_000  # bypass default 5000 cap
from graphify.report import generate

OUT_DIR = Path("graphify-out-full")
CHUNKS_DIR = OUT_DIR / "chunks"
DIRECTED = True


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
    "opt", "opts", "option", "props", "react", "tsx", "page", "view",
    "sentry", "finance", "backend", "frontend",
    "json", "html", "yaml",
    "api", "fastapi", "pydantic", "model", "schema",
    "yes", "see", "section", "above", "below",
    "section", "phase", "task", "todo", "wip",
    "node", "edge", "step", "test", "tests",
}
TOK_RE = re.compile(r"[a-z][a-z0-9]+")


def _label_tokens(text: str) -> list[str]:
    return [
        t for t in TOK_RE.findall(text.lower())
        if len(t) >= 4 and t not in STOP
    ]


def main() -> int:
    detection = json.loads((OUT_DIR / ".graphify_detect.json").read_text())
    ast = json.loads((OUT_DIR / ".graphify_ast.json").read_text())
    print(f"[ast]  {len(ast['nodes'])} nodes, {len(ast['edges'])} edges loaded")

    # Collect surviving semantic chunks
    sem_nodes: list[dict] = []
    sem_edges: list[dict] = []
    sem_hyperedges: list[dict] = []
    surviving: list[int] = []
    missing: list[int] = []

    manifest = json.loads((CHUNKS_DIR / "manifest.json").read_text())
    total_chunks = manifest["total_chunks"]

    for n in range(1, total_chunks + 1):
        result_path = CHUNKS_DIR / f"chunk_{n:02d}_result.json"
        if not result_path.exists():
            missing.append(n)
            continue
        try:
            d = json.loads(result_path.read_text())
            sem_nodes.extend(d.get("nodes", []))
            sem_edges.extend(d.get("edges", []))
            sem_hyperedges.extend(d.get("hyperedges", []))
            surviving.append(n)
        except Exception as e:
            print(f"[warn] chunk {n} unreadable: {e}")
            missing.append(n)

    print(f"[sem]  {len(surviving)}/{total_chunks} chunks recovered: {surviving}")
    if missing:
        print(f"[sem]  missing chunks: {missing}")
    print(f"[sem]  {len(sem_nodes)} nodes, {len(sem_edges)} edges, {len(sem_hyperedges)} hyperedges")

    # Merge AST + semantic, dedupe by node id (AST wins)
    seen = {n["id"] for n in ast["nodes"]}
    merged_nodes = list(ast["nodes"])
    for sn in sem_nodes:
        if sn.get("id") not in seen:
            merged_nodes.append(sn)
            seen.add(sn["id"])
    merged_edges = ast["edges"] + sem_edges

    extraction = {
        "nodes": merged_nodes,
        "edges": merged_edges,
        "hyperedges": sem_hyperedges,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    (OUT_DIR / ".graphify_extract.json").write_text(json.dumps(extraction))
    print(f"[merge] {len(merged_nodes)} nodes, {len(merged_edges)} edges, {len(sem_hyperedges)} hyperedges")

    # Build, cluster, analyze
    G = build_from_json(extraction, directed=DIRECTED)
    if G.number_of_nodes() == 0:
        print("[build] graph empty, aborting")
        return 1
    print(f"[build] {G.number_of_nodes()} nodes, {G.number_of_edges()} edges (directed={DIRECTED})")

    print("[cluster] louvain")
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
        labels[cid] = " / ".join(top[:3]) if top else f"Community {cid}"

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

    print(f"[html] forcing render at {G.number_of_nodes()} nodes (default cap 5000 disabled)")
    to_html(
        G,
        communities,
        str(OUT_DIR / "graph.html"),
        community_labels=labels,
    )
    print(f"[html] {OUT_DIR / 'graph.html'}")

    # Coverage report
    print()
    print("=" * 70)
    print("FULL RUN — MERGE SUMMARY")
    print("=" * 70)
    print(f"  AST coverage:       {len(ast['nodes'])} nodes (full code corpus, free)")
    print(f"  Semantic coverage:  {len(surviving)}/{total_chunks} chunks recovered")
    if missing:
        for m in missing:
            cd = json.loads((CHUNKS_DIR / f"chunk_{m:02d}.json").read_text())
            first = Path(cd["files"][0]).name
            last = Path(cd["files"][-1]).name
            print(f"    chunk {m}: LOST  ({len(cd['files'])} files, {first} -> {last})")
    print()
    print(f"  Merged graph:       {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print(f"  Communities:        {len(communities)}")
    print(f"  God nodes:          {len(gods)}")
    print(f"  Surprises:          {len(surprises)}")
    print()
    print("Top 20 god nodes (most-connected concepts):")
    for i, gn in enumerate(gods[:20], 1):
        lbl = gn.get("label") if isinstance(gn, dict) else str(gn)
        deg = gn.get("degree") if isinstance(gn, dict) else "?"
        src = gn.get("source_file", "") if isinstance(gn, dict) else ""
        if isinstance(src, str) and "Personal Finance Project" in src:
            src = src.split("Personal Finance Project", 1)[-1].lstrip("\\/")
        print(f"  {i:>2}. {lbl}  ({deg} edges)  {src}")
    print()
    print("Communities sorted by size:")
    for cid in sorted(communities, key=lambda c: -len(communities[c])):
        n = len(communities[cid])
        if n < 4:
            continue
        print(f"  [{cid:>3}] {labels[cid]:<60} ({n} nodes)")
    print()
    print(f"  graph.html:        {(OUT_DIR / 'graph.html').resolve()}")
    print(f"  GRAPH_REPORT.md:   {(OUT_DIR / 'GRAPH_REPORT.md').resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
