# P3-T01: Seasonal Income Modeling

## Context

You are working on Sentry Finance, a local-first personal finance app.
The current forecasting engine (`dal/forecasting.py`) treats all income as
a flat monthly average. This is inaccurate for the user's actual income
profile, which is a composite of four distinct income streams:

1. **Military pension** — flat monthly, year-round (DFAS deposit)
2. **VA disability compensation** — flat monthly, year-round (VA deposit)
3. **VA education benefits** — episodic flat (on during semesters, off during breaks)
4. **Officiating income** — seasonal (Aug–Mar peak, zero Apr–Jul), variable per-game amounts

Using a simple rolling average for officiating income produces wildly
wrong projections: it overestimates summer months and underestimates
peak season months. The correct model uses a historical seasonal curve.

### Critical: Non-Recurring Lump Sums in Historical Data

The transaction history contains large, real, correctly-categorized income events
that must **NOT** influence the projected income model. They happened, they are in
the record, but they are not expected to recur on a predictable schedule:

1. **VA disability back-pay** — Retroactive lump-sum catch-up payments in the
   $20,000–$30,000 range that appear in the **"VA Benefits"** category — the same
   category as the regular monthly disability check (~$1,000–$3,000/month). These
   occurred at least twice in the lookback window. They are indistinguishable by
   category alone; only transaction magnitude reveals them.

2. **Insurance settlements** — One-time lump sums in the $20,000–$30,000 range.
   These are now categorized as **"Non-Recurring Income"** in `categories.yaml`.
   Older transactions may have landed in "Deposits" or "Uncategorized".

3. **Federal and state tax refunds** — Already categorized as **"Tax Refund"** in
   `categories.yaml`. These appear in Feb–Mar and represent a return of previously
   paid taxes, not a recurring income stream.

Failing to exclude these will cause the model to project $20–30K in income for
the months they occurred, producing completely invalid forecasts. The model must
detect and exclude them before computing any averages or coefficients.

## Starting State

- `dal/forecasting.py` has `get_cash_flow_forecast()` which uses
  `_get_rolling_averages()` for a single flat monthly income estimate
- `dal/reports.py` defines `_INCOME_CATEGORIES` set
- `categories.yaml` has income sub-categories: "Military Pension",
  "VA Benefits", "VA Education Benefits", "Officiating Income"
- `transactions` table has `category`, `posting_date`, `signed_amount`
- `recurring_transactions` table has active recurring income entries

## Task

### 1. New Function: `build_seasonal_income_model()`

Add to `dal/forecasting.py`:

```python
def build_seasonal_income_model(
    conn: sqlite3.Connection,
    lookback_years: int = 2,
) -> dict:
    """
    Build a composite income model with per-stream seasonal curves.

    Analyzes historical transactions by income sub-category to produce
    monthly coefficients for seasonal streams.

    Returns:
    {
        "streams": {
            "pension": {"type": "flat", "monthly": float},
            "disability": {"type": "flat", "monthly": float},
            "education": {"type": "episodic", "monthly": float, "active_months": [1,2,3,8,9,10,11,12]},
            "officiating": {
                "type": "seasonal",
                "annual_total": float,
                "monthly_coefficients": {1: 0.15, 2: 0.12, ..., 12: 0.0},
                    # coefficient = fraction of annual total earned in that month
            },
        },
        "composite_monthly": {1: float, 2: float, ..., 12: float},
            # sum of all streams' projected monthly amounts by calendar month
        "avg_monthly_total": float,
            # for backward compatibility with flat forecasting
        "excluded_transactions": [
            # Transactions present in history but excluded from projections.
            # Callers can surface these in UI to explain why the model
            # differs from raw historical totals.
            {
                "date": "YYYY-MM-DD",
                "category": str,
                "amount": float,
                "reason": str,  # "non_projection_category" | "outlier_lump_sum"
            },
            ...
        ],
        "projection_note": str,
            # Human-readable summary, e.g.:
            # "Excluded 3 transactions totaling $68,412.00 from income model
            #  (2 VA Benefits outliers, 1 Tax Refund). These are in the historical
            #  record but not projected to recur."
    }
    """
```

**Step 0 — Lump-sum exclusion (run before any stream logic):**

Define the exclusion set at module level:
```python
_NON_PROJECTION_INCOME_CATEGORIES = {
    "Tax Refund",          # IRS/state refunds: real but non-recurring
    "Non-Recurring Income", # Insurance settlements, legal proceeds
}
```

Before building any stream, exclude all transactions in these categories from
the working dataset. Log each excluded transaction (date, category, amount).

For income categories that are **also** used by regular recurring payments (specifically
"VA Benefits"), apply **outlier detection** to catch lump-sum back-pay events:

```python
def _exclude_outliers(amounts: list[float], threshold_multiplier: float = 3.0) -> tuple[list[float], list[float]]:
    """
    Split amounts into normal and outlier lists.
    A transaction is an outlier if it exceeds threshold_multiplier × the median
    of all amounts in the series. Returns (normal, outliers).
    """
```

Apply `_exclude_outliers` to the full list of individual transaction amounts for each
flat stream (pension, disability) before averaging. The 3× median threshold is calibrated
for this dataset: a normal VA disability check is ~$1,000–$3,000; a back-pay lump sum is
$20,000+, which is >3× the median regardless of variation in the normal payments.

**Stream classification logic:**
- Query individual `transactions` (not grouped) for the last `lookback_years` years,
  filtered to `_INCOME_CATEGORIES`, excluding `_NON_PROJECTION_INCOME_CATEGORIES`
- Map categories to streams:
  - "Military Pension" → pension (flat)
  - "VA Benefits", "VA Disability" → disability (flat, outlier-filtered)
  - "VA Education Benefits" → education (episodic)
  - "Officiating Income" → officiating (seasonal)
- Any unclassified income categories that survive exclusion → "other" flat stream
- Accumulate all excluded transactions (from category exclusion + outlier detection)
  into the `excluded_transactions` return list

**Seasonal coefficient computation (officiating):**
- Apply `_exclude_outliers` to officiating amounts before computing coefficients
- For each month (1–12), sum the filtered amounts in that month
- Divide each month's total by the grand total to get coefficients
- Coefficients should sum to ~1.0
- If a month has zero historical officiating income, coefficient = 0.0
- Use the annual total from the most recent complete year (or average
  of available years) as the projected annual amount

**Episodic stream (education):**
- Identify months where education income appeared in >50% of the years examined
- Those are "active months"; inactive months project $0
- Active-month amount = average of non-zero months

### 2. Enhance `get_cash_flow_forecast()`

Modify the existing function to accept an optional `use_seasonal=True` parameter:

```python
def get_cash_flow_forecast(
    conn: sqlite3.Connection,
    months: int = 6,
    history_months: int = 3,
    account_ids: Optional[list[str]] = None,
    use_seasonal: bool = False,    # NEW
) -> dict:
```

When `use_seasonal=True`:
- Call `build_seasonal_income_model()` to get per-month income projections
- For each projected month, use `composite_monthly[month_number]` instead
  of the flat `avg_income` value
- Spending projection is unchanged (still flat recurring + discretionary)
- Add `"income_model": "seasonal"` or `"income_model": "flat"` to the
  response dict so the frontend knows which model was used

When `use_seasonal=False` (default — preserve backward compatibility):
- Existing behavior is unchanged
- Add `"income_model": "flat"` to the response

### 3. API Endpoint

Add to `backend/routers/reports.py`:

```python
@router.get("/api/income/seasonal-model")
def get_seasonal_income_model():
    with get_db() as conn:
        return build_seasonal_income_model(conn)
```

Also update the existing `/api/forecast` endpoint (if present) or create:

```python
@router.get("/api/forecast")
def get_forecast(months: int = 6, seasonal: bool = False):
    with get_db() as conn:
        return get_cash_flow_forecast(conn, months=months, use_seasonal=seasonal)
```

## Files to Modify

1. `dal/forecasting.py` — add `build_seasonal_income_model()`, `_exclude_outliers()`, modify `get_cash_flow_forecast()`
2. `backend/routers/reports.py` — add endpoints

## Files NOT to Modify

- `dal/reports.py` — import `_INCOME_CATEGORIES` but don't change it
- `config/categories.yaml` — already has "Tax Refund" and "Non-Recurring Income" categories
- Any frontend files
- Any connector files
- Database migrations (no schema changes needed)

## Constraints

- The seasonal model is **read-only** — it queries historical transactions,
  it does not create or modify any data
- Coefficients must be computed from actual transaction history, not hardcoded
- **Lump-sum exclusion is mandatory, not optional.** The `_NON_PROJECTION_INCOME_CATEGORIES`
  set must be applied before any stream computation. Omitting this will produce
  projections that are off by $20,000–$30,000 in the months lump sums occurred.
- **Outlier detection must apply to the "VA Benefits" / disability stream** using
  the `_exclude_outliers()` helper (3× median threshold). VA disability back-pay
  ($20K–$30K) lands in the same category as the regular monthly check and cannot
  be excluded by category alone.
- `excluded_transactions` must be populated and returned even if empty — callers
  depend on its presence to determine whether the model has been cleaned
- `projection_note` must state the excluded count and dollar total explicitly
- If no officiating income exists in history, the seasonal stream should
  have all-zero coefficients (graceful degradation)
- If fewer than 12 months of history exist, fall back to flat averaging
  for all streams and set `"income_model": "flat_insufficient_data"`
- Existing behavior when `use_seasonal=False` MUST NOT change (this is the
  default — don't break the cash flow page)
- Round all dollar values to 2 decimal places
- Round coefficients to 4 decimal places
- Import `_INCOME_CATEGORIES` from `dal/reports.py` — do NOT duplicate the set
- The `composite_monthly` dict is keyed by integer month (1–12), not string
- `_exclude_outliers()` must be a standalone helper function (not inline) so it
  can be unit-tested independently

## Done Checklist

- [ ] `build_seasonal_income_model()` exists in `dal/forecasting.py`
- [ ] `_NON_PROJECTION_INCOME_CATEGORIES` defined at module level
- [ ] `_exclude_outliers()` helper exists as a standalone function, tested independently
- [ ] "Tax Refund" and "Non-Recurring Income" transactions excluded before all stream computation
- [ ] Outlier detection (3× median) applied to "VA Benefits" / disability stream
- [ ] `excluded_transactions` list populated and returned (empty list if none)
- [ ] `projection_note` string states excluded count and dollar total
- [ ] Correctly classifies income into pension/disability/education/officiating/other streams
- [ ] Seasonal coefficients computed from filtered (outlier-excluded) monthly distribution
- [ ] Episodic stream identifies active vs. inactive months
- [ ] Flat streams use outlier-filtered monthly average
- [ ] `composite_monthly` dict sums all streams per calendar month
- [ ] `get_cash_flow_forecast()` accepts `use_seasonal` parameter
- [ ] When seasonal=True, per-month income varies by calendar month
- [ ] When seasonal=False, behavior is unchanged (backward compatible)
- [ ] API endpoint `GET /api/income/seasonal-model` returns the model
- [ ] API endpoint `GET /api/forecast` supports `seasonal` query param
- [ ] Handles edge cases: no officiating data, insufficient history, zero income

## Verification

After completion, Claude will:
1. Read `dal/forecasting.py` and verify seasonal logic
2. Verify coefficients sum to ~1.0 for seasonal streams
3. Verify backward compatibility (default behavior unchanged)
4. Run import check: `python -c "from dal.forecasting import build_seasonal_income_model, _exclude_outliers"`
5. Write a pytest test with synthetic income transactions and verify:
   - Flat stream produces equal monthly amounts
   - Seasonal stream produces zero in summer months, higher in winter
   - Episodic stream produces zero in inactive months
   - Composite monthly sums all streams correctly
6. Verify forecast with `use_seasonal=True` varies month-to-month
7. Lump-sum exclusion tests — **mandatory**:
   - Inject a synthetic "VA Benefits" transaction of $25,000 alongside 24 months
     of normal $2,000/month VA Benefits payments. Verify: the $25K is in
     `excluded_transactions` with reason "outlier_lump_sum", and the disability
     stream monthly average is ~$2,000 (not inflated by the outlier)
   - Inject a "Tax Refund" transaction of $4,500 in March. Verify: it appears in
     `excluded_transactions` with reason "non_projection_category", and the
     composite_monthly for March is not inflated
   - Inject a "Non-Recurring Income" transaction of $22,000. Verify: excluded,
     not present in any stream average
   - Verify `projection_note` correctly states the count and dollar total of
     excluded transactions
