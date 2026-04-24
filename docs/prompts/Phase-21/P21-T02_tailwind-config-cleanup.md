# P21-T02: Tailwind config cleanup + typography stack swap

## Context

[docs/DESIGN.md](../../DESIGN.md) landed in P21-T01 as the canonical UI spec. Its **Known Drift** block lists four structural drifts between the spec and the code: Manrope declared but not used (Geist wins at runtime), `--primary` hardcoded as `#11d483` in Tailwind config (breaks dark mode), `background-light`/`background-dark` orphan colors, and duplicate `--chart-1..5` aliases in `index.css`. This task closes those four drifts and swaps the runtime typography stack to the chosen faces (Newsreader display + Inter body + JetBrains Mono numeric) so the app matches the DESIGN.md spec from the Tailwind/CSS layer down. **Color palette stays emerald for now** — the Ember palette swap is P21-T05.

## Starting State

Audit findings across `frontend/src/**` at HEAD:

| Pattern | Hits | Notes |
|---|---|---|
| `bg-background-light` / `bg-background-dark` as Tailwind classes | 0 | Orphans can be dropped cleanly. |
| `text-background-dark` (using the orphan as a text color) | 4 | [TransactionsPage.tsx:763, 983, 1140, 1225](../../../frontend/src/pages/TransactionsPage.tsx) — all on primary-background buttons; correct token is `text-primary-foreground`. |
| `--chart-1..5` usages (not `c1..c5`) | 0 | `index.css:65-69, 111-115` duplicates are dead code. |
| `bg-primary` / `text-primary` / etc. | 88 (6 files) | Benefit from the `var(--primary)` binding — no migration needed, just the config change. |
| Hardcoded `'Geist Variable', Inter, sans-serif` in TSX | 11 | [ReportsPage.tsx](../../../frontend/src/pages/ReportsPage.tsx) Sankey SVG `<text>` elements (lines 715, 721, 874, 884, 961, 1067, 1073, 1087, 1091, 1095, 1099). Migrate to `var(--font-sans)`. |
| Manrope references | 3 | `frontend/index.html:8` Google Fonts `<link>`, `frontend/tailwind.config.js:54-55` `fontFamily` declaration. Both to remove. |
| `stitch_mockup.html` | standalone | Not imported or served; leave alone. |

Package graph:
- `@fontsource-variable/geist` is installed and imported in `index.css:3`. Remove.
- `@fontsource-variable/inter`, `@fontsource-variable/newsreader`, `@fontsource-variable/jetbrains-mono` are all available on fontsource.org and install with the same pattern. Add.

## Task

1. **Swap fontsource dependencies** in [frontend/package.json](../../../frontend/package.json):
   - Remove `@fontsource-variable/geist`
   - Add `@fontsource-variable/inter`, `@fontsource-variable/newsreader`, `@fontsource-variable/jetbrains-mono`
   - Run `npm install` to materialize lockfile.

2. **Rewrite font plumbing** in [frontend/src/index.css](../../../frontend/src/index.css):
   - Line 3: replace `@import "@fontsource-variable/geist";` with three imports for Inter, Newsreader, JetBrains Mono.
   - Line 10: update `--font-sans` to `'Inter Variable', system-ui, -apple-system, sans-serif`.
   - Add `--font-display: 'Newsreader Variable', Georgia, serif;` and `--font-mono: 'JetBrains Mono Variable', ui-monospace, 'SF Mono', monospace;` alongside.
   - Update `.text-numeric` utility (line 187-191) to use `var(--font-mono)` — per DESIGN.md Typography rule, all currency/aligned-numeric columns must use the numeric face.
   - Delete the duplicate `--chart-1..5` block in `:root` (lines 65-69) and in `.dark` (lines 111-115).

3. **Fix Tailwind config** in [frontend/tailwind.config.js](../../../frontend/tailwind.config.js):
   - Replace the `primary: { DEFAULT: "#11d483", foreground: "#ffffff" }` literal with `primary: { DEFAULT: "var(--primary)", foreground: "var(--primary-foreground)" }` so dark mode respects the CSS variable.
   - Remove `"background-light": "#f6f8f7"` and `"background-dark": "#10221a"` — orphan tokens.
   - Replace the `fontFamily: { display: ["Manrope", ...], sans: ["Manrope", ...] }` block with `sans: ["'Inter Variable'", "system-ui", ...]`, `display: ["'Newsreader Variable'", "Georgia", "serif"]`, and `mono: ["'JetBrains Mono Variable'", "ui-monospace", "monospace"]`. This makes existing `font-mono` / `font-display` usages pick up the new faces automatically.

4. **Drop the Manrope CDN link** in [frontend/index.html:8](../../../frontend/index.html). Keep the Material Symbols link below it.

5. **Migrate `text-background-dark` callers** in [TransactionsPage.tsx](../../../frontend/src/pages/TransactionsPage.tsx): replace all 4 occurrences with `text-primary-foreground`.

6. **Migrate hardcoded Geist Variable strings** in [ReportsPage.tsx](../../../frontend/src/pages/ReportsPage.tsx): replace all 11 `"'Geist Variable', Inter, sans-serif"` inline `fontFamily` values with `"var(--font-sans)"`.

7. **Update ROADMAP.md** Phase 21 row — flip T02 to complete in the status column.

## Verification

- `cd frontend && npm install` — completes without lockfile drift.
- `cd frontend && npm run build` — TS + Vite build succeeds, no type errors.
- `cd frontend && npm run dev` — dev server boots; visit Dashboard, Transactions (tap a row to open the edit modal — the button labels must still read white-on-primary, i.e. `text-primary-foreground` works), Reports (Sankey labels must still render with a reasonable sans font).
- Visual grep of computed font on a currency cell: should be `JetBrains Mono Variable` (via `.text-numeric` → `--font-mono`).
- Visual grep of computed font on body text: should be `Inter Variable` (via body → `--font-sans`).
- `grep -r "Manrope" frontend/` returns only `stitch_mockup.html` (standalone).
- `grep -r "Geist Variable" frontend/src/` returns nothing.
- `grep -r "background-light\|background-dark" frontend/src/` returns nothing.
- DESIGN.md Known Drift items 1-4 are no longer true against HEAD.
