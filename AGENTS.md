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
4. Run the Graph Context Check in
   `docs/agent-rules/graph-context-check.md` when the task is non-trivial or
   the blast radius is unclear.
5. Open only the companion docs that touch the task.

Do not blindly load all prompt files. `docs/ROADMAP.md` points to the prompt
file when one matters.

## Graph Context Check

For non-trivial work or unclear blast radius, follow
`docs/agent-rules/graph-context-check.md`. Treat Graphify as advisory; live
code/tests and the canonical docs remain the source of truth.

## Workflow Skills

Matt Pocock's installed skills are explicit user-invoked workflow commands from
`~/.codex/skills/` and `~/.claude/skills/`; do not auto-activate them or
duplicate them as Sentry-local skills.

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
| Graph context checks | `docs/agent-rules/graph-context-check.md` |

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
