# Shared Evidence Ledger

Common input ledger for the five-round adversarial review of UI number
trust. Each participant appends evidence references before making
claims. See [adversarial-review-plan.md §Exchange Of Information](../adversarial-review-plan.md)
for the rules of engagement.

This file was created during Round 2 because Round 1 embedded its
content directly in the plan file. Round 1's evidence is reconstructed
below from the plan + repo state at HEAD (`4eb449e`); Codex should
verify and amend if anything is mischaracterized.

---

## Canonical seed facts (verified)

| Fact | Value | Source |
|---|---|---|
| Seed version | `trusted-2026-04-27-v1` | [scripts/dummy_data/trusted_seed.py:12](../../../../scripts/dummy_data/trusted_seed.py) |
| Seed end date | `2026-04-27` | [trusted_seed.py:13](../../../../scripts/dummy_data/trusted_seed.py) |
| Reference date | `2026-04-28` | [trusted_seed.py:14](../../../../scripts/dummy_data/trusted_seed.py) |
| Seed years | `3` | [trusted_seed.py:15](../../../../scripts/dummy_data/trusted_seed.py) |
| DB fingerprint | `f061229325d607ffd06e8ea22dee2831a2db18bd91f140c16c88982548c8b9ec` | [data/trusted_seed_manifest.json:2](../../../../data/trusted_seed_manifest.json), [tests/test_trusted_seed.py:19](../../../../tests/test_trusted_seed.py) |
| Account count | 12 | manifest `row_counts.accounts` |
| Transaction count | 1607 | manifest `row_counts.transactions` |
| Balance snapshot count | 269 | manifest `row_counts.balance_snapshots` |
| Portfolio snapshot count | 114 | manifest `row_counts.portfolio_snapshots` |
| Owners | 2 (Quintin, Amy) | manifest `row_counts.owners` |
| Alert rules pre-seeded | 4 | manifest `row_counts.alert_rules` |

---

## Audit harness facts (verified)

| Fact | Value | Source |
|---|---|---|
| Audit script | `scripts/audit_number_trust.py` | [path](../../../../scripts/audit_number_trust.py) |
| API client | `fastapi.testclient.TestClient` (in-process) | [audit_number_trust.py:148-156](../../../../scripts/audit_number_trust.py) |
| Oracle DB | same SQLite file as the API; `os.environ["SENTRY_DB_PATH"]` set at top of `run()` | [audit_number_trust.py:642-643](../../../../scripts/audit_number_trust.py) |
| Default DB path | `data/sentry.db` (silent fallback) | [audit_number_trust.py:24](../../../../scripts/audit_number_trust.py), [dal/connection.py:26-27](../../../../dal/connection.py) |
| Owner filter in audit | none — every endpoint called without `owner_id` | [audit_number_trust.py:653-694](../../../../scripts/audit_number_trust.py) |
| Money precision | mixed: `_round2` (float) for `raw_report_summary`; `_cents` for `raw_cashout_period` | [audit_number_trust.py:135-141, 159, 330](../../../../scripts/audit_number_trust.py) |
| Audit-time DB mutation surface | `init_db()` + `seed_default_rules()` + `recover_orphaned_runs()` via FastAPI lifespan | [backend/api_server.py:64-74](../../../../backend/api_server.py); `seed_default_rules` short-circuits on existing rows ([dal/alerts.py:77-79](../../../../dal/alerts.py)) |

---

## Latest audit report (2026-04-29 09:23:12)

| Field | Value | Source |
|---|---|---|
| Report (md) | `docs/audits/number-trust/reports/number-trust-20260429-092312.md` | [path](../reports/number-trust-20260429-092312.md) |
| Report (json) | `docs/audits/number-trust/reports/number-trust-20260429-092312.json` | [path](../reports/number-trust-20260429-092312.json) |
| Diff count | `0` | report root |
| Surfaces audited | `dashboard.net_worth.latest`, `dashboard.monthly_net_flow`, `dashboard.emergency_runway`, `dashboard.credit_scores.latest`, `dashboard.freshness.state_labels`, `cash_flow.current_month`, `cash_flow.rolling.latest_month` (7 entries; 5 of these are Dashboard, 2 are Cash Flow) | [report json:`checks`](../reports/number-trust-20260429-092312.json) |
| Pages NOT audited | Transactions, Reports, Accounts (zero registered values) | [registry](../ui-number-registry.yaml) |
| Owner scopes audited | household only | derived from audit script |

### Cross-endpoint April 2026 agreement (latest report)

| Field | `/api/reports/summary` | `/api/cash-flow/period` | Δ |
|---|---|---|---|
| Income | 16,900.00 | 16,900.00 | 0.00 |
| Spending | 4,629.00 | 4,629.00 | 0.00 |
| Net | 12,271.00 | 12,271.00 | 0.00 |
| Savings rate | (not in `summary`) | 72.6% | n/a |

Source: [report json:23-62, 277-379](../reports/number-trust-20260429-092312.json).
The earlier Round 2 disagreement was superseded by the latest promoted
report; reports and cash-flow definitions still need durable invariant
coverage before this is considered proven.

### Other anomalies in the report (not flagged as diffs by the audit)

- `dashboard.emergency_runway.months_of_runway = 153.8` (≈12.8 years).
  Synthetic ratio:
  `liquid_balance: 252,626 / avg_monthly_spending: 1,642.83`
  ([report json:65-97](../reports/number-trust-20260429-092312.json)).
- `Paycheck (no deposit matched)` appears as an income category in
  the trusted synthetic seed
  ([report json:294-298](../reports/number-trust-20260429-092312.json)).
- `tsp` and `tsp_synthetic` both appear in the freshness list as
  separate institutions
  ([report json:200-207](../reports/number-trust-20260429-092312.json)).
- `dashboard.net_worth.latest` "actual" returns 8 fields; "expected"
  oracle declares 4 — only `assets`, `liabilities`, `month`,
  `net_worth` are checked. `banking_assets`, `investment_assets`,
  `real_estate_assets`, `vehicle_assets` are unverified
  ([report json:4-21](../reports/number-trust-20260429-092312.json)).

---

## Frontend reference-date survey (Grep, Round 2)

`grep -n 'new Date()' frontend/src/**/*.{ts,tsx}` (10 files):

| File | Line(s) | Purpose | In audit scope |
|---|---|---|---|
| [components/layout/Header.tsx](../../../../frontend/src/components/layout/Header.tsx) | 21 | visible "today" string in chrome | yes (chrome) |
| [pages/DashboardPage.tsx](../../../../frontend/src/pages/DashboardPage.tsx) | 75, 96 | current-month default; spending-comparison reference date | yes |
| [pages/CashFlowPage.tsx](../../../../frontend/src/pages/CashFlowPage.tsx) | 823 | period defaults | yes |
| [pages/TransactionsPage.tsx](../../../../frontend/src/pages/TransactionsPage.tsx) | 123, 133 | "This Month", "Last 3 Months" presets | yes |
| [pages/YearlyWrapUpPage.tsx](../../../../frontend/src/pages/YearlyWrapUpPage.tsx) | 27 | year selector default | partly |
| [pages/MonthlyReviewPage.tsx](../../../../frontend/src/pages/MonthlyReviewPage.tsx) | (not enumerated this round) | (not enumerated) | partly |
| [pages/BudgetsPage.tsx](../../../../frontend/src/pages/BudgetsPage.tsx) | (not enumerated) | (not enumerated) | out of scope |
| [pages/ReportsPage.tsx](../../../../frontend/src/pages/ReportsPage.tsx) | (not enumerated) | (not enumerated) | yes |
| [components/DocumentNudge.tsx](../../../../frontend/src/components/DocumentNudge.tsx) | 26, 30 | dismiss-until-tomorrow logic | out of scope |
| [components/ManualAssetEditModal.tsx](../../../../frontend/src/components/ManualAssetEditModal.tsx) | 63 | `today()` for date input default | out of scope |

Audit script's reference date comes from `dal/clock.py` (backend) →
manifest. **Frontend has no equivalent.**

---

## Pre-commit gate behavior (Round 2)

Surfaced when Round 2 attempted to commit two markdown artifacts.

| Fact | Value | Source |
|---|---|---|
| Hook script | `.claude/hooks/pre_commit_gate.py` | [path](../../../../.claude/hooks/pre_commit_gate.py) |
| Trigger | every `git commit …` invocation | hook line 62 |
| Checks | `pytest -x --tb=short -q` then `scripts/pii_scan.py` | hook lines 67-69 |
| Bypass mechanism | none documented; no `SKIP_PYTEST` analog to `SKIP_DOCS_CHECK` | source code inspection |
| Hook introduced | `bdcfeb3 chore(claude): wire pre-commit gate + python auto-fix hooks`, before `4eb449e Establish trusted seed audit foundation` | `git log --diff-filter=A` |
| Round 2 attempt result | 1 failed, 380 passed in 78.15s | gate stderr |
| Failing test | `tests/test_notifications_producers.py::test_bill_overdue_emits_notification` | gate stderr |
| Failing assert | `assert len(overdue) == 1` (got `0`) | gate stderr |
| Test modified on this branch | no (`git log main..HEAD -- tests/test_notifications_producers.py` is empty) | git verification |
| Round 2 resolution | committed with `--no-verify` per explicit user authorization, finding logged in [round-2-adversary.md §Reasoning #14](round-2-adversary.md) | this round |

Round 3 should treat this as a **logged exception**, not a precedent.
A follow-up task is needed to either fix the test, fix the production
code, or document a bypass mechanism.

## Selector / e2e infrastructure (Round 2)

| Search | Result |
|---|---|
| `data-testid` in `frontend/src/**/*.{ts,tsx}` | 0 occurrences |
| `data-test` in same | 0 occurrences |
| `**/playwright*` glob | only `profiles/nfcu/playwright/...` (Chrome credential vault, unrelated) |
| `**/e2e/**` glob | no matches |
| `**/browser_audit*` glob | no matches |

**No automated browser-audit infrastructure exists.** Round 1's
"browser checks" is a manual eye-test.

---

## Open questions for the user (cumulative across rounds)

Maintained as a running list. Each entry is tagged with the round
that raised it.

1. **[R2]** Are `/api/reports/summary` and `/api/cash-flow/period`
   intended to ship two definitions of "April 2026 income/spending/net"
   to the same user? If so, where is the UI label that disambiguates
   them?
2. **[R2 superseded]** Should the audit fail when income category percents do
   not sum to ~100? Latest promoted report sums to 100.1% after display
   rounding; keep as an invariant design question.
3. **[R2]** Is `Paycheck (no deposit matched)` an expected synthetic
   artifact or a seeder bug?
4. **[R2]** Is per-owner accuracy required at the trust gate, or is
   household-only acceptable for now?
5. **[R2 updated]** Is the 153.8-month emergency runway intentional? Should the
   "simplify" phase widen to realistic ratios across banking, debt,
   and investments rather than just investments?
6. **[R2]** Is a manual browser eye-test acceptable as Round 1 trust
   evidence, or must Phase 4 deliver an automated DOM check first?
7. **[R2]** Should the harness add a second, independently-implemented
   oracle (e.g. hand-curated fixtures), or is that overkill for a
   local-first single-household tool?
8a. **[R2]** Should the pre-commit gate accept a documented bypass
    (analogous to `SKIP_DOCS_CHECK`), or should every test failure
    block every commit unconditionally? Surfaced by the
    `test_bill_overdue_emits_notification` failure during the Round 2
    commit attempt.
8b. **[R2]** Is `test_bill_overdue_emits_notification` a test
    brittleness (UTC-vs-local-date boundary) or a real production
    bug in `dal/bills.py`? Triage in a follow-up task.
8. **[R1]** Should canonical backend/dev startup hard-fail without
   `SENTRY_DB_PATH`, or use an explicit
   `SENTRY_DB_MODE=trusted|live` gate?
   ([adversarial-review-plan.md:281](../adversarial-review-plan.md))
9. **[R1]** Should investment simplification replace the canonical
   seed, or live as a separate fixture?
   ([adversarial-review-plan.md:282](../adversarial-review-plan.md))
10. **[R1]** Should browser audit require stable test IDs, accessible
    labels, or both?
    ([adversarial-review-plan.md:283](../adversarial-review-plan.md))
11. **[R1]** Should reports store all proof artifacts, or only the
    latest canonical report?
    ([adversarial-review-plan.md:284](../adversarial-review-plan.md))
12. **[R1]** Should owner-specific UI accuracy be required before
    expanding beyond Dashboard and Cash Flow?
    ([adversarial-review-plan.md:285](../adversarial-review-plan.md))
13. **[R4]** Migration vs labels: commit to migrating
    `dal/reports/spending.py::get_period_summary` to consume
    `compute_period_totals` (codebase already started this for Cash
    Flow and Sankey), or accept two permanent lenses with registry
    labels?
14. **[R4]** Investments scope: bring Investments into the audit
    registry (7 endpoints, ~5,500 seed rows), or scope-limit Phase 2
    to investment data the in-scope pages consume?
15. **[R4]** Live vs manifest fingerprint: should the runtime identity
    endpoint compute a live fingerprint and compare to the manifest's
    recorded value, or just verify the recorded value?
16. **[R4]** Dev endpoints in proof mode: gate `/api/dev/*` by mode
    flag, or have the proof gate verify dev endpoints are unreachable
    before declaring success?
17. **[R4]** Lens vocabulary: controlled enumeration for
    `definition/lens` registry field, or free text?
18. **[R4]** Expected-values fixture granularity: just headline
    totals, or include ~20 per-row spot checks across in-scope pages?

---

## Round 4 findings appended to the ledger

### Cross-endpoint contradiction is unfinished migration, not deliberate design

| Fact | Source |
|---|---|
| `compute_period_totals` is the project's canonical income/spending aggregator | [dal/flow_aggregation.py:1-77](../../../../dal/flow_aggregation.py) docstring |
| Cash Flow's `/api/cash-flow/period` consumes `compute_period_totals` | [dal/cash_flow.py:330](../../../../dal/cash_flow.py) |
| Sankey's `/api/reports/flow` consumes `compute_period_totals` | [dal/reports/flow.py](../../../../dal/reports/flow.py) (grep result) |
| Reports summary's `/api/reports/summary` does NOT consume `compute_period_totals` | [dal/reports/spending.py:156-200](../../../../dal/reports/spending.py) |
| Documented intent: "both pages will consume in PR2" | [dal/flow_aggregation.py:33](../../../../dal/flow_aggregation.py) |

Round 2's $2,107 cross-endpoint disagreement is the legacy lens vs
the new lens. Migration is partially done. Round 4 proposal: finish
the migration in Phase 1.5.

### Audit duplicates the canonical category sets

| Fact | Source |
|---|---|
| `dal/category_classifications.py` declares itself single source of truth | file docstring lines 1-9 |
| Audit defines local copies of `INCOME_CATEGORIES`, `EXCLUDED_FROM_SPEND`, `INCOME_EXCL_FROM_INC`, etc. | [scripts/audit_number_trust.py:28-114](../../../../scripts/audit_number_trust.py) |
| Currently in sync (manual diff) | n/a |
| Automated test enforcing sync | none found |
| Audit script does not import from `dal.category_classifications` | `Grep "from dal.category_classifications" scripts/*.py` returned no matches |

Round 4 proposal: add a Phase 0 (or fold into 1.5) to import the
canonical sets and add a regression test.

### Investments scope vs Phase 2 inconsistency

| Fact | Source |
|---|---|
| Investments endpoint count | 7 (holdings, activity, performance, lots, allocation, tax-buckets, tax-summary) — [backend/routers/investments.py:16-101](../../../../backend/routers/investments.py) |
| Investments seed row count | 114 portfolio_snapshots + 570 investment_holdings + 555 positions_ledger ([trusted_seed_manifest.json](../../../../data/trusted_seed_manifest.json)) |
| Investments registry entries | 0 |
| Phase 2 scope | "round starting balances + monthly contributions, no growth/loss/dividend/sell" — modifies investment seed data |
| Audit verification of Investments-page renders | none |

Round 4 proposal: the user must choose — bring Investments into
audit scope (Phase 4a registry expansion + Phase 4b DOM coverage),
or scope-limit Phase 2 to investment data the in-scope pages
consume (portfolio snapshots feeding net worth, dividends feeding
cash-flow income).

### Runtime identity endpoint scope

| Fact | Source |
|---|---|
| Codex Phase 1 acceptance: "runtime identity fingerprint matches `app_settings.trusted_seed_manifest`" | [round-3-codex-response.md §Phase 1](round-3-codex-response.md) |
| Manifest fingerprint source | written by seeder, never updated post-seed |
| Live DB drift detection | none |
| `app_settings.trusted_seed_manifest` row update writers | only the seeder script |
| Mutation surfaces that bypass the seeder | API ingestion writers, dev/reset endpoint, ad-hoc migrations, accidental writes during import-order DB-path race |

Round 4 proposal: the identity endpoint computes a *live* fingerprint
over the canonical row set and reports it alongside the manifest's
recorded value. Proof gate fails on mismatch.

### Dev endpoints reachable in trusted mode

| Fact | Source |
|---|---|
| `/api/dev/reset-trusted-seed` exists | [backend/routers/dev.py:56](../../../../backend/routers/dev.py) |
| Router unconditionally registered | [backend/api_server.py:55](../../../../backend/api_server.py) |
| Mode-flag gate | none |
| Docstring caveat ("should NOT be exposed in any deployed build") | [backend/routers/dev.py:1-9](../../../../backend/routers/dev.py) |

Round 4 proposal: gate dev endpoints by `SENTRY_DB_MODE` or have
proof gate verify they're unreachable.

---

## Inherited assumptions (carried into Round 3)

From Round 1, treated as given unless rebutted:

- Canonical seed is deterministic and fingerprint-stable on reseed.
  Verified by [tests/test_trusted_seed.py:51-65](../../../../tests/test_trusted_seed.py).
- Live market / network paths are no-ops for synthetic price and
  metadata. Verified by [tests/test_trusted_seed.py:68-114](../../../../tests/test_trusted_seed.py).
- Backend trusted-reference-date plumbing exists in `dal/clock.py`
  and is consumed by routers that default the year/period.

From Round 2, added to the ledger:

- The audit oracle is *not* independent of the API (same DB, same
  process, similar SQL).
- The audit harness has no cross-endpoint or invariant assertions.
- Owner/view filtering is not exercised in any current audit run.
- Frontend pages compute period inputs from `new Date()`, bypassing
  `dal/clock.py` whenever the frontend supplies explicit `start`/`end`.
- No browser-audit infrastructure exists yet; trust claims for
  rendered values rely on manual inspection.

From Round 4, added to the ledger:

- The cross-endpoint contradiction is a half-finished migration to
  `compute_period_totals`, not a deliberate two-lens product
  decision. Cash Flow and Sankey were migrated; Reports summary
  wasn't.
- The audit script's hardcoded category sets duplicate
  `dal/category_classifications.py` (which itself forbids local
  copies). Currently in sync; no automated check.
- Investments page is officially out of scope for the audit but
  Phase 2 reshapes ~5,500 rows of investment seed data the
  Investments page consumes — internal plan inconsistency.
- "Runtime identity matches manifest" is too weak; manifest is
  written once by the seeder, so a mutated trusted DB still passes
  the proposed Phase 1 acceptance.
- `/api/dev/reset-trusted-seed` is reachable in the same backend
  process the proof gate audits, with no mode-flag gate.

From Round 5, final synthesis:

- Codex accepts Round 4's key correction: the Reports vs Cash Flow
  mismatch should be handled as unfinished migration to
  `compute_period_totals`, not as two permanent user-facing lenses.
- Final recommendation keeps the Investments page out of this
  five-page trust phase, while auditing investment-derived values that
  appear on Dashboard, Transactions, Cash Flow, Reports, and Accounts.
- Original Round 5 recommendation was layered proof plus committed
  expected-value fixtures, not a second-language oracle in this phase.
  This was superseded by the post-Round-5 user decision below.
- Final execution order is:
  Phase 0 vocabulary and registry semantics,
  Phase 1 DB authority,
  Phase 1.5 API definitions/invariants/owner-view,
  Phase 2 seed explainability,
  Phase 3 frontend reference date,
  Phase 4a selectors/registry expansion,
  Phase 4b DOM audit,
  Phase 5 one-command proof gate.

Post-Round-5 user decisions:

- Trust contract accepted.
- Canonical cash-flow definition accepted; migrate Reports summary to
  `compute_period_totals`.
- Investments-page exclusion accepted; audit investment-derived values
  on the five scoped pages only.
- Oracle strategy revised stronger: use a second-language independent
  oracle if that is the better trust proof.
- Deterministic/explainable seed accepted; add investment complexity
  later step by step after the simple proof is clean.
- DB authority decision: one database only for active runtime and proof.

See [../implementation-decisions.md](../implementation-decisions.md).

---

## Commands run in Round 2 (reproducibility)

- `git log --oneline -10` (verify branch head and recent context).
- `git show --stat 4eb449e | head -50` (verify Round 1 commit
  contents).
- Glob: `docs/audits/number-trust/**/*`,
  `**/scripts/dummy_data/**/*.py`, `**/audit*.py`, `**/trusted*`,
  `**/playwright*`, `**/e2e/**`, `**/browser_audit*`,
  `frontend/src/**/*.tsx`, `dal/{cash_flow,reports}.py`.
- Grep: `SENTRY_DB_PATH|sentry\.db|trusted_seed_manifest`,
  `new Date\(\)`, `data-testid|data-test`,
  `def get_period_summary|def get_period_detail`,
  `def init_db|def seed_default_rules|def seed_institutions`,
  `def.*period|def.*summary|signed_amount|effective_month|posting_date`.
- Read: full files for `audit_number_trust.py`, `trusted_seed.py`,
  `connection.py`, `clock.py`, `trusted_seed_manifest.json`,
  `ui-number-registry.yaml`, `number-trust-20260429-092312.{md,json}`,
  `tests/test_trusted_seed.py`, partial reads for `api_server.py`,
  `cash_flow.py` (router + DAL), `reports.py`.

No write operations. No DB mutation. No git mutation other than the
final review-round commit (separate, with only the two new artifacts
under `docs/audits/number-trust/adversarial-review/`).

---

## Round 3 Evidence Addendum

Round 3 is recorded in
[round-3-codex-response.md](round-3-codex-response.md).

### Round 3 commands run

- `git status --short`
- `git log --oneline -5`
- `Get-ChildItem docs\audits\number-trust -Recurse`
- `Get-Content docs\audits\number-trust\adversarial-review\round-2-adversary.md`
- `Get-Content docs\audits\number-trust\adversarial-review\shared-evidence.md`
- Python JSON inspection of
  `docs/audits/number-trust/reports/number-trust-20260429-092312.json`
- `Select-String` searches for:
  - `new Date(`
  - `data-testid`
  - `data-test`
  - `owner_id`
  - `TestClient`
  - `SENTRY_DB_PATH`
  - `raw_report_summary`
  - `raw_cashout_period`
  - `_round2`
  - `_cents`

`rg` was attempted but denied by the local Windows environment, so
Round 3 used PowerShell `Select-String`.

### Round 3 verified report values

From `number-trust-20260429-092312.json`:

| Surface | Income | Spending | Net | Savings rate |
|---|---:|---:|---:|---:|
| `dashboard.monthly_net_flow` / `/api/reports/summary` | 16,900.00 | 4,629.00 | 12,271.00 | n/a |
| `cash_flow.current_month` / `/api/cash-flow/period` | 16,900.00 | 4,629.00 | 12,271.00 | 72.6% |

Additional verified values:

- `cash_flow.current_month.income_categories` totals sum to
  `16,900.00`.
- `cash_flow.current_month.income_categories` percentages sum to
  `100.1` after one-decimal display rounding.
- `dashboard.emergency_runway.months_of_runway` is `153.8`.

### Round 3 position summary

Codex accepts the main Round 2 critique and revises the plan:

- Keep Phase 1 single DB authority first.
- Insert Phase 1.5 for API audit invariants and owner/view coverage.
- Reframe investment simplification as part of broader canonical seed
  explainability and realistic-ratio decisions.
- Split the UI audit into selector pass and DOM audit.
- Treat current `Diff count: 0` as a baseline API consistency result,
  not as proof of visible UI number trust.
