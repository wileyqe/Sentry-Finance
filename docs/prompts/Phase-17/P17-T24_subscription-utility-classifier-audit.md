# P17-T24: Subscription Vs Utility Classifier Audit

## Context

The roadmap calls out an unresolved boundary between subscriptions and
utilities. The household decision rule is:

- **Subscriptions** can generally be turned off without disrupting daily life.
- **Utilities** cannot generally be turned off without disrupting daily life.

This boundary affects budgets, lifestyle-creep analysis, cash-flow
interpretation, recurring-change review panels, and the category vocabulary
used by number-trust oracles. The goal is to make the rule explicit, audit the
current category behavior against it, and add tests so future category changes
do not blur the boundary again.

This task is assigned to **Claude**.

## Multi-Agent Coordination

This task is intentionally paired with
`P17-T23_investments-number-trust.md`, assigned to Codex. These branches may
run at the same time.

Claude owns only this responsibility/write set unless the user redirects:

- `config/categories.yaml`
- `config/budgets.yaml`
- `dummy_data/recurring_transactions.json`
- `dal/category_classifications.py`
- `dal/categorization.py`
- `dal/lifestyle.py`
- `scripts/number_trust_vocabulary.py`
- `docs/audits/number-trust/oracle-vocabulary.json`
- `docs/data-lineage/lineage/auto_categorization.yaml`
- Targeted classifier/category tests, likely under `tests/`
- This prompt's outcome section after implementation

Do **not** edit these files in this branch:

- `frontend/src/pages/InvestmentsPage.tsx`
- `frontend/src/pages/InvestmentsOverview.tsx`
- `frontend/src/pages/InvestmentsHoldings.tsx`
- `frontend/src/pages/InvestmentsAllocation.tsx`
- `docs/audits/number-trust/ui-number-registry.yaml`
- `scripts/audit_number_trust.py`
- `scripts/audit_number_trust_dom.py`
- `scripts/number_trust_oracle.mjs`
- `docs/ROADMAP.md` or `docs/ROADMAP_ARCHIVE.md`

If this task appears to require Investments number-trust changes, stop and
write a short note explaining the dependency instead of editing across the
boundary.

Git/worktree discipline:

- Start from clean, up-to-date `main`.
- Create a dedicated branch/worktree, suggested name:
  `claude/p17-subscription-utility-classifier-audit`.
- Do not work directly on `main`.
- Do not rebase, merge, delete, or rewrite Codex's branch/worktree.
- Do not refresh Graphify extraction as part of this task.
- Leave roadmap status updates for the merge pass.

## Starting State

- `config/categories.yaml` has keyword rules for utility-like services:
  `DUKE ENERGY`, electric, water, gas, Spectrum, Comcast, AT&T, T-Mobile,
  Verizon, and Mint Mobile.
- Utility-like telecom/internet/mobile rules currently map to
  `Telephone Services`.
- Streaming and recurring optional-service rules such as Netflix, Hulu,
  Disney, HBO, Paramount, Peacock, Apple TV, YouTube Premium, Spotify,
  Audible, Kindle, Amazon Prime, Patreon, SimpleFIN, and ActBlue currently map
  to `Dues and Subscriptions`.
- `config/budgets.yaml` has distinct budget defaults for `Utilities`,
  `Telephone Services`, and `Dues and Subscriptions`.
- `dummy_data/recurring_transactions.json` contains recurring examples for
  utilities, telecom/internet/mobile, insurance, and subscriptions.
- `dal/category_classifications.py` centralizes canonical category sets:
  income categories, spend exclusions, income exclusions, transfer categories,
  loan categories, lifestyle-creep exclusions, forecast exclusions, and
  non-projection income.
- `dal/lifestyle.py` imports `EXCLUDED_FROM_CREEP` and excludes those
  categories from lifestyle-creep flags.
- `tests/test_flow_classification.py` already contains a static regression
  that every seeder spending category belongs to `INCOME_EXCL_FROM_INC`.
- `tests/test_audit_vocabulary.py` asserts number-trust vocabulary matches
  `scripts/number_trust_vocabulary.py` and canonical category sets.

Graph context at prompt-authoring time pointed at:

- `dal/category_classifications.py`
- `dal/categorization.py`
- `dal/lifestyle.py`
- `dal/recurring.py`
- `dal/budgets.py`
- `config/categories.yaml`
- `config/budgets.yaml`
- `dummy_data/recurring_transactions.json`
- `tests/test_flow_classification.py`
- `tests/test_cashflow_invariants.py`
- number-trust vocabulary tests
- `docs/data-lineage/lineage/auto_categorization.yaml`

Treat that graph as advisory only; live code and tests are executable truth.

## Task

Make the subscription-vs-utility boundary explicit and prove the current
classifier behavior against the household rule.

Required behavior:

1. Inventory the current boundary.
   - List every category and rule that touches `Utilities`,
     `Telephone Services`, `Dues and Subscriptions`, recurring bills, and
     lifestyle-creep exclusions.
   - Compare each one to the household rule.
2. Codify the boundary in the canonical classification layer.
   - Add explicit constants or comments in `dal/category_classifications.py`
     if that is the cleanest local pattern.
   - Utility-like categories should include services that are basic household
     infrastructure, such as power, water, gas, internet, and phone.
   - Subscription categories should include optional recurring services, such
     as streaming, memberships, optional apps, and entertainment subscriptions.
3. Audit and update keyword rules only where the current mapping violates the
   rule.
   - Do not rename categories casually; the budget, reports, and seed data
     already depend on the current category vocabulary.
   - If a category name is correct but its membership in a canonical set is
     wrong, prefer fixing the set membership over renaming transactions.
4. Audit `EXCLUDED_FROM_CREEP`.
   - Utility-like categories should not be flagged as lifestyle creep.
   - `Dues and Subscriptions` should remain eligible for lifestyle-creep flags
     unless the user has made an explicit exception.
5. Audit forecast and budget effects.
   - Preserve existing spend/income/transfer exclusions.
   - Preserve household-only budget behavior.
   - Ensure budget defaults still distinguish utility-like costs from optional
     subscriptions.
6. Add regression tests.
   Cover examples such as:
   - electric/water/gas rules classify as utility-like,
   - internet/cell phone rules classify as utility-like, not optional
     subscription,
   - streaming/music/Prime-style rules classify as subscription,
   - utility-like categories are excluded from lifestyle-creep flags,
   - `Dues and Subscriptions` remains eligible for lifestyle-creep flags,
   - seeder recurring categories and category constants stay internally
     consistent.
7. Update number-trust vocabulary if canonical category sets change.
   - Run the vocabulary generator/checker rather than editing generated JSON
     by hand.
8. Update data-lineage documentation if categorization semantics or canonical
   category sets change.
9. Stop for clarity on genuinely ambiguous product calls.
   - Examples that may need a note or user decision: charitable recurring
     payments, finance/data infrastructure subscriptions, and memberships that
     are optional but operationally useful.
   - If the best answer is to keep an ambiguous item unchanged, document why in
     the outcome.

Implementation notes:

- This is an audit and boundary-hardening task, not a broad category taxonomy
  rewrite.
- Prefer tests over new UI.
- Avoid changing synthetic seed totals unless a category is clearly wrong.
- Do not move `Dues and Subscriptions` into non-discretionary/lifestyle-creep
  exclusions as a blanket category.
- If a new helper such as `UTILITY_LIKE_CATEGORIES` or
  `OPTIONAL_SUBSCRIPTION_CATEGORIES` is added, make downstream usage explicit
  and covered by tests.

## Verification

Minimum verification:

```powershell
python -m py_compile dal\category_classifications.py dal\categorization.py dal\lifestyle.py scripts\number_trust_vocabulary.py
python -m pytest tests\test_flow_classification.py tests\test_cashflow_invariants.py tests\test_phase6.py tests\test_golden_seed.py tests\test_audit_vocabulary.py -q
```

If canonical category sets or number-trust vocabulary changed:

```powershell
python scripts\generate_number_trust_oracle_vocabulary.py --check
python scripts\generate_number_trust_oracle_vocabulary.py
python -m pytest tests\test_audit_vocabulary.py -q
```

If category behavior changes could affect promoted proofs:

```powershell
python scripts\audit_number_trust.py --db data\dummy.db
node scripts\number_trust_oracle.mjs --db data\dummy.db
```

Targeted inspection:

```powershell
rg -n "Utilities|Telephone Services|Dues and Subscriptions|subscription|utility|EXCLUDED_FROM_CREEP|INCOME_EXCL_FROM_INC" config dal tests docs\data-lineage scripts
```

## Done Criteria

- The subscription-vs-utility decision rule is encoded in code comments,
  constants, tests, or docs where future agents will see it.
- Utility-like recurring costs are not treated as optional subscriptions.
- Optional subscriptions remain eligible for lifestyle-creep review.
- Budgets, cash-flow, forecast, and number-trust vocabulary tests pass.
- Any ambiguous items are surfaced in the outcome with the recommended next
  decision.
- The outcome section lists what changed, what was intentionally left alone,
  and why.

## Outcome

Completed 2026-05-01 on branch `claude/p17-subscription-utility-classifier-audit`.

### What changed

1. **`dal/category_classifications.py`** — codified the household decision rule
   with two new constants:

   ```python
   UTILITY_LIKE_CATEGORIES = {"Utilities", "Telephone Services"}
   OPTIONAL_SUBSCRIPTION_CATEGORIES = {"Dues and Subscriptions"}
   ```

   `EXCLUDED_FROM_CREEP` now unions in `UTILITY_LIKE_CATEGORIES` so it is the
   single source of truth — adding a new utility-like category to that
   constant automatically excludes it from lifestyle-creep flagging. A long
   block comment above the constants states the rule, the rationale, and how
   to extend it.

2. **`EXCLUDED_FROM_CREEP` boundary fix** — `Telephone Services` was missing
   from the lifestyle-creep exclusion set, which meant a rate-inflation bump
   on internet/phone bills could trip a creep flag. The union with
   `UTILITY_LIKE_CATEGORIES` fixes that without re-listing the category by
   name.

3. **`config/categories.yaml`** — fixed a pre-existing first-match-wins bug
   where the generic `AMAZON|AMZN → General Merchandise` rule fired before
   `AMAZON PRIME → Dues and Subscriptions`, sending Prime renewals to the
   wrong category for live ingestion. The Prime-specific rule is now lifted
   into the Shopping block above the generic Amazon rule, with a comment
   explaining the ordering constraint. The redundant `AMAZON PRIME` token in
   the streaming-services rule was removed.

4. **`tests/test_subscription_utility_boundary.py`** — new regression suite
   (11 tests) covering: utility/subscription set disjointness; utility-like
   categories excluded from creep; `Dues and Subscriptions` stays
   creep-eligible; both sides excluded from income totals; classifier
   behavior for electric/water/gas, internet/cable/cell, streaming, music,
   audiobooks, and Prime; and seeder/recurring consistency with the
   boundary.

5. **`docs/data-lineage/lineage/auto_categorization.yaml`** — extended the
   `dal/lifestyle.py` consumer note and added a P17-T24 note block
   documenting the new constants, the boundary contract, and the ambiguous
   items intentionally left unchanged.

### What was intentionally left alone

- **`Dues and Subscriptions` membership in any creep-exclusion set.** The
  prompt explicitly forbade it, and the household uses the lifestyle-creep
  panel to review optional-subscription growth — exclusion would defeat
  that.
- **Budget defaults in `config/budgets.yaml`.** `Utilities`,
  `Telephone Services`, and `Dues and Subscriptions` already have distinct
  budget targets, so the boundary is preserved at the budget layer with no
  change.
- **Forecast exclusions (`EXCLUDED_FROM_FORECAST`).** Both utility-like and
  subscription spending are real spending and should feed the forecast;
  neither belongs in the exclusion set.
- **Income exclusion (`INCOME_EXCL_FROM_INC`).** All three boundary
  categories were already present, so refunds in any of them stay out of
  income totals. A new test locks that in.
- **Number-trust oracle vocabulary.** None of the sets surfaced to the
  oracle (`INCOME_CATEGORIES`, `ALL_EXCL_FROM_SPEND`, `EXCLUDED_FROM_SPEND`,
  `INCOME_EXCL_FROM_INC`, etc.) changed, so the committed vocabulary JSON
  is unchanged. `python scripts\generate_number_trust_oracle_vocabulary.py
  --check` passes.
- **`config/budgets.yaml` orphan defaults `Online Services` and
  `Cable/Satellite Services`.** No keyword rule emits either category, so
  they are unused budget defaults. Out of scope for a boundary-hardening
  task; flagging here for a future taxonomy cleanup.

### Ambiguous items, intentionally left in `Dues and Subscriptions`

- **SimpleFIN** — paid finance-data infrastructure used by this app. The
  household *could* return to manual statements, so the "optional" test
  applies; classifying it as utility-like would be a stretch.
- **ActBlue** — recurring political donations. Distinct from
  `Charitable Giving` (currently scoped to UNITED WAY/RED CROSS/`DONATION`
  patterns). Renaming to `Charitable Giving` would mix political and
  charitable streams the household may want to track separately.
- **Patreon** — creator memberships. Optional, fits subscription cleanly.

All three are creep-eligible, which matches the household intent.

### Verification

All commands from the prompt's Verification section ran clean:

```
python -m py_compile dal\category_classifications.py dal\categorization.py \
    dal\lifestyle.py scripts\number_trust_vocabulary.py
python -m pytest tests\test_flow_classification.py \
    tests\test_cashflow_invariants.py tests\test_phase6.py \
    tests\test_golden_seed.py tests\test_audit_vocabulary.py \
    tests\test_subscription_utility_boundary.py -q
# → 59 passed in 4.52s

python scripts\generate_number_trust_oracle_vocabulary.py --check
# → Vocabulary is up to date
python -m pytest tests\test_audit_vocabulary.py -q
# → 4 passed
```

### Follow-ups

- `Online Services` and `Cable/Satellite Services` budget defaults have no
  classifier rule wiring. Consider deletion or addition of corresponding
  keyword rules in a future taxonomy task.
- If a future split breaks `Telephone Services` into separate `Internet
  Services` and `Mobile Services` categories, both new categories must be
  added to `UTILITY_LIKE_CATEGORIES` (the existing test suite will fail
  loudly otherwise).
