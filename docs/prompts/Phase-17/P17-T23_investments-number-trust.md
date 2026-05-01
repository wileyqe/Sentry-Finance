# P17-T23: Investments Number-Trust Expansion

## Context

The promoted number-trust proof covers Dashboard, Transactions, Cash Flow,
Reports, Accounts, Budgets, Monthly Review, and Yearly Wrap-Up across
Household, Quintin, and Amy. Investments is now the remaining primary
user-facing proof gap before the single-user trust bar.

This task extends the same registry, API oracle, second-language oracle, and
DOM/browser proof style to the Investments page. The goal is not to redesign
Investments or fix live brokerage modeling; it is to prove that visible
Investments numbers in the canonical synthetic fixture come from the expected
data path.

This task is assigned to **Codex**.

## Multi-Agent Coordination

This task is intentionally paired with
`P17-T24_subscription-utility-classifier-audit.md`, assigned to Claude. These
branches may run at the same time.

Codex owns only this responsibility/write set unless the user redirects:

- `frontend/src/pages/InvestmentsPage.tsx`
- `frontend/src/pages/InvestmentsOverview.tsx`
- `frontend/src/pages/InvestmentsHoldings.tsx`
- `frontend/src/pages/InvestmentsAllocation.tsx`
- `docs/audits/number-trust/ui-number-registry.yaml`
- `scripts/audit_number_trust.py`
- `scripts/audit_number_trust_dom.py`
- `scripts/number_trust_oracle.mjs`
- Targeted tests for number-trust/Investments behavior if needed
- This prompt's outcome section after implementation

Do **not** edit these files in this branch:

- `dal/category_classifications.py`
- `dal/categorization.py`
- `config/categories.yaml`
- `config/budgets.yaml`
- `dummy_data/recurring_transactions.json`
- `docs/ROADMAP.md` or `docs/ROADMAP_ARCHIVE.md`

If the implementation appears to require classifier, category, or seed-shape
changes, stop and write a short note explaining the dependency instead of
editing across the boundary.

Git/worktree discipline:

- Start from clean, up-to-date `main`.
- Create a dedicated branch/worktree, suggested name:
  `codex/p17-investments-number-trust`.
- Do not work directly on `main`.
- Do not rebase, merge, delete, or rewrite Claude's branch/worktree.
- Do not refresh Graphify extraction as part of this task.
- Leave roadmap status updates for the merge pass.
- Keep generated evidence selective. Commit the final passing proof summary
  only when it is needed as promoted evidence; do not commit every timestamped
  raw JSON artifact produced during iteration.

## Starting State

- Canonical trusted seed: `trusted-2026-04-27-v1`.
- Backend reference date for the trusted seed: `2026-04-28`.
- Latest promoted proof report at prompt-authoring time:
  `docs/audits/number-trust/reports/number-trust-proof-20260501-152854.md`.
- `docs/audits/number-trust/ui-number-registry.yaml` has no Investments
  surface.
- `frontend/src/pages/InvestmentsPage.tsx` is a tab container with
  Overview, Holdings, and Allocation tabs.
- `InvestmentsOverview.tsx` calls `/api/investments/holdings`,
  `/api/investments/performance`, `/api/investments/allocation`, and
  `/api/investments/tax-summary`.
- `InvestmentsHoldings.tsx` calls `/api/investments/holdings`, with expandable
  calls to `/api/investments/lots` and `/api/investments/tax-buckets`.
- `InvestmentsAllocation.tsx` calls `/api/investments/allocation` and
  `/api/investments/tax-summary`.
- `backend/routers/investments.py` routes those endpoints to
  `dal/investments.py`.
- The page uses session-backed local UI state for active tab, timeframe,
  account filter, sort, and X-Ray mode. The DOM audit may need stable controls
  or explicit state reset to make each tab deterministic.

Graph context at prompt-authoring time pointed at:

- `frontend/src/pages/InvestmentsPage.tsx`
- `frontend/src/pages/InvestmentsOverview.tsx`
- `frontend/src/pages/InvestmentsHoldings.tsx`
- `frontend/src/pages/InvestmentsAllocation.tsx`
- `backend/routers/investments.py`
- `dal/investments.py`
- the number-trust proof stack scripts
- Phase 13 investment pipeline prompt history

Treat that graph as advisory only; live code and tests are executable truth.

## Task

Extend the number-trust system so Investments is registered and proven end to
end.

Required behavior:

1. Add stable selectors to tab controls needed by the DOM audit.
   - The audit must be able to reach Overview, Holdings, and Allocation
     deterministically.
   - Avoid relying on prior session state.
2. Add stable `data-testid` selectors to meaningful visible numeric values on
   the Overview tab.
   Cover deterministic values such as:
   - total portfolio value,
   - absolute and percentage change for the selected timeframe when rendered,
   - count of asset classes when rendered,
   - asset allocation legend percentages and dollar amounts,
   - tax diversification dollar amounts and percentages,
   - account value rows or bars when rendered as text.
3. Add stable `data-testid` selectors to meaningful visible numeric values on
   the Holdings tab.
   Cover deterministic values such as:
   - holding price,
   - quantity,
   - market value,
   - percent of portfolio,
   - cash row values,
   - tax-lot or tax-bucket values only where the synthetic fixture reliably
     supports them and the audit can expand the row deterministically.
4. Add stable `data-testid` selectors to meaningful visible numeric values on
   the Allocation tab.
   Cover deterministic values such as:
   - total value in allocation donuts,
   - asset-class dollar amounts and percentages,
   - sector/geographic/market-cap exposure values,
   - X-Ray or tax-treatment values where deterministic and reachable.
5. Add Investments surfaces to the UI number registry for `/investments`.
   Prefer separate surfaces for overview, holdings, and allocation when that
   makes audit output easier to read.
6. Preserve owner behavior.
   - Household, Quintin, and Amy should each be proven according to current
     investment API semantics.
   - If Amy has no visible investment rows, prove the empty state or omit
     owner-specific row checks with an explicit registry/outcome note.
   - Do not change owner scoping in this branch.
7. Extend the Python API/oracle audit for registered Investments values.
   - Keep calculations independent of production DAL report helpers where
     practical.
   - For unavoidable direct endpoint comparisons, be explicit in the outcome
     about what is endpoint-shape validation versus independent arithmetic.
8. Extend the second-language Node oracle where needed.
   - Python and Node check ids must line up.
   - The parity check should exercise the new Investments check ids.
9. Extend DOM/browser expectations so rendered Investments values are checked
   through selector-backed audit style.
   - The audit should navigate tabs rather than assuming only the default
     Overview tab.
   - Avoid proving chart paths, canvas geometry, or hover-only tooltip values
     unless the selector behavior is reliable.
10. Preserve current page behavior and layout.
    - Add selectors and proof plumbing; do not redesign Investments.
    - Do not broaden this task into Fidelity live-shape, TSP live-shape, or
      cost-basis/tax-lot readiness.

Implementation notes:

- Use the same owner/view matrix as the promoted proof.
- Use the runtime reference date where the page or API does.
- Prefer visible text values over SVG-only or CSS-derived values.
- If a tempting value is duplicated, unstable, chart-only, or not worth
  selector-backed proof, leave it unregistered and explain why in the outcome.
- If the proof run emits large timestamped JSON files, keep only the final
  evidence that the roadmap or audit policy actually needs.

## Verification

Minimum verification:

```powershell
python -m py_compile scripts\audit_number_trust.py scripts\audit_number_trust_dom.py
node --check scripts\number_trust_oracle.mjs
python scripts\audit_number_trust.py --db data\dummy.db
node scripts\number_trust_oracle.mjs --db data\dummy.db
```

If the stack is not running, use the one-command proof gate:

```powershell
python scripts\run_number_trust_proof.py
```

Targeted tests/checks:

```powershell
python -m pytest tests\test_audit_vocabulary.py tests\test_owner_scoping.py tests\test_dal_investments_writes.py tests\test_performance_by_asset_class.py tests\test_trusted_seed.py -q
rg -n "investments\.|Investments|investment" docs\audits\number-trust\ui-number-registry.yaml scripts\audit_number_trust.py scripts\audit_number_trust_dom.py scripts\number_trust_oracle.mjs frontend\src\pages\Investments*.tsx
```

If frontend selectors changed:

```powershell
cd frontend
npm run build
```

## Done Criteria

- Investments appears as a registered page surface in the number-trust
  registry.
- API/oracle audit includes the registered Investments values.
- The second-language oracle includes matching Investments checks.
- DOM/browser audit checks registered Investments values across the required
  tabs.
- Household, Quintin, and Amy Investments views are proven according to
  current API owner semantics.
- Existing Investments behavior and owner scoping remain intact.
- The outcome section lists any visible Investments values intentionally left
  unregistered.

## Outcome

Implemented by Codex on `codex/p17-investments-number-trust`.

What changed:

- Added deterministic Investments tab/timeframe/account/X-Ray control selectors.
- Added selector-backed visible numeric values for Investments Overview,
  Holdings, and Allocation without redesigning the page.
- Registered Investments overview, holdings, and allocation surfaces in
  `docs/audits/number-trust/ui-number-registry.yaml`.
- Added Python raw-SQL/API comparisons for `investments.overview`,
  `investments.holdings`, and `investments.allocation`.
- Added matching SQL.js second-language oracle checks.
- Extended the DOM audit to navigate `/investments`, switch to the stable
  `All` timeframe, and click Holdings/Allocation tabs before checking values.
- Updated the audit vocabulary test so it counts each value's declared
  owner/view contexts instead of assuming every registered value has all three
  contexts. This is needed because populated investment row values apply to
  Household/Quintin while Amy is proved through explicit empty-state values.

Registered proof coverage:

- Overview: total value, all-time change amount/percent, asset-class count,
  asset-class legend amounts/percents, tax-diversification amounts/percents,
  and Amy's no-performance empty state.
- Holdings: price, quantity, market value, and portfolio percent collections
  for populated views, plus Amy's empty holdings state.
- Allocation: total value, asset-class amounts/percents, sector amounts/
  percents, geography amounts/percents, market-cap amounts/percents, plus
  Amy's empty allocation state.

Intentionally left unregistered:

- Chart paths, donut geometry, axis ticks, hover-only tooltips, and treemap
  geometry because they are not stable selector-backed text values.
- Overview contribution/growth account bars because the visible values are
  chart/tooltip-derived rather than durable text.
- Expanded tax-lot and tax-bucket values because the current task did not need
  row-expansion proof, and the live-shape/tax-lot task remains separate.
- Allocation X-Ray-specific values because the default allocation tab plus
  overview tax diversification already cover deterministic visible treatment
  values without broadening into X-Ray behavior.

Verification:

- `python -m py_compile scripts\audit_number_trust.py scripts\audit_number_trust_dom.py`
- `node --check scripts\number_trust_oracle.mjs`
- `python scripts\audit_number_trust.py --db data\dummy.db`
- `node scripts\number_trust_oracle.mjs --db data\dummy.db`
- `cd frontend; npm run build`
- `python scripts\run_number_trust_proof.py`
- `python -m pytest tests\test_audit_vocabulary.py tests\test_owner_scoping.py tests\test_dal_investments_writes.py tests\test_performance_by_asset_class.py tests\test_trusted_seed.py -q`

Final passing proof report:
`docs/audits/number-trust/reports/number-trust-proof-20260501-171611.md`.
