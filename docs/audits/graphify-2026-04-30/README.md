# Graphify Audit — 2026-04-30 (delta vs 2026-04-29)

Updated graphify run against `main` @ `2c4ab3b`. This is the second run; the previous snapshot is at [`docs/audits/graphify-2026-04-29/`](../graphify-2026-04-29/) for direct comparison.

## Headline delta

| Metric | 2026-04-29 | 2026-04-30 | Delta |
|---|---:|---:|---:|
| Files in scope | 563 | 594 | +31 |
| Total words | 585K | 1.49M | +2.5× |
| Code files | 327 | 332 | +5 |
| Doc/YAML/JSON files | 236 | 262 | +26 |
| Nodes | 5,148 | 4,590 | **−558** |
| Edges | 9,207 | 9,208 | +1 |
| Communities | 255 | 179 | −76 |
| **Hyperedges** | **33** | **40** | **+7** |
| Orphans (degree 0) | 97 | 62 | −35 |
| Lonely (degree 1) | 2,060 | 1,656 | −404 |
| Hubs (degree 20+) | 58 | 69 | **+11** |
| Density (edges/node) | 1.79 | 2.01 | +12% |

The corpus grew (+31 files, +2.5× words — Codex's number-trust audit landed substantial doc content), but node count dropped by 558. The drop is a **mixed-model artifact**, not a real corpus change: 8 chunks were extracted by Sonnet 4.6, 4 by Haiku 4.5 (after the org's monthly Sonnet/Opus budget hit limits mid-run). Haiku averaged 35–66 nodes per chunk vs Sonnet's 76–90 — more conservative on speculative INFERRED edges.

**The graph is denser and more architecturally informative even though smaller.** Hyperedges +7, hubs +11, density +12%.

## What's new in the architecture

Codex landed Phase 9 / number-trust work since the last snapshot. New god nodes reflect that:

| Node | Edges (today) | Edges (yesterday) |
|---|---:|---:|
| `audit_number_trust.py` | **56** | not in top 15 |
| `reports.py` | 47 | 42 |
| `seed_dummy_data.py` | 41 | 38 |
| `run()` (added to top 15) | 42 | not present |

Yesterday's `events.yaml (Phase 1 taxonomy)` (38 edges) dropped out of top 15 — replaced by `audit_number_trust.py` and the runtime-context surface area Codex added.

## New hyperedges (7 net new architectural patterns)

- **Sign Convention Enforcement Ecosystem** [EXTRACTED 0.95]
- **Owner Scoping Data Flow** [EXTRACTED 0.9] — separate from yesterday's "Owner Scoping End-to-End Invariant"
- **Post-Commit Pipeline (11 steps)** [EXTRACTED 0.85] — graph found one more step than yesterday
- **Audit Framework (Trust Bar Items)** [EXTRACTED 0.8] — number-trust audit framework
- **Institution Connector → Refresh → Pipeline** [INFERRED 0.85]
- **Canonical Income Pipeline** [EXTRACTED 1.0]
- **Investment Snapshot Chain** [INFERRED 0.85]
- **`_EM COALESCE constant shared across cash_flow, flow_aggregation, forecasting, budget`** [EXTRACTED 0.9] — yesterday's lineage-flagged drift now has its own hyperedge!
- **Transfer Exclusion Guard** [EXTRACTED 1.0]
- **Canonical Cash-Flow Definition** [EXTRACTED 1.0]
- **Canonical Category Semantics: vocabulary.json / dal classifications / audit oracle** [EXTRACTED 0.92]

15 yesterday-hyperedges aren't in today's set verbatim, but most are regrouped/re-named (e.g., "Pipeline Unification Across Real and Dummy Data Paths" subsumed by "Post-Commit Pipeline (11 steps)").

## Drift candidates — TODAY (21 total, down from 78)

The semantic-similarity edge count dropped because Haiku is more conservative — fewer false-positive duplicates flagged. Today's high-confidence pairs:

| Score | Drift candidate | Status |
|---|---|---|
| 0.95 | `Invariant bud_001 (Household-Only Budgets, v23)` ~~ `Invariant xc_006 (Budgets No owner_id Writes Blocked)` | **NEW** — both restate the same migration-v23 invariant |
| 0.92 | `Oracle Vocabulary JSON (Neutral Category Semantics)` ~~ `dal/category_classifications.py (single source of truth)` | **NEW** — JSON oracle and Python source-of-truth could drift |
| 0.9 | `Invariant xc_011 (Signed Amount Direction Table Invariant)` ~~ `Invariant txns_001 (Signed Amount Direction Law)` | Same as yesterday |
| 0.88 | `Invariant dash_001 (Net Worth KPI)` ~~ `Invariant acct_002 (Account Groups Sum to NW)` | Same as yesterday |
| 0.88 | `Invariant dash_003 (Savings Rate Formula)` ~~ `Invariant cf_007 (Savings Rate Per Period)` | **NEW** |
| 0.88 | `Invariant bud_002 (Budget Actual Uses Canonical Spending)` ~~ `Invariant cf_004 (Monthly Canonical Pattern)` | Same as yesterday |
| 0.85 | `user_manual_valuation lineage event` ~~ `vehicle_valuation lineage event` | **NEW** — possibly intentional, document if so |
| 0.85 | `Checker Canonical Pattern Guidance` ~~ `Oracle Vocab: all_excl_from_spend` | **NEW** |

**Number-trust audit reports** flag among each other (4 dated reports cluster — expected, they're snapshots over time, not drift).

## What's missing in this snapshot

- **AI-NNN coverage degraded.** Yesterday's graph had 35 distinct AI-NNN entries surfaced; today's has 13. The 22 "missing" entries (AI-003, AI-007, AI-009, etc.) aren't gone from the repo — Haiku-extracted chunks 1, 4, 9, 10 (which include `ACTION_ITEMS.md`) didn't pick them up as nodes. To get full AI-NNN topology, refer to yesterday's snapshot or re-run those four chunks on Sonnet/Opus when budget allows.
- **Mixed extraction quality.** Sonnet chunks (2, 3, 5, 6, 7, 8, 11, 12) average ~85 nodes; Haiku chunks (1, 4, 9, 10) average ~50 nodes. The Sonnet-covered communities are richer.

## Architectural truths that still hold

- Owner-scoping wired DAL → API → Frontend
- Sign convention enforcement wall-to-wall
- `build_account_filter()` still the architecturally critical owner-scoping function (45 edges)
- Post-commit pipeline doc still matches code
- Number-trust audit triple-rail (Python oracle + Node oracle + DOM checker)

## Caveats

- **Mixed-model extraction** (8 Sonnet, 4 Haiku) makes node counts non-comparable across chunks
- Codex's runtime-context contract and single-DB authority work is partially captured (in code AST) but its docs were partially Haiku-extracted
- Snapshot timing: clean — no in-flight Codex commits during the run
- `credential_broker.py` again auto-skipped as sensitive

## How to refresh

When budget allows: re-run chunks 1, 4, 9, 10 on Sonnet for full AI-NNN coverage. See [`tools/graphify/`](../../../tools/graphify/) for orchestration scripts.
