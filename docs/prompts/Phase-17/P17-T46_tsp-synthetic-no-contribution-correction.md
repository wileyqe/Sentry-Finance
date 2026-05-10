# P17-T46: TSP Synthetic No-Contribution Correction

## Context

P17-T45 found that the canonical trusted seed models monthly TSP contribution
transfers even though the expected real TSP posture is retired/no-contribution.
This creates a false cash-flow and accountability shape for the household's
largest investment account.

## Starting State

- `scripts/dummy_data/generator.py` includes `tsp_synthetic` in
  `TRUSTED_INVESTMENT_ACCOUNT_SPECS` with `$100,000` starting balance,
  `$1,500/mo`, and `TSP CONTRIBUTION TRANSFER`.
- `tests/test_trusted_seed.py` asserts 36 TSP contribution transfers,
  final TSP value of `$154,000`, and TSP tax-bucket row counts based on
  contribution-driven snapshot dates.
- `docs/DUMMY_DATA_GENERATION_SPEC.md`, data-lineage `investment_contribution`,
  and some number-trust audit notes still describe TSP monthly transfers.

## Task

1. Remove recurring TSP contribution cash legs from the canonical trusted seed.
2. Keep Acorns/Fidelity contribution coverage intact for generic Shape-B
   investment-transfer tests.
3. Choose the smallest TSP snapshot policy that preserves Investments page
   coverage without implying new money: likely start/end or explicit
   statement-like anchors.
4. Update seed expectations, data-lineage docs, and dummy-data docs.
5. Rebaseline any generated proof fixtures only if the existing verification
   flow requires it.

## Non-Goals

- Do not remove all investment contribution coverage.
- Do not model live TSP credentials, scraper behavior, or old P2 connector work.
- Do not add partner data or trust-bar claims.

## Verification

- `python scripts/seed_dummy_data.py`
- `pytest tests/test_trusted_seed.py tests/test_investment_contributions_view.py tests/test_accountability.py`
- `python scripts/audit_reference_clock_usage.py`
- Run the existing number-trust proof gate if trusted seed fingerprints or
  registered visible values move.
