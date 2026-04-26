# Data Lineage Map

A per-event-type lineage map for Sentry Finance. For every distinct **type**
of event that can occur (a paycheck, a credit-card purchase, a mortgage
payment, a dividend payout, a balance snapshot, a derived metric recompute,
a notification emission, …), this directory documents the full lifecycle:

- **Origin** — where the event is produced (file:symbol).
- **Write signature** — which tables and columns it mutates.
- **Direct consumers** — code that reads the rows it wrote.
- **Derivations** — computed metrics that depend on it, transitively.
- **UI surfaces** — every page/component/tooltip that displays anything
  derived from it.
- **Forecast impact** — how it feeds projections and recurring detection.
- **External effects** — SSE broadcasts, files written, anything outside
  the DB.
- **Inferred edges** — anything static analysis could not confirm with
  high confidence.

The synthetic seeder (`scripts/dummy_data/generator.py` +
`scripts/seed_dummy_data.py`) is the focus. Live ingestion paths
(NFCU/Chase/Acorns/Fidelity/TSP scrapes, document upload, manual UI edits)
are tracked at the type level but not traced in detail this pass; divergences
from the synthetic dataset are flagged where they exist.

## Layout

```
docs/data-lineage/
├── README.md                  ← this file (purpose, how to use)
├── STATUS.md                  ← phase progress, what's done, what's next
├── PROMPT.md                  ← original prompt + codebase tailoring
├── AGENT_GUIDE.md             ← instructions for follow-on agents
├── SESSION_LOG.md             ← session-by-session summary log
├── ACTION_ITEMS.md            ← out-of-scope findings (bugs, gaps, verifications)
├── events.yaml                ← Phase 1: event type taxonomy
├── lineage/                   ← Phase 2: one YAML per event type
│   └── README.md              ← record schema + filename convention
├── inverse-index.yaml         ← Phase 3: table.column → events, surface → events
└── diagrams/                  ← Phase 4: per-event + global Mermaid
    └── README.md              ← diagram conventions
```

## Read order for a new agent

1. **`AGENT_GUIDE.md`** — your operating instructions. Read first.
2. **`STATUS.md`** — where the work is. Tells you what to pick up.
3. **`PROMPT.md`** — the original goal and the codebase-specific
   constraints already negotiated.
4. **`SESSION_LOG.md`** — what prior sessions did, what they learned,
   what they punted on.
5. **`events.yaml`** — the source-of-truth type list. Every Phase 2
   record corresponds to one entry here.

Only after those: dive into per-event YAML files in `lineage/`.

## How to use this map (intended downstream value)

- **Debugging a wrong number on a page.** Open `inverse-index.yaml`,
  find the UI surface, get the list of event types that ultimately feed
  it. Open each event's `lineage/<id>.yaml`, walk write_signature →
  derivations → ui_surfaces to find the layer where the number diverges
  from expectation.
- **Building a new feature.** Open the event types your feature touches;
  re-use existing direct_consumers and derivations rather than computing
  from raw rows again. The inverse index also surfaces existing
  consumers you might break.
- **Auditing for logical errors.** Read `events.yaml` end-to-end and
  ask: are any two events writing the same column with conflicting
  semantics? Are any UI surfaces driven by overlapping derivations that
  should be the same number? Are any data gaps (events that should
  exist but don't)?
- **Future automation.** The YAML files are machine-readable; the
  inverse index and diagrams can be regenerated from them. A schema
  drift check could load `events.yaml` and assert every named column
  still exists in the live schema.

## Caveats

- This is **reference documentation, not executable**. Code is the
  ground truth; if a YAML disagrees with code, fix the YAML.
- Inferred edges are explicitly labeled. Treat them as hypotheses, not
  facts.
- The synthetic seeder produces some events the live system does not
  (and vice versa). Each event record flags its origin context.
- The "type-level" granularity is deliberate. Two paycheck schedules
  (Alex biweekly + Jordan monthly) collapse into one `paycheck` event;
  the differences are catalogued as instances inside that record, not
  as separate types.
