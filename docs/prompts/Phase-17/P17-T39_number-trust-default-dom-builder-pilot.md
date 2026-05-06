# P17-T39: Number-Trust Default DOM Builder Pilot (dashboard.kpis)

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/52

## Context

P17-T36 settled a design question that the DOM script had been quietly
violating: the DOM check is not a third oracle. Oracle-vs-Oracle proves math,
Oracle-vs-API proves the API, and the DOM check proves only that "rendered
text == formatter(API value) at display_precision." Just a renderer check.
No math.

`scripts/audit_number_trust_dom.py` is 2232 lines today, and the bulk of it
is per-surface boilerplate that re-derives expected text from API values
through bespoke if/else ladders. After P17-T37 expands the registry and
P17-T38 lands the comparator, most of that boilerplate becomes mechanical:
navigate → switch view → read selector → format API value → assert. A
generic builder can replace it.

This task is the pilot: build the generic default DOM builder, prove it on
ONE small, well-understood surface (`dashboard.kpis`), and leave the rest
of the script untouched. P17-T40 sweeps the other surfaces once the pattern
is proven.

This is an AFK overnight slice for Codex or Claude.

## Starting State

- `scripts/audit_number_trust_dom.py` (2232 lines) hand-rolls per-surface
  expectation builders inside `build_dom_expectations`.
- `docs/audits/number-trust/ui-number-registry.yaml` lists every audited
  value. The `dashboard.kpis` surface entries already declare `formatter`,
  `selector`, `view_states`, and `audit_stage`.
- T37 has added the additional registry fields (`display_precision`,
  `empty_state`, `owner_scope`, etc.) and the validator hook.
- T38 has reshaped the comparator. Avoid landing T39 on top of an
  in-flight T38 diff.
- The credit-score entry uses a comma-fallback selector
  (`[data-testid^='dashboard-credit-score-'], [data-testid='dashboard-credit-score-empty']`)
  and is a clear case for a named override rather than the default builder.

## Task

1. Read `docs/prompts/Phase-17/P17-T36_number-trust-proof-spec.md` for
   the design decisions, then `docs/audits/number-trust/ui-number-registry.yaml`
   (`dashboard.kpis` surface), then `scripts/audit_number_trust_dom.py`
   (header + the dashboard block in `build_dom_expectations`, lines ~270–490).
2. Add a generic `default_dom_builder(registry_entry, api_value, view_state)`
   function. Place it in `scripts/audit_number_trust_dom.py` if cohesion
   is fine, or in a new sibling module (e.g.
   `scripts/number_trust/default_dom_builder.py`) if a new module reads
   cleaner. Behavior:
   - Navigate to `registry_entry.route`.
   - Switch to `view_state` chip via the existing helper.
   - Wait for stable state with the existing wait helper.
   - Find element by `registry_entry.selector`.
   - Read text content.
   - Format `api_value` via `registry_entry.formatter` at
     `registry_entry.display_precision`.
   - Branch on `registry_entry.empty_state`:
     - `null` → assert element hidden OR an empty-state marker is shown.
     - `zero` → assert formatted text matches "$0.00" or analogous zero-format.
     - `"no_data"` → assert specific no-data text/badge per formatter convention.
   - Else: assert rendered text equals formatted value.
3. Add a named-override registry: `_dom_builders: dict[str, Callable]`.
   Entries can declare `dom_builder: <name>` in the YAML registry and the
   script dispatches to the named function. Existing bespoke handlers
   (e.g. multi-selector credit score, conditional empty-state branches)
   become entries here.
4. Migrate the `dashboard.kpis` surface to the new dispatch:
   - Entries that fit the default-buildable shape go through
     `default_dom_builder`.
   - The credit-score entry declares `dom_builder: credit_score_multiselect`
     (or similar) and a named handler is registered.
   - Any other dashboard.kpis entry that needs bespoke logic
     (conditional renders, empty-state matrix) gets a named handler too.
   - The legacy hand-coded dashboard expectations in
     `build_dom_expectations` are removed once the new dispatch covers them.
5. Leave EVERY other surface (Cash Flow, Transactions, Reports, Accounts,
   Investments, Budgets, Monthly Review, Yearly Wrap-Up) on its current
   hand-coded path. Do not touch them.
6. Extend the T37 validator to enforce default-buildable shape on entries
   without a `dom_builder`: single selector, formatter with known
   `display_precision`, `empty_state` declared, non-empty `view_states`,
   `owner_scope` declared. Run the validator across the full registry
   and confirm `dashboard.kpis` entries either pass shape or carry a
   named override.
7. Add a small unit test file (e.g. `tests/test_number_trust_validator.py`
   or co-located with the existing T37 validator tests) covering:
   - Entry with `audit_stage: api_oracle`, no `dom_builder`, no selector → fails.
   - Entry with `dom_builder: <existing-name>` → passes regardless of selector.
   - Entry with `audit_stage: api_oracle`, default-buildable shape complete
     → passes.

## Non-Goals

- Do not migrate any surface other than `dashboard.kpis`. T40 owns the sweep.
- Do not change comparator behavior. T38 owns it.
- Do not add new registry fields. T37 owns them.
- Do not touch the Python or Node oracle layers.
- Do not delete hand-coded DOM checks for surfaces other than `dashboard.kpis`.
- Do not change selectors, formatters, or display precision of audited
  values; the renderer's behavior is locked.

## Verification

- Run the canonical proof gate
  (`python scripts/run_number_trust_proof.py` or whichever entrypoint is
  current after T36/T37/T38) — full proof must remain green.
- Confirm `dashboard.kpis` DOM checks now pass via the default builder
  and named overrides, with no regression in counts vs. the prior run.
- Run the new validator tests: failure case + named-override pass case +
  default-buildable pass case.
- Capture line count of `scripts/audit_number_trust_dom.py` before and
  after. Expect a small net growth (default builder + named registry +
  small dashboard delta) — the script does NOT yet shrink. The shrink
  is T40's job.
- Run any pre-existing unit tests for the DOM script.

## Agent Shutdown

Use branch `codex/p17-t39-number-trust-default-dom-builder-pilot` or
`claude/p17-t39-number-trust-default-dom-builder-pilot`. Commit and stop.
Do not merge.
