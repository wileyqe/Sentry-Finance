---
description: Return this repo to clean main by pruning merged worktrees and branches safely.
argument-hint: ""
allowed-tools: [Bash, Read]
---

# Git-right

Bring the repository back to clean `main` after parallel branch/worktree work.

## Scope

This command is only for git hygiene after work has already been merged. Do not
implement features, edit roadmap items, run test suites, or delete unmerged
work as part of this command.

## Procedure

1. Inspect the current state:

```powershell
git status --short --branch
git worktree list --porcelain
git branch --all --verbose
```

2. If the current branch is not `main`, switch to `main` only when the current
   worktree is clean. If it is dirty, stop and report the dirty paths.

```powershell
git switch main
git fetch --prune origin
```

3. Fast-forward `main` to `origin/main` if possible. If it is not a
   fast-forward, stop and report the divergence.

```powershell
git merge --ff-only origin/main
```

4. For every extra local worktree, identify its branch and verify that branch
   is already merged into `main` before removal:

```powershell
git merge-base --is-ancestor <branch> main
```

If the check fails, do not remove that worktree or branch. Report it as
unmerged work that needs a human decision.

5. Remove only merged extra worktrees, then prune stale worktree metadata:

```powershell
git worktree remove <path>
git worktree prune
```

6. Delete only merged local branches other than `main`:

```powershell
git branch --merged main
git branch -d <merged-branch>
```

Never use `git branch -D` in this command.

7. Prune stale remote-tracking refs:

```powershell
git remote prune origin
```

8. Finish by proving the repo is clean and simple:

```powershell
git status --short --branch
git worktree list
git branch --all --verbose
```

## Success Criteria

- Current branch is `main`.
- `git status --short --branch` shows no local modifications and no ahead/behind
  drift.
- `git worktree list` shows only the main checkout.
- No merged local feature branches remain.
- Any unmerged branch/worktree was left intact and clearly reported.
