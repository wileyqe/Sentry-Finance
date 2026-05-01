# Sentry Finance --- Architecture & Design Document

> **Living architectural contract.** Enforced invariants, system
> boundaries, and current design decisions live here. Section numbers
> are stable and cited by `CLAUDE.md` and tests --- do not renumber.
> Historical detail and decision records live under `docs/prompts/`.
>
> Last updated: 2026-04-29

## Table of Contents

1. **Mission (§1)** --- six guiding principles
2. **System Architecture (§3)** --- process model, trust boundaries,
   ingestion tiers (**§3.3**), post-commit pipeline (**§3.4**)
3. **Data Architecture (§4)** --- schema groups (§4.2), categorization
   (§4.3), reconciliation (§4.4), archival (§4.5),
   **sign convention (§4.6)**, DAL write wrappers (§4.7),
   lineage map pointer (§4.8)
4. **Analytical Engine (§5)** --- review system (§5.3)
5. **Frontend Architecture (§6)** --- pages, multi-user (§6.3),
   notifications (§6.4)
6. **Pipeline Risk Mitigations (§8)**
7. **Module Map (§9)** / **Document Tree (§10)**

**Companion docs** (load only when relevant):

- `HOUSEHOLD_PROFILE.md` --- owners, accounts, income, BNPL, TSP
- `DUMMY_DATA_GENERATION_SPEC.md` --- canonical trusted seeder design
- `DESIGN.md` --- UI design system
- `ROADMAP.md` --- phased plan + shipped log (authoritative)
- `prompts/README.md` --- per-task institutional memory index
- `data-lineage/` --- per-event data flow map (see `data-lineage/HOWTO.md`)

---

## 1. Mission

Sentry Finance is a **local-first personal financial command center**
for a single household. It replaces third-party aggregators (Mint,
Monarch, Plaid) with direct browser automation, local storage, and
full owner control.

It is **not a dashboard**. A command center provides depth, trend
history, and derived analysis to drive decisions: debt sequencing,
savings-rate optimization, allocation rebalancing, lifestyle creep
detection, major-purchase timing, retirement trajectory. Every
feature is evaluated against that standard.

### Guiding Principles

1. **Automate everything.** Manual steps are a last resort with a nudge.
2. **Local-first, no cloud.** No aggregator APIs. No telemetry.
3. **Security by architecture.** OS keyring, short-lived elevated
   processes, IPC hardening, log redaction.
4. **Owner-scoped from day one.** Every query respects owner context.
5. **Teach the system.** Unrecognized transactions become permanent rules.
6. **Preliminary then revised.** Reports use best available data now,
   upgrade when authoritative documents arrive.

---

## 2. Household Financial Profile

Lives in `HOUSEHOLD_PROFILE.md`. Load only when writing owner-specific
rules (mortgage overfunding, TSP staleness, partner integration).

---

## 3. System Architecture

### 3.1 Process Model

All processes run on the user's Windows machine. The frontend (React +
Tauri) talks to the FastAPI server (`:8000`) via REST + SSE; the API
writes to a local SQLite DB (WAL mode). A non-privileged Refresh
Orchestrator runs per-institution Automation Workers (Chrome CDP for
NFCU/Chase/Fidelity/Acorns/Affirm, scheduled connector for TSP
planned). MFA prompts are routed to the UI via SSE and unblocked via
the MFA bridge. A separate **Credential Broker** runs **UAC-elevated
for seconds only** to read the keyring and pass secrets via IPC, then
exits. Document drop (PDF/XLSX) and an AI Backstop with selector
healing run alongside scrapers.

### 3.2 Trust Boundaries

| Process | Privilege | Lifetime | Role |
|---|---|---|---|
| API Server | Non-privileged | Long-running | REST + SSE serving |
| Refresh Orchestrator | Non-privileged | Per-session | Staleness, retries |
| Automation Worker | Non-privileged | Per-institution | Connector exec, DB writes |
| Credential Broker | **Elevated (UAC)** | **Seconds** | Keyring read, IPC, exit |

### 3.3 Data Ingestion Tiers

| Tier | Method | Institutions | Freshness |
|---|---|---|---|
| **1: Full automation** | Orchestrated connector | NFCU, Chase, Fidelity, Acorns, Affirm | Per refresh policy |
| **2: Semi-automation** | Connector + interactive MFA | TSP (planned) | Daily |
| **3: Document drop** | Drag-drop, auto-recognize | TSP statements, myPay RAS, 1099/1098, Eventlink | Monthly |

Tier 3 institutions not updated by the 5th of the month surface a
persistent toast until a doc is dropped. Recognizers/parsers live in
`dal/parsers/` (TSP, myPay RAS, Eventlink, several 1099/1098 variants).

### 3.4 Post-Ingestion Pipeline

After every connector commit (`backend/result_writer.py::run_post_commit_pipeline`),
in order:

1. Categorization backfill
2. Merchant normalization
3. Transfer reconciliation
4. Recurring detection
5. Acorns investment linkage *(only when institution is `acorns`)*
6. Mortgage payment decomposition (loan amortization splits)
7. Ticker metadata enrichment
8. Derived metric recompute
9. Alert evaluation
10. Goal balance sync
11. Notifications producer (notifications surfaced from steps 8–10)

Date-sensitive finance windows use the backend reference clock:
`dal.clock.reference_date()` / `reference_datetime()` in Python and
`RuntimeContext.referenceDate` in React. Trusted synthetic databases pin
that clock to the seed manifest so bill due labels, doc-drop nudge keys,
freshness, derived summaries, report windows, budget progress, review
selectors, and valuation defaults align to the fixture instead of the
workstation clock. Live databases without the trusted seed setting use
real current time through the same contract. That live fallback is only
the first live-data policy: connector-provided `as_of`, transaction
posting dates, statement close dates, and refresh timestamps remain
separate data facts and must not be collapsed into "today."

Any step that fails is logged and the next step still runs --- the
pipeline is best-effort, not transactional, by design.

---

## 4. Data Architecture

### 4.1 Database

- **Engine:** SQLite 3, WAL mode (`dal/connection.py`)
- **Runtime path authority:** backend/proof runs require an explicit
  `SENTRY_DB_PATH`. Trusted synthetic work uses `data/dummy.db` and verifies
  the active path, seed version, reference date, and live-vs-manifest
  fingerprint through `GET /api/runtime/context`; the legacy
  `GET /api/runtime/identity` endpoint projects the same context into a flat
  status shape. Default DAL access without either `SENTRY_DB_PATH` or an
  explicit `db_path` fails loudly; there is no supported startup path that
  silently falls back to another database.
- **Schema version:** derive from `ls dal/migrations/` --- highest
  `v##` prefix is current. Do not pin a number here; it drifts.
- **Table count:** derive from `sqlite_master` in the live DB.

### 4.2 Schema Overview

Five logical groups. Column-level DDL lives in `dal/migrations/v##_*.py`
--- read those for authoritative shape.

- **Core:** `institutions`, `accounts`, `transactions`,
  `balance_snapshots`, `loan_details`
- **Investment:** `portfolio_snapshots`, `positions_ledger`,
  `investment_holdings`, `investment_details` (P15-T09 per-account /
  per-fund KV: SPAXX SEC yield, TSP fund YTD, Acorns round-ups),
  `benchmark_prices`, `ticker_metadata`, `tax_buckets`. Live via
  `dal/investments.py` (read APIs: holdings/activity/performance/
  allocation/tax-buckets).
- **Derived/analytical:** `derived_summaries`, `recurring_transactions`,
  `recurring_mutations`, `category_overrides`, `merchant_snapshots`,
  `apy_history`, `notifications`
- **Planning:** `budgets` (household-only, see CLAUDE.md guardrail),
  `alert_rules`, `savings_goals`, `real_estate`, `vehicle_assets`,
  `vehicle_valuations`, `income_sources`, `loan_payment_splits`
- **System:** `refresh_runs`, `refresh_events`,
  `institution_refresh_status`, `owners`, `document_drops`
  (carries an `owner_id` column as of v42 — `dfas_1099r` /
  `fidelity_1099` / `acorns_1099` / `affirm_1099int` /
  `mypay_ras` stamp the primary owner; `nfcu_1098` is household).

### 4.3 Categorization Engine

Four-layer priority (`dal/categorization.py`):

1. **User override** (`category_overrides`) --- always wins
2. **Keyword rules** (`config/categories.yaml`, ~100 rules)
3. **Bank-provided category** --- e.g., NFCU scraped values
4. **Fallback:** "Uncategorized" --- triggers user toast

**Teach-the-system:** when a user categorizes an unknown transaction,
the system offers to make it a recurring rule (exact-amount or
amount-range match). Future hits auto-categorize. Used heavily for
check-based utility payments and one-off manual income.

### 4.4 Transfer Reconciliation

`dal/reconciliation.py` matches cross-institution debit/credit pairs:
same absolute amount (integer cents), opposite directions, different
institutions, ≤3-day window, at least one transfer keyword/category.
Tagged pairs are excluded from income/spending via `transfer_tag IS NULL`.

**Risk:** a missed transfer inflates both income and spending. The
mortgage-overfunding pattern (transfer to NFCU XXXX > mortgage payment)
is special-cased --- excess is earmarked savings, not spending.

### 4.5 Archival Policy

- **Active:** full visibility everywhere
- **Completed/closed:** visible through **Dec 31 of the year following
  completion**
- **Archived:** retained in DB, excluded from active views

Applies to BNPL contracts, paid-off loans, closed accounts.

### 4.6 Sign Convention (Phase 10) --- INVARIANT

Every transaction carries three amount-shaped fields with an
**invariant** relationship:

| Field | Type | Convention |
|---|---|---|
| `amount` | REAL ≥ 0 | Absolute dollar value |
| `signed_amount` | REAL | **Negative** for debits, **positive** for credits |
| `direction` | TEXT | `'Debit'` ⟺ `signed_amount < 0`; `'Credit'` ⟺ `> 0` |

**Single choke point:** `dal.transactions.upsert_transactions()` runs
`_assert_sign_direction_invariant()`. Both seeder and live connectors
write through this function; drift fails fast with `ValueError`.

**Canonical SQL pattern.** All analytical aggregates **must** use
`signed_amount` (not `direction + amount`), exclude
`transfer_tag IS NOT NULL` rows, and exclude the relevant category set
from `dal/category_classifications.py`:

```sql
income = SUM(CASE
    WHEN signed_amount > 0
     AND transfer_tag IS NULL
     AND COALESCE(category, 'Other Income') NOT IN <INCOME_EXCL_FROM_INC>
    THEN signed_amount ELSE 0 END)

spending = SUM(CASE
    WHEN signed_amount < 0
     AND transfer_tag IS NULL
     AND COALESCE(category, 'Uncategorized') NOT IN <ALL_EXCL_FROM_SPEND>
    THEN -signed_amount ELSE 0 END)
```

**Why the sign check matters.** A grocery refund posts as a *positive*
amount in a spending category. Without `signed_amount < 0`, the refund
silently subtracts from spending --- the Phase 10 cash-flow mismatch bug.

**Forbidden pattern.** `SUM(CASE WHEN direction = 'Debit' THEN amount …)`
ignores refunds. If you find one, replace it.

**Regression wall:** `tests/test_cashflow_invariants.py` (12 tests)
asserts top-graph = drill-down across every granularity.

### 4.7 DAL Write Wrappers (Phase 17)

Every non-transactional snapshot table has a wrapper shared by seeder
and live connectors:

| Table | Wrapper |
|---|---|
| `balance_snapshots` | `dal.balances.record_balance` |
| `loan_details` | `dal.balances.record_loan_details` |
| `credit_scores` | `dal.credit_scores.record_credit_score` |
| `apy_history` | `dal.apy_history.record_apy_history` |
| `investment_details` | `dal.investment_details.record_investment_details` |
| `investment_holdings` | `dal.investments_writes.record_investment_holdings` |
| `portfolio_snapshots` | `dal.investments_writes.record_portfolio_snapshots` (batch) / `record_portfolio_snapshot` (single) |
| `real_estate` | `dal.real_estate.record_real_estate_valuations` |
| `vehicle_valuations` | `dal.vehicles.add_valuation` |

**Caller-commits convention.** All wrappers accept a `sqlite3.Connection`,
write, and leave `conn.commit()` to the caller --- so orchestrators can
batch multiple wrapper calls in one transaction.

**Invariant guards.** Each wrapper validates inputs and raises
`ValueError` on violation. Examples: FICO `300 ≤ score ≤ 850`,
non-negative shares/values, `cash_balance ≤ total_account_value`,
`|market_value − shares*close_price|` within tolerance, APY ∈ [0, 100].

### 4.8 Data Lineage Map

Per-event-type lineage lives in [`docs/data-lineage/`](data-lineage/).
Start at `data-lineage/HOWTO.md` (three worked recipes for "where does
this number come from?"). The textual `inverse-index.yaml` is fastest
for `<table>.<column>` lookups; per-event Mermaid diagrams under
`data-lineage/diagrams/` are for visualization. The overview diagram
is auto-generated by `data-lineage/build_diagrams.py`.

---

## 5. Analytical Engine

### 5.1 Capabilities

The shipped analytical capability list is `ROADMAP.md` --- every `[v]`
entry is one shipped capability. Planned items are `[ ]` / `[->]`.
Do not duplicate here.

### 5.2 Review System

**Monthly Review** (auto-generates on the 1st or first app open):
income/spending/SR vs prior month, NW change, budget highlights,
subscription mutations, notable transactions, freshness, data quality.

**Yearly Wrap-Up** (two-stage):
- **Preliminary** (January) --- transaction data + derived metrics
- **Revised/Final** (Feb–Mar) --- overlays authoritative tax docs as
  they arrive via document drop. Status progresses preliminary → revised
  → final. Tax-document checklist toast tracks received vs. expected.

Sections include: income by stream, spending by category, NW
trajectory, category shifts vs prior year, interest paid vs earned,
investment performance vs benchmark, debt paid down, recurring-cost
mutations, savings-goal progress, credit-score trend.

---

## 6. Frontend Architecture

### 6.1 Tech Stack

React 19 + TypeScript, Vite 7, Tauri 2. **Recharts** is the sole chart
library (Tremor removed in P21-T04-cont-R). Tailwind 3.4 with OKLCH
tokens (Ember palette) and dark mode. React hooks + fetch (no Redux);
REST + SSE for live refresh. Visual conventions (palette, typography,
component catalog) live in `DESIGN.md` --- load before any
`frontend/**` work.

Date-sensitive frontend defaults consume `GET /api/runtime/context` through
`RuntimeProvider`. Trusted synthetic sessions use the backend manifest
reference date for Header, Dashboard, Transactions, Reports, and Cash Flow
period defaults; live databases without a trusted manifest continue through the
backend's system-clock runtime context.

### 6.2 Pages

| Page | Purpose |
|---|---|
| Dashboard | KPIs (NW, SR, credit, runway), spending chart, widgets |
| Transactions | Paginated table, filters, teach-the-system flow |
| Cash Flow | Rolling 18-mo / 9-qtr / 4-yr charts, drill-down |
| Reports | Sankey flow, accountability scorecard, NW history |
| Accounts | List + sparklines, freshness badges, details panel |
| Budgets | Budget-vs-actual per category (household-only) |
| Investments | Overview / Holdings / Allocation / Tax buckets |
| Documents | Drop UI, parser history, pending nudges |
| Monthly Review | Auto-generated monthly summary (§5.2) |
| Yearly Wrap-Up | Preliminary → Final annual review (§5.2) |
| Settings | Multi-user toggle, refresh policy, owner names |

### 6.3 Multi-User UI

`[Quintin | Household | Amy]` chip switcher renders unconditionally;
Amy's view is a verified empty-state harness until her real data
ingests. Every DAL query, endpoint, and page threads `owner_id`.
Use `dal/owners.build_account_filter(owner_id, account_ids)` --- it
distinguishes `None` (no filter) from `[]` (owner-owns-nothing
short-circuits via `AND 1=0`). The `if not account_ids:` truthy-list
shortcut is a regression.

Ownership source of truth is hybrid and local-first. `config/owner_config.yaml`
is the committed owner roster and primary-owner default. At runtime,
`accounts.owner_id` is authoritative for account ownership and owner-scoped
queries. Settings writes account-owner edits to the DB and mirrors those edits
to gitignored `config/account_ownership.local.yaml`, which is the local rebuild
authority replayed by the real-account `accounts.yaml` seed path. The trusted
synthetic seeder does not read that local override file, and API startup skips
real-account seeding when a trusted seed manifest is present.

### 6.4 Notification System

| Type | Trigger | Behavior |
|---|---|---|
| Document-drop nudge | Tier-3 not updated by 5th | Persistent toast |
| Uncategorized txn | New txn lands as Uncategorized | Categorization toast |
| Subscription price change | `recurring_mutations` insert | Info toast |
| Budget alert | Threshold breach | Per `alert_rules` |
| APY rate change | ≥5 bp on any account | Info / warning toast (≥25 bp) |
| Refresh status | Connector lifecycle | SSE-driven indicator |
| MFA required | TSP-style pause | Modal toast w/ code entry |
| Tax-doc checklist | Yearly incomplete Jan-Mar | Persistent toast |

The notification feed lives behind the header bell
(`NotificationPopover.tsx`). All inserts broadcast on the SSE
`notification` topic via `dal.notifications.record_notification`.

---

## 7. Data Capture Gaps & Planned Additions

Tracked as roadmap tasks, not here. See `ROADMAP.md` Phase 2 (connector
+ document drop) and Phase 4 (connector enhancements + new sources).

---

## 8. Pipeline Risk Mitigations

1. **Transfer detection failures** --- a missed transfer inflates both
   income and spending. Expand `_TRANSFER_KEYWORDS` as real data reveals
   misses; mortgage overfunding is special-cased.
2. **Acorns delta-logging partial scrapes** --- treat partial fund-page
   loads as failures (all-or-nothing); never write partial position
   updates. Scrape guard lives in the Acorns connector.
3. **TSP data staleness** --- as the largest account, stale TSP makes
   NW unreliable. Net-worth display includes a "data as of" indicator;
   Tier-3 nudge fires monthly until TSP connector ships.
4. **Categorization accuracy** --- Uncategorized rows count as spending,
   distorting SR. Teach-the-system reduces this over time; Monthly
   Review surfaces Uncategorized count as a data-quality metric.

---

## 9. Module Map

Module purposes live as docstrings. To enumerate:

```
ls backend/ dal/ extractors/ frontend/src/pages/ scripts/
head -20 <module>.py
```

Seeder design: `DUMMY_DATA_GENERATION_SPEC.md`.

---

## 10. Document Tree

```
docs/
├── ARCHITECTURE.md                <- this file
├── HOUSEHOLD_PROFILE.md           <- owner/account/income context
├── DUMMY_DATA_GENERATION_SPEC.md  <- rolling seeder design
├── DESIGN.md                      <- UI design system
├── ROADMAP.md                     <- phased plan + shipped log
├── COMMANDS.md                    <- env setup, server start, tests
├── PARTNER_MFA_DESIGN.md          <- Phase 20 design doc
├── prompts/                       <- per-task institutional memory
│   └── README.md                  <- phase index + authoring policy
├── data-lineage/                  <- per-event flow map (see HOWTO)
├── audits/                        <- numerical/UI audit reports
├── agent-rules/                   <- branch-hygiene and similar
└── research/                      <- non-code reference material
```

Session startup, status markers, and verification rules live in
`CLAUDE.md` --- not restated here.
