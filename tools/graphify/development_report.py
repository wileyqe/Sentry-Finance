"""Generate a development-facing report from the latest Graphify snapshot."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

try:
    from .query_local import (
        PROJECT_ROOT,
        LocalGraph,
        display_path,
        format_quality,
        load_graph,
        load_previous_graph,
        read_sibling_readme,
    )
except ImportError:  # pragma: no cover - exercised when run as a script path
    from query_local import (  # type: ignore
        PROJECT_ROOT,
        LocalGraph,
        display_path,
        format_quality,
        load_graph,
        load_previous_graph,
        read_sibling_readme,
    )


IMPACT_TERMS = [
    "myPay browser connector",
    "destructive data-wipe tooling",
    "number trust proof gate",
    "owner scoping",
]


def git_last_commit_for_path(repo_root: Path, path: Path) -> str | None:
    try:
        relative_path = path.relative_to(repo_root)
    except ValueError:
        relative_path = path
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h", "--", str(relative_path)],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def readme_run_commit(readme_text: str) -> str | None:
    match = re.search(r"against `main` @ `([0-9a-f]+)`", readme_text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def build_report_payload(
    graph: LocalGraph,
    previous: LocalGraph | None,
    repo_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    quality = graph.quality(previous=previous)
    impacts = {term: graph.impact(term, limit=14) for term in IMPACT_TERMS}
    previous_impacts = {}
    if previous:
        for term, impact in impacts.items():
            if impact["matched_nodes"]:
                continue
            previous_impact = previous.impact(term, limit=8)
            if previous_impact["matched_nodes"] or previous_impact["key_hyperedges"]:
                previous_impacts[term] = previous_impact
    drift = graph.drift_candidates(min_confidence=0.85)[:20]
    hubs = graph.hubs(limit=10, previous=previous)
    readme_text = read_sibling_readme(graph.path)
    return {
        "graph": display_path(graph.path, repo_root),
        "graph_artifact_commit": git_last_commit_for_path(repo_root, graph.path),
        "readme_run_commit": readme_run_commit(readme_text),
        "quality": quality,
        "impacts": impacts,
        "previous_impacts": previous_impacts,
        "drift": drift,
        "hubs": hubs,
    }


def build_development_report(
    graph_path: Path | None = None,
    previous_graph_path: Path | None = None,
    repo_root: Path = PROJECT_ROOT,
) -> str:
    graph = load_graph(graph_path, repo_root=repo_root)
    previous = load_previous_graph(
        graph.path, previous_graph_path, repo_root=repo_root
    )
    payload = build_report_payload(graph, previous, repo_root=repo_root)
    return render_report(payload)


def render_report(payload: dict[str, Any]) -> str:
    quality = payload["quality"]
    warning = quality.get("mixed_extraction_warning") or (
        "Use the 2026-04-30 graph for current architecture, but do not rely on "
        "it alone for full AI-NNN topology because chunks 1, 4, 9, and 10 were "
        "Haiku-extracted."
    )
    lines = [
        "# Graphify Development Use Report",
        "",
        "This report turns the committed Graphify snapshot into a practical task-planning aid. It is a read-only interpretation layer over the graph artifact, not a graph refresh.",
        "",
        "## Graph Summary",
        "",
        f"- Graph: `{payload['graph']}`",
        (
            f"- Shape: {quality['nodes']:,} nodes, {quality['edges']:,} edges, "
            f"{quality['hyperedges']:,} hyperedges, {quality['communities']:,} communities"
        ),
        (
            f"- Navigation risk: {quality['hubs_degree_20_plus']:,} hubs with degree >= 20, "
            f"{quality['orphans']:,} orphans, {quality['lonely']:,} one-edge nodes"
        ),
        f"- AI-NNN coverage surfaced in this graph: {quality['ai_nnn_count']} ids",
    ]
    if payload.get("graph_artifact_commit"):
        lines.append(f"- Refreshed graph artifact commit: `{payload['graph_artifact_commit']}`")
    if payload.get("readme_run_commit"):
        lines.append(f"- README records corpus run against `main` @ `{payload['readme_run_commit']}`")
    if quality.get("delta"):
        lines.extend(
            [
                f"- Previous graph: `{quality['previous_graph']}`",
                (
                    "- Delta vs previous: "
                    f"{quality['delta']['nodes']:+,} nodes, "
                    f"{quality['delta']['edges']:+,} edges, "
                    f"{quality['delta']['hyperedges']:+,} hyperedges, "
                    f"{quality['delta']['communities']:+,} communities"
                ),
            ]
        )
    lines.extend(["", "## Quality Notes", "", f"- Warning: {warning}"])
    if quality.get("ai_nnn_missing_from_current"):
        missing = ", ".join(quality["ai_nnn_missing_from_current"][:24])
        suffix = (
            ""
            if len(quality["ai_nnn_missing_from_current"]) <= 24
            else f" ... (+{len(quality['ai_nnn_missing_from_current']) - 24} more)"
        )
        lines.append(f"- AI-NNN ids present in the previous graph but not surfaced here: {missing}{suffix}")
    lines.append("- Use graph results as routing hints. Live code and tests remain the source of executable truth.")

    lines.extend(["", "## Impact Maps", ""])
    for term, impact in payload["impacts"].items():
        append_impact_section(
            lines,
            term,
            impact,
            previous_impact=payload.get("previous_impacts", {}).get(term),
        )

    lines.extend(["", "## Drift Candidates", ""])
    if payload["drift"]:
        lines.append(
            "High-confidence `semantically_similar_to` edges after filtering timestamped number-trust proof-report duplicates:"
        )
        lines.append("")
        for row in payload["drift"][:12]:
            lines.append(
                f"- {row['confidence']:.2f}: `{row['source_label']}` ~~ `{row['target_label']}`"
            )
            sources = [row.get("source_file"), row.get("target_file")]
            sources = [source for source in sources if source]
            if sources:
                lines.append(f"  Sources: {' | '.join(f'`{source}`' for source in sources)}")
    else:
        lines.append("No high-confidence drift candidates survived filtering.")

    lines.extend(["", "## High-Risk Hubs", ""])
    for row in payload["hubs"]["nodes"][:8]:
        lines.append(
            f"- `{row['label']}` [{row['node_id']}]: degree {row['degree']} "
            "(high risk if changed)"
        )

    lines.extend(
        [
            "",
            "## Suggested Autonomous Uses",
            "",
            "- Start task planning with `impact` to find related files, docs, tests, and lineage before editing.",
            "- Check `hubs` before touching shared functions; degree-heavy nodes deserve broader tests and more careful review.",
            "- Use `drift` to find duplicate invariants or source-of-truth pairs that should be reconciled or documented.",
            "- Use `quality` after future graph refreshes to see whether extraction quality or AI-NNN coverage changed.",
            "",
            "## Commands",
            "",
            "```powershell",
            'python tools\\graphify\\query_local.py search "myPay"',
            'python tools\\graphify\\query_local.py impact "destructive data-wipe tooling"',
            "python tools\\graphify\\query_local.py drift --min-confidence 0.85",
            "python tools\\graphify\\query_local.py quality",
            "python tools\\graphify\\development_report.py",
            "```",
            "",
            "## Raw Quality Summary",
            "",
            "```text",
            format_quality(quality),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def append_impact_section(
    lines: list[str],
    term: str,
    impact: dict[str, Any],
    previous_impact: dict[str, Any] | None = None,
) -> None:
    lines.extend(
        [
            f"### {term}",
            "",
            f"- Direct graph match: {'yes' if impact['direct_match'] else 'no'}",
        ]
    )
    for note in impact.get("notes", []):
        lines.append(f"- Note: {note}")

    lines.append("- Matched nodes:")
    if impact["matched_nodes"]:
        for hit in impact["matched_nodes"][:5]:
            lines.append(
                f"  - `{hit['label']}` [{hit['node_id']}] degree {hit['degree']}, community {hit['community']}"
            )
    else:
        lines.append("  - none")

    lines.append("- Key hyperedges:")
    if impact["key_hyperedges"]:
        for row in impact["key_hyperedges"][:4]:
            lines.append(
                f"  - `{row['label']}` ({row['node_count']} nodes, confidence {row['confidence']:.2f})"
            )
    else:
        lines.append("  - none")

    lines.append("- Likely files:")
    if impact["files"]:
        for group, files in impact["files"].items():
            preview = ", ".join(f"`{path}`" for path in files[:6])
            suffix = "" if len(files) <= 6 else f", ... (+{len(files) - 6} more)"
            lines.append(f"  - {group}: {preview}{suffix}")
    else:
        lines.append("  - none")

    lines.append("- Nearby nodes:")
    if impact["neighbor_nodes"]:
        for row in impact["neighbor_nodes"][:5]:
            lines.append(
                f"  - `{row['relation']}` -> `{row['label']}` [{row['node_id']}] confidence {row['confidence']:.2f}"
            )
    else:
        lines.append("  - none")

    if previous_impact:
        lines.append("- Previous snapshot fallback:")
        lines.append(f"  - Graph: `{previous_impact['graph']}`")
        if previous_impact["matched_nodes"]:
            for hit in previous_impact["matched_nodes"][:4]:
                lines.append(
                    f"  - `{hit['label']}` [{hit['node_id']}] degree {hit['degree']}, community {hit['community']}"
                )
        if previous_impact["key_hyperedges"]:
            for row in previous_impact["key_hyperedges"][:2]:
                lines.append(
                    f"  - Hyperedge: `{row['label']}` ({row['node_count']} nodes, confidence {row['confidence']:.2f})"
                )
    lines.append("")


def write_report(
    graph_path: Path | None = None,
    previous_graph_path: Path | None = None,
    output_path: Path | None = None,
    repo_root: Path = PROJECT_ROOT,
) -> Path:
    graph = load_graph(graph_path, repo_root=repo_root)
    report = build_development_report(
        graph_path=graph.path,
        previous_graph_path=previous_graph_path,
        repo_root=repo_root,
    )
    output = output_path or graph.path.parent / "DEVELOPMENT_USE_REPORT.md"
    output.write_text(report, encoding="utf-8")
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a development-use report from the latest Graphify snapshot."
    )
    parser.add_argument("--graph", type=Path, help="Path to a graph.json snapshot.")
    parser.add_argument(
        "--previous-graph",
        type=Path,
        help="Optional previous graph.json for quality deltas.",
    )
    parser.add_argument("--output", type=Path, help="Report output path.")
    parser.add_argument("--json", action="store_true", help="Print report metadata as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = write_report(
        graph_path=args.graph,
        previous_graph_path=args.previous_graph,
        output_path=args.output,
    )
    if args.json:
        print(json.dumps({"output": str(output)}, indent=2, sort_keys=True))
    else:
        print(f"Wrote {display_path(output, PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
