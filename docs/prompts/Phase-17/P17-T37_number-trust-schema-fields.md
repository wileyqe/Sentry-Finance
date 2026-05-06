# P17-T37: Number-Trust Registry Schema Fields + Validator + Backfill

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/50

## Context

`docs/audits/number-trust/ui-number-registry.yaml` is the canonical source of
truth for every UI number the audit harness can see. The registry is ~1410
lines / ~140 entries, but its schema is implicit — the only hard contract is
ad-hoc presence checks inside `scripts/audit_number_trust.py._registry_diffs`.

P17-T36 grilled through the design and produced five implementation slices.
This is slice 1, the foundation. It adds three declarative fields per entry
(`display_precision`, `empty_state`, `owner_scope`), one conditional field
(`pending_since`), and a real validator that branches on `audit_stage`.
Subsequent slices read these fields: T38 (comparator uses `display_precision`,
deletes tolerance fuzz), T39 (DOM default builder reads the metadata), T40
(oracle WHERE clause reads `owner_scope`), T41 (`pending_since` >60d TTL).

This slice deliberately does NOT change runtime behavior — metadata + validator
only. The proof gate must continue to pass unchanged. AFK overnight slice for
Codex or Claude. Independent, no prerequisites.

## Starting State

- `ui-number-registry.yaml` — 1410 lines, two `audit_stage` values in use
  (`api_oracle`, `registered_pending`), no formal schema, no Pydantic / JSON
  Schema artifact.
- `scripts/audit_number_trust.py._registry_diffs` enforces a thin per-entry
  contract (label, audit_stage, api, formatter, selector, view_states, plus
  `check_id` when `api_oracle`).
- `scripts/number_trust_oracle.mjs` reads the registry as YAML in Node.
- Active formatters include `currency`, `signed_currency`, `compact_currency`,
  `currency_per_month`, `currency_per_day`, `months_one_decimal`, `integer`,
  `integer_or_label`, `percent_one_decimal`, `signed_percent_one_decimal`,
  `percent_zero_decimal`, `label`, `ratio_label`, `date_month`, `chart_point`,
  `chart_series`, plus `*_collection` variants.
- No `display_precision`, `empty_state`, `owner_scope`, `pending_since`, or
  `tolerance` fields exist in the registry today.

## Task

1. Read `docs/audits/number-trust/implementation-decisions.md` (the P17-T36
   decisions doc — confirm it covers the five-slice plan; if not, note the
   drift and proceed using this prompt as the contract), `scripts/audit_number_trust.py`
   `_registry_diffs` and surrounding helpers, `docs/audits/number-trust/ui-number-registry.yaml`,
   and `CLAUDE.md` owner-scoping + integer-cents guardrails.

2. Add a dedicated registry validator module — prefer
   `scripts/number_trust_registry_schema.py` — that owns the schema. Use a
   Pydantic model if it composes cleanly with the existing dict-shaped reads
   in `audit_number_trust.py` and `number_trust_oracle.mjs`; otherwise a
   hand-rolled validator returning a list of diff records (matching the
   existing `_registry_diffs` shape) is acceptable. Do NOT delete the existing
   ad-hoc checks in `audit_number_trust.py` — call into the new validator
   from there so behavior is additive, not a rewrite.

3. Required fields per entry (every entry, regardless of `audit_stage`):
   - `display_precision` — numeric, smallest displayed unit. `0.01` for
     currency cents, `0.1` for `months_one_decimal` / `percent_one_decimal`,
     `1` for `integer`, `100` for `compact_currency` bucketed to the hundred.
     Derivable from `formatter` when unambiguous; explicit override allowed.
   - `empty_state` — `null` (surface renders no DOM value), `zero` (renders
     formatter's zero, e.g. `$0.00`), or `"no_data"` (renders an explicit
     empty-state label).
   - `owner_scope` — `household_only`, `owner_aware`, or `per_owner`.
     Contract field both oracles read; each oracle still writes its own
     WHERE clause.

4. Conditional field:
   - `pending_since` — ISO date `YYYY-MM-DD`. Required when `audit_stage:
     registered_pending`. Forbidden when `audit_stage: api_oracle`. No TTL
     enforcement in this slice (T41 owns >60d check).

5. Validator branches on `audit_stage`:
   - `registered_pending` — required: `id`, `label`, `formatter`,
     `view_states` (non-empty, all known), `empty_state`, `owner_scope`,
     `display_precision`, `pending_since`. `selector`, `oracle`, `check_id`,
     `api`, `dom_builder` are OPTIONAL.
   - `api_oracle` — required: the same minimal set (minus `pending_since`,
     which must be ABSENT) PLUS `api`, `oracle`, `check_id`, `selector`.
     `dom_builder` is an optional opaque string reserved for T39; do not
     validate its referent.

6. Backfill every registry entry:
   - Safe defaults: `empty_state: null`, `owner_scope: household_only`.
   - Derive `display_precision` from `formatter`:
     - `currency*`, `signed_currency*`, `currency_per_month`,
       `currency_per_day` → `0.01`
     - `compact_currency` → `100` (verify against the formatter; document
       choice if `1` is correct instead)
     - `percent_one_decimal*`, `signed_percent_one_decimal`,
       `months_one_decimal` → `0.1`
     - `percent_zero_decimal*`, `integer*`, `integer_or_label`,
       `quantity_collection` → `1`
     - `label*`, `ratio_label`, `date_*`, `chart_point`, `chart_series` →
       `1` with a YAML comment noting "exact-string equality at comparator".
   - Owner-scope override list: scan for entries that should be
     `owner_aware` or `per_owner`. Primary candidates: owner-aware Dashboard
     KPIs, owner-aware Cash Flow totals, per-owner Monthly Review / Yearly
     Wrap-Up views. Cross-reference `frontend/src/lib/useOwnerApi.ts`
     callers and `view_states` declarations.
   - Empty-state override list: scan for entries that should be `zero` or
     `"no_data"`. Primary candidates: cash flow monthly totals that render
     `$0.00`, credit-score widgets with explicit empty-state labels, and
     entries pinned to `*investment_empty_views`.
   - Stamp `pending_since: 2026-05-06` (today's date when the agent runs;
     prefer `dal.clock.reference_date()` if running inside the proof env)
     on every existing `registered_pending` entry.

7. Wire the validator into existing entry points:
   - Call from `scripts/audit_number_trust.py` extending `_registry_diffs`,
     keeping the diff record shape backward compatible.
   - Add a standalone CLI: `python scripts/number_trust_registry_schema.py`
     exits non-zero on validation failure with a structured report. Hook into
     pre-commit / CI the same way `audit_number_trust.py` already is — do
     not invent a new hook system.

8. Tests. Add `tests/test_number_trust_registry_schema.py`:
   - Validator passes on the real backfilled registry.
   - Validator fails on a fixture with `audit_stage: api_oracle` and missing
     `selector`.
   - Validator fails on `audit_stage: registered_pending` without
     `pending_since`.
   - Validator fails on `audit_stage: api_oracle` WITH `pending_since`
     present.
   - Validator fails on missing `display_precision`, missing `empty_state`,
     missing `owner_scope`.
   - Validator fails on unknown `owner_scope` / `empty_state` enum value.
   - Validator passes on a fully-populated minimal `registered_pending` entry
     with no selector/oracle/check_id.

## Non-Goals

- Do NOT change the comparator. Tolerance behavior is unchanged in this slice
  — slice T38 owns the comparator rewrite and tolerance removal.
- Do NOT refactor the DOM script or introduce a default DOM builder.
  Slice T39 owns that.
- Do NOT touch the Python or Node oracles' computation logic. Both still
  produce the same numbers as before.
- Do NOT introduce new `audit_stage` values. The two-state ladder
  (`registered_pending`, `api_oracle`) is fixed.
- Do NOT enforce the >60 day `pending_since` TTL. Slice T41 owns that check.
- Do NOT migrate the existing per-language category exclusion lists. Their
  duplication between Python and Node is intentional per the P17-T36 grill;
  the dup IS the canonical-list proof.
- Do NOT add a `tolerance` field to the registry. There is no tolerance field
  to remove either; just do not introduce one.

## Verification

- `python scripts/number_trust_registry_schema.py` exits 0 against the
  backfilled `ui-number-registry.yaml`.
- `pytest tests/test_number_trust_registry_schema.py -x --tb=short` —
  all new tests pass.
- `pytest tests/test_number_trust_proof_gate.py -x --tb=short` — unchanged.
- `python scripts/run_number_trust_proof.py` — unchanged behavior end to end.
  The proof gate must continue to pass; no oracle, comparator, or DOM script
  change is permitted in this slice.
- Spot-check: open the diff on `ui-number-registry.yaml` and confirm every
  entry gained the three new fields, every `registered_pending` entry gained
  `pending_since`, and no entry lost prior fields.
- `grep -rn "tolerance" docs/audits/number-trust/ scripts/audit_number_trust.py
  scripts/number_trust_oracle.mjs` — should show no NEW occurrences of a
  registry-level tolerance concept introduced by this slice.

## Agent Shutdown

Use branch `codex/p17-t37-number-trust-schema-fields` or
`claude/p17-t37-number-trust-schema-fields`. Commit and stop. Do not merge.
