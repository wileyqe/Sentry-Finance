# Branch & Worktree Hygiene

Soft guardrails: surface git state and offer options, do not block or resolve
unilaterally. Parallel work silently written against a stale `main` is the
most common source of regressions.

## Alert triggers

Check at session start or before starting new work:

- Working tree has uncommitted or untracked changes
- More than one local branch, or more than one registered worktree
- Local `main` differs from `origin/main`
- Any non-main branch has > 10 commits of `main` ahead of its merge base

## What not to allow

- Starting feature work before `main` is confirmed clean and synced.
- A second active branch while the first is unmerged, unless named as an
  explicit parallel effort.
- Mixing small edits (doc, one-file, meta) with complex work (multi-file,
  schema, connector, phase-tracked) on the same branch — small goes to
  `main`, complex goes to a named branch off clean `main`.
- Creating a worktree without naming the files it will touch and surfacing
  overlap with edits elsewhere; decide who wins before parallel edits begin.
- Deleting a branch holding unique unmerged work without explicit confirmation.
- Merging a worktree branch back without reviewing its diff against current
  `main` for schema/PII/sign-convention/dependency drift.
