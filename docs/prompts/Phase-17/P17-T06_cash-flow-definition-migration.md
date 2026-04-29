# P17-T06 Cash Flow Definition Migration

## Context

The trust review found that Cash Flow, Reports flow, and Reports summary could
serve similar income/spending/net numbers through different definitions. The
accepted user decision was to use `dal.flow_aggregation.compute_period_totals`
as the canonical cash-out/gross-up definition across Dashboard, Cash Flow, and
Reports.

## Starting State

- Cash Flow period detail already consumed `compute_period_totals`.
- Reports flow/Sankey already consumed `compute_period_totals`.
- Reports summary had begun consuming `compute_period_totals`, but its public
  response still only exposed income, spending, net, top categories, and
  category count. It did not expose the savings-rate and debt-movement fields
  needed to prove the same lens end to end.
- The parity test wall covered Cash Flow period detail vs Reports flow, but
  not Reports summary.

## Task

1. Keep `dal/reports/spending.py::get_period_summary` on
   `compute_period_totals`.
2. Extend `/api/reports/summary` with the canonical fields:
   `savings_rate`, `debt_service`, `debt_accumulated`, `debt_paid_down`,
   `net_debt_change`, and a `definition` marker.
3. Add Reports summary to the Cash Flow/Reports parity test wall.
4. Extend the number-trust audit so Dashboard's monthly-net-flow summary
   checks the full canonical lens fields.
5. Update roadmap and number-trust evidence docs so the old mismatch is no
   longer treated as an open migration.

## Verification

- `python -m pytest tests/test_cashflow_reports_parity.py -q`
- `python -m pytest tests/test_audit_vocabulary.py -q`
- `python -m ruff check dal/reports/spending.py scripts/audit_number_trust.py tests/test_cashflow_reports_parity.py`
- `$env:SENTRY_DB_PATH="$PWD\data\dummy.db"; $env:SENTRY_DB_MODE="trusted"; python scripts/seed_dummy_data.py`
- `python scripts/audit_number_trust.py --db $env:SENTRY_DB_PATH`
- Full backend suite before completion because the API contract feeds Dashboard
  and Reports.

## Outcome

Cash Flow period detail, Reports flow, and Reports summary now share the same
canonical definition at the API/DAL level. Remaining trust work is no longer
about definition mismatch; it is about owner/view/date certainty, registry
coverage, independent oracle strength, and rendered DOM proof.
