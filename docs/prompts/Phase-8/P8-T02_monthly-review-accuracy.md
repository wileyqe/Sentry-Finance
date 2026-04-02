# P8-T02: Monthly Review Data Accuracy

## Context

You are working on Sentry Finance, a local-first personal finance app.
An audit found two data accuracy bugs on the Monthly Review page that
make the numbers misleading when a user reviews a past month.

**Bug 1 — `net_worth_change` is always None.**
The monthly review API (`GET /api/review/monthly?month=2025-12`) returns
`net_worth_change: None` even though net worth dropped from ~$447K to
~$408K that month. The delta calculation is either unimplemented or
broken.

**Bug 2 — Spending total includes transfers.**
December 2025 shows $33,862 in spending (+415% vs prior month) because
large transfer transactions ("Household Settlement" $45K, "Year-End
HYSA Adjustment" $19K) are included. The same month excluding transfers
would show ~$6-8K, consistent with prior months. The transfer exclusion
logic used in `get_spending_by_category()` is not applied in the monthly
review's spending computation.

## Starting State

- `dal/review.py` — `assemble_monthly_review()` builds the review data
- `dal/reports.py` — `get_net_worth_history()` returns monthly net worth
  snapshots (working correctly for other pages)
- `dal/reports.py:40` — `_EXCLUDED_FROM_SPEND` set includes "Transfers",
  "Transfer", "Credit Card Payments", etc.
- `dal/cash_flow.py` — `_INCOME_CATEGORIES` and `_EXCLUDED_FROM_SPEND`
  sets (correct)
- The monthly review income calculation works correctly (uses
  `_INCOME_CATEGORIES` properly)

## Task

### 1. Fix `net_worth_change` calculation

**File:** `dal/review.py`

Find where `net_worth_change` is computed (or should be computed) in
`assemble_monthly_review()`. The fix should:

1. Call `get_net_worth_history()` from `dal/reports.py` to get at least
   2 months of net worth data (the target month and the prior month).
2. Compute the delta: `current_month_nw - prior_month_nw`.
3. Compute the percentage: `(delta / prior_month_nw) * 100` if
   `prior_month_nw != 0`, else `None`.
4. Return a dict: `{"amount": delta, "pct": pct_change}`.

If the target month or prior month has no net worth data, return `None`
gracefully (don't crash).

### 2. Fix spending to exclude transfers

**File:** `dal/review.py`

Find where the spending total is calculated in `assemble_monthly_review()`.
The spending query must exclude:

1. Categories in `_EXCLUDED_FROM_SPEND` ("Transfers", "Transfer",
   "Credit Card Payments", "Refunds/Adjustments", "Mortgage", "Auto Loan")
2. Categories in `_INCOME_CATEGORIES` (to avoid counting income as
   spending)
3. Transactions with `transfer_tag IS NOT NULL` (reconciled transfer
   pairs)

Match the exclusion pattern used by `get_spending_by_category()` in
`dal/reports.py` — the monthly review should produce spending numbers
consistent with the Reports and Cash Flow pages.

The spending comparison vs prior month (`mom_change_pct`) must also use
the corrected spending figure.

## Files to Modify

1. `dal/review.py` — fix both net_worth_change and spending calculations

## Files NOT to Modify

- `dal/reports.py` — already has correct helpers to call
- `dal/cash_flow.py` — already correct
- Any frontend files — the API response structure stays the same
- Any migration files — no schema changes

## Constraints

- The `net_worth_change` field in the API response must remain a dict
  with `amount` and `pct` keys (or `None` if insufficient data). Do not
  change the response shape — just populate it correctly.
- The spending exclusion must match `_EXCLUDED_FROM_SPEND` from
  `dal/reports.py` exactly. Import the set, don't duplicate it.
- Owner scoping (`owner_id` parameter) must be respected in both fixes.
- Spending amounts are negative `signed_amount` values. Use
  `ABS(signed_amount)` or `-signed_amount` for display totals.
- All amounts rounded to 2 decimal places.

## Done Checklist

- [ ] `net_worth_change` returns correct delta for Dec 2025
      (~-$39K, approximately -8.7%)
- [ ] `net_worth_change` returns `None` gracefully when data is missing
- [ ] Spending total for Dec 2025 is ~$6-8K, not $33K
- [ ] Transfer categories are excluded from spending
- [ ] Transactions with `transfer_tag` set are excluded from spending
- [ ] MoM spending change % reflects the corrected spending figure
- [ ] Owner scoping preserved
- [ ] All existing tests pass (`pytest tests/ -x --tb=short`)

## Verification

After completion, run:
1. `pytest tests/ -x --tb=short` — all tests pass
2. Seed dummy data and start server (see CLAUDE.md for commands)
3. `curl -s "http://127.0.0.1:8000/api/review/monthly?month=2025-12"` —
   - `spending.total` should be ~$6-8K (not $33K)
   - `spending.mom_change_pct` should be a reasonable number (not +415%)
   - `net_worth_change` should be `{"amount": -38964.82, "pct": -8.7}`
     (approximate)
4. `curl -s "http://127.0.0.1:8000/api/review/monthly?month=2025-11"` —
   - Spending and net_worth_change should both be populated
5. Cross-check: spending total should be close to what the Cash Flow
   page shows for the same month
