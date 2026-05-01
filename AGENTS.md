# AGENTS.md

Codex adapter for this repository. `CLAUDE.md` is the primary agent operating
manual; this file keeps Codex-oriented startup notes and avoids copying the full
rule set into a second place.

## Start Here

At the beginning of a session:

1. Check branch/worktree state and read `docs/agent-rules/branch-hygiene.md`
   when git state looks off or feature work is about to start.
2. Read `CLAUDE.md` for current operating rules, guardrails, prompt policy,
   verification expectations, and done criteria.
3. Read `docs/ROADMAP.md`, especially `Next Up`. If a P0 item is open, it is
   the only eligible task unless the user explicitly redirects.
4. Run the Graph Context Check below when the task is non-trivial or the blast
   radius is unclear.
5. Open only the companion docs that touch the task.

Do not blindly load all prompt files. `docs/ROADMAP.md` points to the prompt
file when one matters.

## Graph Context Check

Graphify is a fast advisory map for "what else might be connected?" Use it to
avoid missed context before edits, not to ask permission to edit. Live code and
tests remain executable truth; `docs/ARCHITECTURE.md` remains design truth;
`docs/ROADMAP.md` remains status truth.

Run a graph check before non-trivial edits, multi-file changes, roadmap tasks,
DAL/API/frontend data-flow work, connector/parser work, schema/migration work,
PR merge/rebase work, or whenever blast radius is unclear. It is optional for
typos, tiny doc fixes, obvious one-line fixes, generated report updates, and
narrow test-only changes.

Common commands:

```powershell
python tools\graphify\query_local.py search "<term>"
python tools\graphify\query_local.py impact "<task or concept>"
python tools\graphify\query_local.py neighbors "<node or term>"
python tools\graphify\query_local.py hubs --limit 10
python tools\graphify\query_local.py drift --min-confidence 0.85
python tools\graphify\query_local.py quality
```

- Use `impact` at task start to find related files, tests, docs, and lineage.
- Use `hubs` before editing shared functions or highly connected modules.
- Use `drift` when changing invariants, docs, category rules, lineage, or
  number-trust assets.
- If the graph is stale, missing, or contradicts live code, proceed from
  code/tests and mention the graph limitation in the summary.
- For graph refresh/extraction details, see `tools/graphify/README.md`; do not
  duplicate that workflow here.

## Canonical Docs

Use one source of truth instead of copying long rules across files:

| Need | Canonical source |
|---|---|
| Agent operating rules, guardrails, verification, done criteria | `CLAUDE.md` |
| Current priorities and phase status | `docs/ROADMAP.md` |
| Architecture, invariants, module boundaries, design intent | `docs/ARCHITECTURE.md` |
| Frontend design system and UI rules | `docs/DESIGN.md` |
| Commands and environment setup | `docs/COMMANDS.md` |
| Owner, mortgage, TSP, income, and partner rules | `docs/HOUSEHOLD_PROFILE.md` |
| Trusted synthetic seed design | `docs/DUMMY_DATA_GENERATION_SPEC.md` |
| Event/table/UI lineage | `docs/data-lineage/HOWTO.md` |
| Prompt-file policy and phase prompt index | `docs/prompts/README.md` |
| Git/worktree safety | `docs/agent-rules/branch-hygiene.md` |

If docs and code disagree, use live code/tests for executable behavior and
`docs/ARCHITECTURE.md` for intended design. Fix important drift as part of the
task or mention it in the summary.

## Codex Notes

- The user may have uncommitted work. Never revert changes you did not make.
- Keep one primary task per session. Incidental cleanup is okay only when it
  touches the same path.
- Treat synthetic and live date behavior as one contract. Date-sensitive
  finance windows/defaults use the backend reference clock; live-data `as_of`,
  posting, statement, refresh, and event timestamps remain separate facts.
- Do not use `--no-verify`. If a docs check must be bypassed, use the
  accountable `SKIP_DOCS_CHECK="<reason>"` or `Skip-Docs-Check: <reason>`
  path described in `CLAUDE.md`.
- Do not delete branches, run destructive data wipes, or remove unique
  unmerged work without explicit confirmation.
