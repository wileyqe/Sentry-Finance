# P17-T38: Number-Trust Comparator Display-Precision Exact Equality

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/51

## Context

P17-T36 settled the number-trust proof's metadata-vs-math split. "Math"
(the SQL/Python that produces a value) stays independently duplicated in
Python and Node oracles --- that duplication is the proof. "Wrapper"
(route, selector, formatter, view_states, check_id, owner scoping,
empty-state behavior, display precision) becomes declarative in the
registry. Tolerance is dead: both oracles round to the registry's
`display_precision` and the comparator does exact equality.

Reasoning: float-epsilon fuzz hides real disagreements AND pressures
the oracles to converge in implementation (independence collapses
sociotechnically). Round-then-exact-equal filters ULP noise (oracles can
use independently-ordered sums and still produce `$1,234.56` exactly)
while making real cent-level disagreements visible immediately.

This is slice 2 of 5 implementing P17-T36. T37 (slice 1) adds
`display_precision` to every registry entry and lands first. T38
consumes that field, replaces all comparator fuzz, and deletes dead
tolerance code. AFK overnight slice for Codex or Claude.

## Starting State

- `docs/audits/number-trust/ui-number-registry.yaml` --- one entry per
  visible value. After T37 lands, every entry carries `display_precision`
  (cent `0.01`, integer `1`, basis points `100`, months one-decimal
  `0.1`, etc.).
- `scripts/audit_number_trust.py` --- Python raw-fact oracle plus
  Python-vs-API comparator. Helpers: `_compare`, `_compare_money_cents`,
  `_check_partition`. `_cents()` (~line 374) hardcodes `int(round(value *
  100))` as the implicit money rounding.
- `scripts/number_trust_oracle.mjs` --- Node second-language oracle.
  `cents()`, `round1()`, `round2()` (~lines 61--71) are the parallel
  hardcoded rounding primitives.
- `scripts/run_number_trust_proof.py` --- runs the proof gate end-to-end
  and dispatches both audits.
- `_check_partition` (audit_number_trust.py ~line 3559) uses
  `abs(pct_sum - expected_pct) > 0.5` --- a literal tolerance threshold,
  in scope to delete.
- `tests/test_audit_vocabulary.py` --- existing audit-vocabulary drift
  guard.

## Critical Risk: Divergence Escalation Protocol

Removing fuzz is likely to surface real Python-vs-Node oracle
disagreements that float tolerance was hiding. **These are NOT this
slice's job to fix.** They are bug-fix follow-up PRs. If a divergence
surfaces during T38:

1. Stop. Do not silently widen rounding, add an epsilon, special-case
   the comparison, or change either oracle's math to make the test pass.
2. Capture the failing check_id, both oracle outputs at full precision,
   both rounded outputs at the registry's `display_precision`, and the
   resolved diff.
3. Post a blocker comment on the T38 issue with that capture and pause
   for human triage.
4. Each surfaced divergence becomes its own bug-fix PR referencing the
   T38 issue, with its own loop closure (issue --> fix --> verify both
   oracles agree at display precision --> merge --> close). Do **not**
   bundle bug fixes with the comparator change.

The whole point of T38 is to make divergence visible. Masking it
defeats the slice.

## Task

1. Read `docs/audits/number-trust/implementation-decisions.md`,
   `docs/prompts/Phase-17/P17-T36_number-trust-proof-spec.md`, and the
   "store money as integer cents" guardrail in `CLAUDE.md`. Confirm T37
   merged and `display_precision` is present on every registry entry.
   If not, stop --- T38 is blocked.
2. Audit every numeric comparison in the proof chain across the three
   scripts. Sites: `_compare`, `_compare_money_cents`,
   `_check_partition`, the loop in `_compare_second_language_oracle`,
   the Node oracle's emitted `expected` values, and any partition-pct
   or rate aggregations.
3. Replace each comparator's implicit rounding with a single registry-
   driven helper on both sides:
   - Look up `display_precision` from the registry by `check_id` /
     value `id`.
   - Round both sides to that precision **before** comparing.
   - Exact equality afterward. No `abs(a - b) <= tol`, no
     `math.isclose`, no implicit `_cents()` for non-money fields.
4. Define rounding semantics identically across Py and Node. Recommend
   `round(value / precision) * precision` with half-to-even (Python's
   default `round`; Node needs a tiny helper to match). Document in code
   comments and the operator guide.
5. Delete dead tolerance:
   - `abs(pct_sum - expected_pct) > 0.5` in `_check_partition` --->
     display-precision rounding plus exact equality.
   - Tolerance config keys, helper names, doc refs. Final
     `grep tolerance|TOLERANCE` across the three scripts and
     `docs/audits/number-trust/` returns zero hits, or only docs
     explicitly noting "removed in T38".
6. Add an operator-guide section to `docs/audits/number-trust/README.md`
   (create the file if missing) describing the rounding rule, where
   `display_precision` lives, and how to read a comparator failure.
7. Add focused tests:
   - Differs at full precision, agrees at display precision ---> pass
     (e.g. `1234.5600001` vs `1234.5599999` at `0.01`).
   - Differs at display precision ---> fails with clear diff (e.g.
     `1234.56` vs `1234.57` at `0.01`).
   - Edge cases: `1` (integer credit scores), `100` (basis points),
     `0.1` (months of runway), `0.01` (currency).
   - Half-to-even agreement at the boundary (`0.125` ---> `0.12` at
     `0.01`) on both Py and Node.
8. Run the full proof gate. Every surfaced divergence triggers the
   escalation protocol above --- do not mask, do not bundle.

## Non-Goals

- Do **not** touch oracle math --- the SQL/Python that computes the
  values is INVIOLABLE per the P17-T36 Q1 decision. Do not reorder
  sums to make rounding align, do not change category vocabularies,
  do not migrate to integer-cents arithmetic in the Node oracle.
- Do **not** centralize the Python and Node oracles into one shared
  implementation. Independence is the proof.
- Do **not** refactor the DOM audit script (`audit_number_trust_dom.py`).
  T39 owns that.
- Do **not** add new tolerance modes, per-call display-precision
  overrides, or alternative rounding rules. Display precision is a
  registry field per entry; the comparator is dumb about its source.
- Do **not** mask surfaced divergences. Each one is a real bug or a
  real registry-data issue. Report and pause.
- Do **not** add a `tolerance` field back to the registry under any
  alternate name (`epsilon`, `delta`, `ulp_slack`, etc.).

## Verification

- T37 merged; `display_precision` present on every registry entry
  before starting.
- `python scripts/run_number_trust_proof.py` --- canonical one-command
  runner. Must end `Proof status: PASS` with a promoted report under
  `docs/audits/number-trust/reports/` and zero diffs across all
  `audit_stage: api_oracle` entries.
- New comparator unit tests pass: rounding at each documented
  precision, exact-equality after rounding, half-to-even agreement Py
  vs Node, partition-pct without the 0.5 threshold.
- `pytest tests/test_audit_vocabulary.py -q` still passes.
- Tolerance grep clean across the three scripts plus
  `docs/audits/number-trust/`:
  `tolerance|TOLERANCE|isclose|epsilon|EPSILON` returns only docs
  annotated "removed in T38". `Math.abs` / `abs()` inside oracle math
  (signed-amount magnitudes, percent-change denominators) are NOT
  tolerance and stay.
- Any surfaced divergence: escalation protocol followed, blocker
  comment posted, T38 paused. Not merged until proof gate is green.

## Agent Shutdown

Use branch `codex/p17-t38-number-trust-comparator-display-precision`
or `claude/p17-t38-number-trust-comparator-display-precision`. Commit
and stop. Do not merge. If a divergence surfaced and was escalated
rather than resolved, leave the branch open and the issue in blocker
state --- T38 only lands when the proof gate is green at display
precision.

## Outcomes (Worker 1, 2026-05-06)

**Status:** implemented on
`codex/p17-t38-number-trust-comparator-display-precision`.

- Added a registry-backed display-precision index to
  `scripts/audit_number_trust.py`.
- Replaced cent-specific comparator calls with display-precision rounding
  followed by exact equality.
- Replaced the partition percent slack check with `0.1` display-precision
  rounding followed by exact equality. The first proof run exposed that the
  invariant's old hardcoded `100.0` expected value was not display-precision
  exact for independently rounded rows; the expected side now sums each row's
  display-rounded share and compares exactly.
- Added a Node `roundToDisplayPrecision` helper using the same half-even
  boundary behavior as the Python comparator.
- Added focused tests for full-precision disagreement/display agreement,
  display disagreement, `0.01`/`0.1`/`1`/`100` precision classes,
  Python-vs-Node half-even behavior, and partition percent exact comparison.
- Added `docs/audits/number-trust/README.md` with the operator rounding
  guide.
