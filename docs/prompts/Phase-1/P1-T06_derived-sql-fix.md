# P1-T06: Derived Metrics SQL Fix

## Context

You are working on Sentry Finance, a local-first personal finance app.
There is a critical bug in `dal/derived.py` where two SQL queries use
Python f-string placeholders (`{excl_placeholders}` and `{inc_placeholders}`)
that are never populated. The format strings are inside raw SQL strings
that are NOT f-strings, so the `{...}` syntax is treated as literal
text — causing SQLite to either error or silently produce wrong results.

This corrupts the per-account monthly spending and income calculations
that feed the derived metrics cache.

## Starting State

### Bug location: `dal/derived.py` lines 48-58 (spending query)

```python
row = conn.execute(
    """
    SELECT COALESCE(SUM(-signed_amount), 0) as total
    FROM transactions
    WHERE account_id = ? AND status = 'posted'
      AND posting_date >= ? AND posting_date < ?
      AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
      AND transfer_tag IS NULL
""",
    (account_id, month_start, month_end),
).fetchone()
```

The `{excl_placeholders}` is literally in the SQL string. It is NOT
an f-string (no `f` prefix), so it becomes the literal text
`{excl_placeholders}` inside the `NOT IN (...)` clause. SQLite treats
this as a single string value, so the exclusion filter effectively
does nothing — ALL categories pass through, meaning transfers,
income, and other non-spending categories are counted as spending.

### Bug location: `dal/derived.py` lines 74-84 (income query)

```python
row = conn.execute(
    """
    SELECT COALESCE(SUM(signed_amount), 0) as total
    FROM transactions
    WHERE account_id = ? AND status = 'posted'
      AND posting_date >= ? AND posting_date < ?
      AND COALESCE(category, 'Other Income') IN ({inc_placeholders})
      AND transfer_tag IS NULL
""",
    (account_id, month_start, month_end),
).fetchone()
```

Same bug: `{inc_placeholders}` is a literal string, so the `IN (...)`
clause matches nothing (no category equals the literal text
`{inc_placeholders}`), making income always 0.

### What should happen

These queries should:
1. Build a proper list of excluded/included categories
2. Generate `?, ?, ?` placeholders for each category
3. Pass the categories as parameters to prevent SQL injection

The correct patterns exist elsewhere in the codebase. See
`dal/reports.py:get_spending_by_category()` (lines 63-64) and
`dal/cash_flow.py:get_monthly_cash_flow()` (lines 88-93) for
working examples.

## Task

### Fix the spending query (lines 48-58)

Replace the broken query with properly parameterized SQL:

```python
# Build exclusion list
excl_cats = list(_EXCLUDED_FROM_SPEND | _INCOME_CATEGORIES)
excl_placeholders = ", ".join("?" for _ in excl_cats)

row = conn.execute(
    f"""
    SELECT COALESCE(SUM(-signed_amount), 0) as total
    FROM transactions
    WHERE account_id = ? AND status = 'posted'
      AND posting_date >= ? AND posting_date < ?
      AND signed_amount < 0
      AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
      AND transfer_tag IS NULL
    """,
    (account_id, month_start, month_end) + tuple(excl_cats),
).fetchone()
```

Note: also add `signed_amount < 0` to the spending query — spending
should only count negative amounts. The current query uses
`SUM(-signed_amount)` which would incorrectly make positive amounts
(income) into negative spending without this guard.

### Fix the income query (lines 74-84)

```python
# Build income category list
inc_cats = list(_INCOME_CATEGORIES | {"Other Income"})
inc_placeholders = ", ".join("?" for _ in inc_cats)

row = conn.execute(
    f"""
    SELECT COALESCE(SUM(signed_amount), 0) as total
    FROM transactions
    WHERE account_id = ? AND status = 'posted'
      AND posting_date >= ? AND posting_date < ?
      AND signed_amount > 0
      AND COALESCE(category, 'Other Income') IN ({inc_placeholders})
      AND transfer_tag IS NULL
    """,
    (account_id, month_start, month_end) + tuple(inc_cats),
).fetchone()
```

Note: also add `signed_amount > 0` to the income query — income
should only count positive amounts.

### Verify the imports

At the top of `dal/derived.py`, there is already:
```python
from dal.reports import _EXCLUDED_FROM_SPEND, _INCOME_CATEGORIES
```

Verify this import is present. If not, add it.

## Files to Modify

1. `dal/derived.py` — fix the two broken queries in `recompute_account_metrics()`

## Files NOT to Modify

- `dal/reports.py` — reference only
- `dal/cash_flow.py` — reference only
- Any frontend files
- Any connector files
- Database migrations

## Constraints

- Use f-strings with `{excl_placeholders}` / `{inc_placeholders}`
  (the same pattern as `dal/reports.py` and `dal/cash_flow.py`)
- Pass category values as query parameters (tuple concatenation),
  never interpolate them directly into SQL
- Add sign guards (`signed_amount < 0` for spending, `> 0` for income)
- Keep the `COALESCE` fallbacks (`'Uncategorized'` for spending,
  `'Other Income'` for income) — they handle NULL categories
- Add `"Other Income"` to the income categories set (consistent with
  `dal/reports.py:get_cash_flow_report()` line 124 which does
  `_INCOME_CATEGORIES | {"Other Income"}`)
- Do NOT change anything else in `recompute_account_metrics()` —
  the month calculation logic, the upsert pattern, and the function
  signature must stay the same

## Done Checklist

- [ ] Spending query uses proper parameterized `NOT IN (?, ?, ...)` with f-string
- [ ] Income query uses proper parameterized `IN (?, ?, ...)` with f-string
- [ ] `_EXCLUDED_FROM_SPEND | _INCOME_CATEGORIES` used for spending exclusions
- [ ] `_INCOME_CATEGORIES | {"Other Income"}` used for income inclusions
- [ ] Category values passed as query parameters (not interpolated)
- [ ] `signed_amount < 0` guard added to spending query
- [ ] `signed_amount > 0` guard added to income query
- [ ] Import of `_EXCLUDED_FROM_SPEND, _INCOME_CATEGORIES` verified present
- [ ] No other changes to the function

## Verification

After completion, Claude will:
1. Read `dal/derived.py`
2. Verify both queries use f-strings with parameterized placeholders
3. Verify category sets match existing conventions in reports.py and cash_flow.py
4. Verify sign guards are present
5. Run `python -c "from dal.derived import recompute_account_metrics"`
6. Run a functional test inserting transactions and verifying correct
   spending/income computation
