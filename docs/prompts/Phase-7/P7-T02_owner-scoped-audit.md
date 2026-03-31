# P7-T02: Owner-Scoped DAL Audit

## Context

You are working on Sentry Finance, a local-first personal finance app
for a two-person household. The V5 migration added an `owners` table
and an `owner_id` FK on `accounts`. A helper `resolve_account_ids_for_view()`
in `dal/owners.py` converts a view string (`"mine"`, `"theirs"`, `"ours"`)
into a set of account IDs.

Currently, only `get_budget()` and `get_goals_summary()` accept an
`owner_id` parameter. Every other DAL function queries the full dataset,
meaning there is no way to filter reports, cash flow, metrics, or debt
analysis by owner.

**This task is the prerequisite for multi-user mode.** Every DAL function
that queries accounts or transactions must accept an optional `owner_id`
parameter. When present, it restricts the query to accounts belonging to
that owner (plus shared accounts where `owner_id IS NULL`).

### Filtering strategy

The pattern is consistent across all functions:

```python
def some_function(conn, ..., owner_id: str | None = None) -> ...:
    """..."""
    account_ids = None
    if owner_id:
        from dal.owners import resolve_account_ids_for_view
        account_ids = resolve_account_ids_for_view(conn, owner_id)
    # ... rest of function uses account_ids to filter queries
```

When `owner_id is None` (the default), the function behaves exactly as
it does today — querying all data. This preserves backward compatibility
and means **no existing tests or API calls break**.

### What `resolve_account_ids_for_view` returns

```python
def resolve_account_ids_for_view(conn, view: str) -> set[str]:
    """
    "mine"   → accounts where owner_id = primary_owner
    "theirs" → accounts where owner_id != primary_owner AND owner_id IS NOT NULL
    "ours"   → ALL accounts (shared view — same as no filter)
    <owner_id> → accounts where owner_id = <owner_id> OR owner_id IS NULL
    """
```

When a specific `owner_id` is passed (not a view string), the function
returns that owner's accounts PLUS shared accounts (`owner_id IS NULL`).

## Starting State

- `dal/owners.py` — owner CRUD, `resolve_account_ids_for_view()`
- `dal/migrations/v05_ownership.py` — owners table, accounts.owner_id FK
- `config/owner_config.yaml` — primary_owner + owners list
- Only 2 DAL functions currently accept owner_id

## Task

### Phase A: DAL Functions to Update

For each function below, add `owner_id: str | None = None` as the last
parameter (before any `**kwargs`). When `owner_id` is provided, resolve
it to an account_ids set and inject into the query's WHERE clause.

**The filtering mechanism per function type:**

- **Functions that already accept `account_ids`**: If `owner_id` is
  provided AND `account_ids` is None, resolve owner_id to account_ids.
  If both are provided, intersect them.

- **Functions that query `transactions` directly**: Add
  `AND account_id IN ({placeholders})` when account_ids is set.

- **Functions that query `accounts` directly**: Add
  `AND id IN ({placeholders})` or `AND a.id IN ({placeholders})`.

- **Functions that query `balance_snapshots`**: Add
  `AND account_id IN ({placeholders})`.

- **Functions that compute aggregate metrics**: Filter the underlying
  account or transaction queries, not the derived computation.

#### `dal/transactions.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `get_transactions()` | 260 | Already has `account_id` param; add `owner_id` that resolves to account filter when `account_id` is None |

#### `dal/balances.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `get_all_latest_balances()` | 82 | `balance_snapshots JOIN accounts` — filter `accounts.id` |

#### `dal/reports.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `get_spending_by_category()` | 53 | Already has `account_ids` param — resolve owner |
| `get_cash_flow_report()` | 116 | Already has `account_ids` param — resolve owner |
| `get_net_worth_history()` | 183 | Filter `accounts.id` + scoped RE/vehicle queries |
| `get_category_trend()` | 342 | Filter transactions |
| `export_transactions_csv()` | 390 | Filter transactions |
| `get_period_summary()` | 460 | Filter transactions |
| `get_flow_data()` | 490 | Filter transactions |
| `get_merchant_list()` | 586 | Filter transactions |
| `get_merchant_flow_data()` | 679 | Filter transactions |
| `get_spending_comparison()` | 798 | Filter transactions |

#### `dal/cash_flow.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `get_monthly_cash_flow()` | 84 | Already has `account_ids` — resolve owner |
| `get_quarterly_cash_flow()` | 141 | Already has `account_ids` — resolve owner |
| `get_monthly_rolling_cash_flow()` | 197 | Already has `account_ids` — resolve owner |
| `get_quarterly_rolling_cash_flow()` | 272 | Already has `account_ids` — resolve owner |
| `get_yearly_cash_flow()` | 355 | Already has `account_ids` — resolve owner |
| `get_period_detail()` | 404 | Filter transactions |
| `get_available_years()` | 520 | Filter transactions |

#### `dal/derived.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `compute_emergency_fund_months()` | 273 | Filter `accounts` query |
| `compute_dti_ratio()` | 358 | Filter `transactions` query |
| `compute_interest_cost()` | 443 | Filter liability accounts query |
| `compute_net_worth_velocity()` | 576 | Calls `get_net_worth_history` — pass owner |
| `get_summary_metrics()` | 672 | Calls other functions — pass owner through |

#### `dal/debt.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `get_debt_summary()` | 225 | Filter liability accounts |
| `get_payoff_plan()` | 249 | Filter liability accounts |
| `compare_debt_payoff_vs_invest()` | 321 | Accept specific account IDs (already) |

#### `dal/recurring.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `get_recurring_transactions()` | ~50 | Filter by account_id set |
| `get_recurring_with_payoff()` | 550 | Filter by account_id set |

#### `dal/freshness.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `get_institution_freshness()` | ~30 | Filter by institution_ids from owner's accounts |

#### `dal/lifestyle.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `get_lifestyle_creep()` | 36 | Filter transactions |

#### `dal/review.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `get_monthly_review()` | 16 | Pass owner_id through to all sub-calls |

#### `dal/yearly_wrapup.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `_build_preliminary()` | ~37 | Pass owner_id through to all sub-calls |

#### `dal/performance.py`

| Function | Line | Filter target |
|----------|------|---------------|
| `get_portfolio_performance()` | ~30 | Filter investment accounts |
| `decompose_contributions_vs_performance()` | 384 | Already has `account_ids` — resolve owner |

### Phase B: Router Endpoints

After the DAL is updated, every router endpoint that calls these functions
must accept an optional `owner_id` query parameter and pass it through:

```python
@router.get("/api/reports/spending")
def spending_report(
    months: int = 6,
    owner_id: str | None = None,    # NEW
):
    with get_db() as conn:
        return get_spending_by_category(conn, ..., owner_id=owner_id)
```

**Do NOT add owner_id to these endpoints (they are owner-agnostic):**
- `/api/refresh/*` — refresh runs all institutions
- `/api/mfa/*` — MFA is session-level
- `/api/documents/*` — documents are household-level
- `/api/owners` — owner management itself
- `/api/user-rules` — categorization rules are household-level
- `/api/alerts/*` — alert rules are household-level

### Phase C: Integration Tests

Write `tests/test_owner_scoping.py` with a shared fixture:

```python
@pytest.fixture
def multi_owner_db():
    """In-memory DB with 2 owners, 4 accounts (2 per owner + 1 shared)."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    # Apply all migrations
    # Create owners: "alice", "bob"
    # Create accounts:
    #   "alice_chk" → owner_id="alice", type="checking"
    #   "alice_sv"  → owner_id="alice", type="savings"
    #   "bob_chk"   → owner_id="bob", type="checking"
    #   "shared_cc"  → owner_id=NULL, type="credit_card"
    # Seed transactions across all accounts
    yield db
    db.close()
```

**Test cases:**

1. `get_spending_by_category(conn, owner_id="alice")` — only includes
   transactions from alice_chk, alice_sv, and shared_cc. Excludes bob_chk.
2. `get_net_worth_history(conn, owner_id="alice")` — includes alice's
   accounts + shared, excludes bob's.
3. `compute_emergency_fund_months(conn, owner_id="bob")` — only bob's
   checking/savings + shared.
4. `get_monthly_cash_flow(conn, owner_id="alice")` — scoped to alice.
5. `get_all_latest_balances(conn, owner_id="bob")` — bob's + shared.
6. All functions with `owner_id=None` return the same results as before
   (backward compatibility).

## Files to Modify

Every `dal/*.py` file listed in Phase A, plus:
- Every `backend/routers/*.py` file that wraps those DAL functions

## Files to Create

1. `tests/test_owner_scoping.py`

## Files NOT to Modify

- `dal/migrations/*` — no schema changes
- `dal/owners.py` — already complete
- `config/owner_config.yaml` — no changes
- Any frontend files — this is backend-only

## Constraints

- Every modified function must remain **fully backward compatible**:
  `owner_id=None` (default) produces identical results to the current
  behavior. No existing test may break.
- The `resolve_account_ids_for_view()` call must happen inside each
  function, not at the router level. Routers pass `owner_id` as a
  string; the DAL resolves it. This keeps the resolution logic in one
  place.
- Shared accounts (`owner_id IS NULL`) must ALWAYS be included in a
  filtered view. "Alice's view" = alice's accounts + shared accounts.
- The `"ours"` view returns ALL accounts (equivalent to `owner_id=None`).
  Routers should treat `owner_id="ours"` the same as no filter.
- Do NOT add caching for `resolve_account_ids_for_view()`. The account
  set is small and the query is fast.
- For assembler functions (`get_monthly_review`, `_build_preliminary`),
  pass `owner_id` to every sub-call. If a sub-call fails with the
  parameter, catch and log (defensive coding for any missed functions).

## Done Checklist

- [ ] All ~30 DAL functions listed in Phase A accept `owner_id` parameter
- [ ] All functions with existing `account_ids` param intersect with owner filter
- [ ] All router endpoints in Phase B pass `owner_id` through
- [ ] Refresh, MFA, documents, owners, user-rules, alerts endpoints unchanged
- [ ] `resolve_account_ids_for_view()` called inside DAL, not router
- [ ] Shared accounts always included in filtered views
- [ ] `owner_id=None` produces identical results to current behavior
- [ ] `tests/test_owner_scoping.py` with 6+ test cases
- [ ] All existing tests still pass (backward compatibility)

## Verification

After completion, Claude will:
1. Grep for `owner_id` across all `dal/*.py` — verify every listed function has it
2. Verify `resolve_account_ids_for_view` is called in DAL, not routers
3. Run existing test suite — confirm 0 regressions
4. Run `tests/test_owner_scoping.py` — confirm all pass
5. Spot-check 3 router endpoints for correct `owner_id` passthrough
