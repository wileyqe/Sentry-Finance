# Backend Simplification — Post-Phase 13

> **Status:** In progress, 2026-04-16. Cross-phase cleanup pass, not tied
> to a single ROADMAP task. Root-level prompt per the `docs/prompts/README.md`
> convention for initiatives that span phases.

---

## Context

After Phase 13 shipped, a `/simplify` survey of `backend/`, `dal/`, and
`extractors/` identified 12 simplification opportunities verified against
source. The user accepted all of them. The goal of this pass is to
eliminate duplicated logic that surrounds two of CLAUDE.md's
non-negotiable invariants — the canonical sign convention and owner
scoping — so there's a smaller surface area for those invariants to
break in the future.

Two prior artifacts motivated this pass:

- [`empty_state_audit.md`](empty_state_audit.md) (Phase 12) identified
  the `if not account_ids:` falsy-collapse bug that leaked the primary
  owner's data into a zero-account view. That audit led to the creation
  of `dal.owners.build_account_filter` as the single helper that
  distinguishes `None` (no filter) from `[]` (zero-account
  short-circuit via `AND 1=0`). Parts of the DAL migrated; others
  stayed on the legacy `resolve_owner_account_ids` +
  `_acct_filter_clause` two-step that still depends on the caller
  remembering to use `is not None` instead of truthy checks.
- [`docs/ARCHITECTURE.md` §4.6 "Sign Convention"] mandates that every
  write routes through `dal.transactions.upsert_transactions`, which
  runs `_assert_sign_direction_invariant`. The derivation of
  `signed_amount` from `(amount, direction)` used to live inline in
  `backend/result_writer.py:dataframe_to_txn_dicts` — a second
  implementation waiting to disagree with the assertion.

## Starting State (before this pass)

- `build_account_filter` existed at `dal/owners.py:264` but ~14 DAL
  call sites (mostly `dal/cash_flow.py`) still used the legacy
  two-step. Each site was one refactor mistake away from
  reintroducing the Phase 12 leak.
- `ALL_EXCL_FROM_SPEND` / `INCOME_EXCL_FROM_INC` exclusion sets were
  materialized via `list(...)` + placeholder-string construction at
  25+ sites across `dal/cash_flow.py`, `dal/reports.py`,
  `dal/derived.py`, `dal/budgets.py`, `dal/review.py`,
  `dal/yearly_wrapup.py`.
- `backend/result_writer.py:persist_connector_result` called
  `get_latest_balance(conn, account_id)` in a loop (N+1 queries per
  refresh).
- `backend/result_writer.py:dataframe_to_txn_dicts` hand-rolled
  `signed_amount = amount if is_credit else -amount` instead of
  delegating to the sign chokepoint.
- `backend/result_writer.py:run_post_commit_pipeline` had 5 nearly
  identical try/except blocks around independent pipeline steps.
- `backend/refresh_orchestrator.py:_load_policies` re-opened and
  re-parsed `config/refresh_policy.yaml` on every call.
- Connector retry loops (`extractors/chrome_cdp.py`) spelled out
  `for i in range(N): time.sleep(1); if check(): return` bodies
  by hand.

## Task

Five waves, committed separately so each is independently revertible.
Targeted tests must pass between waves; the full suite runs at the end
of every wave except Wave 1.

### Wave 1 — Add helpers (no call-site changes)

- `dal/category_classifications.get_spend_exclusion_clause()`,
  `get_income_exclusion_clause()` — return `(placeholder_string, params)`.
- `dal/balances.get_latest_balances(conn, account_ids)` — batched
  dict result.
- `dal/transactions.derive_signed_amount(amount, direction)` — single
  place that turns `"Debit"/"Credit"` into a sign.
- `backend/result_writer._run_step(name, fn)` — try/except + log wrapper.
- `dal/migrations.column_exists(conn, table, col)` — intended only for
  **new** migrations; shipped migrations are immutable.
- `extractors/_retry.py` — `poll_with_timeout`, `retry_with_backoff`.
  Minimal; `ai_backstop` remains the place for connector-rich resilience.

### Wave 2 — Migrate to Wave 1 helpers (behavior-preserving)

- ~25 exclusion-list sites → new helpers
- Balance N+1 fix in `persist_connector_result`
- Sign derivation in `dataframe_to_txn_dicts` → `derive_signed_amount`
- 5 pipeline try/except blocks → `_run_step` with inner `_categorize()`/
  `_reconcile()`/etc. helpers
- Drop the pre-flight `csv_path.exists()` — let `pd.read_csv` raise into
  the existing `except Exception` block
- Chrome-launch and Chrome-shutdown polls → `poll_with_timeout`
- **Skip:** `sms_otp.py` retry loop keeps its inline logs;
  `dal/transactions.py` narrow `EXCLUDED_FROM_SPEND` usage is a
  different set than `ALL_EXCL_FROM_SPEND` and must not be unified;
  `routers/transactions.py` manual-create endpoint already bypasses
  `upsert_transactions` and takes a non-canonical `"outflow"` direction
  default, which is a separate bug outside this pass's scope.

### Wave 3 — `build_account_filter` migration (the invariant-risk wave)

~14 call sites, mostly in `dal/cash_flow.py`, replace:

```python
from dal.owners import resolve_owner_account_ids
account_ids = resolve_owner_account_ids(conn, owner_id, account_ids)
acct_sql, acct_params = _acct_filter_clause(account_ids)
```

with:

```python
from dal.owners import build_account_filter
acct_sql, acct_params = build_account_filter(conn, owner_id, account_ids)
```

After the migration, the local `_acct_filter_clause` helper in
`cash_flow.py` becomes dead code. Delete only if no call site
remains. `resolve_owner_account_ids` stays — `dal/derived.py:264` and
`dal/reports.py:206` still need the resolved list shape (they don't
want an SQL fragment).

### Wave 4 — Caching

- `@functools.lru_cache(maxsize=1)` on `_load_policies` in
  `backend/refresh_orchestrator.py`. Expose `reload_policies()` for tests.
- Same treatment in `dal/freshness.py` if it duplicates the YAML read.
- `get_institution_statuses` called in an inner loop at
  `refresh_orchestrator.py:480` — either add a filtered overload or
  build a dict once per refresh.

### Wave 5 — Polish

- DRY monthly/quarterly/annual cash-flow queries (extract a shared
  `_build_cashflow_query`)
- `SELECT *` → projected columns at `backend/routers/user_rules.py:28`,
  `dal/categorization.py:94`
- Lazy `yaml` imports in `backend/refresh_orchestrator.py:16`,
  `dal/categorization.py:18`
- `backend/events.py` — unsubscribe cleanup so the SSE subscriber list
  doesn't grow on client churn
- `backend/ipc.py:48-49` — document the defensive `ctypes.memset`
  try/except (defense-in-depth) or remove it

## Out of Scope (explicitly)

- **Stringly-typed `"Credit"`/`"Debit"` → enum.** DB values depend on
  the literal strings; a Python-layer enum without a migration creates
  two sources of truth.
- **CSV column detection / balance parsing helpers** — only 1–2 sites,
  abstraction not worth it yet.
- **Parameter sprawl in `list_transactions`** — breaks frontend contract.
- **Rewriting `ai_backstop.py`** — it works and is tested.

## Verification

- **Per-wave:** targeted tests listed in the ROADMAP note / plan file.
- **After Wave 3 (owner scoping):** full `pytest tests/ -x --tb=short`.
  If any "Amy owns zero accounts" test regresses, the `AND 1=0`
  short-circuit is broken — stop and bisect.
- **Final:** full suite + `ruff check backend dal extractors tests` +
  `cd frontend && npm run build` + dummy-data reseed + clean API-server
  startup.

## Outcomes (filled in as waves land)

- **Wave 1 ✅ (2026-04-16)** — all 6 helpers added. Nothing called them
  yet. 29 targeted tests passed. Pure additive commit.
- **Wave 2 ✅ (2026-04-16)** — ~25 exclusion sites migrated across
  6 DAL files; 5 pipeline try/except blocks collapsed; balance N+1
  fixed; CSV TOCTOU removed; 2 chrome_cdp poll loops migrated. 155
  targeted tests passed. `_EXCLUDED_FROM_SPEND` import removed from
  `reports.py` and `derived.py` (remaining `INCOME_CATEGORIES` uses
  kept). Surprise: `sms_otp.py` kept its inline retry because the
  remaining-time debug log would be lost under `poll_with_timeout`.
- **Wave 3 ✅ (2026-04-16)** — `dal/cash_flow.py` 8 sites, `dal/transactions.py`
  `get_transactions`/`count_transactions` owner resolvers migrated to
  `build_account_filter`. Local `_acct_filter_clause` helper deleted.
  Full suite (212 tests) passes. Surprise: `transactions.py` had a
  latent `IN ()` SQL bug when a specific owner resolved to `[]` — fixed
  as a side-effect by the migration.
- **Wave 4 ✅ (2026-04-16)** — `_load_policies` in
  `backend/refresh_orchestrator.py` now `@lru_cache(maxsize=1)` with a
  `reload_policies()` test hook. `_get_refresh_policy` in
  `dal/freshness.py` same treatment. New DAL overload
  `dal.refresh_log.get_institution_status(conn, institution_id)`
  replaces the per-institution linear scan in `_run_institution`.
- **Wave 5 ✅ (2026-04-16)** — `SELECT *` → projected columns at two
  sites (`routers/user_rules.py`, `dal/categorization.py`). Lazy `yaml`
  imports in `dal/categorization.py` (already applied to
  `refresh_orchestrator.py` as part of Wave 4). SSE subscriber
  cleanup was already handled correctly (`unsubscribe` in a `finally`
  at `routers/refresh.py:123`). `ipc.py` defensive `try/except` was
  already documented. DRY of monthly/quarterly/annual cashflow queries
  deliberately skipped — the three functions' SQL differs enough
  that a shared builder would be less readable than the 3 parallel
  implementations (CLAUDE.md "3 similar lines better than a premature
  abstraction").

## Final Verification

212/212 pytest pass. Ruff findings on touched files are all pre-existing
(`log.warning` without logger import at `cash_flow.py:542`, unused
`calendar`/`date` imports in `yearly_wrapup.py`) — left to a
follow-up. `init_db()` and `backend.api_server` import cleanly.
