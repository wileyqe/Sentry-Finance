# Subagent Reliability Experiments

Archived from `docs/data-lineage/AGENT_GUIDE.md` during the agent-docs cleanup.
Keep this as background evidence; the active operating rule lives in
`AGENT_GUIDE.md`.

## Session 2: Explore Was Useful For Shape, Not Citations

The initial Explore subagent returned a structural map that was useful for
shape, but specific `file:symbol` claims were unreliable. Examples included
claims for `attribution.py:apply_monthly_attribution:104` and
`debt.py:get_mortgage_payment_txns:591`; neither function existed. The actual
names were `apply_attribution_single` and
`decompose_unsplit_mortgage_payments`.

Takeaway: treat subagent line numbers and function names as hypotheses, not
facts. Run a direct grep or read against the cited file before pasting a
citation into a YAML record.

## Session 4: Verbatim Quotes Did Not Fix Citation Drift

A follow-up experiment used a subagent prompt that required a verbatim 1-3 line
code quote alongside each `file:line:symbol` citation. Eight random spot-checks
found only 2 of 8 citations were accurate.

Observed failure modes:

- Hallucinated function names such as `get_monthly_cash_out` and
  `get_monthly_spending`.
- Misattributed file paths, such as claiming `compute_period_totals` was in
  `dal/payroll.py` when it was in `dal/flow_aggregation.py`.
- Line numbers off by 70+ lines for real functions.
- Quote text copied from one file but labeled with another file or line.

Takeaway: quote requirements can catch some misquotes, but they do not make
subagents citation-authoritative.

## Session 5: Sonnet Improved Citation Accuracy But Missed Transitive Completeness

A later experiment used a Sonnet-level Explore subagent with tight constraints:
cap 30 tool calls, require a verbatim quote per citation, forbid speculation,
use a structured output format with a self-grade footer, and perform a narrow
enumeration task for consumers of `derived_summaries`.

All 5 router-level citations spot-checked clean. What the subagent missed was
transitive completeness: it found obvious metrics endpoints but missed indirect
callers such as `dal/yearly_wrapup.py` calling `compute_interest_cost` and
`dal/scenarios.py` calling `recompute_net_worth`.

Takeaways:

- Sonnet-level subagents were reliable for cited direct evidence in that
  bounded experiment.
- Transitive callers still required local grep/read verification.
- Narrow prompts with explicit numbered tasks, output schema, self-grade
  footer, and tool-call caps were much more reliable than loose prompts.
