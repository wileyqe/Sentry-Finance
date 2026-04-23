# P0 Codebase Audit — Synthesis (2026-04-22)

- **Branch:** `audit/p0-2026-04-22` (off `main` @ `a325b8c`)
- **Agents:** 10 Explore subagents, parallel, self-scoped per the template in `docs/prompts/audits/p0-codebase-audit.md`
- **Raw outputs:** `.audit/*.json` (gitignored)
- **Totals:** 69 findings — **19 P0 · 38 P1 · 12 P2**

## Per-agent counts

| Agent | P0 | P1 | P2 | Total |
|---|---|---|---|---|
| owner-scoping | 0 | 2 | 0 | 2 |
| pii-leaks | 7 | 1 | 0 | 8 |
| n-plus-one | 3 | 6 | 0 | 9 |
| test-coverage-gaps | 0 | 1 | 0 | 1 |
| a11y | 5 | 3 | 2 | 10 |
| dead-code | 0 | 1 | 4 | 5 |
| synthetic-mislabeling | 3 | 3 | 1 | 7 |
| api-contract-drift | 0 | 3 | 3 | 6 |
| type-safety | 1 | 16 | 0 | 17 |
| error-handling | 0 | 2 | 2 | 4 |
| **Total** | **19** | **38** | **12** | **69** |

## Hotspots — same file flagged by 2+ agents

1. **`frontend/src/pages/DashboardPage.tsx`** — flagged by **5 agents** (a11y, type-safety, synthetic-mislabeling, api-contract-drift, error-handling). Keyboard handling on interactive `<div>`s, 16 escape hatches, three seeded-data cards with no affordance, two API-shape drift points, missing error state.
2. **`backend/result_writer.py`** — flagged by **3 agents** (pii-leaks, n-plus-one, error-handling). Five PII log lines + one positions-ledger N+1 + one swallowed CSV exception. The post-commit orchestrator is the single biggest concentration of P0s.
3. **`frontend/src/pages/TransactionsPage.tsx`** — flagged by **3 agents** (a11y, type-safety, api-contract-drift). Add-Transaction dialog a11y, `as any` on location state, snake_case/camelCase coincidence.
4. **`dal/reports.py`** — flagged by **2 agents** (n-plus-one, owner-scoping). Two P0 N+1s in `get_net_worth_history`; one legacy `resolve_owner_account_ids` usage.
5. **`frontend/src/pages/AccountsPage.tsx`** — flagged by **2 agents** (type-safety, api-contract-drift). 22 escape hatches; `investment_cash` NaN risk when holdings_map misses an investment account.

## Top-10 ranked (grouped where one fix clears multiple findings)

### 1 · PII · `backend/result_writer.py:202, 225, 227, 233, 243` [pii-leaks P0 ×5]
Five log statements interpolate `account_id`, which has format `{institution_id}_{last4}` where `last4` comes from live web scraping (Chase, NFCU, etc.). Every refresh writes real card/account last-4 into log files. **Fix:** a `redact_account_id()` helper (or a logging filter) applied at each call site.

### 2 · PII · `extractors/chase.py:966` [pii-leaks P0]
`log.info("[chase] Discovered account IDs: %s", self._account_ids)` emits the full scraped last-4 set on every Chase refresh. **Fix:** remove the log line or redact before formatting.

### 3 · N+1 · `dal/reports.py:1777` [n-plus-one P0]
`get_net_worth_history` fetches latest valuation per real_estate row inside a loop. Shipped / user-blocking. **Fix:** `GROUP BY name` self-join for latest-per-name valuation.

### 4 · N+1 · `dal/reports.py:1811` [n-plus-one P0]
Same endpoint, same shape for vehicles. **Fix:** `GROUP BY vehicle_id, MAX(valuation_date)` + single join.

### 5 · N+1 · `backend/result_writer.py:295` [n-plus-one P0]
Per-unlinked-transaction SELECT on `positions_ledger` for every Acorns refresh (can be 100+ per run). **Fix:** fetch unmatched ledger rows once, match in Python or via a single `IN (…)` query.

### 6 · a11y · `frontend/src/pages/TransactionsPage.tsx:881, 886, 902` [a11y P0 ×3]
Add-Transaction dialog is unusable with keyboard/screen reader: icon-only close button with no `aria-label`, modal ignores Escape, date input has no `htmlFor` binding. **Fix:** three mechanical edits.

### 7 · a11y · `frontend/src/components/layout/Header.tsx:83, 133` [a11y P0 ×2]
Global search input has only a placeholder (no label); notifications panel has no Escape handler. **Fix:** `aria-label` on search; `useEffect` Escape handler on panel.

### 8 · synthetic-mislabeling · `frontend/src/pages/DashboardPage.tsx:287, 315, 730` [synthetic-mislabeling P0 ×3]
Net Worth, Monthly Net Flow, and Budget cards render seeded amounts ($10k+ net worth, $9k monthly savings, seeded budget targets) with no "Seeded" / "Demo" affordance. `SyntheticBadge` already exists at `frontend/src/components/ui/SyntheticBadge.tsx`. **Fix:** add the badge to three card headers when underlying accounts are synthetic.

### 9 · type-safety · `frontend/src/pages/ReportsPage.tsx:1929` [type-safety P0]
11 `as any` casts on `flowData.*` API response fields mask drift of `/api/reports/flow` — a backend rename will break ReportsPage silently. **Fix:** define typed interfaces for the flow endpoint response.

### 10 · PII · `tests/test_dal.py` [pii-leaks P0]
Real merchant name `"NETFLIX.COM 866-5797172 CA"` in a test fixture. Test-only (not shipped) but worth replacing with a dummy. **Fix:** rename to `"Test Merchant"` or faker-style.

## Complete P0 inventory (19 findings — expanded)

| # | Agent | File:Line |
|---|---|---|
| 1 | pii-leaks | `backend/result_writer.py:202` |
| 2 | pii-leaks | `backend/result_writer.py:225` |
| 3 | pii-leaks | `backend/result_writer.py:227` |
| 4 | pii-leaks | `backend/result_writer.py:233` |
| 5 | pii-leaks | `backend/result_writer.py:243` |
| 6 | pii-leaks | `extractors/chase.py:966` |
| 7 | pii-leaks | `tests/test_dal.py` (evidence redacted by agent — needs verification) |
| 8 | n-plus-one | `dal/reports.py:1777` |
| 9 | n-plus-one | `dal/reports.py:1811` |
| 10 | n-plus-one | `backend/result_writer.py:295` |
| 11 | a11y | `frontend/src/pages/TransactionsPage.tsx:886` |
| 12 | a11y | `frontend/src/pages/TransactionsPage.tsx:881` |
| 13 | a11y | `frontend/src/components/layout/Header.tsx:133` |
| 14 | a11y | `frontend/src/components/layout/Header.tsx:83` |
| 15 | a11y | `frontend/src/pages/TransactionsPage.tsx:902` |
| 16 | synthetic | `frontend/src/pages/DashboardPage.tsx:287` |
| 17 | synthetic | `frontend/src/pages/DashboardPage.tsx:315` |
| 18 | synthetic | `frontend/src/pages/DashboardPage.tsx:730` |
| 19 | type-safety | `frontend/src/pages/ReportsPage.tsx:1929` |

## P1 inventory (38 findings — summary for context, not this pass' scope)

- **owner-scoping (2):** legacy `resolve_owner_account_ids` still used in `dal/derived.py:274` and `dal/reports.py:220` — brittle but not currently wrong.
- **pii-leaks (1):** `backend/result_writer.py:177` logs transaction descriptions (may contain merchant identifiers).
- **n-plus-one (6):** `dal/freshness.py:88`, `dal/derived.py:535`, `dal/recurring.py:466, 619`, `dal/forecasting.py:515` (cached but fragile), `scripts/seed_dummy_db.py:39`.
- **test-coverage (1):** no integration test for the connector catch-log-continue isolation in `backend/refresh_orchestrator.py` (**important reassurance:** the agent confirmed the other four invariants — sign/direction, build_account_filter None/[], budgets partial index, transfer+refund aggregates — are all fully covered. No legacy `SUM(CASE WHEN direction='Debit'...)` survivors in `dal/` or `backend/`.)
- **a11y (3):** `<div onClick>` widgets in `DashboardPage.tsx:682, 721`; sidebar nav wrapper in `Sidebar.tsx:51`.
- **dead-code (1):** `frontend/src/components/multi-user/PartnerOnboarding.tsx` — 212 LOC, zero importers.
- **synthetic-mislabeling (3):** recurring-bills widget, recent-transactions list, InvestmentsHoldings tabs — seeded but unlabeled.
- **api-contract-drift (3):** budget field shape (`target` vs `target_amount`), `investment_cash` NaN risk, `spending_comparison` shape differs by timeframe.
- **type-safety (16):** 140 escape hatches across 16 files, worst offenders `InvestmentsAllocation.tsx` (30), `AccountsPage.tsx` (22), `DashboardPage.tsx` (16), `CashFlowPage.tsx` (15), `InvestmentsOverview.tsx` (13).
- **error-handling (2):** swallowed CSV exception in `result_writer.py:263`; missing `raise … from` in `automation_worker.py:54`.

## P2 inventory (12 findings — summary)

- **a11y (2):** decorative dots missing `aria-hidden`, progress bars missing `aria-valuenow`.
- **dead-code (4):** `AccountGroupSkeleton`, `clearSessionState`, `formatShortDate`, `accounts()` in `scripts/dummy_data/generator.py`.
- **synthetic-mislabeling (1):** `dummy_data/Institutions.json` references `owner_id` values `alex`/`jordan` while `owners.json` only defines `quintin`/`amy` — stale fixture.
- **api-contract-drift (3):** budget category field names, snake_case/camelCase, `is_synthetic` boolean vs int.
- **error-handling (2):** bare `except Exception` in `extractors/nfcu_connector.py:488`, frontend pages missing error-state checks (DashboardPage as example).

## Severity judgment calls worth your review

Rubric said **"when in doubt, downgrade."** These agent P0 calls feel borderline to me:

- **Synthetic mislabeling on Dashboard (3× P0 — findings #16, #17, #18)** — Agent reasoned "user may mistake it for real data." But this is a **local-first single-household app** where **the user set up the seed themselves**. I'd argue P1. Flagging for your call.
- **`as any` on ReportsPage (#19)** — No user-visible breakage today; masks drift but doesn't produce wrong output right now. Also the largest-scope fix on the list (defining typed response interfaces). Borderline P1.
- **N+1 on `dal/reports.py` (#8, #9)** — Output is correct; user waits longer on the net-worth card render. Rubric says P0 is "users are currently wrong," which they technically aren't. I'd keep P0 given the dashboard UX impact, but P1 is defensible.
- **`tests/test_dal.py` merchant (#10)** — Test-only, not shipped. Clear P1 in my read. **⚠ I did NOT verify the merchant string exists** — the agent redacted evidence to avoid propagating PII into the audit output. Needs a gut-check grep before any change.

## Stop-and-ask cross-check

Against the prompt's hard-stop list (`accounts.yaml`, migrations, connector auth code, `scripts/pii_scan.py`, `CLAUDE.md`, anything <90% confidence):

- **None** of the top-10 P0 fixes touch those files directly.
- **Worth raising:** the PII redaction for `account_id` logging is a class of leak that `scripts/pii_scan.py` doesn't currently detect. Extending `pii_scan.py` so this can't regress would be the natural follow-up — but that's a separate decision (touches a hard-stop file).
- **Confidence flags:** the `tests/test_dal.py` merchant (#10) is <90% confidence — agent redacted the evidence. I'll grep-verify and show you before any edit.

## Recommended execution order

Low-risk / mechanical first, bigger rewrites last. One commit per fix per prompt. Test slice per CLAUDE.md (DAL/backend → full backend suite; frontend → `npm run build`).

1. **PII log redaction** (#1, #2) — introduce `redact_account_id()` helper, update 6 call sites. Backend suite.
2. **Test fixture PII rename** (#10) — after grep-verifying the string. Backend suite.
3. **a11y frontend fixes** (#6, #7) — mechanical `aria-label` / Escape / `htmlFor`. `npm run build`.
4. **Dashboard synthetic badges** (#8) — three JSX edits using existing `SyntheticBadge`. `npm run build`.
5. **N+1 rewrites** (#3, #4, #5) — larger; full backend suite after each.
6. **ReportsPage typed response** (#9) — largest scope; consider deferring if you demote to P1.

## What I need from you before fixes

1. **Severity demotions?** Any of the four judgment-call items above you want moved to P1?
2. **Order ack or redirect.**
3. **Deferral calls** — happy to skip any of 1–6 if you'd rather batch them separately.
4. **Follow-up scope** — do you want me to extend `scripts/pii_scan.py` in a separate pass to catch `account_id` in log format strings? (touches a hard-stop file, so explicit opt-in only)
