# P17-T19: Budgets Page Number-Trust Expansion

## Context

The current promoted number-trust proof covers Dashboard, Transactions, Cash
Flow, Reports, and Accounts across Household, Quintin, and Amy. The Budgets
page is still outside that rendered DOM proof even though Dashboard already
proves budget widgets. Before the trust bar, the primary Budgets surface should
be proven directly against the canonical synthetic fixture.

Budgets are household-only as of migration v23. This is an invariant, not a
gap: the same Budgets values should render regardless of owner selector state.

This task is assigned to **Claude** for the parallel overnight run.

## Multi-Agent Coordination

This task is intentionally paired with
`P17-T18_destructive-data-wipe-tooling.md`, assigned to Codex. These branches
may run at the same time.

Claude owns only this write set unless the user redirects:

- `frontend/src/pages/BudgetsPage.tsx`
- `docs/audits/number-trust/ui-number-registry.yaml`
- `scripts/audit_number_trust.py`
- `scripts/audit_number_trust_dom.py`
- `scripts/number_trust_oracle.mjs`
- Targeted tests for number-trust/Budgets behavior if needed
- This prompt's outcome section after implementation

Do **not** edit these files in this branch:

- `scripts/wipe_data.py`
- wipe-tool tests
- `docs/COMMANDS.md`
- `docs/ROADMAP.md` or `docs/ROADMAP_ARCHIVE.md`

If the implementation appears to require overlap, stop and write a short note
explaining the dependency instead of editing across the boundary.

Git/worktree discipline:

- Start from clean, up-to-date `main`.
- Create a dedicated branch/worktree, suggested name:
  `claude/p17-budgets-number-trust`.
- Do not work directly on `main`.
- Do not rebase, merge, or delete Codex's branch/worktree.
- Do not refresh Graphify extraction as part of this task.
- Leave roadmap status updates for the morning merge pass.

## Starting State

- `docs/audits/number-trust/ui-number-registry.yaml` has Dashboard budget
  values registered, but no Budgets page surface.
- `frontend/src/pages/BudgetsPage.tsx` renders household-only budget data from
  `/api/budgets?month=<YYYY-MM>`.
- `backend/routers/budgets.py` and `dal/budgets.py` intentionally ignore owner
  query state and return household budget data.
- `scripts/audit_number_trust.py` and `scripts/number_trust_oracle.mjs`
  already have budget summary/category concepts for Dashboard proof.
- `scripts/audit_number_trust_dom.py` exercises owner/view selection for the
  currently registered surfaces.

## Task

Extend the number-trust system so the Budgets page is registered and proven
end to end.

Required behavior:

1. Add stable `data-testid` selectors to Budgets page visible numeric values.
   Cover at least:
   - total assigned/budgeted,
   - total spent,
   - remaining/safe-to-spend amount,
   - percent used,
   - days left,
   - daily allowance,
   - visible category row spent/target values,
   - visible category row remaining values,
   - visible category row percent-used values if rendered.
2. Add a Budgets surface to the UI number registry for route `/budgets`.
3. Mark Budgets values as household-only/same-across-views where appropriate.
   The audit should prove that Household, Quintin, and Amy render the same
   budget facts rather than introducing owner-scoped budget semantics.
4. Extend the API audit/oracle comparison for the registered Budgets values.
5. Extend the second-language oracle where needed. Reuse existing independent
   budget summary/category logic if it is already sufficient; otherwise add
   Budgets-page-specific checks.
6. Extend DOM/browser expectations so the rendered Budgets page values are
   checked through the same selector-backed audit style as the five existing
   pages.
7. Preserve the current Budgets page behavior. Do not redesign the page and do
   not add per-owner budget behavior.

Implementation notes:

- Use the runtime reference date to derive the month under test, matching the
  page behavior.
- Prefer registering values that are visibly meaningful and deterministic in
  the trusted fixture.
- If a tempting value is visually present but unstable or not worth proving,
  leave it unregistered and explain why in the outcome.
- Do not broaden this task into Investments or Review page number-trust.

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

Targeted checks:

```powershell
rg -n "budgets\\.|budget" docs\audits\number-trust\ui-number-registry.yaml scripts\audit_number_trust.py scripts\audit_number_trust_dom.py scripts\number_trust_oracle.mjs frontend\src\pages\BudgetsPage.tsx
```

## Done Criteria

- Budgets appears as a registered page surface in the number-trust registry.
- API/oracle audit includes the registered Budgets values.
- DOM/browser audit checks the registered Budgets values on `/budgets`.
- Household, Quintin, and Amy views prove the same household budget numbers.
- Existing budget household-only behavior remains intact.

## Outcome

Implemented on branch `claude/p17-budgets-number-trust`. The Budgets page is
now a first-class registered surface in the number-trust system, proven end
to end through the same harness as the previously promoted five pages.

What landed:

- `frontend/src/pages/BudgetsPage.tsx`: added stable `data-testid` selectors
  for the safe-to-spend hero, percent used, days left, daily allowance, total
  spent / total assigned, active budget count, and per-category row spent /
  target / remaining-or-over-budget label. The `testIdPart` slug helper
  matches the convention used elsewhere (Dashboard, Cash Flow, Reports,
  Accounts) so DOM selector slugs stay consistent. Page logic, layout, and
  rendered text are unchanged.
- `docs/audits/number-trust/ui-number-registry.yaml`: added two new surfaces
  (`budgets.summary` and `budgets.categories`) with ten new value entries.
  All values are tagged `owner_behavior: household_only_same_across_views`
  and run against the full `*all_views` matrix (household, owner.quintin,
  owner.amy), making the household-only invariant explicit in the registry.
  Registered value/view contexts grew from 234 to 264.
- `scripts/audit_number_trust.py`: added a `raw_budgets_page(conn, month,
  ref)` oracle that mirrors the page's filter (target > 0 OR actual > 0),
  sort (actual desc), and runtime-derived headline values (days_in_month,
  days_left, daily_allowance) by re-using the manifest reference date.
  Per-view loop now compares two new check ids — `budgets.page.summary` and
  `budgets.page.categories` — against the API. The API is still queried
  through `_api_path` so any future regression that re-introduces owner
  scoping on `/api/budgets` is caught immediately. Also restored the
  `EXCLUDED_FROM_SPEND` import that commit 76cc2cc removed without
  replacing its two uses inside `raw_transactions_page` — one-line
  incidental fix that unblocked the audit.
- `scripts/number_trust_oracle.mjs`: added a sibling `budgetsPage(reference
  Date)` method on the Node oracle and emits `budgets.page.summary` and
  `budgets.page.categories` checks per view state. The audit harness's
  Python↔Node parity check (`_compare_second_language_oracle`) now exercises
  the new check ids end to end. Oracle `check_count` went from 60 to 66.
- `scripts/audit_number_trust_dom.py`: added `/budgets` to `ROUTE_ORDER`,
  built selector-backed expectations for every Budgets value (headline +
  category rows), and updated the coverage claim to name all six pages.
- `tests/test_audit_vocabulary.py`: bumped the registered-value-context
  count assertion from 234 to 264 and added "Budgets" to the required page
  set.

Verification (run from the worktree via
`scripts/run_number_trust_proof.py`, which reseeds the trusted DB and starts
isolated backend + frontend dev servers):

```
- pass  reseed trusted DB              (2.46s)
- pass  backend stack                  (5.17s)
- pass  frontend stack                 (3.12s)
- pass  runtime identity               (0.22s)
- pass  API/oracle audit               (6.61s)   264 contexts, 0 diffs
- pass  DOM/browser audit              (51.86s)  484 selector-backed checks,
                                                  111 of them on /budgets
                                                  across the three views,
                                                  0 diffs
- pass  frontend build                 (19.5s)
- pass  audit vocabulary tests         (1.39s)
- pass  trusted seed tests             (12.51s)
```

Per-route coverage from the DOM audit:

```
/dashboard:    115 rendered text checks
/transactions:  33 rendered text checks
/cash-flow:     84 rendered text checks
/reports:       69 rendered text checks
/accounts:      72 rendered text checks
/budgets:      111 rendered text checks   ← new
```

Household / Quintin / Amy each render the identical Budgets numbers — the
audit enforces this by computing one expected payload per month and
comparing it to each owner-scoped API response, which the backend
intentionally continues to ignore the `owner_id` query string on. The
`tests/test_budgets_household.py` invariant suite still passes (10/10) and
the proof artifacts are committed under
`docs/audits/number-trust/reports/number-trust-proof-20260501-020034.{md,json}`.

Things intentionally left unregistered:

- The narrative sentences inside the safe-to-spend block ("at your current
  pace of $X/day, you'll finish $Y under budget") interpolate four numbers
  through prose. They're real values but not selector-friendly and would
  duplicate the headline tile values that already cover the same facts.
- Per-category percent-used: not rendered as visible text, only as a
  progress-bar width. Selector-backed proof would have to read CSS, which
  is more brittle than the surrounding text-based proof.
- The "Spending Breakdown" donut chart's centered total: re-uses the same
  `formatCurrency(totalSpent)` value as the registered total-spent tile,
  so it's covered transitively.

Follow-ups for the morning merge pass:

- Roadmap status update was deferred per the prompt's coordination block.
- Codex's parallel branch (`P17-T18_destructive-data-wipe-tooling.md`) is
  unaffected; this branch only touches the registry, the API audit, the
  Node oracle, the DOM audit, BudgetsPage selectors, and the
  `test_audit_vocabulary` count.
