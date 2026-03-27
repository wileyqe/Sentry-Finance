# 🎛️ /orchestrate — Sentry Finance UI/UX Standardization

## Pre-Flight: Create a Revert Point (Run This First)

Before any agent touches a file, execute the following in the project root to create a named, revertable save point on GitHub:

```powershell
# In: c:\Users\chang\OneDrive\Desktop\Personal Finance Project
git checkout -b ui-audit-$(Get-Date -Format "yyyyMMdd")
git push -u origin ui-audit-$(Get-Date -Format "yyyyMMdd")
```

**To instantly revert everything at any time:**
```powershell
git checkout main
git branch -D ui-audit-$(Get-Date -Format "yyyyMMdd")         # local cleanup
git push origin --delete ui-audit-$(Get-Date -Format "yyyyMMdd") # remote cleanup
```

> **All agent commits must be prefixed `[UI-AUDIT]` and land on this branch only — never on `main`.**

---

## Architecture Context (Read Before Deploying Any Sub-Agent)

| Dimension | Specifics |
|---|---|
| **Framework** | React 18 + TypeScript + Vite (runs on `localhost:1420`) |
| **Styling** | Tailwind CSS v4 + ShadCN — source of truth is [frontend/src/index.css](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/index.css) |
| **Design Token System** | OKLCH color space. Primary = `oklch(0.52 0.13 155)` (emerald). Semantic: `--color-gain`, `--color-loss`, `--color-neutral`. Card system: `.card-l1`, `.card-interactive`. Typography: `.text-label`, `.text-numeric`, `.stat-value`, `.stat-label`. |
| **Charts** | Mix of `@tremor/react` (Dashboard) and `recharts` (Budgets, Investments). Never swap libraries between pages — match the library already in use per file. |
| **Animation** | `framer-motion` (`motion.div`, `containerVariants`, `itemVariants`) on Dashboard/Transactions. `tw-animate-css` for page transitions. |
| **Icons** | Google Material Symbols Outlined only — `<span className="material-symbols-outlined">icon_name</span>` |
| **Layout Shell** | [App.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/App.tsx) → `<Sidebar />` + `<Header />` + `<AnimatedRoutes />`. Page content gets `page-enter` class on mount. All pages are full-height flex columns. |
| **API** | FastAPI at `http://127.0.0.1:8000`. Pages fetch directly with `fetch()` — no shared state/context layer. |

### Ground Truth: Dashboard Page Patterns ([DashboardPage.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/pages/DashboardPage.tsx))

The **Dashboard** is the established reference. All other pages must standardize to these patterns:

1. **Top-level container**: `motion.div` with `containerVariants` / `itemVariants`, `className="flex-1 overflow-auto custom-scrollbar p-12 space-y-16"`
2. **Section separators**: `border-b border-slate-200 dark:border-slate-800` — NOT `slate-100` or `slate-800/50`
3. **Section labels / widget headers**: `className="text-label"` utility class (defined in [index.css](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/index.css)) — NOT ad-hoc `text-[10px] font-bold text-slate-400 uppercase tracking-[0.15em]`
4. **Stat numbers**: `text-5xl font-bold tracking-tight text-numeric` for hero values; `text-3xl font-bold tracking-tight` for chart headers
5. **Inline dropdowns**: The custom invisible-`<select>` + visible label pattern. Not ShadCN `<Select>` unless already used on that page.
6. **Transaction items**: `py-4 border-b border-slate-100 dark:border-slate-800/50`
7. **Semantic colors**: Always `var(--color-gain)` / `var(--color-loss)` — never hardcoded `#10b981` or `red-500`
8. **Positive/Negative deltas**: Use `.stat-delta-pos` / `.stat-delta-neg` utility classes
9. **Cards**: `.card-l1` for static; `.card-interactive` for clickable cards — not inline `bg-white border border-slate-200 rounded-xl`
10. **Hover animations**: `whileHover={{ x: 4 }}` for list items; `whileHover={{ scale: 1.02 }}` for stat cards

---

## Target Pages & Known Inconsistencies

Process pages **in this order** (dependencies first):

### Page 1: [BudgetsPage.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/pages/BudgetsPage.tsx) 🔴 High Priority
- **Container**: Uses bare `<div className="flex-1 flex flex-col ...">` — must adopt `motion.div` with `containerVariants`
- **Section labels**: Uses ad-hoc `text-[10px] font-bold text-slate-400 uppercase tracking-[0.15em]` inline — replace with `.text-label` utility
- **Cards**: Uses inline `bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl` — replace with `.card-l1` 
- **Page padding**: Uses `p-8` — Dashboard uses `p-12`. Standardize to `p-12`
- **Edit hover**: `hover:text-blue-600` — must be `hover:text-[var(--color-gain)]`
- **`bg-background-light`**: This CSS class does not exist in [index.css](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/index.css) — remove it; use `bg-background`

### Page 2: [CashFlowPage.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/pages/CashFlowPage.tsx) 🔴 High Priority  
- Inspect for same patterns as Budgets. Likely uses `p-6` or `p-8` padding, ad-hoc label styles, and missing `motion.div` wrappers.
- Verify the `.cashflow-trend-line` SVG animation from [index.css](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/index.css) is actually being applied
- Check that chart colors use `--chart-c1` through `--chart-c8` variables, not hardcoded hex

### Page 3: [AccountsPage.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/pages/AccountsPage.tsx) 🟡 Medium Priority
- The [AccountsSummaryCard.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/components/AccountsSummaryCard.tsx) component likely uses its own card styling — align it to `.card-l1`/`.card-interactive`
- Verify drill-down/filter behavior (`?filter=assets` / `?filter=liabilities`) driven from Dashboard links still works after any class changes

### Page 4: [TransactionsPage.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/pages/TransactionsPage.tsx) 🟡 Medium Priority  
- Table rows: ensure `border-b border-slate-100 dark:border-slate-800/50` (matches Dashboard transaction list style)
- Filter bar: verify `border border-slate-300 dark:border-slate-700` on inputs matches the Dashboard dropdown style
- Sheet/drawer: [sheet.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/components/ui/sheet.tsx) component — ensure overlay is `bg-black/40 backdrop-blur-sm` (matches BudgetsPage modal)

### Page 5: [ReportsPage.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/pages/ReportsPage.tsx) 🟡 Medium Priority
- Sankey chart container: must be bounded within a `.card-l1` wrapper
- Sub-tab navigation: if present, use `border-b` underline style with `text-[var(--color-gain)]` active color — not arbitrary primary colors

### Page 6: [InvestmentsPage.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/pages/InvestmentsPage.tsx) 🟢 Lower Priority
- Sub-tabs (Investments / Holdings / Allocation): use consistent tab styling. Check if `border-b` + `text-emerald-600` or `text-primary` is used — standardize to `text-[var(--color-gain)] border-b-2 border-[var(--color-gain)]`
- Portfolio benchmark chart: confirm colors use `--chart-c1`, `--chart-c2` etc.

### Page 7: [Header.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/components/layout/Header.tsx) + [Sidebar.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/components/layout/Sidebar.tsx) (Shell) 🟢 Lower Priority
- [Sidebar.tsx](file:///c:/Users/chang/OneDrive/Desktop/Personal%20Finance%20Project/frontend/src/components/layout/Sidebar.tsx): `Settings` link is `<a href="#">` — acceptable to leave as placeholder but add `aria-label` and `cursor-not-allowed opacity-50` to visually signal it's inactive
- User avatar in Sidebar: the `src` URL is a remote Google image — flag this as PII/placeholder risk in the artifact; suggest replacing with a local asset or initials avatar

---

## Agent Workflow (PDCA Cycle Per Page)

### Step 1 — Inspector Agent (Plan)

**System prompt:**
```
You are a UI/UX Inspector for the Sentry Finance app. 
Your ONLY job is to read source files and produce a precise diff plan.

Inputs you will receive:
- The target page file (e.g. BudgetsPage.tsx)
- The ground truth document: this orchestrator prompt's "Ground Truth" section
- index.css (the full token system)

Output format — produce a markdown table:
| Location (file:line) | Problem | Correct Fix |
|---|---|---|

Rules:
- Never modify any file. Read-only.
- Check for: wrong padding classes, ad-hoc label styles (should be .text-label), 
  inline card styles (should be .card-l1/.card-interactive), missing motion.div 
  wrappers, wrong color classes (blue-600 instead of var(--color-gain)), 
  non-existent CSS classes (bg-background-light), wrong border colors.
- Note which Recharts vs Tremor library the page uses — NEVER suggest switching libraries.
- Flag any hardcoded hex colors or pixel values that should use CSS variables.
```

### Step 2 — Developer Agent (Do)

**System prompt:**
```
You are a Developer implementing UI fixes for the Sentry Finance app.

You will receive:
- The Inspector Agent's diff plan (markdown table)
- The target source file content

Rules:
- Edit ONLY the target .tsx file for this page.  
- All changes must be pure className/style string replacements or motion.div wrapper additions.
- NEVER change: API fetch URLs, state logic, event handlers, chart data mappings, component import paths.
- NEVER switch charting libraries (Tremor ↔ Recharts).
- Use ONLY these CSS utilities for new classes: text-label, text-numeric, stat-value, stat-label, 
  stat-delta-pos, stat-delta-neg, card-l1, card-interactive, chip-l2, text-gain, text-loss, 
  text-neutral, bg-gain-subtle, bg-loss-subtle, glow-brand, divider, section-header, focus-ring.
- For motion.div, import { motion } from "framer-motion" if not already imported and use the 
  containerVariants / itemVariants pattern from DashboardPage.tsx exactly.
- Output the complete modified file. No diffs, full file only.
```

### Step 3 — Reviewer Agent (Check)

**System prompt:**
```
You are a UI/UX Reviewer for the Sentry Finance app.

You will receive:
- The Developer Agent's modified file
- The original file (before changes)
- The Inspector's diff plan

Your job: Verify EVERY row in the Inspector's table was correctly addressed.

For each fix, output:
✅ PASS — [Location]: [what was fixed and confirmed correct]
❌ FAIL — [Location]: [what is still wrong and exact instruction to fix it]

Also check for regressions:
- Did any fetch() URL change? → FAIL
- Did any state variable get removed or renamed? → FAIL  
- Did any chart library get switched? → FAIL
- Were any non-existent CSS classes introduced? → FAIL (check against index.css)

Final verdict: APPROVED or REJECTED (with specific rejection reasons).
Iteration count: [current attempt / 3]
```

### Step 4 — Master Agent (Act)

When Reviewer outputs `APPROVED`:
1. Commit the file: `git add frontend/src/pages/[Page].tsx && git commit -m "[UI-AUDIT] Standardize [PageName] to dashboard design system"`
2. Generate the **Page Completion Artifact** (see template below)

If Reviewer outputs `REJECTED` after 3 attempts:
- **Halt immediately for this page**
- Generate the **Incomplete Artifact** (see template below)
- Move to the next page

---

## Output Artifact Templates

### Page Completion Artifact
```markdown
## ✅ [PageName] — UI Standardization Complete (Attempt [N]/3)

### Changes Made
| Fix | Before | After |
|---|---|---|
| Container | `<div className="...">` | `<motion.div variants={containerVariants}>` |
| ... | ... | ... |

### Regression Check
- [ ] All API fetch URLs unchanged
- [ ] All state variables intact
- [ ] Chart library unchanged ([Tremor/Recharts])

### Git Commit
`[UI-AUDIT] Standardize [PageName] to dashboard design system`
`SHA: [commit hash]`
```

### Incomplete Artifact
```markdown
## ⚠️ [PageName] — 3 Attempt Cap Reached. Human Intervention Required.

### What Was Fixed (Partial)
[List of ✅ PASSed items from final Reviewer output]

### What Remains Broken
[List of ❌ FAIL items from final Reviewer output — with exact file:line locations]

### Suggested Manual Fix
[Developer Agent's best-effort guidance for the failing items]

### To Proceed
Review the issues above, apply manual fixes, then run:
`git add frontend/src/pages/[Page].tsx`
`git commit -m "[UI-AUDIT] Standardize [PageName] — partial (human patched)"`
```

---

## Final Master Agent Summary Artifact

After all pages complete:

```markdown
## 🎨 Sentry Finance UI Audit — Session Complete

| Page | Status | Attempts | Commit SHA |
|---|---|---|---|
| BudgetsPage | ✅ COMPLETE | 2/3 | abc1234 |
| CashFlowPage | ✅ COMPLETE | 1/3 | def5678 |
| AccountsPage | ⚠️ PARTIAL | 3/3 | — |
| TransactionsPage | ✅ COMPLETE | 1/3 | ghi9012 |
| ReportsPage | ✅ COMPLETE | 2/3 | jkl3456 |
| InvestmentsPage | ✅ COMPLETE | 1/3 | mno7890 |
| Shell (Header/Sidebar) | ✅ COMPLETE | 1/3 | pqr1234 |

### To Merge to Main
```powershell
git checkout main
git merge ui-audit-[DATE] --no-ff -m "feat(ui): standardize all pages to dashboard design system"
git push origin main
```

### To Discard Everything
```powershell
git checkout main
git push origin --delete ui-audit-[DATE]
git branch -D ui-audit-[DATE]
```
```
