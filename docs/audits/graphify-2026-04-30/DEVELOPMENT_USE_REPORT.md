# Graphify Development Use Report

This report turns the committed Graphify snapshot into a practical task-planning aid. It is a read-only interpretation layer over the graph artifact, not a graph refresh.

## Graph Summary

- Graph: `docs/audits/graphify-2026-04-30/graph.json`
- Shape: 4,590 nodes, 9,208 edges, 40 hyperedges, 179 communities
- Navigation risk: 69 hubs with degree >= 20, 62 orphans, 1,656 one-edge nodes
- AI-NNN coverage surfaced in this graph: 13 ids
- Refreshed graph artifact commit: `a7390be`
- README records corpus run against `main` @ `2c4ab3b`
- Previous graph: `docs/audits/graphify-2026-04-29/graph.json`
- Delta vs previous: -558 nodes, +1 edges, +7 hyperedges, -76 communities

## Quality Notes

- Warning: Use the 2026-04-30 graph for current architecture, but do not rely on it alone for full AI-NNN topology because chunks 1, 4, 9, and 10 were Haiku-extracted.
- AI-NNN ids present in the previous graph but not surfaced here: AI-003, AI-007, AI-009, AI-010, AI-012, AI-013, AI-014, AI-015, AI-016, AI-017, AI-018, AI-024, AI-025, AI-026, AI-027, AI-028, AI-030, AI-035, AI-036, AI-038, AI-039, AI-040
- Use graph results as routing hints. Live code and tests remain the source of executable truth.

## Impact Maps

### myPay browser connector

- Direct graph match: yes
- Matched nodes:
  - `MyPayRASParser` [mypay_ras_mypayrasparser] degree 23, community 3
  - `test_t04_mypay.py` [c_users_chang_onedrive_desktop_projects_personal_finance_project_tests_test_t04_mypay_py] degree 17, community 3
  - `mypay_ras.py` [c_users_chang_onedrive_desktop_projects_personal_finance_project_dal_parsers_mypay_ras_py] degree 5, community 3
  - `P2-T04: myPay RAS Parser` [p2_t04_mypay_parser] degree 4, community 38
  - `dal/parsers/mypay_ras.py — DFAS Retiree Account Statement (RAS) parser.  Recog` [mypay_ras_rationale_1] degree 3, community 3
- Key hyperedges:
  - `Phase 2 Document Ingestion & Parsing` (4 nodes, confidence 0.85)
- Likely files:
  - dal: `dal/document_drop.py`, `dal/parsers/base.py`, `dal/parsers/mypay_ras.py`
  - tests: `tests/test_t04_mypay.py`
  - docs: `docs/prompts/Phase-2/P2-T01_tsp-connector.md`, `docs/prompts/Phase-2/P2-T02_document-drop-backend.md`, `docs/prompts/Phase-2/P2-T03_document-drop-frontend.md`, `docs/prompts/Phase-2/P2-T04_mypay-parser.md`
  - lineage: `docs/data-lineage/lineage/document_upload_commit.yaml`, `docs/data-lineage/lineage/payroll_snapshot.yaml`
- Nearby nodes:
  - `contains` -> `MyPayRASParser` [mypay_ras_mypayrasparser] confidence 1.00
  - `rationale_for` -> `test_t04_mypay.py` [c_users_chang_onedrive_desktop_projects_personal_finance_project_tests_test_t04_mypay_py] confidence 1.00
  - `references` -> `document_upload_commit` [document_upload_commit_event] confidence 1.00
  - `inherits` -> `DocumentParser` [documentparser] confidence 1.00
  - `references` -> `Payroll Snapshot Event` [payroll_snapshot_event] confidence 1.00

### destructive data-wipe tooling

- Direct graph match: no
- Note: No direct node matched the full phrase; results use significant-token fallback.
- Note: Low-signal token matches were ignored so generic graph nodes do not mask a coverage gap.
- Note: No useful seed nodes found in this graph snapshot.
- Matched nodes:
  - none
- Key hyperedges:
  - none
- Likely files:
  - none
- Nearby nodes:
  - none
- Previous snapshot fallback:
  - Graph: `docs/audits/graphify-2026-04-29/graph.json`
  - `P17 Destructive Data-Wipe Tooling` [p17_wipe_tooling] degree 2, community 24

### number trust proof gate

- Direct graph match: yes
- Matched nodes:
  - `Number Trust Proof Gate Report (2026-04-30 00:07:04) â€” PASS` [proof_gate_report_000704] degree 4, community 4
  - `test_number_trust_proof_gate.py` [c_users_chang_onedrive_desktop_projects_personal_finance_project_tests_test_number_trust_proof_gate_py] degree 6, community 5
  - `test_validate_runtime_identity_accepts_matching_trusted_context()` [test_number_trust_proof_gate_test_validate_runtime_identity_accepts_matching_trusted_context] degree 5, community 5
  - `test_final_report_records_passed_gates()` [test_number_trust_proof_gate_test_final_report_records_passed_gates] degree 4, community 5
  - `P17-T17: One-Command Number-Trust Proof Gate` [p17_t17_proof_gate] degree 3, community 36
- Key hyperedges:
  - `Number Trust Proof Pipeline: API Audit + DOM Audit + Proof Gate` (3 nodes, confidence 1.00)
  - `Phase 17 Number Trust Verification Stack` (3 nodes, confidence 0.80)
  - `Number Trust Proof Pipeline: Oracle â†’ API â†’ DOM` (5 nodes, confidence 0.95)
  - `Sign Convention Enforcement Ecosystem` (5 nodes, confidence 0.95)
- Likely files:
  - scripts_tools: `scripts/run_number_trust_proof.py`
  - tests: `tests/test_number_trust_proof_gate.py`
  - docs: `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/audits/files/audit-report.md`, `docs/audits/number-trust/adversarial-review/round-4-adversary-second-pass.md`, `docs/audits/number-trust/adversarial-review/shared-evidence.md`, `docs/audits/number-trust/implementation-decisions.md`, ... (+10 more)
  - other: `AGENTS.md`
- Nearby nodes:
  - `references` -> `DB Fingerprint: f061229325d607ffd06e8ea22dee2831a2db18bd91f140c16c88982548c8b9ec` [db_fingerprint_canonical] confidence 1.00
  - `contains` -> `test_number_trust_proof_gate.py` [c_users_chang_onedrive_desktop_projects_personal_finance_project_tests_test_number_trust_proof_gate_py] confidence 1.00
  - `calls` -> `_runtime_context()` [test_number_trust_proof_gate_runtime_context] confidence 1.00
  - `calls` -> `test_validate_runtime_identity_accepts_matching_trusted_context()` [test_number_trust_proof_gate_test_validate_runtime_identity_accepts_matching_trusted_context] confidence 1.00
  - `calls` -> `test_validate_runtime_identity_reports_path_and_fingerprint_drift()` [test_number_trust_proof_gate_test_validate_runtime_identity_reports_path_and_fingerprint_drift] confidence 1.00

### owner scoping

- Direct graph match: yes
- Matched nodes:
  - `Owner Scoping First-Class Path` [owner_scoping_first_class] degree 2, community 14
  - `dal.owners module (owner scoping)` [dal_owners] degree 24, community 4
  - `Per-owner scoping must agree across both pages.` [test_cashflow_reports_parity_rationale_206] degree 1, community 8
  - `Return the most recent valuation for a vehicle.      Owner scoping is applied` [vehicles_rationale_24] degree 1, community 15
  - `test_owner_scoping.py` [c_users_chang_onedrive_desktop_projects_personal_finance_project_tests_test_owner_scoping_py] degree 21, community 2
- Key hyperedges:
  - `Owner Scoping Data Flow` (5 nodes, confidence 0.90)
  - `Owner-scoping bug fix triad: falsy-list bug â†’ build_account_filter â†’ dal_owners_py` (3 nodes, confidence 0.95)
  - `Phase 7 Multi-User Feature Stack (settings â†’ owner scoping â†’ UI)` (3 nodes, confidence 0.90)
- Likely files:
  - backend: `backend/routers/accounts.py`
  - dal: `dal/accountability_drift.py`, `dal/connection.py`, `dal/flow_aggregation.py`, `dal/investments.py`, `dal/migrations/__init__.py`, `dal/parsers/tsp_statement.py`, ... (+10 more)
  - tests: `tests/test_accountability.py`, `tests/test_cashflow_invariants.py`, `tests/test_cashflow_reports_parity.py`, `tests/test_dal.py`, `tests/test_dividend_interest_flows.py`, `tests/test_income_sources_registry.py`, ... (+3 more)
  - docs: `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/audits/files/_run_reports_audit.py`, `docs/prompts/Phase-6/P6-T02_yearly-wrapup-preliminary.md`, `docs/prompts/Phase-7/P7-T01_settings-page.md`, `docs/prompts/Phase-7/P7-T02_owner-scoped-audit.md`, ... (+4 more)
  - lineage: `docs/data-lineage/lineage/payroll_snapshot.yaml`, `docs/data-lineage/lineage/staleness_evaluation.yaml`
  - other: `CLAUDE.md`
- Nearby nodes:
  - `imports_from` -> `test_cashflow_invariants.py` [c_users_chang_onedrive_desktop_projects_personal_finance_project_tests_test_cashflow_invariants_py] confidence 1.00
  - `imports_from` -> `test_dal.py` [c_users_chang_onedrive_desktop_projects_personal_finance_project_tests_test_dal_py] confidence 1.00
  - `imports_from` -> `dal.owners module (owner scoping)` [dal_owners] confidence 1.00
  - `rationale_for` -> `test_owner_scoping.py` [c_users_chang_onedrive_desktop_projects_personal_finance_project_tests_test_owner_scoping_py] confidence 1.00
  - `contains` -> `test_empty_owner_no_leak()` [test_owner_scoping_test_empty_owner_no_leak] confidence 1.00


## Drift Candidates

High-confidence `semantically_similar_to` edges after filtering timestamped number-trust proof-report duplicates:

- 0.95: `Invariant bud_001: Household-Only Budgets (Migration v23)` ~~ `Invariant xc_006: Budgets No owner_id Writes Blocked`
  Sources: `docs/audits/files/results-accounts_budgets.json` | `docs/audits/files/results-cross_cutting.json`
- 0.92: `Oracle Vocabulary JSON (Neutral Category Semantics)` ~~ `dal/category_classifications.py (single source of truth)`
  Sources: `docs/audits/number-trust/oracle-vocabulary.json` | `docs/audits/number-trust/adversarial-review/round-4-adversary-second-pass.md`
- 0.90: `Invariant xc_011: Signed Amount Direction Table Invariant` ~~ `Invariant txns_001: Signed Amount Direction Law`
  Sources: `docs/audits/files/results-cross_cutting.json` | `docs/audits/files/results-txns_docs.json`
- 0.88: `Invariant bud_002: Budget Actual Uses Canonical Spending` ~~ `Invariant cf_004: Monthly Canonical Pattern`
  Sources: `docs/audits/files/results-accounts_budgets.json` | `docs/audits/files/results-cashflow.json`
- 0.88: `Invariant dash_001: Net Worth KPI Matches History` ~~ `Invariant acct_002: Account Groups Sum to Net Worth`
  Sources: `docs/audits/files/results-dashboard.json` | `docs/audits/files/results-accounts_budgets.json`
- 0.88: `Invariant dash_003: Savings Rate Formula` ~~ `Invariant cf_007: Savings Rate Per Period`
  Sources: `docs/audits/files/results-dashboard.json` | `docs/audits/files/results-cashflow.json`
- 0.85: `Checker Canonical Pattern Guidance` ~~ `Oracle Vocab: all_excl_from_spend`
  Sources: `docs/audits/files/subagent-checker-prompt.md` | `docs/audits/number-trust/oracle-vocabulary.json`
- 0.85: `user_manual_valuation lineage event` ~~ `vehicle_valuation lineage event`
  Sources: `docs/data-lineage/lineage/user_manual_valuation.yaml` | `docs/data-lineage/lineage/vehicle_valuation.yaml`

## High-Risk Hubs

- `get_db()` [connection_get_db]: degree 414 (high risk if changed)
- `.commit()` [tsp_statement_tspstatementparser_commit]: degree 368 (high risk if changed)
- `init_db()` [init_init_db]: degree 141 (high risk if changed)
- `str` [str]: degree 114 (high risk if changed)
- `ParseResult` [base_parseresult]: degree 100 (high risk if changed)
- `DocumentParser` [base_documentparser]: degree 78 (high risk if changed)
- `audit_number_trust.py` [c_users_chang_onedrive_desktop_projects_personal_finance_project_scripts_audit_number_trust_py]: degree 56 (high risk if changed)
- `TSPStatementParser` [tsp_statement_tspstatementparser]: degree 48 (high risk if changed)

## Suggested Autonomous Uses

- Start task planning with `impact` to find related files, docs, tests, and lineage before editing.
- Check `hubs` before touching shared functions; degree-heavy nodes deserve broader tests and more careful review.
- Use `drift` to find duplicate invariants or source-of-truth pairs that should be reconciled or documented.
- Use `quality` after future graph refreshes to see whether extraction quality or AI-NNN coverage changed.

## Commands

```powershell
python tools\graphify\query_local.py search "myPay"
python tools\graphify\query_local.py impact "destructive data-wipe tooling"
python tools\graphify\query_local.py drift --min-confidence 0.85
python tools\graphify\query_local.py quality
python tools\graphify\development_report.py
```

## Raw Quality Summary

```text
Graph: docs/audits/graphify-2026-04-30/graph.json
Summary: 4590 nodes, 9208 edges, 40 hyperedges, 179 communities
Shape: 62 orphans, 1656 lonely, 69 hubs degree>=20, 2.006 edges/node
Confidence counts: {"EXTRACTED": 6074, "INFERRED": 3134}
AI-NNN coverage: 13 ids
Previous graph: docs/audits/graphify-2026-04-29/graph.json
Delta: {"ai_nnn_count": -22, "communities": -76, "edges": 1, "hyperedges": 7, "nodes": -558}
Previous AI-NNN coverage: 35 ids
AI-NNN ids missing from current: AI-003, AI-007, AI-009, AI-010, AI-012, AI-013, AI-014, AI-015, AI-016, AI-017, AI-018, AI-024, AI-025, AI-026, AI-027, AI-028, AI-030, AI-035, AI-036, AI-038 ... (+2 more)
Warning: Use the 2026-04-30 graph for current architecture, but do not rely on it alone for full AI-NNN topology because chunks 1, 4, 9, and 10 were Haiku-extracted.
```
