# lineage/ — per-event records

One YAML file per event type from `../events.yaml`. Filename is the
event id, lowercase_snake_case, suffix `.yaml`.

```
lineage/
├── README.md                    ← this file
├── paycheck.yaml
├── mortgage_payment.yaml
├── retail_purchase.yaml
└── …                            ← one file per event id
```

## Record schema

Every record uses the same top-level shape. Empty sections explicitly
list `[]` with a one-line note rather than being omitted.

```yaml
event_id: <stable_id, matches events.yaml entry>
label: "<human description>"
class: user_action | external_force | system_derived | system_scheduled | live_only

origin:
  file: <relative path>
  symbol: <function or class>
  trigger: <what fires it — schedule, seeder run, refresh, user action, etc.>

write_signature:
  - table: <table name>
    operation: insert | update | delete
    columns_set: [<col>, <col>, ...]
    notes: <conditionals, side effects, invariants>
  # … one entry per table written. Dual-write events list multiple.

direct_consumers:
  # Code that reads the rows this event wrote, before any further derivation.
  - file: <relative path>
    symbol: <function/query/component>
    reads: [<table.column>, ...]
    purpose: <what it does with the read>

derivations:
  # Computed values that depend on this event, transitively.
  - metric: <name, e.g. "monthly_spend_by_category">
    file: <relative path>
    symbol: <function>
    inputs: [<table.column>, ...]
    output_location: <derived_summaries row | API response field | view name>
    fan_out:
      - <list of further metrics or surfaces that depend on this>

ui_surfaces:
  # Every place a user can see this event or something derived from it.
  - page: <route or page name>
    component: <component path under frontend/src/>
    displays: <what specifically — a row, a sum, a chart series, a tooltip>
    via: <the API endpoint and the data hook>

forecast_impact:
  # If this event class feeds forecasting, recurring detection, or
  # projections, document how. Use [] with a note when N/A.
  - module: <forecasting module>
    role: input | seed | adjustment
    notes: <how the event changes the forecast>

external_effects:
  # Anything outside the DB that this event causes — SSE broadcasts,
  # files written, log lines other systems consume. Use [] with a note.
  - <description>

inferred_edges:
  # Edges static analysis could not confirm with high confidence. Each
  # entry must explain WHAT is uncertain and WHAT would resolve it.
  - <description and resolution path>

runtime_confirmed_edges:
  # Edges validated by running the seeder with logging or a similar
  # technique, if you did this pass. Otherwise [].
  - <description>

notes:
  # Caveats, ambiguities, open questions, synthetic-vs-live divergence,
  # links to related events.
  - <free-form>
```

## Field rules

- **Cite or mark inferred.** Every claim about a write or read needs a
  `file:symbol`. If you can't cite it, don't put it under
  `direct_consumers` / `derivations` — put it under `inferred_edges`
  with a one-line resolution path.
- **`columns_set` lists every column the event mutates,** including
  computed ones (`updated_at`, `effective_month`). Skip auto-managed
  identity columns (`id`, `created_at`) unless the event sets them
  non-defaultly.
- **`reads` uses `table.column` qualified names.** This is what makes
  the inverse index possible.
- **Distinguish direct consumers from derivations.** A direct consumer
  reads the raw rows. A derivation produces a new value from them.
  When in doubt: would removing this consumer change the displayed
  number, or just remove a row from a list? Latter → direct consumer.
  Former → derivation.
- **`ui_surfaces` is exhaustive.** Tooltip, hover state, sparkline,
  badge — if it's visible and derived from the event, it goes here.
- **`via`** is `<HTTP method> <path> + <hook name>`. Example:
  `GET /api/cash-flow/monthly + useCashFlowMonthly`.
- **`forecast_impact` is sparse on purpose.** Only events that feed
  `dal.forecasting`, `dal.recurring`, or `dal.lifestyle` have entries.
  Use `[]` with `notes: "no forecast impact"` otherwise.
- **`runtime_confirmed_edges`** is rarely populated this pass.
  Static analysis dominates. Add entries only when you actually ran
  logging.

## Filename convention

- Lowercase, snake_case, matches the `id` field exactly.
- One file per event. Do not combine multiple events into one file
  even when their lineage overlaps (the inverse index handles
  cross-references).
- Live-only events use the same convention; they live in this same
  directory.

## Example skeleton

For copy-paste convenience when starting a new record:

```yaml
event_id: example_event
label: "Example event for copy-paste"
class: user_action

origin:
  file: scripts/dummy_data/generator.py
  symbol: generate_transactions
  trigger: seeder run (rolling end_date), live equivalent: connector CSV row

write_signature:
  - table: transactions
    operation: insert
    columns_set: [id, account_id, institution_id, posting_date, transaction_date,
                  amount, signed_amount, direction, description, category,
                  status, raw_description, institution_txn_id, refresh_run_id,
                  created_at, updated_at]
    notes: |
      Routed through dal.transactions.upsert_transactions which
      enforces the sign/direction invariant.

direct_consumers: []

derivations: []

ui_surfaces: []

forecast_impact: []

external_effects: []

inferred_edges: []

runtime_confirmed_edges: []

notes:
  - "Skeleton; replace with real content."
```
