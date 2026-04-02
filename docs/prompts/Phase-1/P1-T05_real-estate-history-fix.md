# P1-T05: Fix Real Estate Static History

## Context

You are working on Sentry Finance, a local-first personal finance app.
The `get_net_worth_history()` function in `dal/reports.py` currently uses
a single real estate value for ALL historical months. This means if the
home was valued at $320K in March 2026, the January 2025 net worth also
shows $320K for real estate — which is wrong.

The `real_estate` table already has an `as_of` column with timestamps
for each valuation. The fix is to use time-appropriate valuations
instead of the latest value for all months.

## Starting State

### real_estate table schema:
```sql
CREATE TABLE real_estate (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    estimated_value REAL NOT NULL,
    linked_loan_id  TEXT REFERENCES accounts(id),
    source          TEXT DEFAULT 'manual',
    as_of           TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);
```

Multiple rows may exist per property (different valuations over time).
The `name` column identifies the property. Source-specific audit records
have `[source]` in the name (e.g., "123 Main St [zillow]") and should
be excluded from the primary valuation — only aggregate rows (name
without brackets) count.

### Current code in `dal/reports.py` (lines 253-263):

```python
# Latest real estate value (static — not time-series yet)
re_row = conn.execute("""
    SELECT SUM(estimated_value) as total FROM real_estate
    WHERE name NOT LIKE '%[%'
      AND id IN (
          SELECT MAX(id) FROM real_estate
          WHERE name NOT LIKE '%[%'
          GROUP BY name
      )
""").fetchone()
re_value = (re_row["total"] or 0) if re_row else 0
```

This is then applied as a constant to every month:
```python
assets = round(banking + portfolio + re_value, 2)
```

### How the function works:

The function uses two CTEs with `RECURSIVE month_series` to generate
a list of months, then JOINs to get the latest balance/portfolio
snapshot for each account at each month. The real estate value is
applied outside the SQL as a constant Python value.

## Task

### Fix the real estate value to be time-aware

Replace the static real estate query with a per-month lookup that
uses the `as_of` date to find the most recent valuation known at
each historical month.

**Approach:**

1. Query all real estate valuations (excluding `[source]` rows):
   ```sql
   SELECT name, estimated_value, as_of
   FROM real_estate
   WHERE name NOT LIKE '%[%'
   ORDER BY as_of ASC
   ```

2. Build a Python lookup: for each month in the history, find the
   most recent valuation per property that has `as_of <= end_of_month`.
   Sum across all properties for that month's real estate total.

3. Replace the static `re_value` constant with a `re_by_month` dict
   mapping `month_str -> total_re_value`.

4. In the result loop, use `re_by_month.get(month, 0)` instead of
   the constant `re_value`.

**Implementation pattern:**

```python
# Build time-aware real estate values per month
re_rows = conn.execute("""
    SELECT name, estimated_value, as_of
    FROM real_estate
    WHERE name NOT LIKE '%[%'
    ORDER BY name, as_of ASC
""").fetchall()

# Group by property, build valuation timeline
from collections import defaultdict
re_timeline: dict[str, list[tuple[str, float]]] = defaultdict(list)
for r in re_rows:
    re_timeline[r["name"]].append((r["as_of"][:7], r["estimated_value"]))

# For each month, find latest known valuation per property
re_by_month: dict[str, float] = {}
# ... iterate over months from the banking_rows result ...
for month_str in [r["month"] for r in banking_rows]:
    total = 0.0
    for prop_name, valuations in re_timeline.items():
        # Find latest valuation at or before this month
        latest = None
        for val_month, val_amount in valuations:
            if val_month <= month_str:
                latest = val_amount
            else:
                break
        if latest is not None:
            total += latest
    re_by_month[month_str] = total
```

Then in the result loop:
```python
re_value_for_month = re_by_month.get(month, 0)
assets = round(banking + portfolio + re_value_for_month, 2)
# ...
"real_estate_assets": round(re_value_for_month, 2),
```

### Also fix `recompute_net_worth()` in `dal/derived.py`

The `recompute_net_worth()` function in `dal/derived.py` (lines 196-208)
has the same static query pattern. This computes the current point-in-time
net worth, so using the latest valuation is correct for this function.
**No change needed here** — the current behavior (latest value) is
correct for point-in-time net worth. Just noting this for awareness.

## Files to Modify

1. `dal/reports.py` — fix `get_net_worth_history()` to use time-aware
   real estate values

## Files NOT to Modify

- `dal/derived.py` — `recompute_net_worth()` is correct as-is (point-in-time)
- Any frontend files
- Any connector files
- Database migrations
- `real_estate` table schema

## Constraints

- Do NOT change the function signature or return shape — existing
  callers expect the same output format
- The result still includes `real_estate_assets` per month — just with
  the correct historical value instead of a constant
- If no real estate valuation exists before a given month, use 0 for
  that month (property hadn't been recorded yet)
- Exclude `[source]` audit rows (name containing `[`)
- Keep the existing CTE queries for banking and portfolio unchanged
- Use `as_of[:7]` (YYYY-MM) for month comparison — do NOT compare
  full timestamps with day precision (valuations apply for the month
  they were recorded until superseded)

## Done Checklist

- [ ] Real estate values in `get_net_worth_history()` are time-aware
- [ ] Each historical month uses the most recent valuation known at that time
- [ ] Months before any valuation exists show 0 for real estate
- [ ] Source audit rows (name with `[`) are still excluded
- [ ] Return shape unchanged (same keys in each dict)
- [ ] `recompute_net_worth()` in `dal/derived.py` NOT modified
- [ ] No changes to function signature or parameter defaults

## Verification

After completion, Claude will:
1. Read modified `dal/reports.py`
2. Trace the logic to verify time-awareness is correct
3. Verify the return shape hasn't changed
4. Verify source audit rows are excluded
5. Run import check
6. Run functional test with multiple real_estate valuations at different dates
