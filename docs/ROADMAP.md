# Sentry Finance --- Development Roadmap

> **Status tracking document.** Pick the next task from **Next Up**;
> open the matching `docs/prompts/<Phase-N>/` folder when a summary
> below isn't enough. Closed phases live in
> [`ROADMAP_ARCHIVE.md`](ROADMAP_ARCHIVE.md).
>
> Last updated: 2026-04-27 (ACTION_ITEMS triage 2026-04-27 — AI-018
> mis-filed → Resolved; AI-004 product decision closed (Other
> Income); AI-012 + AI-016 superseded to TSP Live Alignment +
> Fidelity Live Alignment backlog entries. P15-T09 investment
> detail scraping shipped 2026-04-26; P16-T03 SSE push + topic
> registry shipped 2026-04-25.)

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

4. ~~`[ ]` **NFCU auto-loan VIN capture**~~ — **Done 2026-04-27.**
   VIN regex was already in `field_patterns`; this run pinned it
   with a fixture, added `dal.vehicles.link_vehicle_to_loan_by_vin`
   for connector-side asset→loan auto-linking, and noted the seed
   cutover as a separate follow-up below.
5. ~~`[ ]` **RefreshBanner topic-name drift**~~ — **Resolved
   2026-04-27 (no-op).** Already fixed in P16-T03. See Phase 16
   side-discovery.
6. `[ ]` **T04-cont-O/S/T** *(Phase 21 leftovers)* --- new logo
   asset, Sankey 12-slot palette, bucket shade collapse review.
   All small, all cosmetic. (T04-cont-U done 2026-04-27.)

**Triggered backlog (don't bundle with unrelated work):**

7. ~~`[ ]` **Move `/api/accounts/{id}/details` to `accounts.py` +
   route through DAL**~~ — **Done 2026-04-27.** Handler relocated
   to `backend/routers/accounts.py`; new `dal/accounts.py` exposes
   `get_account_type` so the dispatch is DAL-only. URL unchanged;
   526-test backend suite green. See Backlog entry below for the
   full record.
8. ~~`[ ]` **`owner_id` threading for `tax-checklist`**~~ — **Done
   2026-04-27.** v42 migration added `document_drops.owner_id`,
   parsers' new `resolve_owner_id` stamps it at commit, and
   `dal.yearly_wrapup.get_expected_tax_docs` filters per-owner.
   See `docs/ROADMAP.md` Backlog entry for the full record.
9. ~~`[ ]` **Lineage map ACTION_ITEMS**~~ --- **Done 2026-04-27.**
   AI-020 + AI-021 closed via migration v43
   (`v_investment_contributions` rewritten to LEFT JOIN on
   `positions_ledger.bank_txn_id = transactions.id`) plus a
   Shape B path in `dal/reports/flow.py` that resolves
   `transfer_flows[]` for brokerage destinations through the
   same canonical link. Sankey now renders a "Transfer →
   investment" ribbon for Acorns + Fidelity contributions;
   accountability scorecard correctly attributes user
   contributions regardless of source shape. AI-009 / AI-004
   closed earlier same day; AI-012 + AI-016 superseded to
   ROADMAP backlog entries (TSP Live Alignment, Fidelity Live
   Alignment). All in-scope action items now resolved.

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

- `[v]` **NFCU auto-loan VIN capture.** Verified 2026-04-27. VIN
  regex pinned in `tests/test_nfcu_extractor.py` (7 fixtures) +
  `dal.vehicles.link_vehicle_to_loan_by_vin` helper added (5
  unit tests in `tests/test_dal_vehicles.py`). Connector wire-up
  to call the helper from a live scrape happens once real NFCU
  auto-loan data lands.
- `[ ]` **Cut `vehicle_assets.linked_loan_id` hand-wired seed link.**
  Once the live NFCU connector has stamped `linked_loan_id` via
  the new `link_vehicle_to_loan_by_vin` helper for at least one
  real scrape, drop the JSON-seeded link from
  `dummy_data/vehicle_assets.json`. Gated on first real-data run.

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

- `[v]` **RefreshBanner topic-name drift.** Reconciliation 2026-04-27:
  the rewire actually landed during P16-T03's 12-constant rollout
  across 11 sites. `RefreshBanner.tsx` already listens for
  `SSE_TOPICS.STATE_CHANGE` / `INSTITUTION_STARTED` /
  `INSTITUTION_COMPLETE` / `INSTITUTION_RETRY` / `INSTITUTION_FAILED` /
  `REFRESH_COMPLETE` / `SESSION_TIMEOUT`. Verified by grep that the
  legacy strings (`session_started`, `institution_progress`,
  `session_completed`) appear nowhere in `frontend/src`. Roadmap
  entry was stale.

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

- `[~]` **T04-cont-O: Logo asset (Low).** Stray
  `border-[3px] border-[color:var(--color-loss)] rounded-none` red
  panel-border on the sidebar `<img>` was dropped from
  `Sidebar.tsx:42` (verified 2026-04-27). The remaining sub-item —
  commission a cream/terracotta logo variant to replace the
  slate-900 + emerald-green PNG at `public/logo.png` — needs a
  designer and stays open.
- `[v]` **T04-cont-S: Sankey 12-slot palette collision.** Added
  `--chart-c9..c12` (rust / sage / mauve / ochre) to both `:root`
  and `.dark` in `index.css`; bumped `chartColor()` modulo from 8
  to 12; reassigned the 4 duplicate `SPEND_COLORS` slots
  (personal/utilities/gifts/health) to the new tokens so the 12
  spend categories render in 12 distinct hues. NW_BUCKET_COLORS
  unaffected (uses fixed `var(--chart-cN)` refs, not the helper).
  `DESIGN.md` palette table extended. Verified 2026-04-27.
- `[v]` **T04-cont-T: ReportsPage bucket shade collapse review.**
  Verified 2026-04-27 (no-op). Reviewed the live Sankey at
  `/reports`. The three bucket nodes render as solid 18-px rects
  in saturated red / teal / green
  (`oklch(0.70 0.20 27)` / `oklch(0.65 0.09 200)` /
  `oklch(0.72 0.16 145)`); the bold "Spent" / "Kept liquid" /
  "Kept illiquid" labels sit 14 px to the right of each rect in
  the matching color, with subtotals beneath in
  `var(--muted-foreground)`. Because the label is positioned
  outside the rect (not stacked), the 2-shade `BUCKET_FILL` /
  `BUCKET_INK` distinction the original pattern provided isn't
  needed — there's no in-rect text contrast problem to solve.
  Render-site opacity is still active for the mortgage mid-node's
  interest/escrow/principal stripes (0.75 / 0.55 / 0.85), and for
  hover dim/lit states (0.20 / 0.55 / 1.00). The collapse holds.
- `[v]` **T04-cont-U: TransactionLogo border tokenization.**
  Swapped `border-slate-200 dark:border-slate-700/50 bg-white
  dark:bg-slate-800` at `TransactionLogo.tsx:188` for
  `border-border bg-card`. Verified 2026-04-27 (25 logos on the
  Transactions page render the new tokens; no slate hex stragglers).

**Non-palette loose thread:** ~~visual agent observed `/cashflow`,
`/monthly-review`, `/yearly-review` rendering with owner-chip only
and no content below.~~ **Resolved 2026-04-27 (no-op).** The agent
guessed at slug-style URL paths that don't exist in the router —
`App.tsx` registers `/cash-flow`, `/review/monthly`,
`/review/yearly` (matching the `Sidebar.tsx` `NAV_LINKS` array),
not the slug variants. Navigating to the wrong URL hits React
Router's "No routes matched location" warning and renders nothing
under the chrome shell, which the agent observed and flagged. All
three pages render full content at their real URLs (CashFlowPage:
"Apr '26" period selector; MonthlyReviewPage: 8 section headings
including Pre-Tax Snapshot, Budget Performance, Subscription
Changes; YearlyWrapUpPage: 8 section headings including Effective
Tax Rate, Income by Stream, Tax Document Checklist). No code
change required.

---

## Backlog (quality / deferred --- triggered, not scheduled)

Items that don't block any phase and fire on a specific trigger.

- `[ ]` **Subscription-vs-utility classification logic.** The
  auto-categorizer treats merchant patterns as either `Utilities`
  or `Dues and Subscriptions`, but the boundary is fuzzy at the
  edges (gym membership, streaming bundles,
  cellphone-with-device-financing, ISP-with-router-rental). User's
  framing: subscriptions can be turned off without impact to daily
  life; utilities cannot. The data-lineage taxonomy adopted that
  test as its source of truth on 2026-04-27 (events.yaml v3,
  PLANET FITNESS reclassification), but the live classifier rules
  in `dal/category_classifications.py` haven't been audited
  against it. Worth a dedicated session — details and nuance
  matter for downstream lifestyle-creep flagging and budget
  targeting. Triggered, not scheduled.
- `[ ]` **Reconciliation hardening.** `dal/reconciliation.py`
  matches integer-cent amounts in opposite directions within 3
  days. Defer FX-aware matching, multi-day clearing windows >3
  days, and partial/fee-adjusted matches until a real-world miss
  surfaces.
- `[ ]` **Extractor changes touching the sign/direction convention.**
  Phase 10 fixed the analytical layer; connectors flow through
  `upsert_transactions()` and are protected by the invariant
  assertion. Defer until extractors are touched for other reasons.
- `[v]` **Move `/api/accounts/{id}/details` handler to `accounts.py`
  + route through DAL.** Verified 2026-04-27. Handler moved from
  `backend/routers/reports.py` to `backend/routers/accounts.py`;
  the only inline SQL (`SELECT type FROM accounts WHERE id = ?`)
  was extracted into a new `dal/accounts.py` with
  `get_account_type(conn, account_id) -> str | None`. URL stayed
  the same so no frontend changes; the test file
  (`tests/test_accounts_details_endpoint.py`) had its import +
  monkeypatch retargeted from `reports as reports_router` to
  `accounts as accounts_router`. Lineage entry in
  `investment_details_snapshot.yaml` repointed to the new file.
  All 526 backend tests pass.
- `[v]` **`owner_id` threading for `tax-checklist` (audit residual).**
  Verified 2026-04-27. v42 migration added
  `document_drops.owner_id` (additive, nullable). Parsers got a
  new `DocumentParser.resolve_owner_id` hook — the five
  primary-scope parsers (`dfas_1099r`, `fidelity_1099`,
  `acorns_1099`, `affirm_1099int`, `mypay_ras`) return the
  configured primary owner; `nfcu_1098` keeps the household
  default (`None`). The router stamps the column on both upload
  and commit. `dal.yearly_wrapup` introduced
  `get_expected_tax_docs(owner_id)` and a per-owner SQL filter
  in `get_tax_doc_checklist`: primary-scope docs match
  `LOWER(owner_id) = ?`, household-scope match `owner_id IS NULL`.
  Endpoint accepts `owner_id` query param;
  `YearlyWrapUpPage.tsx` already passed it. Quintin (primary)
  sees all 5 expected docs; Amy sees only `nfcu_1098`.
  `get_attribution_rules` remains intentionally exempt
  (household-level config).
- `[v]` **UI/UX P0 audit deferrals — pointer to audit log.** The
  2026-04-23 UI/UX audit committed 13 P0 fixes and deferred 14
  others: dark-mode contrast (×4), ViewSelector CSS tokenization,
  Card-primitive pattern extraction, BudgetsPage Button swaps (×3),
  CashFlow filter Button swaps (×2), Header Notifications chrome
  restructure, DashboardPage keyboard a11y, BudgetsPage Sheet
  primitive. Full execution log with per-finding rationale lives
  at `docs/audits/2026-04-23-uiux-execution-log.md`; the synthesis
  document is at `docs/audits/2026-04-23-uiux-synthesis.md`.
  Pulled back into ROADMAP only when one of these surfaces as
  user-blocking in real use. Pointer added 2026-04-27.
- `[v]` **Lineage map: deferred ACTION_ITEMS.**
  `docs/data-lineage/ACTION_ITEMS.md` Open list now empty.
  AI-009 (CC carrying-balance) closed 2026-04-27 via option B (4
  targeted unit tests + 7-file cross-ref sweep + 4-file follow-up
  sweep for AI-018 / AI-019 / AI-035). AI-004 closed 2026-04-27
  (product decision — cashback canonicalises as `Other Income`).
  AI-012 and AI-016 superseded 2026-04-27 to dedicated ROADMAP
  entries below (TSP Live Alignment, Fidelity Live Alignment).
  AI-020 + AI-021 closed 2026-04-27 via migration v43 +
  Shape B path in `dal/reports/flow.py` — the
  `v_investment_contributions` view now joins via
  `positions_ledger.bank_txn_id = transactions.id`, and the
  Sankey resolves brokerage transfers through the same canonical
  link. The "two structural shapes for money flow" framing
  (Shape A paired transactions vs Shape B brokerage ledger
  linkage) is documented in code, tests, and the lineage YAMLs
  for `investment_contribution`, `investment_buy`,
  `investment_implied_buy`, and `investment_link_acorns`. None of
  the resolved items blocked any phase.

- `[ ]` **Fidelity Live Alignment** (supersedes AI-016, filed
  2026-04-27). When the real Fidelity statement parser and/or
  CSV-ingest dividend pipeline ships, dividend rows MUST be
  emitted with `category='Investment Income'` exactly. The
  income source `seed_quintin_fidelity_dividends`
  (`scripts/dummy_data/generator.py:2218-2231`) matches by that
  literal string; alternatives (`Dividend`, `Interest`) silently
  skip and disappear from the Sankey income side. **First step
  when the task runs:** spot-check `scripts/ingest_fidelity_history.py`
  for what category it currently uses on dividend rows it parses
  out of CSV; if it's not `Investment Income`, that's a real bug
  to fix as part of this task. Other files in scope:
  `dal/parsers/fidelity_1099.py` (1099 totals are an independent
  cross-check, not transaction rows), `scripts/dummy_data/generator.py:generate_fidelity_dividends`
  (~1250-1279), the seed registry at lines 2218-2231, and the
  Sankey income wiring in `dal/reports/flow.py` /
  `dal/category_classifications.py`. End state: synthetic and
  live Fidelity dividend rows land on the same income source and
  the Sankey income side stays consistent across data sources.
  Lineage cross-refs: `lineage/equity_dividend.yaml`,
  `lineage/money_market_sweep_interest.yaml`. Trigger: real
  Fidelity statement / CSV dividend ingest path is being touched.

- `[ ]` **TSP Live Alignment** (supersedes AI-012, filed
  2026-04-27). User retired from military service — TSP
  contributions are NOT an event that needs modelling. The
  seeder's "fixed shares, no BUY events, no contribution events"
  shape (`scripts/dummy_data/generator.py::generate_tsp_investment_history`)
  is *correct* for a retired contributor and stays. What matters
  going forward: TSP is a large share of total assets, so
  reallocation events (inter-fund transfers) and per-fund
  performance display are first-class. Audit and correct any
  errant assumptions in the seeder, the post-commit pipeline,
  and `dal/reports/accountability.py::_user_contributions_in_window`
  that still assume ongoing contributions. End state: synthetic
  TSP data shape mirrors what `dal/parsers/tsp_statement.py` (and
  a future inter-fund-transfer parser) would emit; nothing in
  the codebase tries to attribute "user contributed $X to TSP
  this month"; the Sankey does NOT render a labeled cash → TSP
  arrow; the Investments-tab TSP card shows balance + per-fund
  performance. Files in scope:
  `scripts/dummy_data/generator.py::generate_tsp_investment_history`,
  `dal/parsers/tsp_statement.py`,
  `dal/reports/accountability.py::_user_contributions_in_window`,
  `dal/reports/flow.py` Sankey wiring, the Investments tab TSP
  card. Lineage cross-ref: `lineage/tax_bucket_snapshot.yaml`.
  Trigger: TSP balance/allocation/performance UX work, or any
  audit pass over `_user_contributions_in_window`.
- `[v]` **AI-NNN cross-reference doc-coupling gate.** Verified
  2026-04-27. New `scripts/check_action_item_refs.py` blocks
  pre-commit when `docs/data-lineage/ACTION_ITEMS.md` moves an
  AI-NNN between `## Open` and `## Resolved` without staging
  every lineage file (events.yaml + lineage/*.yaml) that
  mentions it. Closed the AI-009 cross-ref drift class — the
  existing `check_freshness.py` only hash-compares generated
  artifacts (inverse-index + diagrams); `check_doc_coupling.py`
  has no rule for ACTION_ITEMS.md changes; so prose drift in
  `notes:` fields slid through silently. Bypass via
  `SKIP_DOCS_CHECK="<reason>"` env var (same hatch as the other
  pre-commit doc checks). Wired into `install_hooks.sh`; the
  hook re-installation note in the script header lists four
  pre-commit checks now (PII, freshness, coupling, AI-refs).
- `[ ]` **Lineage map: dense-diagram polish.** Per-event diagrams
  use a full crossbar between consumers/derivations and UI
  surfaces, producing dense edge fans (`paycheck.mmd` 4×7 = 28
  edges; `investment_buy.mmd` 7×6 = 42). Mermaid renders fine but
  busy. Refinement: parse `derivations[].fan_out` text in
  `build_diagrams.py` and scope edges by named match. Defer until
  someone finds a dense diagram unreadable.
