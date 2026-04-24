# P21-T03: Build missing primitives

## Context

[docs/DESIGN.md](../../DESIGN.md) catalogues 8 Planned primitives in the Components section. Each has a locked prop signature and a target filename. Today, pages re-invent these shapes inline — 10 hand-rolled card patterns across 6 files, 5 inline `animate-pulse` skeletons bypassing `<Skeleton>`, bespoke empty-states in Documents/CashFlow/Accounts, bespoke error handling, duplicated KPI grids and filter rows, and framer-motion variant declarations repeated per page. This task builds the primitives so 21-T04 can do mechanical migration.

## Starting State

- [frontend/src/components/ui/](../../../frontend/src/components/ui/) contains `button.tsx`, `card.tsx`, `input.tsx`, `select.tsx`, `sheet.tsx`, `table.tsx`, `SyntheticBadge.tsx`, `TransactionLogo.tsx`.
- `<Card>` exists but is underused — many pages still hand-roll `bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl`.
- `<Skeleton>` exists at [frontend/src/components/Skeleton.tsx](../../../frontend/src/components/Skeleton.tsx) with presets (`KpiCardsSkeleton`, `ChartSkeleton`, `TransactionListSkeleton`); bypassed by 5 pages using inline `animate-pulse`.
- Framer-motion variants (`containerVariants` / `itemVariants`) are declared per page in BudgetsPage / AccountsPage / CashFlowPage / DashboardPage / InvestmentsPage — identical copies.
- [DESIGN.md](../../DESIGN.md) section 7 "Components" lists 8 Planned primitives with prop signatures.

## Task

Build all 8 primitives under [frontend/src/components/ui/](../../../frontend/src/components/ui/), matching the DESIGN.md signatures and the existing button/card conventions (forwardRef where applicable, `data-slot` attributes, `cn()` helper, `cva` for variants).

1. **`<EmptyState>`** → `empty-state.tsx`. Centered icon + title + description + optional action. No card wrapper — callers compose into a Card if needed.
2. **`<ErrorState>`** → `error-state.tsx`. Card-wrapped alert with title, description, optional retry Button. Uses `<AlertCircle>` from lucide-react.
3. **`<PageHeader>`** → `page-header.tsx`. Inner-page header: title + subtitle + actions slot. Distinct from global `Header.tsx` chrome.
4. **`<SectionHeader>`** → `section-header.tsx`. Wraps `.section-header` utility. `collapsible` prop toggles open state with chevron.
5. **`<FilterBar>`** → `filter-bar.tsx`. Flex container for filter controls. Export `FilterBar.Spacer` and `FilterBar.Search` as compound slots. Callers compose their existing `<Select>` controls inline.
6. **`<StatCard>`** → `stat-card.tsx`. KPI card: label + value + optional delta percent + optional trend slot. Delta colored via `text-gain` / `text-loss` / `text-neutral`. Wraps `<Card>`.
7. **`<Chip>`** → `chip.tsx`. CVA variants: `neutral` (uses `.chip-l2`) / `gain` / `loss` / `accent` / `warning`.
8. **`<PageShell>`** → `page-shell.tsx`. Wraps framer-motion `<motion.div>` with `containerVariants`. Exports `PageShell.Section` with `itemVariants` stagger. Pages stop redeclaring the recipe.

Each primitive:
- Imports `cn` from `@/lib/utils`
- Uses `forwardRef` if it's a generic container; functional components otherwise
- Exports named (not default) to match existing convention
- Avoids hardcoded Tailwind palette names — binds to tokens or existing utilities

## Verification

- `cd frontend && npm run build` — clean.
- `cd frontend && npm run dev` — dev server boots; no new console errors.
- Manual render check: create a sandbox route or just trust T04 migration to exercise the primitives.
- Each primitive's file < 120 lines.
- No primitive depends on another primitive outside the existing `<Card>` / `<Button>` foundations.
