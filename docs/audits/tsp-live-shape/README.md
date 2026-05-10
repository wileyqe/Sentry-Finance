# TSP Live-Shape Alignment Audit

Date: 2026-05-10

Issue: https://github.com/wileyqe/Sentry-Finance/issues/79

Prompt: `docs/prompts/Phase-17/P17-T45_tsp-live-shape-alignment.md`

## Executive Decision

The trusted synthetic seed should stop modeling monthly TSP contribution
transfers in the canonical fixture. Real ongoing TSP contributions are not
expected, and keeping a synthetic `$1,500/mo` TSP cash leg trains the app,
proofs, and cash-flow/accountability views toward a false live-data shape.

The smallest safe implementation slice is a TSP-only synthetic correction:
remove TSP bank-side contribution transactions, linked monthly `BUY` ledger
rows, and contribution-driven TSP balance growth from the canonical trusted
seed while keeping Acorns/Fidelity contribution coverage for generic Shape-B
investment-transfer tests.

## Scope

This was a docs-only audit. It did not log into TSP, use credentials, scrape
live TSP, rework the older P2 connector prompt, change Fidelity paths, or edit
`dal/investments.py` / `tests/test_performance_by_asset_class.py`.

## Sources Read

- `CLAUDE.md`
- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/prompts/Phase-17/P17-T45_tsp-live-shape-alignment.md`
- `docs/prompts/Phase-2/P2-T01_tsp-connector.md` as stale background only
- `docs/DUMMY_DATA_GENERATION_SPEC.md` investment seed section
- `docs/data-lineage/ACTION_ITEMS.md`
- `dal/parsers/tsp_statement.py`
- `dal/tsp_prices.py`
- `extractors/tsp_investment_details.py`
- `extractors/tsp_connector.py` for current connector shape only
- `scripts/dummy_data/generator.py`
- `dal/investments_writes.py`
- targeted allocation/tax-bucket read paths in `dal/investments.py`

`docs/HOUSEHOLD_PROFILE.md` is referenced by `CLAUDE.md` and
`docs/ARCHITECTURE.md`, but it is absent on `origin/main` in this worktree.
The household TSP posture in this audit therefore comes from issue #79, the
P17-T45 prompt, and data-lineage AI-012.

## Graph Context Check

Command run:

```powershell
python tools\graphify\query_local.py impact "P17-T45 TSP live-shape alignment"
```

Graphify matched mostly Fidelity live-shape nodes and suggested
`tests/test_fidelity_live_shape_contract.py`, Fidelity DAL code, and older
phase prompt files. That result appears stale/noisy for this TSP-specific
slice, so the live code paths and canonical docs above were treated as the
source of truth.

## Deliverables

- `live-shape-contract.md` defines the expected live TSP data contract.
- `mismatch-ledger.md` records current mismatches, severity, and follow-up
  owner slice.
- `inter-fund-transfer-model.md` defines future inter-fund-transfer event
  semantics without income/spending/contribution leakage.

Follow-up prompt skeletons were created under `docs/prompts/Phase-17/`:

- `P17-T46_tsp-synthetic-no-contribution-correction.md`
- `P17-T47_tsp-statement-parser-hardening.md`
- `P17-T48_tsp-price-interpolation-freshness-hardening.md`
- `P17-T49_tsp-allocation-performance-number-trust.md`
- `P17-T50_tsp-inter-fund-transfer-model.md`

## Open Live-Data Questions

- What is the real TSP Roth / traditional / tax-exempt split, if any, and
  should the app store it as a user-supplied override?
- Are there any future planned payroll deposits, roll-ins, loans, withdrawals,
  or required distributions that would create real TSP cash activity?
- What is the user's desired target allocation or inter-fund-transfer policy,
  if any, so future reallocation events can be interpreted as portfolio
  decisions rather than contribution activity?
- Which TSP L Fund vintage is currently held if it changes away from L2065?
