---
name: refresh-graph
description: Delta-refresh the graphify knowledge graph against commits since the last snapshot. Dispatches Sonnet sub-agents for changed docs/yaml; AST is free. Trigger with /refresh-graph manually, or via the nightly Windows Task Scheduler job at 3am.
user-invocable: true
---

# refresh-graph

You are running an unattended graphify delta refresh. Follow these steps in order. Do not skip steps. Do not deviate.

## What this does

Looks at git commits since the last recorded refresh, re-extracts only the touched files, merges them into the previous `docs/audits/graphify-current/` snapshot, and stages the result. Code (`.py` / `.ts` / `.tsx` / `.js` / `.jsx`) goes through deterministic AST extraction (free). Docs / YAML / JSON go through Sonnet semantic extraction via parallel sub-agents (uses your Claude Code subscription, not a separate API key).

This command does **not** push or commit. The nightly scheduler wrapper handles that; for a manual run, the user reviews the staged diff and commits themselves.

## Step 1 — Resolve the graphify venv python

Use this Bash one-liner to find the right interpreter and write it to a known location for the rest of the steps. Do not echo the path back to chat — just confirm in one line that it was found.

```bash
PY=""
for cand in "$HOME/graphify-trial-2026-04-29/venv/Scripts/python.exe" "$HOME/graphify-trial-2026-04-29/venv/bin/python"; do
  if [ -x "$cand" ]; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then echo "ERROR: graphify venv python not found"; exit 2; fi
"$PY" -c "import graphify" 2>/dev/null || { echo "ERROR: graphify not importable in venv"; exit 2; }
echo "$PY" > /tmp/.graphify-refresh-py
echo "venv python OK"
```

If it errors, stop and tell the user to run `pip install graphifyy` inside `~/graphify-trial-2026-04-29/venv` (note the double-y package name) and try again.

## Step 2 — Plan the refresh

```bash
PY=$(cat /tmp/.graphify-refresh-py)
GRAPHIFY_PROJECT_ROOT="$(git rev-parse --show-toplevel)" "$PY" tools/graphify/refresh_delta.py --plan-only
status=$?
echo "plan_exit=$status"
```

Interpret the exit code:
- **0** → manifest written; semantic chunks need agent dispatch. Continue to Step 3.
- **1** → either no commits since last refresh, or the diff was code-only and refresh finalized in place. Stop here. Tell the user "no semantic refresh needed" or "code-only refresh applied" depending on the script's last log lines.
- **2** → error. Show the user the script's stderr / final log lines and stop. Common causes: dirty working tree (instruct them to commit/stash), or the doc-change cap was exceeded (instruct them to run a quarterly full rebuild instead of a delta).

## Step 3 — Read the manifest

```bash
cat ~/.graphify-refresh-cache/manifest.json
```

Note the value of `total_chunks` and the `chunks` array. Each entry has `input_path` (the chunk's file list, already on disk) and `output_path` (where the sub-agent must write its result).

## Step 4 — Dispatch all sub-agents in a single message

For each chunk in the manifest, call the Agent tool **in the same response** (not sequential calls). Use `subagent_type="general-purpose"` and `model="sonnet"` for every dispatch — `Explore` is read-only and will silently drop the result, and Opus is overkill for this structured-JSON task.

The prompt for each sub-agent is below. Substitute `INPUT_PATH` and `OUTPUT_PATH` from the chunk entry. Substitute `CHUNK_NUM` and `TOTAL_CHUNKS` from the manifest. Pass them verbatim — do not paraphrase the rules.

```
You are a graphify extraction sub-agent. Read the chunk input file and the source files it lists, produce a knowledge-graph fragment as JSON, and write it with the Write tool to OUTPUT_PATH. Do not print the JSON to chat.

Chunk metadata: INPUT_PATH
This file contains: chunk_num, total_chunks, files (a list of repo-relative paths), output_path.

Steps:
1. Read INPUT_PATH to get the list of files.
2. Read every file in that list.
3. Construct a single JSON object matching the schema below.
4. Use the Write tool to write the JSON object (and only that object — no markdown fences, no preamble) to OUTPUT_PATH.
5. Confirm the write by reading the first 200 chars of OUTPUT_PATH back.

Extraction rules (chunk CHUNK_NUM of TOTAL_CHUNKS):
- EXTRACTED: relationship explicit in source (import, call, citation, "see §3.2"). confidence_score = 1.0.
- INFERRED: relationship implied but not stated. Reason about each edge individually:
  - Direct structural evidence (shared data structure, clear dependency): 0.8-0.9.
  - Reasonable inference with some uncertainty: 0.6-0.7.
  - Weak / speculative: 0.4-0.5.
- AMBIGUOUS: uncertain — flag for review, do not omit. confidence_score 0.1-0.3.

Code files: focus on semantic edges AST cannot find (call relationships, shared data, arch patterns). Do not re-extract imports — AST already has those.
Doc files: extract named concepts, entities, citations. Also extract rationale — sections that explain WHY a decision was made, trade-offs chosen, or design intent. These become nodes with `rationale_for` edges pointing to the concept they explain.

Semantic similarity: if two concepts in this chunk solve the same problem or represent the same idea without any structural link (no import, no call, no citation), add a `semantically_similar_to` edge marked INFERRED with a confidence_score of 0.6-0.95. Only add when similarity is genuinely non-obvious and cross-cutting.

Hyperedges: if 3+ nodes clearly participate together in a shared concept, flow, or pattern not captured by pairwise edges alone, add a hyperedge to the top-level `hyperedges` array. Maximum 3 hyperedges per chunk. Use sparingly.

Node ID format: lowercase, only [a-z0-9_], no dots or slashes. Format: {stem}_{entity} where stem is the filename without extension and entity is the symbol name, both normalized (lowercase, non-alphanumeric replaced with `_`). Example: `dal/transactions.py` + `UpsertTransactions` → `transactions_upserttransactions`. This must match the AST extractor's IDs so cross-references connect.

confidence_score is REQUIRED on every edge. Never omit it. Never use 0.5 as a default.

Output exactly this JSON shape (no other text, no fences):
{"nodes":[{"id":"session_validatetoken","label":"Human Readable Name","file_type":"code|document|paper|image","source_file":"relative/path","source_location":null,"source_url":null,"captured_at":null,"author":null,"contributor":null}],"edges":[{"source":"node_id","target":"node_id","relation":"calls|implements|references|cites|conceptually_related_to|shares_data_with|semantically_similar_to|rationale_for","confidence":"EXTRACTED|INFERRED|AMBIGUOUS","confidence_score":1.0,"source_file":"relative/path","source_location":null,"weight":1.0}],"hyperedges":[{"id":"snake_case_id","label":"Human Readable Label","nodes":["node_id1","node_id2","node_id3"],"relation":"participate_in|implement|form","confidence":"EXTRACTED|INFERRED","confidence_score":0.75,"source_file":"relative/path"}],"input_tokens":0,"output_tokens":0}
```

After dispatching, wait for all sub-agents to complete.

## Step 5 — Verify chunks landed on disk

```bash
ls -la ~/.graphify-refresh-cache/chunk_*_result.json 2>&1
```

For any expected `chunk_NN_result.json` that is missing, that sub-agent failed silently. If more than half are missing, abort: tell the user to re-run, the most likely cause is a sub-agent dispatched as `Explore` (read-only) by mistake. Otherwise continue — `--finalize` tolerates a small number of missing chunks.

## Step 6 — Finalize

```bash
PY=$(cat /tmp/.graphify-refresh-py)
GRAPHIFY_PROJECT_ROOT="$(git rev-parse --show-toplevel)" "$PY" tools/graphify/refresh_delta.py --finalize
status=$?
echo "finalize_exit=$status"
```

If exit is 0, snapshot is in `docs/audits/graphify-current/` and changes are staged. If exit is 2, show stderr and stop.

## Step 7 — Quality summary

```bash
PY=$(cat /tmp/.graphify-refresh-py)
"$PY" tools/graphify/query_local.py quality \
  --graph docs/audits/graphify-current/graph.json \
  --previous-graph docs/audits/graphify-2026-04-30/graph.json
```

Then summarize for the user in 4-6 lines: how many code/doc files were re-extracted, the node/edge delta versus the previous quarterly snapshot, AI-NNN coverage (must stay ≥ 13), and whether the rolling snapshot is staged. Tell them to review `git diff --staged docs/audits/graphify-current/` and decide whether to commit. Do not commit on their behalf.

## Step 8 — Cleanup

Leave `~/.graphify-refresh-cache/` in place; the next `--plan-only` invocation wipes stale chunk files itself. Do not delete it manually.
