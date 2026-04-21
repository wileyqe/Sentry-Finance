# Ops: UI Consistency Pass — Dashboard Design System

## Context

A five-commit branch `ui-audit-20260317` (March 2026) attempted to
standardize six pages (Budgets, Accounts, CashFlow, Transactions,
Investments, Reports) to a shared "dashboard design system." PR #3
against main was opened 2026-04-21 but went immediately `CONFLICTING /
DIRTY`: main had churned the same seven files by +1327/-1114 lines
since the branch's merge base (`bdfd4071`), while the branch itself was
only +151/-70. Phase 13's investments rebuild, owner-scoping fixes, and
the editorial hero treatment (`05e4f51`) had moved the target files
far past where the old diffs could apply.

Diffing the ui-audit recipe against current main revealed that **most
of the intent has already been delivered on main** through independent
work. This doc captures the recipe and the remaining gaps so the
cleanup can be finished cheaply.

PR #3 was closed and `ui-audit-20260317` was deleted; the commits are
preserved as the tag `archive/ui-audit-20260317` pushed to origin.

## Starting State (as of 2026-04-21)

Six pages were in scope. Current main status of each:

| Page | motion wrap | `card-l1` usage | `text-label` usage | Status |
|---|---|---|---|---|
| [BudgetsPage.tsx](frontend/src/pages/BudgetsPage.tsx) | ✓ | ✓ | ✓ | **Done** |
| [AccountsPage.tsx](frontend/src/pages/AccountsPage.tsx) | ✓ | ✓ | ✓ | **Done** |
| [CashFlowPage.tsx](frontend/src/pages/CashFlowPage.tsx) | ✓ | ✓ | ✓ | **Done** |
| [InvestmentsPage.tsx](frontend/src/pages/InvestmentsPage.tsx) | ✓ | ✗ | ✗ | Gap — Phase 13 rebuild skipped `card-l1` / `text-label` |
| [ReportsPage.tsx](frontend/src/pages/ReportsPage.tsx) | ✗ | ✓ | ✓ | Gap — no framer-motion animations |
| [TransactionsPage.tsx](frontend/src/pages/TransactionsPage.tsx) | ✗ | partial (1) | ✓ (13 uses) | Gap — no motion, more `card-l1` adoption possible |

Design-system CSS classes (`card-l1`, `text-label`, `bg-background`,
etc.) are defined in [frontend/src/index.css](frontend/src/index.css).
`framer-motion` is a direct dependency (see
[frontend/package.json](frontend/package.json)).

Three reference implementations already exist on main:
BudgetsPage / AccountsPage / CashFlowPage. Use them as templates.

## The Recipe

The transformation is formulaic. Each page gets the same six edits:

1. **Import framer-motion and define variants at top of file:**
   ```tsx
   import { motion } from "framer-motion";

   const springTransition: any = {
     type: "spring",
     stiffness: 300,
     damping: 30,
   };

   const containerVariants = {
     hidden: { opacity: 0 },
     visible: {
       opacity: 1,
       transition: { staggerChildren: 0.05 },
     },
   };

   const itemVariants = {
     hidden: { opacity: 0, y: 10 },
     visible: { opacity: 1, y: 0, transition: springTransition },
   };
   ```

2. **Wrap outer `<div>` as `<motion.div>`:**
   ```tsx
   // before
   <div className="flex-1 flex flex-col min-w-0 bg-background-light dark:bg-background-dark overflow-auto custom-scrollbar">
   // after
   <motion.div
     variants={containerVariants}
     initial="hidden"
     animate="visible"
     className="flex-1 flex flex-col min-w-0 bg-background overflow-auto custom-scrollbar"
   >
   ```

3. **Wrap header + major content sections** with
   `<motion.div variants={itemVariants}>` so they stagger in.

4. **Replace ad-hoc card styling with `card-l1`:**
   ```tsx
   // before
   <div className="bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl p-6">
   // after
   <div className="card-l1 p-6">
   ```

5. **Replace ad-hoc label styling with `text-label`:**
   ```tsx
   // before
   <span className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.15em] mb-3">
   // after
   <span className="text-label mb-3">
   ```

6. **Normalize spacing + backgrounds:**
   - `p-8` → `p-12`, `px-8` → `px-12` (outer padding)
   - `bg-background-light dark:bg-background-dark` → `bg-background`
   - `border-slate-800/50` → `border-slate-800` (drop alpha)
   - `bg-white/50 dark:bg-background-dark/50` → `bg-white/50 dark:bg-background/50`

## Task

Bring the three remaining pages to parity. Each is self-contained; do
them in separate commits so reverting one doesn't disturb the others.

### T01 — InvestmentsPage: add `card-l1` + `text-label`

Phase 13's rebuild wired up framer-motion but kept ad-hoc card and
label styling. Replace:

- All card containers currently using
  `bg-white dark:bg-slate-900/50 border ... rounded-xl` → `card-l1`
- All tiny uppercase labels using
  `text-[10px] font-bold text-slate-400 uppercase tracking-[0.15em]`
  → `text-label`
- Grep for both patterns in [InvestmentsPage.tsx](frontend/src/pages/InvestmentsPage.tsx)
  and the three Investments sub-pages it composes
  ([InvestmentsOverview](frontend/src/pages/InvestmentsOverview.tsx),
  [InvestmentsHoldings](frontend/src/pages/InvestmentsHoldings.tsx),
  [InvestmentsAllocation](frontend/src/pages/InvestmentsAllocation.tsx))
  — the latter three already use `card-l1`, so they are likely reference-quality.

### T02 — ReportsPage: add framer-motion wrap

Already uses `card-l1` + `text-label`. Missing: the `motion.div`
container + item wrap. Apply recipe steps 1–3 and 6. See
[BudgetsPage.tsx](frontend/src/pages/BudgetsPage.tsx) as a template
for exactly where the `initial="hidden" animate="visible"` wrapper sits
and which sections get `itemVariants`.

### T03 — TransactionsPage: add framer-motion + expand `card-l1`

Has heavy `text-label` use (13 occurrences) but only one `card-l1`
use and no framer-motion. Apply steps 1–3, then grep for any
remaining `bg-white dark:bg-slate-900` card shapes and swap them to
`card-l1`.

## Verification

- [ ] `cd frontend && npm run build` — clean build, no TS errors
- [ ] `cd frontend && npm run tauri dev` — launch and visit each of
      the three touched pages; no console errors, animations play on
      mount (stagger visible)
- [ ] Visual spot-check: each page's top-level card + label styling
      matches BudgetsPage / AccountsPage / CashFlowPage
- [ ] Owner chip switcher (`[Quintin | Household | Amy]`) still
      renders correctly on each page
- [ ] No regressions in investments sub-navigation (if InvestmentsPage
      was touched)

## References

- Original archived branch: tag `archive/ui-audit-20260317` (origin)
- Original commits (five, in chronological order):
  - `2510776` [UI-AUDIT] Standardize BudgetsPage
  - `ccc11f8` [UI-AUDIT] Standardize CashFlowPage
  - `a202c04` [UI-AUDIT] Standardize AccountsPage + AccountsSummaryCard
  - `414f212` [UI-AUDIT] Standardize TransactionsPage
  - `aacb0e7` [UI-AUDIT] Standardize ReportsPage + InvestmentsPage
- Closed PR: [wileyqe/Sentry-Finance#3](https://github.com/wileyqe/Sentry-Finance/pull/3)
- Design system source: [frontend/src/index.css](frontend/src/index.css)
- Reference implementations: BudgetsPage, AccountsPage, CashFlowPage
