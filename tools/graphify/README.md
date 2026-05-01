# tools/graphify

Orchestration scripts that produced [`docs/audits/graphify-2026-04-29/`](../../docs/audits/graphify-2026-04-29/). Preserved as-used for fidelity, not polished — these are audit artifacts.

[Graphify](https://github.com/safishamsi/graphify) builds a knowledge graph from a corpus of code + docs. Code goes through tree-sitter AST extraction (deterministic, free). Docs/YAML/JSON go through LLM-powered semantic extraction (costs tokens, requires Claude Code's `Agent` tool to dispatch parallel sub-agents per the [skill spec](https://github.com/safishamsi/graphify/blob/main/graphify/skill.md)).

## Scripts

| Script | What it does |
|---|---|
| `run_pipeline.py` | Backend-only AST run. First test, ~30 .py files, free. |
| `run_fullcode.py` | Cross-stack code-only AST run. backend + frontend/src + dal + extractors. ~240 files, free. |
| `prepare_full.py` | Stage A of full run. Detects all files in scope, runs AST on code, chunks doc/YAML corpus into ~22-file batches. Writes `chunks/chunk_NN.json` metadata + `.graphify_ast.json`. |
| `merge_full.py` | Stage C of full run. Reads AST + all chunk results, merges (AST nodes win on dedupe), runs Louvain clustering, auto-labels communities with stoplist, generates report + JSON + HTML. Bypasses graphify's default 5,000-node HTML cap. |
| `analyze_full.py` | Drift / loose-end analysis on the merged `graph.json`. AI-NNN connectivity, orphan/hub distribution, `semantically_similar_to` pair extraction, community size histogram. |
| `relabel.py` | Re-runs labeling step only with a stricter stoplist. For iterating on community names without re-extracting. |

Stage B (semantic extraction) of the full run was driven from the Claude Code session that ran `prepare_full.py` — 11 parallel `Agent` tool calls, each receiving its `chunk_NN.json` metadata + the [extraction prompt template from the skill source](https://github.com/safishamsi/graphify/blob/main/graphify/skill.md). There is no standalone CLI for this step; graphify intentionally relies on the host agent.

## Known issues / TODOs before re-running

- **Hardcoded paths.** Each script has `PROJECT_ROOT = Path(r"C:\Users\chang\...")` near the top and writes outputs to `~/graphify-trial-2026-04-29/graphify-out*/`. These need to be parameterized (env var or CLI arg) before the scripts will run anywhere else.
- **Output dir lives outside the repo.** Intentional — keeps generated artifacts (HTML, JSON, intermediate chunks, ~12 MB+ per run) out of the working tree. The committed snapshot is in `docs/audits/graphify-2026-04-29/`.
- **Sonnet retry was a separate dispatch.** The original 11 chunks went out as Opus subagents; chunks 1, 2, 7 hit usage/rate limits and were retried as Sonnet subagents. For future runs, default to Sonnet — the extraction task is structured-JSON-output, well within Sonnet's range, and ~5× cheaper.
- **graphify's HTML render hardcodes `MAX_NODES_FOR_VIZ = 5_000`** in `graphify/export.py`. `merge_full.py` monkey-patches it to 20,000 before calling `to_html`.
- **Windows console encoding.** On Windows + cp1252, the `→` and `·` characters in log output trigger `UnicodeEncodeError`. Scripts use ASCII-only equivalents (`->` and `/`) in console output; reports written to disk use UTF-8.

## Prerequisites

```bash
# Throwaway venv outside the repo, do not pollute project requirements
python -m venv ~/graphify-trial-2026-04-29/venv
source ~/graphify-trial-2026-04-29/venv/Scripts/activate  # Windows Git Bash
pip install graphifyy  # note: package name has double-y; import name is `graphify`
```

## To re-run (full)

1. `python tools/graphify/prepare_full.py` — runs AST + writes 11 chunk metadata files
2. From a Claude Code session: dispatch 11 parallel `Agent` calls (`subagent_type="general-purpose"`, `model="sonnet"`), each pointed at one `chunk_NN.json`. Use the extraction prompt template from the skill spec.
3. After all 11 result files are on disk: `python tools/graphify/merge_full.py`
4. `python tools/graphify/analyze_full.py` for drift / loose-end stats

A truly automated re-run would require either using the [Claude Agent SDK](https://docs.claude.com/en/docs/claude-code/sdk/sdk-overview) to dispatch sub-agents from a standalone Python script, or installing graphify as a slash command (`graphify install`) and running `/graphify <repo>` from a Claude Code session — but the latter writes to `~/.claude/skills/`.

## Caveats on cost

The original 8 successful Opus subagents averaged ~170K tokens each (~1.4M tokens total) and produced 100–180 nodes per chunk. The 3 Sonnet retries averaged ~90K tokens each and produced 80–110 nodes. **For drift detection on a stable lineage corpus, the right cadence is one full run per quarter.** Use `graphify update <path>` (AST-only, free) for code-only refreshes between full runs.

## Delta refresh (`refresh_delta.py` + `/refresh-graph`)

Between quarterly full audits, a delta-aware script keeps a rolling snapshot at `docs/audits/graphify-current/` in step with whatever has been committed since the last refresh. Semantic re-extraction is dispatched by the host Claude Code session — no separate Anthropic API key.

### Trigger paths

**Manual (any time):** invoke the slash command from this Claude Code session.

```
/refresh-graph
```

The command runs the AST step locally, then dispatches Sonnet sub-agents in parallel for changed docs/yaml/json, merges, writes `docs/audits/graphify-current/`, and stages the result. It does **not** commit — review the staged diff and decide.

**Scheduled (Windows Task Scheduler):** register the nightly job once.

```powershell
pwsh -File scripts\install_graphify_task.ps1
claude auth status                               # confirm logged in
gh auth status                                   # confirm logged in
powercfg /waketimers                             # confirm wake registered
Start-ScheduledTask -TaskName "Graphify Nightly" # smoke test
```

The task fires every other day at 3am with `-WakeToRun -StartWhenAvailable`. The wrapper (`scripts/graphify_nightly.ps1`) fast-forwards `main`, invokes `claude -p /refresh-graph --dangerously-skip-permissions`, then commits to a long-lived `graphify/auto-refresh` branch, force-pushes-with-lease, and opens or updates a single rolling PR. Logs to `%LOCALAPPDATA%\graphify-nightly\YYYY-MM-DD.log`. Tear down with `Unregister-ScheduledTask -TaskName "Graphify Nightly" -Confirm:$false`.

**Pre-push hook (free, every push):** `scripts/install_hooks.sh` installs a non-blocking pre-push hook that runs `refresh_delta.py --code-only --no-commit --allow-dirty`. AST-only, ~5s, no subscription usage. Skip with `SKIP_GRAPHIFY_HOOK=1 git push`.

### Modes of `refresh_delta.py`

```bash
python tools/graphify/refresh_delta.py --dry-run          # classify diff, print plan
python tools/graphify/refresh_delta.py --code-only        # AST-only end-to-end (free)
python tools/graphify/refresh_delta.py --plan-only        # AST + manifest at ~/.graphify-refresh-cache/
python tools/graphify/refresh_delta.py --finalize         # consume chunk results, write snapshot
```

`--plan-only` followed by `--finalize` is the contract the slash command uses. Each `--plan-only` run wipes prior chunk files in the work dir, so stale results never re-merge.

### Behavior

- Bails (exit 2) if the working tree is dirty (override with `--allow-dirty`).
- Reads `tools/graphify/.last_refresh.json` for the previous SHA. On first run it bootstraps from the most recent `graphify-YYYY-MM-DD/graph.json` commit.
- `git diff <last_sha>..HEAD --name-status` classifies changed files into AST-eligible (`.py`/`.ts`/`.tsx`/`.js`/`.jsx`) and semantic (`.md`/`.yaml`/`.json`/`.cfg`/`.toml`/`.ini`).
- AST extraction reuses `graphify.extract.extract` (free).
- Cost guard: `--plan-only` refuses if more than `--max-doc-files` (default 50) docs changed — kick a full rebuild instead.
- Merges into the previous snapshot using "AST wins on dedupe", prunes nodes whose `source_file` matches changed/deleted files, then re-clusters and re-renders.
- Writes `graph.json` / `graph.html` / `GRAPH_REPORT.md` / `README.md` to `docs/audits/graphify-current/` and stages them.
- Exit codes: `0` (applied / manifest ready), `1` (no diff), `2` (error).
