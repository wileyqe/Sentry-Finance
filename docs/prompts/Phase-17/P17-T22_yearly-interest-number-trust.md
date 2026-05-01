# P17-T22: Yearly Wrap-Up Interest Panel Number-Trust Promotion

## Context

P17-T21 promoted Monthly Review and Yearly Wrap-Up into the number-trust proof
surface — except for the Yearly Wrap-Up's interest panel, which was left at
`audit_stage: registered_pending`. The four interest values still have stable
DOM selectors and registry entries; what is missing is an independent oracle
implementation in both Python and Node so the values can move from
`registered_pending` → `api_oracle`.

The values in question are visible on `/review/yearly`:

- **Net Interest Cost** KPI (top-row card, headline number).
- **Interest paid** total in the Interest Paid vs. Earned panel.
- **Interest earned** total in the same panel.
- **Net Cost** subtotal (paid − earned) in the same panel.

The page renders these directly from `data.interest.*` returned by
`/api/review/yearly`, which is sourced from
`dal/derived/metrics.compute_interest_cost`. P17-T21 deliberately did not
re-implement that helper independently in two languages: it pulls from
`loan_details.ytd_interest` with a transaction-sum fallback, plus a
HYSA-aware interest-earned calculation that branches on owner scope. That
behavior is deterministic on the trusted seed but non-trivial to mirror.

This task closes the gap.

## Multi-Agent Coordination

Single-agent task; safe to assign to either Claude or Codex. No deliberate
pairing — it touches the same number-trust pipeline files as P17-T21 but
strictly within the interest panel.

Owned write set:

- `docs/audits/number-trust/ui-number-registry.yaml` (flip four
  `audit_stage` fields)
- `scripts/audit_number_trust.py`
- `scripts/audit_number_trust_dom.py`
- `scripts/number_trust_oracle.mjs`
- `tests/test_audit_vocabulary.py` (drop the four interest values from the
  expected `registered_pending` set)
- This prompt's outcome section after implementation

Do **not** edit:

- `dal/derived/metrics.py` (read-only reference for the oracle)
- `dal/yearly_wrapup.py`
- `frontend/src/pages/YearlyWrapUpPage.tsx` (selectors are already in place
  from P17-T21)
- `docs/ROADMAP.md` (leave for the merge pass)

Git/worktree discipline:

- Start from clean, up-to-date `main`.
- Create a dedicated branch, suggested name:
  `claude/p17-yearly-interest-number-trust` (or `codex/...`).
- Do not work directly on `main`.

## Starting State

- Canonical trusted seed: `trusted-2026-04-27-v1`, ref `2026-04-28`.
- Yearly Wrap-Up route: `/review/yearly`. The page lands on
  `currentYear - 1 = 2025` for all owner views.
- Existing data-testid attributes on the page (added in P17-T21):
  - `[data-testid='yearly-wrapup-net-interest-cost']`
  - `[data-testid='yearly-wrapup-interest-paid']`
  - `[data-testid='yearly-wrapup-interest-earned']`
  - `[data-testid='yearly-wrapup-interest-net-cost']`
- Registry entries already exist under surfaces `review.yearly.kpis` and
  `review.yearly.detail`, all currently `audit_stage: registered_pending` with
  no `check_id`.
- API source: `/api/review/yearly` → `dal/yearly_wrapup.py` →
  `dal.derived.metrics.compute_interest_cost(conn, year=year, owner_id=owner_id)`.
  The relevant return fields are:
  - `ytd_total` (interest paid)
  - `interest_earned`
  - `net_interest = interest_earned - ytd_total` (the page uses
    `paid - earned` instead, so net_cost = `ytd_total - interest_earned`).
- `compute_interest_cost` writes to `derived_summaries`. The audit's read-only
  oracle should NOT replicate that write — it computes the same numbers
  independently.
- HYSA account id used by `compute_interest_cost.interest_earned` for the
  household OR-pattern is sourced via `_affirm_hysa_id()` in the same module.
  The oracle can hardcode that account id from the trusted seed if reading
  the helper is impractical.

## Task

Promote the four interest values from `registered_pending` to `api_oracle`.

Required behavior:

1. **Python oracle.** In `scripts/audit_number_trust.py`, extend
   `raw_yearly_wrapup` (or add a sibling helper called from it) so the
   returned dict carries `interest_paid`, `interest_earned`, and
   `interest_net_cost`. Use SQL inline — do not call
   `compute_interest_cost`. Mirror the same priority order:
   - `loan_details.ytd_interest` (or `ytd interest paid`, `interest paid ytd`,
     `%interest%ytd%`) at the latest `as_of` for the requested year per
     liability account, with the same string-cleaning (`$`, `,`, `%`, strip)
     and `try/except float()` parse.
   - Fall back to `SUM(ABS(signed_amount))` over transactions where
     `LOWER(category) LIKE '%interest%' OR LOWER(category) LIKE '%finance
     charge%'` and `strftime('%Y', posting_date) = ?`.
   - Restrict liability accounts to active credit_card / loan / bnpl /
     mortgage with at least one row in `balance_snapshots`,
     `transactions`, or `loan_details` (mirrors the existing helper's
     "ghost account" filter).
   - For `interest_earned`: household view uses the OR-pattern
     `(account_id = <hysa> OR LOWER(category) LIKE '%interest%' OR
     LOWER(description) = 'interest')` with `signed_amount > 0` and
     `strftime('%Y', posting_date) = year`. Owner-scoped view applies the
     same OR-pattern but ALSO restricts to that owner's accounts via
     `_account_scope`. The trusted seed's HYSA account id can be looked up
     once at oracle start (query for `name LIKE '%HYSA%'` or accept the
     id used by `_affirm_hysa_id`).

2. **Node oracle.** In `scripts/number_trust_oracle.mjs`, extend
   `yearlyWrapup` with parallel SQL. Reuse `accountScope` exactly the way
   P17-T21 does. The HYSA id can be looked up via the same query at oracle
   construction time. Both Python and Node must produce byte-identical
   amounts in the trusted seed; the existing
   `_compare_second_language_oracle` will surface any drift.

3. **Registry.** In
   `docs/audits/number-trust/ui-number-registry.yaml`, flip these four
   entries from `audit_stage: registered_pending` to `audit_stage: api_oracle`,
   and re-add `check_id: review.yearly` to each:
   - `review.yearly.net_interest_cost`
   - `review.yearly.interest.paid`
   - `review.yearly.interest.earned`
   - `review.yearly.interest.net_cost`

4. **API audit comparison.** Extend the `review.yearly` check payload in
   `scripts/audit_number_trust.py` so it includes the three interest values
   alongside the existing fields. Compare against the API response's
   `interest.total_paid` / `interest.total_earned` /
   `interest.net_cost`.

5. **DOM expectations.** In `scripts/audit_number_trust_dom.py`, add four
   new expectations under the existing `review.yearly` view-state loop:
   - `yearly-wrapup-net-interest-cost` — formatter `format_compact_currency`
     applied to `paid - earned`. Note: the page uses `text-loss` only when
     net_cost > 0, but the rendered text formatting is identical either way.
   - `yearly-wrapup-interest-paid` — `format_currency(paid)`.
   - `yearly-wrapup-interest-earned` — `format_currency(earned)`.
   - `yearly-wrapup-interest-net-cost` — `format_currency(paid - earned)`.

6. **Test update.** In `tests/test_audit_vocabulary.py`, remove the four
   interest values from the expected `registered_pending` set. The current
   assertion is:
   ```python
   assert {ctx.get("value_id") for ctx in pending_contexts} == {
       "review.yearly.net_interest_cost",
       "review.yearly.interest.paid",
       "review.yearly.interest.earned",
       "review.yearly.interest.net_cost",
   }
   ```
   After this task, `pending_contexts` should be empty (and
   `len(audited_contexts) == len(value_ids) * 3`). The assertions can
   collapse back to the simpler P17-T19-era form.

7. **Preserve owner behavior.** The interest values are owner-scoped on
   the API side. Household reads household totals; per-owner views scope
   to that owner's liability accounts and interest-earned source accounts.
   No new owner behavior in this branch.

Implementation notes:

- The trusted seed's payroll fixtures have monthly cadence. Interest will
  be deterministic per year, but watch for off-by-one between the page's
  `paid - earned` definition and `compute_interest_cost`'s
  `net_interest = earned - paid` definition. The DOM rendering uses
  `paid - earned`, so the registry / oracle / DOM should all use that
  sign convention.
- `compute_interest_cost` writes a row to `derived_summaries`. The audit
  oracle should not write — only read.
- Amy's view: she has no liability accounts in the trusted seed, so
  `interest_paid` and `interest_earned` should both be 0 under
  per-owner scoping. Confirm this in the audit output rather than
  hardcoding.

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

Targeted tests:

```powershell
python -m pytest tests\test_audit_vocabulary.py tests\test_phase6.py tests\test_owner_scoping.py -q
rg -n "interest|review\.yearly" docs\audits\number-trust\ui-number-registry.yaml scripts\audit_number_trust.py scripts\audit_number_trust_dom.py scripts\number_trust_oracle.mjs
```

If frontend selectors changed (they should not — selectors are already
present from P17-T21):

```powershell
cd frontend
npm run build
```

## Done Criteria

- All four interest values are `audit_stage: api_oracle` with
  `check_id: review.yearly` in the registry.
- The Python and Node oracles agree on the three interest amounts for all
  three view states (household, owner.quintin, owner.amy) on the trusted seed.
- The API audit comparison passes — `interest.total_paid`,
  `interest.total_earned`, and the page's `net_cost = paid - earned` value
  match the oracle byte-for-byte.
- The DOM audit verifies the four interest selectors render the expected
  formatted text on `/review/yearly` for all three view states.
- `tests/test_audit_vocabulary.py` no longer enumerates pending interest
  values; the test asserts an empty `pending_contexts`.
- Yearly Wrap-Up rendering and behavior are unchanged.

## Outcome

Implemented. The Yearly Wrap-Up interest values now have independent Python
and Node SQL oracles, are included in the `review.yearly` API comparison, and
are covered by the DOM audit selectors from P17-T21. The four registry values
were promoted to `api_oracle` with `check_id: review.yearly`, and the registry
vocabulary test now expects no `registered_pending` value contexts.

Verification completed:

- `python -m py_compile scripts\audit_number_trust.py scripts\audit_number_trust_dom.py`
- `node --check scripts\number_trust_oracle.mjs`
- `python scripts\audit_number_trust.py --db data\dummy.db`
  (`number-trust-20260501-152825`, diff count 0)
- `node scripts\number_trust_oracle.mjs --db data\dummy.db`
- `python -m pytest tests\test_audit_vocabulary.py tests\test_phase6.py tests\test_owner_scoping.py -q`
  (19 passed)
- `python scripts\run_number_trust_proof.py`
  (`number-trust-proof-20260501-152854`, PASS)
