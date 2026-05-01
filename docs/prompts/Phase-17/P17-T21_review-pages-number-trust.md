# P17-T21: Review Pages Number-Trust Expansion

## Context

The promoted number-trust proof now covers Dashboard, Transactions, Cash Flow,
Reports, Accounts, and Budgets across Household, Quintin, and Amy. The remaining
review surfaces are still outside the rendered DOM proof: Monthly Review and
Yearly Wrap-Up.

These pages are trust-bar critical because they summarize the household's
monthly and annual financial story, including pre-tax snapshots, budget
performance, notable transactions, tax checklist/document state, and yearly
summary totals. Before the single-user trust bar, the visible numeric values on
these review pages should be registered and proven against the canonical
synthetic fixture.

This task is assigned to **Claude** for the clean-context run.

## Multi-Agent Coordination

This task is intentionally paired with
`P17-T20_owner-source-of-truth.md`, assigned to Codex. These branches may run
at the same time.

Claude owns only this responsibility/write set unless the user redirects:

- `frontend/src/pages/MonthlyReviewPage.tsx`
- `frontend/src/pages/YearlyWrapUpPage.tsx`
- `docs/audits/number-trust/ui-number-registry.yaml`
- `scripts/audit_number_trust.py`
- `scripts/audit_number_trust_dom.py`
- `scripts/number_trust_oracle.mjs`
- Targeted tests for number-trust/review behavior if needed
- This prompt's outcome section after implementation

Do **not** edit these files in this branch:

- `dal/owners.py`
- `backend/routers/accounts.py`
- `frontend/src/pages/SettingsPage.tsx`
- Ownership source-of-truth docs/config
- `docs/ROADMAP.md` or `docs/ROADMAP_ARCHIVE.md`

If the implementation appears to require overlap with durable ownership work,
stop and write a short note explaining the dependency instead of editing across
the boundary.

Git/worktree discipline:

- Start from clean, up-to-date `main`.
- Create a dedicated branch/worktree, suggested name:
  `claude/p17-review-pages-number-trust`.
- Do not work directly on `main`.
- Do not rebase, merge, delete, or rewrite Codex's branch/worktree.
- Do not refresh Graphify extraction as part of this task.
- Leave roadmap status updates for the merge pass.

## Starting State

- The canonical trusted seed is `trusted-2026-04-27-v1`, with backend
  reference date `2026-04-28`.
- Latest promoted proof report at prompt-authoring time:
  `docs/audits/number-trust/reports/number-trust-proof-20260501-020034.md`.
- `docs/audits/number-trust/ui-number-registry.yaml` includes Dashboard,
  Transactions, Cash Flow, Reports, Accounts, and Budgets surfaces.
- `scripts/audit_number_trust.py`, `scripts/audit_number_trust_dom.py`, and
  `scripts/number_trust_oracle.mjs` already support the all-views owner matrix.
- `frontend/src/pages/MonthlyReviewPage.tsx` calls
  `/api/review/monthly?month=<YYYY-MM>&owner_id=<owner>`.
- `frontend/src/pages/YearlyWrapUpPage.tsx` calls
  `/api/review/yearly?year=<YYYY>&owner_id=<owner>`.
- `backend/routers/reports.py` routes those endpoints to `dal/review.py` and
  `dal/yearly_wrapup.py`.
- Existing test coverage includes `tests/test_phase6.py` and
  `tests/test_owner_scoping.py` for review assemblers and owner scoping.

Graph context at prompt-authoring time pointed at:

- `frontend/src/pages/MonthlyReviewPage.tsx`
- `frontend/src/pages/YearlyWrapUpPage.tsx`
- `backend/routers/reports.py`
- `dal/review.py`
- `dal/yearly_wrapup.py`
- `tests/test_phase6.py`
- `tests/test_owner_scoping.py`
- the number-trust proof stack scripts

Treat that graph as advisory only; live code and tests are executable truth.

## Task

Extend the number-trust system so Monthly Review and Yearly Wrap-Up are
registered and proven end to end.

Required behavior:

1. Add stable `data-testid` selectors to visible numeric values on
   `MonthlyReviewPage.tsx`.
   Cover meaningful deterministic values such as:
   - income total,
   - spending total,
   - net/savings amount if rendered,
   - budget highlight values,
   - notable transaction amounts,
   - uncategorized count,
   - pre-tax snapshot values where the trusted fixture supports them.
2. Add stable `data-testid` selectors to visible numeric values on
   `YearlyWrapUpPage.tsx`.
   Cover meaningful deterministic values such as:
   - total income,
   - total spending,
   - net/savings summary values,
   - tax document/checklist counts or visible statuses where numeric,
   - effective tax / pre-tax values where rendered,
   - yearly interest, investment, or contribution summary values where the
     synthetic fixture supports them.
3. Add Review surfaces to the UI number registry for:
   - `/review/monthly`
   - `/review/yearly`
4. Preserve owner behavior.
   - Household, Quintin, and Amy should each be proven according to current
     review API semantics.
   - Do not introduce new owner behavior in this branch.
   - If a value is household-only or intentionally owner-scoped, encode that
     clearly in registry metadata or outcome notes.
5. Extend the Python API/oracle audit for the registered Review values.
   - Keep oracle calculations independent of production DAL report helpers
     where practical.
   - It is acceptable to reuse existing raw/oracle helpers from other proof
     surfaces when they already represent the same raw fact.
6. Extend the second-language Node oracle where needed.
   - Python and Node check ids must line up.
   - The parity check should exercise the new Monthly Review and Yearly Wrap-Up
     check ids.
7. Extend DOM/browser expectations so rendered Review page values are checked
   through selector-backed audit style.
8. Preserve current page behavior and layout.
   - Add selectors and proof plumbing; do not redesign the Review pages.
   - Do not broaden this task into Investments number-trust.

Implementation notes:

- Use the backend runtime reference date/month/year where the page does.
- Prefer registering visible values that are deterministic in the trusted
  fixture.
- If a tempting value is prose-only, duplicated elsewhere, visually unstable,
  or not worth selector-backed proof, leave it unregistered and explain why in
  the outcome.
- Be careful with formatted dates versus numbers; register date/status values
  only when they materially improve trust.

## Verification

Minimum verification:

```powershell
python -m py_compile scripts\audit_number_trust.py scripts\audit_number_trust_dom.py
python scripts\audit_number_trust.py --db data\dummy.db
python scripts\audit_number_trust_dom.py --db data\dummy.db --frontend-url http://127.0.0.1:1420 --timeout-ms 20000 --settle-ms 1000
node scripts\number_trust_oracle.mjs --db data\dummy.db
```

If the stack is not running, use the one-command proof gate instead:

```powershell
python scripts\run_number_trust_proof.py
```

Targeted tests/checks:

```powershell
python -m pytest tests\test_audit_vocabulary.py tests\test_phase6.py tests\test_owner_scoping.py -q
rg -n "review\.|monthly|yearly|wrap" docs\audits\number-trust\ui-number-registry.yaml scripts\audit_number_trust.py scripts\audit_number_trust_dom.py scripts\number_trust_oracle.mjs frontend\src\pages\MonthlyReviewPage.tsx frontend\src\pages\YearlyWrapUpPage.tsx
```

If frontend selectors changed:

```powershell
cd frontend
npm run build
```

## Done Criteria

- Monthly Review and Yearly Wrap-Up appear as registered page surfaces.
- API/oracle audit includes the registered Review values.
- The second-language oracle includes matching Review checks.
- DOM/browser audit checks registered Review values on both routes.
- Household, Quintin, and Amy Review views are proven according to current API
  owner semantics.
- Existing review behavior and owner scoping remain intact.

## Outcome

Implemented on branch `claude/p17-review-pages-number-trust`.

**What landed**

- `MonthlyReviewPage.tsx`: stable `data-testid` attributes on Income / Spending /
  Savings Rate KPIs, the Net Worth Δ hero amount and percent, the cash-surplus
  chip, the pre-tax block (gross / federal / state / net pay / pre-tax savings
  rate), the uncategorized count, the budget-highlight `actual` / `budgeted` /
  `variance` cells, and the indexed notable-transaction amounts.
- `YearlyWrapUpPage.tsx`: stable `data-testid` attributes on Total Income /
  Total Spending / Savings Rate / Net Interest Cost KPIs, the status pill
  (`preliminary` / `revised` / `final`), the tax-document received-vs-expected
  count chip, the effective-tax block (gross / federal / state / effective
  rate), the interest paid / earned / net-cost row, the income-by-stream and
  spending-by-category amount cells.
- `docs/audits/number-trust/ui-number-registry.yaml`: six new surfaces under
  routes `/review/monthly` and `/review/yearly` (29 registered values × 3
  view states = 87 new contexts). 25 values × 3 = 75 are wired to the
  `api_oracle` audit stage; the four interest-related Yearly values
  (`net_interest_cost`, `interest.paid`, `interest.earned`, `interest.net_cost`)
  are `registered_pending` because re-implementing
  `dal/derived/metrics.compute_interest_cost` independently in two languages is
  out of scope for this task — the selectors are in place so a future task can
  promote them.
- `scripts/audit_number_trust.py`: new `raw_monthly_review` and
  `raw_yearly_wrapup` oracles plus `_expected_tax_doc_entries` /
  `_tax_doc_received_count` helpers. `run()` adds `review.monthly` and
  `review.yearly` checks per view state. The Monthly Review pre-tax oracle
  matches `dal/payroll.get_gross_income_for_month`'s `ORDER BY id DESC LIMIT 1`
  contract — household view shows the most recent single snapshot rather than
  a household sum, mirroring the API. Net worth delta reuses `raw_net_worth_month`.
- `scripts/number_trust_oracle.mjs`: parallel `monthlyReview`, `yearlyWrapup`,
  `netWorthMonth`, `expectedTaxDocs`, and `taxDocReceivedCount` helpers, plus
  matching push entries in the `checks()` loop. Primary owner is loaded from
  `config/owner_config.yaml` (the `owners` table has no `is_primary` column).
  Registry parsing now passes `{ maxAliasCount: -1 }` so the YAML library
  doesn't trip on the `*all_views` alias the registry uses on every value.
- `scripts/audit_number_trust_dom.py`: `/review/monthly` and `/review/yearly`
  appended to `ROUTE_ORDER`. New formatters `format_compact_currency`,
  `format_review_signed_currency`, `format_pretax_negative_compact`, and
  `format_review_signed_percent` mirror the page's
  `formatCompactCurrency` / `fmtPct` helpers (note: `fmtPct(0) → "0.0%"` with
  no `+` prefix, unlike `format_signed_percent`). DOM expectations cover
  the registered values for both routes; pre-tax / effective-tax / tax-doc
  / income-stream / spending-category expectations conditionally render based
  on whether the API check returned the data.
- `tests/test_audit_vocabulary.py`: header counts updated to derive from the
  registry (`len(audited_contexts) == (len(value_ids) - len(pending)) * 3`) and
  the pending-value enumeration explicitly lists the four interest values.
  The page set assertion now requires `Monthly Review` and `Yearly Wrap-Up`.

**Verification (all green against `data/dummy.db` / trusted seed
`trusted-2026-04-27-v1`, ref `2026-04-28`)**

- `python -m py_compile scripts\audit_number_trust.py scripts\audit_number_trust_dom.py` — clean.
- `python scripts\audit_number_trust.py --db data\dummy.db` — diff count 0;
  72 second-language oracle checks; report
  `number-trust-20260501-135216.md`.
- `python scripts\audit_number_trust_dom.py --db data\dummy.db --frontend-url
  http://127.0.0.1:1420 --timeout-ms 20000 --settle-ms 1000` — DOM diff count 0;
  report `number-trust-dom-20260501-135717.md`.
- `python -m pytest tests\test_audit_vocabulary.py tests\test_phase6.py
  tests\test_owner_scoping.py -q` — 19 passed.
- `cd frontend && npm run build` — clean.
- Manual browser verification at `/review/monthly` and `/review/yearly` (Quintin
  view) confirmed all selectors render and match the API response.

**Owner behavior preserved**

- Household view returns whichever payroll snapshot the API picks up
  (most-recent-by-id, currently Amy's row); both the Python and Node oracles
  match. Quintin renders his own gross/withholding/net.
- Amy's view: account-scoped queries (income/spending/notable transactions)
  short-circuit through `_account_scope`'s `AND 1=0` clause, so income/
  spending/cash-surplus/uncategorized all read 0 and the budget-highlights
  list still reflects the household-only budget rows. Her pre-tax block
  populates from her seeded payroll snapshots; effective-tax block populates
  for the year.
- Tax-doc checklist correctly returns 5 expected docs for primary
  (Quintin) and household, 1 (`nfcu_1098` — household-scope only) for Amy,
  matching `dal/yearly_wrapup.get_expected_tax_docs`.

**Deferred / known gaps**

- Yearly interest panel (`yearly-wrapup-interest-paid`,
  `yearly-wrapup-interest-earned`, `yearly-wrapup-interest-net-cost`,
  `yearly-wrapup-net-interest-cost`) is `registered_pending` — selectors are in
  place, oracle/API/DOM proof is pending an independent re-implementation of
  `compute_interest_cost`.
- Subscription-changes / large-transfers panels on Monthly Review remain
  unregistered: subscription mutations are non-deterministic in the trusted
  seed (the canonical seeder produces zero `recurring_mutations` and zero
  `recurring_transactions` first-seen events in the audit window — the per-
  request audit run prints `Subscription changes failed: no such column:
  first_seen` against an older test fixture).
- "Large transfers" registers no notable transfers under the trusted-seed
  monthly transfer cadence (Acorns/Fidelity/TSP transfers fall below the
  $1,000 threshold for individual entries that are not transfer-tagged).
- Lifestyle-creep panel intentionally not registered — the analysis is
  prose-heavy and the underlying metrics are exercised on the Cash Flow /
  Reports proof surfaces already.
- Pre-tax KPI cards on Monthly Review: per-owner pre_tax block is
  `hidden_when_no_payroll_snapshot`. With the trusted seed, both Quintin and
  Amy have payroll snapshots in March 2026, so the block populates for all
  three views — no view-specific suppression required.
