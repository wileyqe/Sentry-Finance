# Sentry Finance --- Development Roadmap

> **Status tracking document.** Pick the next task from **Next Up**;
> open the matching `docs/prompts/<Phase-N>/` folder when a summary
> below isn't enough. Closed phases live in
> [`ROADMAP_ARCHIVE.md`](ROADMAP_ARCHIVE.md).
>
> Last updated: 2026-04-26 (P15-T09 investment detail scraping shipped
> 2026-04-26; P16-T03 SSE push + topic registry shipped 2026-04-25;
> ARCHITECTURE/CLAUDE/ROADMAP doc slim 2026-04-26.)

## Status Key

- `[ ]` --- Planned (not started)
- `[->]` --- In progress
- `[~]` --- Phase partially done (some tasks `[v]`, others open)
- `[v]` --- Complete (verified)
- `[!]` --- Needs revision

## Session Handoff

See `CLAUDE.md > Read Order`. This file is step 2: scan **Next Up**
below, pick a task, then open its prompt file. The Phase Overview
and dependency graph are reference; completed phase detail lives in
the archive.

---

## Next Up

The actionable open items, ordered by their position in the trust-bar
sequence. Pick from this list before opening a phase block.

**Trust-bar critical path** (gates Phase 19+):

1. `[ ]` **P17 myPay browser connector** *(Phase 17)* --- closes the
   last manual-drop institution. Email-OTP capture is the open
   design question. Most-leveraged single-user-trust task remaining.
2. `[ ]` **P17 destructive data-wipe tooling** *(Phase 17)* ---
   `scripts/wipe_data.py` for the dummy → real cutover. **Open
   question for user:** is this necessary, or should the seeder
   path be retained for ongoing dev work? Decide before building.
3. ~~`[ ]` **P15-T09 Investment detail scraping**~~ — **Done 2026-04-26.**
   See Phase 15 block below.

**Cosmetic / mechanical (small, parallelizable):**

4. `[ ]` **NFCU auto-loan VIN capture** *(Scraper Backlog)* ---
   adds VIN to `field_patterns`; lets connectors auto-link
   asset → loan and removes the hand-wired seed link.
5. `[ ]` **RefreshBanner topic-name drift** *(post-P16)* ---
   banner listens for events the orchestrator never emits. Either
   delete `RefreshBanner.tsx` or rewire to the `SSE_TOPICS` registry.
6. `[ ]` **T04-cont-O/S/T/U** *(Phase 21 leftovers)* --- new logo
   asset, Sankey 12-slot palette, bucket shade collapse review,
   TransactionLogo border tokenization. All small, all cosmetic.

**Triggered backlog (don't bundle with unrelated work):**

7. `[ ]` **Move `/api/accounts/{id}/details` to `accounts.py` +
   route through DAL** --- triggered on next unrelated edit to
   `reports.py` or `accounts.py`.
8. `[ ]` **`owner_id` threading for `tax-checklist`** --- needs a
   `v39_document_drops_owner_id` migration; only one residual
   endpoint from the 2026-04-25 numeric audit.
9. `[ ]` **Lineage map ACTION_ITEMS** --- AI-009 / AI-012 /
   AI-020 / AI-021 in `data-lineage/ACTION_ITEMS.md`. Fire when a
   real Acorns / TSP user surfaces.

**Deferred by the user (don't pull without re-confirmation):**

- `[~]` **P15-T01 Mortgage extra-payment simulator** (deferred 2026-04-18)
- `[~]` **P15-T02 TSP switch/stay analysis** (deferred 2026-04-18)
- `[ ]` **P14-T05 Rental property support** (waits on landlord trigger)

**Hard-blocked (don't touch yet):**

- `[ ]` **P18 Cost basis & tax lots** --- needs real broker statements
- `[ ]` **P19 multi-user infra polish** --- post-trust-bar
- `[ ]` **P20 Partner MFA pipeline** --- post-trust-bar

---

## Phase Overview

| Phase | Title | Status | Prompt folder |
|---|---|---|---|
| **0–13** | (Foundation through Investments Rebuild) | `[v]` Archived | [`ROADMAP_ARCHIVE.md`](ROADMAP_ARCHIVE.md) |
| **14** | Dollar Accountability Overhaul | `[~]` A/B/C/D done; E deferred | `docs/prompts/Phase-14/` |
| **15** | Decision Support Features | `[~]` T03/T03b/T04/T05/T06/T07/T08/T09/T10 done; T01/T02 deferred | `docs/prompts/Phase-15/` |
| **16** | Notifications & Active Surveillance | `[v]` T01–T03 complete | `docs/prompts/Phase-16/` |
| **17** | Real-Data Transition Prep | `[~]` T03 done; T01/T02 planned | `docs/prompts/Phase-17/` |
| **18** | Investments — Tax Lots | `[ ]` Blocked on broker statements | (to be authored) |
| **19** | Multi-User Infra Polish | `[ ]` Planned (post hard-line) | (to be authored) |
| **20** | Partner MFA Pipeline | `[ ]` Planned (post hard-line) | `docs/PARTNER_MFA_DESIGN.md` |
| **21** | Design System Consolidation | `[~]` T01–T05 + T04-cont-A–R done; O/S/T/U queued | `docs/prompts/Phase-21/` |

## Forward-Looking Dependency Graph

```
            [Single-User Trust Bar --- all required]

    Phase 14          Phase 15          Phase 16
    Dollar            Decision support  Notification feed
    Accountability    (P15-T09 only)    (DONE)
                          |    |    |
                          v    v    v
                 Phase 17: Real-Data Transition Prep
                 (wipe tooling + myPay connector)
                                |
                                v
                 Phase 18: Investments — Tax Lots
                 (blocked: needs real broker statements)

  ============== HARD LINE — Trust Bar ==============
       App must be production-trustworthy for the
       user's own data/decisions before any partner
       integration work begins.
  =====================================================

                                |
                                v
                 Phase 19: Multi-User Infra Polish
                                |
                                v
                 Phase 20: Partner MFA Pipeline
```

---

## Single-User Trust Bar (Phases 14–18)

The user's bar for declaring the app "done enough for my own
financial data/decisions" before any partner-integration work.
Phases 14/15/16 can be built in parallel; 17 gates the real-data
cutover; 18 is blocked on real broker statements arriving.

### Phase 14: Dollar Accountability Overhaul

**Goal:** Replace the residual "savings" bar in the Sankey with
terminal-fate accounting --- every dollar traced to **Spent**, **Kept
liquid**, or **Kept illiquid**, plus a top-of-page accountability
scorecard reconciling NW change.

**Phase overview:** `docs/prompts/Phase-14/Dollar-Accountability-Overhaul.md`

**Done (A/B/C/D):**

- `[v]` **P14-T01: Gross paycheck on the Sankey (Phase A).** Verified 2026-04-21 · `docs/prompts/Phase-14/P14-T01_gross-paycheck-sankey.md`
- `[v]` **P14-T02: Four terminal buckets (Phase B).** Verified 2026-04-21 · `docs/prompts/Phase-14/P14-T02_four-terminal-buckets.md`
- `[v]` **P14-T02b: Sankey withholding stripes (cosmetic follow-up).** · `docs/prompts/Phase-14/P14-T02b_sankey-withholdings.md`
- `[v]` **P14-T03: Dividends/interest as real income (Phase C).** Migration v34 (`v_investment_contributions` view); `reinvestment_flows` block on `/api/reports/flow`. Verified 2026-04-22 · `docs/prompts/Phase-14/P14-T03_dividends-interest-income.md`
- `[v]` **P14-T04: Accountability scorecard (Phase D).** New `dal/reports.get_accountability` + `dal/accountability_drift.py` (8 detectors); `GET /api/reports/accountability`; YTD 2026 reports 99.34% accounted. Verified 2026-04-22 · `docs/prompts/Phase-14/P14-T04_accountability-scorecard.md`

**Open:**

- `[ ]` **P14-T05: Rental property support (Phase E, deferred).**
  Rental income, rental expenses, per-property accounts, security
  deposits as `STORED_LIQUID`. Triggers when a rental-income
  registry row is added, `real_estate.type='rental'` is set, or a
  per-property account starts receiving recurring rent-shaped
  deposits. Prompt: `docs/prompts/Phase-14/P14-T05_rental-property-support.md`.

### Phase 15: Decision Support Features

**Goal:** Forward-looking "what should I do differently" features.
Items are independent --- pick any order.

**Done (rewards/APY/details panel track):**

- `[v]` **P15-T03: NFCU rewards points tracking.** Pivot column on `/api/accounts`, amber rewards chip on `AccountsPage`. Verified 2026-04-18 · `docs/prompts/Phase-15/P15-T03_nfcu-rewards-points.md`
- `[v]` **P15-T03b: NFCU rewards regex fix.** Live portal renders `"10,142pts Rewards"`; added value-first regex pattern. Verified 2026-04-18 · `docs/prompts/Phase-15/P15-T03b_nfcu-rewards-regex-fix.md`
- `[v]` **P15-T04: NFCU APY tracking + per-account capture audit.** v30 `apy_history` migration, `dal/apy_history.py`, freshness integration, 15 new `field_patterns`, rolling generators. Verified 2026-04-19 · `docs/prompts/Phase-15/P15-T04_apy-history-phase-b.md`
- `[v]` **P15-T05: Chase detail scraping.** Phase A walkthrough flipped Chase account identities; Phase B added `_scrape_account_details` with Chase-local extractor. Verified 2026-04-19 · `docs/prompts/Phase-15/P15-T05_chase-detail-scraping.md`
- `[v]` **P15-T06: Account Details UI subsection.** New `AccountDetailsPanel.tsx` with lazy per-row fetch via `useOwnerApi`; `formatDetailField.ts` 7-kind dispatcher; merges `loan_details` + latest `apy_history`. Verified 2026-04-23 · `docs/prompts/Phase-15/P15-T06_account-details-ui.md`
- `[v]` **P15-T07: APY history sparkline on Details panel.** Inline-SVG `Sparkline` + `apyTrend` helper; 12-month window; asset/liability-aware sentiment color. Verified 2026-04-23 · `docs/prompts/Phase-15/P15-T07_apy-trend-sparkline.md`
- `[v]` **P15-T08: Manual-asset details (home + vehicle).** v35 `vehicle_assets.linked_loan_id`; `ManualAssetDetailsPanel.tsx`; new endpoints `/api/real_estate/{id}/details` + `/api/vehicles/{id}/details`. Verified 2026-04-24 · `docs/prompts/Phase-15/P15-T08_manual-asset-details.md`
- `[v]` **P15-T10: Details panel single source of truth.** Three-PR fix after a VIN PII leak. v36 (`vehicle_assets.vin/gap_insurance`) + v37 (`real_estate.address/purchase_price/purchase_date`); `dal/account_details_composer.py` ensures loan-side and asset-side render from one source; `record_loan_details` denylist + 16 invariant tests. Verified 2026-04-24 · `docs/prompts/Phase-15/P15-T10_details-panel-single-source.md`

**Done (P15-T09 — investment details, 2026-04-26):**

- `[v]` **P15-T09: Investment detail scraping.** v41
  `investment_details` KV table with `(account_id, fund_ticker,
  field_name, field_value, as_of, refresh_run_id)` shape; new
  `dal/investment_details.py` writer/reader; `get_investment_panel_bundle`
  composer that merges loan_details + apy_history for brokerage
  accounts. Type-dispatch in `/api/accounts/{id}/details` routes
  investment / retirement to the new bundle. Three new connector
  parsers (Fidelity SPAXX SEC yield + per-equity YTD; TSP per-fund
  YTD via Angular SPA second pass; Acorns round-ups + per-ETF YTD)
  with regex fixtures pinning each. AccountDetailsPanel investment
  branch replaced — renders APY card (when present) + account-level
  rows + per-fund table with YTD Return / SEC Yield columns.
  Verified 2026-04-26 · `docs/prompts/Phase-15/P15-T09_investment-detail-scraping.md`.

**Deferred by the user 2026-04-18:**

- `[~]` **P15-T01: Mortgage extra-payment simulator.** Project the
  impact of extra principal payments against the existing
  `loan_details` schedule --- months saved, interest saved,
  amortized vs linear.
- `[~]` **P15-T02: TSP switch/stay analysis.** Compare current fund
  allocation vs alternative lifecycle/index allocations using
  historical TSP return series. Builds on the P13 benchmark-price
  infrastructure.

### Scraper Adjustments Backlog

Parking lot for portal-visible fields not yet captured by the
extractor. Will be swept in a single extractor-focused pass once
the list grows.

- `[ ]` **NFCU auto-loan VIN capture.** Surfaced 2026-04-23 during
  P15-T08. Once the VIN scrape lands, connectors can auto-join
  asset → loan; T08's hand-wired seed link becomes redundant.

### Phase 16: Notifications & Active Surveillance --- `[v]` Complete

**Goal:** Replace the dead header bell with a real notification
feed; give Phases 14–15 a place to emit alerts.

- `[v]` **P16-T01: Notification feed foundation.** v38 `notifications`
  table, `dal/notifications.py`, 4-endpoint router, 4 producers
  (alerts, bills, doc nudges, refresh failures), `NotificationPopover.tsx`.
  Verified 2026-04-24 · `docs/prompts/Phase-16/P16-T01_notification-feed-foundation.md`
- `[v]` **P16-T02: APY rate-change + recurring price-mutation producers.**
  `detect_apy_changes()` (5 bp / 25 bp warning split, direction-agnostic);
  `list_all_mutations()` joins recurring_mutations with parent merchant.
  Two new producer steps + `apy_rate_change` / `recurring_price_mutation`
  in `VALID_TYPES`. Verified 2026-04-25 · `docs/prompts/Phase-16/P16-T02_apy-and-recurring-producers.md`
- `[v]` **P16-T03: SSE push for notifications + topic registry.**
  `record_notification` broadcasts on insert; `NotificationPopover`
  swapped 60 s poll for `EventSource`. New `backend/sse_topics.py` +
  `frontend/src/lib/sseTopics.ts` consolidate 12 constants across
  11 emission sites. Verified 2026-04-25 · `docs/prompts/Phase-16/P16-T03_sse-push-and-topic-registry.md`

**Side-discovery (parking lot):**

- `[ ]` **RefreshBanner topic-name drift.** `RefreshBanner.tsx`
  listens for `session_started` / `institution_progress` /
  `session_completed` --- none of which the orchestrator emits.
  Real topics: `state_change`, `institution_started`,
  `institution_complete`, `institution_failed`, `refresh_complete`.
  Either delete the banner or rewire it against `SSE_TOPICS`.

### Phase 17: Real-Data Transition Prep

**Goal:** Make the dummy → real-data cutover safe and seamless.
**Open question:** when the servers start, loading dummy data is
deliberate. What does the fully empty state look like? Is the
synthetic DB shape-equivalent to the real one? Parity there makes
the transition smooth.

**Done:**

- `[v]` **P17-T03: DAL write wrappers for non-transactional tables.**
  New `dal/real_estate.py` + `dal/investments_writes.py` exposing
  `record_real_estate_valuations`, `record_investment_holdings`,
  `record_portfolio_snapshots(_snapshot)`. `record_credit_score` +
  `add_valuation` harmonized to caller-commits + invariant guards.
  All seeder + connector direct-INSERTs routed through wrappers.
  Verified 2026-04-18 · `docs/prompts/Phase-17/P17-T03_dal-write-wrappers.md`

**Open:**

- `[ ]` **Destructive data-wipe tooling.** `scripts/wipe_data.py`
  with explicit confirmation prompt. **User questions before
  building:** Is this necessary? Should we retain the ability to
  quickly re-seed synthetic data for ongoing dev work?
- `[ ]` **myPay browser connector.** Automate the manual RAS PDF
  drop. Feasibility informed by the existing P2-T04 parser. Closes
  the last manual-drop institution. Open issue: email-OTP capture
  --- needs a secure flow for grabbing the OTP from email.

### Phase 18: Investments — Tax Lots

**Goal:** Replace the "Cost basis not available" empty-state
(P11-T05) with real per-lot data once broker statements arrive.

- `[ ]` **Cost basis & tax lots.** Per-institution parsers (Vanguard /
  Fidelity / Schwab / Greenleaf, myPay/TSP pattern), new
  `investment_tax_lots` table `(account_id, ticker, lot_id,
  acquired_date, shares, cost_per_share, cost_basis, currency)`,
  `dal/tax_lots.py`, `/api/investments/holdings` extension with
  optional `tax_lots` array, Holdings-tab lot table (acquired /
  shares / basis / MV / unrealized $/% / ST-vs-LT), post-commit
  reconciliation. **Blocked on real broker statements.** Surfaced
  2026-04-09.

---

## HARD LINE — Trust Bar

```
============================================================
  STOP. Do not begin Phase 19+ work until Phases 14–18 are
  complete and the user has affirmed the app is production-
  trustworthy for their own financial data/decisions.

  The bar: "a fully working app I would be willing to trust
  with my own financial data/decisions." Partner integration
  is not a substitute for this bar — it compounds on top.
============================================================
```

---

## Partner Integration (Phases 19–20, post-hard-line)

### Phase 19: Multi-User Infrastructure Polish

**Goal:** Close the four items deferred from P12-T05 so multi-user
infra is ready for a real second owner before Phase 20.

- `[ ]` **Owner schema source-of-truth: YAML vs DB.**
  `config/owner_config.yaml` seeds `owners` on first init. After a
  Settings rename, YAML lags DB; renames survive re-seeds but a DB
  wipe reverts to YAML. Pick one source of truth before multi-user.
- `[ ]` **Owner ViewSelector --- fully owners-driven slots.**
  `ViewSelector.tsx` pulls labels from `useView().owners` but the
  3-slot layout is hardcoded. Refactor to one chip per owner +
  fixed "Household" chip when owner #3 is added.
- `[ ]` **Owner delete / archive lifecycle.** `update_owner` only
  renames. Cascade strategy non-trivial: block when owner has
  data? soft-archive with `archived_at`? hard-delete with
  reassignment?
- `[ ]` **Owner cosmetic fields (avatar/color).** `OwnerUpdate`
  Pydantic + `update_owner` kwargs already accept `avatar_emoji`,
  `color_hex`, `archived_at` --- but the columns don't exist. Add
  per-field migrations as each is wired into UI.

### Phase 20: Partner MFA Pipeline

**Goal:** Final gate for partner real-data ingestion --- capture
Amy's MFA codes without the laptop needing her phone in person.

- `[ ]` **Partner MFA pipeline.** Tasker on Android → Tailscale
  overlay POST to `/api/mfa/forward`, multi-owner plumbing through
  `mfa_bridge`, per-owner credential namespaces. Full design in
  `docs/PARTNER_MFA_DESIGN.md`. Trigger when Phases 14–19 are done
  and partner banking ingestion is the active phase.

---

## Phase 21: Design System Consolidation --- `[~]` Mostly done

**Goal:** Close the gap between `DESIGN.md` and `frontend/src/**`
so changing a card / chip / palette happens in one file, not N.

**Done:**

- `[v]` **P21-T01: Author DESIGN.md.** Locked token source of truth
  + Known Drift block. Verified 2026-04-23.
- `[v]` **P21-T02: Tailwind config cleanup + typography swap.**
  Removed Manrope/Geist; installed Inter / Newsreader / JetBrains Mono;
  bound `primary` to `var(--primary)`. Verified 2026-04-23 ·
  `docs/prompts/Phase-21/P21-T02_tailwind-config-cleanup.md`
- `[v]` **P21-T03: Build 8 missing primitives.** `<EmptyState>`,
  `<ErrorState>`, `<PageHeader>`, `<SectionHeader>`, `<FilterBar>`,
  `<StatCard>`, `<Chip>`, `<PageShell>`. Verified 2026-04-23 ·
  `docs/prompts/Phase-21/P21-T03_build-primitives.md`
- `[v]` **P21-T04: Migrate pages to primitives.** 4 waves: 10 cards
  → `<Card>`, 5 skeletons → `<Skeleton>`, 2 pages wrapped in
  `<PageShell>`, 2 empty states → `<EmptyState>`. Verified
  2026-04-23 · `docs/prompts/Phase-21/P21-T04_migrate-to-primitives.md`
- `[v]` **P21-T05: Ember palette swap.** `:root` + `.dark`
  replaced with Ember terracotta + amber + warm-cream tokens;
  chart palette rotated to terracotta-anchored 8-hue spread.
  Verified 2026-04-24 · `docs/prompts/Phase-21/P21-T05_ember-palette-swap.md`
- `[v]` **T04-continuation A–R: Emerald / hex / mono / sentiment
  sweep.** Five parallel agents shipped Blocker + High + Medium
  items 2026-04-24: chrome-shell purge (Sidebar/Header/App
  selection), Settings buttons + toggles, Dashboard KPI/freshness
  leaks, Reports Sankey + withholding palette, Recharts tooltip
  tokenization, oklch chart-series literals, SyntheticBadge
  violet → amber, account-group decorative colors, neutral-palette
  bulk sweep (576 hits / 26 files), primary-opacity dark-mode
  audit, `font-mono` → `.text-numeric` (21 sites), sentiment-
  palette migration (85 hits), TransactionLogo hex palette,
  font-feature-settings, focus-ring sweep, MFAModal inline-style
  purge. **Tremor → Recharts migration (T04-cont-R)** removed
  `@tremor/react`; bundle shrank −19% CSS / −36% JS.

**Open (cosmetic leftovers):**

- `[ ]` **T04-cont-O: Logo asset (Low).** `public/logo.png` bakes a
  slate-900 panel + emerald-green mark. Commission a
  cream/terracotta variant; drop the stray
  `border-[color:var(--color-loss)]` 3-px red border.
- `[ ]` **T04-cont-S: Sankey 12-slot palette collision (Low).**
  `SPEND_COLORS` was remapped from 12 hexes to the 8-slot
  `chartColor(i)` cycle, so slots repeat. Either add `--chart-c9..c12`
  or consolidate SPEND categories to 8.
- `[ ]` **T04-cont-T: ReportsPage bucket shade collapse review.**
  Agent 4 collapsed the 2-shade `BUCKET_FILL` / `BUCKET_INK`
  pattern to one semantic token + render-site opacity. If buckets
  look flat on visual QA, restore the 2-shade pattern via new
  `--chart-bucket-*-fill`/`-ink` tokens.
- `[ ]` **T04-cont-U: TransactionLogo border tokenization (Low).**
  Hash-to-color palette migrated to Ember OKLch hues, but border
  styling at line 169 still uses `border-slate-200
  dark:border-slate-700/50 bg-white dark:bg-slate-800`. Migrate
  to `border-border bg-card`.

**Non-palette loose thread:** visual agent observed `/cashflow`,
`/monthly-review`, `/yearly-review` rendering with owner-chip only
and no content below on the running dev server. May be a data-wire
issue, may be pre-existing, may be a navigation-timing artifact.
Worth a 5-minute look before declaring those pages clean.

---

## Backlog (quality / deferred --- triggered, not scheduled)

Items that don't block any phase and fire on a specific trigger.

- `[ ]` **Reconciliation hardening.** `dal/reconciliation.py`
  matches integer-cent amounts in opposite directions within 3
  days. Defer FX-aware matching, multi-day clearing windows >3
  days, and partial/fee-adjusted matches until a real-world miss
  surfaces.
- `[ ]` **Extractor changes touching the sign/direction convention.**
  Phase 10 fixed the analytical layer; connectors flow through
  `upsert_transactions()` and are protected by the invariant
  assertion. Defer until extractors are touched for other reasons.
- `[ ]` **Move `/api/accounts/{id}/details` handler to `accounts.py`
  + route through DAL.** Currently in `backend/routers/reports.py`
  with inline SQL (pre-dates the no-direct-queries guardrail).
  Wrap in `dal/loan_details.py::get_latest_loan_details(conn, account_id)`
  and relocate. Triggered on next unrelated touch to `reports.py`
  or `accounts.py`. Surfaced 2026-04-23 during P15-T06.
- `[ ]` **`owner_id` threading for `tax-checklist` (audit residual).**
  The 2026-04-25 numeric audit found 10 endpoints missing
  `owner_id`; 9 fixed in-session. One remains:
  `GET /api/review/yearly/tax-checklist`. Blocker:
  `document_drops` has no `owner_id` column. Per-owner support
  needs a `v39_document_drops_owner_id` migration plus updating
  each parser's `commit()` to stamp `owner_id`, plus making
  `_EXPECTED_TAX_DOCS` per-owner-aware (Amy doesn't get a myPay
  RAS). `get_attribution_rules` is intentionally exempt
  (household-level config).
- `[ ]` **Track UI/UX P0 audit deferrals (2026-04-23) in ROADMAP.**
  Add a pointer to `docs/audits/2026-04-23-uiux-execution-log.md`
  so the 14 deferred P0s (dark-mode contrast × 4, ViewSelector
  CSS tokenization, Card primitive pattern extraction, BudgetsPage
  Button swaps × 3, CashFlow filter Button swaps × 2, Header
  Notifications chrome restructure, DashboardPage keyboard a11y,
  BudgetsPage Sheet primitive) are findable. One-paragraph
  pointer, not a re-paste.
- `[ ]` **Lineage map: deferred ACTION_ITEMS.**
  `docs/data-lineage/ACTION_ITEMS.md` carries four items needing
  seeder architecture work: AI-009 (CC carrying-balance), AI-012
  (TSP payroll-deduction contributions), AI-020 + AI-021 (v34
  view rewrite for cross-account contribution attribution).
  AI-020/021 + AI-012 share architecture --- tackle together once
  a real Acorns / TSP user surfaces. AI-009 is independent. None
  block any phase.
- `[ ]` **Lineage map: dense-diagram polish.** Per-event diagrams
  use a full crossbar between consumers/derivations and UI
  surfaces, producing dense edge fans (`paycheck.mmd` 4×7 = 28
  edges; `investment_buy.mmd` 7×6 = 42). Mermaid renders fine but
  busy. Refinement: parse `derivations[].fan_out` text in
  `build_diagrams.py` and scope edges by named match. Defer until
  someone finds a dense diagram unreadable.
