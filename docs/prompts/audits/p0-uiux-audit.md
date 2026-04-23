# P0 UI/UX Audit — Prompt Template (Autonomous)

Paste the block below into a fresh Claude Code session (on clean `main`), or
let the registered scheduled task fire it unattended. It dispatches 10
parallel audit agents scoped to Sentry Finance's frontend consistency
(color tokens, contrast, typography scale, spacing/radius rhythm,
alignment, primitive reuse, chrome consistency, chart system, state +
feedback patterns, visibility-side a11y), synthesizes findings into
P0/P1/P2 buckets, and lands eligible P0 fixes on a dedicated branch
without pushing. Edit this file rather than editing the prompt inline at
paste time — keeps the template and its history in one place.

Origin: UI/UX twin of `docs/prompts/audits/p0-codebase-audit.md`. The
backend template required human ack between synthesis and execution; this
template runs unattended end-to-end (hence the explicit Autonomous
Execution Mode below). Designed to ground every finding in the existing
design system in `frontend/src/index.css` so the audit normalizes toward
something already in the codebase rather than inventing taste.

---

You are starting a comprehensive UI/UX consistency audit of the Sentry Finance frontend. This is a **frontend-only** audit (`frontend/src/**`) and runs **autonomously** — there is no human in the loop between synthesis and execution. Before dispatching any agents, do these in order; if any pre-flight check fails, stop, and write `docs/audits/{today}-uiux-execution-log.md` explaining the abort.

1. Read `CLAUDE.md`, `frontend/src/index.css` (the token source-of-truth: lines 8–125 define `:root` and `.dark` blocks; lines 176–284 define utilities like `.text-label`, `.card-l1`, `.chip-l2`, `.stat-value`, `.focus-ring`), and `frontend/tailwind.config.js`. These define the design system this audit normalizes toward — every finding must reference one of them.
2. Confirm `main` is clean and synced with `origin/main` per CLAUDE.md's Branch & Worktree Hygiene. Create and switch to `audit/p0-uiux-{today}` off clean `main`. All fix commits land there; nothing pushes.
3. `mkdir -p .audit docs/audits` and confirm `.audit/` is in `.gitignore` (it should be — the backend audit added it on 2026-04-22).

Then **dispatch 10 Explore subagents in parallel**, one per mandate. Each writes `.audit/uiux-<name>.json` using the schema below (Bash heredoc is the established pattern from the backend audit), caps findings at 25 (top-severity only), and ignores `node_modules`, `dist`, `frontend/dist`, `data/`, `.venv/`, `__pycache__`. Scope every grep/read to `frontend/src/**` unless the mandate explicitly targets `frontend/tailwind.config.js`.

**Agent mandates** (scoped to Sentry Finance specifics, not generic lint):

1. **color-tokens** — every color reference outside the token system: hex literals (`#11d483` in `tailwind.config.js` fallback, etc.), named Tailwind colors (`emerald-500`, `slate-200`, `rose-500`, `text-slate-400`, `bg-slate-50`), raw RGB in CSS modules (specifically `frontend/src/components/multi-user/ViewSelector.css`), inline OKLch literals in TSX (e.g., `frontend/src/components/AccountsSummaryCard.tsx`). For each, name the existing CSS variable that should be used (`--primary`, `--card`, `--border`, `--color-gain`, `--color-loss`, `--muted-foreground`, `--ring`, etc.). Bias toward "use existing token" — do NOT propose new tokens unless a clear gap exists; if you do, mark it `PRIMITIVE_NEW` (deferred).

2. **color-contrast** — WCAG AA (4.5:1 for body text, 3:1 for large text and UI components) on text/background pairs in **both** light and dark themes. Compute against the actual OKLch values defined in `index.css` (convert to sRGB for the contrast computation). Specifically check: chrome (sidebar nav inactive text on `--sidebar`, sidebar active text on `--sidebar-primary`, header text on `--background`), semantic value colors (`--color-gain` and `--color-loss` on `--card` and `--background`), chip/badge backgrounds vs text (`.chip-l2`), focus rings vs the surface they sit on, placeholder text on `--input`, `--muted-foreground` on `--muted` and on `--card`.

3. **typography-system** — inventory every `text-*` size class, `text-[Xpx]` arbitrary value, `font-*` weight class, `tracking-*`, and font-family override across `frontend/src/**`. Build the actual typography scale from observation. Flag arbitrary `text-[13.5px]`, `text-[10px]`, `text-[11.5px]` and the like — they should round to the nearest standard step. Flag the **font-family contradiction**: `index.css` `--font-sans` is "Geist Variable" but `tailwind.config.js` declares font family "Manrope". Determine which actually renders and surface the dead-code side. Surface where `.text-label`, `.stat-value`, `.stat-label`, `.text-numeric` (defined in `index.css` utilities) should be used instead of ad-hoc class strings.

4. **spacing-radius-system** — inventory padding/margin/gap (`p-*`, `px-*`, `py-*`, `m-*`, `gap-*`), border radius (`rounded-*` and `var(--radius)`), and border width (`border-*`) usage. Build the actual scales. Flag radius mismatches — e.g., `rounded-lg` vs `rounded-xl` vs `var(--radius)` (which is `0.75rem`) on adjacent surfaces of the same kind. Flag border-width drift in chrome and form controls. Note: the `.card-l1` and `.card-interactive` utilities use `var(--radius)` — places that hand-roll cards with `rounded-xl` should be flagged as utility bypasses.

5. **alignment-and-rhythm** — within a row of sibling cards/sections: card height mismatches (any sibling row using `flex` or `grid` where children differ in implied height), icon vertical centering vs adjacent text baseline, divider thickness/color uniformity (`.divider` utility exists), gap between sibling cards. Across pages: page header spacing pattern (read `Header.tsx` PAGE_META alongside each page's local header to spot drift), section-header pattern (the `.section-header` utility exists at `index.css:262–266` — flag bypass).

6. **primitive-bypass** — **the central concern of this audit.** For each shared primitive in `frontend/src/components/ui/` (Button, Input, Select, Sheet, Table, SyntheticBadge, TransactionLogo) and at the components/ root (`Skeleton.tsx`, `ToastContainer.tsx`): grep for hand-rolled equivalents in `frontend/src/pages/**` and `frontend/src/components/**`. Examples to specifically check:
   - inline `className="...px-4 py-2 bg-white dark:bg-slate-800 border...rounded-lg"` buttons that should use `<Button variant="outline">`;
   - inline `bg-white dark:bg-slate-900 rounded-xl shadow-2xl` cards (no Card primitive exists yet — flag as PRIMITIVE_NEW deferred, not P0);
   - inline `animate-pulse rounded-md bg-slate-200` skeleton divs that should use `<Skeleton>`;
   - any one-off modal pattern that duplicates `MFAModal.tsx` or `Sheet.tsx` shape.

   For each ad-hoc pattern recurring ≥3 times: propose extraction to a new primitive with a suggested file path (mark PRIMITIVE_NEW, deferred). **Bias toward using an existing primitive over creating a new one.** Existing-primitive bypasses are P0/P1; new-primitive proposals are P1/P2 deferred under PRIMITIVE_NEW.

7. **chrome-consistency** — `frontend/src/components/layout/Sidebar.tsx`, `frontend/src/components/layout/Header.tsx`, `frontend/src/components/multi-user/ViewSelector.tsx` + `ViewSelector.css`, `frontend/src/components/RefreshBanner.tsx`, `frontend/src/components/ToastContainer.tsx`, `frontend/src/components/ErrorBoundary.tsx`. For each interactive element: presence of active/hover/focus states, focus ring contrast, keyboard reachability. Hardcoded color audit — Header uses `focus-visible:ring-emerald-500/30` (should be `var(--ring)`-based), ViewSelector.css uses raw RGB and named hex (should be tokens). Light/dark behavior — every chrome surface must respect both themes. **Special attention to `ViewSelector.css`** — it is the only raw CSS module in the app and is an island; it should either move to Tailwind classes against tokens OR continue as a CSS module but use `var(--token)` references. ViewSelector value semantics (`quintin`/`ours`/`amy`) are out of bounds — see CHROME_RESTRUCTURE in deferral codes.

8. **chart-system** — Recharts (3.8.x) and Tremor (3.18.x) coexistence in `frontend/src/pages/**`. Every chart's color source: token (`--chart-c1` through `--chart-c8`, or `--chart-1` through `--chart-5`), Tremor named palette (e.g., `colors={['emerald']}` in DashboardPage), hex literal, or inline `var(--color-*)`. Audit axis color, grid color, tick label size/color, tooltip shape, legend position/style across `DashboardPage`, `ReportsPage`, `CashFlowPage`, `InvestmentsPage`. Sparkline color consistency. Flag pages mixing both libraries on the same screen — pick a winner per page (in the suggested fix, name which library should stay).

9. **state-and-feedback** — for every async data fetch in `frontend/src/pages/**` and `frontend/src/components/**`: does it have loading + empty + error states, and do those states use shared primitives (`Skeleton.tsx`, `ToastContainer.tsx`) or hand-rolled equivalents? Specific check: pages without an error state (the backend audit flagged DashboardPage; verify others). Skeleton variance — count distinct loading-shimmer implementations across the app and identify which ones can collapse onto `<Skeleton>` / `<KpiCardsSkeleton>` / `<ChartSkeleton>` / `<TransactionListSkeleton>`.

10. **a11y-affordances** — visibility-side a11y. Focus rings: present and contrasted on every chrome button (the `.focus-ring` utility exists at `index.css:282–284` — flag bypass). `aria-label` on icon-only chrome buttons (notifications, refresh, close, ViewSelector buttons, Sidebar collapse). Color-only signaling: gain/loss values rendered with only color (no `+`/`−` glyph, no arrow icon, no screen-reader text). `prefers-reduced-motion` respect for `.page-enter`, `.cashflow-trend-line`, and any framer-motion usage. Screen-reader text for status pills (`SyntheticBadge`, freshness pill). **Distinct from the backend audit's `a11y` mandate** — that one was a quick 25-finding sweep biased toward forms; this one is exhaustive on visibility and chrome.

**Finding schema** (strict — each agent emits exactly this):

```json
{
  "agent": "<name>",
  "scanned_paths": ["..."],
  "findings": [
    {
      "severity": "P0|P1|P2",
      "title": "<short>",
      "file": "frontend/src/...",
      "line": 123,
      "evidence": "<=3 lines of code>",
      "why": "<which token/primitive/utility is being bypassed, or which contrast/a11y rule fails>",
      "suggested_fix": "<concrete change — exact replacement string when possible>",
      "confidence": 0.95,
      "autonomous_eligible": true,
      "deferral_reason": null
    }
  ]
}
```

- `confidence` — agent's own self-assessed 0.0–1.0 confidence the finding and the fix are correct.
- `autonomous_eligible` — true iff the fix passes the gate in Autonomous Execution Mode below. The agent makes the call.
- `deferral_reason` — one of `TOKEN_DEF`, `PRIMITIVE_NEW`, `CHROME_RESTRUCTURE`, `MULTIFILE`, `LOW_CONFIDENCE`, `TAILWIND_CONFIG`, or `null`.

**Severity** (enforce strictly; when in doubt, downgrade):

- **P0** — visibly wrong on a shipped page: unreadable text (contrast < AA), invisible focus on a chrome button, dark mode breakage, hand-rolled control that visibly diverges from the primitive sitting next to it on the same page, hardcoded color that breaks in dark mode.
- **P1** — drift from the token / primitive system with latent risk; not visibly wrong today but next change drifts further. Most primitive-extraction opportunities live here.
- **P2** — hygiene / preventive only.

**After agents return — synthesis (autonomous, no ack needed).**

Write `docs/audits/{today}-uiux-synthesis.md` with:

- Header block (branch, agent count, raw-output location, totals).
- Per-agent counts table (P0/P1/P2/Total per agent).
- **Hotspots** — files flagged by ≥2 agents, sorted by count. The backend audit's hotspot pattern surfaced `DashboardPage.tsx` (5 agents) and `result_writer.py` (3 agents); expect similar concentration on the largest pages here (`ReportsPage` 107KB, `TransactionsPage` 66KB, `DashboardPage` 45KB).
- **Top-10 ranked across buckets** — title + `file:line` + one-sentence impact.
- **Complete P0 inventory** — table of every P0 with `file:line`, `confidence`, and `autonomous_eligible` flag.
- **Deferred** — every P0 with `autonomous_eligible: false`, grouped by `deferral_reason`, with the original finding inline so a future session can act on them.
- **Borderline severity calls** — P0s the agents flagged that you would downgrade (mirror the backend audit's "Severity judgment calls worth your review" section). Still execute these as P0 for this run; the section is for next-session triage.

**Autonomous Execution Mode — execute eligible P0s without ack.**

For each P0 with `autonomous_eligible: true`, in order of risk (color-token swaps and `aria-label` adds first; chrome edits next; chart-system changes last), execute this loop:

1. **Apply the fix** to the file(s) named in the finding using the `suggested_fix`.
2. **Run** `cd frontend && npm run build` from the repo root. (Backend untouched, no Python tests.)
3. **If green:** `git add` only the touched files, then `git commit -m "fix(uiux/{agent}): {title}"` with a body that cites `<file>:<line>` from the finding. One commit per fix.
4. **If red:** `git restore` the touched files, append the finding to the execution log under `## Build failed (reverted)` with the build error tail, and continue.

**Eligibility gate** — `autonomous_eligible` is true iff ALL of:

- `confidence >= 0.95`
- Touches ≤ 3 files in the commit
- Uses an existing token / primitive / utility — does NOT define a new one
- Does NOT modify token definitions in `frontend/src/index.css :root` or `.dark` blocks
- Does NOT touch `frontend/tailwind.config.js`
- Does NOT restructure `Sidebar.tsx` nav structure, `Header.tsx` PAGE_META, or `ViewSelector.tsx` value semantics (`quintin`/`ours`/`amy`)
- Is not a primitive-extraction (those go under `PRIMITIVE_NEW`, deferred)

If the gate fails, the agent sets `autonomous_eligible: false` and chooses one of:

- `TOKEN_DEF` — fix would redefine a token (must be human-decided)
- `PRIMITIVE_NEW` — fix would create a new primitive (architectural)
- `CHROME_RESTRUCTURE` — touches Sidebar / Header / ViewSelector structure
- `MULTIFILE` — would need >3 files in one commit
- `LOW_CONFIDENCE` — agent confidence < 0.95
- `TAILWIND_CONFIG` — would touch `frontend/tailwind.config.js`

`BUILD_FAILED` is reserved for the execution log (set by the runtime, not the agent), and indicates the fix was attempted and reverted.

**After all eligible P0s have either committed or been reverted**, write `docs/audits/{today}-uiux-execution-log.md`:

- One section per **committed** fix: subject, file:line, agent, commit hash.
- One section per **build-failed** fix: subject, file:line, agent, build-error tail.
- One section per **deferred** P0: title, file:line, `deferral_reason`, original finding inline.
- Footer: total elapsed time, `commits_landed` count, `build_failures` count, `deferred_count`.

Do NOT push. Do NOT modify `docs/ROADMAP.md`. Do NOT delete the scheduled task that triggered this run — that is a separate cleanup the user will handle.

**Out of scope** (will be skipped even if flagged):

- Taste decisions: changing brand color, swapping fonts, redesigning the sidebar layout, picking a different chart library.
- New features, ROADMAP changes, scope expansion from one finding into "while I'm here" cleanups.
- Cross-page refactors that touch >3 files in one commit (those become `PRIMITIVE_NEW` or `MULTIFILE` deferred findings).
- Backend changes — this audit is `frontend/src/**` only.
- Modifying `frontend/tailwind.config.js`, `index.css :root`, or `index.css .dark` blocks (token-definition layer is human-decided).
- P1 / P2 fixes (next session's scope).
