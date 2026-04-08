# Phase 12 — Empty-State Audit (Amy view)

> **Status:** Research complete. **Code fixes are out of scope for this doc.**
> Findings inform a follow-up plan.
>
> Captured: 2026-04-08 against the dummy dataset (`data/dummy.db`) after
> P12-T01..T05 attributed every synthetic row to Quintin.

---

## TL;DR — the one bug behind half the leaks

**`if not account_ids:` collapses an empty list and `None` into the same
"no filter" branch.** When a view resolves to "this owner has zero
accounts" (i.e. Amy), the resolver returns `[]`, every downstream DAL
helper that uses the falsy-check pattern silently drops its filter, and
the query returns *Quintin's* full dataset under Amy's view.

The buggy pattern lives in:

- `dal/cash_flow.py:45-50` — `_acct_filter_clause` (`if not account_ids: return "", []`)
- `dal/reports.py` — every `if not account_ids and owner_id:` block (lines 55, 142, 417, 483, 628, 731, 832, 961). The block resolves owner → `account_ids`, but the *next* line (`if account_ids:`) is also a truthy check, so the resolved empty list silently disables the filter.
- `dal/budgets.py:217`, `dal/forecasting.py:434/489/566`, `dal/allocation.py:219`, `dal/performance.py:427` — same `if account_ids:` pattern. **Each needs an audit pass to confirm whether the upstream resolver hands them empty lists or `None`.**

The contract conflict is subtle: `dal/owners.py:resolve_account_ids_for_view`
returns `None` for "no filter" (line 171) and a `set` (possibly empty)
otherwise (line 224); `resolve_owner_account_ids` (line 242) then casts
that set to a `list`, so callers see `[]` for "this owner owns nothing"
and `None` for "no filter at all". The DAL helpers conflate the two.

**The fix is 1-line per call site:** change every `if not account_ids:`
guard that should mean "no filter" to `if account_ids is None:`, and
every `if account_ids:` guard that should mean "filter is set" to
`if account_ids is not None:`. A *separate* short-circuit then needs to
return zero rows when `account_ids == []`.

This single fix resolves the majority of the data leaks below.

---

## Methodology

1. **Three Explore subagents in parallel** (A: Core financial, B: Planning & tracking, C: Reports / reviews / meta) walked the live preview comparing Quintin vs Amy views via `preview_snapshot`, `preview_console_logs`, `preview_network`.
2. **Direct-API cross-check** from inside the preview browser via `fetch()` calls to confirm/refute the agents' "looks empty visually" or "looks leaky visually" claims at the JSON level. This caught two classes of error:
   - **False negatives** — the page rendered "empty" because the *frontend* dropped owner filter, so the agent saw a clean Amy state visually when the backend was actually returning zero rows for unrelated reasons.
   - **Confirmed leaks** — endpoints that returned Quintin's full dataset under `?owner_id=amy` or `?view=amy`.
3. **Root-cause read** of `dal/owners.py`, `dal/cash_flow.py`, and the `dal/reports.py` resolver blocks identified the falsy-list bug above as the underlying cause for ~4 of the leaks.

---

## Confirmed correct (no action required)

These endpoints return clean empty arrays under `view=amy` / `owner_id=amy`:

| Endpoint | Behavior on Amy |
|---|---|
| `GET /api/accounts?view=amy` | `[]` |
| `GET /api/transactions?owner_id=amy` | `[]` |
| `GET /api/credit-scores?owner_id=amy` | empty list |
| `GET /api/holdings?view=amy` | empty |
| `GET /api/portfolio/snapshots?view=amy` | empty |
| `GET /api/portfolio/performance?view=amy` | empty / zeros |
| `GET /api/recurring-patterns?owner_id=amy` | empty |
| `GET /api/savings-goals?owner_id=amy` | `[]` |

Account-bound queries work because `transactions`, `credit_scores`,
`holdings`, `portfolio_snapshots`, `recurring_patterns`, and
`savings_goals` either denormalize `owner_id` directly (post v21) or
filter by `account_id IN (resolved_ids)` *with* a correct
`is None` check.

---

## Confirmed leaks (Amy view returns Quintin's data)

Verified by direct `fetch()` from the preview browser. Each of these
should return zero rows / zeros under `?owner_id=amy`, but returns
Quintin's full dataset instead:

| # | Endpoint | Symptom | Suspected fix locus |
|---|---|---|---|
| L1 | `GET /api/budgets?month=2026-04&owner_id=amy` | Returns Quintin's full budget list (~16 rows) | `dal/budgets.py:217` (`if account_ids:` truthy check) — also verify the router actually threads `owner_id` |
| L2 | `GET /api/reports/flow?...&owner_id=amy` | Returns Quintin's monthly cash flow series | `dal/reports.py` — one of the 8 `if not account_ids and owner_id:` blocks (likely the `get_cash_flow_report` block at line 142). Empty resolved set leaks. |
| L3 | `GET /api/review/monthly?month=2026-03&owner_id=amy` | Returns full monthly review for Quintin | Likely a downstream of L2 or L4 — `dal/review.py` and `dal/cash_flow.py` both touch this code path |
| L4 | `GET /api/review/yearly?year=2025&owner_id=amy` | Returns Quintin's yearly wrap-up | `dal/yearly_wrapup.py` calls into `dal/cash_flow.py` and `dal/payroll.py` — the cash_flow path hits the `_acct_filter_clause` bug |
| L5 | `GET /api/reports/spending?...&owner_id=amy` | Returns Quintin's spending breakdown | `dal/reports.py:55` block — `account_ids = list(resolved)` then `if account_ids:` guard |

**Common root**: L1, L2, L3, L4, L5 all flow through the
`if not account_ids:` (or `if account_ids:`) truthy-list pattern.
Fix the pattern, fix all five.

---

## Frontend filter-threading gaps (independent of L1–L5)

Even after the DAL bug is fixed, two frontend pages don't pass `owner_id`
to their fetches at all, so they will *still* render Quintin's data under
the Amy chip:

| # | File | Issue |
|---|---|---|
| F1 | `frontend/src/pages/BudgetsPage.tsx` | No `owner_id` or `view=` param on any of its `apiFetch` calls. Confirmed by `Grep`: zero matches for `owner_id\|view=`. |
| F2 | `frontend/src/pages/ReportsPage.tsx` | Same — zero matches. |

These need to:
1. Read `view` (or `ownerParam`) from `useView()`.
2. Append `&owner_id=${ownerParam}` (or `?view=${view}`) to every fetch
   that exposes per-owner data.
3. Re-fetch on view change (effect dependency).

This is the same pattern already applied in `DashboardPage.tsx`,
`AccountsPage.tsx`, `TransactionsPage.tsx` — copy from there.

---

## Empty-state polish (UI gaps when the data IS correctly empty)

Even on endpoints that return the right data, several pages render
poorly when the response is empty. These are user-experience issues, not
data-correctness issues.

### Severity 1 — visible breakage / NaN

| # | Page / component | Issue |
|---|---|---|
| P1 | DashboardPage cashflow chart | Stuck on "Loading…" forever when the series returns empty (Agent A). Spinner never replaces with empty-state copy. |
| P2 | DashboardPage spending donut | Renders an empty SVG with no fallback. No "No spending this period" message. |
| P3 | InvestmentsPage performance chart | Y-axis collapses to a single point at 0; no empty-state placeholder. |
| P4 | Monthly Review savings_rate KPI | Displays `NaN%` when income == 0. (`net / income * 100` divides by zero — guarded in `_row_to_period` but not in the review aggregator.) |
| P5 | Yearly Wrap-Up effective tax rate | Same NaN risk if `gross_income == 0`. |

### Severity 2 — missing empty-state copy

| # | Page / component | Issue |
|---|---|---|
| P6 | BudgetsPage monthly target grid | Just shows an empty grid; needs "No budget set for this view" with a CTA back to the household view. |
| P7 | RecurringPage list | Empty list shows nothing — should say "No recurring patterns detected for this owner yet." |
| P8 | Goals view | Empty list silently. |
| P9 | DocumentsPage | Empty file list silently. |
| P10 | ReportsPage | Most charts render axes only; no copy. |

### Severity 3 — dead interactions

| # | Page / component | Issue |
|---|---|---|
| P11 | DashboardPage recurring item click | Click handler still navigates but lands on an empty filtered list (already partially fixed in commit `943629d`; verify Amy case). |
| P12 | TransactionsPage filters | Filter chips still active when there are zero rows; should disable or render "No transactions match" without offering filter UI. |

### Severity 4 — non-issues / agent misclassifications (do not fix)

The subagents reported a handful of "leaks" that the direct-API
cross-check disproved — they were artifacts of the testing
methodology (agents mutated `localStorage` and reloaded, which
sometimes raced the `ViewContext` mount). These are NOT in this
document. Trust the table above.

---

## Recommended follow-up plan shape

A follow-up plan should bundle work into three commits:

### Commit 1 — backend filter-pattern fix (highest leverage)
- Audit every `if not account_ids:` and `if account_ids:` site listed in the **TL;DR** root-cause section.
- Decide the contract: change the resolver to return `None` for "no filter" and an empty *frozenset* (truthy-distinct) for "no accounts", OR change every call site to use `is None` / `is not None` and add an explicit empty short-circuit. Recommend the second — it's more explicit and matches Python idioms.
- Add a regression test: for each leaky endpoint above, assert that `?owner_id=amy` returns zero rows / zero amounts.

### Commit 2 — frontend filter threading
- Fix `BudgetsPage.tsx` and `ReportsPage.tsx` to thread `view` / `owner_id` through every fetch.
- Audit the rest of the page tree for the same gap with `grep -L "owner_id\|view=" frontend/src/pages/*.tsx`.

### Commit 3 — empty-state polish
- Severity 1 first (NaN guards + chart loaders).
- Severity 2 next (empty-state copy).
- Severity 3 last (dead-interaction cleanup).

---

## What's NOT in this audit

- **Owner delete / archive UX** — deferred (see ROADMAP backlog).
- **Multi-owner ViewSelector slot rendering** — deferred (slots are still hardcoded; ROADMAP backlog).
- **YAML vs DB owner config source-of-truth** — deferred (ROADMAP backlog).
- **Code fixes** — explicitly out of scope for this audit. The
  follow-up plan above is the next planning artifact.
