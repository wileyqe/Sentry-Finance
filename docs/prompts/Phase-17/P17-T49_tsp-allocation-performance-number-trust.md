# P17-T49: TSP Allocation And Performance Number-Trust Expansion

## Context

P17-T45 found that current TSP allocation metadata covers the expected
L2065/C/S holdings, but visible TSP allocation, X-Ray, tax, and YTD return
values need explicit proof before trust-bar readiness.

## Starting State

- `fund_composition` covers TSP_C, TSP_S, TSP_I, TSP_F, TSP_G, TSP_L2065, and
  TSP_LINCOME.
- `fund_sector_weights` covers TSP_C, TSP_S, and TSP_I directly; lifecycle
  sector exposure is derived through composition.
- `extractors/tsp_investment_details.py` parses per-fund `ytd_return` and
  `fund_name`.
- `investment_details.as_of` is currently stored by `backend/result_writer.py`
  as the writer's current date.

## Task

1. Register/prove TSP allocation, X-Ray, tax-bucket, and per-fund YTD values
   that are visible on Investments or account details surfaces.
2. Decide how source dates should flow into `investment_details.as_of`.
3. Add proof coverage for `TSP_L2065`, `TSP_C`, and `TSP_S` metadata.
4. Document how annual lifecycle composition updates should happen.
5. Coordinate with issue #80 before changing asset-class performance code or
   `dal/investments.py`.

## Non-Goals

- Do not implement performance-by-asset-class internals if #80 owns them.
- Do not invent live TSP YTD values.
- Do not change Fidelity parser/audit/cost-basis files.

## Verification

- Run relevant investment-detail and number-trust proof tests.
- Run the one-command number-trust proof gate if registry or visible values
  change.
- Run `python scripts/audit_reference_clock_usage.py` if date semantics change.
