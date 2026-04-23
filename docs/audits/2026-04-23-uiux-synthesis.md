# P0 UI/UX Audit — Synthesis

**Date:** 2026-04-23
**Branch:** `audit/p0-uiux-2026-04-23` (off clean `main`)
**Agents:** 10 Explore subagents in parallel (color-tokens, color-contrast, typography-system, spacing-radius-system, alignment-and-rhythm, primitive-bypass, chrome-consistency, chart-system, state-and-feedback, a11y-affordances)
**Raw outputs:** `.audit/uiux-*.json` (10 files; `uiux-chrome.json` and `uiux-color-contrast.json` were reconstructed from agent return summaries after heredoc write failures — noted inline in the files via `_note` field)
**Totals:** ~37 P0 / ~73 P1 / ~16 P2 = ~126 findings

---

## Per-agent counts

| Agent                    | P0 | P1 | P2 | Total | Auto-P0 |
| ------------------------ | -: | -: | -: | ----: | ------: |
| color-tokens             |  4 | 15 |  2 |    21 |       2 |
| color-contrast           |  7 |  3 |  0 |    10 |       1 |
| typography-system        |  0 |  3 |  7 |    10 |       0 |
| spacing-radius-system    |  2 |  3 |  2 |     7 |       2 |
| alignment-and-rhythm     |  0 | 10 |  1 |    11 |       0 |
| primitive-bypass         |  8 |  6 |  1 |    15 |       7 |
| chrome-consistency       |  4 |  6 |  0 |    10 |       4 |
| chart-system             |  0 | 15 |  3 |    18 |       0 |
| state-and-feedback       |  4 | 11 |  0 |    15 |       1 |
| a11y-affordances         |  8 |  1 |  0 |     9 |       7 |
| **Total**                | **37** | **73** | **16** | **126** | **24** |

---

## Hotspots — files flagged by ≥2 agents

Ordered by agent coverage (descending):

| File                                                        | Agents | Which                                                                                                  |
| ----------------------------------------------------------- | -----: | ------------------------------------------------------------------------------------------------------ |
| `frontend/src/components/layout/Header.tsx`                 |      6 | color-tokens, color-contrast, chrome, primitive-bypass, a11y, typography                               |
| `frontend/src/pages/BudgetsPage.tsx`                        |      6 | color-tokens, primitive-bypass, chart, alignment, state-feedback, spacing-radius                       |
| `frontend/src/components/layout/Sidebar.tsx`                |      5 | color-tokens, color-contrast, chrome, a11y, typography                                                 |
| `frontend/src/components/multi-user/ViewSelector.css`       |      4 | color-tokens, color-contrast, chrome, a11y                                                             |
| `frontend/src/pages/AccountsPage.tsx`                       |      4 | alignment, chart, state-feedback, typography                                                           |
| `frontend/src/pages/CashFlowPage.tsx`                       |      3 | primitive-bypass, alignment, state-feedback                                                            |
| `frontend/src/index.css`                                    |      3 | color-tokens, color-contrast, a11y (self-referential on tokens, focus-ring, reduced-motion gate)       |
| `frontend/src/components/CreditScorePopup.tsx`              |      3 | color-tokens, spacing-radius, chart                                                                    |
| `frontend/src/pages/TransactionsPage.tsx`                   |      3 | color-tokens, state-feedback, spacing-radius                                                           |
| `frontend/src/pages/DashboardPage.tsx`                      |      3 | typography, chart, a11y                                                                                |
| `frontend/src/pages/MonthlyReviewPage.tsx`                  |      3 | primitive-bypass, state-feedback, alignment                                                            |
| `frontend/src/components/ToastContainer.tsx`                |      2 | color-contrast, a11y                                                                                   |
| `frontend/src/components/MFAModal.tsx`                      |      2 | spacing-radius, a11y                                                                                   |
| `frontend/src/pages/ReportsPage.tsx`                        |      2 | color-tokens, chart                                                                                    |
| `frontend/src/pages/InvestmentsAllocation.tsx`              |      2 | chart, state-feedback                                                                                  |
| `frontend/src/pages/YearlyWrapUpPage.tsx`                   |      2 | primitive-bypass, state-feedback                                                                       |
| `frontend/src/pages/SettingsPage.tsx`                       |      2 | primitive-bypass, state-feedback                                                                       |
| `frontend/src/components/ErrorBoundary.tsx`                 |      2 | chrome, spacing-radius                                                                                 |

**Chrome dominates.** `Header.tsx`, `Sidebar.tsx`, `ViewSelector.css`, and `ToastContainer.tsx` collectively carry the majority of multi-agent P0s — focus rings, hardcoded palette colors, raw RGB in CSS, missing aria-labels. **BudgetsPage is the content-area hotspot** — primitive-bypass (5 of 8 P0s), chart tooltips, header rhythm, hand-rolled modal.

---

## Top-10 ranked across buckets

| #  | Finding                                                                              | File                                                             | Impact                                                           |
| -: | ------------------------------------------------------------------------------------ | ---------------------------------------------------------------- | ---------------------------------------------------------------- |
|  1 | Dark-mode sidebar active text fails AA (2.12:1)                                      | `frontend/src/index.css:120`                                     | Token-level contrast failure; visible regression dark mode      |
|  2 | Dark-mode muted-foreground fails AA on card (2.21:1)                                 | `frontend/src/index.css:84`                                      | Secondary text unreadable on dark card surfaces                 |
|  3 | Header search + chrome buttons missing `focus-visible` ring                          | `frontend/src/components/layout/Header.tsx:93,109,136`           | Keyboard nav invisible on every chrome button                   |
|  4 | ViewSelector.css uses raw RGB + hardcoded emerald for every surface                  | `frontend/src/components/multi-user/ViewSelector.css:10-66`      | Sole non-tokenized chrome surface; inconsistent across themes   |
|  5 | Toast close button lacks `aria-label` + focus ring                                   | `frontend/src/components/ToastContainer.tsx:47`                  | Screen-reader invisible; can't dismiss via keyboard             |
|  6 | BudgetsPage: 5 hand-rolled buttons sitting next to other Button usage                | `frontend/src/pages/BudgetsPage.tsx:194,204,211,518,519`         | Most egregious primitive-bypass concentration in the app        |
|  7 | `rounded-2xl` (16px) drifts past tokenized `--radius` (12px) on modals               | `frontend/src/components/CreditScorePopup.tsx:206`, `MFAModal.tsx:122` | Modal corner-radius diverges from card siblings              |
|  8 | BudgetsPage mutation error only logged to console                                    | `frontend/src/pages/BudgetsPage.tsx:106`                         | Silent save failure — user sees no feedback                     |
|  9 | Sidebar active-nav hardcoded emerald classes                                         | `frontend/src/components/layout/Sidebar.tsx:54`                  | Breaks sidebar-primary/accent token path; 3.61:1 contrast       |
| 10 | 200+ `text-[Xpx]` arbitrary sizes bypass scale across 15+ files                      | various (typography)                                              | System drift; long-term unmaintainable typography               |

---

## Complete P0 inventory (autonomous-eligible in bold)

### Chrome — focus-ring and aria-label additions (Phase A — lowest risk)

| # | Agent | File:Line | Title | Conf | Elig |
|---|---|---|---|---|---|
|  1 | a11y | `Sidebar.tsx:27` | Sidebar collapse button missing focus-ring | 0.99 | **true** |
|  2 | a11y | `Header.tsx:109` | Header Refresh button missing focus-ring | 0.99 | **true** |
|  3 | a11y | `Header.tsx:136` | Header Notifications button missing focus-ring | 0.99 | **true** |
|  4 | a11y | `ToastContainer.tsx:47` | Toast close missing aria-label + focus-ring | 0.98 | **true** |
|  5 | a11y | `MFAModal.tsx:212` | MFAModal Cancel missing focus-ring | 0.99 | **true** |
|  6 | a11y | `MFAModal.tsx:222` | MFAModal Submit missing focus-ring | 0.99 | **true** |
|  7 | a11y | `ViewSelector.css:21` | Pill buttons lack `:focus-visible` CSS rule | 0.98 | **true** |

### Chrome — hardcoded color swaps (Phase B)

| # | Agent | File:Line | Title | Conf | Elig |
|---|---|---|---|---|---|
|  8 | color-tokens | `Header.tsx:67` | `bg-white/80 dark:bg-[#060608]/90` hardcoded | 0.98 | **true** |
|  9 | color-tokens | `Sidebar.tsx:24` | `bg-white dark:bg-[#060608]` hardcoded | 0.98 | **true** |

### Radius — rounded-2xl drift (Phase C)

| # | Agent | File:Line | Title | Conf | Elig |
|---|---|---|---|---|---|
| 10 | spacing-radius | `CreditScorePopup.tsx:206` | `rounded-2xl` on popup card | 0.99 | **true** |
| 11 | spacing-radius | `MFAModal.tsx:122` | `rounded-2xl` on MFA modal | 0.99 | **true** |

### State/Feedback — toast error (Phase D)

| # | Agent | File:Line | Title | Conf | Elig |
|---|---|---|---|---|---|
| 12 | state-feedback | `BudgetsPage.tsx:106` | Mutation error only logged (`toast` already imported) | 0.95 | **true** |

### Primitive bypass — Button swaps (Phase E — higher risk)

| # | Agent | File:Line | Title | Conf | Elig |
|---|---|---|---|---|---|
| 13 | primitive-bypass | `BudgetsPage.tsx:194` | Month nav → `<Button variant="ghost" size="icon">` | 0.95 | **true** |
| 14 | primitive-bypass | `BudgetsPage.tsx:204` | Configure → `<Button variant="outline">` | 0.95 | **true** |
| 15 | primitive-bypass | `BudgetsPage.tsx:211` | New Budget → `<Button>` | 0.95 | **true** |
| 16 | primitive-bypass | `BudgetsPage.tsx:518` | Create Budget → `<Button>` | 0.95 | **true** |
| 17 | primitive-bypass | `BudgetsPage.tsx:519` | Cancel → `<Button variant="outline">` | 0.95 | **true** |
| 18 | primitive-bypass | `CashFlowPage.tsx:331` | Reset → `<Button variant="outline" size="sm">` | 0.95 | **true** |
| 19 | primitive-bypass | `CashFlowPage.tsx:337` | Apply → `<Button size="sm">` | 0.95 | **true** |
| 20 | primitive-bypass | `Header.tsx:136` | Notifications → `<Button variant="ghost" size="icon">` | 0.95 | **true** |

### P0 findings deferred (autonomous-ineligible)

| Agent | File:Line | Title | Reason |
|---|---|---|---|
| color-contrast | `index.css:120` | Sidebar active text 2.12:1 (dark) | TOKEN_DEF |
| color-contrast | `index.css:84` | muted-foreground 2.19:1 (dark) | TOKEN_DEF |
| color-contrast | `index.css:98` | --color-gain 2.8:1 (dark) | TOKEN_DEF |
| color-contrast | `index.css:236` | .chip-l2 text 3.88:1 (dark) | TOKEN_DEF |
| color-contrast | `Header.tsx / ViewSelector.css` | text-emerald-500 / active pill contrast 2.54:1 | CHROME_RESTRUCTURE |
| color-tokens | `ViewSelector.css:10,55` | Raw RGB for every surface + hardcoded emerald | CHROME_RESTRUCTURE |
| color-tokens | `ReportsPage.tsx:66` | Sankey hex palette | TOKEN_DEF |
| color-tokens | `TransactionsPage.tsx:50`, `BudgetsPage.tsx:33` | Inline OKLch literals in TSX | TOKEN_DEF |
| chrome | `Header.tsx:67`, `Sidebar.tsx:24` | Arbitrary #060608 dark-bg hex | CHROME_RESTRUCTURE (duplicate finding — handled by color-tokens Phase B) |
| chrome | `ViewSelector.css:21` | No :focus-visible rule | CHROME_RESTRUCTURE (overlapped with a11y #7 which is executable) |
| primitive-bypass | `BudgetsPage.tsx:485` | Modal should use Sheet primitive | MULTIFILE |
| state-feedback | `CashFlowPage.tsx:536,562`, `TransactionsPage.tsx:247` | Errors swallowed, no user feedback | LOW_CONFIDENCE (UX decision needed on error banner copy / retry UI) |
| a11y | `DashboardPage.tsx:302` | Clickable KPI cards lack keyboard accessibility (6 cards) | MULTIFILE |

---

## Borderline severity calls — worth review next session

These were flagged P0 but could reasonably be downgraded:

- **`ViewSelector.css:21` pill focus-visible** (a11y) — Marked P0 because pills are chrome, but the component is currently not the primary navigation and users don't keyboard-navigate between owners often. **Still executed as P0 this run.**
- **`Sidebar.tsx:27` collapse button focus-ring** (a11y) — P0 for keyboard users; arguable because the button is a toggle for a visual-only feature. **Still executed as P0.**
- **`BudgetsPage.tsx:106` missing toast on mutation error** (state-feedback) — Silent failure on save is arguably P0; however the mutation is optimistic and may not have user-visible effect. Executed because the toast import exists and adding the call is zero-risk.
- **Header/Sidebar `bg-white dark:bg-[#060608]`** (color-tokens) — Marked P0 because `#060608` is an arbitrary hex; however it does work in both themes currently. Borderline — executed because the swap to `bg-background` is safer long-term.
- **The 4 TOKEN_DEF contrast P0s** — These are genuinely P0 visibility failures but require editing `:root`/`.dark` blocks. Human design review needed on whether to raise gain/loss/muted-fg lightness (may shift brand palette).

---

## Execution plan

Next: Phase A → Phase B → Phase C → Phase D → Phase E, one commit per fix, build after each, revert on build failure. Results logged to `docs/audits/2026-04-23-uiux-execution-log.md`.
