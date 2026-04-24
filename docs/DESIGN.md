---
name: Sentry Finance
description: Warm, craft-focused design system for a local-first personal finance command center
version: 0.1.0
status: target
colors:
  # Base palette — Ember Studio, adapted to OKLch for dark-mode symmetry.
  # Light values derive from https://designmd.ai/chef/ember-studio;
  # dark values proposed alongside them so the existing `.dark` machinery keeps working.
  primary:            "oklch(0.52 0.17 40)"    # #C2410C terracotta — actions, CTAs, focus rings
  primary-hover:      "oklch(0.41 0.14 35)"    # #9A3412 burnt sienna
  primary-foreground: "oklch(0.98 0.002 90)"
  accent:             "oklch(0.76 0.16 70)"    # #F59E0B amber — highlights, badges
  background:         "oklch(0.98 0.002 90)"   # #FAFAF9 warm white
  card:               "oklch(0.96 0.003 85)"   # #F5F5F4 surface
  surface-raised:     "oklch(0.91 0.005 80)"   # #E7E5E4 hover / selected
  foreground:         "oklch(0.18 0.005 50)"   # #1C1917 warm near-black
  muted-foreground:   "oklch(0.40 0.008 65)"   # #57534E warm gray
  border:             "oklch(0.87 0.004 75)"   # #D6D3D1
  ring:               "{colors.primary}"
  # Semantic value colors — sentiment, not brand.
  color-gain:         "oklch(0.56 0.18 145)"   # #16A34A
  color-loss:         "oklch(0.58 0.22 27)"    # #DC2626
  color-warning:      "oklch(0.67 0.15 55)"    # #D97706
  color-neutral:      "oklch(0.53 0.01 60)"    # #78716C stone
  # Chart palette — 8 hues, terracotta-anchored, ≥40° OKLch hue separation.
  chart-c1:           "oklch(0.57 0.16 40)"    # terracotta (primary echo)
  chart-c2:           "oklch(0.55 0.09 200)"   # teal (cool counterweight)
  chart-c3:           "oklch(0.72 0.15 75)"    # amber (accent echo)
  chart-c4:           "oklch(0.45 0.11 340)"   # plum
  chart-c5:           "oklch(0.58 0.08 115)"   # olive
  chart-c6:           "oklch(0.42 0.14 15)"    # burgundy
  chart-c7:           "oklch(0.50 0.08 250)"   # slate-blue
  chart-c8:           "oklch(0.68 0.13 85)"    # gold
typography:
  # Selected from the /design-variations gallery on 2026-04-24. Variation 14: craft editorial.
  display:
    fontFamily: "Newsreader"
    source: "Google Fonts, variable (ital,opsz,wght)"
    role: "Hero numerics ($487,231.84 net worth), page display headings"
  heading:
    fontFamily: "Newsreader"
    role: "h1 / h2 section heads"
  subhead:
    fontFamily: "Inter"
    role: "h3 subsection heads"
  body:
    fontFamily: "Inter"
    source: "Google Fonts, variable (wght)"
    role: "paragraphs, list text, form controls"
    featureSettings: '"cv11", "ss01"'
  numeric:
    fontFamily: "JetBrains Mono"
    source: "Google Fonts, variable (wght)"
    role: "Currency columns, amounts, tabular figures"
    featureSettings: '"tnum"'
    required: "font-variant-numeric: tabular-nums"
  label:
    fontFamily: "Inter"
    role: "Uppercase tracked labels (MONTH TO DATE, etc.)"
    transform: "uppercase"
    tracking: "0.12em"
    weight: 600
  scale:
    display:  { size: "2.5rem",   weight: 700, lineHeight: 1.05, tracking: "-0.015em" }
    h1:       { size: "1.875rem", weight: 700, lineHeight: 1.1,  tracking: "-0.015em" }
    h2:       { size: "1.35rem",  weight: 600, lineHeight: 1.2,  tracking: "-0.01em"  }
    h3:       { size: "1rem",     weight: 600, lineHeight: 1.25 }
    body-md:  { size: "0.92rem",  weight: 400, lineHeight: 1.55 }
    body-sm:  { size: "0.82rem",  weight: 400, lineHeight: 1.5  }
    label:    { size: "0.7rem",   weight: 600, lineHeight: 1.0,  tracking: "0.12em" }
rounded:
  sm:   "calc(var(--radius) - 4px)"   # 8px
  md:   "calc(var(--radius) - 2px)"   # 10px
  lg:   "var(--radius)"               # 12px — default card radius
  full: "9999px"                      # chips, avatar, pill buttons
spacing:
  # Tailwind default 4px scale; no custom spacing tokens introduced.
  base: 4
  scale: [4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80]
shadows:
  sm:    "0 1px 3px oklch(0 0 0 / 0.06), 0 1px 2px oklch(0 0 0 / 0.04)"
  md:    "0 4px 16px oklch(0 0 0 / 0.06), 0 2px 6px oklch(0 0 0 / 0.04)"
  lg:    "0 12px 40px oklch(0 0 0 / 0.08), 0 4px 12px oklch(0 0 0 / 0.04)"
  xl:    "0 24px 64px oklch(0 0 0 / 0.10), 0 8px 24px oklch(0 0 0 / 0.06)"
  brand: "0 4px 16px oklch(0.52 0.17 40 / 0.25)"
components:
  card:
    background: "{colors.card}"
    border: "1px solid {colors.border}"
    borderRadius: "{rounded.lg}"
    shadow: "{shadows.sm}"
    shadowHover: "{shadows.md}"
  card-interactive:
    extends: "card"
    hoverTransform: "translateY(-1px)"
    hoverBorder: "{colors.primary}"
  chip:
    background: "{colors.surface-raised}"
    color: "{colors.foreground}"
    borderRadius: "{rounded.full}"
  stat-delta-pos:
    color: "{colors.color-gain}"
    background: "oklch(0.56 0.18 145 / 0.08)"
  stat-delta-neg:
    color: "{colors.color-loss}"
    background: "oklch(0.58 0.22 27 / 0.08)"
---

# Sentry Finance — Design System

**Status:** `target` — Phase 21 consolidation. Token source of truth lives in [frontend/src/index.css](../frontend/src/index.css); the Ember adaptation of `:root` and `.dark` landed in Phase 21-T05 (2026-04-24). The "Known Drift" block at the end tracks the remaining gaps (all T04-continuation palette-name migration at this point).

## Overview

Sentry Finance is a local-first desktop finance command center for a single household. The design language is **warm and craft-focused** — cream surfaces, terracotta for action, amber for attention, JetBrains Mono for figures. Editorial rather than dashboard: data density matters more than chart decoration, and every surface should help the household answer the only question that counts — **"what should I do differently?"** We pair Newsreader (display / headings) with Inter (body) and JetBrains Mono (numerics) to land somewhere between a Sunday-paper personal finance column and a pilot's checklist.

The palette is adopted from [Ember Studio](https://designmd.ai/chef/ember-studio), converted from hex to OKLch so the existing light/dark machinery in `index.css` keeps working. Primary (terracotta) is an **action color**, not sentiment — money moves up and down in green and red, independent of brand.

## Colors

### Base palette

| Token | Light (OKLch) | Hex | Dark (OKLch) | Role |
|---|---|---|---|---|
| `--primary` | `oklch(0.52 0.17 40)` | `#C2410C` | `oklch(0.66 0.16 42)` | Actions, CTAs, active states, focus rings, links |
| `--primary-hover` | `oklch(0.41 0.14 35)` | `#9A3412` | `oklch(0.56 0.14 38)` | Primary-button hover |
| `--accent` | `oklch(0.76 0.16 70)` | `#F59E0B` | `oklch(0.78 0.15 70)` | Notifications, badges, attention highlights |
| `--background` | `oklch(0.98 0.002 90)` | `#FAFAF9` | `oklch(0.16 0.008 45)` | Page background |
| `--card` | `oklch(0.96 0.003 85)` | `#F5F5F4` | `oklch(0.20 0.008 45)` | Card / panel surface |
| `--surface-raised` | `oklch(0.91 0.005 80)` | `#E7E5E4` | `oklch(0.24 0.008 45)` | Hover / selected rows, chips |
| `--foreground` | `oklch(0.18 0.005 50)` | `#1C1917` | `oklch(0.96 0.003 85)` | Primary text |
| `--muted-foreground` | `oklch(0.40 0.008 65)` | `#57534E` | `oklch(0.72 0.008 65)` | Secondary / metadata text |
| `--border` | `oklch(0.87 0.004 75)` | `#D6D3D1` | `oklch(1 0 0 / 10%)` | Card and divider borders |
| `--ring` | `{colors.primary}` | — | — | Focus ring (always bound to primary) |

Dark mode is **intentional, not inverted** (following Ember's stance). Backgrounds shift into a warm-charcoal family with a hint of orange hue so terracotta still reads as the same material at night. Do not invert L\* and call it done.

### Semantic value colors (sentiment)

| Token | Light | Hex | Dark |
|---|---|---|---|
| `--color-gain` | `oklch(0.56 0.18 145)` | `#16A34A` | `oklch(0.72 0.16 145)` |
| `--color-loss` | `oklch(0.58 0.22 27)` | `#DC2626` | `oklch(0.70 0.20 27)` |
| `--color-warning` | `oklch(0.67 0.15 55)` | `#D97706` | `oklch(0.78 0.14 55)` |
| `--color-neutral` | `oklch(0.53 0.01 60)` | `#78716C` | `oklch(0.65 0.01 60)` |

**Rule.** Never hardcode Tailwind palette names (`text-emerald-500`, `bg-rose-500`, `text-slate-400`) for money sentiment or metadata. Use the semantic utilities `.text-gain` / `.text-loss` / `.text-neutral` (defined in [frontend/src/index.css](../frontend/src/index.css)) or the `sentimentClass()` helper at [frontend/src/lib/sentimentClass.ts](../frontend/src/lib/sentimentClass.ts). 327 violations of this rule exist across 24 files today; they migrate to tokens in Phase 21-T04.

### Chart palette

Eight distinct hues, terracotta-anchored, ≥40° hue separation in OKLch so 8-series stacked charts stay legible. Two warm anchors (c1, c3) + one cool complement (c2) handle the common two-series case.

| Slot | OKLch | Role |
|---|---|---|
| `--chart-c1` | `oklch(0.57 0.16 40)` | terracotta — most-salient series |
| `--chart-c2` | `oklch(0.55 0.09 200)` | teal — second-most-salient |
| `--chart-c3` | `oklch(0.72 0.15 75)` | amber |
| `--chart-c4` | `oklch(0.45 0.11 340)` | plum |
| `--chart-c5` | `oklch(0.58 0.08 115)` | olive |
| `--chart-c6` | `oklch(0.42 0.14 15)` | burgundy |
| `--chart-c7` | `oklch(0.50 0.08 250)` | slate-blue |
| `--chart-c8` | `oklch(0.68 0.13 85)` | gold |

**Series assignment rule.** Highest-salience series is always `c1`, next `c2`, etc. Consistent across every chart on every page so readers build a stable mental model. Do not remap c1/c2 per page.

## Typography

Selected from the `/design-variations` gallery on 2026-04-24. The goal: **craft editorial** — a finance page that reads like a Sunday broadsheet column more than a Bloomberg terminal. Variable-font families keep the download budget small; every face is on Google Fonts.

| Role | Family | Weight | Used for |
|---|---|---|---|
| Display | **Newsreader** (variable) | 700 | Net-worth hero, page display headings, KPI titles |
| Heading | **Newsreader** (variable) | 600 | h1, h2 |
| Subhead | **Inter** (variable) | 600 | h3, card titles |
| Body | **Inter** (variable) | 400 | Paragraphs, list text, form labels |
| Numeric | **JetBrains Mono** (variable) | 500 | Currency columns, tabular figures, amounts |
| Label | **Inter** (variable) | 600 | Uppercase tracked labels, stat captions |

### Scale

| Step | Size | Weight | Line height | Tracking | Class (today) |
|---|---|---|---|---|---|
| display | 2.5rem (40px) | 700 | 1.05 | -0.015em | `.stat-value` (update in 21-T03) |
| h1 | 1.875rem (30px) | 700 | 1.1 | -0.015em | page `<h1>` |
| h2 | 1.35rem (22px) | 600 | 1.2 | -0.01em | section header |
| h3 | 1rem (16px) | 600 | 1.25 | — | card title |
| body-md | 0.92rem (15px) | 400 | 1.55 | — | paragraph |
| body-sm | 0.82rem (13px) | 400 | 1.5 | — | caption, helper text |
| label | 0.7rem (11px) | 600 | 1.0 | 0.12em | `.text-label`, `.stat-label` |

### Rules

- **All currency and aligned numeric columns must use the numeric face** via `.text-numeric` ([index.css:187-191](../frontend/src/index.css)). Never use inline `font-mono` — it picks whatever mono the OS ships, loses JetBrains' character, and doesn't guarantee tabular alignment.
- **Body text carries `font-feature-settings: "cv11", "ss01"`** for the Inter stylistic set that fixes the single-story `a` and opens the `g`. This is already set on `body` at [index.css:134](../frontend/src/index.css).
- **Labels stay uppercase with 0.12em tracking.** No lowercase variants of `MONTH TO DATE` — it loses its affordance as a datum-scope marker.
- **Newsreader is display-only.** Do not run body paragraphs in Newsreader — the optical sizing gets harder to read below 18px.

## Layout

### Shell

[App.tsx](../frontend/src/App.tsx) composes the root:

```
┌─────────────────────────────────────────────────┐
│ Sidebar  │  Header (PAGE_META + ViewSelector)  │
│ (nav)    ├──────────────────────────────────────┤
│          │                                      │
│          │  <main>  Page content                │
│          │                                      │
└─────────────────────────────────────────────────┘
```

[Sidebar.tsx](../frontend/src/components/layout/Sidebar.tsx) is the tab router. [Header.tsx](../frontend/src/components/layout/Header.tsx) carries the page title (from a `PAGE_META` map), the refresh button, and — unconditionally — the owner-chip ViewSelector.

### Page scaffold

Every page follows the same shape. In Phase 21-T03 this gets extracted to a `<PageShell>` primitive so the recipe isn't re-declared per file:

```tsx
<motion.div
  variants={containerVariants}
  initial="hidden"
  animate="visible"
  className="flex-1 flex flex-col min-w-0 bg-background overflow-auto custom-scrollbar"
>
  <motion.div variants={itemVariants}>
    <PageHeader title="Accounts" subtitle="..." />
  </motion.div>

  <motion.div variants={itemVariants}>
    <FilterBar>…</FilterBar>
  </motion.div>

  <motion.div variants={itemVariants}>
    {/* content sections, each wrapped in <Card> */}
  </motion.div>
</motion.div>
```

Framer Motion variants:

```tsx
const springTransition: any = { type: "spring", stiffness: 300, damping: 30 };
const containerVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.05 } },
};
const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0, transition: springTransition },
};
```

These variants live in one place (will be `<PageShell>`'s module) so timing changes propagate everywhere.

### Owner chip (first-class)

[ViewSelector.tsx](../frontend/src/components/multi-user/ViewSelector.tsx) renders the **[Quintin | Household | Amy]** switcher unconditionally. Every new page's data fetch MUST thread `owner_id` via `useOwnerApi()` — this is a CLAUDE.md guardrail, not an optional convention.

### Background

Page root is always `bg-background`. The Tailwind colors `background-light` / `background-dark` are orphans (see Known Drift) and must not be used.

## Elevation & Depth

Five shadow levels + one branded accent. Cards live at L1; modals at L3. Do not introduce new shadow values — if something needs to pop more, check whether it should be L2 or L3 first.

| Level | Token | Usage |
|---|---|---|
| L0 | none | Page background. `surface-base` utility. |
| L1 | `--shadow-sm` → `--shadow-md` on hover | Content cards. `<Card>` / `.card-l1`. |
| L1 interactive | same + `translateY(-1px)` + primary-tinted border on hover | Clickable cards. `<Card variant="interactive">` / `.card-interactive`. |
| L2 | inline | Chips, badges, inline indicators. `<Chip>` / `.chip-l2`. |
| L3 | `--shadow-lg` / `--shadow-xl` | Modals, sheets, popovers. `<Sheet>`, `<Popover>`. |
| Accent | `--shadow-brand` | Rare — primary-tinted glow on premium surfaces. |

### Rules

- **No hand-rolled card shapes.** `className="bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl"` is a violation. Use `<Card>` (or the underlying `.card-l1` if you're inside a primitive that can't consume React components). 10 violations exist today across 6 files; migrated in Phase 21-T04.
- **Shadows only come from the token scale.** No `shadow-[...arbitrary]` values.

## Shapes

- **Radius.** `--radius: 0.75rem` (12px) → `rounded-lg`. `md` = 10px, `sm` = 8px, computed off `--radius`. Chips and pills use `rounded-full`.
- **Borders.** Always 1px, always `var(--border)`. No drop-alpha variants (`border-slate-800/50`).
- **Sparklines** ([Sparkline.tsx](../frontend/src/components/charts/Sparkline.tsx)) strip chrome: no axes, no legend, no grid. They earn their place by being quiet.
- **Divider.** `.divider` utility at [index.css:250-254](../frontend/src/index.css). 1px `var(--border)` with no margin, consumers handle spacing.

## Components

Sentry Finance's UI is a **shared component library** — modifying a card of a given spec in one file updates every card of that spec across the app. Every entry below is the single point of change for its shape.

Status legend: `Built` = exists and in use; `Planned` = spec locked here, implementation in Phase 21-T03.

### Built

| Primitive | File | Surface |
|---|---|---|
| `<Button>` | [ui/button.tsx](../frontend/src/components/ui/button.tsx) | CVA variants (default / outline / secondary / ghost / destructive / link) × sizes (xs / sm / default / lg / icon). `[&_svg]` selectors auto-size child icons. |
| `<Card>` | [ui/card.tsx](../frontend/src/components/ui/card.tsx) | Variants default / interactive. Slots: `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter`. Usage is inconsistent today — many pages still hand-roll; migration is 21-T04. |
| `<Table>` | [ui/table.tsx](../frontend/src/components/ui/table.tsx) | Semantic HTML wrapper with `TableHeader` / `TableBody` / `TableRow` / `TableHead` / `TableCell` / `TableFooter`. |
| `<Select>` | [ui/select.tsx](../frontend/src/components/ui/select.tsx) | @base-ui/react select, tokenized trigger. |
| `<Sheet>` | [ui/sheet.tsx](../frontend/src/components/ui/sheet.tsx) | Side / bottom drawer; shadow-lg. |
| `<Input>` | [ui/input.tsx](../frontend/src/components/ui/input.tsx) | Token-bound form input. |
| `<ViewSelector>` | [multi-user/ViewSelector.tsx](../frontend/src/components/multi-user/ViewSelector.tsx) | Owner chip switcher; unconditional; lives in Header. |
| `<TransactionLogo>` | [ui/TransactionLogo.tsx](../frontend/src/components/ui/TransactionLogo.tsx) | Tiered fallback: Clearbit → Google favicon → deterministic letter avatar. Sizes sm / md / lg. |
| `<Skeleton>` | [Skeleton.tsx](../frontend/src/components/Skeleton.tsx) | Presets: `KpiCardsSkeleton`, `ChartSkeleton`, `TransactionListSkeleton`. 5 pages currently bypass with inline `animate-pulse`; migrated in 21-T04. |
| `<Sparkline>` | [charts/Sparkline.tsx](../frontend/src/components/charts/Sparkline.tsx) | Stripped-chrome Recharts area; color from `sentimentStrokeClass()`. |
| `<SyntheticBadge>` | [ui/SyntheticBadge.tsx](../frontend/src/components/ui/SyntheticBadge.tsx) | Marks synthetic / test data on cards and rows. |
| `toast(msg, type, duration)` | [lib/toast.ts](../frontend/src/lib/toast.ts) | Event-bus toast; rendered by `<ToastContainer>` fixed bottom-right. |
| `formatCurrency(amount)` | [lib/formatCurrency.ts](../frontend/src/lib/formatCurrency.ts) | `-$1,234.56` convention, sign before `$`, 2 decimals. |
| `formatCompactCurrency(amount)` | [lib/formatCompactCurrency.ts](../frontend/src/lib/formatCompactCurrency.ts) | K/M/B abbreviation for KPI values ≥10,000. |
| `formatDetailField(field, value)` | [lib/formatDetailField.ts](../frontend/src/lib/formatDetailField.ts) | Field-aware formatter for account-detail panels (currency / percent / date / count). |
| `sentimentClass(value)` | [lib/sentimentClass.ts](../frontend/src/lib/sentimentClass.ts) | Maps a signed number to `text-gain` / `text-loss` / `text-neutral`. |

### Planned (21-T03)

Every Planned primitive below has a target file under [frontend/src/components/ui/](../frontend/src/components/ui/) and a minimum prop signature so the implementation is mechanical.

**`<EmptyState>`** — replaces bespoke empty states in Documents / CashFlow / Accounts / Reports (different shape in each today).
```tsx
<EmptyState
  icon={<Inbox />}
  title="No documents yet"
  description="Drop a PDF or import via Gmail to get started."
  action={<Button>Import</Button>}  // optional
/>
```
→ `frontend/src/components/ui/empty-state.tsx`

**`<ErrorState>`** — fallback card with retry; replaces inline error banners.
```tsx
<ErrorState
  title="Couldn't load transactions"
  description={error.message}
  onRetry={() => refetch()}
/>
```
→ `frontend/src/components/ui/error-state.tsx`

**`<PageHeader>`** — inner-page header (distinct from the global chrome `Header`).
```tsx
<PageHeader
  title="Accounts"
  subtitle="Net worth, assets, liabilities"
  actions={<Button>Refresh</Button>}
/>
```
→ `frontend/src/components/ui/page-header.tsx`

**`<SectionHeader>`** — wraps `.section-header` utility; optional collapsible.
```tsx
<SectionHeader title="Bank accounts" collapsible>
  {...}
</SectionHeader>
```
→ `frontend/src/components/ui/section-header.tsx`

**`<FilterBar>`** — locks the timeframe / account / category / search row shape. Removes duplicated filter logic from Dashboard / CashFlow / Transactions / Accounts.
```tsx
<FilterBar>
  <FilterBar.Timeframe value={tf} onChange={setTf} />
  <FilterBar.Account value={acc} onChange={setAcc} />
  <FilterBar.Spacer />
  <FilterBar.Search value={q} onChange={setQ} />
</FilterBar>
```
→ `frontend/src/components/ui/filter-bar.tsx`

**`<StatCard>`** — KPI card. Replaces duplicate grids in Dashboard KPI row / Accounts summary / Investments overview.
```tsx
<StatCard
  label="Net Worth"
  value={formatCompactCurrency(487231.84)}
  delta={+1.2}           // percent; colors via sentimentClass
  trend={<Sparkline data={...} />}  // optional
/>
```
→ `frontend/src/components/ui/stat-card.tsx`

**`<Chip>`** — `.chip-l2` as a typed component with variants.
```tsx
<Chip variant="gain">+2.4%</Chip>
<Chip variant="loss">-$1,203</Chip>
<Chip variant="accent">New</Chip>
<Chip variant="neutral">Pending</Chip>
```
→ `frontend/src/components/ui/chip.tsx`

**`<PageShell>`** — framer-motion container + variants + background + owner-chip plumbing. Pages stop re-declaring the recipe.
```tsx
<PageShell>
  <PageHeader title="…" />
  <PageShell.Section>…</PageShell.Section>
  <PageShell.Section>…</PageShell.Section>
</PageShell>
```
→ `frontend/src/components/ui/page-shell.tsx`

## Do's and Don'ts

### Do

- **Reach for an existing primitive before writing new markup.** If a primitive doesn't exist for the shape you need, **author one in [frontend/src/components/ui/](../frontend/src/components/ui/)** rather than hand-rolling inline. This is the shared-library contract — one place to change a spec, not N.
- **Use `var(--token)` references** for anything design-system. Never Tailwind palette names (`emerald-500`, `slate-200`, `rose-500`) — they don't respond to the palette and they break dark mode quietly.
- **Thread `owner_id` through every data fetch** via `useOwnerApi()`. Not optional; it's a CLAUDE.md guardrail.
- **Use `.text-numeric`** for any currency or aligned numeric column. Never inline `font-mono`.
- **Use `formatCurrency` / `formatCompactCurrency`.** Never hand-format money.
- **Use `.text-gain` / `.text-loss` / `sentimentClass()`** for value sentiment.

### Don't

- **Don't hardcode hex / RGB / OKLch literals in TSX.** 12 files have violations today; they migrate in 21-T04.
- **Don't introduce a new chart library.** Recharts is the only chart library. (Tremor was removed in 21-T04-cont-R on 2026-04-24; `@tremor/react` is no longer a dependency.)
- **Don't hand-roll** skeletons, empty states, error states, modals, filter rows, KPI cards, or page headers when a primitive exists (or is Planned above — build the primitive, don't inline around it).
- **Don't write CSS modules** except in extraordinary cases. [ViewSelector.css](../frontend/src/components/multi-user/ViewSelector.css) is the last surviving module and already token-bound (`var(--primary)` / `var(--border)` / `color-mix`); don't regress it.
- **Don't use `bg-background-light` / `bg-background-dark`** — those Tailwind colors are orphans.

### Verifying a change against this doc

Before merging a PR that touches `frontend/src/**`, run this three-question check:

1. **Is every color a token?** Grep your diff for `#[0-9a-fA-F]{6}`, `oklch(`, `rgb(`, `text-emerald-`, `text-rose-`, `text-slate-`, `bg-white dark:bg-slate`. Zero hits is the target.
2. **Is every card a `<Card>`?** Grep for `rounded-xl.*border` and `bg-white dark:bg-slate-900` in the diff.
3. **Is every currency value formatted?** Grep for `toFixed`, `.toLocaleString`, `$${`. Use `formatCurrency` instead.

If a primitive is missing for what you're building, **stop and build it** — don't inline around it.

## Known Drift

These are tracked against real code on `main`. `Resolved` items stay here as a record; open items flag the work that's queued.

1. ~~**Font family contradiction** — Manrope vs Geist at runtime.~~ **Resolved 21-T02 (2026-04-23):** Inter + Newsreader + JetBrains Mono now import from `@fontsource-variable/*` and bind via Tailwind's `fontFamily` block.

2. ~~**Primary color hardcoded in Tailwind config** (`primary.DEFAULT: "#11d483"`).~~ **Resolved 21-T02:** Tailwind `primary` now binds to `var(--primary)` / `var(--primary-foreground)`; dark mode follows the CSS variable.

3. ~~**Orphan Tailwind colors** `background-light` / `background-dark`.~~ **Resolved 21-T02:** deleted from config; `bg-background` is the only surface root.

4. ~~**Chart palette duplication** (`--chart-1..5` vs `--chart-c1..c8`).~~ **Resolved 21-T02:** old alias block deleted; `--chart-c1..c8` is the single source.

5. ~~**Palette is emerald, not terracotta.**~~ **Resolved 21-T05 (2026-04-24):** `:root` and `.dark` in [index.css](../frontend/src/index.css) replaced wholesale with the Ember light/dark blocks above. Added `--primary-hover`, `--surface-raised`, `--color-warning`. The four utility-level hardcoded emerald references (`.card-interactive:hover` border, `.chip-l2`, `.bg-gain-subtle` / `.bg-loss-subtle`, `.focus-ring`) now bind to tokens via `color-mix` / `var(--surface-raised)` / `var(--foreground)`. Dark-mode chart palette keeps Ember hues at +~0.10 lightness so lines contrast against the charcoal surface — a deliberate departure from the single-table spec above.

6. **327 Tailwind palette-name usages across 24 files** (still open). Primarily `text-slate-400`, `text-emerald-500`, `text-rose-500`, `bg-white dark:bg-slate-900/50`. Sidebar's active-item emerald is a particularly visible case after the Ember swap. **Fix (21-T04-continuation):** page-by-page migration to tokens and primitives.

7. **5 TSX files with hardcoded `oklch(0.52 0.13 155)` literals** (still open). [DashboardPage.tsx:220](../frontend/src/pages/DashboardPage.tsx), [BudgetsPage.tsx:36-54](../frontend/src/pages/BudgetsPage.tsx), [AccountsPage.tsx:233](../frontend/src/pages/AccountsPage.tsx), [AccountsSummaryCard.tsx:43](../frontend/src/components/AccountsSummaryCard.tsx) all embed the old-emerald chart-series color inline. **Fix (21-T04-continuation):** migrate each to `var(--chart-c1)` (or the matching slot).

8. **`font-feature-settings` body mismatch** (still open). DESIGN.md § Typography specifies `"cv11", "ss01"` for Inter; [index.css:126](../frontend/src/index.css) currently sets `"cv02", "cv03", "cv04", "cv11"`. Cosmetic typography drift; fix with the T04-continuation sweep.

## References

- Token source of truth: [frontend/src/index.css](../frontend/src/index.css)
- Tailwind theme bindings: [frontend/tailwind.config.js](../frontend/tailwind.config.js) (contains drift listed above)
- Shadcn config: [frontend/components.json](../frontend/components.json) — style `base-nova`, `lucide` icons, aliases `@/components`, `@/lib`, `@/hooks`, `@/components/ui`
- Stack versions: [frontend/package.json](../frontend/package.json) — React 19, Vite 7, Tauri 2, Tailwind 3.4, Recharts 3.8 (sole chart library as of 21-T04-cont-R)
- Phase 21 roadmap: [docs/ROADMAP.md](ROADMAP.md) § Phase 21
- Typography selection artifact: `.design-variations/typography-20260424-1200/index.html` (variation 14 chosen; `.design-variations/` is gitignored)
- External reference: Google Labs [design.md](https://github.com/google-labs-code/design.md) spec; Ember Studio [palette source](https://designmd.ai/chef/ember-studio)
