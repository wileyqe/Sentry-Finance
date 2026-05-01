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

Pending.
