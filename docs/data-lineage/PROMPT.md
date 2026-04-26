# Original Prompt + Codebase Tailoring

This file preserves the original task prompt **and** the codebase-specific
modifications negotiated in session 1, so future agents start from the
same baseline and don't relitigate decisions.

## Original prompt (verbatim, with one author note)

> # Financial Command Center — Event & Data Lineage Map
>
> ## Goal
>
> Produce an exhaustive, per-event-type data lineage map for the Financial
> Command Center, anchored on the synthetic-seeded dataset. For every distinct
> event that can occur, document its full lifecycle: where it originates, every
> table/column it writes, every derivation that consumes it, every UI surface
> that displays anything derived from it, and every downstream metric or
> forecast it influences.
>
> This is reference documentation that the audit pipeline, future debugging,
> and any new feature work will rely on. Optimize for completeness and
> accuracy, not brevity.
>
> ## Scope
>
> - Codebase: this directory.
> - Database: the SQLite schema in use (read the schema directly; do not
>   assume).
> - Data origin: synthetic seeder only, for now. Note where live ingestion
>   paths (NFCU/Playwright, email parsing) would diverge, but do
>   not trace them in detail this pass.
>
> ## Method
>
> Use static analysis as the primary tool: read the seeder, the data access
> layer, derivation modules, API/SSE handlers, and frontend components.
> Where static analysis cannot resolve a path with confidence (dynamically
> built SQL, conditional dispatch, indirect calls, ORM magic), mark the edge
> as `inferred` and explain. Do not silently guess.
>
> Where runtime tracing is feasible — e.g., adding temporary logging to the
> data access layer and running the seeder — note explicitly which edges were
> runtime-confirmed.
>
> *(Phase descriptions, YAML schema, output paths, and rules sections are
> preserved verbatim in the original task message in `SESSION_LOG.md` ↦
> Session 1, and re-encoded in machine form by `lineage/README.md` and
> `events.yaml`.)*

## Codebase-specific tailoring (decisions made in session 1)

### Granularity is type-level, not instance-level

The user clarified mid-session: the goal is to map every **type** of
event (paycheck, mortgage payment, retail purchase, dividend, snapshot,
…), not every instance. Two paychecks (Alex biweekly + Jordan monthly)
collapse into one `paycheck` event with both schedules captured as
instances inside the record.

### No live scheduler / `external_force` jobs exist

The original prompt's `external_force` class assumes background jobs
that emit interest accrual, dividend payouts, price ticks, etc.
**This repo has none.** Live external-force events arrive as
transaction rows from connector CSVs/scrapes (NFCU, Chase, Acorns,
Fidelity, TSP) via `backend/automation_worker.py` →
`backend/result_writer.persist_connector_result`, triggered by a user
clicking Refresh. For the synthetic dataset, the **seeder is the
entire production pipeline** — interest, dividends, price drift,
payroll, valuations, APY history are all produced by
`scripts/dummy_data/generator.py`.

We keep the four-class taxonomy. `external_force` rows in synthetic
mode all originate in the seeder; each carries a "live divergence"
note describing where the equivalent live edge would land.

### Schema is reconstructed from migrations

40 sequential migrations live in `dal/migrations/v01_core.py`
through `dal/migrations/v40_transfer_tag_index.py`. There is no single
DDL file. When verifying a `write_signature.table.column` exists,
walk the migrations or query the live `dummy.db`.

### `system_scheduled` will be empty

The post-commit pipeline (`backend.result_writer.run_post_commit_pipeline`)
runs categorize → reconcile → mortgage-split → derived-recompute →
alerts → goal-sync → notifications. These fire in response to a
refresh, not a clock — they are `system_derived`, not `system_scheduled`.
The `system_scheduled` class is retained in the schema for parity with
the original prompt but should remain empty unless a true scheduled
job is added in the future.

### Dual-write events are one event

Some seeder events write to two tables that look like separate events
but are one logical event:

- A Fidelity dividend writes BOTH `positions_ledger`
  (DIVIDEND, share_delta=0) AND `transactions` (Investment Income credit).
- An Acorns auto-invest writes BOTH a checking debit AND
  `positions_ledger` BUY rows AND a `transfer_tag` linkage.

Modeled as one event with multiple rows under `write_signature` plus
explicit notes on the linkage rather than two separate events.

### Output path

Files live under `docs/data-lineage/`. The original prompt rendered the
README link as `[README.md](http://README.md)` due to a markdown
artifact; corrected to plain `README.md` here.

### Live-only events are listed but not deeply traced this pass

`connector_*`, `document_upload_*`, and `user_*_crud` event types are
listed in `events.yaml` for completeness so the inverse index is whole,
but full Phase 2 lineage records for them are deferred. The synthetic
dataset does not exercise these paths, and the user explicitly scoped
them out for this pass.

### Out-of-scope today

These appear in the original prompt's category list but are produced
by neither the seeder nor the live system today. Listed in
`events.yaml` under a `not_modeled` section so they don't get silently
invented in Phase 2:

- ATM withdrawal / cash transaction
- Stock split, capital-gain distribution (separate from dividends)
- FX rate update
- Account open / close lifecycle event (PayFlex BNPL has static
  `closed_at`, no event row)
- Statement-close / cycle-close event (only the prior-cycle CC
  payment back-fill exists, which is a derived calculation in the
  seeder, not an event row)
