from __future__ import annotations

import json
from pathlib import Path

from tools.graphify import development_report
from tools.graphify import query_local


def write_graph(path: Path, nodes: list[dict], links: list[dict], hyperedges: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "directed": True,
                "multigraph": False,
                "graph": {},
                "nodes": nodes,
                "links": links,
                "hyperedges": hyperedges,
            }
        ),
        encoding="utf-8",
    )


def fixture_graphs(tmp_path: Path) -> tuple[Path, Path]:
    previous = tmp_path / "docs" / "audits" / "graphify-2026-04-29" / "graph.json"
    current = tmp_path / "docs" / "audits" / "graphify-2026-04-30" / "graph.json"

    write_graph(
        previous,
        nodes=[
            {
                "id": "old_mypay",
                "label": "myPay parser prompt",
                "source_file": str(tmp_path / "docs" / "prompts" / "P2-T04-mypay.md"),
                "community": 1,
            },
            {"id": "ai_001", "label": "AI-001 current item", "source_file": "docs/data-lineage/ACTION_ITEMS.md", "community": 2},
            {"id": "ai_002", "label": "AI-002 old item", "source_file": "docs/data-lineage/ACTION_ITEMS.md", "community": 2},
            {"id": "ai_003", "label": "AI-003 old item", "source_file": "docs/data-lineage/ACTION_ITEMS.md", "community": 2},
        ],
        links=[
            {
                "source": "old_mypay",
                "target": "ai_001",
                "relation": "mentions",
                "confidence": "EXTRACTED",
                "confidence_score": 0.9,
                "source_file": "docs/ROADMAP.md",
            }
        ],
        hyperedges=[
            {
                "id": "phase_2_document",
                "label": "Phase 2 Document Ingestion",
                "nodes": ["old_mypay"],
                "confidence": "INFERRED",
                "confidence_score": 0.85,
                "source_file": "docs/ROADMAP.md",
            }
        ],
    )
    (previous.parent / "README.md").write_text("# Graphify Audit 2026-04-29\n", encoding="utf-8")

    write_graph(
        current,
        nodes=[
            {
                "id": "p2_t04_mypay_parser",
                "label": "P2-T04 myPay Parser",
                "source_file": str(tmp_path / "docs" / "prompts" / "P2-T04-mypay.md"),
                "community": 1,
            },
            {
                "id": "connector_mypay",
                "label": "myPay browser connector",
                "source_file": str(tmp_path / "extractors" / "mypay_connector.py"),
                "community": 1,
            },
            {
                "id": "refresh_orchestrator",
                "label": "refresh_orchestrator",
                "source_file": str(tmp_path / "backend" / "refresh_orchestrator.py"),
                "community": 1,
            },
            {
                "id": "p17_t17_proof_gate",
                "label": "number trust proof gate",
                "source_file": str(tmp_path / "docs" / "ROADMAP.md"),
                "community": 2,
            },
            {
                "id": "scripts_run_number_trust_proof",
                "label": "run_number_trust_proof.py",
                "source_file": str(tmp_path / "scripts" / "run_number_trust_proof.py"),
                "community": 2,
            },
            {
                "id": "owner_scoping_flow",
                "label": "Owner Scoping Data Flow",
                "source_file": str(tmp_path / "docs" / "ARCHITECTURE.md"),
                "community": 3,
            },
            {
                "id": "build_account_filter_helper",
                "label": "build_account_filter()",
                "source_file": str(tmp_path / "dal" / "owners.py"),
                "community": 3,
            },
            {
                "id": "budget_invariant_one",
                "label": "Invariant bud_001 Household-Only Budgets",
                "source_file": str(tmp_path / "docs" / "data-lineage" / "ACTION_ITEMS.md"),
                "community": 4,
            },
            {
                "id": "budget_invariant_two",
                "label": "Invariant xc_006 Budgets No owner_id Writes Blocked",
                "source_file": str(tmp_path / "docs" / "data-lineage" / "ACTION_ITEMS.md"),
                "community": 4,
            },
            {
                "id": "report_one",
                "label": "Number Trust Audit Report 20260429-234650",
                "source_file": str(tmp_path / "docs" / "audits" / "number-trust" / "reports" / "number-trust-20260429-234650.md"),
                "community": 5,
            },
            {
                "id": "report_two",
                "label": "Number Trust DOM Audit Report 20260429-234814",
                "source_file": str(tmp_path / "docs" / "audits" / "number-trust" / "reports" / "number-trust-dom-20260429-234814.md"),
                "community": 5,
            },
            {"id": "ai_001", "label": "AI-001 current item", "source_file": "docs/data-lineage/ACTION_ITEMS.md", "community": 2},
        ],
        links=[
            {
                "source": "p2_t04_mypay_parser",
                "target": "connector_mypay",
                "relation": "documents",
                "confidence": "EXTRACTED",
                "confidence_score": 0.92,
                "source_file": "docs/ROADMAP.md",
            },
            {
                "source": "connector_mypay",
                "target": "refresh_orchestrator",
                "relation": "integrates_with",
                "confidence": "INFERRED",
                "confidence_score": 0.88,
                "source_file": "docs/ARCHITECTURE.md",
            },
            {
                "source": "p17_t17_proof_gate",
                "target": "scripts_run_number_trust_proof",
                "relation": "implemented_by",
                "confidence": "EXTRACTED",
                "confidence_score": 0.95,
                "source_file": "docs/audits/number-trust/implementation-decisions.md",
            },
            {
                "source": "owner_scoping_flow",
                "target": "build_account_filter_helper",
                "relation": "depends_on",
                "confidence": "EXTRACTED",
                "confidence_score": 0.97,
                "source_file": "docs/ARCHITECTURE.md",
            },
            {
                "source": "budget_invariant_one",
                "target": "budget_invariant_two",
                "relation": "semantically_similar_to",
                "confidence": "INFERRED",
                "confidence_score": 0.95,
                "source_file": "docs/data-lineage/ACTION_ITEMS.md",
            },
            {
                "source": "report_one",
                "target": "report_two",
                "relation": "semantically_similar_to",
                "confidence": "INFERRED",
                "confidence_score": 0.99,
                "source_file": "docs/audits/number-trust/reports",
            },
        ],
        hyperedges=[
            {
                "id": "phase_2_document",
                "label": "Phase 2 Document Ingestion & Parsing",
                "nodes": ["p2_t04_mypay_parser", "connector_mypay"],
                "confidence": "INFERRED",
                "confidence_score": 0.85,
                "source_file": "docs/ROADMAP.md",
            },
            {
                "id": "proof_gate",
                "label": "Number Trust Proof Pipeline: API Audit + DOM Audit + Proof Gate",
                "nodes": ["p17_t17_proof_gate", "scripts_run_number_trust_proof"],
                "confidence": "EXTRACTED",
                "confidence_score": 1.0,
                "source_file": "docs/audits/number-trust/implementation-decisions.md",
            },
            {
                "id": "owner_scope",
                "label": "Owner Scoping Data Flow",
                "nodes": ["owner_scoping_flow", "build_account_filter_helper"],
                "confidence": "EXTRACTED",
                "confidence_score": 0.9,
                "source_file": "docs/ARCHITECTURE.md",
            },
        ],
    )
    (current.parent / "README.md").write_text(
        "Updated graphify run against `main` @ `2c4ab3b`.\n"
        "Mixed extraction used Haiku-extracted chunks 1, 4, 9, 10.\n",
        encoding="utf-8",
    )
    return previous, current


def test_latest_graph_discovery(tmp_path: Path) -> None:
    previous, current = fixture_graphs(tmp_path)

    assert query_local.discover_latest_graph(tmp_path) == current
    assert query_local.discover_previous_graph(current, tmp_path) == previous


def test_search_ranking_prefers_exact_phrase(tmp_path: Path) -> None:
    _, current = fixture_graphs(tmp_path)
    graph = query_local.LocalGraph(current, repo_root=tmp_path)

    hits = graph.search("myPay browser connector")

    assert hits[0].node_id == "connector_mypay"
    assert hits[0].degree == 2


def test_neighbor_traversal_resolves_search_term(tmp_path: Path) -> None:
    _, current = fixture_graphs(tmp_path)
    graph = query_local.LocalGraph(current, repo_root=tmp_path)

    result = graph.neighbors("myPay browser connector")

    neighbor_ids = {row["node_id"] for row in result["neighbors"]}
    assert "p2_t04_mypay_parser" in neighbor_ids
    assert "refresh_orchestrator" in neighbor_ids


def test_drift_filter_excludes_timestamped_number_trust_reports(tmp_path: Path) -> None:
    _, current = fixture_graphs(tmp_path)
    graph = query_local.LocalGraph(current, repo_root=tmp_path)

    filtered = graph.drift_candidates(min_confidence=0.85)
    all_rows = graph.drift_candidates(
        min_confidence=0.85, include_expected_audit_reports=True
    )

    assert [(row["source_id"], row["target_id"]) for row in filtered] == [
        ("budget_invariant_one", "budget_invariant_two")
    ]
    assert any(row["expected_audit_report_pair"] for row in all_rows)


def test_quality_summary_includes_delta_and_mixed_extraction_warning(tmp_path: Path) -> None:
    previous, current = fixture_graphs(tmp_path)
    graph = query_local.LocalGraph(current, repo_root=tmp_path)
    previous_graph = query_local.LocalGraph(previous, repo_root=tmp_path)

    summary = graph.quality(previous=previous_graph)

    assert summary["nodes"] == 12
    assert summary["delta"]["nodes"] == 8
    assert summary["ai_nnn_count"] == 1
    assert summary["previous_ai_nnn_count"] == 3
    assert "AI-002" in summary["ai_nnn_missing_from_current"]
    assert "Haiku-extracted" in summary["mixed_extraction_warning"]


def test_development_report_generation(tmp_path: Path) -> None:
    previous, current = fixture_graphs(tmp_path)
    output = tmp_path / "report.md"

    report_text = development_report.build_development_report(
        graph_path=current,
        previous_graph_path=previous,
        repo_root=tmp_path,
    )
    written = development_report.write_report(
        graph_path=current,
        previous_graph_path=previous,
        output_path=output,
        repo_root=tmp_path,
    )

    assert "# Graphify Development Use Report" in report_text
    assert "myPay browser connector" in report_text
    assert "destructive data-wipe tooling" in report_text
    assert "timestamped number-trust proof-report duplicates" in report_text
    assert "Haiku-extracted" in report_text
    assert written == output
    assert output.read_text(encoding="utf-8").startswith("# Graphify Development Use Report")
