# P1-T04: Net Worth Velocity

## Context

You are working on Sentry Finance, a local-first personal finance app.
The user wants to see how fast their net worth is changing — not just
the number, but the rate. Month-over-month change, rolling 3-month
trend, and rolling 12-month trend. This is the "speedometer" for
the command center dashboard.

## Starting State

- `dal/reports.py` has `get_net_worth_history(conn, months=24)` which
  returns monthly net worth snapshots:
  ```python
  [{"month": "2026-01", "assets": float, "liabilities": float, "net_worth": float}, ...]
  ```
- `derived_summaries` table caches metrics with `UNIQUE(scope, metric, period)`
- The net worth history is reconstructed from `balance_snapshots`,
  `portfolio_snapshots`, and `real_estate` tables

## Task

### 1. New DAL Function

Add to `dal/derived.py`:

```python
def compute_net_worth_velocity(conn: sqlite3.Connection) -> dict:
    """
    Compute rate of net worth change across multiple timeframes.

    Uses get_net_worth_history() to get monthly snapshots, then
    computes velocity metrics.

    Returns:
    {
        "current_net_worth": float,
        "mom_change": float | None,       # Month-over-month $ change
        "mom_pct": float | None,          # Month-over-month % change
        "rolling_3m_change": float | None,  # 3-month $ change
        "rolling_3m_monthly_avg": float | None,  # Avg monthly change over 3 months
        "rolling_12m_change": float | None,  # 12-month $ change
        "rolling_12m_monthly_avg": float | None,  # Avg monthly change over 12 months
        "trend": "accelerating" | "steady" | "decelerating" | "declining" | "insufficient_data",
        "history": [
            {
                "month": "2026-01",
                "net_worth": float,
                "mom_change": float | None,
                "mom_pct": float | None,
            }
        ],
    }
    """
```

**Month-over-month (MoM):**
- `mom_change = current_month_nw - previous_month_nw`
- `mom_pct = (mom_change / abs(previous_month_nw)) * 100` if previous != 0

**Rolling 3-month:**
- `rolling_3m_change = current_nw - nw_from_3_months_ago`
- `rolling_3m_monthly_avg = rolling_3m_change / 3`

**Rolling 12-month:**
- `rolling_12m_change = current_nw - nw_from_12_months_ago`
- `rolling_12m_monthly_avg = rolling_12m_change / 12`

**Trend classification:**
- Compare rolling_3m_monthly_avg to rolling_12m_monthly_avg:
  - `accelerating`: 3m avg > 12m avg AND both positive
  - `steady`: 3m avg within 20% of 12m avg AND both positive
  - `decelerating`: 3m avg < 12m avg AND 3m avg still positive
  - `declining`: 3m avg is negative
  - `insufficient_data`: fewer than 4 months of history

**History array:**
- Return the full monthly history with per-month MoM changes
- This powers the velocity chart on the dashboard

### 2. Store in derived_summaries

Store the key velocity metrics:

```python
for metric, value in [
    ('nw_mom_change', mom_change),
    ('nw_rolling_3m_avg', rolling_3m_monthly_avg),
    ('nw_rolling_12m_avg', rolling_12m_monthly_avg),
]:
    if value is not None:
        conn.execute("""
            INSERT INTO derived_summaries (scope, metric, period, value, computed_at)
            VALUES ('global', ?, NULL, ?, datetime('now'))
            ON CONFLICT(scope, metric, period)
            DO UPDATE SET value = excluded.value, computed_at = excluded.computed_at
        """, (metric, value))
```

### 3. Wire into recompute pipeline

Add to `recompute_for_institution()` after interest cost.

### 4. API Endpoint

Add to `backend/routers/reports.py`:

```python
@router.get("/api/metrics/net-worth-velocity")
def get_net_worth_velocity():
    with get_db() as conn:
        return compute_net_worth_velocity(conn)
```

## Files to Modify

1. `dal/derived.py` — add `compute_net_worth_velocity()`, wire into pipeline
2. `backend/routers/reports.py` — add endpoint

## Files NOT to Modify

- `dal/reports.py` — use `get_net_worth_history()` as-is (read only)
- Any frontend files
- Any connector files
- Database migrations

## Constraints

- Import and call `get_net_worth_history` from `dal/reports` — do NOT
  duplicate the net worth query logic
- Request 24 months of history to ensure 12-month rolling is available
- Handle edge cases: fewer than 2 months (no MoM), fewer than 4 months
  (no 3m rolling), fewer than 13 months (no 12m rolling)
- Use `abs()` for percentage denominators to handle negative net worth
- Round dollar values to 2 decimal places
- Round percentages to 1 decimal place
- The history array should be the most recent 24 months (oldest first)

## Done Checklist

- [ ] `compute_net_worth_velocity()` exists in `dal/derived.py`
- [ ] MoM change computed correctly ($ and %)
- [ ] Rolling 3-month change and monthly average computed
- [ ] Rolling 12-month change and monthly average computed
- [ ] Trend classification logic implemented (accelerating/steady/decelerating/declining)
- [ ] History array includes per-month MoM changes
- [ ] Key metrics stored in `derived_summaries`
- [ ] Function called in `recompute_for_institution()` pipeline
- [ ] API endpoint `GET /api/metrics/net-worth-velocity` functional
- [ ] Handles insufficient history gracefully

## Verification

After completion, Claude will:
1. Read modified files
2. Verify velocity calculations are mathematically correct
3. Verify trend classification thresholds are reasonable
4. Verify `get_net_worth_history` is called, not duplicated
5. Run import check
6. Run functional test with synthetic net worth data
