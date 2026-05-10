# P17-T45: TSP Live-Shape Alignment

## Context

TSP is the household's largest investment account and therefore the largest
single data-trust risk when stale or modeled incorrectly. The current roadmap
calls out one specific mismatch: the trusted synthetic seed models monthly TSP
contributions, while the real household posture says no new TSP contributions
are expected because the owner is retired.

This slice is an audit-and-scoping pass. It should align the synthetic story,
document-drop parser, price interpolation path, investment details path, and
cash-flow/accountability interpretation before any live connector or TSP
implementation work claims trust-bar readiness.

## Starting State

- `docs/HOUSEHOLD_PROFILE.md` says TSP has no new contributions, is held for
  ease of use and low fees, is roughly allocated across L2065/C/S funds, and
  is the largest investment account by far.
- `docs/ARCHITECTURE.md` treats TSP as planned Tier 2 semi-automation plus
  Tier 3 document drop. It also names TSP staleness as a major risk: stale TSP
  makes net worth unreliable and should surface through freshness nudges.
- `docs/prompts/Phase-2/P2-T01_tsp-connector.md` is an older connector prompt.
  It is useful background, but some details are stale or intentionally
  deferred. Do not treat it as the current source of truth without verifying
  live code and docs.
- `dal/parsers/tsp_statement.py` parses TSP statement PDFs and commits
  `balance_snapshots`, per-fund `investment_holdings`, `portfolio_snapshots`,
  ticker metadata, and a placeholder traditional `tax_buckets` row.
- `dal/tsp_prices.py` fetches or loads TSP share prices and can interpolate
  daily holdings from statement-anchored units. Its module docstring assumes
  a retired/no-contribution account where units are constant between
  statement anchors.
- `extractors/tsp_investment_details.py` parses per-fund YTD return from the
  TSP investments page text and uses the same ticker mapping as the statement
  parser.
- `scripts/dummy_data/generator.py` currently treats synthetic TSP like the
  other trusted investment accounts: starting balance plus deterministic
  monthly investment transfers and `BUY` rows. That is useful for generic
  transfer/linkage tests but conflicts with the real no-contribution TSP
  posture.
- Flow/accountability reports already account for future TSP-shaped brokerage
  transfers through `positions_ledger.bank_txn_id`, but real TSP should not
  imply monthly bank-side contribution cash legs unless actual evidence
  appears.

## Task

1. Read `CLAUDE.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`,
   `docs/HOUSEHOLD_PROFILE.md`, this prompt, and the TSP-related code paths
   named in Starting State.
2. Run the Graph Context Check for TSP live-shape alignment and record any
   relevant files/tests/docs that the graph adds beyond this prompt.
3. Create a TSP live-shape audit under `docs/audits/tsp-live-shape/` with:
   - a live-shape contract for balances, per-fund units, NAV/price,
     allocation, YTD/performance data, tax buckets, and inter-fund transfers;
   - a mismatch ledger comparing trusted synthetic behavior, statement
     parser behavior, price interpolation, investment details scraping, and
     expected real TSP behavior;
   - explicit severity for each mismatch (`block`, `gap`, `cosmetic`) and a
     recommended owner slice for each follow-up.
4. Decide whether the trusted synthetic seed should stop modeling monthly TSP
   contribution transfers. If changing it is recommended, scope the smallest
   safe implementation slice and name every test/report likely to move.
   If keeping the current synthetic contribution pattern temporarily, document
   the compatibility reason and make the mismatch explicit.
5. Audit the statement parser contract:
   - per-fund unit precision and ticker mapping;
   - top-line balance vs per-fund sum agreement;
   - placeholder `tax_buckets` behavior and whether it is acceptable for live
     trust;
   - behavior when a TSP statement is recognized but per-fund detail is missing.
6. Audit `dal/tsp_prices.py` as the no-contribution market-movement path:
   - confirm constant-unit interpolation is valid between statement anchors;
   - confirm price-source freshness and failure behavior are safe;
   - confirm interpolated holdings do not invent bank-side cash flows.
7. Audit per-fund performance/allocation surfaces:
   - how `extractors/tsp_investment_details.py` provides YTD return;
   - how TSP funds map through allocation and X-Ray composition tables;
   - whether `TSP_L2065`, `TSP_C`, and `TSP_S` have enough metadata for the
     Investments page and number-trust proof.
8. Audit inter-fund transfer expectations. Real TSP may have future
   inter-fund-transfer events, but these should be intra-account share
   reallocations, not income, spending, or user contributions. Define the
   event shape that future code should use and what must be excluded from
   cash-flow/accountability reports.
9. Produce follow-up prompt skeletons for any implementation slices surfaced
   by the audit. Likely candidates include:
   - synthetic TSP no-contribution correction;
   - TSP statement parser hardening;
   - TSP price interpolation/freshness hardening;
   - TSP allocation/performance number-trust expansion;
   - future inter-fund-transfer modeling.
10. Update `docs/ROADMAP.md` with the issue link and any scoped follow-up
    slices. Do not mark this task complete until the audit deliverables exist.

## Non-Goals

- Do not log into live TSP, scrape my.tsp.gov, or use credentials in this
  slice.
- Do not implement the old P2-T01 TSP connector prompt wholesale.
- Do not add or remove migrations unless the audit discovers a truly blocking
  schema mismatch and the user explicitly redirects this slice into
  implementation.
- Do not start partner-integration work or cross the trust-bar hard line.
- Do not rewrite Fidelity, Acorns, or generic investment flows except to
  document how TSP should differ.
- Do not invent live TSP contribution transactions. Real bank-side or payroll
  evidence must drive any future contribution-like row.

## Verification

- Audit docs exist under `docs/audits/tsp-live-shape/` and include both a
  live-shape contract and mismatch ledger.
- The audit explicitly answers whether synthetic TSP monthly contributions
  should be removed, retained temporarily, or split into a separate synthetic
  fixture mode.
- The audit names follow-up implementation slices with scope, non-goals, and
  likely verification commands.
- Docs are checked against live code paths listed in this prompt.
- If this slice remains docs-only, no code tests are required. If code changes
  are made despite the intended audit scope, run the relevant tests for touched
  modules plus `python scripts/audit_reference_clock_usage.py`.

## Agent Shutdown

Use a branch named for the agent lane, for example
`codex/p17-t45-tsp-live-shape-alignment` or
`claude/p17-t45-tsp-live-shape-alignment`. Commit the prompt/audit work with a
clear message. Do not merge. Leave a summary with: audit files produced, the
synthetic-contribution decision, follow-up slices created, and any live-data
questions that still require the user.
