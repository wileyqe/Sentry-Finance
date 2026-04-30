# Graphify Audit — 2026-04-29

A one-shot static-analysis snapshot of the entire repo (code + docs + lineage YAMLs) using [graphify](https://github.com/safishamsi/graphify). Captured at commit `247eafc` (`main`).

## What's in this folder

- **`GRAPH_REPORT.md`** — full text report (105 KB). Communities, god nodes, surprising connections, hyperedges, suggested questions.
- **`graph.html`** — interactive vis.js visualization (5.1 MB). Open in any browser; click nodes, search, filter by community.
- **`graph.json`** — persistent graph data (7.3 MB). Queryable later via `graphify query "..."`, `graphify path "A" "B"`, `graphify explain "X"`.

The orchestration scripts that produced this snapshot live in [`tools/graphify/`](../../../tools/graphify/).

## Corpus

- **563 files**: 327 code (backend, frontend/src, dal, extractors, scripts, tests) + 236 docs/YAML/JSON (docs/, top-level *.md)
- **5,148 nodes · 9,207 edges · 255 communities · 33 hyperedges**
- Edge confidence: 66% EXTRACTED · 34% INFERRED · <0.1% AMBIGUOUS
- 1 file auto-skipped as sensitive: `backend/credential_broker.py`

## Architectural truths the graph confirms

- **Owner-scoping is wired DAL → API → Frontend.** Hyperedge: `dal_owners_build_account_filter`, `owner_chip_switcher`, `frontend_use_owner_api` [EXTRACTED 1.00]. The falsy-list regression CLAUDE.md warns about has its own hyperedge documenting the fix path.
- **Sign convention enforcement is wall-to-wall.** Hyperedge connects the canonical pattern + `dal_transactions_upsert` + `test_cashflow_invariants` + `dal_category_classifications` [EXTRACTED 0.98].
- **Post-commit pipeline matches doc.** `seed_dummy_data → result_writer → upsert_transactions → run_post_commit_pipeline → reconcile_transfers` [EXTRACTED 0.95].
- **Number-trust audit is a triple-rail proof.** Python oracle + Node oracle + DOM checker + UI registry [EXTRACTED 0.95].
- **Lineage system is internally consistent.** Cross-references between YAMLs resolve correctly.

## Drift candidates (actionable)

From 78 `semantically_similar_to` edges, the high-confidence cross-source-file pairs:

| Score | Drift candidate | Action |
|---|---|---|
| 0.95 | `CLAUDE.md Mission` ~~ `AGENTS.md Mission` | Converge on shared content or document divergence |
| 0.92 | `CLAUDE.md Non-Negotiable Guardrails` ~~ `AGENTS.md Non-Negotiable Engineering Rules` | Pick a single source of truth |
| 0.90 | Invariant `xc_011` ~~ Invariant `txns_001` | Both restate signed_amount/direction/amount law |
| 0.88 | `ARCHITECTURE.md §4.6 Sign Convention` ~~ `orchestrator-prompt.md Project-Specific Invariants` | Move canonical text to ARCHITECTURE.md, reference from orchestrator-prompt.md |
| 0.88 | Invariant `dash_001` ~~ Invariant `acct_002` | Two phrasings of the same net-worth-KPI invariant |
| 0.85 | `investment_implied_buy` ~~ `investment_buy` | Document divergence reason if intentional |
| 0.82 | Invariant `bud_002` ~~ Invariant `cf_004` | Both describe canonical spending pattern |
| 0.78 | Round 4 audit duplicates canonical category sets ~~ AI-015 manual maintenance | Possible duplicate finding |
| 0.7 | `bank_interest_credit` ~~ `money_market_sweep_interest` | Two interest-credit events that may unify |

Plus the self-reported `_EM constant duplicated across 17 files` flag from `income_attribution.yaml` — graph surfaces a real refactor opportunity.

## Loose-end taxonomy

| Category | Count | Note |
|---|---|---|
| Total nodes | 5,148 | |
| Orphans (0 edges) | 97 (1.9%) | Mostly module-level docstrings and unreferenced UI components (e.g. `chip.tsx`, `card.tsx`) |
| Lonely (1 edge) | 2,060 (40%) | Each referenced exactly once — high but normal for static analysis |
| Hubs (20+ edges) | 58 (1.1%) | The architectural backbone |
| Single-node communities | 97 | Pure noise — orphan UI components |
| 50+ node communities | 25 | The real architectural clusters |

**AI-NNN action items (`docs/data-lineage/ACTION_ITEMS.md`):**
- 65 entries surfaced as nodes
- 9 orphans — all marked `(resolved)` in their labels (reference deleted code; archival candidates)
- 14 well-connected (2+ edges) — actively cross-referenced

**Lineage YAMLs:**
- 765 lineage-related nodes
- 14 orphans
- 86 hubs (5+ edges)

## Top god nodes (most-connected concepts)

| # | Node | Edges |
|---|---|---|
| 1 | `get_db()` | 414 |
| 2 | `init_db()` | 141 |
| 3 | `ParseResult` | 100 |
| 4 | `DocumentParser` | 78 |
| 5 | `TSPStatementParser` | 48 |
| 6 | `build_account_filter()` | 45 |
| 7 | `events.yaml (Phase 1 taxonomy)` | 38 |
| 8 | `today()` | 37 |
| 9 | `main()` | 36 |
| 10 | `record_notification()` | 34 |

The fact that `build_account_filter()` (the regression-critical owner-scoping function CLAUDE.md warns about) is the 6th-most-connected concept across 5,148 nodes is graphify identifying it as architecturally central from AST + doc references alone.

## Caveats

- **Mixed extraction.** 8 chunks were extracted by Opus 4.7, 3 by Sonnet 4.6 (chunks 1, 2, 7 — retried after the original Opus attempts hit usage/rate limits). Sonnet was slightly more conservative on speculative INFERRED edges.
- **Snapshot timing.** Codex's `codex-trusted-seed-audit` branch was actively committing during the run. Files in the audit corpus reflect "repo state at the moment each subagent read them," not a single atomic snapshot.
- **`credential_broker.py` excluded.** Auto-flagged as sensitive by graphify's filename heuristic. Anything credential-flow-related is one degree underrepresented.
- **Static only.** Graph captures what files reference — not whether the code behaves correctly at runtime, nor whether documented invariants are actually enforced everywhere.

## How to refresh

See [`tools/graphify/`](../../../tools/graphify/). For an AST-only refresh on the code side (free, deterministic), `tools/graphify/run_fullcode.py`. A full re-run of the doc/YAML semantic extraction requires dispatching parallel Agent calls per the `prepare_full.py` chunk metadata; this is best invoked from a Claude Code session.
