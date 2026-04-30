"""Run the graphify pipeline against the project backend, end-to-end.

Mirrors the steps in graphify's skill.md but invokes the Python API directly
so we don't need an agent host. Code-only corpus means we skip semantic
extraction (no LLM cost). Communities are auto-labeled from top node labels.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from graphify.analyze import god_nodes, suggest_questions, surprising_connections
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.detect import detect, save_manifest
from graphify.export import to_html, to_json
from graphify.extract import collect_files, extract
from graphify.report import generate

INPUT_PATH = Path(
    r"C:\Users\chang\OneDrive\Desktop\Projects\Personal Finance Project\backend"
)
OUT_DIR = Path("graphify-out")
DIRECTED = True


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)

    # Step 2: detect
    print(f"[detect] scanning {INPUT_PATH}")
    detection = detect(INPUT_PATH)
    (OUT_DIR / ".graphify_detect.json").write_text(json.dumps(detection))
    print(
        f"[detect] {detection.get('total_files', 0)} files, "
        f"~{detection.get('total_words', 0):,} words"
    )
    counts = {k: len(v) for k, v in detection.get("files", {}).items() if v}
    print(f"[detect] by category: {counts}")

    skipped = detection.get("skipped_sensitive", []) or []
    if skipped:
        print(f"[detect] skipped {len(skipped)} sensitive files")

    if detection.get("total_files", 0) == 0:
        print("[detect] no supported files found")
        return 1

    # Step 3 Part A: AST extraction (deterministic, free)
    code_files: list[Path] = []
    for f in detection.get("files", {}).get("code", []):
        p = Path(f)
        code_files.extend(collect_files(p) if p.is_dir() else [p])

    if not code_files:
        print("[ast] no code files found, aborting (this trial is code-only)")
        return 1

    print(f"[ast] running tree-sitter extraction on {len(code_files)} code files")
    ast_result = extract(code_files, cache_root=Path("."))
    print(
        f"[ast] {len(ast_result['nodes'])} nodes, "
        f"{len(ast_result['edges'])} edges"
    )

    # Code-only fast path: no semantic extraction needed
    has_non_code = any(
        detection.get("files", {}).get(k, [])
        for k in ("document", "doc", "docs", "paper", "papers", "image", "images")
    )
    if has_non_code:
        print("[semantic] non-code files detected, but trial is AST-only — skipping")
    else:
        print("[semantic] code-only corpus, skipping (per graphify fast-path rule)")

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
        print("[build] graph is empty — aborting")
        return 1
    print(f"[build] {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    print("[cluster] louvain community detection")
    communities = cluster(G)
    cohesion = score_all(G, communities)
    print(f"[cluster] {len(communities)} communities")

    print("[analyze] god nodes, surprising connections")
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)

    # Auto-label communities by most common node-label tokens
    labels: dict[int, str] = {}
    for cid, members in communities.items():
        # Take label tokens from member nodes, count, pick top 3 distinctive ones.
        bag: Counter[str] = Counter()
        for nid in members:
            label = G.nodes[nid].get("label", nid)
            for tok in str(label).replace("_", " ").split():
                tok = tok.strip().lower()
                if len(tok) >= 3 and tok.isalnum():
                    bag[tok] += 1
        top = [t for t, _ in bag.most_common(4)]
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
        str(INPUT_PATH),
        suggested_questions=questions,
    )
    (OUT_DIR / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    to_json(G, communities, str(OUT_DIR / "graph.json"))
    print(f"[report] {OUT_DIR / 'GRAPH_REPORT.md'}")
    print(f"[json] {OUT_DIR / 'graph.json'}")

    # Step 6: HTML
    if G.number_of_nodes() > 5000:
        print(f"[html] graph has {G.number_of_nodes()} nodes — too large, skipping")
    else:
        to_html(
            G,
            communities,
            str(OUT_DIR / "graph.html"),
            community_labels=labels,
        )
        print(f"[html] {OUT_DIR / 'graph.html'}")

    # Save manifest for future --update
    save_manifest(detection.get("files", {}))

    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  files processed: {detection.get('total_files', 0)}")
    print(f"  nodes:           {G.number_of_nodes()}")
    print(f"  edges:           {G.number_of_edges()}")
    print(f"  communities:     {len(communities)}")
    print(f"  god nodes:       {len(gods)}")
    print(f"  surprises:       {len(surprises)}")
    print(f"  llm tokens used: 0 (AST-only path)")
    print()
    print("Community labels:")
    for cid in sorted(communities):
        print(f"  [{cid:>2}] {labels[cid]:<40}  ({len(communities[cid])} nodes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
