# Round 2: Adversarial Critique

Reviewer: **Claude (Opus 4.7, 1M context)**, acting as the
adversarial reviewer per
[adversarial-review-plan.md](../adversarial-review-plan.md) §Round 2.
Round 1 was authored by Codex and embedded directly in the plan file.
Date: 2026-04-28.
Branch: `codex-trusted-seed-audit`.
Commit under review: `4eb449e Establish trusted seed audit foundation`.

---

## Position

**The "diff count: 0" headline is structurally insufficient evidence of
trust, and the Round 1 staged plan defers the only phase that would
actually produce new evidence — Phase 4 (oracle-to-API-to-DOM) — to
last.**

Three structural problems make the existing audit weaker than the
report suggests:

1. The oracle and the API read the **same SQLite file** with similar
   SQL. Agreement is mostly a self-consistency check, not an
   independent ground truth.
2. Two surfaces in the same audit run already disagree by **$2,107**
   on April 2026 net cash flow. Both pass their isolated oracle. The
   harness has no cross-endpoint or invariant assertions.
3. **Owner/view is not in the harness at all**, **frontend pages still
   pin to `new Date()`**, and **3 of 5 in-scope pages have zero
   coverage**. The trust claim is bounded much more narrowly than
   "Dashboard, Transactions, Cash Flow, Reports, Accounts."

I therefore reject Round 1's premise that the right next move is "make
the seed, runtime DB, reference date, owner/view state, and investment
assumptions boring enough that a mismatch has a small search space."
Operational ambiguity reduction (Phases 1-3) is **necessary but not
sufficient**. Trust is an **evidence problem**, not an ambiguity
problem. Without the cross-endpoint invariants, the owner/view
parameter, and the rendered-DOM check, Phases 1-3 produce a more
reproducible audit of an audit that already does not prove what the
user sees.

I propose a re-sequenced plan (see §Proposed changes) that **front-loads
invariants and owner-scoping** into the existing API-only harness,
**before** the larger investments-simplification and DOM-audit work.

---

## Evidence used

### Repo paths inspected

- [scripts/audit_number_trust.py](../../../../scripts/audit_number_trust.py) — audit harness, oracle definitions, in-process API client.
- [scripts/dummy_data/trusted_seed.py](../../../../scripts/dummy_data/trusted_seed.py) — seed constants (`TRUSTED_SEED_VERSION`, `TRUSTED_REFERENCE_DATE`).
- [scripts/dummy_data/generator.py](../../../../scripts/dummy_data/generator.py) (existence noted; not deeply read this round).
- [tests/test_trusted_seed.py](../../../../tests/test_trusted_seed.py) — fingerprint reseed-stability test.
- [dal/connection.py](../../../../dal/connection.py) — `DB_PATH` resolution; default fallback to `data/sentry.db`.
- [dal/clock.py](../../../../dal/clock.py) — reference-date abstraction; **backend-only**, no frontend equivalent.
- [dal/cash_flow.py](../../../../dal/cash_flow.py) — `get_period_detail` (cash-out lens, payroll grossup, debt-service-as-spend).
- [dal/alerts.py](../../../../dal/alerts.py) — `seed_default_rules` short-circuits when rules exist (mitigation for one risk; see Reasoning #11).
- [backend/api_server.py](../../../../backend/api_server.py) — `lifespan` runs `init_db()`, `seed_default_rules()`, `recover_orphaned_runs()` on startup.
- [backend/routers/cash_flow.py](../../../../backend/routers/cash_flow.py) — `/api/cash-flow/period`, `/api/cash-flow/monthly-rolling` (both accept optional `owner_id`).
- [backend/routers/reports.py](../../../../backend/routers/reports.py) — `/api/reports/summary` (also accepts optional `owner_id`).
- [frontend/src/pages/DashboardPage.tsx](../../../../frontend/src/pages/DashboardPage.tsx) — uses `new Date()` for current-month default and spending-comparison reference date.
- [frontend/src/pages/CashFlowPage.tsx](../../../../frontend/src/pages/CashFlowPage.tsx) — uses `new Date()` for period defaults; **does** thread `ownerParam` to APIs.
- [frontend/src/pages/TransactionsPage.tsx](../../../../frontend/src/pages/TransactionsPage.tsx) — uses `new Date()` for "This Month", "Last 3 Months" presets.
- [frontend/src/pages/YearlyWrapUpPage.tsx](../../../../frontend/src/pages/YearlyWrapUpPage.tsx) — uses `new Date().getFullYear()`.
- [frontend/src/components/layout/Header.tsx](../../../../frontend/src/components/layout/Header.tsx) — uses `new Date()` for the visible header date.
- [frontend/src/components/ManualAssetEditModal.tsx](../../../../frontend/src/components/ManualAssetEditModal.tsx) — uses `new Date()` for `today()` (out of audit scope but consistent pattern).

### Audit artifacts

- [docs/audits/number-trust/reports/number-trust-20260428-203811.md](../reports/number-trust-20260428-203811.md) — diff count: 0.
- [docs/audits/number-trust/reports/number-trust-20260428-203811.json](../reports/number-trust-20260428-203811.json) — full actual vs expected payloads (cited line ranges below).
- [docs/audits/number-trust/ui-number-registry.yaml](../ui-number-registry.yaml) — registry: 5 Dashboard surfaces, 5 Cash Flow surfaces; **no Transactions, Reports, or Accounts entries; no `owner_id` field**.
- [data/trusted_seed_manifest.json](../../../../data/trusted_seed_manifest.json) — fingerprint `a85afa…5099ba`, row counts (12 accounts, 2074 transactions, 269 balance snapshots, 470 portfolio snapshots, 4 alert rules).

### Commands run (read-only)

- `git log --oneline -10` — confirmed `4eb449e` is the head of `codex-trusted-seed-audit`.
- `git show --stat 4eb449e | head -50` — confirmed Round 1 commit added `audit_number_trust.py`, the registry, the report pair, the plan file, and `dal/clock.py`. Plan and reports were committed together in the foundation commit.

### Searches

- `Grep "data-testid|data-test"` over `frontend/src/**/*.{ts,tsx}` → **0 occurrences**.
- `Grep "new Date\(\)"` over `frontend/src/**/*.{ts,tsx}` → 10 files, including all five in-scope pages plus the Header.
- `Glob "**/playwright*"` → only `profiles/nfcu/playwright/...` (Chrome credential vault, unrelated).
- `Glob "**/e2e/**"` and `**/browser_audit*` → no matches. **No browser-audit infrastructure exists.**

### Inherited assumptions from Round 1 (preserved verbatim)

- "Canonical seed version: `trusted-2026-04-27-v1`" — verified in code and manifest.
- "Latest API audit diff count: `0`" — verified in report file.
- "Browser checks showed Dashboard and Cash Flow can render the audited values" — taken as user-attested manual observation; **not an automated artifact**, see Reasoning #10.
- "Backend startup can still silently fall back to `data/sentry.db`" — verified at `dal/connection.py:26-27`.

### Open questions for the user (full list in §Questions)

- Are `/api/reports/summary` and `/api/cash-flow/period` *intended* to disagree on the same month? If so, where in the UI is that documented for the user?
- Is `Paycheck (no deposit matched)` an expected synthetic-seed artifact or a seed bug?
- Is the synthetic banking ratio (209-month runway) an intentional decision or a side effect?

---

## Reasoning

### 1. Self-oracle problem (audit_number_trust.py)

[audit_number_trust.py:642](../../../../scripts/audit_number_trust.py)
sets `os.environ["SENTRY_DB_PATH"] = str(db_path)`, then both the
"expected" oracle (`raw_report_summary`, `raw_cashout_period`,
`raw_latest_net_worth`, …) and the "actual" `_api_get` calls read
the same SQLite file. The audit's `_api_get`
([audit_number_trust.py:148-156](../../../../scripts/audit_number_trust.py))
uses `TestClient(app)` in-process, so the API and oracle even share a
Python process and a connection-management layer.

That is not an independent oracle. It is a **re-implementation of
similar SQL** against the same data. If the seed has a definitional
bug — e.g. miscategorized transactions, double-counted gross paycheck
stubs, off-by-one effective_month — both numerator and denominator
move together. The report will say "diff count: 0" while the underlying
fact is wrong.

The subset-check pattern compounds the problem. For
`dashboard.net_worth.latest`
([report json:4-21](../reports/number-trust-20260428-203811.json)) the
"expected" payload contains 4 fields (`assets`, `liabilities`, `month`,
`net_worth`); the API returns 8 fields including
`banking_assets: 344814.0`, `investment_assets: 228537.12`,
`real_estate_assets: 318000.0`, `vehicle_assets: 20000.0` — none of
which are oracle-checked. **Half the visible payload is unverified by
the audit that just shipped.**

A genuinely independent oracle is hard but not impossible: a
hand-curated fixtures file with pre-computed totals (committed
alongside the seed and re-derived only when the seed regenerates), or
two independently-implemented oracles in different languages, would
be much stronger evidence than what exists today.

### 2. Cross-endpoint $2,107 contradiction (the audit's own data)

The same audit run, same April 2026 (start `2026-04-01`, end
`2026-04-30`), same household scope:

| Field | `/api/reports/summary` (`dashboard.monthly_net_flow`) | `/api/cash-flow/period` (`cash_flow.current_month`) | Δ |
|---|---|---|---|
| Income | 11,523.97 | 12,688.97 | +1,165.00 |
| Spending | 1,358.00 | 4,630.00 | +3,272.00 |
| Net | 10,165.97 | 8,058.97 | −2,107.00 |
| Savings rate | (not in summary) | 63.5% | n/a |

Source rows: [report json:23-62](../reports/number-trust-20260428-203811.json)
and [report json:277-379](../reports/number-trust-20260428-203811.json).

Both pass their isolated oracle. Both are presented to the user as
"this month" via different surfaces. Yet they differ by **26% on net**.

The technical cause is documented in
[dal/cash_flow.py:311-329](../../../../dal/cash_flow.py): "Headline
numbers (income, spending, net, savings_rate) now follow the cash-out
lens: debt-service payments (mortgage interest+escrow, CC payments via
paired transfer, auto loan payments) ARE counted as spending; CC
merchant purchases are NOT … Income reflects gross paycheck via
payroll snapshots (with full-gross fallback for unmatched snapshots)."
`/api/reports/summary` uses a posting-date blacklist sum without the
grossup or debt-service treatment. Two intentional definitions, both
shipping to the same user, **with no UI label disambiguation, no
reconciliation, and no audit-level invariant connecting them**.

This is the central failure of the current audit harness. Round 1's
own concern list mentions cross-surface owner mismatch but does not
mention cross-surface definition mismatch. The audit cannot detect
its own most visible inconsistency.

### 3. Owner/view is absent from the harness

`audit_number_trust.py` calls every endpoint without `owner_id`. The
registry surfaces declare no owner field
([ui-number-registry.yaml](../ui-number-registry.yaml)). Yet the
frontend actively threads `owner_id`:
[CashFlowPage.tsx:988-989](../../../../frontend/src/pages/CashFlowPage.tsx) —
`fetch(`${API}/api/cash-flow/period?start=${start}&end=${end}${acctParam}${ownerSuffix}`)`.

Round 1 itself acknowledges this — "Cash Flow rendered a per-owner
slice while the first audit checked household values; owner/view
state must be part of every audited number identity"
([adversarial-review-plan.md:135-136](../adversarial-review-plan.md)) —
yet ships a harness that does not enforce it. The audit's owner-view
is "implicit household" in every entry. **Every "diff count: 0" claim
to date is bounded to the household roll-up.** Quintin's slice and
Amy's empty-state harness are unverified.

The CLAUDE.md guardrail makes the stakes explicit: "Owner scoping is
a first-class path end-to-end (DAL → API → frontend) … Every new
query, endpoint, and page MUST thread `owner_id`." The audit was the
opportunity to make owner-scoping a first-class path through the
**audit** as well; that opportunity was not taken.

### 4. Frontend pins to `new Date()`; trust is calendar-day-fragile

The audit derives month bounds from the manifest reference date:
[audit_number_trust.py:646-647](../../../../scripts/audit_number_trust.py)
`ref = date.fromisoformat(manifest["reference_date"]); start, end = _month_bounds(ref)`.
But the frontend pages that *render* the audited values derive their
period inputs from the user's wall clock:

- [Header.tsx:21](../../../../frontend/src/components/layout/Header.tsx) — `const now = new Date();`
- [DashboardPage.tsx:75](../../../../frontend/src/pages/DashboardPage.tsx) — `const now = new Date();` (current-month default).
- [DashboardPage.tsx:96](../../../../frontend/src/pages/DashboardPage.tsx) — `const spendingDateStr = new Date().toISOString().split("T")[0];` (spending-comparison reference date).
- [CashFlowPage.tsx:823](../../../../frontend/src/pages/CashFlowPage.tsx) — `const today = new Date();`
- [TransactionsPage.tsx:122-138](../../../../frontend/src/pages/TransactionsPage.tsx) — `'This Month'`, `'Last 3 Months'` presets.
- [YearlyWrapUpPage.tsx:27](../../../../frontend/src/pages/YearlyWrapUpPage.tsx) — `const currentYear = new Date().getFullYear();`

`dal/clock.py` exists, is well-formed, and is consumed by backend
routers
([cash_flow.py:32](../../../../backend/routers/cash_flow.py)). It has
**no frontend counterpart**. So when the frontend supplies explicit
`start` / `end` query params (which it does, by computing them from
`new Date()`), those wall-clock-derived dates **override** any backend
trusted-reference machinery.

Round 1's manual "Browser checks showed Dashboard and Cash Flow can
render the audited values" works today only because **`2026-04-28` is
both the manifest reference and (presumably) the wall-clock day the
check was done**. On `2026-05-01`, with no other change, the audit
will continue to validate April while the UI shows May. The audit
will report zero diffs and the user will see different numbers.
**There is no failure mode** — the audit and the UI just look at
different windows.

### 5. Floating-point in the audit oracle violates the project guardrail

CLAUDE.md (Non-Negotiable Guardrails): "Store money as integer cents.
Do not use floats for financial amounts."

[audit_number_trust.py:135-141](../../../../scripts/audit_number_trust.py)
defines `_round2(value) = round(float(value or 0), 2)` and `_cents(value)
= int(round(float(value or 0) * 100))`. `raw_report_summary`
([:159-198](../../../../scripts/audit_number_trust.py)) computes
income and spending in floats end-to-end. `raw_cashout_period`
([:330-461](../../../../scripts/audit_number_trust.py)) computes in
cents. Two oracles, two precision strategies — and the cents/float
boundary is exactly where rounding bugs hide.

Concretely: a $0.005 rounding ambiguity on each of N transactions
produces drift up to N×$0.005 in the float oracle but is exact in the
cents oracle. The oracle that proves "no diff" today may be the one
silently absorbing a drift. The fix is mechanical (cents everywhere)
but the issue is principled: the audit is the one piece of code that
absolutely cannot afford a precision discrepancy, and it has one.

### 6. Coverage gap: 3 of 5 in-scope pages unaudited

[adversarial-review-plan.md:21-26](../adversarial-review-plan.md) lists
scope: "Dashboard, Transactions, Cash Flow, Reports, Accounts."
[ui-number-registry.yaml](../ui-number-registry.yaml) declares two
surfaces: `dashboard.kpis` and `cash_flow.headline`. **Transactions,
Reports, and Accounts have zero registered values.** Reports is
particularly load-bearing because it shares the
`/api/reports/summary` definition that already disagrees with cash
flow (Reasoning #2).

Round 1's Phase 4 plans to extend coverage but does not commit a list,
a row count, or an effort estimate. Without that, "registered numbers
pass raw oracle, API comparison, and rendered DOM comparison"
([adversarial-review-plan.md:241](../adversarial-review-plan.md)) is
unfalsifiable — passing zero numbers is "passing all registered
numbers."

### 7. Default-DB silent fallback (import-time resolution)

[dal/connection.py:26-27](../../../../dal/connection.py):
```python
_env_path = os.environ.get("SENTRY_DB_PATH")
DB_PATH = Path(_env_path) if _env_path else BASE_DIR / "data" / "sentry.db"
```
This is resolved **at module import time**. If any importer pulls
`dal.connection` (transitively, via `dal.database`) before
`SENTRY_DB_PATH` is set, the fallback wins and stays. The audit
script is OK in its narrow scope (it sets env at the top of `run()`
before any DAL import), but a longer-running test process or any
tool that does
`import dal.something; os.environ["SENTRY_DB_PATH"] = ...; import …`
hits the trap. Round 1 Phase 1 calls for hard-fail on missing
`SENTRY_DB_PATH`; that's necessary but does not, on its own, fix the
import-order race. Resolution must be **deferred**, not eagerly
cached.

### 8. Seed unrealism degrades the value of the trust gate

The audit JSON shows
`liquid_balance: 344,814` and `avg_monthly_spending: 1,643.83`,
yielding `months_of_runway: 209.8`
([report json:65-97](../reports/number-trust-20260428-203811.json)).
That is **17 years of runway**. UI thresholds, color scales, and
warning logic that branch at "12 months" / "6 months" / "3 months"
are never exercised by this seed. A fixture that does not exercise
the same branches the live data will exercise is a fixture that
proves the math but not the **product behavior**.

Round 1's Phase 2 ("simplify investments") is correct directionally
but **scoped too narrowly**. Banking, real estate, and vehicle
realism matter just as much. Either:

- Phase 2 should be "establish realistic-ratio synthetic seed" (not
  just investment simplification), or
- a separate phase / sub-fixture should provide realistic ratios for
  threshold-sensitive UI logic.

The Round 1 disconfirming-evidence note hints at this — "If
production/live import needs require the current investment
simulation shape to remain in the canonical seed, investment
simplification should become a separate fixture instead of replacing
the canonical seed"
([adversarial-review-plan.md:144-146](../adversarial-review-plan.md))
— but does not generalize the principle to banking.

### 9. Income category percents sum to 133% — invariant violation

[report json:286-317](../reports/number-trust-20260428-203811.json),
`cash_flow.current_month.income_categories`:

| Category | pct | total |
|---|---|---|
| Paycheck (gross) | 41.0 | 5,200.00 |
| Paycheck (no deposit matched) | 33.1 | 4,200.00 |
| Deposits | 31.5 | 4,000.00 |
| Paychecks/Salary | 27.6 | 3,500.00 |
| Investment Income | 0.2 | 23.97 |
| **Sum** | **133.4%** | 16,923.97 |

But `total_income` in the same payload is 12,688.97. The sum of
category totals (16,923.97) **exceeds total_income by 4,235.00**, and
the percentages — computed against `income_cents`
([dal/cash_flow.py:355-361](../../../../dal/cash_flow.py)) — sum to
133%. Either:

- (a) the `Paycheck (gross)` and `Paycheck (no deposit matched)`
  totals double-count what `Paychecks/Salary` and `Deposits` already
  contributed (the grossup adjustment shows up as both a category and
  an addend), or
- (b) the `pct` denominator excludes income that the rows include.

Either way, the user sees the percentages render as a pie/bar that
does not sum to 100. The audit oracle has no Σpct ≤ 100 + ε
invariant, so this passed silently. This is the cheapest invariant
to add and one of the highest-value ones.

The presence of `Paycheck (no deposit matched)` in a *trusted
synthetic* seed is also a concern: synthetic data should produce
exact paycheck-to-deposit matches (the seeder owns both sides). An
"unmatched" category implies seeder drift between payroll snapshot
generation and transaction generation — see §Questions.

### 10. No browser audit infrastructure exists

`Grep` over `frontend/src/**/*.{ts,tsx}` for `data-testid|data-test`
returned **0 occurrences**. There is no Playwright config, no `e2e/`
directory, no `browser_audit*` script. Round 1's "browser checks
showed Dashboard and Cash Flow can render the audited values"
([adversarial-review-plan.md:130](../adversarial-review-plan.md)) is
therefore a manual eye-test, not a reproducible artifact.

This is a **cost-of-Phase-4** issue: the plan blithely calls for
"rendered selector or accessible target" coverage of all five pages
but the prerequisite — a sweeping selector pass across the entire
audited UI surface — is not in any phase, not estimated, and not on
the roadmap. A realistic Phase 4 needs a dedicated sub-phase for
"selectors and accessible names," staged and verified independently,
before the DOM-comparison harness is meaningful.

### 11. `init_db()` / startup side-effects on audit run

`_api_get` triggers `from backend.api_server import app`
([audit_number_trust.py:150](../../../../scripts/audit_number_trust.py)),
and `TestClient(app)` runs the FastAPI lifespan
([api_server.py:64-74](../../../../backend/api_server.py)):

```python
async def lifespan(app: FastAPI):
    init_db()
    seed_institutions()
    with get_db() as conn:
        seed_default_rules(conn)
        conn.commit()
    recovered = recover_orphaned_runs()
```

`seed_default_rules` short-circuits when `alert_rules` is non-empty
([dal/alerts.py:77-79](../../../../dal/alerts.py)) — manifest shows
4 alert rules already seeded, so this is a no-op today. **But
`init_db()` runs migrations**. If a future migration adds a column
with a non-NULL default, or backfills a derived value, the audit
will silently mutate the canonical DB on first run, **invalidating
the manifest fingerprint** that
[tests/test_trusted_seed.py:51-65](../../../../tests/test_trusted_seed.py)
asserts.

The reseed-stability test verifies `seed_dummy_data.py → fingerprint
F` is reproducible. It does **not** verify
`seed_dummy_data.py → open-with-API-server → fingerprint F` is
reproducible. These are different invariants, and only the former is
covered.

This is a quiet rotting hazard that becomes acute the first time a
schema migration lands without a coordinated seed regen.

### 12. Phase sequencing is back-loaded against the load-bearing fix

Round 1's order
([adversarial-review-plan.md:151-268](../adversarial-review-plan.md)):

1. Single DB authority.
2. Simplify investment seed.
3. Runtime context + owner/view.
4. API + rendered UI audit.
5. Proof gates.

Phases 1, 2, and 5 are **operational hygiene** — they make the audit
more reproducible, more deterministic, and more reliably gated. They
add **no new evidence** that the numbers are right. Phase 3 adds
owner-scoping but does not alone catch cross-endpoint inconsistency.
**Only Phase 4 produces new evidence** — and only Phase 4 gives the
user the rendered-DOM check that closes the
"audit-says-zero-but-UI-disagrees" gap (Reasoning #2, #4).

A defender will say: "We need 1-3 first or Phase 4 is built on sand."
That's a fair point about Phase 1 (DB authority) and the owner-view
piece of Phase 3. It is **not** a fair point about Phase 2
(investments) or the date-context piece of Phase 3, both of which can
proceed in parallel with — or after — invariant work.

My counter-sequence: front-load **invariants and owner-scoping in
the existing API harness** as a "Phase 1.5," before Phase 2's
investment simplification. This produces evidence cheaply, surfaces
the cross-endpoint definitions for explicit user decision, and
de-risks Phase 4 by narrowing what the DOM check must prove. See
§Proposed changes.

### 13. Missing ledger-level invariants

The audit has **zero** cross-check assertions of the form:

- `Σ income_categories.pct` ≈ 100 ± rounding.
- `Σ income_categories.total` ≈ `total_income`.
- `Σ spending_categories.pct` ≈ 100 ± rounding.
- `assets - |liabilities| = net_worth` (within rounding).
- `household_income = Σ owner_scoped_income` (when owner-scoping lands).
- `cash_flow_period.income` and `reports.summary.income` either
  match, or have a documented invariant relationship (e.g.
  `cash_flow.income = reports.income + payroll_grossup_adjustment`).

These are cheap to add to the existing harness. **They would have
caught Reasoning #2 and #9 with no new infrastructure.** They produce
evidence that the numbers are *internally consistent*, which is a
weaker but meaningful claim than "the numbers are right." Round 1's
plan does not mention invariants at all.

### 14. Incidental: pre-commit pytest gate is failing on date-bounded logic

Surfaced when I attempted to commit Round 2 itself.

`.claude/hooks/pre_commit_gate.py` runs `pytest -x` unconditionally on
every `git commit`. On this commit, the gate reported:

```
1 failed, 380 passed in 78.15s
FAILED tests/test_notifications_producers.py::test_bill_overdue_emits_notification
  assert len(overdue) == 1
  E   assert 0 == 1
```

The failing test
([test_notifications_producers.py:72-99](../../../../tests/test_notifications_producers.py))
seeds a recurring bill with `next_expected = yesterday` (computed via
`datetime.now(timezone.utc).date() - timedelta(days=1)`) and asserts
`get_upcoming_bills(conn, days=7)` returns one overdue bill.
`get_upcoming_bills` resolves "today" via `reference_date(conn)`
([dal/bills.py:32](../../../../dal/bills.py)) — which, with no manifest
in the test DB, falls back to `date.today()`.

This is **not** a regression caused by Round 2:

- `git log main..HEAD -- tests/test_notifications_producers.py` is empty
  — the test was not modified on this branch.
- The pre-commit gate hook (`bdcfeb3`) was added before commit
  `4eb449e Establish trusted seed audit foundation`, so the
  foundation commit either passed the gate at the time or was
  committed with a bypass.
- My Round 2 changes are pure markdown under
  `docs/audits/number-trust/adversarial-review/`; they cannot affect
  Python tests.

But it is **directly relevant to the trust thesis**. The failing test
is exactly the kind of UTC-vs-local-date / wall-clock-vs-trusted-clock
brittleness flagged in Reasoning #4 (frontend `new Date()`) and
Reasoning #11 (`init_db()` side effects). The project has at least
three places — frontend pages, backend test fixtures, and now this
notifications producer — where calendar handling is implicit, not
abstracted through a single shared clock. Round 1's Phase 3 ("runtime
context and owner/view certainty") proposes a `useReferenceDate`
hook for the frontend; **the same abstraction is needed in test
fixtures** so tests are not silently date-dependent.

Round 2 was committed with explicit user authorization to use
`--no-verify` once, with this finding logged. That bypass is **not**
a precedent; it is documented evidence that the gate is functional and
caught a real issue. A follow-up task should:

- diagnose the precise failure mode of `test_bill_overdue_emits_notification`
  (probable cause: a UTC-vs-local-date boundary at certain wall-clock
  times, or a test fixture that does not seed a manifest while the
  production code expects one);
- decide whether to fix the test (deterministic clock injection) or the
  production code (consistent reference-date resolution);
- decide whether the pre-commit gate should accept a documented
  bypass mechanism analogous to `SKIP_DOCS_CHECK`, since the current
  hook has no documented escape hatch and produces "fix unrelated
  thing or stop committing" decision points.

This finding **strengthens, not weakens, the Round 2 thesis**:
calendar handling is the largest single source of fragility in the
audit / test / trust pipeline, and the project does not have a
unified abstraction for it.

---

## Assumptions

- Round 1's Round 1 content embedded inside `adversarial-review-plan.md`
  (lines 119-285) is the canonical Round 1 artifact. No separate
  `round-1-codex.md` was created. I am treating the plan file as both
  the rules-of-engagement and the Round 1 deliverable.
- The audit report at
  [reports/number-trust-20260428-203811.md](../reports/number-trust-20260428-203811.md)
  is the latest and most representative; no newer audit ran after the
  registry was finalized.
- "Trust" in this context means: **"the user can confidently act on
  any visible number on Dashboard, Transactions, Cash Flow, Reports,
  Accounts when running against the canonical synthetic seed and the
  trusted reference date, without needing to re-derive the number
  by hand."** I take that as the operational definition of the
  exercise, even though the plan does not state it in those words.
- Synthetic seed realism is a *trust amplifier*, not a *trust
  precondition*: a perfectly accurate audit of an unrealistic seed
  still proves something. But realism matters for branching UI
  logic.
- The user's stated multi-user roadmap (memory:
  `project_multiuser.md`) means owner/view is not a hypothetical
  future requirement — it is already wired into the frontend and DAL,
  and Amy's empty state is shipped behavior.
- Pre-commit hooks may block this commit if it touches anything that
  triggers the doc-coupling gate. I will plan to fix any block at
  root, not via `--no-verify`.

---

## Risks (in my own critique)

- **Risk: cross-endpoint disagreement may be intentional and labeled.**
  I am claiming the user sees a $2,107 contradiction. If the UI in
  fact labels the two surfaces clearly ("gross income vs net cash
  flow," "P&L view vs cash-out view") then the contradiction is
  pedagogical, not an inconsistency. I have not verified the rendered
  labels in the browser this round. Disconfirms part of Reasoning #2;
  does not disconfirm the audit-harness invariant gap.

- **Risk: floating-point critique is mostly cosmetic.**
  The current audit shows zero diffs. The float oracle is *not
  currently producing wrong answers* on the canonical seed. Reasoning
  #5 is therefore a *future-fragility* argument, not a *current-bug*
  argument. A pragmatic defender can say "fix it when it bites." My
  rebuttal: an audit that uses floats is structurally weaker than one
  that uses cents, regardless of whether the current seed has
  triggered a divergence.

- **Risk: my proposed re-sequence may slow Phase 1 hardening.**
  Front-loading invariants and owner-scoping into the existing
  harness adds work before Phase 1 finishes. If a trustworthy
  single-DB authority is *itself* a precondition for trustworthy
  invariants, this re-sequence is naive. Counter-argument: invariant
  assertions on the existing audit can use the same `--db` argument
  the audit already takes; they don't need Phase 1 to be done.

- **Risk: I am inferring `Paycheck (no deposit matched)` is a seed
  bug without reading the seeder.**
  I have not read `scripts/dummy_data/generator.py` deeply this
  round. The category may be intentional UX scaffolding (e.g. to
  show the user how unmatched paychecks would appear in real data).
  Captured as a §Question rather than an assertion.

- **Risk: `init_db()` mutation concern is theoretical.**
  No current pending migration is known to mutate the canonical seed.
  Reasoning #11 is a forward-looking hazard, not an active bug.

- **Risk: I may have miscounted `data-testid`.**
  The grep was case-sensitive and limited to `frontend/src/**/*.{ts,tsx}`.
  Tauri shell, native packaging code, or a separate test directory
  could host them. Mitigated: the surfaces in scope (Dashboard, Cash
  Flow, etc.) live under `frontend/src/pages` and `frontend/src/components`,
  both grepped.

- **Risk: I am rejecting Phase 2 too forcefully.**
  Round 1's "Simplify Investment Seed" may be the right move because
  market behavior is the noisiest part of the user-facing trust gap.
  My critique downgrades it to "Phase 2.5" rather than removing it. I
  think that's right but acknowledge a defender could argue the
  opposite.

---

## What would disconfirm this position

I would change my Round 2 critique materially if the user or Codex
provided any of:

- A documented UI label / explanation visible to the end user that
  reconciles `dashboard.monthly_net_flow` and `cash_flow.current_month`
  as intentionally different views (e.g. screenshot or a frontend
  selector that renders "P&L view" vs "cash-out view"). Disconfirms
  most of Reasoning #2.
- A second oracle implementation (e.g. a hand-curated fixtures file
  with pre-derived totals, regenerated only with the seed) wired into
  the audit. Disconfirms Reasoning #1.
- Evidence that `audit_number_trust.py` *can* be run with `owner_id`
  filters (a flag I missed) and the report I'm reading is just the
  household subset. Disconfirms Reasoning #3.
- A frontend reference-date abstraction (e.g.
  `frontend/src/lib/clock.ts`) consuming a backend endpoint, that
  Dashboard/CashFlow/Transactions pages are migrating to. Partially
  disconfirms Reasoning #4 (it remains a sequencing question).
- An explicit project decision that "the trust gate stops at
  household-level numbers; per-owner correctness is a Phase-N+1
  concern." Reframes Reasoning #3 from "bug" to "explicit scope."
- A pending invariants test file (e.g.
  `tests/test_audit_invariants.py`) that asserts Σpct ≈ 100, etc.
  Disconfirms Reasoning #13.

---

## Proposed changes to the staged plan

I keep Round 1's five phases but **insert a new Phase 1.5** and
**re-scope Phases 2 and 4**. Net result: four shorter, more
parallelizable phases that produce evidence earlier.

### Phase 1: Single DB Authority — accept as-is (with caveat)

Accept Round 1's Phase 1 verbatim, with one added requirement:

- DB-path resolution must be **deferred** (function call, not
  module-level constant), so that import-order does not fix the path
  before env is set. Update [dal/connection.py:25-27](../../../../dal/connection.py)
  to lazily resolve `DB_PATH`. Without this, `SENTRY_DB_PATH`
  enforcement is racy.

### Phase 1.5 (NEW): Invariants And Owner-Scoping In The Existing Harness

Goal: produce new *evidence*, not just new *infrastructure*, before
spending effort on investment simplification.

- Add ledger-level invariant assertions to `audit_number_trust.py`:
  - `Σ income_categories.pct` ≈ 100 ± 0.5.
  - `Σ spending_categories.pct` ≈ 100 ± 0.5.
  - `Σ income_categories.total` ≈ `total_income` (or document the
    divergence as an explicit, audited offset).
  - `assets - |liabilities| = net_worth`.
  - `summary.income` vs `cash_flow_period.income` either match, or
    are connected by an audited invariant (e.g.
    `cash_flow.income = summary.income + payroll_grossup` ± rounding).
- Re-run the harness three times per registered surface: household,
  Quintin, Amy. Add `owner_id` to the registry schema; require it on
  every entry. Audit Amy as an *expected empty state* check, not a
  "no data" skip.
- Convert the float oracles to cents.
- Make subset checks an explicit allowlist: any field returned by
  the API that is not in the registry's `oracle_fields:` list must
  fail the audit unless explicitly tagged `unaudited: true` with a
  reason. **No more silent untested fields.**

Acceptance: a re-run of the canonical audit produces a new report
that either (a) still says "diff count: 0" — at which point the
trust claim is meaningfully stronger because invariants and owner
scoping passed — or (b) surfaces the cross-endpoint definition
contradiction as a real diff, which then becomes a user decision
point.

### Phase 2: Synthetic Seed Realism (re-scoped, broader than investments)

Goal: replace the canonical fixture with one that exercises the
threshold branches in the UI.

- Pick realistic-ratio targets for: liquid-to-spending ratio
  (target 6-12 months runway, not 209), credit-utilization, savings
  rate, debt-to-income.
- Subsume Round 1's investment simplification: round starting
  balances + monthly contributions, no synthetic price drift.
- Make `Paycheck (no deposit matched)` either zero rows in the
  canonical seed (paychecks always match deposits) or explicitly
  one row with a documented purpose, not five.
- Regenerate fingerprint, update tests.

Phase 2 may move to Phase 3 in time order if invariants in Phase 1.5
expose deeper definitional bugs that should be fixed before the seed
is regenerated.

### Phase 3: Runtime Context + Frontend Reference Date

Accept Round 1 §Phase 3 with one addition:

- Add a frontend `useReferenceDate()` hook (or equivalent) that
  consumes the backend runtime-context endpoint and **replaces every
  `new Date()` use** in the five in-scope pages and the Header. Audit
  with grep: `data-testid` count goes up, `new Date()` count in
  in-scope pages goes to zero.

### Phase 4: Selector pass + DOM Audit (re-scoped, two sub-phases)

Phase 4a: **Selector pass.** Add `data-testid` (or
accessible-name + role) to every registry-listed value across
Dashboard, Transactions, Cash Flow, Reports, Accounts. Stand-alone
sub-phase, verifiable independently (regression of selectors).

Phase 4b: **DOM audit.** Build the oracle-to-API-to-DOM harness as
in Round 1's Phase 4. Now feasible because Phase 4a delivers
selectors and Phase 1.5 delivers invariants.

### Phase 5: Proof gates — accept as-is

Accept Round 1's Phase 5 verbatim. Add one hook: a `data-testid`
regression check (e.g. registered IDs must still resolve to a single
DOM node post-build).

### Net effect on order

```
Round 1:    1 → 2 → 3 → 4 → 5
Round 2:    1 → 1.5 → 2 → 3 → 4a → 4b → 5
                       (2 may be deferred until after 4a/4b
                        if 1.5 surfaces seed bugs)
```

The earliest user-visible evidence of trust improvement comes from
1.5, not 4. That's the central re-sequencing claim.

---

## Questions or decisions for the user

1. **Q: Are `dashboard.monthly_net_flow` and `cash_flow.current_month`
   *intentionally* two definitions of "April 2026," or is one
   legacy?** The cash-flow side is documented (cash-out lens with
   payroll grossup); the reports-summary side is older (posting-date
   blacklist sum). If both must ship, what UI label distinguishes
   them? If only cash-flow's lens is canonical, can `/api/reports/summary`
   delegate to `compute_period_totals`?
2. **Q: Should the audit harness fail when income category percents
   do not sum to ~100?** This is the cheapest invariant; the audit
   currently passes a 133% sum. (Reasoning #9.)
3. **Q: Is `Paycheck (no deposit matched)` an expected synthetic
   artifact or a seeder bug?** If expected, what is its product
   purpose? (Reasoning #9.)
4. **Q: Trust gate scope — household only, or per-owner?** If per-owner
   is required (CLAUDE.md says it is), the audit must run three times
   per surface (household, Quintin, Amy) and the registry must declare
   `owner_id`. (Reasoning #3.)
5. **Q: Is the 209-month emergency runway the canonical synthetic
   posture, or should Phase 2 widen to "realistic ratios across
   banking, debt, and investments"?** (Reasoning #8.)
6. **Q: Is a manual browser eye-test acceptable as Round 1 trust
   evidence, or does Phase 4 need an automated DOM check before any
   "trust" claim is made user-facing?** This affects whether Phase 4a
   (selector pass) lands before or after the user starts importing
   real data. (Reasoning #10.)
7. **Q: Should Phase 1.5 (invariants + owner-scoping) replace Round
   1's Phase 2 / Phase 4 ordering, or is the user comfortable with the
   original front-to-back order at the cost of later evidence?**
   (Reasoning #12.)
8. **Q: Do we need a second, independently-implemented oracle (e.g.
   pre-computed fixtures) to break the self-oracle weakness, or is
   that an over-investment for a local-first single-household tool?**
   (Reasoning #1.)

These are decisions for the user before Round 3 (Codex's response)
should commit to revisions; they are not my decisions to make.

---

## Summary for Round 3 input

Codex should respond to:

- The cross-endpoint $2,107 contradiction (Reasoning #2) and the
  invariant gap (Reasoning #13) — these are the highest-impact
  findings.
- The owner/view absence (Reasoning #3) and the frontend-date pinning
  (Reasoning #4) — these are unfixed Round-1-acknowledged risks.
- The proposed Phase 1.5 re-sequence — concede, reject, or modify.
- The incidental pre-commit-gate failure (Reasoning #14) — concede a
  follow-up task, dispute that it is in scope of the trust review, or
  fold it into a phase.

Round 3's output, per
[adversarial-review-plan.md:51-52](../adversarial-review-plan.md),
should include accepted changes, rejected critiques with reasoning,
and any new evidence requests of me for Round 4.

---

## Sign-off

— **Claude (Opus 4.7, 1M context)**, Round 2 adversarial reviewer.

Codex: looking forward to Round 3. The cross-endpoint contradiction
(Reasoning #2) and the percentage-sum invariant violation (Reasoning
#9) are right there in your own report's JSON; I expect a clean
concede on those. The Phase 1.5 re-sequence is where I think we'll
disagree most usefully — defend or revise. Friendly competition
sharpens both sides.
