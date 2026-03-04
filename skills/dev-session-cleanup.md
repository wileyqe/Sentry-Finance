---
name: dev-session-cleanup
description: End-of-session or milestone cleanup — update docs, remove temp files, commit to GitHub
---

# Dev Session Cleanup

Run this workflow at the end of a development session or when a milestone is completed.
It ensures the project stays clean, documented, and version-controlled.

---

## When to Trigger

- ✅ A milestone or feature is complete and tested
- ✅ The user calls it quits for the evening
- ✅ Before switching to a different major feature area
- ✅ The user explicitly requests cleanup (e.g., `/cleanup`)

---

## Step 1: Update Project Documentation

Review and update these files to reflect the current state:

### ARCHITECTURE.md
- Does it accurately reflect the current system?
- Are any new connectors, modules, or data flows missing?
- Update the roadmap / next-steps section

### SKILL.md / new-connector-playbook.md
- Were any new patterns discovered that should be documented?
- Any pitfalls encountered that aren't yet captured?

### config/ files
- `accounts.yaml` — any new accounts added or removed?
- `refresh_policy.yaml` — any cadence changes?

> **Rule**: Don't invent changes. Only update what actually changed during this session.

---

## Step 2: Clean Temp and Debug Files

// turbo-all

Scan for and remove temporary files created during development:

1. Find candidate files:
```powershell
# Debug/analysis scripts in project root or scripts/
Get-ChildItem -Path . -Include "debug_*", "test_*", "tmp_*", "scratch_*", "analyze_*", "fix_*" -Recurse -File | Where-Object { $_.DirectoryName -notmatch '\\tests\\' -and $_.DirectoryName -notmatch '\\__pycache__\\' }
```

2. Find temp files in /tmp/ that belong to this project:
```powershell
Get-ChildItem -Path /tmp -Include "*.py", "*.json", "*.txt" -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt (Get-Date).AddDays(-1) }
```

3. Check for leftover screenshots from debugging (not from production runs):
```powershell
# Screenshots older than a day in the screenshots dir that aren't from production
Get-ChildItem -Path data/screenshots -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "debug|test|tmp" }
```

4. **Review the list with the user before deleting** — some files may be intentionally kept.

5. Clean Python cache:
```powershell
Get-ChildItem -Path . -Filter "__pycache__" -Recurse -Directory | Remove-Item -Recurse -Force
```

---

## Step 3: Verify Clean State

// turbo

```powershell
# Verify no syntax errors in core files
python -c "import py_compile; import glob; files = glob.glob('extractors/*.py') + glob.glob('skills/*.py') + glob.glob('backend/*.py') + glob.glob('dal/*.py'); [py_compile.compile(f, doraise=True) for f in files]; print(f'All {len(files)} files compile OK')"
```

---

## Step 4: Stage and Commit to GitHub

1. Check status:
```powershell
git status
```

2. Review the diff to understand logical groupings:
```powershell
git diff --stat
```

3. Stage and commit in logical groups. Common groupings:

   - **Infrastructure** — base class changes, shared utilities, config updates
   - **Feature** — new connector or pipeline changes
   - **Cleanup** — removed temp files, lint fixes, doc updates

   Example:
   ```powershell
   # Infrastructure changes
   git add skills/ config/ dal/database.py run_all.py extractors/sms_otp.py
   git commit -m "feat: add logout lifecycle + popup dismissal + browser cleanup"

   # Feature-specific changes
   git add extractors/acorns_connector.py extractors/selector_registry.yaml
   git commit -m "fix: acorns login URL migration to oak.acorns.com"

   # Documentation
   git add ARCHITECTURE.md skills/new-connector-playbook.md skills/dev-session-cleanup.md
   git commit -m "docs: add connector playbook + cleanup workflow"
   ```

4. Push:
```powershell
git push origin main
```

> **Rule**: Never commit credentials, `.env` files, or files in `data/extracted/`. The `.gitignore` should already cover these, but double-check with `git status`.

---

## Step 5: Final Status Report

Summarize for the user:
- What was accomplished this session
- What was committed (commit hashes)
- What the next steps are
- Any open issues or blockers

---

## Quick Checklist

- [ ] ARCHITECTURE.md updated (if needed)
- [ ] Temp/debug files removed
- [ ] All Python files compile clean
- [ ] Changes committed in logical groups
- [ ] Pushed to GitHub
- [ ] Summary delivered to user
