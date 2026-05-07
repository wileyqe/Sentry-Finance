# P17-T40: Number-Trust DOM Migration Sweep

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/53

## Context

P17-T36 settled the number-trust design questions. Q3 chose option C — a default
DOM builder with named overrides — over a fully declarative or fully hand-coded
approach. T39 builds the default builder and pilots it on `dashboard.kpis`.
This slice (T40) sweeps every other surface in the registry onto the same
machinery, collapsing the 2232-line DOM script into a small dispatch layer plus
a handful of hand-coded named handlers for the genuinely quirky entries.

This is an AFK overnight slice for Codex or Claude. It is the final DOM-side
slice of the P17-T36 design and unblocks nothing further in this design.

## Starting State

- `scripts/audit_number_trust_dom.py` is 2232 lines of mostly-repetitive
  `DomExpectation` construction plus per-surface formatter glue.
- `docs/audits/number-trust/ui-number-registry.yaml` carries 21 non-dashboard
  surfaces with ~135 value entries:
  `dashboard.spending_budget_recurring`, `transactions.table`,
  `cash_flow.headline`, `cash_flow.detail_panels`, `reports.summary`,
  `reports.flow`, `accounts.header`, `investments.overview`,
  `investments.holdings`, `investments.allocation`, `budgets.summary`,
  `budgets.categories`, `review.monthly.kpis`, `review.monthly.pretax`,
  `review.monthly.detail`, `review.yearly.kpis`, `review.yearly.tax`,
  `review.yearly.detail`.
- T37 added the registry fields used by the validator and the optional
  `dom_builder:` slot for named overrides.
- T38 owns the comparator; T39 owns the default builder and migrated
  `dashboard.kpis` end-to-end.
- The validator from T37 already enforces "default-buildable shape OR named
  builder" but the rest of the registry has not been migrated yet, so most
  entries currently lean on the hand-coded path.

## Task

1. Read the T39 outcomes (default builder shape, naming convention for
   override functions, how `dashboard.kpis` was migrated), the validator
   from T37, and the comparator from T38. Skim
   `scripts/audit_number_trust_dom.py` end-to-end before changing anything so
   the surface-by-surface quirks are in your head.
2. Walk the registry in `docs/audits/number-trust/ui-number-registry.yaml`
   surface-by-surface (skip `dashboard.kpis` — already done by T39). For each
   value entry decide:
   - **Default-buildable**: single `selector`, simple formatter, no
     conditional render, no animation/timing race, no multi-element fan-out,
     no popover/hover gating. Leave the entry without a `dom_builder` so the
     validator demands the default shape; delete the matching hand-coded
     `DomExpectation` glue.
   - **Quirky**: declare `dom_builder: <descriptive_name>` on the entry and
     port the existing hand-coded logic into a named builder function in
     `scripts/audit_number_trust_dom.py`. Keep the function self-contained
     and reuse the registry's `selector`, `formatter`, and
     `view_states`/`owner_scope` whenever possible; only the truly bespoke
     logic should live in the function body.
3. Common quirk patterns to expect named overrides for:
   - Multi-selector fallbacks like `dashboard.credit_scores.latest`'s
     `[data-testid^='dashboard-credit-score-'], [data-testid='dashboard-credit-score-empty']`.
   - List/aggregate values where the DOM check counts elements rather than
     reading text (likely `transactions.table`, `investments.holdings`,
     `budgets.categories`).
   - Render-shape branches that aren't reducible to `owner_scope:
     household_only` (i.e. the value is shown in every view but the markup
     itself differs).
   - Animation/transition timing where the default `wait for stable` is too
     loose.
   - Popover/tooltip values that need a hover or click before they exist in
     the DOM.
   If a surface is entirely quirks, declare named overrides for all of its
   entries — do not contort an entry into the default shape just to claim it
   was migrated.
4. Prefer one commit per surface so a mid-sweep proof-gate breakage can be
   reverted to the previous green surface. The final commit ties the sweep
   together (line-count drop confirmation, validator/proof-gate green,
   orphan-handler check).
5. Add a small audit/test (a focused pytest case or a script invoked from
   the proof gate) that grep-checks `scripts/audit_number_trust_dom.py` for
   builder-shaped functions that no registry entry references — orphaned
   hand-coded DOM logic should fail loudly so future drift is caught at PR
   review.

## Non-Goals

- Do not touch `dashboard.kpis` — T39 already migrated it.
- Do not modify the default builder. If you find a real gap, file a follow-up
  issue describing the shape that defeated the default and add a TODO comment
  pointing at it; do not extend the builder inline.
- Do not change the comparator (T38) or the registry schema (T37).
- Do not touch oracles or the API audit path.
- Do not bypass the validator. Every `api_oracle` entry must satisfy the
  default-buildable shape or name an existing builder by the end of this
  slice.
- Do not migrate `registered_pending` entries beyond what the validator
  already requires of them.

## Verification

- Run the registry validator from T37 against the full registry. Every
  `api_oracle` entry must satisfy default-buildable shape OR reference an
  existing named builder.
- Run the canonical proof gate end-to-end:
  `python scripts/run_number_trust_proof.py`. It must exit clean with the
  same surface coverage as before the sweep.
- Confirm the DOM script line-count drop. Target ~500–700 lines vs. the
  starting ~2232 lines; record the actual number in the PR description and
  in the post-merge outcomes section of this prompt file.
- Run the new orphan-handler check. Any builder function defined in
  `scripts/audit_number_trust_dom.py` that no registry entry references must
  fail it.
- Run any dashboard/number-trust tests that touch the DOM script directly
  (e.g. existing `tests/test_audit_number_trust_dom*.py` if present), plus a
  smoke run of the proof gate against the trusted seed view-state matrix.

## Agent Shutdown

Use branch `codex/p17-t40-number-trust-dom-migration-sweep` or
`claude/p17-t40-number-trust-dom-migration-sweep`. Commit and stop. Do not
merge. If the proof gate breaks mid-sweep and cannot be cleanly resolved
within the slice, stop at the last green surface commit and surface the
failing surface in the PR description rather than papering over it.

## Outcome

Completed on branch `codex/p17-t40-number-trust-dom-migration-sweep`, stacked on
`origin/codex/p17-t39-number-trust-default-dom-builder-pilot`.

- Migrated every non-`dashboard.kpis` `api_oracle` DOM surface to registry
  dispatch via named `dom_builder` overrides. `dashboard.kpis` remained owned
  by T39's default-builder pilot.
- Collapsed `scripts/audit_number_trust_dom.py` from 2335 lines to 745 lines
  by moving the shared DOM formatting and rule table into
  `scripts/number_trust_dom_rules.py`.
- Added orphan-builder enforcement through both
  `tests/test_audit_number_trust_dom_builders.py` and the DOM audit entrypoint,
  so unreferenced builder handlers fail loudly.
- Full proof gate passed:
  `docs/audits/number-trust/reports/number-trust-proof-20260506-195225.md`.
  The final DOM report was
  `docs/audits/number-trust/reports/number-trust-dom-20260506-195520.md`.
- Surface coverage remained green: 616 selector-backed DOM checks, 0 DOM diffs,
  399 registered value/view contexts, 396 touched, 3 uncovered.

No default-builder gaps or blockers were found.
