"""Re-label communities with a stoplist for filler tokens, regenerate report+HTML."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from graphify.analyze import god_nodes, suggest_questions, surprising_connections
from graphify.build import build_from_json
from graphify.cluster import score_all
from graphify.export import to_html, to_json
from graphify.report import generate
from networkx.readwrite import json_graph

OUT_DIR = Path("graphify-out")
INPUT_PATH = (
    r"C:\Users\chang\OneDrive\Desktop\Projects\Personal Finance Project\backend"
)

# Generic English + code-pattern fillers worth dropping from auto-labels.
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
    "opt", "opts", "option", "options",
    "sentry", "finance", "backend",
    "py", "json", "html",
    "api", "fastapi", "pydantic", "model", "schema",
    "yes", "ok", "if", "else", "when", "where", "what", "how", "why",
    "see", "section", "above", "below",
}

TOK_RE = re.compile(r"[a-z][a-z0-9]+")


def _tokens(text: str) -> list[str]:
    """Lowercase tokens of length >= 4, alpha-num, not in stop list."""
    return [
        t for t in TOK_RE.findall(text.lower())
        if len(t) >= 4 and t not in STOP
    ]


def main() -> int:
    extraction = json.loads((OUT_DIR / ".graphify_extract.json").read_text())
    detection = json.loads((OUT_DIR / ".graphify_detect.json").read_text())

    G = build_from_json(extraction, directed=True)
    # Re-derive communities from graph.json instead of re-clustering, so the
    # node-set matches what was rendered. Actually simpler: just re-cluster.
    from graphify.cluster import cluster
    communities = cluster(G)
    cohesion = score_all(G, communities)
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)

    labels: dict[int, str] = {}
    for cid, members in communities.items():
        bag: Counter[str] = Counter()
        for nid in members:
            label = G.nodes[nid].get("label", nid)
            for tok in _tokens(str(label)):
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
        INPUT_PATH,
        suggested_questions=questions,
    )
    (OUT_DIR / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    to_json(G, communities, str(OUT_DIR / "graph.json"))
    to_html(
        G,
        communities,
        str(OUT_DIR / "graph.html"),
        community_labels=labels,
    )

    print(f"  nodes:           {G.number_of_nodes()}")
    print(f"  edges:           {G.number_of_edges()}")
    print(f"  communities:     {len(communities)}")
    print()
    print("Community labels (with stoplist):")
    for cid in sorted(communities):
        n = len(communities[cid])
        print(f"  [{cid:>2}] {labels[cid]:<45}  ({n} nodes)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
