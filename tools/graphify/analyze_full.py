"""Run drift / loose-end analysis on the full graph."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from networkx.readwrite import json_graph

GRAPH_JSON = Path("graphify-out-full/graph.json")


def main() -> None:
    data = json.loads(GRAPH_JSON.read_text())
    G = json_graph.node_link_graph(data, edges="links")

    print(f"Loaded: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print()

    # 1. AI-NNN action items
    ai_pattern = re.compile(r"\bAI[-_]?\d{3}\b", re.I)
    ai_nodes = []
    for nid, d in G.nodes(data=True):
        label = str(d.get("label", "")) + " " + str(nid)
        if ai_pattern.search(label):
            ai_nodes.append((nid, d, G.degree(nid)))

    ai_orphans = [a for a in ai_nodes if a[2] == 0]
    ai_lonely = [a for a in ai_nodes if a[2] == 1]
    ai_well = [a for a in ai_nodes if a[2] >= 2]

    print(f"AI-NNN nodes:           {len(ai_nodes)}")
    print(f"  orphans (0 edges):    {len(ai_orphans)}")
    print(f"  lonely (1 edge):      {len(ai_lonely)}")
    print(f"  connected (2+ edges): {len(ai_well)}")
    print()
    print("Top 10 AI-NNN by connectivity:")
    for nid, d, deg in sorted(ai_nodes, key=lambda a: -a[2])[:10]:
        print(f"  {deg:>3} edges  {d.get('label', nid)[:80]}")
    print()
    if ai_orphans:
        print(f"AI-NNN orphans (first 15):")
        for nid, d, _ in ai_orphans[:15]:
            print(f"  - {d.get('label', nid)[:90]}")
    print()

    # 2. Lineage YAML nodes and their connectivity to DAL
    lineage_nodes = [
        (nid, d, G.degree(nid))
        for nid, d in G.nodes(data=True)
        if "data-lineage" in str(d.get("source_file", "")).lower()
        or "lineage" in str(d.get("label", "")).lower()
    ]
    print(f"Lineage-related nodes:  {len(lineage_nodes)}")
    print(f"  orphans:              {sum(1 for _,_,d in lineage_nodes if d == 0)}")
    print(f"  with 1 edge:          {sum(1 for _,_,d in lineage_nodes if d == 1)}")
    print(f"  with 5+ edges:        {sum(1 for _,_,d in lineage_nodes if d >= 5)}")
    print()

    # 3. Overall orphan/loose-end counts
    degree_dist: Counter[int] = Counter(dict(G.degree()).values())
    orphans = [(nid, d) for nid, d in G.nodes(data=True) if G.degree(nid) == 0]
    lonely = [(nid, d) for nid, d in G.nodes(data=True) if G.degree(nid) == 1]
    print(f"Loose-end taxonomy across all 5148 nodes:")
    print(f"  degree 0 (orphans):    {len(orphans)}")
    print(f"  degree 1 (lonely):     {len(lonely)}")
    print(f"  degree 2-4 (small):    {sum(c for d,c in degree_dist.items() if 2 <= d <= 4)}")
    print(f"  degree 5-19 (medium):  {sum(c for d,c in degree_dist.items() if 5 <= d <= 19)}")
    print(f"  degree 20+ (hubs):     {sum(c for d,c in degree_dist.items() if d >= 20)}")
    print()

    # 4. Community size distribution
    by_community = defaultdict(list)
    for nid, d in G.nodes(data=True):
        cid = d.get("community", -1)
        by_community[cid].append(nid)
    print(f"Community size distribution:")
    sizes = sorted([len(v) for v in by_community.values()], reverse=True)
    print(f"  total:        {len(sizes)}")
    print(f"  single-node:  {sum(1 for s in sizes if s == 1)}")
    print(f"  2-3 nodes:    {sum(1 for s in sizes if 2 <= s <= 3)}")
    print(f"  4-9 nodes:    {sum(1 for s in sizes if 4 <= s <= 9)}")
    print(f"  10-49 nodes:  {sum(1 for s in sizes if 10 <= s <= 49)}")
    print(f"  50+ nodes:    {sum(1 for s in sizes if s >= 50)}")
    print()

    # 5. Edge confidence distribution
    by_conf: Counter[str] = Counter()
    for u, v, d in G.edges(data=True):
        by_conf[d.get("confidence", "UNKNOWN")] += 1
    print(f"Edge confidence:")
    for conf, n in by_conf.most_common():
        print(f"  {conf}: {n} ({n*100/G.number_of_edges():.1f}%)")
    print()

    # 6. Drift candidates: semantic_similar_to edges (suggest duplicated concepts)
    sim_edges = [
        (u, v, d) for u, v, d in G.edges(data=True)
        if d.get("relation") == "semantically_similar_to"
    ]
    print(f"semantically_similar_to edges (drift candidates): {len(sim_edges)}")
    for u, v, d in sim_edges[:15]:
        ulabel = G.nodes[u].get("label", u)[:60]
        vlabel = G.nodes[v].get("label", v)[:60]
        score = d.get("confidence_score", "?")
        print(f"  [{score}] {ulabel}")
        print(f"          ~~ {vlabel}")
    print()

    # 7. Orphan node sample (first 20 by source file)
    print(f"Sample of orphaned nodes (first 20):")
    for nid, d in orphans[:20]:
        src = str(d.get("source_file", ""))
        if "Personal Finance Project" in src:
            src = src.split("Personal Finance Project", 1)[-1].lstrip("\\/")
        label = d.get("label", nid)[:60]
        print(f"  {label}    [{src or 'no source'}]")


if __name__ == "__main__":
    main()
