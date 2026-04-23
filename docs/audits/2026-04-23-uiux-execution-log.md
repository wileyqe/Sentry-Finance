# P0 UI/UX Audit — Execution Log

**Date:** 2026-04-23
**Branch:** `audit/p0-uiux-2026-04-23` (off clean `main`; 13 commits landed; nothing pushed)
**Synthesis:** [`2026-04-23-uiux-synthesis.md`](./2026-04-23-uiux-synthesis.md)
**Totals:** 13 fixes committed / 0 build failures / 14 P0s deferred (6 from Phase E + 8 from synthesis deferral pool)

---

## Committed fixes

### Phase A — focus-ring + aria-label additions (7 fixes → 6 commits)

| # | Subject | File:Line | Agent | Commit |
|--:|---------|-----------|-------|--------|
|  1 | Sidebar collapse button focus-ring            | `frontend/src/components/layout/Sidebar.tsx:27`           | a11y-affordances   | `a57725f` |
|  2 | Header Refresh button focus-ring              | `frontend/src/components/layout/Header.tsx:109`           | a11y-affordances   | `6d66380` |
|  3 | Header Notifications button focus-ring        | `frontend/src/components/layout/Header.tsx:136`           | a11y-affordances   | `8856a89` |
|  4 | Toast close aria-label + focus-ring           | `frontend/src/components/ToastContainer.tsx:47`           | a11y-affordances   | `45ce8c8` |
|  5–6 | MFAModal Cancel + Submit focus-ring (batched) | `frontend/src/components/MFAModal.tsx:212,222`            | a11y-affordances   | `6d4787e` |
|  7 | ViewSelector pill `:focus-visible` CSS rule   | `frontend/src/components/multi-user/ViewSelector.css:21`  | a11y-affordances   | `fa1c971` |

### Phase B — color-token swaps on chrome surfaces (2 fixes)

| # | Subject | File:Line | Agent | Commit |
|--:|---------|-----------|-------|--------|
|  8 | Header `bg-white/80 dark:bg-[#060608]/90` → `bg-background/80` | `frontend/src/components/layout/Header.tsx:67` | color-tokens | `b0d953b` |
|  9 | Sidebar `bg-white dark:bg-[#060608]` → `bg-background`        | `frontend/src/components/layout/Sidebar.tsx:24` | color-tokens | `5b203d4` |

### Phase C — radius tokenization (2 fixes)

| # | Subject | File:Line | Agent | Commit |
|--:|---------|-----------|-------|--------|
| 10 | CreditScorePopup `rounded-2xl` → `rounded-lg`   | `frontend/src/components/CreditScorePopup.tsx:206` | spacing-radius-system | `3d54fd5` |
| 11 | MFAModal `rounded-2xl` → `rounded-lg`           | `frontend/src/components/MFAModal.tsx:122`         | spacing-radius-system | `f1580ce` |

### Phase D — state/feedback (1 fix)

| # | Subject | File:Line | Agent | Commit |
|--:|---------|-----------|-------|--------|
| 12 | BudgetsPage fetch error → toast + console                           | `frontend/src/pages/BudgetsPage.tsx:106` | state-and-feedback | `604072f` |

### Phase E — primitive-bypass Button swaps (2 of 8 executed)

| # | Subject | File:Line | Agent | Commit |
|--:|---------|-----------|-------|--------|
| 14 | BudgetsPage Configure button → `<Button variant="outline">` (+ Button import) | `frontend/src/pages/BudgetsPage.tsx:207` | primitive-bypass | `18a0247` |
| 17 | BudgetsPage New Budget dialog Cancel → `<Button variant="outline">`           | `frontend/src/pages/BudgetsPage.tsx:522` | primitive-bypass | `19e3c27` |

---

## Build-failed (reverted)

None. All 13 commits built green (`cd frontend && npm run build`) on first or second attempt.

**One transient build-break noted mid-run** (not a reverted finding): Fix 14 initial commit attempted `import { Button } from "@/components/ui/Button"` (capitalized `Button`); repo convention is lowercase `button.tsx`. Fixed in-place before commit — no revert cycle, same finding landed as `18a0247`.

---

## Deferred P0s — picked up by this run but NOT committed

### Phase E remainders (6 findings) — LOW_CONFIDENCE / CHROME_RESTRUCTURE

Agent marked these `autonomous_eligible: true` at 0.95 confidence, but this executor downgraded them during the risk review at the start of Phase E. Reasoning (per finding) below; next session can reassess with visual-regression verification.

<details>
<summary><strong>Fix 13 — BudgetsPage month nav buttons → `<Button variant="ghost" size="icon">` (LOW_CONFIDENCE)</strong></summary>

- **File:Line:** `frontend/src/pages/BudgetsPage.tsx:197,201`
- **Evidence:** Two icon-only buttons with `text-slate-400 hover:text-slate-700` and a `material-symbols-outlined` child.
- **Suggested fix:** `<Button variant="ghost" size="icon"><ChevronLeftIcon /></Button>`
- **Downgrade reason:** Current buttons have no explicit size; `size="icon"` is 32x32 which may not match visual position relative to the month heading. Material Symbols icon vs the suggested `<ChevronLeftIcon />` would also require a swap from the material-symbols-outlined span pattern used elsewhere in the codebase.
</details>

<details>
<summary><strong>Fix 15 — BudgetsPage New Budget button → `<Button>` (LOW_CONFIDENCE)</strong></summary>

- **File:Line:** `frontend/src/pages/BudgetsPage.tsx:214`
- **Evidence:** `className="flex items-center gap-2 px-4 py-2 bg-[var(--color-gain)] text-white rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity"`
- **Suggested fix:** `<Button variant="default">` (which uses `bg-primary`)
- **Downgrade reason:** The current button intentionally uses `var(--color-gain)` (semantic "positive action" green, oklch 0.42 lightness) rather than `var(--primary)` (brand green, 0.52 lightness). The agent's fix would substitute one green for another, but the visual delta is intentional — "add to budget" is a gain action. Revisit only if the design system unifies primary and gain.
</details>

<details>
<summary><strong>Fix 16 — BudgetsPage Create Budget button → `<Button>` (LOW_CONFIDENCE)</strong></summary>

- **File:Line:** `frontend/src/pages/BudgetsPage.tsx:521`
- **Evidence:** `className="flex-1 px-4 py-2.5 bg-slate-900 dark:bg-white text-white dark:text-slate-900 rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity"`
- **Suggested fix:** `<Button>`
- **Downgrade reason:** This button uses an inverse-surface pattern (`bg-slate-900 dark:bg-white`) that doesn't map cleanly to any Button variant. `variant="default"` would substitute brand green; `variant="secondary"` would substitute muted gray; neither preserves the inverse contrast intent. Use the paired fix opportunity to decide: do we want a "solid-inverse" Button variant, or retire the inverse pattern in favor of brand primary? Design decision, not an autonomous edit.
</details>

<details>
<summary><strong>Fix 18 — CashFlowPage Reset filter → `<Button variant="outline" size="sm">` (LOW_CONFIDENCE)</strong></summary>

- **File:Line:** `frontend/src/pages/CashFlowPage.tsx:331`
- **Evidence:** `className="flex-1 h-9 rounded-lg border border-slate-200 dark:border-slate-700 text-sm font-semibold ..."`
- **Suggested fix:** `<Button variant="outline" size="sm" className="flex-1">Reset</Button>`
- **Downgrade reason:** Current button is `h-9` (36px); `size="sm"` is `h-7` (28px) and `size="default"` is `h-8` (32px). `size="lg"` is `h-9` but the filter drawer context may expect a smaller action button. Picking the right size is a visual judgment. Would also need the Button import at top of file.
</details>

<details>
<summary><strong>Fix 19 — CashFlowPage Apply filter → `<Button size="sm">` (LOW_CONFIDENCE)</strong></summary>

- **File:Line:** `frontend/src/pages/CashFlowPage.tsx:337`
- **Evidence:** `className="flex-1 h-9 rounded-lg bg-[var(--primary)] text-white text-sm font-semibold hover:opacity-90 transition-opacity"`
- **Suggested fix:** `<Button size="sm">`
- **Downgrade reason:** Same `h-9` vs `h-7/h-8/h-9` sizing question as Fix 18. Pair with Fix 18 when both are executed.
</details>

<details>
<summary><strong>Fix 20 — Header Notifications → `<Button variant="ghost" size="icon">` (CHROME_RESTRUCTURE)</strong></summary>

- **File:Line:** `frontend/src/components/layout/Header.tsx:136`
- **Evidence:** Icon-only chrome button in Header (already received `focus-ring` in Phase A commit `8856a89`).
- **Suggested fix:** `<Button variant="ghost" size="icon">`
- **Downgrade reason:** The button has state-dependent classes (`bg-slate-50 dark:bg-slate-800/60 border ...`) that signal a specific chrome visual distinct from Button's default ghost (which is transparent until hover). Swapping to ghost loses the always-visible "tactile" chrome look. Chrome primitive decisions belong under CHROME_RESTRUCTURE, not an autonomous primitive-extraction. Keep as-is until chrome design system is explicitly reworked.
</details>

### P0s deferred from the synthesis pool (non-executable in this run)

All of these were correctly marked `autonomous_eligible: false` by the source agent. Listed here so a future session can pick them up without re-running agents.

<details>
<summary><strong>TOKEN_DEF — contrast failures requiring `:root`/`.dark` edits (4 findings)</strong></summary>

- `frontend/src/index.css:120` — `--sidebar-primary-foreground` oklch(0.10) on `--sidebar-primary` oklch(0.60) = **2.12:1** in dark mode (AA fail). Fix: raise `.dark` `--sidebar-primary-foreground` to oklch(0.97).
- `frontend/src/index.css:84` — `--muted-foreground` oklch(0.65) on `--muted` oklch(0.22) or `--card` oklch(0.16) = **2.19–2.21:1** in dark mode. Fix: raise `.dark` `--muted-foreground` to oklch(0.75).
- `frontend/src/index.css:98` — `--color-gain` oklch(0.65) on `--card`/`--background` = **2.81–2.82:1** in dark mode. Fix: raise `.dark` `--color-gain` to oklch(0.75 0.14 155).
- `frontend/src/index.css:236` — `.dark .chip-l2` oklch(0.75) on oklch(0.25) = **3.88:1**. Fix: raise the color to oklch(0.85).

All four are single-line token edits under human review — they shift brand palette perceptually and should not be bot-applied.
</details>

<details>
<summary><strong>CHROME_RESTRUCTURE — ViewSelector.css system swap (1 structural finding)</strong></summary>

- `frontend/src/components/multi-user/ViewSelector.css` — every surface (lines 10, 13, 17, 18, 29, 38, 42-44, 47-50, 55-58, 61-66) uses raw RGB instead of tokens, and the active pill hardcodes emerald-500 instead of `var(--primary)`. A full pass would either (a) move the file to Tailwind classes against tokens, or (b) keep it CSS-module but replace every rgb() with `var(--token)`. Structural work — one human-reviewed commit.
</details>

<details>
<summary><strong>PRIMITIVE_NEW — no existing Card primitive (1 recurring pattern)</strong></summary>

- Pattern `bg-white dark:bg-slate-900 rounded-xl shadow-*` appears in multiple places (CreditScorePopup, BudgetsPage new-budget modal, Header notifications popover, etc.). No Card primitive exists yet — `.card-l1` is a utility class, not a component. Recommend extracting `<Card>` in a separate session with variant props for elevation and interactivity. Out of this audit's scope.
</details>

<details>
<summary><strong>LOW_CONFIDENCE — UX-decision state/feedback (3 findings)</strong></summary>

- `frontend/src/pages/CashFlowPage.tsx:536,562` — chart + detail fetches silently swallow errors. Fix requires choosing an error UX (toast only, inline banner, retry button, etc.).
- `frontend/src/pages/TransactionsPage.tsx:247` — recurring-merchants fetch silently fails. Same UX decision.
- (BudgetsPage fetch error — handled in Fix 12 above using the toast approach.)
</details>

<details>
<summary><strong>MULTIFILE — spanning &gt; 3 files (2 findings)</strong></summary>

- `DashboardPage.tsx` — 6 clickable KPI `<motion.div>` elements with `onClick` but no keyboard handler. Consistent keyboard-accessibility shim across all 6 is a single coordinated change.
- `BudgetsPage.tsx:485` — New Budget modal is a one-off hand-rolled overlay that should use `<Sheet>` primitive; fix also touches any other modal that duplicates the pattern.
</details>

---

## Footer

- **Elapsed time:** ~60 minutes start-to-finish (10 agents in parallel for ~4 min on the slowest, then synthesis + 13 build-verify-commit cycles)
- **`commits_landed`:** 13
- **`build_failures`:** 0
- **`deferred_count`:** 14 (6 Phase E re-downgrades + 8 from original synthesis pool)
- **Scheduled task cleanup:** *not performed* — user will handle separately per the prompt template's standing instruction.
- **Branch left as-is on `audit/p0-uiux-2026-04-23`**, 38 commits ahead of `main` before audit + 13 new commits = branch is 51 commits ahead of `origin/main`. Not pushed. User decides whether to merge to `main` or squash-land.
