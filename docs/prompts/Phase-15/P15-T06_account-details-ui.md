# P15-T06: Account Details UI subsection

## Context

Phase 15's T03 / T03b / T04 / T05 tasks dramatically expanded the
**capture** surface for per-account detail fields — NFCU + Chase
connectors now scrape ~50 distinct fields into `loan_details` (APR,
APY, credit limits, minimum payment, due dates, rewards points,
14-day payoff, collateral, VIN, GAP flag, etc.), and v30 added
`apy_history` as a proper time-series with invariants. **But none of
it was visible in the UI.** The Accounts page rendered balance +
institution + (sometimes) APR chip + rewards chip, and that was it.

T06 closes that loop: a per-account **inline expand** Details panel
on the Accounts page that surfaces every scraped field plus the
latest APY row in a consistent, type-aware layout. UI surfacing of
the capture work was explicitly deferred to this task by the T04
Phase B prompt ("UI surfacing deferred to T06").

## Starting State

**Backend:**
- `/api/accounts/{account_id}/details` handler in
  [backend/routers/reports.py:95][reports.py] returned only
  `loan_details` as `{field_name: {value, as_of}}`; `apy_history` was
  **not** joined, so any UI consumer saw stale APY (pre-v30) or
  missing APY (post-v30 reroute).
- `dal/apy_history.py` already exposed
  `get_latest_apy(conn, account_id) -> dict | None` from P15-T04
  Phase B; no DAL changes needed.
- Loan-details fields were written by
  `record_loan_details` + intercepted APY routed through
  `record_apy_history` (T04 Phase B; result_writer choke point).

**Frontend:**
- `AccountsPage.tsx` rendered one row per account inside collapsible
  group sections (Credit cards / Loans / Cash / Real Estate /
  Vehicles / Investments). Each row's entire surface was clickable
  (`onClick={handleAccountClick}`) — manual assets opened the
  `ManualAssetEditModal`, investments routed to `/investments`,
  everything else routed to `/transactions?account_id=...`.
- No detail panel, accordion primitive, or inline expand existed on
  the page. The only per-item detail surface in the codebase was
  `CreditScorePopup.tsx` — a portal-rendered modal, too heavy for
  per-row scraped-field rendering.
- `<Card>` primitive was recently added (commit `0bd133b`); used on
  the page for group shells via `card-l1`.
- The `feat/manual-assets-home-vehicle-equity` PR (merged to `main`
  as commit `b14c1aa`) added a "Details" toggle pattern on the
  Dashboard Net Worth KPI card — that commit's approach (inline
  expand + `stopPropagation` so the underlying card click still
  navigates) was the nearest-precedent reference.

**Seeded test data (deterministic, end_date=2026-01-15):**
- `summit_cc` → 7 loan_details fields (credit card).
- `summit_chk` → 5 loan_details fields + 1 apy_history row.
- `summit_sav` → 4 loan_details fields + 1 apy_history row.
- `summit_mtg` → 12 loan_details fields (`type='loan'`).
- `coastal_*`, `brighton_sav`, investment accounts → no details.

## Task

1. **Extend the handler** in
   [backend/routers/reports.py:95][reports.py] to call
   `dal.apy_history.get_latest_apy` alongside the existing
   `loan_details` query and return a new `apy_latest` key. Shape:
   `{apy_rate: float, as_of: ISO-date, source: str} | None`. This is
   finishing an incomplete handler that predates `apy_history`, not
   "new backend."
2. **Add `tests/test_accounts_details_endpoint.py`** — 5 unit tests:
   loan_details + apy merge, loan_details only, apy only, empty both,
   dedup keeps newest loan_details row. Uses a temp sqlite DB plus a
   `monkeypatch`-redirected `get_db` so the handler can be called
   directly without spinning up FastAPI.
3. **Create `frontend/src/lib/formatDetailField.ts`** — a
   single-file field-formatting utility. Maps ~25 known field names
   to one of 7 kinds (currency / percent / date / count / boolean /
   months / text). Key helpers:
   - `formatDetailField(fieldName, rawValue) -> string | null` —
     returns null when the value is empty, unparseable, or matches a
     garbage heuristic (`/\bas of\b/i` for Chase subtitle bleed).
     Null tells the caller to hide the row entirely.
   - `parseDetailDate(raw)` — handles both ISO
     (`2026-04-20T10:00:00`) and MM/DD/YYYY (portal) shapes.
   - `formatDetailDate(raw)` + `formatPercent(n)` + `fieldLabel(k)`.
4. **Create
   `frontend/src/components/accounts/AccountDetailsPanel.tsx`** — a
   self-fetching panel component. Props: `{accountId, accountType,
   open}`. Internally calls `useOwnerApi('/api/accounts/{id}/details',
   {skip: !open})` — fetches only once per account, suppressed while
   collapsed. Dispatches on `accountType` to one of three ordered
   field lists (DEPOSIT_ORDER, CREDIT_CARD_ORDER, LOAN_ORDER); an
   unknown type falls back to alphabetical. Renders:
   - APY hero row (only when `apy_latest != null`), showing
     `apy_rate` + formatted `as_of` + `source`.
   - Two-column responsive grid of label/value pairs — 18px label,
     tabular-nums value, `font-mono` for VIN.
   - Panel footer with "Scraped {oldest as_of}".
   - Loading / error / empty-state variants for the three non-data
     cases.
5. **Wire the toggle in
   [frontend/src/pages/AccountsPage.tsx][acctpage]:**
   - New `expandedDetails` session-persisted state
     (`useSessionState('accounts:expandedDetails', {})`).
   - Inside each account row, add a "Details" chip button right
     before the trailing `chevron_right`. `stopPropagation` on click
     so the underlying row-body click still navigates. Matches the
     Dashboard NW toggle's visual language (`unfold_more` icon,
     rounded-full background, focus-ring).
   - Conditional `hasDetailsToggle` — skip for manual assets
     (`account._manualKind`) and investment/retirement accounts
     (`account.type === 'investment' || 'retirement'`).
   - Split the clickable row into (a) an outer wrapper div (hover
     bg) containing (b) an inner clickable div (navigation) and (c)
     the `<AccountDetailsPanel>` rendered below. The panel is always
     mounted so the `skip: !open` pattern on the fetch hook works
     lazily.
6. **Prompt file + ROADMAP updates** — this file; flip P15-T06 to
   `[v]`; add P15-T07/T08/T09 under Phase 15 `[ ]`; add two backlog
   entries (endpoint-file move + UI/UX audit pointer).

### Deferred — tracked on ROADMAP (not in T06)

- **APY history chart** (P15-T07). Time-series from `get_apy_history`
  rendered as a sparkline on the panel.
- **Manual-asset details subsection** (P15-T08). Extend the pattern
  to home + vehicle rows, joining scraped NFCU mortgage / auto-loan
  fields via `linked_loan_id`.
- **Investment detail scraping** (P15-T09). Fidelity SEC yield, TSP
  fund YTD, Acorns contribution summary — populates the
  investment-kind layout T06 leaves empty.
- **Endpoint-file move** (backlog). Handler currently lives in
  `reports.py` with inline SQL; DAL-routed relocation to
  `accounts.py` is CLAUDE.md-guardrail cleanup.
- **UI/UX P0 audit pointer** (backlog). Pointer from ROADMAP to
  `docs/audits/2026-04-23-uiux-execution-log.md` so the 14 deferred
  P0s are findable from the main status doc.

## Verification

- `pytest tests/test_accounts_details_endpoint.py -v` → 5/5 pass.
- `pytest tests/ -x --tb=short` → full suite green (baseline ≥345).
- `cd frontend && npm run build` → green.
- `python scripts/pii_scan.py --all-tracked` → clean.
- **Dev-server walkthrough** on seeded DB, Quintin view:
  - `summit_cc` (credit card) → 7 rendered rows (Payment Due, 14-Day
    Payoff, YTD Interest, Rewards 8,450 pts, Cash Advance Limit,
    Cash Advance Available, Date Opened).
  - `summit_chk` (checking) → APY hero (0.06% as of Apr 15, 2026 ·
    scrape) + 5 rows (Available Balance, Dividends YTD, Last Year
    Dividends, Direct Deposit Yes, Date Opened).
  - `summit_mtg` (loan type, mortgage shape) → 12 rendered rows
    (Interest Rate, Payoff Today, 14-Day Payoff, Minimum Payment,
    Purchase Price, Term, Payments Made, Escrow Balance, YTD
    Interest, Collateral, Date Opened, Originated).
  - Row-body click on Summit Visa Platinum → `/transactions?account_id=summit_cc`
    (stopPropagation preserves underlying navigation).
  - Investment rows (Acorns Synthetic, Fidelity Brokerage
    (Investments), TSP Uniformed Services) + manual-asset rows
    (Primary Residence, 2021 Toyota RAV4) → **no** Details toggle
    rendered.
  - Amy view → zero account rows, zero Details toggles (empty-state
    harness).

## Outcomes

- **Type dispatch:** the seeded mortgage account has `type='loan'`,
  not `'mortgage'`. Rather than rely on string matching (the portal
  `collateral_type` field would work but is unreliable), the
  mortgage + auto-loan layouts were unified into a single
  `LOAN_ORDER`. The hide-if-missing rule naturally drops
  escrow/purchase_price/term_months for autos and vin/gap_flag for
  mortgages. Simpler, more robust, and mirrors how the DB actually
  stores the data.
- **Self-fetching panel:** moved the fetch from `AccountsPage.tsx`
  into `AccountDetailsPanel` itself. Per-row `useOwnerApi` with
  `{skip: !open}` gives each panel independent loading state + free
  refetch-on-reopen without wiring a parent-level cache map. Matches
  the CreditScorePopup's conditional-fetch pattern.
- **Fidelity Brokerage (Cash) synthesis quirk:** the AccountsPage
  splits high-balance investment accounts into a synthesized
  "Investments" row + a "Cash" row. The Cash row gets a Details
  toggle (type `savings`) even though the underlying account is an
  investment with no scraped fields — it renders the "No scraped
  details yet" empty state. Accepted as-is; the synthesized row's
  `_originalId` routes the fetch to the real investment account,
  which correctly has no loan_details.
- **Vite HMR warnings pre-existing:** the HMR error log pre-existed
  this task (cached reload failures for BudgetsPage, card.tsx,
  ManualAssetEditModal — not caused by T06). `npm run build`
  verifies the actual source state.
- **Screenshot automation flaked** (preview_screenshot timed out
  twice despite a responsive page). End-to-end verification was
  done via `preview_eval` DOM snapshots — all six verification
  checks above were confirmed through DOM content, not pixels.

[reports.py]: /backend/routers/reports.py
[acctpage]: /frontend/src/pages/AccountsPage.tsx
