# Investments Tab — Trust Remediation (Pass 2)

> **Status:** Plan approved. Execution in progress.
> **Follows:** `feat(mvp): Investments + Documents trust audit (M1-M7)` (commit `af9d47b`, 2026-04-08)
> **Scope signed-off:** P0 + P1 + P2 minus the dummy-vs-benchmark gap (ship as-is + doc note) minus real cost-basis parsing (roadmap skeleton only).
> **Date:** 2026-04-09

---

## Context

The M1-M7 investments + documents trust audit landed in commit `af9d47b`. A
follow-up audit on 2026-04-09 (three parallel Explore subagents + live preview
verification via `preview_snapshot`, `preview_network`, `preview_eval`, direct
API fetch) confirmed the architectural shape is sound — owner scoping threads
end-to-end, DAL boundaries are clean, and every number the UI currently shows
reconciles to the cent against the seeded database ($196,100 total portfolio
across 3 Quintin accounts). But the audit also surfaced a cluster of functional
bugs and data-trust gaps that make the tab less trustworthy than it looks.

The guiding rule for this pass: **every number, every label, every chart line
should be either truthful or explicitly absent.** No dead code paths, no
misleading labels, no silent degradation into empty-state placeholders that
look identical to "we have data but can't compute it."

## Starting State (verified live on 2026-04-09)

### Functional bugs

- **YTD is a lie.** `TF_MONTHS['YTD'] = 12` in `InvestmentsPage.tsx:33` →
  `/api/investments/performance?months=12` → backend maps to `period="1y"` →
  the UI displays the 1Y number under the YTD label. Verified: on 2026-04-09
  the YTD card showed `+5.39%` (identical to 1Y), not the expected ~1.4% for
  3 months of seeded data.
- **Dead S&P and Bonds chart lines.** The `Backtested Performance` LineChart
  declares `<Line dataKey="sp500" />` and `<Line dataKey="bonds" />` at
  `InvestmentsPage.tsx:381-382`, but `performanceData` is only ever populated
  with `{date, portfolio}`. The legend implies three lines are drawn; only
  one ever is.
- **Degenerate 1W / 1M / YTD timeframes** show "No snapshots for this
  period / N/A" because the seeded dataset has monthly snapshots, and a
  31-day window catches only a single snapshot (returns need ≥2). Verified
  under Quintin 1M: all four cards N/A. No user-facing "try a longer
  timeframe" hint.
- **Missing React key.** Holdings-table map at `InvestmentsPage.tsx:593-660`
  returns a fragment `<>...</>` with no key. Verified in preview_console_logs:
  `Each child in a list should have a unique "key" prop. Check the render
  method of InvestmentsPage.`
- **Recharts width(-1) height(-1) warning flood.** Verified 25+ warnings per
  navigation in preview_console_logs. Caused the full-screen screenshot tool
  to time out. Root cause: one or more ResponsiveContainer(s) mount inside
  a flex child before the parent has layout measurements (the Allocation tab
  is the most likely culprit — its flex child is missing `min-h-0`, unlike
  the Investments tab charts).

### Data-trust gaps

- **"Sector Allocation" shows asset-class labels.** The backend
  `_KNOWN_SECTORS` dict in `dal/allocation.py` maps VTI → "Diversified",
  VXUS → "International", BND → "Bonds" — these are asset-class-shaped
  strings, not real GICS sectors. The backend already returns the correct
  labels under `by_asset_class`, but the frontend reads `by_sector` and
  labels the chart "Sector Allocation". The two arrays are currently
  identical in value.
- **`ticker_metadata` table is empty.** 0 rows. Allocation survives only
  because `_KNOWN_ASSET_CLASSES` and `_KNOWN_SECTORS` are hardcoded
  fallbacks in `dal/allocation.py`. Any new ticker would land as "Unknown"
  until the first yfinance call succeeded.
- **`*_dec` precision columns are dead weight.** V4 added
  `shares_dec`/`close_price_dec`/`market_value_dec`/`cost_basis_dec` as
  TEXT decimal-precision columns. The seeder's `seed_investment_history()`
  does a raw INSERT at `scripts/seed_dummy_data.py:363-370` and omits
  them; all 288 seeded rows have NULL there. `dal/investments._from_dec_col()`
  silently falls back to the REAL column, so the precision upgrade path is
  never exercised.
- **Orphaned investment accounts.** `acorns_0000` and `fidelity_REDACTED` have
  `owner_id = NULL`, zero holdings, zero transactions, zero snapshots.
  Leftovers from ad-hoc connector scripts (`scripts/ingest_fidelity_history.py`,
  `scripts/parse_acorns_pdf.py`) that inserted placeholder accounts before the
  user wired up the real connector.
- **Dead `past_3m_return` field reads.** `InvestmentsPage.tsx:100` reads
  `h.past_3m_return` from the holdings API response — the field does not
  exist in the response schema. Silently defaults to 0, never rendered.
- **Contributions-vs-Performance math checks out** (Simple Dietz verified
  against API for all 3 accounts); no fix needed.

### Intentionally NOT fixed in this pass (per user call on 2026-04-09)

- **The 27pp portfolio-vs-benchmark gap.** The seeded portfolio uses
  deterministic linear drift (VTI +1.5/mo, VXUS +0.3/mo, BND −0.1/mo)
  while benchmark TWR comes from live yfinance data. This makes the
  demo portfolio appear to underperform the S&P 500 by ~27pp on a 1Y
  view. Mathematically correct but cosmetically misleading. Ship as-is;
  add a one-paragraph note to CLAUDE.md so future sessions know the
  underperformance is a seeding artifact, not a bug.
- **Real cost-basis / tax-lot parsing.** The Holdings table has an
  expandable "Tax Lots" row showing a placeholder because `cost_basis`
  is NULL on all 288 rows. The user wants this as a real feature backed
  by broker-statement parsing, not a demo stub. Roadmap skeleton goes
  into `docs/ROADMAP.md` under Future/Unphased; the placeholder stays
  in place until the real feature lands.

---

## Task

See `.claude/plans/resilient-cuddling-riddle.md` for the full plan. Summary:

### Frontend — `frontend/src/pages/InvestmentsPage.tsx` (7 edits)

1. Replace `TF_MONTHS` with `TF_PERIOD`; send `period=` instead of `months=`.
   YTD → `period=ytd` (backend's `get_portfolio_performance` already handles
   this correctly at `dal/performance.py:385-386`).
2. Delete the two dead `<Line dataKey="sp500" />` and `<Line dataKey="bonds" />`
   declarations. Remove the two corresponding legend chips.
3. Fix the missing React key on the Holdings table fragment by replacing
   `<>...</>` with `<React.Fragment key={h.id}>`.
4. Add `minHeight={1}` to every `ResponsiveContainer` in the file and
   `min-h-0` to the Allocation tab's flex child to match the Investments
   tab pattern.
5. Rename "Sector Allocation" → "Asset Class Allocation" in both occurrences;
   read `by_asset_class` instead of `by_sector`; replace the position-based
   icon map with a content-based map keyed on asset-class label.
6. Add a degenerate-timeframe message and pre-emptively disable the 1W/1M
   buttons (hoverable explanation: "Seeded data has monthly resolution only").
7. Remove the dead `past_3m_return` reads on lines 100 and 843.

### Backend — `backend/routers/investments.py`

8. In the aggregate-path `period_days` lookup (line 59), handle `period=="ytd"`
   explicitly so the combined `monthly_returns` query uses Jan 1 of the
   current year, not 366 days back (the existing `.get("ytd", 366)` fallback
   is the same bug that hit the frontend, at a second site).

### Seeder — `scripts/dummy_data/generator.py` + `scripts/seed_dummy_data.py`

9. Add `_TICKER_METADATA` and `generate_ticker_metadata()` in `generator.py`.
10. Amend `generate_investment_history()` to emit `shares_dec`, `close_price_dec`,
    `market_value_dec` alongside the REAL values.
11. Amend `seed_investment_history()` in `seed_dummy_data.py` to include the
    `*_dec` columns in its INSERT statement.
12. Add `seed_ticker_metadata()` that calls `dal.allocation._upsert_ticker_metadata()`.
13. Add `cleanup_orphaned_investment_accounts()` that deletes investment/retirement
    accounts with `owner_id IS NULL` AND zero holdings AND zero transactions AND
    zero balance_snapshots. Call from `main()` between `init_db()` and the first
    seed step.
14. Wire `seed_ticker_metadata()` into `main()` right after `seed_investment_history()`.

### Tests — `tests/test_investments_trust.py` (append 5)

15. `test_ytd_timeframe_uses_calendar_year_start` — assert YTD window starts
    on Jan 1 of current year, not 366 days back.
16. `test_degenerate_1m_timeframe_returns_empty_monthly_returns` — pin the
    current behavior: `period='1m'` on monthly-frequency seeded data returns
    `monthly_returns=[]`.
17. `test_ticker_metadata_seeded_for_known_tickers` — after seeding, VTI/
    VXUS/BND rows exist with non-Unknown asset_class.
18. `test_holdings_decimal_precision_path` — rows have non-NULL `*_dec`
    columns; `get_latest_holdings()` returns `Decimal` types.
19. `test_orphaned_investment_accounts_cleaned_up_on_seed` — insert a stub
    orphan, call `cleanup_orphaned_investment_accounts()`, assert removal.

### Docs

20. `docs/ROADMAP.md` — add "Cost Basis & Tax Lots (deferred feature)"
    skeleton under Future/Unphased.
21. `CLAUDE.md` — one-paragraph note that seeded portfolio uses deterministic
    drift while benchmarks are real yfinance.
22. This file — fill in Outcomes section after execution.

---

## Verification

### Unit / integration
```bash
pytest tests/test_investments_trust.py -x --tb=short
pytest tests/test_owner_scoping.py -x --tb=short
pytest tests/test_dal.py -x --tb=short
```
Expect: 7 existing + 5 new = 12 passing tests in the trust suite.

### Seeder determinism
```bash
python scripts/seed_dummy_data.py
```
Post-seed sqlite check:
- `SELECT COUNT(*) FROM ticker_metadata` → 3
- `SELECT COUNT(*) FROM accounts WHERE type IN ('investment','retirement') AND owner_id IS NULL` → 0
- `SELECT COUNT(*) FROM investment_holdings WHERE shares_dec IS NOT NULL` → 288

### Live preview (Quintin view)
- 4 performance cards show real TWR values (not N/A) at default 3M
- Click YTD → network request is `?period=ytd&...` (not `?months=12`)
- Click 1M → button is disabled
- Holdings tab → 8 rows, no React key warnings
- Allocation tab → title is "Asset Class Allocation", legend labels
  are "US Equity" / "International Equity" / "Bonds", no recharts
  width(-1) warnings
- Amy view still renders empty state correctly (regression)
- Refresh benchmarks button still works

### Lint
```bash
ruff check backend dal extractors tests
cd frontend && npm run build
```

---

## Execution Notes

- **Backend YTD fix had a hidden dependency.** The frontend change
  (send `period=ytd` instead of `months=12`) reaches two backend code
  paths, not one. `get_portfolio_performance()` at
  `dal/performance.py:385-386` already handled `period="ytd"`
  correctly. But `routers/investments.py:59` — the aggregate-account
  path — had its own `period_days` dict that was missing the `"ytd"`
  key and fell back to `366` days. So without fixing both, benchmark
  cards would show real YTD numbers (from the per-account path) but
  portfolio TWR would still show 1Y data (from the aggregate path).
  The plan caught this; the live verification caught the incomplete
  fix one round earlier than the test would have.
- **Backend needed a manual restart.** The FastAPI dev server in
  `.claude/launch.json` does not have `--reload`, so the YTD fix
  didn't take effect until `preview_stop` + `preview_start`. Vite
  hot-reloads frontend changes automatically; backend changes need
  a full restart. Noted for future work in this codebase.
- **Two dev databases exist.** `data/sentry.db` (default) and
  `data/dummy.db` (what the backend uses per
  `.claude/launch.json`'s `SENTRY_DB_PATH=data/dummy.db` env var).
  Re-seeded against `data/dummy.db` specifically so the running
  backend would see the new `ticker_metadata` rows and `*_dec`
  precision columns.
- **Recharts width(-1) warning suppression was partial.** Added
  `minHeight={1}` to all three `ResponsiveContainer`s and `min-h-0`
  to the Allocation tab's flex child. Inspecting the rendered DOM
  confirmed the fix landed (`style="... min-width: 0px; min-height: 1px;"`)
  and the charts render at correct sizes (e.g. 409×296). But
  recharts still logs the warning during pre-measurement on mount,
  because its warning check fires before the CSS min-height applies.
  Chasing the residual further would require either (a) switching
  to `aspect` prop, which requires a hardcoded aspect ratio, or
  (b) keeping the `ResponsiveContainer` permanently mounted and
  toggling inner content instead of conditionally mounting the
  container. Both are bigger refactors than this pass should take.
- **React key warning: fragment lift fixed it.** Replaced `<>...</>`
  at the `.map()` return with `<Fragment key={h.id}>...</Fragment>`
  (and dropped the now-redundant `key` on the inner `<tr>`). Fresh
  page load with `preview_console_logs` filtered to errors showed
  zero "unique key prop" warnings — confirmed gone.
- **Ruff was not installed on PATH** (`ruff check` → command not
  found), but `python -m ruff check` worked. Found 3 pre-existing
  errors in files I touched: E402 × 2 on `scripts/seed_dummy_data.py`
  (pre-existing `sys.path.insert` pattern) and F401 × 1 on
  `tests/test_investments_trust.py` line 57 (`timedelta` imported
  in the `seeded_db` fixture but never used there). None of these
  were introduced by the changes in this pass — verified with
  `git diff`. Did not fix per "don't refactor beyond scope" rule.
- **YTD live verification math:** Today is 2026-04-09. YTD window
  covers Feb 1, Mar 1, Apr 1 (three portfolio_snapshots, one per
  month). Three returns chained: (1.0047)³ − 1 = 1.4166% ≈ **+1.42%**.
  The UI displayed exactly `+1.42%` after the fix. Before the fix,
  YTD showed +5.39% (identical to 1Y). Benchmark cards also differ
  correctly: YTD S&P = −0.21% vs. 1Y S&P = +36.13%.
- **Asset class allocation live verification:** Allocation tab title
  now reads "Asset Class Allocation" (was "Sector Allocation"). Breakdown
  labels now read "US Equity / International Equity / Bonds" (was
  "Diversified / International / Bonds"). Icons now content-aware
  (VXUS → "public", BND → "savings") instead of position-based.
- **Seeder verification:** After re-run, `ticker_metadata` has 3 rows
  (VTI / VXUS / BND), 0 orphaned investment accounts,
  `SELECT COUNT(*) FROM investment_holdings WHERE shares_dec IS NOT NULL`
  = 288 / 288.
- **Test results:** 12/12 passing in `test_investments_trust.py`
  (7 existing + 5 new). 22/22 passing in `test_owner_scoping.py` +
  `test_dal.py` regression check. Frontend `npm run build` produced
  a clean production bundle (pre-existing chunk-size warning only).

## Outcomes

**What was built:**

- **Frontend (`frontend/src/pages/InvestmentsPage.tsx`, 9 edits):**
  - Replaced `TF_MONTHS` with `TF_PERIOD` sending `period=` instead
    of `months=`
  - Removed two dead `<Line dataKey="sp500"/>` and
    `<Line dataKey="bonds"/>` declarations
  - Removed the two corresponding legend chips
  - Replaced `<>...</>` with `<Fragment key={h.id}>` in Holdings
    table map
  - Added `minHeight={1}` to all three `ResponsiveContainer`s
  - Added `min-h-0` to the Allocation tab flex child
  - Renamed "Sector Allocation" → "Asset Class Allocation" in both
    occurrences
  - Switched allocation fetch from `data.by_sector` to
    `data.by_asset_class`
  - Added `ICON_FOR_ASSET_CLASS` map keyed on asset-class label,
    replacing position-based icon ternary
  - Threaded `perfEmptyReason` state with degenerate-timeframe
    detection ("Not enough snapshots for this timeframe — try 3M
    or longer")
  - Gated 1W and 1M buttons with `DEGENERATE_TFS` set — disabled
    with `title` explaining why
  - Removed two dead `past_3m_return` field reads

- **Backend (`backend/routers/investments.py`):**
  - Added explicit `if period == "ytd"` branch to the aggregate-path
    `monthly_returns` query to anchor `start_date` to Jan 1 of the
    current year instead of falling back to 366 days

- **Seeder (`scripts/dummy_data/generator.py`):**
  - Added `_TICKER_METADATA` dict for VTI/VXUS/BND
  - Added `generate_ticker_metadata()` function
  - Extended `generate_investment_history()` to dual-write `shares_dec`,
    `close_price_dec`, `market_value_dec` alongside the legacy REAL
    columns

- **Seeder (`scripts/seed_dummy_data.py`):**
  - Added `shares_dec` / `close_price_dec` / `market_value_dec` to the
    `INSERT INTO investment_holdings` statement in
    `seed_investment_history()`
  - Added `seed_ticker_metadata(conn)` that reuses
    `dal.allocation._upsert_ticker_metadata()`
  - Added `cleanup_orphaned_investment_accounts(conn)` targeted delete
  - Wired both new functions into `main()`: cleanup before seed inserts,
    `seed_ticker_metadata()` right after `seed_investment_history()`

- **Tests (`tests/test_investments_trust.py`):**
  - Updated `seeded_db` fixture to call `seed_ticker_metadata()`
  - Added `test_ytd_timeframe_uses_calendar_year_start`
  - Added `test_degenerate_1m_timeframe_returns_empty_monthly_returns`
  - Added `test_ticker_metadata_seeded_for_known_tickers`
  - Added `test_holdings_decimal_precision_path`
  - Added `test_orphaned_investment_accounts_cleaned_up_on_seed`

- **Docs:**
  - `docs/ROADMAP.md`: added "Cost Basis & Tax Lots (deferred feature)"
    entry under Future / Unphased
  - `CLAUDE.md`: added dummy-portfolio-uses-deterministic-drift note
    under Current Project Shape
  - `docs/prompts/investments_trust_pass2.md`: this file

**What surprised us:**

1. The YTD bug had **two backend code paths**, not one. Fixing
   only the aggregate router path would have been fine; the
   per-account path (`get_portfolio_performance()`) was already
   correct. But I'd have been surprised at live verification
   if I'd only fixed the frontend and trusted the per-account
   path. The plan's file-by-file walk caught this.

2. **Backend does not hot-reload.** `.claude/launch.json` doesn't
   pass `--reload` to uvicorn. YTD fix didn't take effect until
   manual `preview_stop` + `preview_start`. Should probably add
   `--reload` to the dev backend config as a follow-up — cheap
   quality-of-life fix for future sessions.

3. **Two dev databases.** `SENTRY_DB_PATH=data/dummy.db` in the
   backend launch config means the default `python scripts/seed_dummy_data.py`
   (which targets `data/sentry.db`) doesn't affect the running
   backend. Had to re-run with `SENTRY_DB_PATH=data/dummy.db`
   explicitly. Worth documenting alongside the launch.json
   `--reload` follow-up.

4. **Recharts `minHeight={1}` doesn't fully suppress the warning.**
   Recharts' own warning message says "add a minWidth(0) or
   minHeight(1)" as the fix, but adding `minHeight={1}` only gates
   RENDER below 1px; it does not suppress the warning logged during
   pre-measurement when the container briefly sees 0×0 dimensions
   on mount. The charts render at correct sizes; this is purely
   console noise. Documented as a residual (see Deferred below).

**What was deferred (by plan, not accident):**

- **Dummy-vs-benchmark 27pp gap.** Shipped as-is with a one-paragraph
  honesty note in `CLAUDE.md`. User call: linear-drift seed vs. real
  yfinance benchmarks is mathematically correct, just cosmetically
  misleading. Reshape of the seeder to match benchmark volatility is
  an explicit design decision, not a bug fix.
- **Real cost-basis / tax-lot parsing.** Roadmap skeleton lives in
  `docs/ROADMAP.md > Future / Unphased`. Placeholder in the Holdings
  table tax-lot expander stays in place.
- **Mobile responsiveness at 375px.** Timeframe buttons overflow
  off-screen. Tauri desktop app; not in P0/P1/P2 scope.
- **Export "Performance" button.** Still a `toast("coming soon")`.
  Out of scope.
- **Hardcoded `http://127.0.0.1:8000` URLs.** Codebase-wide
  pattern, not investments-specific.

**Residuals / known issues from this pass:**

1. **Recharts width(-1) warnings still fire on mount.** Noisy but
   non-functional. To fully suppress, would need to either switch
   to `aspect` prop (requires hardcoded ratio) or permanently mount
   the `ResponsiveContainer` and toggle inner content. Both are
   bigger refactors than this pass should take.
2. **Backend `--reload` missing from `.claude/launch.json`.** Should
   be added as a cheap quality-of-life follow-up.
3. **Three pre-existing ruff lint errors** in files this pass touched
   (E402 × 2 on `scripts/seed_dummy_data.py`, F401 on
   `tests/test_investments_trust.py:57`). Not introduced by this
   pass — did not fix per scope rules.
