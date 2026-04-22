# docs/prompts/ --- Institutional Memory

> **Detailed decision records.** Prompt files hold starting-state
> assumptions, verification checklists, and design rationale that
> `docs/ROADMAP.md` compresses to a paragraph per task. Load a prompt
> file **only when ROADMAP's task summary is not enough** --- they are
> institutional memory, not required session reading.

---

## How to find a prompt

Two paths, pick whichever fits:

1. **By task (most common):** Open `docs/ROADMAP.md`, find the next
   `[ ]` or `[!]` task, and follow the `Prompt:` line under it. Every
   task that has a dedicated prompt points to its file from ROADMAP.
2. **By phase theme:** Use the Phase Index table below.

Do not grep the folder blindly --- ROADMAP has faster, richer context.

## When to load a prompt file

- **Yes:** you need the original "Context / Starting State / Task /
  Verification" scaffolding for a task that is about to be worked on,
  revised, or re-verified.
- **Yes:** you are tracing *why* a decision was made and the git log
  commit message is not enough.
- **No:** you just need the current file layout or shipped feature list
  --- read the code or the ROADMAP `[v]` entries.
- **No:** you only want to know "what's next" --- the ROADMAP task
  summary answers that without the full prompt.

## When to author a prompt file

Non-obvious bug fixes, multi-file changes, architectural shifts, and
new features should get a prompt file using the five-section scaffold
below. The test: if you'd want to reconstruct the reasoning six months
from now, it gets a prompt.

**Exceptions** --- no prompt file required:

- Typos, docstring tweaks, comment edits, lint/style/type cleanups
- One-line or few-line bug fixes with obvious root cause
- ROADMAP status updates and prompt-file authoring itself (meta)
- Small, tightly related cleanup discovered mid-task (already allowed
  under CLAUDE.md's default working model)

Non-obvious bug fixes, multi-file changes, architectural shifts, and
new features are NOT exceptions --- those are exactly the work that
produces institutional memory worth keeping.

---

## Phase Index

| Phase | Folder | Theme | Tasks | ROADMAP anchor |
|---|---|---|---|---|
| **0** | `Phase-0/` | Foundation & data quality | P0-T01..T05 | `## Phase 0: Foundation & Data Quality` |
| **1** | `Phase-1/` | Core derived metrics | P1-T01..T06 | `## Phase 1: Core Derived Metrics` |
| **2** | `Phase-2/` | TSP connector + document drop | P2-T01..T04 | `## Phase 2: TSP Connector & Document Drop` |
| **3** | `Phase-3/` | Forecasting & decision support | P3-T01..T04 | `## Phase 3: Forecasting & Decision Support` |
| **4** | `Phase-4/` | Connector enhancements & new sources | P4-T01..T07 | `## Phase 4: Connector Enhancements & New Data Sources` |
| **5** | `Phase-5/` | Frontend live data integration | P5-T01..T07 | `## Phase 5: Frontend Live Data Integration` |
| **6** | `Phase-6/` | Reviews & lifestyle analysis | P6-T01..T05 + corrections | `## Phase 6: Reviews & Lifestyle Analysis` |
| **7** | `Phase-7/` | Settings & multi-user prep | P7-T01..T03 | `## Phase 7: Settings & Multi-User Prep` |
| **8** | `Phase-8/` | UI/UX audit fixes + data accuracy | P8-T01..T08 + `Data-Accuracy-Overhaul.md` + `Post-Phase-Review.md` | `## Phase 8: UI/UX Audit Fixes` |
| **9** | --- | Income truth metrics | (no dedicated folder; tracked inline in ROADMAP) | `## Phase 9: Income Truth Metrics` |
| **10** | `Phase-10/` | Data trust overhaul | `Data-Trust-Overhaul.md` | `## Phase 10: Data Trust Overhaul` |
| **11** | --- | End-to-end numerical audit + adjustment pass | (no dedicated folder; tracked inline in ROADMAP) | `## Phase 11: End-to-End Numerical Audit + Adjustment Pass` |
| **12** | --- | Synthetic attribution + owner edit scaffolding | (no dedicated folder; `empty_state_audit.md` at the prompts root was produced mid-phase) | `## Phase 12: Synthetic Attribution + Owner Edit Scaffolding` |
| **13** | `Phase-13/` | Investments rebuild (strip + one-source-at-a-time) | `P13-T01_investments-rebuild-strip.md` + more to come | `## Phase 13: Investments Rebuild` |
| **14** | `Phase-14/` | Dollar accountability overhaul (terminal-fate Sankey + accountability scorecard) | `Dollar-Accountability-Overhaul.md` + `P14-T01..T05` | `## Phase 14: Dollar Accountability Overhaul` |

Phases 9, 11, and 12 deliberately do not have dedicated folders ---
their tasks were small enough to live inline in ROADMAP.

---

## Naming conventions

- **Per-task prompts:** `P#-T##_kebab-title.md` (e.g.
  `P0-T01_military-categorization.md`). The `P` is the phase, `T` is the
  task, everything after the underscore is a short human-readable slug.
- **Phase-wide initiatives** (architectural overhauls): bare kebab-case
  titles, e.g. `Data-Trust-Overhaul.md`, `Data-Accuracy-Overhaul.md`.
  These span multiple tasks and tables and sit beside the numbered
  prompts in their phase folder.
- **Corrections:** `P#-CORRECTIONS.md` --- post-hoc bug/audit reports
  issued after a phase's verification (e.g. `P6-CORRECTIONS.md`).
- **Root-level research docs:** live directly in `docs/prompts/` if
  they don't belong to a single phase (e.g. `empty_state_audit.md`).

## Prompt file structure

Every per-task prompt follows the same five-section scaffold:

1. `# P#-T##: Title`
2. `## Context` --- why this task exists, what problem it solves
3. `## Starting State` --- what the code/data looks like before the task
4. `## Task` --- the actual work, usually with numbered sub-steps
5. `## Verification` --- how to check it's done (tests, manual checks)

Larger prompts add `## Architecture` notes, `## Known Issues`, or
`## Post-Implementation Checklist` sections but the core four always appear.

## Cross-references out

Prompts often cite `docs/ARCHITECTURE.md` section numbers. **§3.3
(Data Ingestion Tiers)** and **§4.6 (Sign Convention)** are the most
common targets --- both are locked section numbers and will not be
renumbered.
