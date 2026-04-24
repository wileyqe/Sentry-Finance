# Sentry Finance --- Architecture & Design Document

> **Living architectural contract.** Enforced invariants, active system
> boundaries, and current design decisions live here. Historical rationale
> and detailed decision records live in `docs/prompts/` --- see the
> companion documents listed below.
>
> Last updated: 2026-04-08

---

## Table of Contents

1. **Mission (§1)** --- why Sentry Finance exists, six guiding principles
2. **System Architecture (§3)** --- process model, trust boundaries,
   ingestion tiers (**§3.3**), post-commit pipeline (**§3.4**)
3. **Data Architecture (§4)** --- schema groups (§4.2), categorization
   engine (§4.3), transfer reconciliation (§4.4), archival policy (§4.5),
   **sign convention (§4.6)**, DAL write wrappers (§4.7)
4. **Analytical Engine (§5)** --- monthly/yearly review contract (§5.3)
5. **Frontend Architecture (§6)** --- tech stack, pages, multi-user
   policy (§6.3), notification system (§6.4)
6. **Pipeline Risk Mitigations (§8)** --- transfer, Acorns, TSP,
   categorization risk contracts
7. **Document Tree (§10)** --- where everything lives

**Bold sections** are cited by guardrails in `CLAUDE.md` or by live code.
Their section numbers are locked and will not be renumbered.

**Companion documents** (load only when relevant to the task):

- `docs/HOUSEHOLD_PROFILE.md` --- owner context, accounts, income streams,
  property, credit cards, BNPL philosophy, TSP posture
- `docs/DUMMY_DATA_GENERATION_SPEC.md` --- rolling seeder design and
  determinism invariants (absorbs the former §9.4.1 narrative)
- `docs/ROADMAP.md` --- phased plan with status markers; the `[v]` log
  is the authoritative shipped-capability list
- `docs/prompts/README.md` --- phase-by-phase index of institutional
  memory; load individual prompt files only on demand

---

## 1. Mission

Sentry Finance is a **local-first personal financial command center** for a
single household. It replaces third-party aggregators (Mint, Monarch, Plaid)
with direct browser automation, local storage, and full owner control.

**It is not a dashboard.** A dashboard shows numbers. A command center
provides the depth, trend history, and derived analysis to make decisions
with lasting financial impact:

- Debt sequencing (which balance to attack first)
- Savings rate optimization (am I keeping enough of what I earn)
- Investment rebalancing (is my allocation still right)
- Lifestyle creep detection (is spending growing faster than income)
- Major purchase timing (can I absorb this and stay on track)
- Retirement trajectory (am I where I need to be)

Every feature and design decision is evaluated against that standard.

### Guiding Principles

1. **Automate everything.** If data can be fetched programmatically,
   it must be. Manual steps are a last resort with a nudge system.
2. **Local-first, no cloud.** All data stays on the user's machine. No
   third-party aggregator APIs. No telemetry.
3. **Security by architecture.** Credentials in OS keyring, short-lived
   elevated processes, IPC hardening, log redaction.
4. **Owner-scoped from day one.** Multi-user is architecturally present
   but UI-toggled off until activated. Every query respects owner context.
5. **Teach the system.** Unrecognized transactions prompt the user;
   classifications become permanent rules. The system gets smarter with use.
6. **Preliminary then revised.** Reports use the best available data now
   and upgrade when authoritative documents arrive.

---

## 2. Household Financial Profile

Owner context, institutions, accounts, income streams, property, credit
cards, BNPL philosophy, and TSP posture live in
**`docs/HOUSEHOLD_PROFILE.md`**. Load that file only when writing
owner-specific rules (mortgage overfunding detection, TSP staleness
mitigation, institution-specific categorization, partner integration
logic). Routine architectural work does not need it.

---

## 3. System Architecture

### 3.1 Process Model

```
+-------------------- User's Machine (Windows) --------------------+
|                                                                    |
|  +-------------+    +----------------+    +--------------+         |
|  |  Frontend   |--->|  API Server    |--->|  SQLite DB   |         |
|  | React+Tauri |    |  FastAPI :8000 |    |  WAL mode    |         |
|  +-------------+    +-------+--------+    +--------------+         |
|                             | SSE + REST          ^                |
|                             v                     |                |
|                     +----------------+            |                |
|                     |   Refresh      |  writes ---+                |
|                     |  Orchestrator  |                             |
|                     +-------+--------+                             |
|      +----------+----------+----------+----------+-------+        |
|      v          v          v          v          v       v        |
|  +------+  +------+  +-------+  +------+  +-----+  +------+     |
|  | NFCU |  |Chase |  |Fidelity| |Acorns|  | TSP |  |Affirm|     |
|  +--+---+  +--+---+  +---+---+  +--+---+  +--+--+  +--+---+     |
|     |         |           |         |         |         |          |
|     +----+----+           |         |    MFA Bridge     |          |
|          |                |         |    (SSE toast)    |          |
|          v                v         v         |         v          |
|   +-----------+    +----------+  +--------+   |   +---------+     |
|   |Chrome CDP |    |CSV Ingest|  | Delta  |   |   |DOM Scrape|    |
|   +-----+-----+    +----------+  |Logging |   |   +---------+     |
|         |                         +--------+   |                   |
|         v                                      |                   |
|   +-----------+                                |                   |
|   | SMS OTP   |    +---------------------------+                   |
|   | auto-cap  |    |                                               |
|   +-----------+    v                                               |
|              +--------------+     +-------------------+            |
|              | Document Drop |     | AI Backstop +     |           |
|              | (PDF/XLSX)    |     | Selector Healing   |          |
|              +--------------+     +-------------------+            |
|                                                                    |
|   +----------------------------------------------------------+    |
|   | Credential Broker (UAC-elevated, seconds only)            |    |
|   | keyring -> IPC -> exit                                    |    |
|   +----------------------------------------------------------+    |
+--------------------------------------------------------------------+
```

### 3.2 Trust Boundaries

| Process | Privilege | Lifetime | Role |
|---------|-----------|----------|------|
| API Server | Non-privileged | Long-running | REST + SSE serving |
| Refresh Orchestrator | Non-privileged | Per-session | Staleness, state machine, retries |
| Automation Worker | Non-privileged | Per-institution | Connector execution, DB writes |
| Credential Broker | **Elevated (UAC)** | **Seconds** | Keyring read, IPC, exit |

### 3.3 Data Ingestion Tiers

The system supports three tiers of data ingestion, in priority order:

| Tier | Method | Institutions | Freshness |
|------|--------|-------------|-----------|
| **Tier 1: Full automation** | Orchestrated connector on schedule | NFCU, Chase, Fidelity, Acorns, Affirm | Per refresh policy (hours/days) |
| **Tier 2: Semi-automation** | Connector with interactive MFA bridge | TSP (planned) | Daily (session reuse minimizes MFA prompts) |
| **Tier 3: Document drop** | Drag-and-drop on UI, auto-recognize, parse | TSP statements, myPay RAS, tax documents (1099/1098), Eventlink XLSX | Monthly (nudge system if overdue) |

**Document Drop Design:**
- UI accepts drag-and-drop of PDF and XLSX files
- Auto-recognition: file content is matched against known document
  parsers (TSP statement, myPay RAS, 1099-R, 1098, Eventlink export)
- Parsed data is ingested into the appropriate tables
- If a Tier 3 institution hasn't been updated by the 5th of the month,
  a **persistent toast** (small, unmovable) remains on screen until the
  document is dropped
- Document parsers: `ingest_tsp.py` (exists), myPay RAS (to build),
  1099/1098 tax docs (to build), Eventlink XLSX (to build)

### 3.4 Post-Ingestion Pipeline

After every connector writes data, the post-commit pipeline runs:

```
Connector writes -> Categorization backfill
                 -> Transfer reconciliation
                 -> Recurring detection
                 -> Derived metrics recompute
                 -> Alert evaluation
                 -> Goal balance sync
```

This pipeline is implemented in `backend/result_writer.py` and runs
per-institution after each refresh.

---

## 4. Data Architecture

### 4.1 Database

- **Engine:** SQLite 3 with WAL mode
- **Connection:** `dal/connection.py` --- WAL, foreign keys, busy timeout
- **Schema version:** do **not** pin a number here --- it drifts. Run
  `ls dal/migrations/`; the highest `v##` prefix is the current version.
- **Table count:** derive from `sqlite_master` in the live DB, not this doc.

### 4.2 Schema Overview

Tables fall into five logical groups. Column-level detail lives in the
migration files (`dal/migrations/v##_*.py`) --- read those for authoritative
DDL, not this document.

- **Core:** `institutions`, `accounts`, `transactions`, `balance_snapshots`,
  `loan_details`
- **Investment (partial rebuild — P13 in progress):**
  `portfolio_snapshots`, `positions_ledger`, `investment_holdings`,
  `benchmark_prices`, `ticker_metadata` --- tables exist via their
  original migrations but remain **empty** during the rebuild.
  P13-T01 deleted the DAL modules (`dal/investments.py`,
  `dal/allocation.py`, `dal/performance.py`), the `/api/investments/*`
  endpoints, and the seeder's investment generation. P13-T02 added
  a single canonical investment account row (`acorns_synthetic_0000`,
  "Acorns Synthetic", owner `quintin`, $0 balance) so the account
  exists and is ready to receive transfers; the five investment
  tables above still hold zero rows. Later P13 tasks will add
  transfers, then holdings, then whatever analytical layer replaces
  the old performance/allocation stack.
- **Derived/analytical:** `derived_summaries`, `recurring_transactions`,
  `recurring_mutations`, `category_overrides`, `merchant_snapshots`
- **Planning:** `budgets`, `alert_rules`, `savings_goals`, `real_estate`
- **System:** `refresh_runs`, `refresh_events`,
  `institution_refresh_status`, `owners` (multi-user ownership; active but
  UI-hidden until toggled)

**Investment total priority** (dormant during P13 rebuild): the prior
priority rule ordered `portfolio_snapshots.total_account_value` >
`SUM(investment_holdings.market_value)` > `balance_snapshots.balance`.
It is not enforced today because the investment surface is empty; the
rule will be revisited when the rebuild decides on a new read path.

### 4.3 Categorization Engine

Four-layer priority system (`dal/categorization.py`):

1. **User override** (`category_overrides` table) --- always wins
2. **Keyword rules** (`config/categories.yaml`) --- regex on description,
   first match wins, ~100 rules covering income, transfers, housing,
   food, transport, shopping, bills, entertainment, healthcare, financial
3. **Bank-provided category** --- e.g., NFCU sends categories from scraping
4. **Fallback:** "Uncategorized" --- triggers a toast prompting user action

**Teach-the-system flow (new):**

When a user categorizes an unknown transaction (e.g., a check):
1. User assigns category and merchant name
2. System offers: "Make this a recurring rule?"
3. If yes: match by exact amount or amount range?
4. Future matching transactions auto-categorize with assigned
   merchant name and category

This handles check-based utility payments (water/sewer monthly ~$55,
trash/recycling quarterly ~$105) and any other anonymous transactions.

### 4.4 Transfer Reconciliation

`dal/reconciliation.py` matches cross-institution debit/credit pairs:
- Same absolute amount (integer cents comparison)
- Opposite directions
- Different institutions
- Within 3-day posting window
- At least one has transfer keyword or category

Tagged pairs are excluded from income/spending calculations via
`transfer_tag IS NULL` in all analytical queries.

**Known risk:** A missed transfer inflates both income and spending.
The mortgage overfunding pattern (transfer to XXXX > mortgage payment)
requires special handling --- the excess is earmarked savings, not spending.

### 4.5 Archival Policy

System-wide rule for closed/completed accounts and contracts:
- **Active:** full visibility in all views and reports
- **Completed/closed:** visible through **December 31 of the year
  following completion**
- **Archived:** data remains in database, excluded from active views
  and reports unless explicitly queried

Applies to: BNPL contracts, paid-off loans, closed accounts.

### 4.6 Sign Convention (Phase 10)

Every transaction in the database carries three amount-shaped fields, and
the relationship between them is **invariant**:

| Field | Type | Convention |
|---|---|---|
| `amount` | REAL ≥ 0 | Always non-negative (the absolute dollar value) |
| `signed_amount` | REAL | **Negative** for debits, **positive** for credits |
| `direction` | TEXT | `'Debit'` ⟺ `signed_amount < 0`; `'Credit'` ⟺ `signed_amount > 0` |

**Single choke point:** the invariant is enforced inside
`dal.transactions.upsert_transactions()` via `_assert_sign_direction_invariant()`.
Both the dummy seeder and live institution connectors write through this
function, so any drift fails fast with a `ValueError` naming the offending
account, posting date, and description before any row reaches the DB.

**Canonical SQL pattern.** All analytical aggregates that compute income or
spending **must** use the blacklist + sign-check pattern. Use
`signed_amount` (not `direction + amount`), and always exclude
`transfer_tag IS NOT NULL` rows plus the appropriate category exclusion set
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
amount in a spending category (`Groceries`). Without the
`signed_amount < 0` clause, the refund silently subtracts from the
spending total — exactly the bug that caused the Phase 10 cash-flow
mismatch where top-graph numbers disagreed with drill-down numbers for
the same date range.

**Regression wall:** `tests/test_cashflow_invariants.py` builds a hand-
auditable fixture with a refund pair, a `Deposits` income row, transfers,
and multi-owner data, then asserts that monthly/quarterly/yearly top-graph
totals exactly equal drill-down totals across every granularity. The
blacklist + sign-check pattern is the only pattern that satisfies all 12
invariants.

**Forbidden pattern.** Do **not** introduce new aggregates that follow
the legacy `SUM(CASE WHEN direction = 'Debit' THEN amount …)` shape. It
ignores refunds and disagrees with the canonical pattern. If you find
one, replace it (this is how `dal/budgets.py` and `dal/goals.py` were
fixed in Phase 10).

### 4.7 DAL Write Wrappers (Phase 17)

Every non-transactional snapshot table has a DAL write wrapper that
seeder and live connectors share:

| Table | Wrapper |
|---|---|
| `balance_snapshots` | `dal.balances.record_balance` |
| `loan_details` | `dal.balances.record_loan_details` |
| `credit_scores` | `dal.credit_scores.record_credit_score` |
| `investment_holdings` | `dal.investments_writes.record_investment_holdings` |
| `portfolio_snapshots` | `dal.investments_writes.record_portfolio_snapshots` / `record_portfolio_snapshot` |
| `real_estate` | `dal.real_estate.record_real_estate_valuations` |
| `vehicle_valuations` | `dal.vehicles.add_valuation` |

**Caller-commits convention.** All wrappers follow the
`upsert_transactions` shape: they accept a `sqlite3.Connection`,
perform writes, and leave `conn.commit()` to the caller. This lets
orchestrators batch multiple wrapper calls inside a single transaction.

**Invariant guards.** Each wrapper validates its inputs before any
INSERT and raises `ValueError` with row context on violation — the
direct analog of `_assert_sign_direction_invariant` for
non-transactional data. Guards include FICO range `300 ≤ score ≤ 850`,
non-negative shares/values, `cash_balance ≤ total_account_value`,
and `|market_value − shares*close_price|` within rounding tolerance.

---

## 5. Analytical Engine

### 5.1 Current Capabilities

The shipped analytical capability list lives in `docs/ROADMAP.md` ---
every `[v]` entry is one shipped capability with its module, verification
date, and prompt link. Do not duplicate here; the roadmap is the
authoritative source.

### 5.2 Planned Capabilities

Planned analytical work lives in `docs/ROADMAP.md` --- every `[ ]` and
`[->]` entry is a planned task with priority and prompt file. Data-gap
work specifically lives in the Phase 2 and Phase 4 sections.

### 5.3 Review System

**Monthly Review** (auto-generates on 1st of month or first app open):
- Income vs. spending vs. prior month
- Savings rate
- Net worth change from last month
- Budget vs. actual highlights
- Subscription price changes detected
- Notable transactions
- Account freshness status
- Data quality indicators

**Yearly Wrap-Up** (dedicated page, two-stage):
- **Preliminary** (January): built from transaction data, derived metrics,
  balance snapshots. Labeled "Preliminary."
- **Revised/Final** (February-March): overlays authoritative tax documents
  (1099s, 1098) as they arrive via document drop. Checklist toast tracks
  received vs. expected documents. Upgrades to "Final" when complete.

Yearly wrap-up contents:
- Total income (by stream), total spending (by category)
- Net worth trajectory for the year
- Category spending shifts vs. prior year
- Total interest paid vs. earned
- Investment performance vs. benchmark
- Debt paid down
- Recurring cost changes (subscription mutations)
- Savings goals progress
- Credit score trend

---

## 6. Frontend Architecture

### 6.1 Tech Stack

React 19 + TypeScript, Vite 7, Tauri 2 desktop shell, Recharts (sole
chart library — Tremor removed in Phase 21-T04-cont-R), Tailwind CSS
3.4 with OKLCH design tokens (Ember palette) and dark mode, React
hooks + fetch (no Redux), REST + SSE for live refresh progress.
Exact versions live in `frontend/package.json`.

**Visual system and component conventions:** see
[`docs/DESIGN.md`](DESIGN.md) — canonical token values (Ember palette,
Newsreader / Inter / JetBrains Mono typography, 8-hue chart palette),
component catalog (Built + Planned primitives), and Do's and Don'ts
for `frontend/**` work.

### 6.2 Pages

| Page | Purpose |
|------|---------|
| **Dashboard** | KPI cards (net worth, savings rate, credit scores, emergency fund months), spending chart, recent transactions, budget & recurring widgets |
| **Transactions** | Paginated table, filter popover, recurring toggle, add/categorize transaction, teach-the-system flow |
| **Cash Flow** | 18-month/9-quarter/4-year rolling charts, bar click drill-down, savings rate trend |
| **Reports** | Spending by category, Sankey flow, net worth history, category trend, spending comparison |
| **Accounts** | Account list with balance sparklines, institution freshness indicators, account-detail navigation |
| **Budgets** | Budget vs. actual per category, progress bars, month navigation |
| **Investments** | Portfolio summary, holdings table, performance vs. benchmark, contribution vs. growth decomposition |
| **Monthly Review** | Auto-generated monthly summary (see 5.3) |
| **Yearly Wrap-Up** | Preliminary → Final annual review (see 5.3) |
| **Settings** | Multi-user toggle, refresh policy, document drop management, notification preferences |

### 6.3 Multi-User UI

- **Default:** Single-user mode. No selector visible. All data shown.
- **Activated via:** Settings menu toggle
- **When active:** Selector appears at top of app: **Mine | Theirs | Household**
- **Mine/Theirs:** Filters all views to accounts owned by that person
- **Household:** Combined view across both owners
- Architecture supports this from day one; every DAL query accepts
  optional `owner_id` filter

### 6.4 Notification System

| Type | Trigger | Behavior |
|------|---------|----------|
| **Document drop nudge** | Tier 3 institution not updated by 5th of month | Persistent toast, small, unmovable until resolved |
| **Uncategorized transaction** | New transactions land as Uncategorized | Toast prompting categorization action |
| **Subscription price change** | `recurring_mutations` entry created | Informational toast |
| **Budget alert** | Spending exceeds threshold | Toast per `alert_rules` configuration |
| **Refresh status** | Connector running/complete/failed | SSE-driven progress indicator |
| **MFA required** | TSP (or similar) connector paused at MFA | Modal toast with code entry field |
| **Tax document checklist** | Yearly wrap-up incomplete | Persistent toast in Jan-Mar tracking received vs. expected docs |

---

## 7. Data Capture Gaps & Planned Additions

Connector enhancements (missing fields per institution) and new data
sources (myPay RAS, Eventlink, KBB/NADA, tax documents) are tracked as
roadmap tasks, not in this document. See `docs/ROADMAP.md` Phase 2
(connector + document drop) and Phase 4 (connector enhancements + new
data sources) for current priorities, effort estimates, and prompt
links.

---

## 8. Pipeline Risk Mitigations

### 8.1 Transfer Detection Failures

**Risk:** Missed transfer inflates both income and spending.
**Mitigation:**
- Expand `_TRANSFER_KEYWORDS` as real data reveals missed patterns
- Monthly review flags unusual income spikes for manual verification
- Mortgage overfunding pattern: system must recognize that NFCU XXXX
  receives more than the mortgage debits; excess is earmarked savings

### 8.2 Acorns Delta-Logging Partial Scrapes

**Risk:** Partial fund page loads record incomplete deltas; next full
scrape creates phantom implied transactions on wrong dates.
**Mitigation:**
- Connector must treat partial scrapes as failures (all-or-nothing)
- If any fund page times out, discard the entire scrape and log an error
- Never write partial position updates

### 8.3 TSP Data Staleness

**Risk:** As the largest account (~10x others), stale TSP data makes
net worth unreliable.
**Mitigation:**
- Build TSP browser connector with MFA bridge (Tier 2)
- Until then, document drop with persistent nudge toast
- All dashboard views must show data freshness per institution
- Net worth display should include a "data as of" indicator showing
  the oldest balance snapshot date across all contributing accounts

### 8.4 Categorization Accuracy

**Risk:** Uncategorized transactions count as spending (not income),
distorting savings rate.
**Mitigation:**
- Teach-the-system flow reduces Uncategorized over time
- Add income stream patterns to `categories.yaml` (Military Pension,
  VA Benefits, VA Education Benefits, Officiating Income)
- Officiating income: broad regex + teach-the-system for new districts
- Monthly review surfaces Uncategorized count as a data quality metric

---

## 9. Module Map

Module purposes live as docstrings in each package. This document
deliberately does **not** enumerate them --- file lists drift faster than
anyone can maintain in prose, and CLAUDE.md already directs agents to
read code, not this section, for module layout.

To enumerate:

```
ls backend/ dal/ extractors/ frontend/src/pages/ scripts/
head -20 <module>.py          # read the docstring
```

Seeder design details that used to live here have moved to
`docs/DUMMY_DATA_GENERATION_SPEC.md` §0 (Design Overview).

---

## 10. Document Tree

```
docs/
+-- ARCHITECTURE.md                 <- this file (living contract)
+-- HOUSEHOLD_PROFILE.md            <- owner/account/income context
+-- DUMMY_DATA_GENERATION_SPEC.md   <- rolling seeder design
+-- ROADMAP.md                      <- phased plan + shipped capability log
+-- prompts/
|   +-- README.md                   <- phase-by-phase index
|   +-- Phase-0/ ... Phase-10/      <- per-task institutional memory
|   +-- empty_state_audit.md        <- Phase 12 research doc
+-- research/                       <- non-code reference material
```

**Session startup sequence** lives in `CLAUDE.md > Read Order`.
**Status markers** for roadmap tasks live in `ROADMAP.md > Status Key`.
**Verification rules** for implementation tasks live in
`CLAUDE.md > Verification Rules`. None of these are restated here.
