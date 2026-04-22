# Superpowers Framework --- When to Use

> **Confidence-triggered reference.** Load only when deciding whether to
> lean on the structured workflow framework for a task. The operative
> rule lives in `CLAUDE.md` under "Structured Workflow Framework".

The Superpowers plugin (`obra/superpowers-marketplace`) provides
auto-activating skills for brainstorming, plan writing, subagent
dispatch, worktree isolation, TDD cycles, and root-cause debugging.
Do not invoke specific Superpowers skills by name --- they activate
from context, and the operating manual should not couple to the
framework's internal naming.

**Rule from CLAUDE.md:** if you land below 85% confident the framework
adds value, ask the user before using it. The triggers below inform
that confidence judgment.

## High confidence --- use the framework (≥85%)

- Multi-phase initiatives spanning backend + DAL + frontend (e.g. the
  data accuracy overhaul, a new connector build, a schema-shaped feature)
- Any change touching `dal/migrations/` plus reconciliation, derived
  metrics, or the post-commit pipeline
- New extractor/connector from scratch, including parser + writer + tests
- Refactors crossing 3+ architectural seams (router → DAL → orchestrator
  → connector)
- Work the user explicitly scopes via a new `docs/prompts/` file

## Medium confidence --- ask first (<85%)

- Single-area but non-trivial bug fixes where root cause is unclear
- New parser variant for an existing connector
- A new API endpoint with non-trivial validation, SSE events, or DAL
  changes
- Frontend feature contained to one component tree but with new state
  shape
- Performance work in a hot path

## Low / not needed --- skip the framework

- Doc-only edits, ROADMAP updates, prompt file authoring
- Single-file refactors, renames, typo fixes
- Lint/style cleanups
- Adding a single test case to an existing suite
- Config tweaks, dependency bumps
- Anything already scoped to a "small, tightly related cleanup" per
  CLAUDE.md's default working model
