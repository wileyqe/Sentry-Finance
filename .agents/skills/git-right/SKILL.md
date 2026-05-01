---
name: git-right
description: "Actively return the repo to one clean, up-to-date main line. Use when the user invokes /Git-right, $git-right, Git-right, asks to clean up git, asks to get back to clean main, asks to prune branches/worktrees, or wants all completed work committed, pushed, PR'd, merged, and pruned while unfinished work is clearly preserved on an open branch."
---

# Git Right

Get the repository back to a single clean `main` line. Treat dirty work, extra branches, and extra worktrees as work to triage and resolve, not as an automatic stopping point.

## Operating Contract

- Determine the best path forward and keep going through safe, ordinary git/GitHub steps.
- Commit completed work, push branches, open PRs, merge or enable auto-merge when checks and repository rules allow it, then prune merged branches/worktrees.
- Preserve unfinished work on an appropriate open branch and report it clearly as remaining work.
- Stop for user clarity only when the next step requires a product decision, would discard work, would rewrite history, would bypass a policy, or is otherwise ambiguous.
- Never abandon, delete, reset, force-push, or overwrite work without explicit user confirmation.

## First Pass

Inspect the full repository shape:

```powershell
git status --short --branch
git worktree list --porcelain
git branch --all --verbose
git remote -v
```

Also inspect enough local context to understand current work:

```powershell
git diff --stat
git diff --name-status
git log --oneline --decorate --graph --all -n 30
```

Identify:

- Current branch and ahead/behind state.
- Dirty, staged, and untracked paths in every worktree.
- Local branches, remote-tracking branches, and their heads.
- Which branches are already merged into `main`.
- Which work appears complete, incomplete, unrelated, or unsafe to decide.

## Triage Dirty Work

For each dirty worktree or branch, choose the least surprising path:

- If the work is coherent and appears complete, verify it with focused checks, commit it with a clear message, push it, open a PR if needed, and merge or enable auto-merge when allowed.
- If the work is coherent but incomplete, commit or preserve it on a clearly named branch only when that is the best way to make the worktree clean without losing work. Prefer a draft PR or clear branch report for incomplete work that should remain visible.
- If the dirty paths are generated artifacts, reports, logs, or obvious temporary files, decide whether they should be committed, ignored, or removed based on repo patterns. Ask before deleting if there is any chance they contain unique work.
- If unrelated tasks are mixed together, split them only when the split is obvious and safe. Ask for direction when the grouping is ambiguous.
- If tests fail, CI fails, or verification is missing for a risky change, keep the branch open and report exactly what remains.

Do not stop merely because dirty work exists. Stop only when a decision cannot be made safely from the repository context.

## Complete Work

When a branch looks complete:

1. Review the diff and relevant docs to understand scope.
2. Run focused validation appropriate to the change.
3. Stage only relevant files.
4. Commit with an intentional message.
5. Push the branch.
6. Create a PR if the work is not already on `main`.
7. Merge, squash-merge, or enable auto-merge only when checks, review rules, and repository policy allow it.
8. Return to `main`, fetch, and fast-forward.

Use available GitHub app tools for PR creation, review/CI inspection, and merge operations when available. Use `gh` or git CLI only when needed.

## Preserve Open Work

When work should stay open:

- Leave it on a named branch with no dirty worktree when possible.
- Push the branch if preserving it remotely is the safest way not to lose work.
- Open a draft PR when that improves visibility and the branch has a coherent unfinished task.
- Report the branch as intentionally retained, including what task did not complete and what should happen next.

Do not delete retained branches or their worktrees.

## Main Cleanup

After completed work is merged or after open work has been preserved:

```powershell
git switch main
git fetch --prune origin
git merge --ff-only origin/main
```

If `main` and `origin/main` diverge, stop and report the divergence. Do not rebase, force-push, or make a merge commit on `main` unless the user explicitly approves that strategy.

For each extra worktree, remove it only after proving its branch is merged or intentionally preserved elsewhere:

```powershell
git merge-base --is-ancestor <branch> main
git worktree remove <path>
git worktree prune
```

Delete only merged local branches other than `main`:

```powershell
git branch --merged main
git branch -d <merged-branch>
```

Prune stale remote-tracking refs:

```powershell
git remote prune origin
```

Do not delete live remote branches unless the user explicitly requested remote branch deletion and the branch is safely merged.

## Finish

Prove the final state:

```powershell
git status --short --branch
git worktree list
git branch --all --verbose
```

Report:

- What was committed, pushed, PR'd, merged, and pruned.
- Whether the repo is now on clean `main`.
- Any branch intentionally left open and the task still remaining there.
- Any blocker requiring the user's decision.

Success means:

- Current branch is `main`.
- `main` is up to date with `origin/main`.
- The main worktree is clean.
- Merged worktrees and local branches are pruned.
- Unfinished work, if any, is preserved on explicit open branches with clear next steps.
