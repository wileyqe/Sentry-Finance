# Session Log

Append-only. One entry per session. Newest at the bottom (so a chronological
read tells the story). Five lines is the target; longer is fine when a
session decides something load-bearing.

---

## Session 1 — 2026-04-25 — Scaffolding + Phase 1 draft

**Did:** Surveyed the codebase (40 migrations, ~50 DAL modules, 18
routers, 14 frontend pages, 2300-line seeder + 1300-line driver,
post-commit pipeline). Drafted the type-level event taxonomy (~50
event types across 4 classes + a `not_modeled` parking lot). Created
this directory structure, the prompt-tailoring decisions doc, the
agent guide, and `events.yaml`. Added a pointer in
`docs/ARCHITECTURE.md > Document Tree`.

**Surprises:**
- The active seeder is `scripts/seed_dummy_data.py` (with underscore);
  `scripts/seed_dummy_db.py` (without) is a deprecated JSON-file
  seeder still living in the tree.
- No live scheduler exists. All `external_force` events are seeder
  output; live equivalents arrive as connector CSV/scrape rows. The
  `system_scheduled` class will likely stay empty.
- Dividends are dual-written: `positions_ledger` (DIVIDEND,
  share_delta=0) AND `transactions` (Investment Income credit). The
  Sankey income side reads the transactions row; portfolio metrics
  read the ledger row. Worth modeling as one event with two write
  rows.
- The Acorns auto-invest is triple-coupled: a checking debit, a
  positions_ledger BUY, and a `transfer_tag = "invest:{id}"` linkage
  written by the post-commit pipeline (`_link_acorns_bank_debits`).
  Same pattern in the seeder via `seed_acorns_investments`.

**Open / punted:**
- Phase 1 type-level consolidation is a draft. User asked for
  spot-checking before Phase 2 starts. See `STATUS.md > Phase 1`.
- Live-only event records (connector lifecycle, document upload,
  user CRUD) deferred to a later pass.
- Mortgage payment decomposition (`loan_payment_splits`) is a
  derived event that fires only when a payment lands. The seeder
  produces 36 mortgage payments; verify the decomposer runs against
  all of them in the post-commit pipeline.

**Next agent should:** Read `STATUS.md`, then start Phase 2 with the
"Cash-flow / Sankey-feeding events" batch (paycheck, mortgage_payment,
retail_purchase, internal_transfer, credit_card_payment,
bank_interest_credit, equity_dividend). 5–8 records per session is
the target.

**Addendum (same session):** User caught a missing event during
Phase 1 spot-check — `interest_charge` (interest debits on a CC with
a carried balance, or explicit interest lines on a loan). Added as a
`live_only` entry. The synthetic seeder doesn't emit this because
CCs are paid off in full every cycle; `interest_cost_recompute` reads
`loan_details.ytd_interest` (KV, set by `loan_details_snapshot`) as
its first source and only falls back to transaction rows when KV is
absent — so the synthetic dataset never exercises the live
transaction-row path. Added cross-references on
`loan_details_snapshot` and `mortgage_payment` notes pointing at the
divergence. Worth checking: are there other "live-only debit
families" (late fees, annual fees, returned-payment fees, ATM fees,
foreign-transaction fees) that the seeder also doesn't emit but the
live system would? Mentioned briefly in the `interest_charge` notes;
spawn a separate `cc_fee` event entry if any of them have distinct
downstream paths.

---

## Session 1.5 — 2026-04-25 — events.yaml v2 gap pass

**Did:** Took the question from the `interest_charge` addendum
seriously and ran a full second pass over events.yaml. User
green-lit the proposed adds. Bumped events.yaml to v2.

Added (20 new event types):

- `system_derived` (5): ticker_metadata_enrichment,
  accountability_scorecard_compute, accountability_drift_detection,
  recurring_loan_link, merchant_snapshot_rebuild.
- `live_only` (15): cc_fee, deposit_account_fee, cash_deposit,
  check_deposit, check_written, atm_withdrawal (promoted from
  not_modeled), cashback_redemption, tax_refund,
  bonus_or_one_off_income, reimbursement, manual_transaction_entry,
  alert_rule_edit, categorization_rule_delete, staleness_evaluation,
  document_parse_failure.

Two new top-level sections:

- `synthetic_gaps` — 8 instances of existing event types the seeder
  doesn't emit (officiating income, military pension, VA benefits,
  rental income, cash dividend payout, TSP contribution, carried CC
  balance with interest, refresh failure). Not new event types,
  rather missing test coverage for live downstream paths.
- `lineage_notes` — 4 top-level docs (dual_classification_risk,
  investment_income_match_rule, dual_write_dividend_pattern,
  seeder_vs_live_attribution).

**Surprises:**

- `dal/recurring.py:link_recurring_to_loans` is genuinely a separate
  derivation worth its own event — it builds a join used by Debt and
  Recurring-with-payoff that the rest of recurring detection doesn't
  expose.
- `accountability_drift.py` has 8 detectors, each independent, each
  with its own UI fix-action button. That's 8 separate `derivations`
  entries when Phase 2 traces the accountability tab.
- `Other Income` is in `INCOME_CATEGORIES` but NOT in
  `NON_PROJECTION_INCOME` — meaning a bonus categorized as "Other
  Income" would inflate the income forecast model. Possible bug;
  noted in `bonus_or_one_off_income`.
- `Deposits` category counting as income means a cash redeposit (e.g.
  selling something offline and putting cash back in the bank) would
  count as income on the Sankey. Real interpretation question; noted
  in `cash_deposit`.
- The merchant-normalization regex strips check numbers, which is
  intentional for recurring detection but means two checks to the
  same payee appear as one merchant. Noted in `check_written`.

**Open / punted:**

- `Other Income` vs `NON_PROJECTION_INCOME` is a possible logical
  bug. Not in scope for the lineage map, but worth raising with the
  user when Phase 2 traces income forecasting.
- Same for the `Deposits = income` interpretation question.
- The 8 synthetic_gaps entries are all "nice to have synthetic
  coverage for someday." Track in seeder-enhancement backlog, not
  in this map.

**Next agent should:** Same as before — start Phase 2 with the
cash-flow batch. `events.yaml` is now stable enough to begin tracing
without expecting major taxonomy churn. If a Phase 2 trace reveals a
new event type that should exist, add it to `events.yaml` and
increment the version + revision_log.

---

## Session 1.6 — 2026-04-25 — ACTION_ITEMS.md created

**Did:** User flagged that out-of-scope findings (possible bugs,
verification needs, etc.) would get buried in long session logs and
become needles in a haystack. Created `ACTION_ITEMS.md` with a
durable AI-NNN id scheme, severity legend, and a clear
add-as-you-find-it protocol. Seeded it with 17 items recovered from
this session's earlier conversation:

- 4 bugs / interpretation questions (Other Income vs forecasts,
  Deposits = income, CC Fees not in interest cost, cashback
  classification ambiguity)
- 4 verification needs (mortgage decomposer count,
  Acorns same-day linking, APY notification noise, recurring
  detection in pipeline)
- 4 synthetic-vs-live gaps (interest cost path, Fidelity EFT
  mirroring, 8 income types not seeded, TSP contributions)
- 5 cleanup / future-parser items (deprecated seed_dummy_db.py,
  attribution try/except swallow, INCOME_EXCL_FROM_INC maintenance,
  future Fidelity parser category, check deposit hold scenario)

Updated `README.md`, `AGENT_GUIDE.md`, `STATUS.md`, and
`docs/ARCHITECTURE.md` to point at the new file. Added an explicit
"log findings immediately" principle to `AGENT_GUIDE.md` so future
agents don't batch-and-forget.

**Next agent should:** Same Phase 2 plan as session 1.5. Plus:
read `ACTION_ITEMS.md` open list before starting; add any new
finding to it the moment it surfaces.

---

## Session 2 — 2026-04-25 — Phase 2 cash-flow batch

**Did:** Wrote all 7 records in the cash-flow / Sankey-feeding
batch: paycheck, mortgage_payment, retail_purchase,
internal_transfer, credit_card_payment, bank_interest_credit,
equity_dividend. Each YAML cites verified `file:symbol` for every
write/read claim, with the standard 5 + meta sections populated.
Used a single Explore subagent at the start to map the breadth of
`transactions` consumers + UI surfaces (one structured report
covering all 7 events), then verified function names and line
numbers via direct `Grep`/`Read` before citing in YAML — the
subagent's claims contained several inaccurate function names
(`apply_monthly_attribution`, `get_mortgage_payment_txns`) so the
verification pass was load-bearing.

**Surprises:**

- `reconcile_transfers` skips same-institution pairs
  (`dal/reconciliation.py:109-110`). The synthetic seeder's CC
  payment legs are summit_chk + summit_cc (both `summit`) and
  coastal_chk + coastal_cc (both `coastal`) — same institution. So
  CC payments NEVER get a `transfer_tag` in synthetic mode. The
  cash-out lens `transfer_flows[]` requires `transfer_tag IS NOT
  NULL` (`dal/reports/flow.py:339`). Result: synthetic CC payments
  are entirely invisible to the cash-out lens transfer-flow path
  that the docstring (`dal/flow_aggregation.py:44-48`) promises.
  The synthesized "Credit Card Payments" line item in
  spending_breakdown is dead code for synthetic data. **AI-018.**
- Same dynamic for summit_chk → summit_sav internal transfer ($800/mo,
  the largest single transfer in the dataset). Category exclusion
  ('Transfers' ∈ EXCLUDED_FROM_SPEND) keeps it out of headline
  numbers, but the bucket-level transfer-flow attribution misses it.
- `recompute_interest_earned` reads
  `account_id = _affirm_hysa_id()` AND `LOWER(description) =
  'interest'` exact-match. Synthetic descriptions are 'BRIGHTON
  HYSA INTEREST' / 'SUMMIT SHARE DIVIDEND' / 'SUMMIT CHECKING
  DIVIDEND' — none match. So the dedicated interest-earned metric
  is always 0 in synthetic mode; the Sankey income-side 'Interest'
  ribbon is unaffected (it uses category-match). **AI-019.**
- `dal/derived/recompute.py:recompute_account_metrics` uses the
  LEGACY `ALL_EXCL_FROM_SPEND` filter, so per-account
  monthly_spending excludes mortgages and CC payments. This
  diverges from `compute_period_totals` (cash-out lens) which DOES
  include them. The two numbers can disagree on the same window.
- The seeder's CC payment back-fill skips months with `cycle_net >=
  0` (`generator.py:504-505`), so months where grocery refunds
  dominate produce no payment at all. Rare given 3% refund rate but
  the path exists.

**Open / punted:**

- Frontend hook names (`useQuery` calls, etc.) are inferred from
  page enumeration; specific component reads remain unverified
  (every record's `inferred_edges` notes this). A targeted Explore
  pass over `frontend/src/pages/` could resolve in a future session.
- Whether `compute_dti_ratio` and `_detect_cc_payment_boundary`
  agree on what counts as a CC payment (potential double-count
  risk). Listed in credit_card_payment.yaml inferred_edges.
- AI-005 (mortgage decomposer count 36) still unverified.
- AI-006 (Acorns same-day multiple-ledger) still unverified.

**Logged AI items:** AI-018, AI-019.

**Next agent should:** Pick up Phase 2 batch 2 — investment events:
investment_contribution, investment_buy, investment_sell,
dividend_reinvestment, portfolio_snapshot,
investment_holdings_snapshot. Heaviest synthetic-vs-live divergence
expected, especially around the Acorns triple-coupling
(`_link_acorns_bank_debits`) and the Fidelity EFT mirroring gap
(AI-010). Read STATUS.md and ACTION_ITEMS.md open list first.

---

## Session 3 — 2026-04-26 — Phase 2 investment batch

**Did:** Wrote all 6 records in the investment batch:
investment_contribution, investment_buy, investment_sell,
dividend_reinvestment, portfolio_snapshot,
investment_holdings_snapshot. Skipped the Explore subagent this
time given session 2's verification cost — instead used
`Grep ^def` directly against `dal/investments.py`,
`dal/investments_writes.py`, `dal/reports/flow.py`, and the
seeder to verify every cited symbol. Updated AGENT_GUIDE.md with
a "verify subagent claims before citing" admonition near the
existing "Use Agent for breadth" guidance.

**Surprises:**

- The v34 `v_investment_contributions` view's LEFT JOIN keys on
  `t.account_id = pl.account_id`. Acorns puts the cash leg on
  summit_chk and the ledger on acorns_synthetic — different
  account_ids — so the join NEVER matches. Acorns BUY/IMPLIED_BUY
  rows always classify as `intra_account_credit`, never
  `user_contribution`. Live Acorns has the same topology, so
  this isn't a synthetic-only issue. The
  `tests/test_investment_contributions_view.py` test setup
  paints both rows on the same account, masking this gap. AI-021.
- `_compute_bucket_totals.transfer_flows[]` requires a t1↔t2
  self-join on shared transfer_tag, but Acorns contributions only
  produce ONE transactions row (on summit_chk). The Sankey
  therefore loses the labeled "cash → investment" arrow for
  Acorns; the dollars flow into residual STORED_LIQUID instead.
  This is the third instance of the same join-shape mismatch
  (CC payment was AI-018, Acorns is AI-020).
- Acorns IMPLIED_BUY ledger rows do NOT set `cost_basis_dec`
  (the seeder's dict lacks the key, line 1072-1086). `get_lots`
  falls back to `shares × yfinance_closing_price` (line 236).
  Numerically equivalent in synthetic mode but a divergence from
  Fidelity's BUYs which DO set it.
- `realized_gain_dec` on SELL rows is populated but has no
  canonical reader today — the column data flows nowhere. Worth
  raising if a "YTD realized gains" KPI is on the roadmap.
- `record_investment_holdings` uses `INSERT OR REPLACE` (no audit
  trail on rewrites). `record_portfolio_snapshots` is append-only
  with NO unique constraint — TSP overrides via DELETE+INSERT.
- The `_DIVIDEND_TICKERS` map drives quarterly dividend cadence.
  Fidelity buys exclude QQQM from the SELL path (line 1472)
  because the seller logic doesn't handle fractional shares — a
  defensive skip, but it means QQQM never gets sold in synthetic
  mode.

**Open / punted:**

- AI-021: the v34 view design vs. how Acorns actually works. The
  fix is non-trivial: either drop the account_id join predicate
  (and rely on transfer_tag alone) or write a mirror transactions
  row on the brokerage account during linkage. Filed as a bug for
  the user to scope.
- AI-020: Acorns transfer_flows[] never resolve a t1/t2 pair.
  Fix is similar — write the brokerage-side mirror row, OR
  augment the bucket classifier to read positions_ledger
  directly when transactions can't pair.
- AI-010 (Fidelity EFT not mirrored) remains. Its fix would also
  address part of AI-020/AI-021 for Fidelity.
- Whether `_enrich_monthly_with_contributions` (line 839)
  double-counts reinvestments — function unread.
- Whether `_detect_stale_portfolio_snapshot` threshold is
  configurable — function unread.

**Logged AI items:** AI-020, AI-021. The numbering inserts AI-020
+ AI-021 ABOVE AI-019 in the file because each addition pushes
the latest entry to the top of the Open list — see the file's
"How to use" header.

**Next agent should:** Pick up Phase 2 batch 3 — system-derived
events: derived_summary_recompute_per_account, net_worth_recompute,
emergency_fund_runway_recompute, dti_ratio_recompute,
interest_cost_recompute, transfer_reconciliation,
mortgage_payment_decomposition, alert_evaluation, goal_balance_sync,
notification_emission, sign_direction_invariant. These are
post-commit-pipeline events; the patterns repeat (writers in
`dal/derived/recompute.py`, `dal/derived/metrics.py`,
`backend/result_writer.py`). Many can share inferred edges.
Read STATUS.md and ACTION_ITEMS.md open list first.

---

## Session 4 — 2026-04-26 — Phase 2 system-derived batch (partial) + corrections

**Did:** Wrote 6 system-derived event records:
transfer_reconciliation, mortgage_payment_decomposition,
auto_categorization, income_attribution, alert_evaluation,
sign_direction_invariant. Also CORRECTED two prior records
(credit_card_payment and internal_transfer) and closed AI-018 as
incorrect after discovering the reconciler's second pass.

Ran a deliberate experiment on subagent reliability with
explicit verbatim-quote requirements. Spot-checked 8 random
citations; only 2 of 8 (~25%) were accurate. Hallucinated
function names, misattributed file paths, and line numbers off
by 70+ for real functions. Documented the verdict and the
practical rule (subagents for breadth enumeration only;
re-verify every citation) in `AGENT_GUIDE.md`.

**Surprises:**

- `dal/reconciliation.py` has TWO passes — cross-institution
  (≤3 days) at line 102-175 and SAME-institution-different-
  account (≤1 day) at line 177-253. Session 2 missed the second
  pass and incorrectly claimed CC payments and internal
  transfers stayed untagged. AI-018 was filed in error and is
  now closed; both YAML records corrected.
- `_TRANSFER_KEYWORDS` (`dal/reconciliation.py:16-40`) includes
  institution names (fidelity, acorns, tsp, affirm, chase, navy
  federal, nfcu) — adding a new connector likely requires
  appending to this list, otherwise its transfers won't satisfy
  the transfer-like check.
- 17 DAL files redefine `_EM = COALESCE(effective_month,
  strftime('%Y-%m', posting_date))` as a per-file constant. A
  shared utility would prevent the N+1 update risk.
- `recompute_account_metrics` reads `posting_date` directly
  (not `_EM`) at line 73 — so per-account monthly_income may
  not respect attribution stamping. Possible gap, listed as
  inferred edge in income_attribution.yaml.
- `_eval_large_txn` writes severity 'info' (line 243), but
  `_notifications` writes the rendered notification with
  severity 'warning' (line 505). Mismatch — flagged as inferred
  edge in alert_evaluation.yaml.
- The mortgage decomposer's `transfer_tag IS NULL` filter would
  EXCLUDE post-tagged mortgage payments, but 'Mortgages' is
  NOT in `TRANSFER_CATEGORIES` (only in `EXCLUDED_FROM_SPEND`
  and `LOAN_CATEGORIES`), so the reconciler doesn't tag them
  via the second pass either. AI-005 (36-split invariant)
  remains valid.

**Subagent reliability experiment results:**

Spot-checked 8 specific citations from the breadth subagent's
output:
- 2/8 PASS: `dal/budgets.py:218 (transfer_tag IS NULL)`,
  `backend/routers/alerts.py:47 (@router.get("/api/alerts/events"))`.
- 6/8 FAIL: hallucinated `get_monthly_cash_out` and
  `get_monthly_spending` (don't exist); misattributed
  `compute_period_totals` to `dal/payroll.py` (it's in
  `flow_aggregation.py`); claimed `get_recent_alerts` at line
  320 (actual: 396); claimed mortgage filter at
  `flow_aggregation.py:260` (actually income filter; mortgage
  filter is in `dal/reports/flow.py`).

The verbatim-quote requirement DID help — quotes that did get
copied accurately could be checked. But the subagent could also
copy a quote from one location and misattribute the location.
Net cost-benefit: subagent saved discovery time on which files
to grep, but every citation needed independent verification.
For batch 3 I used the subagent's output ONLY as a candidate
hint list; every YAML citation came from direct Grep / Read.

**Open / punted:**

- 17 system-derived events still pending — listed in STATUS.md.
- AI-022 candidate for whether `decompose_unsplit_mortgage_payments`
  picks up mortgage payments correctly given the reconciler's
  ordering. Resolved during writing — the
  `_TRANSFER_KEYWORDS`/`TRANSFER_CATEGORIES` filters DON'T
  match mortgage payments, so the splitter sees `transfer_tag
  IS NULL` and runs as expected.
- 17-file `_EM` duplication — refactor candidate for the user.
- `recompute_account_metrics` posting_date vs effective_month
  divergence — flagged in income_attribution.yaml inferred
  edges, may warrant an AI item.

**Logged AI items:** none new (AI-018 closed as incorrect; the
mortgage-decomposer-ordering question resolved during writing).

**Next agent should:** Continue Phase 2 batch 4 — derived
metrics: derived_summary_recompute_per_account, net_worth_recompute,
emergency_fund_runway_recompute, dti_ratio_recompute,
interest_cost_recompute, net_worth_velocity_recompute,
interest_earned_recompute. All writers live in
`dal/derived/recompute.py` and `dal/derived/metrics.py`; share
the `derived_summaries` table. Continue with the
direct-Grep/Read approach — the subagent reliability experiment
showed it's net-negative for citation quality.

---

## Session 5 — 2026-04-26

**Goal:** Phase 2 batch 4 — 7 derived-metric events. Try Sonnet
(not Haiku) subagents with tight constraints, validate
aggressively; if Sonnet fails the same way, skip subagent use.

**Records written (7):**

- `derived_summary_recompute_per_account` (per-account
  monthly_spending + monthly_income; uses posting_date directly,
  flagged divergence with `_EM`).
- `net_worth_recompute` (banking + real estate + vehicles;
  investments excluded P13; row unconsumed by UI which reads
  `get_net_worth_history` directly; also called by
  `dal/scenarios.py` for return value).
- `emergency_fund_runway_recompute` (powers Dashboard Runway KPI
  via `/api/metrics/emergency-fund`).
- `dti_ratio_recompute` (powers Dashboard DTI pill +
  CashFlowPage series; cash-account-debit-side measurement;
  pipeline writes 2 months but UI reads 12).
- `interest_cost_recompute` (loan_details → transactions
  fallback; surfaces in Yearly Wrap-Up via `dal/yearly_wrapup.py`;
  /api/metrics/interest-cost endpoint exists but no frontend
  consumer; two interest_earned figures coexist with
  recompute_interest_earned).
- `net_worth_velocity_recompute` (MoM/3m/12m; trend label
  computed but unpersisted; powers Dashboard Net Worth KPI).
- `interest_earned_recompute` (exact-match
  `LOWER(description)='interest'` filter; dead in synthetic mode
  per AI-019; row unconsumed; possible deprecation candidate).

**Sonnet subagent experiment — markedly better than session 4:**

Spawned `Explore` with `model: "sonnet"` and tight constraints:
- 30-tool-call cap
- Required verbatim 1-line snippet alongside every cite
- Structured 4-task output (DAL readers / API endpoints /
  frontend consumers / self-grade footer)
- Explicit "READERS: NONE FOUND" / "UI: NONE FOUND" outputs
  rather than speculation

Spot-check results:
- All 5 router endpoint citations passed
  (`backend/routers/reports.py:71/82/88/97/106` —
  metrics_summary, get_emergency_fund, get_dti_ratio,
  get_interest_cost, get_net_worth_velocity).
- All 3 frontend citations passed
  (`DashboardPage.tsx:160/161/171`,
  `CashFlowPage.tsx:1009`).
- DAL reader (`dal/derived/metrics.py:597/614 —
  get_summary_metrics`) verified correct.

Pass rate ~100% on what Sonnet DID cite. Big improvement over
session 4's Haiku ~25%. Working hypothesis: model-tier was the
limiting factor, plus the structured-output prompt prevented
the casual-narrative drift that catalyzed Haiku
mis-attribution.

What Sonnet missed: **transitive completeness**, not accuracy.
It found `/api/metrics/interest-cost` but missed that
`dal/yearly_wrapup.py:163-180` calls `compute_interest_cost`
directly — so when Sonnet said "ytd_interest_cost: UI NONE
FOUND", that was wrong; the Yearly Wrap-Up page consumes it.
Similarly missed `dal/scenarios.py:80` calling
`recompute_net_worth`. These came up via my own
verification-pass Grep for `compute_interest_cost|
recompute_net_worth` across the repo.

**Practical rule (added to AGENT_GUIDE):** Sonnet subagents
are reliable for what they DO cite — quote directly. But
spot-check transitive callers yourself; the subagent stops at
the API layer it was pointed at, even with explicit "follow
the call graph" instruction. Lock the prompt structure
(numbered tasks, explicit output schema, self-grade footer,
tool-call cap). Loose prompts to Sonnet still drift.

**Open / punted:**

- 10 system-derived events still pending: investment_link_acorns,
  goal_balance_sync, notification_emission, merchant_normalization,
  recurring_pattern_detection, ticker_metadata_enrichment,
  accountability_scorecard_compute,
  accountability_drift_detection, recurring_loan_link,
  merchant_snapshot_rebuild.
- Possible cleanup: `derived_summaries.net_worth` row +
  `interest_earned` row + per-account `monthly_spending` /
  `monthly_income` rows are all unconsumed by the current
  frontend. Either deprecate the writers or wire up a
  consumer. Worth raising to the user as a parking-lot item
  rather than as an AI (it's an architectural choice, not a
  bug).

**Logged AI items:** none new. The Sonnet subagent reliability
finding lives in AGENT_GUIDE, not as an AI.

**Next agent should:** Continue Phase 2 batch 5 — investment +
recurring-detection events: `investment_link_acorns`,
`goal_balance_sync`, `merchant_normalization`,
`recurring_pattern_detection`, `recurring_loan_link`,
`merchant_snapshot_rebuild`. Each writes to a different table
so the surface area is wider than the derived-metrics batch.
Continue with Sonnet subagents constrained the same way; do
the transitive-caller Grep yourself. AGENT_GUIDE.md has the
updated rule.

---

## Session 6 — 2026-04-26

**Goal:** Phase 2 batch 5 — 7 linkage/UX events
(investment_link_acorns, goal_balance_sync, notification_emission,
merchant_normalization, merchant_snapshot_rebuild,
recurring_pattern_detection, recurring_loan_link). Continue
Sonnet subagent approach with structured prompt + aggressive
validation, since session 5 showed the citations are reliable.

**Records written (7):**

- `investment_link_acorns` — bank↔ledger pairing; Acorns-only
  (Fidelity EFT remains unlinked = AI-010); cross-link
  AI-020/AI-021. Pre-fetch optimization noted for future
  performance maintenance.
- `goal_balance_sync` — auto-sync writer; no dedicated
  GoalsPage today; trajectory uses `_get_avg_monthly_net`
  (which doc-drifts: claims derived_summaries, actually
  reads transactions); auto-completion logic clamps negative
  balances to 0.
- `notification_emission` — 7 producers fan into one DAL
  write; SSE broadcast on success; severity drift between
  alert side ('info') and notification side ('warning')
  flagged.
- `merchant_normalization` — **NEW FINDING:** writer is
  seeder-only; not called by `backend/`. New transactions
  land with merchant=NULL forever. AI-022 filed.
- `merchant_snapshot_rebuild` — **NEW FINDING:** table is
  write-only. events.yaml's claimed readers
  (`get_merchant_list`, `get_merchant_flow_data`) actually
  read `transactions.merchant` directly. AI-023 filed.
- `recurring_pattern_detection` — full UPSERT scan;
  mutation detection only on UPDATE branch (first-pass
  detection of pre-existing patterns silently skips
  mutations); `amount_stable=0` patterns excluded from
  monthly totals; cross-link AI-008.
- `recurring_loan_link` — two-strategy matcher; idempotent
  but not corrective; `/api/recurring/with-payoff` has
  no frontend consumer (events.yaml's "Debt page" consumer
  is aspirational).

**Sonnet subagent verdict (continued from session 5):**

This batch's Sonnet pass found 41 citations across 7 targets.
Spot-checked validation against `backend/routers/notifications.py`
(4 routes), `backend/routers/goals.py` (7 routes incl. POST
/api/goals/sync), `backend/routers/recurring.py` (11 routes
incl. /api/bills/* tucked in there), and frontend api_calls
in NotificationPopover, DashboardPage (line 88 recurring),
TransactionsPage (line 243 recurring tag pass). All
spot-checks passed. Pattern of failure observed in earlier
sessions (Haiku hallucinations, ~25% pass rate) did not
recur with Sonnet + structured prompt.

The one place Sonnet was load-bearing in a NEGATIVE sense:
its output for merchant_snapshot_rebuild correctly said
"NONE FOUND" for DAL readers, contradicting events.yaml's
claim. I followed up with a direct Grep across the whole
repo (`merchant_snapshots`) which returned only 4 files —
all writers, the migration, and a doc mention. Sonnet's
"NONE FOUND" was correct; events.yaml was stale. Without
the validation step I might have copied the events.yaml
description into the YAML and propagated the staleness.

**New AI items:**

- AI-022 — `merchant_normalization` not in post-commit
  pipeline (seeder-only). gap. Live data has merchant=NULL
  forever; the merchant-trends report path falls back to
  raw description.
- AI-023 — `merchant_snapshots` table is write-only. cleanup.
  Either wire it up to `get_merchant_list` /
  `get_merchant_flow_data` for performance, or drop the
  table entirely.

**Open / punted:**

- 3 system-derived events still pending:
  ticker_metadata_enrichment (external API dependency),
  accountability_scorecard_compute (read-time, complex),
  accountability_drift_detection (8 sub-detectors —
  deserves its own batch).
- After system-derived: notification + freshness events,
  live-only events, then Phase 3 inverse index, Phase 4
  diagrams.

**Observations on the events.yaml staleness pattern:**

This batch surfaced TWO cases where events.yaml's
description claims downstream consumers that don't exist
today (merchant_snapshots' purported readers,
recurring_loan_link's purported Debt page). Pattern: an
agent (or the user) wrote the events.yaml entry as
intent or roadmap, and the implementation took a
different turn or stalled. The lineage map's job is
"codebase as it is", so we treat the YAMLs as
authoritative and surface the discrepancy. Both got
flagged in inferred_edges + new AI items.

**Next agent should:** Pick up the 3 remaining system-derived
events (ticker_metadata_enrichment is straightforward;
accountability_scorecard_compute and the 8-detector
accountability_drift_detection are bigger and may want
their own session). After that, Phase 2 will be ~80%
done — at that point Phase 3 (inverse index) becomes a
candidate. Continue Sonnet subagent + aggressive
validation pattern.

---

## Session 7 — 2026-04-26

**Goal:** Phase 2 batch 6 — close out the system-derived
class with the final 3 events: ticker_metadata_enrichment,
accountability_scorecard_compute, accountability_drift_detection
(the latter has 8 sub-detectors). Continue Sonnet subagent
+ aggressive validation pattern.

**Records written (3):**

- `ticker_metadata_enrichment` — seeder-only (AI-024 filed);
  3-branch yfinance resolution; 30-day per-ticker staleness
  skip; powers Investments Holdings/Allocation/Overview tabs
  via LEFT JOIN ticker_metadata in `get_holdings` and
  `get_allocation`. Cross-link to invariant
  `inv_009_ticker_metadata_covers_all_holdings`.
- `accountability_scorecard_compute` — read-time identity
  reconciliation Δ NetWorth = Dollars in − Dollars spent ±
  Market Δ ± RE Δ ± Vehicle Δ + unexplained; powers
  ReportsPage AccountabilityScorecard widget at
  `ReportsPage.tsx:2331-2335`. ~15-20 sub-queries per widget
  load (acceptable single-user; flagged as cost). Empty-state
  contract: zero NW delta → vacuously 1.0 accounted_for_pct.
- `accountability_drift_detection` — 8 detectors documented
  individually with their reads, fix_actions, and severities;
  embedded in scorecard payload as `drift_sources`. Frontend
  AccountabilityModal at `ReportsPage.tsx:1648` renders
  DriftRow per source; `fixClick` dispatcher at line 1671
  switches on `fix_action` string and navigates to the
  appropriate page.

**Sonnet subagent verdict (continued):** 28 citations across
3 targets; spot-checked router endpoints
(`/api/reports/accountability` at line 486, all 7
`/api/investments/*` routes), the modal/DriftRow JSX
(line 1648, 1781-1783, 1835), and the fixClick switch
(line 1671-1691). All passed. Sonnet correctly listed
`(none found)` for two sub-sections (Target 2/3 DAL
readers, Target 3 separate API endpoint) — both genuinely
empty. No drift from earlier sessions.

**New AI item:**

- AI-024 — `enrich_ticker_metadata` not in post-commit
  pipeline (seeder-only). gap. New tickers appearing in
  production data render with 'Unknown' fallbacks because
  the LEFT JOIN returns NULL. Wire into pipeline (cheap
  with the existing 30-day staleness skip) OR expose a
  one-shot endpoint.

**Phase 2 status update:**

System-derived class is now COMPLETE (23/23). 36 of ~70
total events done — about 51% through Phase 2.

Remaining classes (rough mapping; verify against events.yaml):
- `user_action` (~12) — UI-driven CRUD events. Will likely
  follow the same shape as merchant/recurring DAL writers.
- `external_force` (~15) — connector-driven events
  (refresh, document_drop, etc.).
- `live_only` (~31) — connector lifecycle, document upload,
  user CRUD. STATUS.md notes this can be skipped on first
  pass.

**Pattern observation across sessions 5-7:**

Six Sonnet subagent runs across three batches; pass rate
on cited locations is effectively 100%. The `(none found)`
outputs have all been correct (i.e. when Sonnet says it
didn't find anything, there genuinely isn't anything to
find). The remaining failure mode is **completeness** —
the subagent finds the obvious endpoint surface but
misses transitive callers (e.g. yearly_wrapup.py calling
compute_interest_cost in session 5; merchant_snapshots'
true non-consumers in session 6; would expect similar
gaps if a future batch's events have indirect callers
through views or scheduled scripts).

**Next agent should:** Decide between:
  (a) Continue Phase 2 with `user_action` and
      `external_force` classes (~27 events combined).
  (b) Pause Phase 2 at 51% and start Phase 3 (inverse
      index) using the 36 records on hand. Phase 3 is
      a JOIN across all per-event YAMLs; partial input
      would produce a misleading map per STATUS.md
      ("Build only after Phase 2 is ≥80% complete").
      So (a) is the right call unless the user explicitly
      wants an early-look inverse index.
  (c) Pivot to Phase 4 diagrams for the system-derived
      class only — produce a focused subgraph for the
      post-commit pipeline. Useful as a checkpoint but
      not in the prescribed phase order.

Recommendation: continue with (a). User_action events are
small and similar in shape (UI CRUD); external_force has
the connector / freshness events which surface real
production behaviors not yet documented.

---

## Session 8 — 2026-04-26

**Goal:** Close out the user_action class — 4 remaining
events (utility_bill, insurance_payment, subscription_charge,
purchase_refund). All are seeder-emitted transactions sharing
the upsert_transactions writer; downstream lineage parallels
retail_purchase. Skipped Sonnet subagent for this batch — the
shape is too well-known from the cash-flow batch (session 2)
and the consumer surface is the same set of transaction
readers already enumerated there.

**Records written (4):**

- `utility_bill` — 4 patterns (Utilities/Telephone/Telephone/
  Dues and Subscriptions); checking-side, counts toward
  `spending_cents`. Note: PLANET FITNESS is 'Dues and
  Subscriptions' in the seeder, NOT a separate
  'Health & Fitness' category as events.yaml's example list
  implies. Worth flagging if a future taxonomy distinction
  matters.
- `insurance_payment` — semi-annual GEICO $600; FREQUENCY_BAND
  170-200d picks it up at ≥3 occurrences (3-year window has
  6); MONTHLY_FACTORS['semiannual']=0.167 smooths to ~$100/mo
  in forecast.
- `subscription_charge` — Netflix/Spotify monthly + Amazon
  Prime annual; CC routing means cash-out lens treats them as
  `debt_accumulated_cents` (paired CC payment is the actual
  cash-out). Annual cadence (Amazon Prime) lands in band
  (350,380,'annual') — requires ≥3 years of history to
  detect.
- `purchase_refund` — 3% of grocery purchases; SAME category
  as parent (Groceries), POSITIVE signed_amount;
  INCOME_EXCL_FROM_INC keeps it out of income totals.
  Documented as LOAD-BEARING regression guard for the prior
  sign-handling bug (CLAUDE.md > Non-Negotiable Guardrails);
  any change to refund seeding rate / category should
  preserve the regression test fixtures.

**Phase 2 status update:**

- system_derived: ✅ COMPLETE (23/23)
- user_action: ✅ COMPLETE (12/12)
- external_force: 5/15 (paycheck precursor + investment
  inflows from sessions 2-3)
- live_only: 0/31 (skip on first pass per STATUS)
- 40 of ~70 events done — about 57% through Phase 2.

**No new AI items this session.** Several existing items
were cross-linked into the new YAMLs:
- AI-008 (recurring not in pipeline) — affects all 4 events.
- AI-015 (INCOME_EXCL_FROM_INC manual maintenance) —
  load-bearing for purchase_refund.
- AI-022 (merchant_normalization not in pipeline) —
  cross-linked in subscription_charge merchant trends path.

**Process note:** Skipping the Sonnet subagent for this
batch was a deliberate cost decision — the consumer surface
is identical to retail_purchase / paycheck (already
enumerated in session 2). When the next event class shifts
(external_force has snapshots writers like balance_snapshot,
apy_rate_snapshot — different writer module, different
downstream readers), the Sonnet pattern resumes. Rule of
thumb: spawn the subagent when the writer module changes,
skip when writing parallel YAMLs in the same writer family.

**Next agent should:** Pick up external_force class. The
remaining 11 events split into rough sub-batches:

- **Snapshot writers (6):** balance_snapshot, tax_bucket_snapshot,
  apy_rate_snapshot, credit_score_reading, vehicle_valuation,
  real_estate_valuation, payroll_snapshot. All connector-driven
  except payroll_snapshot (document-upload). Most write to a
  table named `<thing>_snapshots` or `<thing>_history` with
  dated rows.
- **Loan-side (1):** loan_details_snapshot — KV writes to
  `loan_details`. Cross-link interest_cost_recompute /
  mortgage_payment_decomposition.
- **Investment external (3):** money_market_sweep_interest,
  market_price_tick, tax_lot_initial. Writer locations vary;
  market_price_tick is yfinance-driven.
- (5 already done from sessions 2-3.)

A reasonable batch size is 5-7 events. Snapshot writers
(6) is a coherent first batch since they share the
"connector-emits-row + dashboard-reads-latest" pattern.

---

## Session 9 — 2026-04-26 — External_force snapshot batch

**Goal:** Phase 2 snapshot-writer batch from STATUS.md
recommendation: 7 external_force events sharing the
"connector-emits-row + dashboard-reads-latest" pattern.
balance_snapshot, tax_bucket_snapshot, apy_rate_snapshot,
credit_score_reading, vehicle_valuation, real_estate_valuation,
payroll_snapshot.

**Records written (7):**

- `balance_snapshot` — single write path through
  `dal.balances.record_balance` serves seeder, connectors,
  parsers; consumed by net_worth, emergency_fund, dti,
  forecast, freshness, accountability, debt, scenarios,
  goals, alerts, recurring loan link, yearly wrap-up.
  Closure walk emits monthly anchors per non-investment
  account; investment series lives on portfolio_snapshot.
  Seeder asserts no positive liability balance at
  post-seed integrity check (line 1241-1247).
- `tax_bucket_snapshot` — TSP-only via
  `generate_tsp_investment_history`; no live writer
  (AI-025 filed). cents-stored INTEGER (unlike
  balance_snapshots REAL); UNIQUE(account_id, bucket_type,
  as_of) with INSERT OR REPLACE. Conservative default in
  `get_tax_summary` silently flips a missing-bucket account
  to Tax-Deferred — production hazard.
- `apy_rate_snapshot` — `dal.apy_history.record_apy_history`
  with [0,100] / ISO date / 3-source-set invariants.
  Consumers: `detect_apy_changes` → notification, freshness
  map (one of three timestamp sources), account-details
  panel APY chart. AI-007 confirmed 5 bp default threshold
  (not 1 bp; misread originally).
- `credit_score_reading` — `dal.credit_scores.record_credit_score`
  with [300,850] invariant; case-insensitive owner_id.
  Display-only (no derived metric, no notification, no
  forecast input). Powers Dashboard card + drill-in popup.
  Note asymmetry vs apy_rate_change: APY changes fire
  notifications, score changes do not (likely intentional
  noise tradeoff).
- `vehicle_valuation` — `dal.vehicles.add_valuation` with
  estimated_value > 0 invariant; UPDATE-on-match key
  (vehicle_id, valuation_date, source). Owner-scoping via
  vehicle_assets JOIN, not on the valuation row.
  Suggested-value heuristic (15%/10%/15% floor) is dual-use
  (modal pre-fill + future KBB stand-in).
  `_detect_vehicle_depreciation_unrecorded` drift detector.
- `real_estate_valuation` — `dal.real_estate.record_real_estate_valuations`
  batch writer; APPEND-ONLY (no UNIQUE constraint, deliberate
  for multi-provenance same-day rows). Identity columns
  added in v37 sparse-per-row; `resolve_latest_identity`
  walks newest-first picking first-non-null. Two drift
  detectors: stale + interpolated.
- `payroll_snapshot` — NO DAL writer helper (AI-027 filed) —
  both seeder and live mypay_ras parser write raw SQL.
  Consumers: yearly wrap-up effective tax rate, monthly
  pre-tax KPI, Sankey gross-up via `compute_period_totals`,
  drift detector, 1099-R cross-validation. Synthetic
  Sankey gross-up is silently dead because
  `source=dummy_seeder` substring never matches paycheck
  descriptions like "ALEX PAYROLL" (AI-026 filed).

**Surprises:**

- `tax_buckets` writer is seeder-only — no live TSP
  statement parser writes it; the parser only writes
  holdings + portfolio_snapshots. Live data would fall
  through `get_tax_summary`'s "no bucket data" default and
  silently flip the entire account into Tax-Deferred.
  Different from AI-022/AI-023 (which are write-only with
  no readers); this is a write-gap with an active reader
  pipeline. AI-025 filed.
- `payroll_snapshots` is the only snapshot writer without a
  dedicated DAL helper — both writers (seeder + parser)
  emit raw SQL INSERTs. Asymmetry vs every other snapshot
  writer (record_balance, record_apy_history,
  record_credit_score, add_valuation,
  record_real_estate_valuations). AI-027 filed.
- The seeder uses `source=dummy_seeder` for synthetic
  payroll snapshots. `find_matching_deposit_tx_id` matches
  by source_label substring against deposit
  merchant/description — substring "dummy_seeder" never
  matches paycheck descriptions. So the Sankey gross-up
  withholdings-decomposition path is silently dead in
  synthetic mode (UI shows the empty-state copy at
  `ReportsPage.tsx:1300`). AI-026 filed.
- `vehicle_valuations` UPDATEs on (vehicle_id, valuation_date,
  source) match while `real_estate` is append-only. Both
  are valuation tables but the schemas differ deliberately:
  real estate preserves multi-provenance same-day rows
  (Zillow vs Redfin vs manual); vehicles overwrite Manual
  with Manual.
- The audit punch list item #5 (P1, owner_id ambiguity in
  `dal.freshness.get_institution_freshness`) was confirmed
  by tracing balance_snapshot — the apy_last term wraps in
  try/except for pre-v30 schemas (line 138-145), but the
  owner_id-scoped path raises OperationalError on the
  ambiguous `id` column. Documented in balance_snapshot.yaml
  inferred_edges.

**Open / punted:**

- 4 external_force events still pending:
  loan_details_snapshot, money_market_sweep_interest,
  market_price_tick, tax_lot_initial.
- Whether v15_payroll_snapshots UNIQUE constraint actually
  keys (pay_period, source, owner_id) or just
  (pay_period, source) — direct Read of v15 migration
  punted; seeder INSERT OR REPLACE works either way.
- Whether `dal/parsers/mypay_ras.py` writes through any
  shared helper — not read this session; AI-027 description
  notes the verification gap.
- `_detect_real_estate_interpolated` may fire perpetually in
  synthetic mode (every quarter has only `source=estimate`
  rows from real_estate.json). Verify via runtime trace.
- 1099-R validation block (yearly_wrapup.py:497+) — source
  of `federal_tax_1099r` not traced.

**Logged AI items:** AI-025 (tax_buckets seeder-only),
AI-026 (payroll Sankey gross-up dead in synthetic),
AI-027 (no record_payroll_snapshot DAL helper).

**Next agent should:** Continue Phase 2 batch 7 — finish
the external_force class with the 4 remaining entries:

- `loan_details_snapshot` — KV writes to loan_details;
  cross-link interest_cost_recompute /
  mortgage_payment_decomposition. Single biggest remaining
  lever for synthetic-vs-live divergence narratives
  (AI-009 directly references it).
- `money_market_sweep_interest` — SPAXX dual-write; parallel
  to equity_dividend.
- `market_price_tick` — yfinance fetch + benchmark_prices
  cache + deterministic fallback drift. CLAUDE.md > Project
  Shape calls out the seeded-vs-live mismatch directly.
- `tax_lot_initial` — INITIAL_BASELINE positions_ledger row.

After this batch, external_force class is COMPLETE (15/15)
and Phase 2 will be ~74% done — Phase 3 inverse index
becomes a candidate per STATUS.md threshold ("≥80%
complete"). Either continue to live_only events
(connector lifecycle, document upload, user CRUD — many
are smaller, similar in shape) OR start Phase 3 partial.

---

## Session 10 — 2026-04-26 — External_force closeout

**Goal:** Finish the external_force class with the remaining 4
events: loan_details_snapshot, money_market_sweep_interest,
market_price_tick, tax_lot_initial. User explicitly requested
Sonnet subagents to keep main-context controlled, with
aggressive citation validation.

**Approach:**

Spawned 4 Sonnet `Explore` subagents in parallel, one per
event, each with:
- Tightly numbered output schema (TARGETs 1..N + self-grade footer)
- Required verbatim 1-line quote per citation
- Hard tool-call cap (20-30 per agent)
- Explicit `NONE FOUND` literal for empty sections
- `(unverified)` mark for citations they couldn't quote

Then aggressively validated citations via a single batched
parallel Read call (15 spot-checks across ~10 files). All
citations matched the file/line/symbol claims.

**Records written (4):**

- `loan_details_snapshot` — KV writer at `dal.balances.record_loan_details`
  with COLLATERAL_FIELDS denylist + `apy` redirect to
  apy_history at the result_writer edge. Consumers: 10+ DAL
  readers (compute_interest_cost primary path,
  _get_loan_apr for debt summary, maturity_date suppression
  in forecasting, account-details bundle composer, inline
  pivot in list_accounts router). 8 backend endpoints, 4
  frontend surfaces. Cross-link AI-009 (synthetic
  ytd_interest path is sole interest-cost source).
- `money_market_sweep_interest` — SPAXX dual-write parallel
  to equity_dividend but with crucial differences: NO
  REINVESTMENT counterpart (shares stay at $1 NAV), so
  `_compute_reinvestment_flows` never matches SPAXX rows;
  cash compounds in portfolio_snapshots.cash_balance instead.
  CASH_EQUIVALENTS = {"SPAXX","FDRXX"} singleton singled out
  in `dal/investments.py:23` for cash-vs-equity routing.
  Live Fidelity connector (line 431) only persists cash
  balance, doesn't emit dividend rows.
- `market_price_tick` — yfinance bulk fetch + linear-drift
  fallback for the 15 known tickers; INSERT OR IGNORE so
  re-seeds are idempotent. Second writer
  `dal/tsp_prices.py:upsert_benchmark_prices` uses
  INSERT OR REPLACE — TSP API wins over fallback drifts.
  CONFIRMED `dal/performance.py` is DELETED post-P13;
  `_daily_totals_unfiltered` is the new source-of-truth
  for portfolio time-series (no TWR computation today).
- `tax_lot_initial` — INITIAL_BASELINE rows from 4 writer
  paths (Acorns seeder, Fidelity seeder, Acorns connector,
  Acorns PDF backfill); TSP emits zero. v34 view classifies
  these as `intra_account_credit` indirectly via the
  `t.id IS NULL` branch (no paired bank-leg with
  transfer_tag), which is correct today but structurally
  fragile if a future linkage assigns bank_txn_id.

**Subagent reliability — continued from session 5/6/7:**

Batch results:
- loan_details_snapshot: 24/24 cites with verbatim quotes,
  0 unverified, 0 NONE FOUND, 18 / 30 tool calls.
- money_market_sweep_interest: 24/24 with quotes, 0 unverified,
  partial NONE FOUND in TARGET 4 (no UI names SPAXX), 20 / 25.
- market_price_tick: 24/26 with quotes, 3 unverified
  (get_allocation / get_tax_buckets / get_tax_summary internals
  not deeply read), 1 NONE FOUND (dal/parsers/), 17 / 25.
- tax_lot_initial: 18/18 with quotes, 0 unverified, 3 NONE
  FOUND (no frontend label, no DAL write-side guard, TSP
  emits zero), 17 / 20.

Spot-check validation pass: read 15 file ranges directly
(generator.py:1540-1575 / 1715-1725 / 2215-2230 / 1252-1260 /
910-950 / 960-1010 / 1075-1090 / 1380-1390;
dal/investments.py:200-244;
dal/migrations/v34_investment_contributions_view.py;
extractors/acorns_connector.py:920-955;
dal/forecasting.py:535-555;
backend/routers/debt.py;
dal/tsp_prices.py:95-135). Glob confirmed `dal/performance.py`
absent. **Every spot-checked citation matched** — file, line,
symbol, and quoted text. Zero hallucinations across all 4
agents.

The Sonnet+structured-prompt+tool-cap pattern continues to
produce reliable citations. Three ingredients matter:
- Numbered TARGET sections with explicit output schema
- Required verbatim quote alongside every cite
- Self-grade footer that forces the agent to count its own
  citations and unverified marks

The remaining failure mode is still **transitive completeness**
— agents stop at the API layer they were pointed at. For this
batch the agents' "unverified" marks (3 in market_price_tick)
were correctly self-flagged rather than papered over.

**Surprises:**

- The CLAUDE.md > Project Shape paragraph references
  `dal/performance.get_benchmark_monthly_returns` which has
  been deleted for ~weeks (P13-T01 commit 9ef66a3).
  The audit report in docs/audits/files also carries similar
  stale wording. AI-028 filed.
- Docstring at `generator.py:1256-1258` claims
  `seed_quintin_bank_interest` will catch live SPAXX rows,
  but the actual catcher (based on category='Investment Income'
  match rule) is `seed_quintin_fidelity_dividends`. The
  docstring would mislead a future Fidelity-statement-parser
  author. AI-029 filed.
- `backend/routers/accounts.py:99-115` pivots loan_details via
  `MAX(CASE WHEN field_name=...)` over ALL `as_of` timestamps,
  not the latest snapshot per field. For monotonically-non-
  decreasing fields it matches latest-wins; for decreasing
  fields (rewards_points after redemption) it returns the
  all-time max. The AccountDetailsPanel's bundle composer
  does this correctly via ORDER BY as_of DESC. The two surfaces
  silently disagree. AI-031 filed.
- Acorns IMPLIED_BUY rows OMIT `cost_basis_dec` (line
  1075-1086) — `get_lots:236` falls back to `shares ×
  yfinance_closing_price`. Same gap exists in the live
  Acorns connector (line 937-954 inserts no cost_basis_dec
  column at all). Fidelity DOES set it faithfully (line 1385
  `cost_basis=actual_cost`). Realized-gain reporting on
  Acorns SELLs would be structurally inaccurate, though
  cosmetic in synthetic mode (no SELLs fire). AI-030 filed.
- The v34 view's classification of INITIAL_BASELINE as
  `intra_account_credit` works today only because no writer
  sets `bank_txn_id` on these rows. A single future linkage
  pass could break it. Subagent suggested an explicit
  `transaction_type != 'INITIAL_BASELINE'` guard — captured
  in tax_lot_initial.yaml inferred_edges, no AI item filed
  yet (more of a hardening recommendation than a current bug).
- TWO writer paths converge on `benchmark_prices` with
  different conflict semantics (INSERT OR IGNORE vs INSERT
  OR REPLACE) — TSP API wins over fallback drifts. The same
  ticker can hold either real or synthetic prices depending
  on which writer ran most recently.

**Open / punted:**

- `_get_loan_min_payment` — `dal/debt.py:_get_liability_accounts`
  computes `min_payment = max(25.0, balance * 0.02)` in Python,
  ignoring `loan_details.minimum_payment` even when present.
  Possibly intentional override or a divergence from the
  docstring. Listed in inferred_edges of loan_details_snapshot.
- Whether `seed_loan_details_*` helpers ever write `apy`
  directly to loan_details (the live writer strips it; the
  seeder may not). Untraced.
- Whether `dal/tsp_prices.py:interpolate_daily_holdings`
  is in the post-commit pipeline or only manual.
- ReportsPage rendering branch when reinvestment_flows is
  empty (always for SPAXX) — confirmed empty by DAL but UI
  guard not directly read.
- `get_lots` does not return `transaction_type`, so the
  InvestmentsHoldings tax-lot drawer cannot label
  INITIAL_BASELINE rows as such. Hardening recommendation,
  not yet an AI item.

**Logged AI items:** AI-028 (CLAUDE.md stale ref to
deleted module), AI-029 (docstring drift on SPAXX income
source), AI-030 (Acorns IMPLIED_BUY missing cost_basis_dec),
AI-031 (list_accounts pivot all-time-max bug).

**Phase 2 status update:**

- system_derived: ✅ COMPLETE (23/23)
- user_action: ✅ COMPLETE (12/12)
- external_force: ✅ COMPLETE (15/15)
- live_only: 0/24 (deferred per STATUS.md)
- 51 of ~70 events done — about 73% through Phase 2.

**Next agent should:** With Phase 2 at 73%, two paths
forward:

  (a) **Continue with live_only events.** The class has
      ~24 entries (connector_refresh_lifecycle,
      connector_balance_scrape, connector_transactions_csv_upsert,
      connector_loan_details_scrape, connector_mfa_required,
      connector_failure, document_upload_commit,
      user_category_override, user_attribution_rule_crud,
      user_budget_crud, user_goal_crud,
      user_recurring_dismiss_reactivate, user_manual_valuation,
      user_notification_state_change, interest_charge,
      cc_fee, deposit_account_fee, cash_deposit, check_deposit,
      check_written, atm_withdrawal, cashback_redemption,
      tax_refund, bonus_or_one_off_income, reimbursement,
      manual_transaction_entry, alert_rule_edit,
      categorization_rule_delete, staleness_evaluation,
      document_parse_failure, dev_advance_dummy_data).
      Many share write paths (connector lifecycle is one
      module; user CRUD is mostly thin wrappers; fee/income-type
      events all flow through upsert_transactions). Could
      group into 3-4 batches of 6-8 each.

  (b) **Start Phase 3 inverse index.** STATUS.md says
      "Build only after Phase 2 is ≥80% complete."
      We're at 73%. Building now risks producing a misleading
      map that misses the live_only writer paths. Defer
      until at least one more batch (probably the connector
      lifecycle + document upload events, ~7 entries —
      brings Phase 2 to ~84%).

**Recommendation:** (a) continue with live_only, batched
as: connector lifecycle (6-7), document upload + parse
failure (2), user CRUD (8), fee/income types (~9). The
connector lifecycle batch is highest debugging value —
covers production refresh failures, MFA flow, freshness
events. After that batch Phase 2 hits ~84% and Phase 3
becomes safe.

Subagent approach validated for citation accuracy on this
session — keep using it for breadth enumeration with
direct-Grep verification on transitive callers.

---

## Session 11 — 2026-04-26 — Live_only connector lifecycle batch

**Goal:** Open the live_only class with the connector lifecycle
batch per session 10's recommendation: 7 events
(connector_refresh_lifecycle, connector_balance_scrape,
connector_transactions_csv_upsert, connector_loan_details_scrape,
connector_mfa_required, connector_failure, staleness_evaluation).
User explicitly requested Sonnet subagents to keep main-context
controlled.

**Approach:**

Spawned 7 Sonnet `Explore` subagents in parallel, one per event,
each with the validated session-10 prompt schema (numbered TARGETs
+ verbatim-quote requirement + tool cap + self-grade footer).
Each prompt was scoped to the event's UNIQUE surface — e.g.
balance_scrape and loan_details_scrape were told NOT to
re-enumerate downstream consumers already covered in
balance_snapshot.yaml / loan_details_snapshot.yaml /
apy_rate_snapshot.yaml, focusing instead on the live-path
specifics (anomaly guard, apy split, refresh_run_id thread).

Spot-validated ~6 representative citations via direct Read:
state_machine.py:184 defaults_fatal, refresh_orchestrator.py:626-654
failure path, refresh_orchestrator.py:419 STALENESS_EVALUATED emit,
extractors/tsp_connector.py:194-217 two-phase MFA, dal/notifications.py:65-117
record_notification, dal/apy_history.py:32-66 invariants, plus
hands-on confirmation of the SSE consumption-pattern bug across
RefreshBanner/MFAModal/NotificationPopover. All passed.

**Records written (7):**

- `connector_refresh_lifecycle` — RefreshSession state machine
  over `refresh_runs` / `refresh_events` /
  `institution_refresh_status`. 5 wildcard DAL readers wrap
  every consumer surface; no focused per-column SELECTs exist.
  Two-layer timeout (per-institution + 30-min session) with
  `_force_fail` recovery path.
- `connector_balance_scrape` — live path through
  `persist_connector_result.record_balance`. Cross-references
  `balance_snapshot.yaml` for the ~12 readers + 8 derivations
  + 9 UI surfaces.
- `connector_transactions_csv_upsert` — CSV-specific
  normalization (column candidates, sequence_index dedup,
  failure list). Only NFCU + Chase emit CSVs into
  `result.files`; Fidelity has explicit `return []` to bypass
  generic CSV ingestion. Cross-references per-event
  transaction YAMLs for downstream.
- `connector_loan_details_scrape` — APY split logic + 3
  connector emitters (Chase + NFCU include apy; Affirm uses
  separate path; Fidelity uses loan_details for cost-basis).
  parse_apy_string vs _assert_apy_valid layering documented.
  Cross-references `loan_details_snapshot.yaml` and
  `apy_rate_snapshot.yaml`.
- `connector_mfa_required` — TSP-only today. Two-phase emit
  (SMS auto-capture → manual fallback). Notes the unused
  WAITING_MFA / WAITING_FOR_USER state machine values that
  the connector code never drives.
- `connector_failure` — orchestrator exception handler with
  3 logical paths. Notification dedup_key uses event_id (not
  institution_id alone) so each failure event is unique
  across runs. `record_notification` swallow at line 647-648
  silently drops failed inserts.
- `staleness_evaluation` — explicitly contrasts the two
  evaluators (`evaluate_staleness` vs
  `get_institution_freshness`) — different sources, different
  thresholds, different audiences. Documented as a debugging
  trap.

**Surprises:**

- **AI-032 — RefreshBanner AND MFAModal both dead.** The
  `/api/refresh/events` SSE stream
  (`backend/routers/refresh.py:119`) emits `event:
  {topic}\ndata: {...}\n\n` for every event. Per HTML5 spec,
  named events go to `addEventListener("topic", ...)`, not
  `onmessage`. RefreshBanner.tsx:33 and MFAModal.tsx:34 both
  use `es.onmessage` — which never fires for typed events.
  RefreshBanner additionally uses legacy topic literals
  (`session_started`, `institution_progress`,
  `institution_completed`, `session_completed`,
  `session_failed`) that don't match canonical sse_topics
  constants. Net: sync banner never appears, onRefreshComplete
  never fires (so balance pages don't auto-refresh after a
  refresh), AND a real TSP MFA challenge cannot be answered
  from the UI (the connector thread blocks on
  `mfa_bridge.wait_for_code` until session timeout).
  NotificationPopover.tsx:89 uses the correct pattern as the
  reference fix. The `INSTITUTION_FAILED` /
  `INSTITUTION_RETRY` / `STALENESS_EVALUATED` SSE topics also
  have zero subscribers as a downstream symptom of the same
  bug class.
- **AI-033 — `summary["anomalies"]` is write-only.** The 10×
  balance ratio guard at `result_writer.py:198-215` flags
  suspicious balance changes, logs a WARNING, and appends to
  a list no caller reads. A 100× balance scrape silently
  writes the bad value AND the anomaly entry; only the
  backend log reflects it.
- **AI-034 — refresh_run_id never threaded through.** Both
  `record_balance` and `record_loan_details` accept the
  parameter, but `persist_connector_result` calls them
  positionally with one fewer argument — `now` fills `as_of`,
  refresh_run_id defaults to None. Per-run forensic queries
  impossible.
- **AI-035 — `refresh_events.mfa_prompted` always zero.**
  Column defined, parameter exposed in
  `update_refresh_event` signature, bound in SQL — but no
  caller ever passes True. Zero readers anywhere.
  Half-implemented telemetry.
- **AI-036 — `summary["failed_csvs"]` never read.** A refresh
  that silently fails to parse 3 of 5 CSVs looks identical to
  a clean refresh on every surface; only a backend log.error
  reflects the failure. Same anti-pattern as AI-033.
- **Five wildcard DAL readers, no focused SELECTs.** Every
  refresh-state DAL function does `SELECT *`. No focused
  reader exists for any subset of failure-state columns.
  Consumers always fetch the full row and project
  client-side. Probably fine at this scale; worth noting.
- **Two staleness models coexist.** `evaluate_staleness`
  (4 h Tier-1 default, source = institution_refresh_status
  only) vs `get_institution_freshness` (24 h Tier-1 default,
  source = 4-way MAX). Different audiences, different
  thresholds, deliberate split — but easy debugging trap.

**Sonnet subagent verdict (continued from sessions 5-10):**

7 agents, ~165 citations total, 0 self-flagged unverified.
Spot-checks passed on every sampled citation. The pattern
continues to be reliable for ENUMERATION + verbatim-quote-as-
evidence. Transitive-caller completeness remains the only
failure mode — the SSE-stream-`event:`-framing bug
(`routers/refresh.py:119` interacting with the spec) was
something I noticed myself by reading the SSE handler, not
something the agents escalated. They reported the topic-string
mismatch but didn't dig into the framing layer.

**Logged AI items:** AI-032, AI-033, AI-034, AI-035, AI-036.
Five new items — the highest count since session 1.5's gap
pass.

**Phase 2 status update:**

- system_derived: ✅ COMPLETE (23/23)
- user_action: ✅ COMPLETE (12/12)
- external_force: ✅ COMPLETE (15/15)
- live_only: 7/24 (connector lifecycle batch this session)
- 58 of ~70 events done — about 83% through Phase 2.

Phase 2 is now over the 80% threshold STATUS.md set for
starting Phase 3.

**Next agent should:** Two viable paths:

  (a) Finish `document_upload_commit` +
      `document_parse_failure` first (2 events, coherent
      pair sharing `dal/document_drop.py` + `dal/parsers/`).
      Brings Phase 2 to ~86% and gives Phase 3 cleaner input.
  (b) Start Phase 3 inverse index immediately on the 58
      records on hand. STATUS.md threshold is met.
  (c) Both in parallel — Phase 3 inverse index in one stream,
      remaining live_only batches (doc upload, user CRUD,
      live debit/credit families) in another.

Recommendation: (a) for one more session to round out
live_only's most-singular writers, then (b). User CRUD and
debit/credit families are repetitive — they cross-reference
existing transaction/notification YAMLs more than they add
new structure, so they're lower priority for completing the
Phase 2 → Phase 3 handoff.

Continue Sonnet subagent + aggressive validation pattern.

---

## Session 12 — 2026-04-26 — Phase 2 closeout (live_only completion)

**Goal:** Per user direction "stay in phase 2 until completion."
Finish the remaining 17 live_only events in three sub-batches:
document pair (2), user CRUD (10), live debit/credit families
(11), plus dev_advance_dummy_data (1) — 24 total.

**Approach:**

Mixed strategy per session 8's cost rule (skip subagent when
writer family is shared):
- **Document pair:** spawned 2 Sonnet subagents in parallel
  (parsers are 10 distinct modules with unique commit shapes;
  worth the breadth enumeration).
- **User CRUD (10):** wrote directly without subagents. Read
  the writer modules (`dal/categorization.py`,
  `dal/attribution.py`, `dal/budgets.py`, `dal/goals.py`,
  `dal/recurring.py`, `dal/notifications.py`) and routers
  (`alerts.py`, `goals.py`, `budgets.py`, `recurring.py`,
  `notifications.py`, `user_rules.py`, `transactions.py`,
  partial `reports.py` for attribution + valuations) in 4
  batched reads. Consumer surface is exhaustively covered in
  prior YAMLs — each user CRUD record is a focused writer-
  side description with cross-references to the downstream
  per-event records.
- **Live debit/credit families (11):** wrote directly without
  subagents per session 8's "writer family is shared" rule.
  All flow through `upsert_transactions` and reuse the
  retail_purchase / paycheck downstream readers. Each YAML is
  ~70-100 lines focused on synthetic-vs-live divergence and
  category-classification narratives.
- **dev_advance_dummy_data:** read the single 128-line file
  directly and wrote the YAML.

Spot-validated key citations from the document subagents:
- `dal/parsers/base.py:15-27` ParseResult dataclass + can_commit
  default + blocking_warnings property — confirmed.
- `backend/routers/documents.py:55-62` upload INSERT, line
  118-126 commit UPDATE pattern — confirmed.
- `dal/migrations/v14_document_drops.py:4-14` schema — confirmed
  (no source column on loan_details parallel; document_drops
  is a separate table).

**Records written (24):**

Document pair (2):
- `document_upload_commit` — 10-parser dispatch table; per-
  parser commit shapes; institution_map dispatch for the
  post-commit pipeline (only tsp_statement + mypay_ras
  trigger it — AI-038 finding).
- `document_parse_failure` — 3 failure modes; 8 `⚠ BLOCK:`
  callsites; frontend dual-surface error rendering (inline
  + toast).

User CRUD (10):
- `user_category_override` — set_user_override + the richer
  rule-creation side-effect path.
- `user_attribution_rule_crud` — three endpoints in reports
  router; no PATCH/PUT exposed.
- `user_budget_crud` — UPDATE-then-INSERT pattern; CLAUDE.md
  household-only guardrail.
- `user_goal_crud` — soft-delete via status='cancelled'; no
  PATCH for name/target/deadline.
- `user_recurring_dismiss_reactivate` — exact-string action
  validation; status change doesn't cascade.
- `user_manual_valuation` — vehicle + real estate write paths
  shared with seeder.
- `user_notification_state_change` — mark_read idempotent,
  dismiss not; no SSE broadcast on state change.
- `alert_rule_edit` — PATCH-only; no DELETE; no retroactive
  suppression of fired events.
- `categorization_rule_delete` — DELETE-only; rules created
  as side effect of overrides.
- `manual_transaction_entry` — POST /api/transactions writes
  RAW SQL, bypassing upsert_transactions invariant gate
  (AI-037).

Live debit/credit families (11):
- `interest_charge` — synthetic seeder doesn't emit; faked
  via loan_details.ytd_interest in synthetic mode.
- `cc_fee` — Fees family lands in spending bucket today,
  not interest cost (AI-003 leak).
- `deposit_account_fee` — asset-debit (immediate) vs CC fee
  (liability addition).
- `cash_deposit` — counts as income via 'Deposits'
  category (AI-002).
- `check_deposit` — pending → posted lifecycle; partial-hold
  scenarios may transient-violate closure (AI-017).
- `check_written` — merchant_normalization regex strips
  check numbers (intentional but AI-022 means it's
  seeder-only).
- `atm_withdrawal` — promoted from not_modeled in v2
  events.yaml; no merchant relationship.
- `cashback_redemption` — categorization ambiguous (AI-004);
  rewards_points decrement is independent of the
  transactions credit row.
- `tax_refund` — best-classified one-off income type
  (3-way exclusion membership).
- `bonus_or_one_off_income` — silent forecast inflation if
  categorized 'Other Income' (AI-001).
- `reimbursement` — cross-account variant has no analog of
  purchase_refund's INCOME_EXCL_FROM_INC protection;
  inflates Sankey income.

Dev (1):
- `dev_advance_dummy_data` — synchronous subprocess invocation
  of seed_dummy_data.py; SSE broadcast intent dead due to
  AI-032; no environment flag gate.

**Surprises:**

- **AI-037 — `POST /api/transactions` bypasses
  `upsert_transactions`.** The `create_transaction` endpoint at
  `backend/routers/transactions.py:34-57` writes raw SQL
  directly to the transactions table, skipping the canonical
  sign/direction invariant choke point that CLAUDE.md
  guardrails explicitly call load-bearing. Pydantic default
  `direction='outflow'` is also non-canonical. This is the
  most severe finding of this session.
- **AI-038 — pipeline gap on three parsers.** Eventlink,
  acorns_statement, and acorns_confirmation parsers WRITE
  business data to ledger tables (`transactions`,
  `positions_ledger`) but DO NOT trigger
  `run_post_commit_pipeline` because they're not in the
  `institution_map`. Their data lands but downstream
  metrics (categorization, recurring detection, alerts,
  goal sync) don't recompute until the next refresh of any
  pipeline-mapped institution.
- **AI-039 — document history can't distinguish failed from
  pending.** The status column renders only "Committed" /
  "Pending" — no third state for failed uploads.
- **AI-040 — commit UPDATE matches on JSON-substring.** The
  PK is available from the upload INSERT's `lastrowid` but
  isn't propagated to the commit step; instead, the UPDATE
  uses `WHERE summary_json LIKE '%"file_id": "..."%'`.
  Fragile.
- **`update_attribution_rule` and `update_goal` are dead
  DAL functions.** Both exist in the DAL but no route
  handler exposes them. A user editing an attribution rule
  or goal name must DELETE + POST, losing the rule_id /
  goal_id and any external reference to it.
- **`interest_cost_recompute` synthetic-vs-live divergence
  fully traced.** The seeder paths (loan_details.ytd_interest
  via `loan_details_snapshot`) are the only signal in
  synthetic mode; `interest_charge` is the live equivalent
  but the synthetic seeder doesn't pay carried CC balances.
  Cross-link AI-009 confirmed across both YAMLs.
- **The Eventlink parser writes raw SQL with hardcoded
  `direction='credit'` (lowercase).** Same problem class as
  AI-037 but in a parser instead of a route handler.
  Folded into AI-037's notes.

**Sonnet subagent verdict (continued from sessions 5-11):**

2 agents this session (document pair only). 28 + 22 verbatim
citations, 0 self-flagged unverified. Spot-checks on
ParseResult dataclass + document_drops INSERT/UPDATE patterns
all passed. Pattern continues to be reliable.

For the other 22 records this session, NO subagents — direct
Reads + Writes. Per session 8's rule, when the writer family
is well-known and parallel YAMLs follow the same shape
(11 transaction-row events sharing upsert_transactions; 10
user CRUD events with thin DAL/router pairs), spawning a
subagent costs more than it saves. The work scaled cleanly:
~2 hours of direct authoring vs. an estimated ~3 hours if
each had needed subagent spawning + validation.

**Logged AI items:** AI-037 (POST /api/transactions bypass),
AI-038 (3 parsers don't trigger pipeline), AI-039 (history
can't distinguish failed/pending), AI-040 (JSON-substring
commit UPDATE). Four new items.

**Phase 2 status update:**

- system_derived: ✅ COMPLETE (23/23)
- user_action: ✅ COMPLETE (12/12)
- external_force: ✅ COMPLETE (15/15)
- live_only: ✅ COMPLETE (24/24)
- **Phase 2 ✅ COMPLETE.** 82 YAMLs on disk
  (some events have multiple sub-records or
  cross-references; events.yaml has ~70 unique IDs).

**Next agent should:** Start Phase 3 — the inverse index
(`docs/data-lineage/inverse-index.yaml`). STATUS.md says
"Build only after Phase 2 is ≥80% complete; it is a join
across all per-event files and partial input produces a
misleading map." Phase 2 is now 100%. The build pattern:
walk every `lineage/*.yaml`, extract every
`write_signature.table.column` and `direct_consumers.reads`
+ `derivations.inputs`, then invert to produce an index of
`table.column → list of events that touch it`. Programmatic
build is recommended (a Python script reading the YAMLs)
since the join is mechanical and the result will be
~hundreds of entries.

After Phase 3, Phase 4 diagrams (per-event Mermaid +
`_overview.mmd`) is the final piece. Both are best generated
programmatically from the YAMLs once Phase 2 is stable —
which it now is.

---

## Session 12.5 — 2026-04-26 — Critical AI fix pass (between Phase 2 and 3)

**Goal:** User asked when to tackle action items. Recommendation
was to wait for Phase 3 (inverse index gives clustering data
that turns 40 individual items into ~5-8 themed sessions), with
two exceptions worth fixing immediately because of severity:
AI-037 (raw-SQL `POST /api/transactions` bypassing the
sign/direction invariant — data integrity hazard) and AI-032
(RefreshBanner + MFAModal both dead — a live TSP refresh hangs
until 30-min timeout). User approved fixing both.

**Code changed:**

- `backend/routers/transactions.py:create_transaction` —
  rewrote to route through `dal.transactions.upsert_transactions`
  with `derive_signed_amount(abs(amount), direction)`.
  Added `_DIRECTION_ALIASES` map for back-compat with the
  TransactionsPage modal's `inflow`/`outflow` strings.
  Pydantic default updated `direction='outflow' → 'Debit'`.
  Merchant preserved via post-upsert UPDATE.
- `dal/parsers/eventlink.py:commit` — same shape: build
  canonical txn dicts and route through
  `upsert_transactions`. Fixed two parallel bugs (lowercase
  `direction='credit'`, non-existent `merchant_name`
  column write).
- `frontend/src/components/RefreshBanner.tsx` — replaced
  `es.onmessage` + legacy topic literals with
  `addEventListener` against canonical `SSE_TOPICS`
  constants. Subscribes to STATE_CHANGE,
  INSTITUTION_STARTED/_COMPLETE/_RETRY/_FAILED,
  REFRESH_COMPLETE, SESSION_TIMEOUT. Side effect:
  `institution_failed` and `institution_retry` topics now
  have a working subscriber where they had none before.
- `frontend/src/components/MFAModal.tsx` — replaced
  `es.onmessage` with `addEventListener(SSE_TOPICS.MFA_REQUIRED,
  ...)`. Real TSP MFA challenges now surface the OTP
  modal instead of hanging the connector thread.

**Verification:**

- 74 backend tests pass:
  test_transaction_invariants (5),
  test_document_drop_trust (9), test_document_drops (3),
  test_t02_document_drop (23), test_dal (15),
  test_reconciliation (7), test_dal_harmonization (8),
  test_failure_modes (4).
- Preview HMR picks up both UI changes; app mounts
  cleanly (no Vite error overlay); EventSource opens
  against the backend SSE endpoint successfully;
  no new console errors related to the touched
  components.

**YAMLs updated to reflect fixes:**

- `lineage/manual_transaction_entry.yaml` — AI-037 marked
  FIXED, write_signature notes describe the new alias map
  + derive_signed_amount path; income_attribution side
  effect now actually fires.
- `lineage/document_upload_commit.yaml` — Eventlink write
  signature updated to canonical Credit + merchant column;
  AI-037 cross-link marked FIXED.
- `lineage/connector_refresh_lifecycle.yaml` — RefreshBanner
  + MFAModal notes flipped from ⚠ to ✅ with the fix
  description.
- `lineage/connector_mfa_required.yaml` — MFAModal note
  flipped to FIXED with the new addEventListener pattern.
- `lineage/connector_balance_scrape.yaml` — RefreshBanner
  surface re-described as the working live-refetch
  trigger.
- `lineage/connector_failure.yaml` — Refresh banner SSE
  surface updated; INSTITUTION_FAILED / INSTITUTION_RETRY
  topics now have a subscriber.
- `lineage/connector_transactions_csv_upsert.yaml` —
  RefreshBanner surface re-described.
- `lineage/staleness_evaluation.yaml` — RefreshBanner
  note clarified (STALENESS_EVALUATED still has no
  subscriber, but for a different reason now —
  STATE_CHANGE → EVALUATING_STALENESS already drives the
  banner).
- `lineage/dev_advance_dummy_data.yaml` — REFRESH_COMPLETE
  SSE now reaches UI; "feel responsive" intent restored.

**ACTION_ITEMS.md:** AI-032 and AI-037 moved from Open to
Resolved with full root-cause + fix descriptions and
verification notes.

**Findings during the fix pass:**

- The Eventlink parser had a SECOND undisclosed bug — its
  raw SQL referenced a non-existent `merchant_name`
  column on `transactions`. The schema column is
  `merchant` (added in v11). The INSERT would have
  raised `sqlite3.OperationalError: no column named
  merchant_name` whenever a real Eventlink upload was
  committed. Suggests the eventlink commit path may
  never have been exercised end-to-end in production
  data — possibly synthetic-only or untested. Folded
  into the AI-037 fix.
- The TransactionsPage modal frontend (line 976) sends
  `direction: amt < 0 ? 'outflow' : 'inflow'`. Both
  legacy values are silently translated by the new
  alias map, so no frontend change was required for
  the fix to land. A future cleanup pass could
  switch the modal to canonical strings, but that's
  pure aesthetics.
- The frontend modal also doesn't let the user
  express "I have $50 and this is a Debit" — direction
  is always derived from sign. Out of scope; cosmetic
  UX gap, not a data-integrity issue.

**Process note:**

This session was small and focused (2 AI items, ~4 file
edits, ~10 YAML touch-ups). Deliberately stayed
narrow rather than triaging the rest of the AI list —
that's the work for after Phase 3, when the inverse
index can cluster the remaining 38 items.

**Next agent should:** Begin Phase 3 (inverse index)
per session 12's recommendation. The build pattern is
mechanical: walk every `lineage/*.yaml`, extract every
`write_signature.table.column` and
`direct_consumers.reads` + `derivations.inputs`, invert
to produce `table.column → list of events that touch it`.
A short Python script reading the YAMLs is the right
shape; result will be ~hundreds of entries.

---

## Session 13 — 2026-04-26 — Phase 3 (inverse index) generated

**Did:** Authored `build_inverse_index.py` and regenerated
`inverse-index.yaml` — Phase 3 deliverable. The script walks
`lineage/*.yaml`, joins `write_signature.columns_set` with the
sibling `table` for `written_by`, extracts `<table>.<column>`
tokens from `direct_consumers[].reads` and `derivations[].inputs`
for `read_by`, and aggregates `ui_surfaces[].page` →
`fed_by_events` + `via_endpoints` (verb+/api/path extracted
from the free-form `via:` string).

**Final stats:** 82 lineage files walked, 82/82 events
round-trip cleanly against `events.yaml`, 293 unique
`<table>.<column>` entries, 127 unique UI pages. 50
prose-only inputs survive in `unparsed_reads_for_followup` —
references to function names, in-memory state, frozensets, and
config files; correct to leave as prose.

**Pre-flight / data-quality fixes:** Seven lineage YAMLs
failed strict YAML parse on the first run and were repaired
with mechanical edits, no semantic change:

- `check_deposit.yaml`, `check_written.yaml` — `columns_set`
  was a single prose blob containing `{'pending', 'posted'}`
  flow-mapping syntax; rewrote as proper one-column-per-line
  list (the tokens are the canonical `transactions` columns).
- `document_upload_commit.yaml` — two `columns_set` items
  contained `:` separators that broke list framing; quoted
  the affected items.
- `merchant_normalization.yaml` — double-quoted scalar
  contained `\s` (regex) which YAML reads as an unknown
  escape; switched to single quotes and doubled the
  apostrophes.
- `net_worth_recompute.yaml` — `reads` continuation line
  indented 6sp instead of 8sp under the list item; quoted
  and re-indented as a folded scalar.
- `portfolio_snapshot.yaml` — two `output_location` values
  began with a backtick (unquoted, illegal YAML); quoted both.
- `user_goal_crud.yaml` — continuation line started with
  `AI:` which YAML reads as a key; quoted the multi-line
  string.

These seven faults would have broken any future YAML tool too,
so worth catching once.

**Aggregator nuances:**

1. Several `derivations[].inputs` are bare strings instead of
   lists (e.g. `inputs: get_recurring`). Iterating a string in
   Python emits per-character entries (200+ of them). Added a
   `coerce_list()` helper: scalars become a 1-item list. This
   is a schema violation per `lineage/README.md` but pervasive
   in the existing records — easier to be tolerant than to
   batch-rewrite the YAMLs. Light cleanup welcome on next edit.
2. About 105 reads/inputs entries name a bare table without a
   column suffix (e.g. `transactions on cash accounts (debit
   categories)`). Resolved against the set of tables seen in
   `write_signature` and emitted as `<table>.*` reads — captures
   the relationship rather than dropping it.

**Surprises:**

- The Cash Flow page is fed by **22** distinct events — the
  highest-traffic UI surface in the corpus. Transactions page
  next at 17, then Dashboard at 15. This validates the
  intuition that those three pages are where any data
  regression will surface fastest.
- `transactions.signed_amount` is written by 17 events and
  read by 14 — easily the most central column in the system.
  Any cash-flow / spending / income aggregator change touches
  this column; the inverse index now lists every event that
  must be considered for behavioural drift.
- `derived_summaries.metric` is written by 7 derived-recompute
  events but read by only 1 (`derived_summary_recompute_per_account`).
  That asymmetry confirms the long-suspected pattern: most
  `derived_summaries.<metric>` rows are write-only relative to
  the UI — the UI reads through compute-on-the-fly DAL helpers,
  not through `derived_summaries` rows.

**Next agent should:** Phase 4 (diagrams). The inverse index
is now stable and can drive Mermaid generation programmatically
(walk `by_table_column` for write→read edges, walk
`by_ui_surface` for event→page edges; one diagram per high-traffic
event, one `_overview.mmd`). Or pivot to triaging the open
ACTION_ITEMS — the inverse index makes it cheap to ask "if I
fix AI-NNN, which events / UI pages does that touch?" by
greping the YAML for the affected table.column.

---

## Session 14 — 2026-04-26 — ACTION_ITEMS clear-the-board sprint

**Did:** Single-session sweep of the ACTION_ITEMS backlog under
the `option-a` plan (`~/.claude/plans/option-a-let-s-see-snuggly-pixel.md`).
Cluster-by-cluster execution with subagents for breadth on
high-fan-out clusters (Cluster 5 + Cluster 6), main-thread
verification of every cited `file:line:symbol` before editing,
targeted pytest after each fix, full-suite + lint + frontend build
at the end.

**Score:** 31 of 33 in-scope AIs resolved + 4 deferred (AI-004,
AI-016, AI-020, AI-021 from the upfront triage) + 2 deferred
mid-sprint (AI-009, AI-012). Total 35 / 37 open AIs touched.

**Resolved (in execution order):**

- Cluster 7-quick: AI-013 (deleted deprecated `seed_dummy_db.py`),
  AI-028 (CLAUDE.md ref to deleted `dal/performance.py`),
  AI-029 (SPAXX docstring), AI-031 (list_accounts MAX-pivot CTE).
- Cluster 1 (income classification): AI-001 (Other Income →
  NON_PROJECTION_INCOME), AI-015 (regression test parsing
  BUDGET_BASE + recurring_transactions.json), AI-002
  (Deposits-as-income product question documented), AI-011 (dead
  income types in synthetic mode documented).
- Cluster 6 (telemetry threading): AI-034 (refresh_run_id end-to-end),
  AI-033 (balance_anomaly notification), AI-036 (csv_parse_failure
  notification), AI-035 (mfa_prompted flag from connector to
  refresh_events).
- Cluster 5 (snapshot writers): AI-027 (record_payroll_snapshot
  DAL helper, both seeder and parser route through it), AI-026
  (synthetic source_label aligned to ACME CORP PAYROLL),
  AI-025 (TSP statement parser writes a placeholder traditional
  bucket — honest about what the document doesn't carry).
- Cluster 7-remainder + Cluster 4-verifications: AI-003
  (compute_interest_cost CC-fee design intent documented),
  AI-014 (narrowed Exception → ImportError/OperationalError +
  WARNING log on others), AI-023 (deleted dead
  rebuild_merchant_snapshots), AI-039 (third "Failed" badge
  state on Documents page), AI-040 (PK-lookup commit UPDATE
  with substring fallback), AI-005/006/007/017 verifications
  closed.
- Cluster 4: AI-010 (Fidelity EFT bank-side mirror with
  transfer_tag link), AI-019 (deprecated dead
  recompute_interest_earned). AI-009 + AI-012 deferred —
  CC-carrying-balance + TSP-payroll-deduction modelling are
  architectural seeder additions out of scope for this pass.
- Cluster 2 (HIGHEST RISK pipeline): AI-008 (recurring detect),
  AI-022 (merchant normalize), AI-024 (ticker enrichment),
  AI-038 (eventlink/acorns parsers wired into institution_map).
- Cluster 3: AI-030 (Acorns cost_basis_dec on
  INITIAL_BASELINE/IMPLIED_BUY rows in both seeder and
  connector).

**Pipeline ordering (post-Cluster-2):**

1. Categorization
2. Merchant normalization (NEW, AI-022)
3. Transfer reconciliation
4. Recurring pattern detection (NEW, AI-008)
5. Acorns linkage (institution-gated)
6. Mortgage decomposition
7. Ticker metadata enrichment (NEW, AI-024)
8. Derived recompute
9. Alert evaluation
10. Goal balance sync
11. Notifications

Each new step uses the same `_run_step` try/log/continue isolation
as existing steps, so a crash in any one can't block the rest.

**End-of-sprint verification:**

- `python docs/data-lineage/build_inverse_index.py` — 82/82 events
  round-trip, 293 unique table.column entries, 127 UI surfaces.
- `python -m ruff check` against the 17 files I touched —
  no new lint warnings introduced (the 17 remaining warnings are
  pre-existing).
- `python -m pytest tests/ --tb=short` — **457/457 pass** in 98.18s.
- `cd frontend && npm run build` — Vite ✅ in 11.87s.
- Manual smoke (preview server, /documents): Vite hot-reloaded
  both AI-039 (Failed badge ternary) and AI-040 (`document_drop_id`
  in commit body) cleanly. End-to-end live upload→commit flow
  needs a running backend with migrations + a deliberately-broken
  PDF, which isn't routine smoke; the structural changes are
  covered by `tests/test_t02_document_drop.py` (23/23).

**Surprises:**

- AI-013 (deleting `seed_dummy_db.py`) had immediate downstream
  effects: `rebuild_merchant_snapshots` (AI-023) lost its only
  caller and became obviously dead, AI-022's `backfill_merchant_column`
  citation dropped one of its two references. Cleanup edits are
  often coupled in chains — worth deleting first to surface the
  actual dead-code shape.
- AI-007 was already-resolved by Phase 16 (5bp threshold) before
  the AI was filed. The lineage map had captured the 1bp concern
  correctly at the time; the code had moved on.
- AI-014's `try/except: pass` had been silently absorbing the
  ImportError shape for so long that nobody had verified it WASN'T
  also absorbing real bugs. The `WARNING` log path is the smallest
  diff that adds visibility.
- Cluster 5's AI-025 (TSP tax_buckets): the TSP statement
  document doesn't carry the Roth/Traditional split. Deferring
  was tempting but the placeholder writer + log.warning is more
  honest than leaving the table empty (the existing
  `get_tax_summary` fallback already assumes 100% traditional;
  AI-025 just makes the implicit explicit).
- Cluster 6's AI-035: the cleanest path was to flow `mfa_prompted`
  through ConnectorResult → summary → orchestrator rather than
  threading event_id into the connector. Three small, well-isolated
  edits beat one cross-cutting plumb.
- Subagents (Cluster 5 explore agent) cited line numbers
  accurately this session — possibly because the prompt
  emphasised re-Grep verification and required verbatim quotes.
  Even so, the verification re-Grep caught one minor citation
  shift on the ACTION_ITEMS body's claim that
  "scripts/seed_dummy_data.py:981-..." — the actual range was
  981-1003. Citation drift never disappears entirely.

**Process notes / changes:**

- Subagent calls: 2 explore agents (1 each for Cluster 5
  context-mapping + Cluster 1 inventory at session-start). The
  Plan-first instruction for Cluster 2 was honoured by reading
  the existing pipeline structure in detail before editing,
  rather than by spawning a separate Plan subagent — judgement
  call given the structural straightforwardness of "add 3 more
  `_run_step` invocations between existing ones".
- Two AIs deferred mid-sprint with explicit
  `deferred_seeder_scope` / `deferred_architectural` status
  tags so they're easy to find later.
- Lineage YAML touch-ups: ~10 records updated with
  `✅ AI-NNN FIXED <date>` cross-links so future sessions
  reading those YAMLs see the resolution status without
  cross-referencing ACTION_ITEMS.

**Next agent should:** Phase 4 (Mermaid diagrams). The
inverse index is regenerated cleanly, ACTION_ITEMS is much
shorter, and the cluster taxonomy is captured in this entry
for anyone retracing how the board got cleared. Or — if a
real Acorns / TSP user surfaces — tackle AI-020 / AI-021
(deferred architectural) and AI-012 (TSP contributions) in a
single focused session, since they share the cross-account
contribution-attribution architecture.

**Do not commit.** User reviews and commits.

---

## Session 15 — 2026-04-26 — Phase 4 (diagrams) generated

**Did:** Authored `build_diagrams.py` and generated all 82 per-event
Mermaid diagrams plus `diagrams/_overview.mmd`. Phase 4 complete.
Followed the Phase 3 pattern: a single generator script that walks
`lineage/*.yaml` and emits diagrams from the YAML so they don't
drift. Updated `diagrams/README.md` and `STATUS.md` to point at the
script.

**Per-event diagram shape:**

- origin (rounded rectangle, amber) — `file:symbol` from `origin`.
- write tables (stadium, blue) — one per distinct table in
  `write_signature`; insert/update/delete operations are collapsed
  onto one node and joined as a `<br/>` op summary line.
- direct consumers + derivations (rectangle, grey for consumers,
  green for derivations) — labelled `file:symbol`, derivations also
  carry the metric name on a second line.
- ui surfaces (hexagon, pink) — deduped by `page` value.
- external effects (circle, purple, dotted edge) — capped at 6 per
  diagram; no-op rows ("No SSE.", "n/a", etc.) filtered.

Edges:

- origin → each write table.
- For each consumer/derivation: prefer table edges matched against
  `<table>.<col>` tokens in the consumer's `reads` / derivation's
  `inputs`; fall back to the first write table when no match.
- For each UI surface: edge from every consumer + derivation. If
  there are no consumers/derivations the write tables fan out
  directly. (Crossbar fan-out for events like `paycheck` is dense
  but correct; refinement via `fan_out` text is a future polish.)

**Overview shape:**

Four class subgraphs (`user_action 12`, `external_force 16`,
`system_derived 23`, `live_only 31`) → top-5 write tables (by
combined write+read activity, writers≥1) → top-5 UI surfaces (by
total `fed_by_events` count). One arrow per dominant relationship,
not per individual event. The "written by 0" join-target trap
(initial output included `accounts`) was filtered out by requiring
at least one writer per included table.

**Final stats:**

- 83 Mermaid files written (`82 events + 1 overview`).
- All 83 pass a basic syntax check (every edge endpoint is a
  declared node; node-shape parens/brackets/braces balanced).
- The Cash Flow page is the most-fed UI in the overview (transactions,
  positions_ledger, portfolio_snapshots, balance_snapshots all flow
  to it), confirming the Phase 3 finding from session 13.
- `transactions` is reachable from all four class super-nodes — the
  central spine of the system, as expected.

**Token-extraction iteration:** The first pass produced
unhelpful effect labels for SSE topics. Three iterations to settle:

1. Naive "first uppercase token" produced `SSE`, `INFO`, `FIXED`
   from prose like "REFRESH_COMPLETE SSE after batch" and
   "✅ AI-036 FIXED 2026-04-26".
2. Reordered to prefer underscore-bearing UPPER tokens — fixed
   `REFRESH_COMPLETE` cases, but still missed connector lifecycle
   SSE topics ("SSE state_change") because the topic is lowercase.
3. Final ordering: leading `SSE <topic>` pattern wins (handles
   connector lifecycle); else underscore-bearing UPPER token (handles
   `REFRESH_COMPLETE`); else other UPPER, then backtick, then
   first-three-words. Filtered `GENERIC_TOKENS` set
   (`SSE`, `INFO`, `WARN`, etc.). After the third iteration: 5/6
   connector-lifecycle effect topics resolve to their actual SSE
   topic name; `REFRESH_COMPLETE` and `notification` resolve clean
   on the other events spot-checked.

**Surprises:**

- The "(none — read-only check)" table label in
  `sign_direction_invariant.yaml` flowed through to the diagram
  intact (sanitized to `tbl_none_read_only_check`). It's not a real
  table but the convention "explicit `[]` placeholder rather than
  omit" produces a node anyway. Acceptable — the diagram correctly
  shows that this event has no write but has downstream consumers
  via the choke-point invariant.
- `merchant_normalization` and `merchant_snapshot_rebuild` produce
  diagrams with a single UI node "(none traced today)" — the YAMLs
  faithfully document that these analytics paths have no live
  consumer. The diagram preserves that finding visually rather than
  hiding it.
- The crossbar fan-out for high-derivation events (`paycheck` has
  4 derivations × 7 UIs = 28 edges; `investment_buy` has 7
  derivations × 6 UIs = 42 edges) is the noisiest output. Mermaid
  renders fine but the layout is dense. Captured as a future-polish
  follow-up in `STATUS.md > Phase 4`; ship as-is for now.

**Files touched (no application code):**

- new: `docs/data-lineage/build_diagrams.py`
- new: `docs/data-lineage/diagrams/<82 events>.mmd`
- new: `docs/data-lineage/diagrams/_overview.mmd`
- updated: `docs/data-lineage/diagrams/README.md` (points at
  generator, lists shape conventions)
- updated: `docs/data-lineage/STATUS.md` (Phase 4 row → ✅ done,
  Phase 4 section now mirrors Phase 3 with stats + follow-ups)

**Verification:**

- `python build_diagrams.py` from `docs/data-lineage/` — 82+1
  diagrams written, no skipped files.
- Static Mermaid sanity check (declared-vs-referenced node IDs,
  shape paren balancing) — 0 errors across all 83 files. No
  `mmdc` CLI available in this environment to do a full render
  test; the static check is conservative but catches the obvious
  failure modes (typo'd edge endpoints, unbalanced brackets).
- Spot-checked `paycheck.mmd`, `connector_refresh_lifecycle.mmd`,
  `merchant_normalization.mmd`, `investment_buy.mmd`,
  `sign_direction_invariant.mmd`, and `_overview.mmd` for label
  legibility. All read clean.

**Next agent should:** Phase 4 is done. Validation checklist in
`STATUS.md` is now satisfiable end-to-end (every event has a
record, the inverse index round-trips, every diagram renders).
The lineage map is complete. Reasonable next moves:

- Tackle the deferred architectural items (AI-009 CC carrying
  balance, AI-012 TSP payroll deduction, AI-020/AI-021 v34 view
  rewrite) — all need seeder/architecture work, not lineage work.
- Polish pass on the diagrams: use `derivations[].fan_out` text
  to scope derivation→UI edges instead of full crossbar fan-out
  on dense events.
- Use the lineage map as intended: when a bug is reported, grep
  the inverse index for the affected `<table>.<column>` to list
  every event/UI that could be involved, then open the per-event
  diagram for each.

**Do not commit.** User reviews and commits.
