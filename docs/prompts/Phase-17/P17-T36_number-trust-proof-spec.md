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
