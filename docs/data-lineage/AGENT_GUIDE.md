# Agent Guide — Data Lineage Map

You are picking up a multi-session reference-documentation effort. This
guide is your operating manual. Read it once, then refer back as needed.

## Your job

Produce per-event-type lineage records for Sentry Finance. The current
phase and the next concrete unit of work are tracked in `STATUS.md` —
**read that first.** You are not expected to "finish the whole thing"
in one session; you are expected to advance one phase by a measurable
amount and leave the next agent a clean handoff.

## Read order before you start

1. `AGENT_GUIDE.md` (this file).
2. `STATUS.md` — current state and next concrete task.
3. `PROMPT.md` — original goal and codebase tailoring decisions
   already made; do not relitigate.
4. `SESSION_LOG.md` — what prior sessions did and learned. Especially
   the most recent 1–2 entries.
5. `ACTION_ITEMS.md` — open out-of-scope findings. Skim the open
   list so you don't re-discover known issues. If your work
   surfaces a new finding, log it there immediately (see "Log
   findings" principle below).
6. `events.yaml` — the source-of-truth type list. Pick your work
   from here.
7. `lineage/README.md` — the YAML schema and filename convention for
   per-event records (read before writing your first record).

Project-wide context:

- `CLAUDE.md` (repo root) — project guardrails. Especially the sign
  convention, DAL-only writes, and the canonical income/spending
  exclusion patterns.
- `docs/ARCHITECTURE.md` §3 (process model + post-commit pipeline)
  and §4 (data architecture).

## Operating principles

### Code is ground truth

If a YAML disagrees with code, fix the YAML. The map describes the
codebase as it is, not as it ought to be. If the code looks wrong,
note it under `inferred_edges` or `notes` in the affected record and
flag it in `STATUS.md > Known gaps and parking lot` — but do **not**
fix the code in this effort.

### Cite or mark `inferred`

Every claim about a write or read must cite a `file:symbol`. If you
cannot cite it, mark the edge `inferred` and explain what would
resolve it (a runtime trace, a deeper code read, a question for the
user). Silent guesses are worse than no entry.

### Direct consumers vs derivations

- **Direct consumer** — code that reads the rows the event wrote,
  before any further computation. (e.g. the transactions list page
  reads `transactions` rows directly.)
- **Derivation** — computed value built from those rows. (e.g.
  `monthly_spending` per category sums `transactions.signed_amount`.)

The distinction matters for debugging; keep them in separate sections
of the YAML.

### UI surfaces are exhaustive

A tooltip, hover state, sparkline on a card — if it displays anything
derived from the event, it goes in `ui_surfaces`. Don't omit "small"
surfaces. The whole point is that an audit pipeline can list every
visible consumer of an event.

### Synthetic-vs-live divergence is information

If the seeder produces an event the live system does not, or vice
versa, flag it in the `notes` section of the affected record. The
synthetic dataset is the focus, but divergence is itself useful
output.

### Do not modify code

This effort is documentation. Do not edit `dal/`, `backend/`,
`frontend/`, `extractors/`, or `scripts/` files. If you discover a
real bug worth fixing, surface it to the user; do not fold it into a
data-lineage commit.

### Log findings to ACTION_ITEMS.md immediately

When you discover anything out of scope for the lineage map — a
suspected bug, an interpretation question, a verification gap, a
synthetic-vs-live divergence, a code smell — open `ACTION_ITEMS.md`
and add a new `AI-NNN` entry **the moment you find it**. Don't
batch them up at end of session; they'll get lost. Each entry is
2–3 lines and uses the next sequential id. The format and severity
legend are in the file's header.

The point of this discipline: the user's stated goal is
"troubleshoot, build, find logical errors, find overlaps and gaps."
Surfacing those findings durably is at least as valuable as the
lineage map itself. A finding noted only in `SESSION_LOG.md` becomes
a needle in a haystack within a few sessions.

### Use Agent (subagent) for breadth, not depth

Searching for "every UI surface that displays X" can fan out across
the frontend tree. Use subagents for breadth-first enumeration and
direct `Grep`/`Read` tools for depth on a specific file. Avoid
spawning subagents for a single grep.

Treat subagent output as a candidate hint list. Verify every
`file:symbol:line` citation directly before writing it into a YAML
record, and run your own grep for transitive callers. Prior reliability
experiments are archived in `_archive/subagent-experiments.md`.

## Workflow per event type

For each event you trace:

1. Open `events.yaml`, locate the entry, read its origin pointer.
2. `Read` the origin file at the cited symbol. Confirm the
   `write_signature` against the code.
3. `Grep` for every reader of each `write_signature.table` —
   restrict to `dal/` first, then `backend/`, then live ingestion.
   Distinguish direct consumers from derivations.
4. For every derivation, recursively trace its consumers (one hop
   into derivations is usually enough; flag deeper chains).
5. For every API endpoint that exposes a derivation, find the
   frontend hook/component that calls it. Walk to the rendered
   surface (page, card, tooltip, chart series).
6. Note any `external_effects` (SSE broadcasts, files written, log
   lines other systems consume).
7. Mark anything you couldn't confirm as `inferred_edges`.
8. Write the record to `lineage/<event_id>.yaml` following the schema
   in `lineage/README.md`.
9. Cross-check: does the record cite at least one
   `frontend/src/.../*.tsx` UI surface? If not, the event has no
   visible consumer — flag in `notes` with "no UI surface found"
   so a future review can decide if it's dead data.

## Workflow per session

1. **Open `STATUS.md`.** Identify the next batch from "Phase 2
   recommended order of attack" or whatever the current phase is.
2. **Pick a batch size you can finish.** 5–8 events is typical.
   Less if any are unfamiliar (investments, attribution, classifier).
3. **Do the work.** One event at a time; do not batch writes.
4. **Update `STATUS.md`.** Move events from "not started" to
   "complete" in the phase tracker. Add any new gaps to the parking
   lot.
5. **Append to `SESSION_LOG.md`.** Date + 5-line summary: what you
   did, what surprised you, what's open.
6. **Do not commit.** The user reviews and commits.

## Common pitfalls

- **The seeder.** The active seeder is
  `scripts/seed_dummy_data.py` and its delegate
  `scripts/dummy_data/generator.py`. (Historical note: a
  `scripts/seed_dummy_db.py` JSON-file seeder used to live next
  to it as a foot-gun; it was deleted 2026-04-26 per AI-013, so
  the underscore-vs-no-underscore confusion is no longer a
  concern.)
- **Missing the `_assert_sign_direction_invariant` choke point.**
  Every transaction insert (seeder + live) flows through
  `dal.transactions.upsert_transactions`, which enforces the canonical
  sign/direction convention. Reference it in `write_signature.notes`
  rather than re-deriving the convention per event.
- **Conflating `transactions` writes with `positions_ledger` writes
  for investment events.** Dividends and Acorns contributions write
  to BOTH tables. Capture both rows in `write_signature` plus the
  linkage (`transfer_tag`, `bank_txn_id`, `investment_link`).
- **Forgetting attribution (`effective_month`).** Income/payroll
  events get an `effective_month` stamp via `dal.attribution`
  immediately after insert. Reports that bucket by month use
  `COALESCE(effective_month, strftime('%Y-%m', posting_date))`. Note
  both columns in the relevant `direct_consumers`.
- **Forgetting transfer-tag exclusion.** Cash-flow / spending /
  income aggregates exclude rows with `transfer_tag IS NOT NULL`
  AND rows in the categorical exclusion sets from
  `dal/category_classifications.py`. Capture both filters when
  describing a derivation that reads `transactions`.

## What "done" looks like

A Phase 2 record is complete when:

- All five top-level YAML sections are populated (or explicitly
  marked `[]` with a reason).
- Every cited `file:symbol` resolves.
- At least one UI surface is named, OR a `notes` line explains why
  no UI consumer exists.
- The record passes the `STATUS.md > Validation checklist` items
  applicable to a single event.

A phase is complete when its row in `STATUS.md` flips to ✅ AND the
validation checklist passes for that phase.
