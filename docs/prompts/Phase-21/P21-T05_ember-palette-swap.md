# P21-T05: Ember palette swap — `:root` + `.dark` replacement

## Context

[docs/DESIGN.md](../../DESIGN.md) locks Ember Studio (terracotta + amber over warm cream) as the target palette. P21-T02 closed the structural drifts (Geist→Inter/Newsreader/JetBrains Mono, `primary` Tailwind binding, orphan `background-light/dark`, duplicate `--chart-1..5`) and P21-T03/T04 built the primitive library and migrated hand-rolled shapes. What remains is the actual palette: `:root` and `.dark` in [frontend/src/index.css](../../../frontend/src/index.css) still carry emerald `oklch(0.52 0.13 155)` values inherited from the original shadcn-green theme. This task replaces those token blocks wholesale per the DESIGN.md § Colors tables, along with the four utility-level hardcoded emerald references so nothing inside `index.css` still carries an old-palette literal.

## Starting State

- `index.css:17-68` — `:root` block. `--primary`, `--ring`, `--sidebar-primary`, `--shadow-brand`, `--color-gain`, `--chart-c1` all set to emerald `oklch(0.52 0.13 155)`; surface colors are grayscale with no warmth (`oklch(0.975 0 0)` background, `oklch(1 0 0)` card).
- `index.css:70-117` — `.dark` block. Same emerald references at the lifted-lightness dark values; surfaces are pure-grayscale charcoal.
- `index.css:216` — `.card-interactive:hover` `border-color` hardcoded to `oklch(0.52 0.13 155 / 0.20)` (emerald 20%).
- `index.css:225-230` — `.chip-l2` uses grayscale `oklch(0.95 0 0)` / `oklch(0.30 0 0)` literals that bypass the token layer; DESIGN.md § Layout "chip" component spec binds chip background to `--surface-raised` and color to `--foreground`.
- `index.css:238-239` — `.bg-gain-subtle` / `.bg-loss-subtle` use hardcoded emerald-alpha / red-alpha literals that duplicate the soon-to-change `--color-gain` / `--color-loss` values.
- `index.css:274-276` — `.focus-ring` uses `ring-emerald-500/40` (Tailwind palette name). Not reactive to palette changes.
- DESIGN.md § "Known Drift" item 5 is the canonical record of the above and is the acceptance gate for T05.
- DESIGN.md § "Don't write CSS modules" note cites `ViewSelector.css` as the "last holdout" — verified it already uses `var(--primary)` / `var(--border)` / `color-mix` and no hex/oklch literals. The note is out of date; dropping it in the Known Drift cleanup.

Per-page inline `oklch(0.52 0.13 155)` references in [DashboardPage.tsx:220](../../../frontend/src/pages/DashboardPage.tsx), [BudgetsPage.tsx:36,37,54](../../../frontend/src/pages/BudgetsPage.tsx), [AccountsPage.tsx:233](../../../frontend/src/pages/AccountsPage.tsx), [AccountsSummaryCard.tsx:43](../../../frontend/src/components/AccountsSummaryCard.tsx) are the 12-files "hardcoded OKLch in TSX" callout in DESIGN.md § Don'ts. Those are explicit T04-continuation scope — not in T05.

## Task

1. **Replace `:root` block** with Ember light tokens per DESIGN.md § Colors tables. Add the new `--primary-hover`, `--surface-raised`, `--color-warning` tokens (not in the current code). Chart palette rotates to terracotta-anchored with amber, plum, olive, burgundy, slate-blue, gold.

2. **Replace `.dark` block** with Ember dark tokens. Backgrounds shift into warm charcoal (`oklch(0.16/0.20/0.24 0.008 45)`) so terracotta still reads as terracotta at night; borders remain `oklch(1 0 0 / <alpha>)`. Chart palette in dark mode keeps the same hues as light with lightness bumped ~+0.10 so lines contrast against the charcoal surface — a deliberate departure from DESIGN.md's single table (DESIGN.md shows one set; chart lines need slightly more luminance on dark bg than text does).

3. **Tokenize hardcoded emerald inside `index.css`:**
   - `.card-interactive:hover border-color` → `color-mix(in oklch, var(--primary) 20%, transparent)` (stays in sync with primary).
   - `.chip-l2` — drop the grayscale literals + the `.dark .chip-l2` override; use `background: var(--surface-raised)` and `color: var(--foreground)` so both modes pick up warmth automatically.
   - `.bg-gain-subtle` / `.bg-loss-subtle` → `color-mix(in oklch, var(--color-gain|loss) 10%, transparent)` so subtle-bg chips track whatever gain/loss hue the mode applies.
   - `.focus-ring` — replace `ring-emerald-500/40` with `--tw-ring-color: color-mix(in oklch, var(--primary) 40%, transparent)` set after the @apply block, so the ring color reacts to whichever primary the mode serves.

4. **Update DESIGN.md § Known Drift** — item 5 flips from "open" to "resolved in 21-T05". Drop the "ViewSelector.css is the last holdout" note in § Don'ts since that file is already tokenized. Bump the front-matter `status: target` language in § Overview to reflect that the Ember palette now lives in `:root`/`.dark`, not just in this spec.

5. **Update ROADMAP.md Phase 21 row** — flip T05 to complete, surface the per-page hardcoded-oklch cleanup as a T04-continuation follow-up with file/line pointers.

## Verification

- `cd frontend && npm run build` — TS + Vite build clean.
- `cd frontend && npm run dev` — boot and visually confirm each page:
  - Dashboard KPI cards: background is warm cream, not gray; ViewSelector active pill is terracotta, not emerald; primary buttons reading as burnt-orange.
  - Transactions: row hover is warm-tan, not gray-slate; focus ring on the search input is terracotta/40.
  - Reports: Sankey `--chart-c1` terminal bucket renders terracotta; other nodes spread across the new 8-hue palette.
  - Cash Flow: `.bg-gain-subtle` / `.bg-loss-subtle` deltas sit on the new gain/loss hues, not on the old emerald/crimson.
  - Accounts: interactive card hover border reads faint terracotta, not faint emerald.
- `grep -n "oklch(0.52 0.13 155" frontend/src/index.css` — zero hits.
- `grep -n "ring-emerald" frontend/src/index.css` — zero hits.
- DESIGN.md Known Drift item 5 flipped to "resolved" and no longer claims the palette is emerald on `main`.

## Not in scope

- The 5 TSX files with hardcoded `oklch(0.52 0.13 155)` chart/category literals (DashboardPage / BudgetsPage / AccountsPage / AccountsSummaryCard). Those migrate to `var(--chart-c*)` under the T04-continuation sweep — flagged as follow-up in ROADMAP.
- The 327 Tailwind palette-name usages (`text-slate-400`, `text-emerald-500`, etc.). Also T04 continuation.
- `font-feature-settings` on body: DESIGN.md specifies `"cv11", "ss01"` but `index.css:126` currently sets `"cv02", "cv03", "cv04", "cv11"`. Not a palette concern; park as a follow-up.
