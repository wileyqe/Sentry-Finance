# P15-T03b: NFCU Rewards Regex Fix (Value-First Pattern)

## Context

P15-T03 shipped the end-to-end `rewards_points` path (connector →
`record_loan_details` → `/api/accounts` pivot → amber chip on
`AccountsPage.tsx`) on 2026-04-18, verified against a seeded row on
`summit_cc_3341`. The 251-test suite passed.

Hours later, the P15-T04 Phase A walkthrough of the live NFCU card
detail page surfaced a latent bug: the rewards balance is rendered
inside a button label formatted **`"10,142pts Rewards"`** — digits →
`pts` → `Rewards`. The T03 regex patterns in
`extractors/nfcu_connector.py` (`Rewards?\s+Points?\s+Balance` /
`Points?\s+Balance` / `Available\s+Points`) all expect the label first
and the numeric value after, so none of them match NFCU's actual DOM.

Why T03 tests passed anyway: `tests/test_rewards_points.py` exercised
the DAL, pivot SQL, and UI path by writing through
`record_loan_details` directly. The extractor regex was never
exercised against live-shaped text. Once a real refresh ran against
NFCU, `rewards_points` would come back `None` and `print(f"✗
rewards_points: not found")` would log without failing the refresh.

See `P15-T04_audit_capture_proposal.md` §"T03 rewards regex bug" for
the original surfacing. Scope-wise this is a few-line targeted fix,
but it warrants a prompt file because (a) the root cause involved an
interactive audit, not reading the code, and (b) the extractor design
shift (value-first patterns) is useful context for future connectors.

## Starting State

- `extractors/nfcu_connector.py:948-952` — the `rewards_points` entry
  in `field_patterns` holds three label-first fragments only.
- `extractors/nfcu_connector.py:1340-1359` — `_extract_field_value` is
  a staticmethod that interpolates each pattern as a label prefix into
  an assembled regex whose capture group is the value. Every field in
  the connector assumes label-first shape.
- `tests/test_rewards_points.py` — 5 tests, all hitting the DAL/pivot
  path. None exercise `_extract_field_value`.
- No existing `tests/test_nfcu_extractor.py`.
- P15-T03 roadmap entry flipped to `[v]`; T03b listed as a separate
  planned follow-up.

## Task

1. **Extend the `rewards_points` pattern list** in
   `extractors/nfcu_connector.py` with the value-first regex
   `r"(\d[\d,]*)\s*pts\s+Rewards?"`. List it **first** so it wins
   against the label-first fallbacks when both shapes co-exist on a
   page. Keep the three label-first patterns for defensive coverage
   of statement-view DOM shapes and future NFCU UI tweaks.

2. **Teach `_extract_field_value` to accept value-first patterns.**
   If a pattern already contains its own capture group (detected via
   `re.compile(r"\((?!\?:)")` — any `(` that is not the start of a
   non-capturing group `(?:`), use the pattern verbatim as the full
   regex and return group 1. Otherwise fall through to the existing
   label-first assembly. Document the shape in the docstring so
   future callers know the convention.

3. **Write extractor-level unit tests** in `tests/test_nfcu_extractor.py`:
   - Value-first with comma (`"10,142pts Rewards"`) → `"10,142"`
   - Value-first no comma (`"8450pts Rewards"`) → `"8450"`
   - Singular label (`"1pts Reward"`) → `"1"` (the `?` quantifier)
   - Case insensitive (`"10,142PTS REWARDS"`)
   - Value-first embedded in surrounding page text
   - Label-first `Rewards Points Balance: 8,450` still matches
   - Label-first `Available Points 12,400` still matches
   - Unrelated field (credit limit, dollar format) unaffected
   - `None` when no match
   - Negative: `"5000pts Loyalty"` must NOT match (not NFCU rewards)

4. **Do not touch the DAL, pivot, seeder, or UI.** T03 already
   verified those paths; T03b is surgical to the extractor.

5. **Flip the ROADMAP entry** from `[ ]` to `[v]` with a one-paragraph
   summary and a link back to this prompt.

## Verification

- `pytest tests/test_nfcu_extractor.py -x --tb=short` → all new cases
  pass.
- `pytest tests/test_rewards_points.py -x --tb=short` → still 5/5
  (T03 DAL/pivot path untouched).
- Full backend suite: `pytest tests/ -x --tb=short` → 261 passing, no
  regressions against the 251 baseline.
- `python -c "from extractors.nfcu_connector import NFCUConnector;
  print('ok')"` — connector module still imports cleanly.
- Live portal re-verification is deferred to the next NFCU refresh.
  When it runs, expect `print("   ✔ rewards_points: 10,142")` (or
  whatever the live balance reads) instead of the prior
  `✗ not found` line.

## Outcome (2026-04-18)

- `rewards_points` pattern list expanded to 4 entries; value-first
  regex listed first per the design in Task §1.
- `_extract_field_value` gained the capture-group detection. The
  pattern-authoring convention (plain string = label-first, regex
  with capture group = value-first) is now documented in the
  docstring and reusable by other connectors that hit the same DOM
  shape (Chase in P15-T05 is a likely candidate).
- 10 new tests in `tests/test_nfcu_extractor.py`; suite total 261/261.
- No DAL / seeder / UI change, per scope.

## Follow-ups surfaced

- None. The fix is self-contained and the remaining NFCU-rewards
  concerns (trend tracking, redemption-gap alerts) are already
  scoped to Phase 16.
