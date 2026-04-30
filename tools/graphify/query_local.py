"""Query committed Graphify audit snapshots without graphify dependencies.

This module is intentionally dependency-light: it reads the committed
``docs/audits/graphify-*/graph.json`` node-link files and builds a small local
index for development navigation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_ROOT = PROJECT_ROOT / "docs" / "audits"
DEFAULT_GRAPH_PATTERN = "graphify-*/graph.json"
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "tool",
    "tools",
    "tooling",
    "with",
}
LOW_SIGNAL_TOKENS = {
    "api",
    "browser",
    "cli",
    "connector",
    "data",
    "file",
    "graph",
    "json",
    "local",
    "node",
    "parser",
    "report",
    "script",
    "tool",
    "tooling",
}
AI_ID_RE = re.compile(r"\bAI[-_]?\d{3}\b", re.IGNORECASE)
TIMESTAMP_RE = re.compile(
    r"(?:20\d{2}[-_]?\d{2}[-_]?\d{2}|20\d{6})(?:[-_ ]?\d{4,6})?"
)


@dataclass(frozen=True)
class SearchHit:
    node_id: str
    label: str
    score: float
    degree: int
    community: Any
    source_file: str


class GraphQueryError(RuntimeError):
    """Raised when a graph query cannot be resolved."""


class LocalGraph:
    """Small in-memory index over a Graphify node-link JSON file."""

    def __init__(self, graph_path: Path, repo_root: Path = PROJECT_ROOT) -> None:
        self.path = graph_path
        self.repo_root = repo_root
        self.data = json.loads(graph_path.read_text(encoding="utf-8"))
        self.nodes: list[dict[str, Any]] = list(self.data.get("nodes", []))
        self.links: list[dict[str, Any]] = list(self.data.get("links", []))
        self.hyperedges: list[dict[str, Any]] = list(self.data.get("hyperedges", []))
        self.node_ids = [str(node.get("id", index)) for index, node in enumerate(self.nodes)]
        self.nodes_by_id = {
            str(node.get("id", index)): node for index, node in enumerate(self.nodes)
        }
        self.adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        self._build_adjacency()

    def _build_adjacency(self) -> None:
        for edge in self.links:
            source = self.endpoint_to_node_id(edge.get("source"))
            target = self.endpoint_to_node_id(edge.get("target"))
            if source not in self.nodes_by_id or target not in self.nodes_by_id:
                continue
            self.adjacency[source].append((target, edge))
            self.adjacency[target].append((source, edge))

    def endpoint_to_node_id(self, endpoint: Any) -> str:
        if isinstance(endpoint, int) and 0 <= endpoint < len(self.node_ids):
            return self.node_ids[endpoint]
        text = str(endpoint)
        if text in self.nodes_by_id:
            return text
        return text

    def degree(self, node_id: str) -> int:
        return len(self.adjacency.get(node_id, []))

    def node_label(self, node_id: str) -> str:
        node = self.nodes_by_id.get(node_id, {})
        return str(node.get("label") or node_id)

    def node_source(self, node_id: str) -> str:
        node = self.nodes_by_id.get(node_id, {})
        return display_path(node.get("source_file", ""), self.repo_root)

    def search(self, term: str, limit: int = 10) -> list[SearchHit]:
        query = normalize_text(term)
        compact_query = compact_text(term)
        tokens = token_set(term)
        hits: list[SearchHit] = []

        for node_id, node in self.nodes_by_id.items():
            label = str(node.get("label") or node_id)
            source_file = str(node.get("source_file") or "")
            haystack = normalize_text(" ".join([node_id, label, source_file]))
            compact_haystack = compact_text(" ".join([node_id, label, source_file]))
            score = 0.0

            if query and query == normalize_text(node_id):
                score += 120
            if query and query == normalize_text(label):
                score += 100
            if query and query in normalize_text(node_id):
                score += 60
            if query and query in normalize_text(label):
                score += 55
            if query and query in normalize_text(source_file):
                score += 18
            if compact_query and compact_query in compact_haystack:
                score += 35

            for token in tokens:
                token_weight = 0.35 if token in LOW_SIGNAL_TOKENS else 1.0
                if token in normalize_text(node_id):
                    score += 14 * token_weight
                if token in normalize_text(label):
                    score += 12 * token_weight
                if token in normalize_text(source_file):
                    score += 4 * token_weight

            if score <= 0:
                continue

            degree = self.degree(node_id)
            score += min(degree, 50) * 0.08
            hits.append(
                SearchHit(
                    node_id=node_id,
                    label=label,
                    score=round(score, 3),
                    degree=degree,
                    community=node.get("community"),
                    source_file=display_path(source_file, self.repo_root),
                )
            )

        hits.sort(key=lambda hit: (-hit.score, -hit.degree, hit.label.lower()))
        return hits[:limit]

    def resolve_node(self, term_or_node_id: str) -> SearchHit:
        if term_or_node_id in self.nodes_by_id:
            return self._hit_for_node(term_or_node_id, 999.0)
        hits = self.search(term_or_node_id, limit=1)
        if not hits:
            raise GraphQueryError(f"No graph node matched {term_or_node_id!r}")
        return hits[0]

    def _hit_for_node(self, node_id: str, score: float = 0.0) -> SearchHit:
        node = self.nodes_by_id[node_id]
        return SearchHit(
            node_id=node_id,
            label=str(node.get("label") or node_id),
            score=score,
            degree=self.degree(node_id),
            community=node.get("community"),
            source_file=display_path(node.get("source_file", ""), self.repo_root),
        )

    def neighbors(self, term_or_node_id: str, limit: int = 20) -> dict[str, Any]:
        resolved = self.resolve_node(term_or_node_id)
        rows: list[dict[str, Any]] = []
        for neighbor_id, edge in self.adjacency.get(resolved.node_id, []):
            rows.append(
                {
                    "node_id": neighbor_id,
                    "label": self.node_label(neighbor_id),
                    "degree": self.degree(neighbor_id),
                    "community": self.nodes_by_id.get(neighbor_id, {}).get("community"),
                    "relation": str(edge.get("relation") or ""),
                    "confidence": numeric_confidence(edge),
                    "confidence_kind": str(edge.get("confidence") or ""),
                    "source_file": display_path(edge.get("source_file", ""), self.repo_root),
                    "node_source_file": self.node_source(neighbor_id),
                }
            )
        rows.sort(key=lambda row: (-row["confidence"], -row["degree"], row["label"].lower()))
        return {"resolved": hit_to_dict(resolved), "neighbors": rows[:limit]}

    def impact(self, term: str, limit: int = 20) -> dict[str, Any]:
        all_hits = self.search(term, limit=12)
        direct_hits = [
            hit for hit in all_hits if meaningful_hit(term, hit.node_id, self.nodes_by_id[hit.node_id])
        ][:8]
        seed_hits = list(direct_hits)
        direct_match = bool(seed_hits)

        if not seed_hits:
            seen: set[str] = set()
            for token in high_signal_tokens(term):
                for hit in self.search(token, limit=3):
                    if hit.node_id not in seen:
                        seed_hits.append(hit)
                        seen.add(hit.node_id)
            seed_hits = seed_hits[:8]

        seed_ids = {hit.node_id for hit in seed_hits}
        source_files: set[str] = {hit.source_file for hit in seed_hits if hit.source_file}
        neighbor_rows: list[dict[str, Any]] = []

        for seed_id in seed_ids:
            for neighbor_id, edge in self.adjacency.get(seed_id, []):
                neighbor_source = self.node_source(neighbor_id)
                edge_source = display_path(edge.get("source_file", ""), self.repo_root)
                if neighbor_source:
                    source_files.add(neighbor_source)
                if edge_source:
                    source_files.add(edge_source)
                neighbor_rows.append(
                    {
                        "node_id": neighbor_id,
                        "label": self.node_label(neighbor_id),
                        "degree": self.degree(neighbor_id),
                        "community": self.nodes_by_id.get(neighbor_id, {}).get("community"),
                        "relation": str(edge.get("relation") or ""),
                        "confidence": numeric_confidence(edge),
                        "source_file": edge_source,
                        "node_source_file": neighbor_source,
                    }
                )

        neighbor_rows = dedupe_dicts(neighbor_rows, "node_id")
        neighbor_rows.sort(
            key=lambda row: (-row["confidence"], -row["degree"], row["label"].lower())
        )

        hyperedge_rows = self.matching_hyperedges(term, seed_ids, limit=10)
        for hyperedge in hyperedge_rows:
            if hyperedge["source_file"]:
                source_files.add(hyperedge["source_file"])
            for node_id in hyperedge.get("nodes", []):
                node_source = self.node_source(str(node_id))
                if node_source:
                    source_files.add(node_source)

        notes = []
        if not direct_match:
            notes.append(
                "No direct node matched the full phrase; results use significant-token fallback."
            )
        if not direct_match and all_hits and not seed_hits:
            notes.append(
                "Low-signal token matches were ignored so generic graph nodes do not mask a coverage gap."
            )
        if not seed_hits:
            notes.append("No useful seed nodes found in this graph snapshot.")

        return {
            "query": term,
            "graph": display_path(self.path, self.repo_root),
            "direct_match": direct_match,
            "matched_nodes": [hit_to_dict(hit) for hit in seed_hits],
            "key_hyperedges": hyperedge_rows,
            "neighbor_nodes": neighbor_rows[:limit],
            "files": group_files(source_files),
            "notes": notes,
        }

    def matching_hyperedges(
        self, term: str, seed_ids: set[str], limit: int = 10
    ) -> list[dict[str, Any]]:
        query_tokens = token_set(term)
        signal_tokens = set(high_signal_tokens(term))
        if not signal_tokens:
            signal_tokens = set(significant_tokens(term))
        if not seed_ids:
            if signal_tokens:
                query_tokens = signal_tokens
        rows: list[dict[str, Any]] = []
        for hyperedge in self.hyperedges:
            nodes = [str(node_id) for node_id in hyperedge.get("nodes", [])]
            label = str(hyperedge.get("label") or hyperedge.get("id") or "")
            text = normalize_text(" ".join([label, str(hyperedge.get("id", "")), *nodes]))
            overlap = len(seed_ids.intersection(nodes))
            token_hits = sum(1 for token in query_tokens if token in text)
            signal_hits = sum(1 for token in signal_tokens if token in text)
            if overlap <= 0 and signal_hits <= 0:
                continue
            rows.append(
                {
                    "id": str(hyperedge.get("id") or label),
                    "label": label,
                    "relation": str(hyperedge.get("relation") or ""),
                    "confidence": numeric_confidence(hyperedge),
                    "confidence_kind": str(hyperedge.get("confidence") or ""),
                    "source_file": display_path(
                        hyperedge.get("source_file", ""), self.repo_root
                    ),
                    "node_count": len(nodes),
                    "nodes": nodes,
                    "match_score": overlap * 10 + signal_hits * 3 + token_hits * 0.2,
                }
            )
        rows.sort(
            key=lambda row: (
                -row["match_score"],
                -row["confidence"],
                -row["node_count"],
                row["label"].lower(),
            )
        )
        return rows[:limit]

    def drift_candidates(
        self,
        min_confidence: float = 0.85,
        include_expected_audit_reports: bool = False,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for edge in self.links:
            relation = str(edge.get("relation") or "").lower()
            if relation != "semantically_similar_to":
                continue
            confidence = numeric_confidence(edge)
            if confidence < min_confidence:
                continue
            source_id = self.endpoint_to_node_id(edge.get("source"))
            target_id = self.endpoint_to_node_id(edge.get("target"))
            source_label = self.node_label(source_id)
            target_label = self.node_label(target_id)
            source_file = self.node_source(source_id)
            target_file = self.node_source(target_id)
            expected = is_expected_audit_report_pair(
                source_label, target_label, source_file, target_file
            )
            if expected and not include_expected_audit_reports:
                continue
            rows.append(
                {
                    "source_id": source_id,
                    "source_label": source_label,
                    "target_id": target_id,
                    "target_label": target_label,
                    "confidence": confidence,
                    "source_file": source_file,
                    "target_file": target_file,
                    "edge_source_file": display_path(
                        edge.get("source_file", ""), self.repo_root
                    ),
                    "expected_audit_report_pair": expected,
                }
            )
        rows.sort(
            key=lambda row: (
                -row["confidence"],
                row["source_label"].lower(),
                row["target_label"].lower(),
            )
        )
        return rows

    def hubs(self, limit: int = 15, previous: "LocalGraph | None" = None) -> dict[str, Any]:
        node_rows = []
        for node_id in self.nodes_by_id:
            degree = self.degree(node_id)
            if degree <= 0:
                continue
            previous_degree = previous.degree(node_id) if previous and node_id in previous.nodes_by_id else None
            node_rows.append(
                {
                    "node_id": node_id,
                    "label": self.node_label(node_id),
                    "degree": degree,
                    "previous_degree": previous_degree,
                    "degree_delta": None
                    if previous_degree is None
                    else degree - previous_degree,
                    "community": self.nodes_by_id[node_id].get("community"),
                    "source_file": self.node_source(node_id),
                    "high_risk_if_changed": degree >= 20,
                }
            )
        node_rows.sort(key=lambda row: (-row["degree"], row["label"].lower()))

        hyperedge_rows = []
        previous_hyperedges = {}
        if previous:
            previous_hyperedges = {
                str(edge.get("id") or edge.get("label")): edge
                for edge in previous.hyperedges
            }
        for hyperedge in self.hyperedges:
            key = str(hyperedge.get("id") or hyperedge.get("label"))
            nodes = list(hyperedge.get("nodes", []))
            previous_count = None
            if key in previous_hyperedges:
                previous_count = len(previous_hyperedges[key].get("nodes", []))
            hyperedge_rows.append(
                {
                    "id": key,
                    "label": str(hyperedge.get("label") or key),
                    "node_count": len(nodes),
                    "previous_node_count": previous_count,
                    "node_count_delta": None
                    if previous_count is None
                    else len(nodes) - previous_count,
                    "confidence": numeric_confidence(hyperedge),
                    "source_file": display_path(
                        hyperedge.get("source_file", ""), self.repo_root
                    ),
                    "high_risk_if_changed": len(nodes) >= 5,
                }
            )
        hyperedge_rows.sort(
            key=lambda row: (-row["node_count"], -row["confidence"], row["label"].lower())
        )
        return {
            "graph": display_path(self.path, self.repo_root),
            "nodes": node_rows[:limit],
            "hyperedges": hyperedge_rows[:limit],
        }

    def quality(self, previous: "LocalGraph | None" = None) -> dict[str, Any]:
        degrees = {node_id: self.degree(node_id) for node_id in self.nodes_by_id}
        confidence_counts = Counter(
            str(edge.get("confidence") or "UNKNOWN") for edge in self.links
        )
        relation_counts = Counter(str(edge.get("relation") or "") for edge in self.links)
        ai_ids = collect_ai_ids(self)
        readme_text = read_sibling_readme(self.path)
        mixed_warning = mixed_extraction_warning(readme_text)

        summary: dict[str, Any] = {
            "graph": display_path(self.path, self.repo_root),
            "nodes": len(self.nodes),
            "edges": len(self.links),
            "hyperedges": len(self.hyperedges),
            "communities": len(
                {node.get("community") for node in self.nodes if node.get("community") is not None}
            ),
            "orphans": sum(1 for degree in degrees.values() if degree == 0),
            "lonely": sum(1 for degree in degrees.values() if degree == 1),
            "hubs_degree_20_plus": sum(1 for degree in degrees.values() if degree >= 20),
            "density_edges_per_node": round(len(self.links) / max(len(self.nodes), 1), 3),
            "confidence_counts": dict(sorted(confidence_counts.items())),
            "top_relations": dict(relation_counts.most_common(10)),
            "ai_nnn_count": len(ai_ids),
            "ai_nnn_ids": sorted(ai_ids),
            "mixed_extraction_warning": mixed_warning,
        }

        if previous:
            previous_ai_ids = collect_ai_ids(previous)
            summary["previous_graph"] = display_path(previous.path, self.repo_root)
            summary["delta"] = {
                "nodes": len(self.nodes) - len(previous.nodes),
                "edges": len(self.links) - len(previous.links),
                "hyperedges": len(self.hyperedges) - len(previous.hyperedges),
                "communities": summary["communities"]
                - len(
                    {
                        node.get("community")
                        for node in previous.nodes
                        if node.get("community") is not None
                    }
                ),
                "ai_nnn_count": len(ai_ids) - len(previous_ai_ids),
            }
            summary["previous_ai_nnn_count"] = len(previous_ai_ids)
            summary["ai_nnn_missing_from_current"] = sorted(previous_ai_ids - ai_ids)
        return summary


def discover_graphs(repo_root: Path = PROJECT_ROOT) -> list[Path]:
    audit_root = repo_root / "docs" / "audits"
    return sorted(audit_root.glob(DEFAULT_GRAPH_PATTERN), key=lambda path: path.parent.name)


def discover_latest_graph(repo_root: Path = PROJECT_ROOT) -> Path:
    graphs = discover_graphs(repo_root)
    if not graphs:
        raise GraphQueryError(f"No graphify snapshots found under {repo_root / 'docs' / 'audits'}")
    return graphs[-1]


def discover_previous_graph(
    selected_graph: Path, repo_root: Path = PROJECT_ROOT
) -> Path | None:
    graphs = [path for path in discover_graphs(repo_root) if path != selected_graph]
    older = [path for path in graphs if path.parent.name < selected_graph.parent.name]
    if older:
        return older[-1]
    return graphs[-1] if graphs else None


def load_graph(path: Path | None, repo_root: Path = PROJECT_ROOT) -> LocalGraph:
    graph_path = path or discover_latest_graph(repo_root)
    return LocalGraph(graph_path, repo_root=repo_root)


def load_previous_graph(
    selected_graph: Path,
    previous_graph_path: Path | None,
    repo_root: Path = PROJECT_ROOT,
) -> LocalGraph | None:
    path = previous_graph_path or discover_previous_graph(selected_graph, repo_root)
    if not path or not path.exists():
        return None
    return LocalGraph(path, repo_root=repo_root)


def normalize_text(value: Any) -> str:
    return str(value or "").casefold()


def compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value))


def token_set(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalize_text(value))
        if token and token not in STOPWORDS
    }


def significant_tokens(value: str) -> list[str]:
    return sorted(token for token in token_set(value) if len(token) >= 3)


def high_signal_tokens(value: str) -> list[str]:
    return sorted(
        token
        for token in significant_tokens(value)
        if token not in LOW_SIGNAL_TOKENS
    )


def meaningful_hit(term: str, node_id: str, node: dict[str, Any]) -> bool:
    label = str(node.get("label") or node_id)
    source_file = str(node.get("source_file") or "")
    haystack = normalize_text(" ".join([node_id, label, source_file]))
    compact_haystack = compact_text(" ".join([node_id, label, source_file]))
    compact_query = compact_text(term)
    if compact_query and compact_query in compact_haystack:
        return True

    tokens = high_signal_tokens(term)
    if not tokens:
        tokens = significant_tokens(term)
    return any(token in haystack for token in tokens)


def numeric_confidence(item: dict[str, Any]) -> float:
    for key in ("confidence_score", "score", "weight"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    value = item.get("confidence")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def display_path(value: Any, repo_root: Path = PROJECT_ROOT) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""

    try:
        path = Path(text)
        if path.is_absolute():
            return path.relative_to(repo_root).as_posix()
    except (OSError, ValueError):
        pass

    root_text = str(repo_root).replace("/", "\\")
    lowered = text.casefold()
    root_lowered = root_text.casefold()
    if root_lowered in lowered:
        index = lowered.index(root_lowered)
        relative = text[index + len(root_text) :].lstrip("\\/")
        return relative.replace("\\", "/")
    return text.replace("\\", "/")


def hit_to_dict(hit: SearchHit) -> dict[str, Any]:
    return {
        "node_id": hit.node_id,
        "label": hit.label,
        "score": hit.score,
        "degree": hit.degree,
        "community": hit.community,
        "source_file": hit.source_file,
    }


def dedupe_dicts(rows: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[Any] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        value = row.get(key)
        if value in seen:
            continue
        seen.add(value)
        result.append(row)
    return result


def group_files(paths: Iterable[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {
        "backend": [],
        "dal": [],
        "extractors": [],
        "frontend": [],
        "scripts_tools": [],
        "tests": [],
        "docs": [],
        "lineage": [],
        "other": [],
    }
    for path in sorted({path for path in paths if path}):
        normalized = path.replace("\\", "/")
        lowered = normalized.casefold()
        if lowered.startswith("tests/") or "/tests/" in lowered:
            groups["tests"].append(normalized)
        elif "docs/data-lineage/" in lowered:
            groups["lineage"].append(normalized)
        elif lowered.startswith("docs/") or "/docs/" in lowered:
            groups["docs"].append(normalized)
        elif lowered.startswith("frontend/src/") or "/frontend/src/" in lowered:
            groups["frontend"].append(normalized)
        elif lowered.startswith("backend/") or "/backend/" in lowered:
            groups["backend"].append(normalized)
        elif lowered.startswith("dal/") or "/dal/" in lowered:
            groups["dal"].append(normalized)
        elif lowered.startswith("extractors/") or "/extractors/" in lowered:
            groups["extractors"].append(normalized)
        elif lowered.startswith("scripts/") or lowered.startswith("tools/"):
            groups["scripts_tools"].append(normalized)
        else:
            groups["other"].append(normalized)
    return {name: values for name, values in groups.items() if values}


def is_expected_audit_report_pair(
    source_label: str,
    target_label: str,
    source_file: str,
    target_file: str,
) -> bool:
    combined_source = " ".join([source_label, source_file]).casefold()
    combined_target = " ".join([target_label, target_file]).casefold()
    both_number_trust = "number" in combined_source and "trust" in combined_source
    both_number_trust = both_number_trust and "number" in combined_target and "trust" in combined_target
    both_reports = (
        ("report" in combined_source or "audit" in combined_source)
        and ("report" in combined_target or "audit" in combined_target)
    )
    timestamped = bool(TIMESTAMP_RE.search(combined_source)) and bool(
        TIMESTAMP_RE.search(combined_target)
    )
    same_report_dir = (
        "docs/audits/number-trust/reports" in source_file.casefold()
        and "docs/audits/number-trust/reports" in target_file.casefold()
    )
    return both_number_trust and both_reports and (timestamped or same_report_dir)


def collect_ai_ids(graph: LocalGraph) -> set[str]:
    ids: set[str] = set()
    for node in graph.nodes:
        text = " ".join(
            [
                str(node.get("id", "")),
                str(node.get("label", "")),
                str(node.get("source_file", "")),
            ]
        )
        ids.update(match.upper().replace("_", "-") for match in AI_ID_RE.findall(text))
    return ids


def read_sibling_readme(graph_path: Path) -> str:
    readme = graph_path.parent / "README.md"
    if not readme.exists():
        return ""
    return readme.read_text(encoding="utf-8", errors="replace")


def mixed_extraction_warning(readme_text: str) -> str | None:
    lowered = readme_text.casefold()
    if "haiku" not in lowered and "mixed" not in lowered:
        return None
    chunks = "chunks 1, 4, 9, and 10"
    if "chunks 1, 4, 9, 10" in lowered:
        chunks = "chunks 1, 4, 9, and 10"
    return (
        "Use the 2026-04-30 graph for current architecture, but do not rely on "
        f"it alone for full AI-NNN topology because {chunks} were Haiku-extracted."
    )


def format_search(term: str, graph: LocalGraph, hits: list[SearchHit]) -> str:
    lines = [f'Graph: {display_path(graph.path, graph.repo_root)}', f'Search: "{term}"']
    if not hits:
        lines.append("No matching nodes found.")
        return "\n".join(lines)
    for index, hit in enumerate(hits, 1):
        lines.append(
            f"{index}. {hit.label} [{hit.node_id}] "
            f"(score {hit.score:.2f}, degree {hit.degree}, community {hit.community})"
        )
        if hit.source_file:
            lines.append(f"   source: {hit.source_file}")
    return "\n".join(lines)


def format_neighbors(result: dict[str, Any]) -> str:
    resolved = result["resolved"]
    lines = [
        f"Resolved: {resolved['label']} [{resolved['node_id']}] "
        f"(degree {resolved['degree']}, community {resolved['community']})"
    ]
    if resolved.get("source_file"):
        lines.append(f"source: {resolved['source_file']}")
    if not result["neighbors"]:
        lines.append("No adjacent nodes found.")
        return "\n".join(lines)
    for index, row in enumerate(result["neighbors"], 1):
        lines.append(
            f"{index}. {row['relation']} -> {row['label']} [{row['node_id']}] "
            f"(confidence {row['confidence']:.2f}, degree {row['degree']})"
        )
        source = row.get("source_file") or row.get("node_source_file")
        if source:
            lines.append(f"   source: {source}")
    return "\n".join(lines)


def format_impact(result: dict[str, Any]) -> str:
    lines = [
        f"Impact map: {result['query']}",
        f"Graph: {result['graph']}",
        f"Direct graph match: {'yes' if result['direct_match'] else 'no'}",
    ]
    for note in result.get("notes", []):
        lines.append(f"Note: {note}")

    lines.append("")
    lines.append("Matched nodes:")
    if result["matched_nodes"]:
        for hit in result["matched_nodes"][:8]:
            lines.append(
                f"- {hit['label']} [{hit['node_id']}] "
                f"(degree {hit['degree']}, community {hit['community']})"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Key hyperedges:")
    if result["key_hyperedges"]:
        for row in result["key_hyperedges"][:8]:
            lines.append(
                f"- {row['label']} ({row['node_count']} nodes, confidence {row['confidence']:.2f})"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Likely files:")
    if result["files"]:
        for group, files in result["files"].items():
            lines.append(f"{group}:")
            for path in files[:12]:
                lines.append(f"- {path}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Nearby nodes:")
    if result["neighbor_nodes"]:
        for row in result["neighbor_nodes"][:10]:
            lines.append(
                f"- {row['relation']} -> {row['label']} [{row['node_id']}] "
                f"(confidence {row['confidence']:.2f})"
            )
    else:
        lines.append("- none")
    return "\n".join(lines)


def format_drift(rows: list[dict[str, Any]], min_confidence: float) -> str:
    lines = [f"Drift candidates with confidence >= {min_confidence:.2f}"]
    if not rows:
        lines.append("No matching drift candidates found.")
        return "\n".join(lines)
    for index, row in enumerate(rows, 1):
        lines.append(
            f"{index}. {row['confidence']:.2f}: {row['source_label']} ~~ {row['target_label']}"
        )
        sources = [row.get("source_file"), row.get("target_file")]
        sources = [source for source in sources if source]
        if sources:
            lines.append(f"   sources: {' | '.join(sources)}")
        if row.get("expected_audit_report_pair"):
            lines.append("   note: expected timestamped audit-report duplicate")
    return "\n".join(lines)


def format_hubs(result: dict[str, Any]) -> str:
    lines = [f"Graph: {result['graph']}", "Top connected nodes:"]
    for index, row in enumerate(result["nodes"], 1):
        risk = " HIGH RISK IF CHANGED" if row["high_risk_if_changed"] else ""
        delta = ""
        if row["degree_delta"] is not None:
            delta = f", delta {row['degree_delta']:+d}"
        lines.append(
            f"{index}. {row['label']} [{row['node_id']}] "
            f"(degree {row['degree']}{delta}){risk}"
        )
    lines.append("")
    lines.append("Top hyperedges:")
    for index, row in enumerate(result["hyperedges"], 1):
        risk = " HIGH RISK IF CHANGED" if row["high_risk_if_changed"] else ""
        delta = ""
        if row["node_count_delta"] is not None:
            delta = f", delta {row['node_count_delta']:+d}"
        lines.append(
            f"{index}. {row['label']} ({row['node_count']} nodes{delta}, "
            f"confidence {row['confidence']:.2f}){risk}"
        )
    return "\n".join(lines)


def format_quality(summary: dict[str, Any]) -> str:
    lines = [
        f"Graph: {summary['graph']}",
        (
            f"Summary: {summary['nodes']} nodes, {summary['edges']} edges, "
            f"{summary['hyperedges']} hyperedges, {summary['communities']} communities"
        ),
        (
            f"Shape: {summary['orphans']} orphans, {summary['lonely']} lonely, "
            f"{summary['hubs_degree_20_plus']} hubs degree>=20, "
            f"{summary['density_edges_per_node']} edges/node"
        ),
        f"Confidence counts: {json.dumps(summary['confidence_counts'], sort_keys=True)}",
        f"AI-NNN coverage: {summary['ai_nnn_count']} ids",
    ]
    if "delta" in summary:
        lines.append(f"Previous graph: {summary['previous_graph']}")
        lines.append(f"Delta: {json.dumps(summary['delta'], sort_keys=True)}")
        lines.append(
            f"Previous AI-NNN coverage: {summary.get('previous_ai_nnn_count', 0)} ids"
        )
        missing = summary.get("ai_nnn_missing_from_current", [])
        if missing:
            preview = ", ".join(missing[:20])
            suffix = "" if len(missing) <= 20 else f" ... (+{len(missing) - 20} more)"
            lines.append(f"AI-NNN ids missing from current: {preview}{suffix}")
    if summary.get("mixed_extraction_warning"):
        lines.append(f"Warning: {summary['mixed_extraction_warning']}")
    return "\n".join(lines)


def add_common_flags(parser: argparse.ArgumentParser, suppress_defaults: bool = False) -> None:
    default: Any = argparse.SUPPRESS if suppress_defaults else None
    bool_default: Any = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument(
        "--graph",
        type=Path,
        default=default,
        help="Path to a graph.json snapshot.",
    )
    parser.add_argument(
        "--previous-graph",
        type=Path,
        default=default,
        help="Optional previous graph.json for quality and hub deltas.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=bool_default,
        help="Emit JSON output.",
    )


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    add_common_flags(common, suppress_defaults=True)

    parser = argparse.ArgumentParser(
        description="Query committed Graphify snapshots for development impact."
    )
    add_common_flags(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", parents=[common])
    search_parser.add_argument("term")
    search_parser.add_argument("--limit", type=int, default=10)

    neighbors_parser = subparsers.add_parser("neighbors", parents=[common])
    neighbors_parser.add_argument("term_or_node_id")
    neighbors_parser.add_argument("--limit", type=int, default=20)

    impact_parser = subparsers.add_parser("impact", parents=[common])
    impact_parser.add_argument("term")
    impact_parser.add_argument("--limit", type=int, default=20)

    drift_parser = subparsers.add_parser("drift", parents=[common])
    drift_parser.add_argument("--min-confidence", type=float, default=0.85)
    drift_parser.add_argument(
        "--include-expected-audit-reports",
        action="store_true",
        help="Include timestamped number-trust proof-report duplicate pairs.",
    )

    hubs_parser = subparsers.add_parser("hubs", parents=[common])
    hubs_parser.add_argument("--limit", type=int, default=15)

    subparsers.add_parser("quality", parents=[common])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    graph = load_graph(args.graph)
    previous = None
    if args.command in {"quality", "hubs"}:
        previous = load_previous_graph(graph.path, args.previous_graph)

    if args.command == "search":
        hits = graph.search(args.term, limit=args.limit)
        payload: Any = [hit_to_dict(hit) for hit in hits]
        text = format_search(args.term, graph, hits)
    elif args.command == "neighbors":
        payload = graph.neighbors(args.term_or_node_id, limit=args.limit)
        text = format_neighbors(payload)
    elif args.command == "impact":
        payload = graph.impact(args.term, limit=args.limit)
        text = format_impact(payload)
    elif args.command == "drift":
        payload = graph.drift_candidates(
            min_confidence=args.min_confidence,
            include_expected_audit_reports=args.include_expected_audit_reports,
        )
        text = format_drift(payload, args.min_confidence)
    elif args.command == "hubs":
        payload = graph.hubs(limit=args.limit, previous=previous)
        text = format_hubs(payload)
    elif args.command == "quality":
        payload = graph.quality(previous=previous)
        text = format_quality(payload)
    else:
        parser.error(f"unknown command {args.command}")
        return 2

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GraphQueryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
