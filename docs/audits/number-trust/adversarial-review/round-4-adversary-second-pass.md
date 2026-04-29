# Round 4: Second Adversarial Critique

Reviewer: **Claude (Opus 4.7, 1M context)**, second adversarial pass
per [adversarial-review-plan.md](../adversarial-review-plan.md) §Round 4.
Date: 2026-04-28.
Branch: `codex-trusted-seed-audit`.
Round 3 commit under review: Codex's `round-3-codex-response.md`
(written on top of Round 2 commit `ca286f6`).

---

Supersession note: this historical round cited an earlier promoted audit
report, which has been replaced by the single retained promoted report
`number-trust-20260429-124043`. Current facts live in
[shared-evidence.md](shared-evidence.md).

## Position

Codex conceded most of the Round 2 critique cleanly and the revised
plan is meaningfully stronger. The Phase 1 → 1.5 → 2 → 3 → 4a → 4b → 5
sequence is the right shape. The layered proof model (A through F)
is the right framing. The owner/view + invariants + cents-first work
in Phase 1.5 produces evidence early, which was the load-bearing
sequencing complaint.

But a deeper code-scour during Round 4 turned up evidence that
**reframes one of the central decisions** and surfaces three
concrete blind spots Round 3 doesn't address. Specifically:

1. The cross-endpoint $2,107 contradiction is **NOT** "two
   intentional lenses." It's a partially-completed migration. The
   project has a canonical aggregator (`compute_period_totals` in
   [dal/flow_aggregation.py](../../../../dal/flow_aggregation.py))
   that Cash Flow and Sankey already consume; the Reports summary
   endpoint simply wasn't migrated. **Codex's "decompose into named
   offsets OR delegate" framing should commit to the delegation
   path** — the codebase already decided which lens is canonical.
2. The audit script's hardcoded category sets violate
   [dal/category_classifications.py](../../../../dal/category_classifications.py)'s
   own "single source of truth" rule. The audit should import these
   sets, not redefine them.
3. **Investments is officially out of scope but Phase 2 reshapes
   investment seed data**. That's an internal contradiction in the
   plan: Phase 2 changes data that no audit covers.

These are not theoretical blind spots; they are missed evidence
already present in the repo. Round 5 should fold them into the final
synthesis.

The remainder of this document concedes where Codex is right (most
of it), pushes harder where the plan is still under-specified, and
answers Codex's five Round-4 questions directly.

---

## Evidence used

### New repo paths inspected (Round 4)

- [dal/category_classifications.py](../../../../dal/category_classifications.py) — declares itself the single source of truth (line 4-5: "Every module in the DAL that needs to classify transactions … MUST import from here. Do NOT define local copies.").
- [dal/flow_aggregation.py:1-77](../../../../dal/flow_aggregation.py) — explicitly documents that the pre-PR1 income/spending split between Cash Flow and Reports endpoints was a known bug, fixed by exposing `compute_period_totals` as a unified aggregator both pages "will consume in PR2."
- [dal/reports/spending.py:156-200](../../../../dal/reports/spending.py) — `get_period_summary`, the function backing `/api/reports/summary`. Does **not** call `compute_period_totals`; uses the legacy posting-date blacklist sum.
- [dal/cash_flow.py:330-337](../../../../dal/cash_flow.py) — `get_period_detail`, the function backing `/api/cash-flow/period`. **Does** call `compute_period_totals` (`from dal.flow_aggregation import compute_period_totals`).
- [backend/routers/investments.py:16-101](../../../../backend/routers/investments.py) — 7 distinct Investments endpoints (holdings, activity, performance, lots, allocation, tax-buckets, tax-summary). None registered in [ui-number-registry.yaml](../ui-number-registry.yaml).
- [backend/routers/dev.py:56-80](../../../../backend/routers/dev.py) — `POST /api/dev/reset-trusted-seed` endpoint shipped in the same FastAPI app that serves the trusted UI. No mode-flag gate.

### Cross-checks

- `Grep "compute_period_totals" {dal,backend}/**/*.py` → 3 files: `dal/cash_flow.py`, `dal/reports/flow.py` (Sankey), `dal/flow_aggregation.py` (the source). **Not** `dal/reports/spending.py`.
- `Grep "from dal.category_classifications|category_classifications" scripts/*.py` → no matches. **The audit script does not import the canonical sets.**
- Manual diff of `INCOME_CATEGORIES`, `EXCLUDED_FROM_SPEND`, `INCOME_EXCL_FROM_INC` between
  [audit_number_trust.py:28-83](../../../../scripts/audit_number_trust.py)
  and
  [dal/category_classifications.py:34-124](../../../../dal/category_classifications.py)
  → currently identical (14, 10, and 24+10=34 entries respectively).
  No automated test enforces this.

### Inherited evidence from prior rounds

- All Round 2 evidence in [shared-evidence.md](shared-evidence.md), unchanged.
- All Codex Round 3 acceptances treated as agreed unless reopened below.

---

## Reasoning

### Areas of agreement with Round 3 (concise)

These I won't relitigate. Codex called them right:

- **Phase 1.5 ordering.** Front-load invariants, owner-scoping, cents-first, registry field-coverage before larger seed work. Right call.
- **Layered proof model A→F.** Seed manifest → raw recomputation → cross-endpoint invariants → API → DOM → expected-values fixture. Right framing; covers what Round 2 asked for without overcommitting to a second-language oracle.
- **Owner/view in registry + expected_state for Amy.** Treating Amy as an affirmative empty-state audit case (not a skip) is exactly right. Round 2 asked for it; Round 3 delivered it.
- **Definition/lens metadata is a generally useful audit concept.** Even though I argue below that the *current* mismatch will dissolve via migration, the lens metadata pattern is still valuable for genuinely separate views (annualized vs trailing, gross vs net, etc.).
- **Phase 4 split into 4a (selectors) + 4b (DOM audit).** Round 2's one Phase-4 lump was wrong; Codex's split is right.
- **Cents-first audit math.** Codex correctly priorities this below invariants/owner-view but commits to it. Right priority call.
- **Deferring 209-month-runway decision to user.** Right; this is a product decision, not a math decision.
- **Same-DB raw oracle is a layer, not garbage.** Codex's defense is fair; my Round 2 framing was too dismissive. The raw oracle does prove "production DAL agrees with an independent SQL recomputation," which is a real (if narrow) claim. Treating it as Layer B with B/C/D/E/F on top is the correct compromise.
- **Pre-commit hook policy deferred.** Fine, with the caveat that the failing test is a calendar-determinism issue and Phase 3 should explicitly own the follow-up.

### New finding #1 — The cross-endpoint contradiction is unfinished migration, not deliberate design

[dal/flow_aggregation.py:11-33](../../../../dal/flow_aggregation.py)
states explicitly:

> Pre-PR1 the Cash Flow page (`dal/cash_flow.py`) and the Reports
> page (`dal/reports.py::get_flow_data`) each ran their own
> income/spending SQL with the same INTENDED filter … but different
> surrounding context (date columns, grouping, payroll integration).
> The result: "Last 30 Days" on Reports vs. "April so far" on Cash
> Flow returned visibly different income and spending totals for
> nearly identical windows. … This module exposes a clean API
> (`compute_period_totals`) that both pages **will consume in PR2**.

`Grep "compute_period_totals"` confirms PR2 was completed for the
Sankey flow ([dal/reports/flow.py](../../../../dal/reports/flow.py))
and for Cash Flow
([dal/cash_flow.py:330](../../../../dal/cash_flow.py)) — but **not
for `dal/reports/spending.py::get_period_summary`**, which is the
function backing `/api/reports/summary` and therefore the source of
Round 2's `dashboard.monthly_net_flow` numbers
([report json:23-62](../reports/number-trust-20260429-124043.json)).

`get_period_summary`
([dal/reports/spending.py:156-200](../../../../dal/reports/spending.py))
still does its own income SQL plus `get_spending_by_category`, both
using the legacy posting-date blacklist with no payroll grossup and
no debt-service-as-spend. **This is the lens that
`flow_aggregation.py` documents as the wrong one.**

The implication for the plan:

Codex's Round 3 §Reasoning 1 ("Cross-endpoint contradiction") lists
three options:

> - either the two surfaces are expected to match,
> - or the difference is expected and decomposed into named offsets,
> - or one endpoint becomes canonical and the other delegates.

The codebase already chose option 3 (one endpoint canonical, the
other delegates) and partially executed it. Cash Flow and Sankey
delegate to `compute_period_totals`. The summary endpoint hasn't
been migrated yet. **The right Phase 1.5 deliverable is to finish
that migration**, not to add registry metadata to manage two
permanent lenses.

This is also why Codex's Round 3 question #1 ("Should monthly net
flow have one canonical definition across Dashboard, Cash Flow, and
Reports, or may the app expose multiple lenses with explicit
labels?") is partially settled by the codebase: the project
**already** decided one canonical definition, in the form of
`compute_period_totals`. The user decision is more limited:
**ratify the existing canonical, or override it.**

I propose that Phase 1.5 explicitly include:

> - Migrate `dal/reports/spending.py::get_period_summary` to consume
>   `compute_period_totals` (matching the pattern in
>   `dal/cash_flow.py::get_period_detail` and
>   `dal/reports/flow.py`). Verify the audit's
>   `dashboard.monthly_net_flow` and `cash_flow.current_month`
>   numbers converge for the canonical seed.

This finishes a project-acknowledged TODO and dissolves the most
visible Round-2 contradiction without needing labels or registry
lens metadata for *this* mismatch. The lens metadata field still
belongs in the registry for future genuinely-distinct views, but it
shouldn't be the load-bearing answer to the Reports/Cash-Flow
disagreement.

### New finding #2 — Audit duplicates the canonical category sets

[dal/category_classifications.py:1-9](../../../../dal/category_classifications.py)
opens with:

> Every module in the DAL that needs to classify transactions as
> income, spending, transfers, or exclusions MUST import from here.
> Do NOT define local copies.

Yet
[scripts/audit_number_trust.py:28-114](../../../../scripts/audit_number_trust.py)
defines local copies of:

- `INCOME_CATEGORIES` (14 entries),
- `EXCLUDED_FROM_SPEND` (10 entries),
- `ALL_EXCL_FROM_SPEND` (24 entries, computed),
- `INCOME_EXCL_FROM_INC` (34 entries, computed),
- `CASHOUT_SPEND_EXCLUDE` (17 entries),
- `DEBT_CASH_CATEGORIES` (6 entries),
- `LIABILITY_TYPES` (5 entries),
- `CASH_ACCOUNT_TYPES` (3 entries).

A hand diff shows the first three currently match the DAL's
canonical sets, character-for-character. **No automated test
enforces this.** A future PR that adds a new income category to
`dal/category_classifications.py` (say, `"Crypto Earnings"`) without
touching `audit_number_trust.py` produces:

- API totals: include the new category as income (because the DAL
  category set was updated).
- Audit oracle totals: exclude the new category from income (because
  the audit's local `INCOME_CATEGORIES` is stale).
- Audit reports: a real diff, classified as "API logic bug" — but
  the bug is in the audit's own duplication, not in the API.

This degrades trust: the audit produces false positives that look
like API regressions. Or, conversely, if the new category should
have been excluded but the audit's stale set keeps it included, the
audit produces a false negative — silent agreement on wrong totals.

The fix is mechanical: replace the local definitions with imports.
The intentional independence note at the top of `audit_number_trust.py`
("does not call production DAL report helpers for oracle values")
is about not sharing **logic**, not about not sharing **vocabulary**.
Sharing the category sets keeps the oracle independent of the API's
SQL while preventing definitional drift.

I propose Phase 1.5 also include:

> - Replace the local category-set definitions in
>   `audit_number_trust.py` with imports from
>   `dal/category_classifications.py`. Add a regression test that
>   confirms the audit oracle's category sets are exactly the
>   canonical sets.

This is one of the cheapest improvements possible and closes a
quiet drift hazard.

### New finding #3 — Phase 2 changes investment data that no audit covers

The project scope per
[adversarial-review-plan.md:21-26](../adversarial-review-plan.md)
is "Dashboard, Transactions, Cash Flow, Reports, Accounts."
Investments is **not** in scope.

But Codex's revised Phase 2 says:

> Apply the user's investment simplification:
> - round starting balances,
> - monthly transfers/contributions only,
> - no growth, no losses, no dividends, no sells, …

Investments backs **7 distinct API endpoints**
([backend/routers/investments.py:16-101](../../../../backend/routers/investments.py))
and consumes ~5,500 rows of seed data
([trusted_seed_manifest.json](../../../../data/trusted_seed_manifest.json):
470 portfolio_snapshots + 3170 investment_holdings + 1861
positions_ledger). Phase 2 reshapes the entire input domain that
those endpoints render, but **no Phase covers verifying what the
Investments page actually shows after the reshape**.

This is the same defect as Round 2 finding #6 (3 of 5 in-scope pages
unaudited) — except now the unaudited surface is being *actively
modified* by Phase 2 instead of just left alone.

Two coherent options:

- **(a) Bring Investments into the audit scope.** Add Investments
  registry entries in Phase 4a; verify Holdings, Activity, Allocation,
  and Tax-Summary numbers in Phase 4b. Phase 2's investment-seed
  changes then have a verification path.
- **(b) Scope-limit Phase 2 to investment data that audited surfaces
  consume.** Specifically: portfolio snapshots feeding net worth, and
  dividend transactions feeding cash-flow income. Leave
  Investments-page-specific data (holdings, lots, fund composition)
  alone.

Either is defensible. **The current plan picks neither**, which is
the worst of both worlds: Phase 2 changes data nobody verifies.
Codex should commit to one.

I lean toward (a) because the user explicitly mentioned the
multi-user / banking roadmap (memory: `project_multiuser.md`) — once
real brokerage data is imported, Investments is a primary trust
target, and adding it to the registry now is cheaper than adding
it later.

### New finding #4 — "Verify runtime DB identity" is too vague

Codex's Phase 1 acceptance criterion:

> A clean stack restart shows exactly one backend, one frontend, and
> one trusted DB identity.
> The runtime identity fingerprint matches `app_settings.trusted_seed_manifest`.

That's the manifest-recorded fingerprint matching itself (because
both come from the same `app_settings` row). It does not catch the
common-but-quiet failure mode: the trusted DB has been mutated
*outside* the seeder. Examples:

- A user accidentally hit `POST /api/dev/reset-trusted-seed` and
  re-seeded with non-deterministic state somewhere.
- A user ran an ingestion smoke test against the trusted DB.
- A test or migration accidentally wrote to `data/sentry.db` while
  `SENTRY_DB_PATH` was unset (the import-order issue from Round 2 #7).

In all three cases, `app_settings.trusted_seed_manifest` is
unchanged (the seeder writes it; nothing else does). But the rest
of the DB has drifted.

Phase 1's identity endpoint should also expose a **live fingerprint**
computed from the same SQL the seeder uses to compute the canonical
fingerprint, comparing against the manifest's recorded fingerprint.
Round 4 proposal:

> Phase 1 acceptance addition:
> - The identity endpoint computes a live fingerprint over the
>   canonical row set and reports it alongside the manifest's
>   recorded fingerprint. The proof gate fails if they differ.

This catches the "DB was tampered with after seeding" case that
Phase 1's current acceptance criterion silently passes.

### New finding #5 — Dev endpoints in the proof gate

[backend/routers/dev.py:56](../../../../backend/routers/dev.py):
`POST /api/dev/reset-trusted-seed` is exposed in the same FastAPI
app that serves the trusted UI. The router docstring (lines 1-9)
says these endpoints "should NOT be exposed in any deployed build,"
but there is no runtime gate — the router is unconditionally
included in
[backend/api_server.py](../../../../backend/api_server.py).

For the proof gate's purposes:

- If a user's browser session can hit `/api/dev/reset-trusted-seed`
  while the proof gate is running, the trusted DB can be re-seeded
  mid-audit. The current proof flow is sequential (reseed → start
  → audit) so this is mostly hypothetical, but the gate explicitly
  claims reproducibility.
- More concretely: the proof gate's "verify runtime DB identity"
  step should also verify *the dev endpoints are not reachable* in
  proof mode, OR the dev endpoints should be gated by the same DB
  mode flag as the canonical-trusted-DB enforcement.

Round 4 proposal:

> Phase 1 (or Phase 5) acceptance addition:
> - Either dev endpoints are gated by `SENTRY_DB_MODE` (or
>   equivalent) and refuse in non-dev mode, OR the proof gate
>   verifies dev endpoints return 404 / 403 before treating the audit
>   as valid.

### New finding #6 — Controlled vocabulary for "definition lens"

Codex's Phase 4a registry expansion adds a `definition/lens` field.
Without a controlled vocabulary, this becomes free-text:
"cash-out lens" vs "cash_out_lens" vs "cashout-lens" vs "cash-out
view (D3 grossup)" all appear plausible. Different audit entries will
classify the same lens differently, and no invariant will be able to
say "these two surfaces share a lens."

Round 4 proposal:

> Phase 4a addition:
> - The registry's `definition/lens` field is constrained to an
>   enumeration documented in the registry header. Initial values:
>   `cash_out_grossup` (the `compute_period_totals` lens),
>   `posting_date_blacklist` (the legacy `get_period_summary`
>   lens, deprecated after Phase 1.5 migration),
>   `gross_pretax`, `net_aftertax`, `annualized`, `trailing_n_months`.
>   New lens labels require a same-PR registry-header update.

If finding #1 lands (migration of `get_period_summary`), the
`posting_date_blacklist` lens disappears from the registry on the
same PR.

### Concession: Round 2's "self-oracle problem" framing was too strong

Codex's Round 3 partial-acceptance is right. The same-DB raw oracle
is not garbage — it does prove "two independent SQL implementations
agree on selected values for one fixture." That is real evidence,
just not full-stack evidence. Codex's Layer A→F model integrates it
correctly.

I withdraw the Round 2 push for a second-language oracle. The
committed expected-values fixture (Codex Layer F) is the right
near-term independence step. I revisit this in Question 3 below.

### Concession: Investment simplification deserves its own scope

Codex's Round 3 §Partially Accepted ("Investment simplification
critique") is fair. The user explicitly wants round balances +
monthly transfers + no market complexity. That's a real product
request, separate from "the seed has unrealistic ratios in other
ways." Reframing Phase 2 as "canonical seed explainability and
realistic ratios" with both the user's investment narrowing and the
broader realism question inside it is the right structure.

### Concession: Same-DB oracle as a layer

Withdrawn. Codex's defense is correct: it remains a useful first
layer, especially when categorization vocabulary is shared (see
finding #2 above).

---

## Direct answers to Codex's five Round-4 requests

> **Q1: Is the revised Phase 1 → 1.5 → 2 → 3 → 4a → 4b → 5 sequence
> now evidence-forward enough?**

YES, with one addition. Phase 1.5 should explicitly commit to
**migrating `get_period_summary` to consume `compute_period_totals`**
(finding #1 above). Without that, "add cross-endpoint invariants"
either silently passes (if the invariant is "report-summary minus
cash-flow-period equals payroll_grossup + debt_service_decomposed,"
which is contortion to make legacy-lens-vs-cashout-lens look
intentional) or fails the audit and forces the migration anyway.
Better to commit to the migration up front.

> **Q2: Does the plan overfit to the current Cash Flow vs Reports
> mismatch, or is definition/lens metadata a generally useful audit
> concept?**

Mostly the latter. The lens metadata is generally useful — for
genuinely distinct views like trailing-twelve-months vs
year-to-date, gross vs net, household vs per-owner. But for the
*current* mismatch, see Q1: the codebase already decided what's
canonical; the right answer is to finish the migration, not to
permanently label two lenses. So the plan slightly overfits to this
specific mismatch while still landing the generally-useful concept.
Net: keep the lens field; commit to the migration; remove the
`posting_date_blacklist` lens label after migration.

> **Q3: Is a committed expected-values fixture sufficient
> independence, or should a truly independent oracle be required
> before live-data import?**

Sufficient, with conditions:

- The fixture must include **per-row spot checks**, not just
  headline totals. E.g., "transaction id `tx_2026-04-15_001`
  signed_amount = -42.50, category = 'Groceries', owner = Quintin"
  for ~20 representative transactions across all in-scope pages.
- The fixture is regenerated only by a deliberate, auditable command
  (`scripts/regenerate_expected_values.py --confirm`), not by the
  seeder itself.
- A test enforces that the fixture's claims are reachable via two
  paths: raw SQL on the trusted DB, and the public API. Failure on
  either side flags drift.

A truly independent second-language oracle remains optional. The
expected-values fixture closes the most important gap (the audit's
"expected" is computed from the same DB as "actual") at much lower
cost than a second oracle implementation.

> **Q4: Should seed realism be a prerequisite for DOM audit, or can
> DOM audit proceed against the current deterministic seed while
> seed realism is refined in parallel?**

DOM audit can and should proceed against the current deterministic
seed. Realism is a separate concern that affects which **branches**
of UI logic are exercised (color thresholds, warning banners, etc.),
not whether the rendered numbers match the API. The deterministic
seed is sufficient ground truth for "the API number and the DOM
number agree." Phase 2 (realism) and Phase 4b (DOM audit) can run in
parallel after Phase 1.5; they don't have to be sequential.

This is how I'd visualize it:

```
1 → 1.5 ─┬→ 2 (realism)        ─┐
         ├→ 3 (frontend dates) ─┼→ 5 (proof gate)
         └→ 4a (selectors) → 4b (DOM audit) ─┘
```

Three independent tracks after Phase 1.5, converging at Phase 5.

> **Q5: Are any of the five in-scope pages still under-specified in
> the revised plan?**

YES, two:

- **Reports.** No registry entries today; not added in Phase 1.5;
  finally appears in Phase 4a as part of "expand registry coverage."
  Given finding #1 (the Reports summary endpoint is the source of
  the cross-endpoint contradiction), Reports should get registry
  entries in Phase 1.5, not Phase 4a, so the migration's correctness
  is verified at the same time it lands.
- **Accounts.** Only mentioned generically. Accounts has a clear
  invariant the audit should encode now: every account's displayed
  balance equals its latest `balance_snapshot.balance`, and the sum
  of (active checking + savings) equals the Dashboard's
  `liquid_balance`. This invariant is testable today against the
  existing audit harness and doesn't need DOM coverage to be
  meaningful.

Investments is still ambiguously in/out of scope (finding #3
above) — that's a user decision.

---

## Remaining decision points for the user (cumulative)

These extend the existing list in
[shared-evidence.md](shared-evidence.md):

1. **Migration vs labels.** Commit to migrating
   `get_period_summary` to `compute_period_totals` (codebase already
   started this), or accept two permanent lenses with registry
   labels?
2. **Investments scope.** Bring Investments into the audit registry,
   or scope-limit Phase 2 to investment data the in-scope pages
   consume?
3. **Live vs manifest fingerprint.** Should the proof gate compute a
   live fingerprint and compare to the manifest, or just verify the
   manifest's recorded value?
4. **Dev endpoints in proof mode.** Gate `/api/dev/*` by mode flag,
   or have the proof gate verify dev endpoints are unreachable
   before declaring success?
5. **Lens vocabulary.** Use a controlled enumeration for the
   definition/lens registry field, or allow free text?
6. **Expected-values fixture granularity.** Just headline totals, or
   include ~20 per-row spot checks across in-scope pages?

Round 5 should fold these into the user-decision section of the
final synthesis.

---

## Assumptions

- Codex's Round 3 acceptances stand unless explicitly reopened.
- The codebase at HEAD = `ca286f6` (Round 2 commit) is canonical for
  Round 4 evidence.
- The user's stated goal — trust before live-data import — has not
  shifted between rounds.
- "Phase" labels are workflow units, not commitment-level
  boundaries; reordering or splitting is fine if it produces
  evidence sooner.

## Risks (in my own Round 4 critique)

- **Risk: finding #1 may be wrong if `get_period_summary` is being
  intentionally retained as a "lighter" summary endpoint** (e.g. for
  dashboard performance). I have not read every consumer of
  `/api/reports/summary` to rule this out. Disconfirms the
  "migration is unfinished" framing if a deliberate decision exists.
  Mitigation: Phase 1.5 should investigate before migrating.
- **Risk: finding #2 may be over-engineering for a one-call audit
  script.** Importing from `category_classifications.py` is simple,
  but adding a regression test creates one more thing to maintain.
  Counter: the canonical sets file explicitly forbids local copies
  in its own docstring; the audit isn't exempt by virtue of being
  in `scripts/`.
- **Risk: finding #3 may assume the user will eventually want
  Investments coverage.** If they explicitly do not, scope-limiting
  Phase 2 is fine and Investments remains permanently out of audit.
  Mitigation: question #2 above lets the user decide.
- **Risk: finding #4 (live fingerprint) adds runtime cost** to every
  identity-endpoint call. Mitigation: compute on demand or cache for
  N seconds.
- **Risk: I may be too generous in conceding the same-DB oracle
  point.** A defender of Round 2's stronger framing could argue that
  Layer B's value is illusory: independent SQL recomputation against
  the same DB just proves the DB has internally consistent data,
  not that the data is right. I think Codex's layered model
  acknowledges this implicitly (Layers C through F do the heavier
  evidence-lifting), so the concession is fine.

## What would disconfirm this Round 4 position

- A grep finding that `compute_period_totals` is intentionally
  *not* used by the summary endpoint for documented performance or
  semantic reasons — would withdraw finding #1.
- Evidence that `dal/category_classifications.py`'s "single source
  of truth" rule has documented exceptions for `scripts/` —
  would soften finding #2.
- A user statement that Investments is permanently out of audit
  scope and Phase 2 should explicitly avoid touching
  Investments-only data — would resolve finding #3 in favor of
  scope-limiting.
- A user statement that the proof gate is fine with manifest-only
  fingerprint and the live-fingerprint comparison is over-engineering
  — would soften finding #4.

---

## Proposed final staged plan (input to Round 5 synthesis)

This bundles Codex's Round 3 plan plus the Round 4 findings into a
form Round 5 can adopt or revise.

### Phase 0 (NEW): Audit-vocabulary deduplication

Goal: stop the audit from defining its own copy of the canonical
category sets.

- Replace local `INCOME_CATEGORIES`, `EXCLUDED_FROM_SPEND`,
  `INCOME_EXCL_FROM_INC`, etc. in
  [scripts/audit_number_trust.py](../../../../scripts/audit_number_trust.py)
  with imports from
  [dal/category_classifications.py](../../../../dal/category_classifications.py).
- Add `tests/test_audit_vocabulary.py` asserting that the audit's
  effective category sets equal the canonical sets.
- Defensible as Phase 0 because it has zero ordering dependency on
  Phase 1.

### Phase 1: Single DB Authority

(As Codex revised, with two additions.)

- Deferred DB-path resolution
  ([dal/connection.py:25-27](../../../../dal/connection.py)).
- Hard-fail or explicit mode flag for missing `SENTRY_DB_PATH`.
- Identity endpoint exposes: resolved path, seed version, reference
  date, **manifest fingerprint AND live fingerprint**, schema
  version, process id.
- Either dev endpoints are mode-gated, OR proof-gate Phase 5
  verifies dev endpoints are unreachable.

### Phase 1.5: API audit invariants, owner/view, and lens migration

(Codex's Phase 1.5, with two additions.)

- All Codex acceptance criteria (invariants, owner/view runs,
  cents-first, registry field-coverage, classification taxonomy).
- **Add: migrate `dal/reports/spending.py::get_period_summary` to
  consume `compute_period_totals`.** Verify Round 2's $2,107
  cross-endpoint disagreement converges to zero.
- **Add: register Reports headline values now**, so the migration's
  correctness is verified at the same time it lands.
- **Add: register Accounts headline values now**, with the
  invariant `Σ(account.displayed_balance) = Dashboard.liquid_balance`
  (for active cash accounts). Cheap; no DOM coverage needed yet.

### Phase 2: Canonical seed explainability and realistic ratios

(As Codex revised. User decisions on realism targets per Codex's
question #4.)

- **Decide: Investments scope** (per Round 4 finding #3). Either
  bring Investments into the audit (then Phase 4a expands), or
  scope-limit Phase 2 to data the in-scope pages consume.

### Phase 3: Frontend reference date

(As Codex revised. The pre-commit-test failure (Round 2 #14)
becomes an explicit Phase 3 sub-task.)

### Phase 4a: Selectors and registry expansion

(As Codex revised. Add controlled-vocabulary `definition/lens`
field per Round 4 finding #6.)

### Phase 4b: Oracle to API to DOM audit

(As Codex revised. Can run in parallel with Phase 2 and Phase 3 per
Round 4 answer to Codex Q4.)

### Phase 5: Proof gate

(As Codex revised. Gate also verifies live fingerprint matches
manifest fingerprint per Round 4 finding #4.)

---

## Sign-off

— **Claude (Opus 4.7, 1M context)**, Round 4 second adversarial
reviewer.

Codex: cleanly conceded most of Round 2 — that's a strong Round 3.
Round 4's job was to find what the deeper code-scour catches that
the abstract critique didn't, and the codebase repaid that scrutiny:
the cross-endpoint contradiction is a half-finished migration, not
two intentional lenses; the audit duplicates the canonical category
sets in violation of the project's own rule; and Phase 2 reshapes
investment data nobody verifies.

Three findings reframe one decision (lens metadata vs migration),
patch one quiet drift hazard (vocabulary duplication), and surface
one scope inconsistency (Investments). The rest of Round 3 holds —
including, gladly, your defense of the same-DB oracle as Layer B.

Round 5 is yours. Looking forward to the synthesis.
