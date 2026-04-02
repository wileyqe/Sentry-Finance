# P8-T01: Income Accounting Fix

## Context

You are working on Sentry Finance, a local-first personal finance app.
An audit of the UI against dummy data uncovered two critical accounting
bugs that make income figures wrong across the app.

**Bug 1 — Yearly Wrap-Up shows $3,600 income instead of ~$207K.**
The `_INCOME_STREAMS` list in `dal/yearly_wrapup.py` is missing
"Paychecks/Salary" and several other income categories. It only contains
military-specific streams plus Tax Refund. Since the dummy data (and
real data) uses "Paychecks/Salary" as the main income category, the
yearly review finds almost no income and reports a -3,936% savings rate.

**Bug 2 — `get_summary()` ignores its date range for income.**
`dal/reports.py` line 514 hardcodes `get_cash_flow_report(conn, months=1)`
regardless of the `start_date` / `end_date` parameters passed to
`get_summary()`. This means the Dashboard's monthly summary and any
multi-month report summary only ever counts 1 month of income.

## Starting State

- `dal/reports.py:25` — `_INCOME_CATEGORIES` set (correct, includes
  "Paychecks/Salary", "Income", "Interest", etc.)
- `dal/yearly_wrapup.py:17` — `_INCOME_STREAMS` list (incomplete,
  missing "Paychecks/Salary" and 6 other categories)
- `dal/reports.py:514` — `get_summary()` calls
  `get_cash_flow_report(conn, months=1)` regardless of date range
- `dal/cash_flow.py:15` — `_INCOME_CATEGORIES` set (mirrors reports.py)
- `dal/review.py:232` — monthly review income uses `_INCOME_CATEGORIES`
  from `cash_flow.py` (works correctly)

## Task

### 1. Sync `_INCOME_STREAMS` with `_INCOME_CATEGORIES`

**File:** `dal/yearly_wrapup.py`

Replace the hardcoded `_INCOME_STREAMS` list with the canonical
`_INCOME_CATEGORIES` set from `dal/reports.py`. The yearly wrap-up
should recognize the same income categories as the rest of the system.

Current (broken):
```python
_INCOME_STREAMS = [
    "Military Pension",
    "VA Benefits",
    "VA Education Benefits",
    "Officiating Income",
    "Other Income",
    "Non-Recurring Income",
    "Tax Refund",
]
```

Missing categories: "Income", "Paychecks/Salary", "Rental Income",
"Deposits", "Interest", "Investment Income", "Retirement Income".

Fix: Import and use `_INCOME_CATEGORIES` from `dal.reports`, or define
`_INCOME_STREAMS` as a list derived from that set. The iteration at
line 59 (`for stream in _INCOME_STREAMS:`) must still work — it queries
each category individually for current/prior year comparison. Convert
the set to a sorted list for deterministic output order.

### 2. Fix `get_summary()` to use the actual date range

**File:** `dal/reports.py`

The `get_summary()` function (around line 500) currently does:
```python
cash_flow = get_cash_flow_report(conn, months=1, ...)
total_income = sum(m["income"] for m in cash_flow)
```

This ignores `start_date` and `end_date`. Replace the income calculation
with a direct query against the transactions table using the actual date
range:

```python
income_cats = list(_INCOME_CATEGORIES)
ph = ", ".join("?" for _ in income_cats)
row = conn.execute(
    f"""
    SELECT COALESCE(SUM(signed_amount), 0) as total
    FROM transactions
    WHERE status = 'posted' AND transfer_tag IS NULL
      AND signed_amount > 0
      AND category IN ({ph})
      AND posting_date >= ? AND posting_date <= ?
    """,
    income_cats + [start_date, end_date],
).fetchone()
total_income = round(row["total"] or 0, 2)
```

If the function accepts `account_ids` or `owner_id`, apply those filters
to this query as well (match the pattern used by `get_spending_by_category`
in the same file).

Remove the `get_cash_flow_report(conn, months=1)` call from `get_summary`.

## Files to Modify

1. `dal/yearly_wrapup.py` — sync `_INCOME_STREAMS` with canonical set
2. `dal/reports.py` — fix `get_summary()` income calculation

## Files NOT to Modify

- `dal/cash_flow.py` — already correct
- `dal/review.py` — monthly review already works
- `dal/derived.py` — uses correct income categories
- Any migration files — no schema changes

## Constraints

- Do not change the yearly wrap-up output structure. The `income_by_stream`
  array should still contain one entry per category with `stream`, `total`,
  `prior_year`, and `yoy_change_pct` fields.
- The `get_summary()` fix must respect `owner_id` and `account_ids`
  parameters if present, matching the existing function signature.
- Income is identified by `signed_amount > 0` AND category in the income
  set. Do not count negative amounts in income categories.
- Keep `transfer_tag IS NULL` in the income query to exclude reconciled
  transfers.
- All amounts rounded to 2 decimal places.

## Done Checklist

- [ ] `_INCOME_STREAMS` in `yearly_wrapup.py` includes all categories
      from `_INCOME_CATEGORIES` in `reports.py`
- [ ] Yearly wrap-up API returns correct income for 2025 (~$207K total,
      dominated by Paychecks/Salary)
- [ ] Savings rate is no longer -3,936%
- [ ] `get_summary()` uses actual `start_date`/`end_date` for income
- [ ] `get_summary()` no longer calls `get_cash_flow_report(months=1)`
- [ ] Owner/account scoping preserved in the new income query
- [ ] All existing tests pass (`pytest tests/ -x --tb=short`)

## Verification

After completion, run:
1. `pytest tests/ -x --tb=short` — all existing tests pass
2. Seed dummy data: `SENTRY_DB_PATH=data/dummy.db python scripts/seed_dummy_data.py`
3. Start server: `SENTRY_DB_PATH=data/dummy.db python backend/api_server.py`
4. Verify yearly review: `curl -s "http://127.0.0.1:8000/api/review/yearly?year=2025"` —
   `total_income` should be ~$195K+, not $3,600
5. Verify summary: `curl -s "http://127.0.0.1:8000/api/reports/summary?start_date=2025-01-01&end_date=2025-12-31"` —
   `total_income` should match yearly review
6. Verify monthly: `curl -s "http://127.0.0.1:8000/api/reports/summary?start_date=2025-11-01&end_date=2025-11-30"` —
   `total_income` should be ~$15K (one month of pension + VA)
