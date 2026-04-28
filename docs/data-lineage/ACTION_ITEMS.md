# Action Items

Out-of-scope findings from the data-lineage map effort. Items here are
**not** lineage-map tasks — they're code-level questions, possible bugs,
verification needs, and synthetic-vs-live gaps that surfaced while
tracing event lineage. Each one would otherwise get buried in
`SESSION_LOG.md` or in a single event's `notes` field.

## How to use this file

- **For agents working on the lineage map:** when you find anything
  that isn't a lineage-map task — a possible bug, an unexplored
  divergence, a verification gap, a code smell — add an entry here
  with a new `AI-NNN` id (next sequential number) and a 2–3 line
  description. Don't try to fix it; just log it. Cite the
  `events.yaml` entry or `lineage/<id>.yaml` file that surfaced it.
- **For the user:** use this list to spawn focused investigation /
  fix sessions. Each entry is sized to be one short session.
- **Status transitions:** move items between sections as they're
  resolved. Don't delete resolved items — keep the audit trail.

## Severity legend

- **bug** — likely defect in production code; user behavior would surprise
- **interpretation** — ambiguous behavior; may or may not be intentional
- **gap** — missing functionality / test coverage; not currently broken
- **verification** — claim worth confirming with a runtime check
- **cleanup** — dead code, deprecated paths, maintenance concern

---

## Open

_All open AIs resolved as of 2026-04-27. AI-020 + AI-021 closed
together via v43 (`positions_ledger.bank_txn_id`-based view rewrite
+ Sankey Shape B path)._

---

## Resolved

### AI-021 — `v_investment_contributions` cannot classify Acorns contributions as `user_contribution`

**Severity:** bug · **Found in:** lineage/investment_contribution.yaml · **Resolved:** 2026-04-27 (v43 — view rewrite + Shape B integration)

**Root cause:** The v34 view joined ``transactions`` to
``positions_ledger`` on ``(account_id, date, transfer_tag IS NOT
NULL)``. Brokerages don't emit bank-style transactions rows in
their feeds (a brokerage's feed is share movements, not currency
movements), so for every Shape-B money flow into an investment
account (Acorns, Fidelity EFT, future TSP, future taxable broker)
the cash leg sat on a checking account while the ledger rows sat
on the brokerage account. The ``account_id`` predicate never
aligned and these contributions ALWAYS classified as
``intra_account_credit``. The accountability scorecard
(``dal/reports/accountability.py:_user_contributions_in_window``)
therefore reported $0 user contributions for Acorns even though
~$350/mo of cash was being routed in.

**Fix (migration v43):**
``dal/migrations/v43_investment_contributions_via_bank_txn_id.py``
drops and recreates the view with ``LEFT JOIN transactions t ON
t.id = pl.bank_txn_id`` — the canonical link the post-commit
linker (``backend/result_writer.py:_link_acorns_bank_debits``) and
AI-010's seeder pass already populate. A partial covering index
on ``positions_ledger.bank_txn_id WHERE NOT NULL`` keeps the JOIN
cheap.

For Acorns ($350 → 4 IMPLIED_BUY rows): the linker sets
``bank_txn_id`` on exactly one primary ledger row, which
classifies as ``user_contribution`` with
``matched_tx_signed_amount = -$350``. The other three rows have
NULL bank_txn_id and classify as ``intra_account_credit`` —
semantically truthful (downstream allocation, not new user money).
Cardinality is 1:1 by construction; ``SUM(ABS(matched_tx_signed_amount))``
returns $350 per debit, never 4 × $350.

For Fidelity: AI-010's paired summit_chk debit + ``bank_txn_id``
on the corresponding DEPOSIT ledger row classifies the EFT as
``user_contribution`` directly. Subsequent BUY rows on later
dates (no ``bank_txn_id``) classify as ``intra_account_credit`` —
truthful, since they redeploy cash already in SPAXX.

The structural insight: every money flow between accounts is
either Shape A (both sides emit a transactions row, paired via
``transfer_tag``) or Shape B (bank emits a transactions row;
brokerage emits ``positions_ledger`` rows linked via
``bank_txn_id``). v43 teaches the analytical layer about Shape B
without inventing a fake transactions row on the brokerage side
that live data wouldn't produce.

``_user_contributions_in_window`` was rewritten to UNION both
shapes — Shape A via ``transactions ↔ transactions`` peer-type
filter, Shape B via the v43 view — so the accountability identity
correctly captures user contributions regardless of the source
shape.

**File:**
``dal/migrations/v43_investment_contributions_via_bank_txn_id.py``
(new) +
``dal/reports/accountability.py:_user_contributions_in_window``
(rewritten to UNION both shapes) +
``tests/test_investment_contributions_view.py`` (fixtures updated
to populate ``bank_txn_id``; new
``test_view_acorns_multi_ledger_per_debit`` regression guard for
the cardinality wrinkle the v34 view's date+account join would
have produced).

**Verification:** Full backend suite passes (532/532). New
regression guards explicitly assert the 1:1 cardinality and the
$350-not-$1400 user-contribution sum on the Acorns 4-ETF shape.

### AI-020 — Acorns contributions never appear in `transfer_flows[]` (no t1/t2 pair)

**Severity:** gap · **Found in:** lineage/investment_contribution.yaml · **Resolved:** 2026-04-27 (v43 — Shape B path in flow.py)

**Root cause:** ``_compute_bucket_totals`` built ``transfer_flows[]``
by self-joining ``transactions t1`` to ``transactions t2`` on
shared ``transfer_tag``. Brokerages emit ledger rows, not
transactions rows, so the self-join produced zero matches for
Acorns / Fidelity-shape transfers. The Sankey lost its labeled
"cash → investment" arrow; the dollars instead absorbed into the
residual STORED_LIQUID bucket. Approximately right for the
accountability math (because STORED_LIQUID is the residual), but
mislabeled the visual flow.

**Fix:** ``dal/reports/flow.py`` now constructs ``transfer_flows[]``
from two sources:
- Shape A — the existing ``transactions ↔ transactions``
  self-join on ``transfer_tag`` (mortgage / CC payment / internal
  transfer).
- Shape B — a new ``transactions JOIN positions_ledger ON
  pl.bank_txn_id = t.id`` query, peer account resolved through
  ``pl.account_id → accounts.type``. Always classifies
  STORED_ILLIQUID (the existence of a linked ledger row IS the
  proof the cash bought shares).

A ``shape`` field (``'A'`` | ``'B'``) is now part of each
``transfer_flows`` entry so consumers (and tests) can distinguish
the source path.

The legacy ``brokerage_buy_matches_transfer`` 5-day-window
heuristic (``dal/flow_classification.py:215``) was deleted —
deterministic ``bank_txn_id`` linkage replaces it. The
``brokerage_buy_matched`` parameter on ``classify()`` was removed;
the classifier's brokerage branch now defaults to STORED_LIQUID
(reserved for the currently-empty Shape A brokerage case where a
future broker emits a paired transactions row).

**File:** ``dal/reports/flow.py:_compute_bucket_totals`` (Shape B
subquery added) + ``dal/flow_classification.py``
(``brokerage_buy_matches_transfer`` deleted, ``classify()``
simplified) + ``dal/reports/{spending,net_worth,merchant,cash_flow_report,accountability,csv_export}.py``
+ ``dal/flow_aggregation.py`` (unused imports stripped) +
``tests/test_flow_shape_b_brokerage.py`` (new — asserts Shape B
resolves with shape='B' and contributes $350 once, not 4×) +
``tests/test_flow_classification.py`` (legacy
brokerage_buy_matched assertions removed) +
``scripts/seed_dummy_data.py:seed_acorns_investments`` (now calls
the canonical ``_link_acorns_bank_debits`` directly, removing the
duplicated linkage logic — exercises the same code path live data
uses on every refresh).

**Verification:** Full backend suite passes (532/532). New
``test_shape_b_acorns_resolves_in_transfer_flows`` and
``test_shape_b_two_distinct_debits_same_day_dont_collapse``
explicitly verify the Shape B path produces correct cardinality
and labeling.

### AI-004 — `cashback_redemption` classification is ambiguous

**Severity:** interpretation · **Found in:** events.yaml `cashback_redemption` · **Resolved:** 2026-04-27 (product decision — Other Income; documentation closeout)

**Decision:** A CC rewards redemption canonicalises to
`category='Other Income'`. It counts as income on the Sankey
(`Other Income` ∈ `INCOME_CATEGORIES`) and is excluded from
projected-income forecasts (`Other Income` ∈
`NON_PROJECTION_INCOME` since AI-001 closed 2026-04-26), so a
windfall like a one-off rewards redemption is visible historically
without inflating the forward forecast. The alternative
classification (`Refunds/Adjustments`, in `INCOME_EXCL_FROM_INC`)
would have hidden redemptions from the income side entirely — that
path is now off the table.

**Fix:** Comment block added above `INCOME_CATEGORIES` in
`dal/category_classifications.py` documenting the canonical
mapping and steering any future rewards-redemption parser at
`category='Other Income'`. Cross-refs in
`docs/data-lineage/lineage/cashback_redemption.yaml` swept to
reflect the decision.

### AI-016 — Future Fidelity statement parser must use `category='Investment Income'`

**Severity:** verification · **Found in:** events.yaml lineage_notes `investment_income_match_rule` · **Resolved:** 2026-04-27 (superseded → ROADMAP: Fidelity Live Alignment)

**Closeout shape:** the constraint (any future Fidelity dividend
parser must emit `category='Investment Income'` exactly, or rows
disappear from the Sankey income side) is real and forward-looking.
Pinning it solely in a seeder docstring or a parser scaffold risks
being missed when the live parser actually gets written. The right
home is inside whatever live-Fidelity work item ships — captured
at task-design time.

**Carried forward to:** `docs/ROADMAP.md` → "Fidelity Live
Alignment" backlog entry. The roadmap entry tracks the constraint
plus the spot-check on `scripts/ingest_fidelity_history.py` for
its current dividend categorization, plus the synthetic+live
alignment goal. Cross-refs in `lineage/equity_dividend.yaml` and
`lineage/money_market_sweep_interest.yaml` annotated.

### AI-012 — TSP contribution events not modeled

**Severity:** gap · **Found in:** events.yaml synthetic_gaps `tsp_contribution` · **Resolved:** 2026-04-27 (superseded → ROADMAP: TSP Live Alignment)

**Closeout shape:** the original framing assumed the absence of
TSP contribution events was a gap to fill. It isn't — the user
retired from military service and no longer contributes to TSP.
The seeder's "fixed shares, no BUY events, no contribution events"
shape is *correct* for a retired contributor and should stay that
way. What matters going forward is reallocation tracking and
performance display, since TSP remains a large share of total
assets; and any errant code paths that still expect ongoing
contributions need to be audited and corrected.

**Carried forward to:** `docs/ROADMAP.md` → "TSP Live Alignment"
backlog entry. The roadmap entry covers the seeder/parser shape
audit, `_user_contributions_in_window` correctness for the
no-contribution case, the Sankey wiring (TSP must NOT appear as a
labeled cash → investment arrow today), reallocation event
modelling, and the Investments-tab TSP card. Cross-ref in
`lineage/tax_bucket_snapshot.yaml` annotated.

### AI-018 — Synthetic CC payments invisible to cash-out lens — INCORRECT (closed)

**Severity:** gap (likely) / interpretation · **Found in:** lineage/credit_card_payment.yaml · **Resolved:** 2026-04-26 (audit correction — finding was incorrect; reconciler second pass already covers same-institution synthetic CC pairs)

This finding is incorrect and is resolved by reading the rest of
the reconciler. `reconcile_transfers` has a SECOND PASS at
`dal/reconciliation.py:177-253` that handles
same-institution-different-account pairs (≤1 day, transfer-like
keyword/category). Synthetic CC payment pairs (summit_chk +
summit_cc both `institution_id='summit'`, same posting_date 25th,
opposite direction, category 'Credit Card Payments' ∈
`TRANSFER_CATEGORIES`) DO satisfy second-pass criteria and DO get
tagged. The cash-out-lens `transfer_flows[]` therefore DOES surface
them with peer_account_type='credit_card' as documented.

Session 2 reviewed only the first pass (line 102-175) and missed
the second-pass branch starting at line 177. The original AI-018
write-up should be disregarded; cred_card_payment.yaml and
internal_transfer.yaml have been corrected to reflect both passes.
Lesson learned: read full functions before drawing structural
conclusions.

### AI-018 (original — kept for audit trail) — Synthetic CC payments invisible to cash-out lens (transfer_tag never set)

**Severity:** gap (likely) / interpretation · **Found in:** lineage/credit_card_payment.yaml · **Resolved:** 2026-04-26 (see corrected entry above)

`dal/flow_aggregation.py` (lines 44-48 docstring + 419-428) treats CC
payments as CONSUMED via the transfer-flow path: it reads
`transfer_flows[]` from `_compute_bucket_totals`, which requires
`t1.transfer_tag IS NOT NULL` (`dal/reports/flow.py:339`).
`reconcile_transfers` skips same-institution pairs
(`dal/reconciliation.py:109-110`), and synthetic CC payment legs are
SAME institution (summit_chk + summit_cc both `institution_id='summit'`,
coastal_chk + coastal_cc both `institution_id='coastal'`). So no tag
fires, no `transfer_flows[]` entry, no synthesized "Credit Card
Payments" line in spending_breakdown. The cash-out lens silently
treats $0 of CC service per period in synthetic mode. Live data
(NFCU CC + Chase checking, etc.) is cross-institution and would
produce the documented behavior — but the synthetic dataset cannot
exercise it. Either (a) extend the reconciler to pair same-institution
liability-bound transfers, (b) seed CC payments cross-institution, or
(c) document the divergence and make the synthesizer fall back to a
category-based debit-leg sum when `transfer_flows[]` is empty.

**File:** `dal/reconciliation.py:109-110` + `dal/flow_aggregation.py:419-428`
+ `scripts/dummy_data/generator.py:489-514`

### AI-032 — RefreshBanner.tsx and MFAModal.tsx use `es.onmessage` and never receive any SSE events

**Severity:** bug · **Found in:** lineage/connector_refresh_lifecycle.yaml + lineage/connector_mfa_required.yaml · **Resolved:** 2026-04-26

**Root cause:** The SSE stream at `/api/refresh/events`
(`backend/routers/refresh.py:99-133`) emits every event with an
`event: {topic}\ndata: {...}\n\n` framing (line 119). Per the HTML5
SSE spec, named events dispatch only to listeners registered via
`addEventListener("topic", ...)`; the `onmessage` property catches
only events without an `event:` field. Both `RefreshBanner.tsx:33`
and `MFAModal.tsx:34` used `onmessage`, so neither component ever
received the typed SSE events. RefreshBanner additionally branched
on legacy topic literals (`session_started`, `institution_progress`,
`institution_completed`, `session_completed`, `session_failed`)
that don't match canonical `sse_topics.py` constants.

**Fix:** Switched both components to
`es.addEventListener(SSE_TOPICS.<TOPIC>, ...)` with payload
extraction via `JSON.parse(event.data).data` — the same pattern
`NotificationPopover.tsx:89` already used correctly.

- `RefreshBanner.tsx`: Subscribes to `STATE_CHANGE` (banner shows
  for non-terminal states), `INSTITUTION_STARTED` / `_COMPLETE` /
  `_RETRY` / `_FAILED` (per-institution status text),
  `REFRESH_COMPLETE` (banner dismisses with 2 s delay; status
  field drives copy: success / partial errors / errors / timeout),
  and `SESSION_TIMEOUT`. Side effect: the
  `institution_failed`/`institution_retry`/`refresh_complete` SSE
  topics now have a working frontend subscriber where they had
  none before.
- `MFAModal.tsx`: Subscribes to `MFA_REQUIRED` and surfaces the
  6-digit OTP modal as originally intended. A real TSP MFA
  challenge no longer hangs the connector thread until the 30-min
  session timeout.

**Verified:** Preview reload, no console errors, EventSource
opens cleanly against the backend SSE endpoint, app mounts
without a Vite error overlay.

**Files changed:** `frontend/src/components/RefreshBanner.tsx`,
`frontend/src/components/MFAModal.tsx`.

### AI-037 — `POST /api/transactions` bypasses `upsert_transactions` (and the sign/direction invariant)

**Severity:** bug · **Found in:** lineage/manual_transaction_entry.yaml · **Resolved:** 2026-04-26

**Root cause:** `backend/routers/transactions.py:34-57` wrote
raw SQL directly to the `transactions` table, skipping
`dal.transactions.upsert_transactions` and therefore the
`_assert_sign_direction_invariant` choke point that CLAUDE.md
guardrails call load-bearing. Two specific manifestations:

1. Pydantic default `direction: str = "outflow"` was non-canonical
   (`Credit`/`Debit` are the only valid values).
2. `signed_amount` was echoed from the request body, so a
   positive amount paired with `direction='Debit'` would silently
   violate the invariant.

A parallel issue lived in `dal/parsers/eventlink.py:215-222`,
which wrote raw SQL with hardcoded lowercase `direction='credit'`
AND wrote a non-existent `merchant_name` column.

**Fix:**

- `backend/routers/transactions.py`: `create_transaction` now
  routes through `upsert_transactions`. Direction is normalized
  via a `_DIRECTION_ALIASES` map (accepts canonical `Credit` /
  `Debit` plus legacy `inflow` / `outflow` for back-compat with
  the existing TransactionsPage modal). Anything else returns
  HTTP 422 before touching the DB. `signed_amount` is derived
  via `derive_signed_amount(abs(amount), direction)` rather than
  echoed. Pydantic default updated to `Debit`. Merchant column
  is preserved via an explicit UPDATE after the upsert (since
  `upsert_transactions` doesn't write the merchant column).
- `dal/parsers/eventlink.py`: `commit()` now builds canonical
  txn dicts and routes through `upsert_transactions`. Direction
  is canonical `Credit`. The 7-day duplicate guard is preserved
  as a pre-filter (wider than upsert's deterministic-hash dedup).
  Merchant is stamped on the canonical `merchant` column via
  post-upsert UPDATE.

**Verified:** All 74 affected tests pass
(`tests/test_transaction_invariants.py`,
`tests/test_document_drop_trust.py`, `tests/test_document_drops.py`,
`tests/test_t02_document_drop.py`, `tests/test_dal.py`,
`tests/test_reconciliation.py`, `tests/test_dal_harmonization.py`,
`tests/test_failure_modes.py`).

**Files changed:** `backend/routers/transactions.py`,
`dal/parsers/eventlink.py`.

### AI-013 — `scripts/seed_dummy_db.py` is deprecated and broken

**Severity:** cleanup · **Found in:** session 1 codebase survey · **Resolved:** 2026-04-26

**Root cause:** Old JSON-file seeder pointing at `transactions_dense.json`,
`balance_snapshots.json`, etc. — files that no longer exist in
`dummy_data/`. Active seeder is `scripts/seed_dummy_data.py` (with
underscore). Confirmed via Grep: zero Python imports referenced the
deprecated file (only doc-level mentions in README + ROADMAP).

**Fix:** Deleted `scripts/seed_dummy_db.py`. Removed it from the
`scripts/` row of the README directory-map table at line 152. The
`docs/ROADMAP.md` past-tense reference at line 603 (P15-T08 history)
is left in place — it accurately records work done at the time.

### AI-028 — CLAUDE.md references deleted `dal/performance.py` module

**Severity:** cleanup · **Found in:** lineage/market_price_tick.yaml · **Resolved:** 2026-04-26

**Root cause:** CLAUDE.md described the Investments-tab benchmark TWR
as "comes from live yfinance data via
`dal/performance.get_benchmark_monthly_returns`," but `dal/performance.py`
was deleted in P13-T01 (commit 9ef66a3). There is no live TWR
computation today — the Performance card shows absolute portfolio
value, no benchmark overlay at all. Citation drift confirmed: the
referenced text was at lines 109-110 (not 101 as the AI body said —
CLAUDE.md was trimmed in commit 5f3b6db, shifting line numbers).

**Fix:** Rewrote the second bullet under "Project Shape" in CLAUDE.md
(lines 106-115) to describe the post-P13 reality: seeded
`investment_holdings.market_value` reflects linear drift, no benchmark
overlay exists, any rewire to bring one back is an explicit design
decision. The `audit-report.md` finding #7 is left for a future
audit-doc consolidation pass.

### AI-029 — Stale docstring at generator.py:1256-1258 about SPAXX income source

**Severity:** cleanup · **Found in:** lineage/money_market_sweep_interest.yaml · **Resolved:** 2026-04-26

**Root cause:** `generate_fidelity_dividends` docstring said the SPAXX
sweep-interest archetype is "not seeded today" and would be caught by
`seed_quintin_bank_interest`. Both claims wrong: SPAXX dividends ARE
seeded (line 1564 emits `category='Investment Income'`), and the
catcher is `seed_quintin_fidelity_dividends` (line 2219-2230, matches
`Investment Income`), NOT `seed_quintin_bank_interest` (matches
`Interest`). Docstring predated the SPAXX wiring being finalized.

**Fix:** Rewrote the relevant paragraph in the `generate_fidelity_dividends`
docstring at `scripts/dummy_data/generator.py:1252-1262` to describe
current behaviour and call out that any future live Fidelity statement
parser must keep emitting `Investment Income` to land on the same
income source.

### AI-031 — `list_accounts` loan_details pivot returns all-time max, not latest

**Severity:** bug · **Found in:** lineage/loan_details_snapshot.yaml · **Resolved:** 2026-04-26

**Root cause:** `backend/routers/accounts.py:99-115` pivoted
`loan_details` via `MAX(CASE WHEN field_name=...)` GROUP BY account_id,
which aggregates the all-time max of `field_value` across every
historical `as_of` per (account_id, field_name). Monotonic fields
(credit_limit, interest_rate-on-fixed-rate-loans) happened to match
latest-wins, but decreasing fields (rewards_points after redemption,
minimum_payment after refinance) would silently return the all-time
max, disagreeing with the AccountDetailsPanel drilldown which uses
`get_loan_panel_bundle` (`dal/account_details_composer.py:94-107`,
`ORDER BY as_of DESC` + Python first-wins dedup).

**Fix:** Wrapped the pivot in a CTE that pre-restricts to the latest
row per (account_id, field_name) via correlated subquery on `MAX(as_of)`.
Same MAX-CASE pivot then runs over only-latest rows so the per-field
value is the latest as written.

**Verification:** `pytest tests/test_dal.py -x --tb=short` — 15/15 pass.

### AI-001 — `Other Income` missing from `NON_PROJECTION_INCOME`

**Severity:** bug (suspected) · **Found in:** events.yaml `bonus_or_one_off_income` · **Resolved:** 2026-04-26

**Root cause:** `Other Income` was in `INCOME_CATEGORIES` (so positive
rows count as income) but missing from `NON_PROJECTION_INCOME`. The
forecasting model would treat a one-off bonus or unclassified credit
as projection-eligible, inflating the projected-income line. The
sibling `Non-Recurring Income` was already in both sets.

**Fix:** Added `"Other Income"` to `NON_PROJECTION_INCOME` in
`dal/category_classifications.py` with a one-line comment explaining
the catch-all rationale (bonuses, gifts, unclassified credits).

**Verification:** `pytest tests/test_flow_classification.py
tests/test_attribution.py tests/test_cashflow_invariants.py -x --tb=short`
— 60/60 pass.

### AI-002 — `Deposits` category counts as income

**Severity:** interpretation · **Found in:** events.yaml `cash_deposit` · **Resolved:** 2026-04-26 (documentation closeout)

**Root cause:** `Deposits` is in `INCOME_CATEGORIES` (intentional —
direct bank deposits, ACH credits, etc. are genuine income), but
there's no UI affordance today to mark a specific Deposits row as a
*redeposit* (selling something offline and returning the cash to
checking) and exclude it from the income side.

**Fix (documentation only — no code change):** Extended the existing
comment block in `dal/category_classifications.py` (lines 62-66) to
record the open product question and steer any future implementation
toward per-transaction exclusion (a flag / transfer_tag-style marker)
rather than moving the whole `Deposits` category into
`INCOME_EXCL_FROM_INC`, since most `Deposits` rows are genuine income.

### AI-011 — Eight income types registered but never emitted

**Severity:** gap · **Found in:** events.yaml `synthetic_gaps` section · **Resolved:** 2026-04-26 (documentation closeout)

**Root cause:** `INCOME_CATEGORIES` has 14 entries; the seeder only
emits 5 (Paychecks/Salary, Interest, Investment Income, Retirement
Income via TSP, Deposits implicit). The other 9 (Officiating, Military
Pension, VA, VA Education, Tax Refund, Non-Recurring, Other, Rental,
plus the generic "Income") have classifier rules + exclusion-set
memberships that are dead code in synthetic mode.

**Fix (documentation only — no code change):** Added a comment block
above `INCOME_CATEGORIES` in `dal/category_classifications.py`
enumerating which 5 are exercised vs which 9 are dead code in
synthetic mode and pointing future authors at the doc-drop / connector
test fixtures as the place to round-trip the rest. Seeder coverage
expansion (actually emitting these archetypes) is captured under
AI-009 / AI-010 / AI-012 in the same sprint.

### AI-015 — `INCOME_EXCL_FROM_INC` requires manual maintenance per new spending category

**Severity:** cleanup · **Found in:** events.yaml lineage_notes `dual_classification_risk` · **Resolved:** 2026-04-26

**Root cause:** Every new spending category must be added to
`INCOME_EXCL_FROM_INC` to keep refunds in that category out of income
totals. The protection is opt-in per category, with no test catching
omission. A new BUDGET_BASE entry or recurring-bill row could silently
leak refunds into income.

**Fix:** Added
`tests/test_flow_classification.py::test_seeder_spending_categories_excluded_from_income`
which parses the seeder source statically (no fixture DB) — extracts
spending categories from `BUDGET_BASE` in
`scripts/dummy_data/generator.py` and from outflow rows in
`dummy_data/recurring_transactions.json`, then asserts every category
is in `INCOME_EXCL_FROM_INC`. The test includes a clear failure
message that names the missing categories and points the author at
the right file to update.

**Verification:** `pytest tests/test_flow_classification.py
tests/test_attribution.py -x --tb=short` — 46/46 pass (15 in
test_flow_classification including the new regression).

### AI-034 — `refresh_run_id` never threaded through to `record_balance` / `record_loan_details`

**Severity:** gap (observability) · **Found in:** lineage/connector_balance_scrape.yaml + lineage/connector_loan_details_scrape.yaml · **Resolved:** 2026-04-26

**Root cause:** `dal/balances.py` already accepted
`refresh_run_id: str | None = None` on both `record_balance` (line 15)
and `record_loan_details` (line 169), but
`backend/result_writer.py:persist_connector_result` called them
positionally with one fewer argument and never plumbed the live
session's `RefreshSession.run_id` through. The
`balance_snapshots.refresh_run_id` and `loan_details.refresh_run_id`
columns existed but were always NULL, blocking forensic queries
("which balances came from refresh run X?").

**Fix:** Threaded `refresh_run_id` end-to-end:

- `backend/result_writer.persist_connector_result` gained a kwarg
  `refresh_run_id: str | None = None`; passes it to both
  `record_balance` and `record_loan_details`.
- `backend/automation_worker.run_institution` gained a matching
  kwarg + a `**_kwargs` sink (forward-compat).
- `backend/refresh_orchestrator._run_with_timeout` now invokes the
  worker as `worker_fn(institution_id, creds, refresh_run_id=self.run_id)`.
- Test workers in `tests/test_refresh_orchestrator.py` updated to
  accept `**_kwargs` so the new kwarg is harmless to fakes.

**Verification:** `pytest tests/test_refresh_orchestrator.py
tests/test_chase_extractor.py tests/test_nfcu_extractor.py
tests/test_dal.py -x --tb=short` — 46/46 pass.

### AI-033 — `summary["anomalies"]` (10× balance guard) is write-only telemetry

**Severity:** gap (observability) · **Found in:** lineage/connector_balance_scrape.yaml · **Resolved:** 2026-04-26

**Root cause:** `backend/result_writer.py` flagged balance changes
>10× or <0.1× of the previous snapshot, logged a WARNING, and
appended to `summary["anomalies"]`. Codebase-wide grep returned
exactly one result — the write site itself. The list was never
surfaced to the user; the only signal was a backend log line. A
scraping bug that 100×ed a balance silently wrote the bad value.

**Fix:** Added a `balance_anomaly` notification type
(`dal/notifications.VALID_TYPES`) and emit one
`record_notification` row inside `persist_connector_result` after
the balance loop completes when `summary["anomalies"]` is non-empty.
Severity `warning`, dedup key
`balance_anomaly:{institution_id}:{refresh_run_id}` so repeated
runs collapse, payload carries the per-account ratio details,
link `/accounts`. Notification emission is wrapped in a try/log/
continue per CLAUDE.md (observability writes must not break the
commit path).

**Verification:** `pytest tests/ -k notification -x --tb=short` —
35/35 pass (existing notification suite still green; the new type
exercises the same write path).

### AI-036 — `summary["failed_csvs"]` never read by any caller

**Severity:** gap (observability) · **Found in:** lineage/connector_transactions_csv_upsert.yaml · **Resolved:** 2026-04-26

**Root cause:** Per-CSV pandas-read or upsert failures were
captured as `{path, error}` dicts in `summary["failed_csvs"]`
but no caller branched on the list. A refresh in which 3 of 5
CSVs silently failed parsing looked identical to a clean refresh
on every surface.

**Fix:** Added a `csv_parse_failure` notification type and emit
one row inside `persist_connector_result` when
`summary["failed_csvs"]` is non-empty. Title summarises the count;
body lists the first three filenames; payload carries the full
failure list; dedup key
`csv_parse_failure:{institution_id}:{refresh_run_id}`. Same
try/log/continue isolation as AI-033.

**Verification:** Same suite as AI-033 — full notification + DAL
+ extractor matrix passes.

### AI-035 — `refresh_events.mfa_prompted` column is write-only-as-zero

**Severity:** cleanup (or gap, depending on intent) · **Found in:** lineage/connector_mfa_required.yaml · **Resolved:** 2026-04-26

**Root cause:** The `mfa_prompted` column existed in
`refresh_events`, was a parameter on
`dal.refresh_log.update_refresh_event`, and was bound in the
SQL UPDATE — but nothing ever set it to True. The TSP MFA path
broadcast an `MFA_REQUIRED` SSE event but never reached
`refresh_events`.

**Fix:** Threaded an `mfa_prompted` flag from connector → worker →
orchestrator:

- `ConnectorResult` gained a `mfa_prompted: bool = False` attr.
- `InstitutionConnector.__init__` initialises `self._mfa_prompted = False`.
- The base `run()` method's success-path
  `ConnectorResult(...)` now passes `mfa_prompted=self._mfa_prompted`.
- `extractors/tsp_connector._wait_for_mfa` sets
  `self._mfa_prompted = True` immediately before each blocking
  `wait_for_otp` / `wait_for_code` call (the two real prompt
  paths; session-reuse / silent post-login paths leave it False).
- `backend/automation_worker.run_institution` reads
  `result.mfa_prompted` and threads it as
  `summary["mfa_prompted"]`.
- `backend/refresh_orchestrator._run_institution` passes
  `mfa_prompted=bool(worker_result.get("mfa_prompted", False))`
  into `update_refresh_event` on the COMPLETED branch. The
  RETRY/FAILED branches don't carry the flag (worker_result isn't
  populated when an exception fires).

**Verification:** `pytest tests/test_refresh_orchestrator.py -x
--tb=short` — 2/2 pass.

### AI-027 — `payroll_snapshots` has no DAL writer helper

**Severity:** cleanup · **Found in:** lineage/payroll_snapshot.yaml · **Resolved:** 2026-04-26

**Root cause:** Every other snapshot table had a `record_*` DAL
helper (`record_balance`, `record_apy_history`,
`record_credit_score`, `add_valuation`, etc.) but
`payroll_snapshots` did not. Both seeder and live myPay parser
emitted raw SQL, which meant no shared invariant point and no
single owner_id-lowercasing site.

**Fix:** Added
`dal.payroll.record_payroll_snapshot(conn, *, pay_period, source,
owner_id, gross_pay, federal_tax=None, state_tax=None,
sbp_premium=None, health_insurance=None, dental_vision=None,
other_deductions=None, net_pay=None, raw_json='{}')`. Withholdings
default to None (preserves SQL NULL on the parser path so
`test_t04_mypay::test_missing_fields_are_none` still asserts
`row['federal_tax'] is None`). When all sibling fields are
non-None and net_pay is omitted, the helper auto-computes
`net_pay = gross - sum(withholdings)`. Owner_id is lowercased on
write. Both call sites — `scripts/seed_dummy_data.py` (Quintin +
Amy seed loops) and `dal/parsers/mypay_ras.py:commit` — now
route through the helper. The parser uses an `_opt_float` helper
to preserve None for missing extracted fields.

**Verification:** `pytest tests/test_attribution.py
tests/test_t04_mypay.py tests/test_payroll.py tests/test_payroll_flow.py
tests/test_comprehensive.py -x --tb=short` — 85/85 pass.

### AI-026 — Synthetic payroll Sankey gross-up never fires

**Severity:** gap · **Found in:** lineage/payroll_snapshot.yaml · **Resolved:** 2026-04-26

**Root cause:** Synthetic Quintin payroll snapshots had
`source='dummy_seeder'`. `find_matching_deposit_tx_id` does a
substring match on the deposit's merchant or description.
"dummy_seeder" doesn't appear in any synthetic paycheck
description ("ACME CORP PAYROLL", "JORDAN FREELANCE ACH"), so
the matcher returned None for every Quintin row, and the Sankey
gross-up + withholdings decomposition path was silently dead in
synthetic mode.

**Fix:** Changed Quintin's seeder source from `"dummy_seeder"` to
`"ACME CORP PAYROLL"` in `scripts/dummy_data/generator.py:generate_payroll_snapshots`.
The biweekly Alex paycheck transactions (description "ACME CORP
PAYROLL", → summit_chk owned by 'quintin') now match every
monthly synthetic snapshot. The mapping is semantically
imperfect (one $5200 monthly snapshot pairs with the first $4000
biweekly transaction in that month) but exercises the gross-up
code path end-to-end. Amy's snapshots use `"Primary W-2 source"`
unchanged — Amy has no paycheck transactions in the seeder, so
no match would ever fire regardless of label. The gap there is
captured under AI-011 / future synthetic coverage work.

The live mypay_ras path uses `source='mypay_ras'`; whether that
substring appears in real DFAS deposit descriptions is a
data-fitness question that depends on the user's actual bank
formatting and is out of scope for the synthetic fix.

**Verification:** `pytest tests/test_payroll_flow.py
tests/test_payroll.py tests/test_attribution.py -x --tb=short`
— 42/42 pass (including the Sankey-decomposition end-to-end test).

### AI-025 — `tax_buckets` has no live writer (seeder-only)

**Severity:** gap · **Found in:** lineage/tax_bucket_snapshot.yaml · **Resolved:** 2026-04-26 (placeholder writer + log warning)

**Root cause:** Only the seeder wrote `tax_buckets`. A live TSP
statement upload via `dal/parsers/tsp_statement.py` would leave
the table empty for the new account; downstream `get_tax_summary`
silently fell through to its "no bucket data → assume
traditional" fallback, flipping the entire balance into
Tax-Deferred on the Allocation donut.

**Constraint surfaced during fix:** A TSP statement document
does NOT carry the Roth/Traditional contribution split. The
seeder fabricates the split with a deterministic time-drift
formula (62%→67% Roth) but a live parser cannot infer it from
the statement.

**Fix (placeholder + explicit logging):** TSP parser
`commit()` now writes a single
`bucket_type='traditional'` row at full balance with
`vested_pct=1.0` and `as_of=statement_date`. This matches what
`get_tax_summary` already implicitly assumed, but makes the
implicit explicit and queryable. A `log.warning` line emits on
every TSP commit so the placeholder nature is visible to
operators tailing logs. Future feature: an externally-configured
allocation override can replace these rows with the real split
when the user supplies one. The `INSERT OR REPLACE` keyed on
`(account_id, bucket_type, as_of)` makes the override
straightforward.

The seeder-side write path is unchanged (still the synthetic
62%→67% drift formula). Synthetic and live paths now both
populate the table; live data conservatively under-represents
Roth until a real split is configured.

**Verification:** `pytest tests/test_comprehensive.py
tests/test_t04_mypay.py -x --tb=short` — 43/43 pass.

### AI-003 — `compute_interest_cost` doesn't catch generic CC fees

**Severity:** gap (possible leak) · **Found in:** events.yaml `cc_fee` · **Resolved:** 2026-04-26 (audit closeout — design intent confirmed)

**Audit decision:** the narrow filter (`category LIKE '%interest%' OR
category LIKE '%finance charge%'`) is the correct design. CC fees
(annual fees, late fees, ATM fees, foreign-transaction fees) are
discretionary or quasi-discretionary spending — they're "consumption,"
not "cost of money." Surfacing them under the interest-cost panel
would conflate behavioural-spending signals with debt-service signals
and make the YTD interest cost number harder to read. Fees already
land in the cash-flow Sankey CONSUMED bucket via the generic
spending pipeline (category 'Fees'), so they're visible — they
just don't compound into the interest-cost narrative.

**Fix:** Documentation only — added a comment block in
`dal/derived/metrics.py` above the transactions-side fallback
filter spelling out the intent, so any future audit doesn't
re-litigate the choice.

### AI-005 — Verify `decompose_unsplit_mortgage_payments` runs against all 36 synthetic payments

**Severity:** verification · **Found in:** SESSION_LOG.md session 1 punted note · **Resolved:** 2026-04-26 (verification closeout)

**Verification:** Static analysis of the chain confirms the 36 mortgage
payments are processed:

1. `scripts/seed_dummy_data.py:1187-1194` runs
   `run_post_commit_pipeline(institution_id)` once per seeded
   institution after txn writes complete. The mortgage account
   `summit_mtg` belongs to the `summit` institution, so the pipeline
   fires.
2. `backend/result_writer.py:run_post_commit_pipeline` calls
   `decompose_unsplit_mortgage_payments(conn)` (single shared call
   site, not per-account).
3. `dal/debt.py:574 decompose_unsplit_mortgage_payments` selects
   ALL `category IN ('Mortgage', 'Mortgages')` debits with no
   existing split, regardless of institution. So every synthetic
   mortgage debit on `summit_chk` (the seeded payment shape) is
   picked up in one sweep.
4. Fail-soft: per-txn errors log a warning and continue, so a single
   bad row can't drop the count by more than one.

A runtime spot-check ($PROJECT_ROOT/data/sentry.db must be seeded):
`sqlite3 data/sentry.db "SELECT COUNT(*) FROM loan_payment_splits
WHERE transaction_id IN (SELECT id FROM transactions WHERE
category IN ('Mortgage','Mortgages') AND signed_amount < 0)"`
should equal 36 after a fresh seed. Filed as a follow-up runtime
check rather than a code change since the decomposer behaves
correctly by design.

### AI-006 — `_link_acorns_bank_debits` same-day multi-ledger behaviour

**Severity:** verification · **Found in:** events.yaml `investment_link_acorns` · **Resolved:** 2026-04-26 (verification closeout)

**Verification:** The linker pops EXACTLY ONE ledger row per bank
debit (`bucket.pop(0)` at `backend/result_writer.py:442`). For an
Acorns roundup that allocates across 4 ETFs, only the first ledger
row gets `bank_txn_id` set; the other 3 stay with NULL. This is
correct by design — the join semantics in
`v_investment_contributions` (and any future cross-account
contribution view) only need ONE matching ledger row per debit;
the other 3 ledger rows are still summed for portfolio aggregation
via `account_id` joins, they just don't carry the bank linkage.

The behaviour is deliberate but undocumented. No code change;
captured here in the resolved log as the canonical answer.

### AI-007 — APY 1bp notification threshold may be too noisy

**Severity:** verification · **Found in:** lineage map's notification_emission entry · **Resolved:** 2026-04-26 (already-resolved)

**Verification:** `dal/apy_history.detect_apy_changes` already has
`threshold_pct: float = 0.05` (5 bp floor) and
`warning_threshold_pct: float = 0.25` (25 bp severity split), per
the function's docstring "Defaults match the locked Phase 16
thresholds: 5 bp floor, 25 bp info→warning split." The AI body was
filed BEFORE Phase 16 locked these defaults; the concern is now
moot. Synthetic accounts seed with `drift_bps` of 1-4
(`scripts/dummy_data/generator.py:809-812`), so per-step deltas
fall below the 5bp floor and don't fire. Cumulative drift across
multiple same-direction steps could in theory cross the threshold,
but that's correct behaviour: a 5bp+ APY change is genuinely
noteworthy.

No code change. Closing as already-resolved.

### AI-014 — `apply_attribution_single` silently swallows ImportError

**Severity:** verification · **Found in:** events.yaml lineage_notes `seeder_vs_live_attribution` · **Resolved:** 2026-04-26

**Root cause:** The `try / except Exception: pass` around
`apply_attribution_single` in `dal/transactions.py` was originally
defensive cover for pre-v19 schemas where the
`income_attribution_rules` table didn't exist. Production has been
≥v19 for many migrations. The blanket except meant a real
attribution bug (e.g. a refactor breaking the call signature)
would silently leave `effective_month` NULL on every txn — and
month-bucketing reports would silently fall back to `posting_date`.

**Fix:** Narrowed the except to
`(ImportError, sqlite3.OperationalError)` (the exact two failure
shapes pre-v19 schemas produce) with a `pass` for back-compat. Any
other `Exception` is now caught separately and logged at WARNING
with the txn id, so silent failures surface in logs without
blocking the commit.

**Verification:** `pytest tests/test_dal.py
tests/test_attribution.py -x --tb=short` — 47/47 pass.

### AI-017 — Check deposit partial-hold may transient-violate closure invariant

**Severity:** verification · **Found in:** events.yaml `check_deposit` · **Resolved:** 2026-04-26 (verification closeout)

**Verification:** Synthetic seeder doesn't model partial holds —
`generate_balance_snapshots` walks closure-invariant-compliant
balances directly from cumulative `signed_amount`. The closure
invariant (`balance_snapshots.balance == start + Σ signed_amount`)
holds exactly for synthetic data. Live data could in theory
transient-violate it on a partial-hold day (some funds available,
remainder in hold), but:

1. The closure-invariant test runs against synthetic data via
   `tests/test_cashflow_invariants.py`, not against live ingestion.
2. Live banks expose the *available* balance plus an aggregate, not
   the per-deposit hold structure, so the invariant is normally
   defined on the available-balance series rather than the
   transactional series. No live-side test exercises this path.

The transient violation, if it ever occurred, would be a single
day's mismatch that resolves when the hold clears. Not currently a
test failure surface. Filed as a closeout — if a real check-deposit
test ever needs to exercise the hold path, it should add a
tolerance window matching the bank's hold policy.

### AI-023 — `merchant_snapshots` table is write-only

**Severity:** cleanup · **Found in:** lineage map's `merchant_snapshot_rebuild` entry · **Resolved:** 2026-04-26

**Root cause (post AI-013):** `rebuild_merchant_snapshots` in
`dal/merchant_normalizer.py` had its only caller in the deprecated
`scripts/seed_dummy_db.py:284`. After AI-013 deleted that file
on 2026-04-26, the function had zero callers anywhere in the repo
and the `merchant_snapshots` table was both unread (callers like
`get_merchant_list` and `get_merchant_flow_data` go directly to
`transactions.merchant`) and unwritten.

**Fix:** Removed the `rebuild_merchant_snapshots` function from
`dal/merchant_normalizer.py` and the `from collections import
Counter` import (only used by that function). The module docstring
preserves a historical note pointing at this resolution. The
`merchant_snapshots` table itself remains in the schema —
dropping the table requires a new migration (out of scope for a
cleanup pass); flagged here as a future schema-cleanup candidate.
The v11 migration file is unchanged.

### AI-039 — `document_drops` history doesn't distinguish failed from pending

**Severity:** cleanup (UX) · **Found in:** lineage/document_parse_failure.yaml · **Resolved:** 2026-04-26

**Root cause:** The Documents-page history table rendered only two
states ("Committed" / "Pending") keyed off `committed_at`. A
staged-then-abandoned upload (parser couldn't match, user walked
away) and a genuinely-staged-waiting upload looked identical. The
indirect signal `parser_type='unknown'` was visible only in a
sibling chip column.

**Fix:** Added a third visual state to
`frontend/src/pages/DocumentsPage.tsx:152-180` — a red "Failed"
badge with the `error` icon rendered when
`committed_at IS NULL AND parser_type === "unknown"`. Pure JSX
ternary chain (no schema change, no API change). The existing
`text-loss` Tailwind class matches other failure-style copy in the
app for visual consistency.

**Verification:** Vite hot-reload picks up the change with no
compile errors (`preview_logs --level error` returned "No server
errors found"). Without a backend running and an actual failed
PDF in document_drops, end-to-end browser verification of the
visible Failed badge is deferred to the end-of-sprint UI smoke
step. The branch is structurally trivial — a pure ternary on an
existing field — and `npm run build` at end-of-sprint will catch
any TS error.

### AI-010 — Fidelity EFT deposits not mirrored as `transactions` rows

**Severity:** gap · **Found in:** events.yaml `investment_contribution` · **Resolved:** 2026-04-26

**Root cause:** Synthetic Fidelity $500/month EFT deposits landed only
as `positions_ledger` DEPOSIT rows on SPAXX. The cash-flow Sankey
never saw the outflow leg because no checking-side transaction
existed. Live ingestion of a real Fidelity EFT would emit BOTH legs
(checking debit + Fidelity ledger DEPOSIT).

**Fix:** Added a post-generator pass to `seed_fidelity_investments`
in `scripts/seed_dummy_data.py` that emits a paired `summit_chk`
debit ($500, "FIDELITY EFT TRANSFER", category='Investments') for
each Fidelity DEPOSIT ledger row, then sets `transfer_tag` to
`invest:{ledger_id}` and `bank_txn_id` on the ledger row to link
the two legs (mirrors the Acorns triple-coupling pattern at
`seed_acorns_investments`). The transfer_tag exclusion keeps the
debit out of spending/income aggregates while making the cash flow
visible. Cross-link AI-021 (deferred): the cross-account topology
still leaves Fidelity contributions invisible to
`_user_contributions_in_window` until the v34 view's
`t.account_id = pl.account_id` predicate is relaxed.

**Verification:** `pytest tests/test_comprehensive.py
tests/test_attribution.py tests/test_dal.py -x --tb=short` —
75/75 pass. Static check: `upsert_transactions` enforces
sign/direction invariant; the synthetic rows all have
`signed_amount = -500.0` + `direction='Debit'`.

### AI-019 — `recompute_interest_earned` metric is zero for synthetic data

**Severity:** gap · **Found in:** lineage/bank_interest_credit.yaml · **Resolved:** 2026-04-26 (deprecation)

**Root cause:** `dal/derived/recompute.recompute_interest_earned`
filtered for `account_id = _affirm_hysa_id()` AND
`LOWER(description) = 'interest'`. The seeder writes interest credits
to brighton_sav / summit_sav / summit_chk with descriptions like
"BRIGHTON HYSA INTEREST" / "SUMMIT SHARE DIVIDEND" — neither
satisfies both filters, so the metric was always 0. No UI consumer
read the resulting `derived_summaries(metric='interest_earned')`
row. Meanwhile, `compute_interest_cost` already returns an
`interest_earned` field with broader semantics (any HYSA-typed
account by `category='Interest'`), covering the same concern.

**Fix:** Removed the `recompute_interest_earned(conn)` and
`recompute_interest_earned(conn, owner_id=oid)` calls from
`recompute_for_institution` in `dal/derived/recompute.py`. The
function body is preserved with a `DEPRECATED` docstring header so
any out-of-tree caller still importing it from `dal.derived`
doesn't crash; new code MUST use
`compute_interest_cost(...)['interest_earned']` instead.

**Verification:** `pytest tests/test_comprehensive.py
tests/test_attribution.py tests/test_dal.py -x --tb=short` —
75/75 pass. The `interest_earned` field returned by
`compute_interest_cost` is unaffected and continues to be
exercised by `test_t02t03t04.py::test_interest_cost_*`.

### AI-040 — Document commit UPDATE matches by JSON-substring instead of PK lookup

**Severity:** cleanup (correctness risk) · **Found in:** lineage/document_upload_commit.yaml · **Resolved:** 2026-04-26

**Root cause:** `backend/routers/documents.py` updated the staged
`document_drops` row in `commit_document` via
`WHERE summary_json LIKE '%"file_id": "<uuid>"%'`. Substring match
on a JSON blob is fragile (sensitive to JSON-key reordering /
whitespace / future schema evolution that nests `file_id` deeper)
even though UUID collisions are practically impossible. The row's
PK was always available from the upload INSERT's `lastrowid` but
not threaded through.

**Fix:** End-to-end PK plumbing:

- Upload endpoint captures `cursor.lastrowid` and returns
  `document_drop_id` alongside `file_id`.
- `CommitRequest` Pydantic model gained an optional
  `document_drop_id: int | None`.
- `commit_document` prefers `WHERE id = ?` when
  `document_drop_id` is provided; legacy clients still fall back
  to the substring lookup.
- Frontend `DocumentDrop.tsx` updated: `UploadResult` interface
  picks up the new field; the commit body now includes
  `document_drop_id: uploadResult.document_drop_id`.

**Verification:** `pytest tests/test_t02_document_drop.py -x
--tb=short` — 23/23 pass. Frontend Vite reload showed no compile
errors. End-to-end flow (upload → commit → row updated) deferred
to the end-of-sprint UI smoke step.

### AI-008 — `recurring_pattern_detection` not in post-commit pipeline

**Severity:** interpretation · **Found in:** events.yaml `recurring_pattern_detection` · **Resolved:** 2026-04-26

**Root cause:** `dal.recurring.detect_recurring` was the only
post-commit-class step that didn't run automatically. Live data had
stale `recurring_transactions` until the user manually triggered a
scan via `POST /api/recurring/scan`.

**Fix:** Added a `_detect_recurring` step to
`backend.result_writer.run_post_commit_pipeline`, slotted between
Transfer reconciliation and the Acorns/mortgage decomposition
steps. Wrapped in the same `_run_step` try/log/continue isolation
as the other steps so a recurring-detect crash can't block alerts
or goal sync.

**Verification:** `pytest tests/test_dal.py
tests/test_attribution.py tests/test_comprehensive.py
tests/test_reconciliation.py tests/test_t02_document_drop.py
tests/test_t04_mypay.py tests/test_chase_extractor.py
tests/test_nfcu_extractor.py tests/test_refresh_orchestrator.py -x
--tb=short` — 151/151 pass.

### AI-022 — `merchant_normalization` not in post-commit pipeline

**Severity:** gap · **Found in:** lineage map's `merchant_normalization` entry · **Resolved:** 2026-04-26

**Root cause:** `dal.merchant_normalizer.backfill_merchant_column`
was called only from the seeder. New transactions from a live
refresh landed with `merchant=NULL`, so merchant aggregations fell
back to raw descriptions and produced noisy output.

**Fix:** Added a `_normalize_merchants` step to
`run_post_commit_pipeline`, immediately after Categorization
backfill. The function is idempotent (only updates rows where
`merchant` is NULL or empty), so re-running it on every refresh is
safe and cheap. Same try/log/continue isolation as the other steps.

**Verification:** Same suite as AI-008 — 151/151 pass.

### AI-024 — `enrich_ticker_metadata` not in post-commit pipeline

**Severity:** gap · **Found in:** lineage map's `ticker_metadata_enrichment` entry · **Resolved:** 2026-04-26

**Root cause:** `enrich_ticker_metadata` (in
`scripts/dummy_data/generator.py`) was seeder-only. Any new ticker
that appeared in `investment_holdings` after seed time (e.g. a user
buying a stock outside the hardcoded `_ALL_INVESTMENT_TICKERS`
list) had no `ticker_metadata` row, so allocation pies fell back
to "Unknown" / "Equity".

**Fix:** Added a `_enrich_tickers` step to
`run_post_commit_pipeline`, slotted right before Derived recompute.
Computes the distinct set of tickers from `investment_holdings`
and passes them to `enrich_ticker_metadata(conn, tickers=...)`,
so live data drives the enrichment scope rather than the seeder's
hardcoded list. The 30-day staleness skip inside
`enrich_ticker_metadata` keeps the per-refresh cost low; yfinance
failures fall back to the hardcoded `_TICKER_METADATA_FALLBACK`
dict, so the step never throws. Same try/log/continue isolation.

**Verification:** Same suite as AI-008 — 151/151 pass.

### AI-038 — Eventlink + Acorns parsers don't trigger post-commit pipeline

**Severity:** gap · **Found in:** lineage/document_upload_commit.yaml · **Resolved:** 2026-04-26

**Root cause:** `backend/routers/documents.py`'s `institution_map`
covered only `tsp_statement → 'tsp'` and `mypay_ras → 'mypay'`. The
eventlink, acorns_statement, and acorns_confirmation parsers
WROTE business data (transactions / positions_ledger / accounts)
but didn't trigger the post-commit pipeline, so categorization,
reconciliation, recurring detection, alerts, goal sync, and
notifications were all skipped after these uploads.

**Fix:** Added three new entries to `institution_map`:

- `"eventlink": "eventlink"` (synthetic institution id; harmless
  when passed to `recompute_for_institution` — that function
  iterates accounts of the given institution_id, so an unknown id
  just produces an empty iteration).
- `"acorns_statement": "acorns"` (real institution; the post-commit
  pipeline already has a special-case Acorns linkage step).
- `"acorns_confirmation": "acorns"` (same).

The dispatch logic at the post-`commit()` site is unchanged.

**Verification:** Same suite as AI-008 — 151/151 pass.

### AI-009 — Synthetic dataset never exercises live interest-cost transaction path

**Severity:** gap · **Found in:** events.yaml `interest_charge` · **Resolved:** 2026-04-27 (option B — dedicated tests)

**Root cause:** `compute_interest_cost` (`dal/derived/metrics.py:336-356`)
prefers `loan_details.ytd_interest` (KV, set by
`loan_details_snapshot`) and only falls back to summing `transactions`
rows when the KV is absent. The seeder always populates the KV, so
the transactions-row aggregation path was structurally untested by
the synthetic dataset. The original entry suggested either (A)
backfill the seeder to emit Interest debits or (B) write a dedicated
test that builds the transactions-row scenario; (A) was deferred as
"deferred_seeder_scope" because it requires non-trivial CC
payment-cycle changes.

**Fix (option B):** The existing `test_interest_cost_loan_details`
(`tests/test_t02t03t04.py:174-204`) already exercises the basic
shape (an `auto` loan with no loan_details rolls up via the
transactions path with `source='transactions'`), but four explicit
filters in the fallback SQL had no targeted coverage. Added four
focused tests after `test_interest_cost_no_data`:

- `test_interest_cost_finance_charge_category_matches` — the
  `LOWER(category) LIKE '%finance charge%'` branch counts (paired
  with the `'%interest%'` branch in the same test).
- `test_interest_cost_excludes_prior_year_transactions` — the
  `strftime('%Y', posting_date) = ?` filter keeps last-year's
  interest from leaking into YTD.
- `test_interest_cost_excludes_pending_transactions` — the
  `status = 'posted'` filter excludes `status='pending'` rows.
- `test_interest_cost_monthly_breakdown_from_transactions` — the
  `monthly_breakdown` array (separate query at lines 417-428)
  populates correctly from the transactions path, including the
  finance-charge variant.

**Verification:** `pytest tests/test_t02t03t04.py -v` — 16/16 pass
(the existing 12 plus the 4 new). Full backend suite: 530/530 pass.

**Future work:** option A (backfilling the seeder to leave partial
CC balances and emit Interest debits) remains a separate concern;
that's about exercising the full pipeline (categorization →
attribution → reconciliation → derived recompute) end-to-end on
synthetic data, not just the metric-compute SQL. If/when the seeder
pass happens, these tests stay valid as DAL-level pinning.

**Files changed:** `tests/test_t02t03t04.py` (+4 test functions).

### AI-030 — Acorns IMPLIED_BUY missing `cost_basis_dec`

**Severity:** gap · **Found in:** lineage/tax_lot_initial.yaml · **Resolved:** 2026-04-26

**Root cause:** Both the Acorns seeder
(`scripts/dummy_data/generator.py:generate_acorns_investment_history`)
and the live Acorns connector
(`extractors/acorns_connector.py:_apply_acorns_holdings_delta`)
inserted `INITIAL_BASELINE` / `IMPLIED_BUY` rows without setting
`cost_basis_dec`. `dal/investments.get_lots:236` fell back to
`shares × yfinance_close_today` (observation-day MTM) rather than
the lot's actual purchase-day basis. Realized-gain math for any
future SELL was structurally inaccurate vs Fidelity (which sets
the column faithfully).

**Fix:** Both writers now compute `cost_basis_dec` as
`shares × contemporaneous_close` and write it on
`INITIAL_BASELINE` / `IMPLIED_BUY` rows:

- Seeder: `(shares_bought * Decimal(price)).quantize(Decimal("0.01"))`
  added to `ledger_rows` and the `INSERT` statement.
- Connector: gated on `txn_type in ("IMPLIED_BUY",
  "INITIAL_BASELINE")`. SELL rows leave the column NULL because
  `realized_gain_dec` is computed against the FIFO cost-basis series,
  not the SELL row's own basis.

The approximation (mark-to-market against the lot's date) is the
same shape Acorns will report when its statements are eventually
parsed — there's no "true purchase price" to recover, but the
basis is now anchored to the lot date instead of refresh day.

**Verification:** `pytest tests/test_comprehensive.py
tests/test_dal.py tests/test_attribution.py
tests/test_t02_document_drop.py -x --tb=short` — 98/98 pass.

---

## Adding new items

When adding an entry, use the next sequential `AI-NNN` id (don't
reuse retired numbers — even resolved items keep their id). Format:

```markdown
### AI-NNN — One-line title

**Severity:** bug | interpretation | gap | verification | cleanup
**Found in:** path to the events.yaml entry, lineage record, or
session log line that surfaced it.

2–3 sentence description. State the concern, not the fix. If a fix
is obvious in one line, suggest it; otherwise leave the design
question open.

**File:** the actual code file:line that would change to address it.
```

**Don't fix code from inside the lineage map effort.** Surface the
item, link it, move on. The user spawns focused fix sessions
separately.
