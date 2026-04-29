---
name: context-audit
description: Audit Codex config for token waste — AGENTS.md, allow-list, memory, skills, settings, deny rules. Scores health and offers fixes.
user-invocable: true
---

# Context Health Audit

Find token waste and context bloat in this project's Codex configuration.

## Step 1: Gather configuration data

Read all configuration sources in parallel. Do not ask the user to run
`/context` or any other slash command — gather the data directly.

**Files to read:**

```
# Project AGENTS.md
C:/Users/chang/OneDrive/Desktop/Projects/Personal Finance Project/AGENTS.md

# Settings (allow-list, deny rules)
C:/Users/chang/OneDrive/Desktop/Projects/Personal Finance Project/.Codex/settings.local.json

# Memory index and individual memory files
C:/Users/chang/.Codex/projects/C--Users-chang-OneDrive-Desktop-Projects-Personal-Finance-Project/memory/MEMORY.md
# Then glob: C:/Users/chang/.Codex/projects/C--Users-chang-OneDrive-Desktop-Projects-Personal-Finance-Project/memory/*.md

# All skill files
# Glob: .Codex/skills/*/SKILL.md
```

**Directories to check for build artifacts** (use `ls` or glob, not recursive):

```
frontend/node_modules/
frontend/dist/
__pycache__/           (check backend/, dal/, extractors/, tests/, config/, skills/)
.venv/
node_modules/          (root level)
dist/                  (root level)
```

Record line counts for AGENTS.md, each skill, and the memory index. Record
the number of entries in `permissions.allow` and whether `permissions.deny`
exists. Record which artifact directories are present on disk.

## Step 2: Audit AGENTS.md

**Line count:**
- Flag if > 200 lines
- Critical if > 400 lines

**Five-filter rule scan.** Read every rule and instruction in AGENTS.md.
Flag any that match:

| Filter        | Flag when...                                                        |
|---------------|---------------------------------------------------------------------|
| Default       | Codex already does this without being told ("write clean code")    |
| Contradiction | Conflicts with another rule in the same or a different config file  |
| Redundancy    | Repeats something covered elsewhere in the same file                |
| Bandaid       | Added to fix one bad output, not improve outputs generally          |
| Vague         | Would be interpreted differently every time ("use good judgment")   |

**Progressive disclosure.** If > 200 lines, check whether sections like
Environment Setup, Command Reference, or Done Means could move to reference
files with one-line pointers. Only recommend splitting when the content is
not universally needed every session.

**Scoring (max -15):**

| Condition              | Deduction |
|------------------------|-----------|
| > 200 lines            | -5        |
| > 400 lines            | -10       |
| Per 5 rules flagged    | -3        |
| Any contradictions     | -5        |

## Step 3: Audit allow-list

Parse `permissions.allow` from `.Codex/settings.local.json`.

**Categorize each entry:**

- **Reusable pattern** — contains a wildcard (`:*`, `*`), covers a command
  family (e.g., `Bash(git add:*)`, `Bash(npm install:*)`). These are healthy.
- **Stale artifact** — an exact one-shot command from a past session. Signs:
  specific PIDs (`taskkill //PID 12760`), specific test file paths, inline
  Python one-liners (`python -c "..."`), specific curl commands with query
  params, specific `Read()` paths outside the project.

Count total entries, reusable patterns, and stale artifacts.

**Scoring (max -25):**

| Condition                  | Deduction |
|----------------------------|-----------|
| > 50 total entries         | -5        |
| > 100 total entries        | -10       |
| > 150 total entries        | -15       |
| Stale entries > 50% total  | -5        |
| Stale entries > 75% total  | -10       |

## Step 4: Audit memory system

Read the memory index and each referenced memory file.

**Checks:**

- Count total memory files
- Count index lines (flag if > 50, which approaches the 200-line display cap)
- For each memory file, read the frontmatter `type` and `description`
- Flag memories where the described content duplicates something already in
  AGENTS.md (redundancy)
- Flag memories with no frontmatter or missing `type`/`description` fields

**Staleness is contextual.** `user` and `reference` memories age slowly and
should not be flagged on date alone. `project` memories older than 60 days
are likely stale. `feedback` memories are durable unless the behavior they
correct has been codified into AGENTS.md.

**Scoring (max -10):**

| Condition                        | Deduction |
|----------------------------------|-----------|
| Memory duplicates AGENTS.md      | -3 each   |
| Missing frontmatter fields       | -2 each   |
| Stale project memories (>60 days)| -2 each   |

## Step 5: Audit skills

Read each `.Codex/skills/*/SKILL.md`.

**Line count per skill:**
- Flag if > 200 lines
- Critical if > 500 lines

**Content checks:**
- Run the five-filter scan (same as Step 2) on instruction content
- Check for broken path references that don't match current project layout
- Check for synonymous instructions ("be concise" + "keep it short")
- Check for hedging language ("you may want to", "consider maybe")

**Scoring (max -10):**

| Condition                  | Deduction |
|----------------------------|-----------|
| Skill > 200 lines          | -3 each   |
| Skill > 500 lines          | -5 each   |
| Per 3 flagged instructions | -2        |

## Step 6: Audit settings and deny rules

**Settings checks:**

| Setting                            | Flag if             |
|------------------------------------|---------------------|
| `autocompact_percentage_override`  | Missing or > 80     |
| `BASH_MAX_OUTPUT_LENGTH` (env)     | Missing (default)   |

**Deny rules.** Check whether `permissions.deny` exists in settings. Then
check which of these artifact directories exist on disk:

| Directory pattern      | Present? |
|------------------------|----------|
| `frontend/node_modules`| check    |
| `frontend/dist`        | check    |
| `*/__pycache__`        | check    |
| `.venv`                | check    |
| `node_modules` (root)  | check    |
| `dist` (root)          | check    |

If artifact directories exist but no deny rules cover them, flag it.

**MCP servers.** Count the number of MCP servers loaded in the session.
Report the count and list them. Do NOT penalize user-level tool connections
(Calendar, Gmail, Chrome, computer-use, Kapture, Preview, pdf-viewer,
Shadcn UI, mcp-registry, scheduled-tasks, Slack) — these are workspace
tools, not project bloat. Only penalize MCP servers configured at the
project level in `.Codex/settings.local.json` that duplicate CLI
functionality.

**Scoring (max -20):**

| Condition                                 | Deduction |
|-------------------------------------------|-----------|
| Missing autocompact override              | -5        |
| Missing bash output length override       | -3        |
| No deny rules + artifact dirs exist       | -10       |
| Per project-level MCP duplicating a CLI   | -3        |

## Step 7: Score and report

Start at 100. Apply deductions from Steps 2-6, respecting per-category caps.
Floor at 0.

**Labels:**

| Score  | Label      |
|--------|------------|
| 90-100 | CLEAN      |
| 70-89  | NEEDS WORK |
| 50-69  | BLOATED    |
| 0-49   | CRITICAL   |

**Severity per issue:** CRITICAL if > 10 pts, WARNING if 5-10 pts, INFO if < 5 pts.

Output this format:

```
# Context Health Audit

Score: {N}/100 [{LABEL}]

## Breakdown

| Category         | Deduction | Cap | Details               |
|------------------|-----------|-----|-----------------------|
| AGENTS.md        | -{n}      | -15 | {line count, flags}   |
| Allow-list       | -{n}      | -25 | {total/reusable/stale}|
| Memory           | -{n}      | -10 | {file count, issues}  |
| Skills           | -{n}      | -10 | {line counts, flags}  |
| Settings & deny  | -{n}      | -20 | {missing items}       |
| MCP              | -{n}      | -10 | {count, project-level}|

## Issues

### [{CRITICAL|WARNING|INFO}] {Category}: {Problem}
{What's wrong — one or two sentences}
Fix: {Actionable one-liner}

### Flagged Rules
{Each flagged rule from AGENTS.md or skills: the text, which filter, why}

## Top 3 Fixes
1. {Highest-impact fix with estimated point recovery}
2. {Second}
3. {Third}
```

## Step 8: Offer to fix

After the report, present three tiers:

**Auto-apply** (safe, additive — do these without asking):
- Add `permissions.deny` rules for detected artifact directories

**Show diff, then apply on confirmation:**
- Allow-list consolidation: show stale entries to remove, report before/after count
- AGENTS.md rule removal: show each flagged rule with its filter and reason
- Stale memory cleanup: show each file with reason for removal

**Report-only** (user decides outside this skill):
- MCP server count and recommendations
- Settings overrides (user should set these based on their own preferences)
- Skill rewrite suggestions

For the confirm tier, show the proposed changes clearly, then ask:
"Want me to apply any of these? I can apply them individually or all at once."
