---
name: dev-stop
description: Full shutdown — commit and push changes, update ROADMAP.md, stop dev servers, and clean up. Use when wrapping up a dev session.
user-invocable: true
---

# Dev Session Shutdown

Pack up the dev session: sync work to GitHub, update project notes, then stop servers.

## Step 1: Check for uncommitted work

```bash
cd "/c/Users/chang/OneDrive/Desktop/Projects/Personal Finance Project"
git status
git diff --stat
```

If there are staged or unstaged changes, summarize what changed and ask the user
for a commit message (or propose one based on the diff). Then:

```bash
git add <relevant files>
git commit -m "<message>"
```

Do NOT commit `.env`, credentials, or `data/*.db` files.
Do NOT commit without showing the user what will be included.

## Step 2: Update project docs

Check if any work done this session should be reflected in project tracking:

- Read `docs/ROADMAP.md` — update status markers for any tasks that were
  completed or progressed (`[ ]` → `[->]` or `[v]`).
- If ARCHITECTURE.md has drifted from changes made this session, fix it or
  flag it in the commit.

Only make doc updates if there is something meaningful to record. Do not
add noise.

## Step 3: Push to GitHub

```bash
git push origin main
```

If the push fails (e.g., rejected due to remote changes), alert the user
rather than force-pushing.

## Step 4: Kill backend (uvicorn on port 8000)

Find the PID listening on port 8000 and kill it. Use `//PID` and `//F` (double
slash) because Git Bash on Windows mangles single-slash flags.

```bash
netstat -ano | grep ":8000 " | grep LISTENING | awk '{print $5}' | sort -u
# Then for each PID:
taskkill //PID <pid> //F
```

## Step 5: Kill frontend (Vite on port 1420)

Same approach for port 1420:

```bash
netstat -ano | grep ":1420 " | grep LISTENING | awk '{print $5}' | sort -u
# Then for each PID:
taskkill //PID <pid> //F
```

## Step 6: Verify ports are free

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/accounts 2>/dev/null || echo "Backend: stopped"
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:1420/ 2>/dev/null || echo "Frontend: stopped"
```

## Step 7: Final report

Report to the user:

- **Git**: what was committed and pushed (or "nothing to commit")
- **Docs**: what was updated (or "no updates needed")
- **Servers**: confirmation both ports are free
- **Status**: "Session packed up. Ready to close."
