# P21-T04: Migrate pages to the primitive library

## Context

P21-T03 landed the 8 Planned primitives ([EmptyState](../../../frontend/src/components/ui/empty-state.tsx), [ErrorState](../../../frontend/src/components/ui/error-state.tsx), [PageHeader](../../../frontend/src/components/ui/page-header.tsx), [SectionHeader](../../../frontend/src/components/ui/section-header.tsx), [FilterBar](../../../frontend/src/components/ui/filter-bar.tsx), [StatCard](../../../frontend/src/components/ui/stat-card.tsx), [Chip](../../../frontend/src/components/ui/chip.tsx), [PageShell](../../../frontend/src/components/ui/page-shell.tsx)). This task replaces hand-rolled shapes across the pages so the shared-library contract holds: a card of a given spec changes in one file.

## Starting State

Audit findings (P21-T01 / T02):

- **10 hand-rolled card patterns** across 6 files (`bg-white dark:bg-slate-900*` + `rounded-xl` + `border`): CreditScorePopup, ToastContainer, Sidebar, Header, ReportsPage (×2), TransactionsPage (×4).
- **5 pages with inline `animate-pulse`** bypassing `<Skeleton>`: CashFlowPage, MonthlyReviewPage, SettingsPage, YearlyWrapUpPage, RefreshBanner (the Skeleton.tsx primitive itself uses `animate-pulse` internally — in-scope hit, not a bypass).
- **Framer-motion recipe duplicated** in 8 pages; 2 pages (ReportsPage, TransactionsPage) don't have motion yet — the P21-T01 UI-consistency audit flagged both.
- **Bespoke empty states** in DocumentsPage and CashFlowPage.

The 327 Tailwind palette-name usages (`text-slate-400`, `text-emerald-500`, etc.) are a separate concern — this task does not chase every one, but fixes surface drift inside any file it touches.

## Task

### Wave 1 — Hand-rolled card shapes → `<Card>`

Grep each of the 6 files for `bg-white dark:bg-slate-900` (with variants `/50`, `/70`, etc.) and replace with `<Card>` import + wrapper. Keep inline padding / flex / gap classes that are page-specific; only the elevation/bg/border moves into the primitive. Drop `rounded-xl border border-slate-*/50` since `.card-l1` supplies both.

### Wave 2 — Inline skeletons → `<Skeleton>`

For each of the 5 bypass files, replace `<div className="animate-pulse ..." />` with `<Skeleton />` (or a preset like `<ChartSkeleton>` if the context matches). The existing Skeleton primitive already applies `animate-pulse` + radius + muted bg.

### Wave 3 — Pages missing framer-motion → `<PageShell>`

Convert ReportsPage and TransactionsPage page roots to wrap in `<PageShell>` + `<PageShell.Section>` blocks. Remove the local `containerVariants` / `itemVariants` declarations if any (they'll come from the primitive). For pages that ALREADY have motion, do not migrate in this pass (deferred; not blocking).

### Wave 4 — Bespoke empty states → `<EmptyState>`

Find the centered-icon empty state in DocumentsPage and the "no data for this period" in CashFlowPage. Replace with `<EmptyState icon={<...>} title="..." description="..." />`. Drop per-page styling.

## Not in scope (explicit non-goals)

- Migrating all 14 pages to `<PageShell>` — only the 2 that lack motion. Migrating the other 8 (already animated via inline recipe) is deferred to a follow-up sweep; their behavior is already correct.
- Fixing every `text-slate-*` / `text-emerald-*` / `text-rose-*` palette-name usage (327 total). Inline incidental palette fixes in files we touch are welcome; the comprehensive sweep is a T04-continuation task.
- Inlining new `<StatCard>` adoption on the Dashboard KPI grid — Dashboard already uses a functional KPI pattern; rewriting that is deferred to avoid regression risk here.

## Verification

- `cd frontend && npm run build` — clean (TS + Vite).
- `cd frontend && npm run dev` — dev server boots; no new console errors.
- Preview spot check (via `mcp__Claude_Preview__preview_*`):
  - Dashboard renders (not touched, regression check)
  - Transactions renders with motion (new behavior)
  - Reports renders with motion (new behavior)
  - Documents empty state renders via `<EmptyState>` (visible `data-slot="empty-state"` in DOM)
  - Cash Flow empty state renders via `<EmptyState>` (visible `data-slot="empty-state"` in DOM)
- `grep -rE 'bg-white dark:bg-slate-900' frontend/src/` shows the expected reduction (was 10, should be ≤2 — any remaining are in files intentionally not migrated in this pass).
- `grep -r 'animate-pulse' frontend/src/ --include='*.tsx'` excluding Skeleton.tsx → ≤1 hit (or clearly justified remainder).
