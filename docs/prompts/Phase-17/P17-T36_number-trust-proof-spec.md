# P17-T36: Number-Trust Proof Metadata/Spec Design

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/39

## Context

The number-trust proof now spans registry YAML, Python raw-fact oracles,
Node second-language oracles, DOM selector expectations, and the one-command
proof gate. Adding one visible value still requires touching several file
types. Some duplication is intentional: independent Python and Node math is
the proof, not waste. The design decision is where metadata should become
declarative without collapsing oracle independence.

This is HITL. Do not implement until the user and an agent review the design.

## Starting State

- `docs/audits/number-trust/ui-number-registry.yaml` declares surfaces,
  values, view states, selectors, and audit stages.
- `scripts/audit_number_trust.py` owns Python raw-fact expectations.
- `scripts/number_trust_oracle.mjs` owns independent Node/SQL expectations.
- `scripts/audit_number_trust_dom.py` builds selector-backed DOM checks.
- `scripts/run_number_trust_proof.py` runs the API/oracle and DOM proof.

## Design Questions

1. Which parts of a value definition should live in registry metadata:
   route, selector, formatter, view states, check id, tolerance, empty-state
   behavior, and owner behavior?
2. Which parts must remain independently implemented in Python and Node?
3. Should DOM expectations be generated directly from registry metadata, or
   should registry metadata only validate hardcoded builders?
4. How should registered-but-not-selector-backed values be represented?
5. What is the smallest first implementation slice after the decision?

## Non-Goals

- Do not implement during the design issue.
- Do not remove the second-language oracle.
- Do not centralize Python and Node math into one shared implementation.
- Do not weaken current proof coverage.

## Verification For Later Implementation

- Registry validation catches missing route/selector/view-state metadata.
- Existing proof reports remain 0-diff.
- Python and Node expected values remain independent.
- DOM selector checks remain at least as complete as before.

## Agent Shutdown

For the HITL design issue, do not commit code. Produce a recommended design
and proposed AFK follow-up slices for user approval.

## Outcomes (post-decision, 2026-05-05)

**Status:** `[v]` design complete. Issue #39 closed. Decision tree resolved through a 5-question grilling session; AFK implementation fan-out is tracked as five new sibling slices (T37–T41).

### Decision summary

**Q1. Math vs wrapper.** "Math" = the SQL/Python that produces the value. Stays independently duplicated in Python and Node oracles — that duplication IS the proof. "Wrapper" (route, selector, formatter, view_states, check_id, owner-scoping rule, empty_state, display_precision) becomes declarative in the registry. Tolerance is dead: both oracles round to the registry's `display_precision` and the comparator does exact equality. Round-then-exact filters float ULP noise (legitimate independence preserved) while making real cent-level disagreements visible immediately.

**Q2. Three new declarative fields, one concept deleted.**
- ADD `display_precision` (e.g. `0.01` cents, `0.1` months, `1` integer, `100` basis_points).
- ADD `empty_state` (`null` | `zero` | `"no_data"`).
- ADD `owner_scope` (`household_only` | `owner_aware` | `per_owner`) — contract, not algorithm; oracles each write their own WHERE clause.
- DELETE tolerance field/concept entirely.
- KEEP duped: category exclusion lists. Python pulls from canonical `dal/category_classifications.py`; Node hand-codes its own. That dup is the proof of the canonical list — moving it to registry would collapse the proof.

**Q3. DOM check refactor — option C (default builder + named overrides).** The DOM check is NOT a third oracle; it proves "rendered text == formatter(API value) at display_precision." Default builder reads registry fields and generates the assertion mechanically. Quirky entries (multi-selector fallback, conditional render, animation timing, popover gating) declare `dom_builder: <name>` referencing a hand-coded handler. Validator: every entry without `dom_builder` must satisfy default-buildable shape. ~2232-line DOM script collapses to ~500–700 lines after full migration.

**Q4. Binary `audit_stage` with TTL.**
- `registered_pending` — selector/dom_builder/oracle all optional. Must declare label, formatter, view_states, empty_state, owner_scope, display_precision, AND `pending_since` (ISO date).
- `api_oracle` — must satisfy default-buildable shape; oracle in both Py and Node.
- TTL: validator fails if entry is `registered_pending` AND `pending_since` is more than 60 days old. Forcing function — without it the pending bucket becomes a junk drawer.

**Q5. Five implementation slices.**
- **T37** — Schema + validator + backfill. Foundation. Independent. Issue [#50](https://github.com/wileyqe/Sentry-Finance/issues/50).
- **T38** — Comparator display-precision exact equality. Strip tolerance. Surfaces hidden Py/Node divergences as escalation-required blockers. Blocked by T37. Issue [#51](https://github.com/wileyqe/Sentry-Finance/issues/51).
- **T39** — Default DOM builder pilot on `dashboard.kpis`. Prove pattern on small surface. Blocked by T37+T38. Issue [#52](https://github.com/wileyqe/Sentry-Finance/issues/52).
- **T40** — DOM migration sweep across remaining ~21 surfaces. Blocked by T37+T38+T39. Issue [#53](https://github.com/wileyqe/Sentry-Finance/issues/53).
- **T41** — `pending_since` TTL enforcement. Independent code path; can land in parallel with T39/T40. Blocked by T37 only. Issue [#54](https://github.com/wileyqe/Sentry-Finance/issues/54).

Ship order: 1 → 2 → 3 → 4 → 5. T41 can run in parallel with T39 and T40 once T37 lands.

### Sociotechnical safeguard preserved

The "round at display precision then exact equal" rule was specifically chosen over full-precision tolerance to avoid the convergence trap: under fuzz pressure, the second oracle's author looks at the first oracle's code and copies its order-of-operations until proof passes, collapsing independence into translated copies. Display-precision rounding cuts ULP noise without that pressure — both oracles can use independently-ordered sums and still produce `$1,234.56` exactly. Real cent-level bugs surface immediately.
