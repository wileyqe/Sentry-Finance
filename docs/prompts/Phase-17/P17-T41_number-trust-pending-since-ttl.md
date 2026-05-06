# P17-T41: Number-Trust pending_since TTL Enforcement

GitHub issue: https://github.com/wileyqe/Sentry-Finance/issues/54

## Context

P17-T36's design grilling settled on a binary `audit_stage` model
(`registered_pending` vs `api_oracle`) with a forcing function: every
`registered_pending` entry carries a `pending_since` ISO date, and the
validator fails if any pending entry has aged past 60 days without being
promoted to `api_oracle` or removed.

The reasoning is that `registered_pending` becomes a junk drawer otherwise.
Months pass, the list grows, no proof is ever added. A hard 60-day TTL forces
the question: promote or delete.

T37 introduced the `pending_since` field and accepts any date as valid. This
slice — T41 — adds the >60-day failure check on top of T37's groundwork.

This is an AFK overnight slice for Codex or Claude. It can run in parallel
with T39 and T40 because it touches an independent code path (validator
only). It is strictly blocked by T37.

## Starting State

- T37 has merged: `pending_since` field is required on every
  `registered_pending` entry and is populated for the current registry.
- The validator (extended in T37) accepts any ISO date for `pending_since`.
- `dal.clock.reference_date()` is the canonical date source per CLAUDE.md
  "Project Shape" — synthetic and live dates share one reference clock.
- `python scripts/audit_reference_clock_usage.py` polices wall-clock usage.
- `python scripts/run_number_trust_proof.py` is the canonical proof runner.
- `docs/audits/number-trust/README.md` (or the operator guide near the
  registry) is where the rule should be documented.

## Task

1. Read the validator code added in T37, `dal/clock.py`, and
   `docs/audits/number-trust/ui-number-registry.yaml` (note the
   `audit_stage_meanings` block).
2. Extend the validator with one additional check: for every entry where
   `audit_stage == 'registered_pending'`, compute
   `(reference_date() - pending_since).days`. If the difference exceeds 60,
   fail validation with a message that names the entry id, surface, and the
   number of days overdue, and tells the operator the two acceptable
   responses ("promote to `api_oracle` with full Q3 default-buildable shape,
   or remove the entry").
3. Use the existing date-source helper if T37 added one. Otherwise call
   `dal.clock.reference_date()` directly. Do NOT use wall-clock
   `datetime.now()` / `date.today()`.
4. Hardcode the 60-day threshold as a module-level constant. Do not make it
   runtime-configurable in this slice. If runtime knobs are wanted later,
   that is a separate ticket.
5. The TTL only applies to entries where `audit_stage == 'registered_pending'`.
   `api_oracle` entries that happen to carry a `pending_since` field MUST NOT
   trip the TTL.
6. Add unit tests:
   - Fixture entry with `audit_stage: registered_pending` and `pending_since`
     61 days before `reference_date()` → validator fails with the descriptive
     message.
   - Fixture entry with `audit_stage: registered_pending` and `pending_since`
     59 days before `reference_date()` → validator passes.
   - Fixture entry with `audit_stage: api_oracle` and `pending_since` set far
     in the past → validator does NOT trip TTL.
7. Run the proof against the live registry. T37's backfill is recent, so no
   current entry should age out. If any entry is within a few days of the
   threshold or already over it, STOP, do not silently delete or promote
   anything — leave a blocker comment on the GitHub issue naming the entries
   and pause for human triage.
8. Document the rule in `docs/audits/number-trust/README.md` (or whichever
   operator guide sits next to the registry). One short paragraph: what the
   TTL is, why it exists, the two accepted responses when an entry trips it.

## Non-Goals

- Do not auto-promote stale entries to `api_oracle`. The TTL is a forcing
  function, not an automation.
- Do not auto-delete stale entries. A human decides: promote or remove.
- Do not make the 60-day threshold runtime-configurable.
- Do not touch the DOM script, comparator, or oracles.
- Do not change any registry entry's `audit_stage` or `pending_since` field
  as part of this slice.
- Do not change the `audit_stage_meanings` block beyond what's needed to
  reference the new TTL rule.

## Verification

- Run the validator's unit tests, including the three new fixtures above.
- Run `python scripts/run_number_trust_proof.py` against the current
  registry — must pass.
- Run `python scripts/audit_reference_clock_usage.py` — must pass; the new
  code uses `dal.clock.reference_date()`, not wall-clock.
- Confirm by hand that the failure message names the entry id, surface,
  days overdue, and the two operator responses.

## Agent Shutdown

Use branch `codex/p17-t41-number-trust-pending-since-ttl` or
`claude/p17-t41-number-trust-pending-since-ttl`. Commit and stop. Do not
merge. If a registry entry is at risk of tripping the TTL on land, post a
blocker comment on the issue instead of forcing the check through.
