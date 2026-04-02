# P0-T03: Transfer Reconciliation Hardening

## Context

You are working on Sentry Finance, a local-first personal finance app.
The transfer reconciliation engine (`dal/reconciliation.py`) matches
cross-institution debit/credit pairs and tags them so they're excluded
from income/spending calculations.

Missed transfers inflate BOTH income and spending. This is a critical
data quality issue because every analytical report depends on accurate
transfer tagging.

Additionally, the owner has a specific pattern: NFCU checking account
0459 is a **dedicated mortgage funding account**. The owner transfers
MORE than the mortgage payment amount each month, intentionally building
a buffer. The excess is earmarked savings, not spending.

## Starting State

- `dal/reconciliation.py` exists with `reconcile_transfers()` function
- Transfer matching criteria: same amount, opposite direction, different
  institutions, within 3 days, at least one has transfer keyword/category
- Keywords list: `_TRANSFER_KEYWORDS` (about 15 keywords)
- Category list: `_TRANSFER_CATEGORIES` (Transfers, Credit Card Payments, Savings)

## Task

### 1. Expand Transfer Keywords

Add these keywords to `_TRANSFER_KEYWORDS` in `dal/reconciliation.py`:

```python
_TRANSFER_KEYWORDS = [
    # Existing keywords (keep all of these):
    "transfer",
    "ach",
    "xfer",
    "fidelity",
    "acorns",
    "tsp",
    "affirm",
    "chase",
    "navy federal",
    "nfcu",
    "direct deposit",
    "payroll",
    # New additions:
    "moneyline",           # NFCU internal transfer product name
    "mobilepay",           # mobile payment transfers
    "real time payment",   # RTP transfers
    "ach credit",          # ACH transfers (credit side)
    "ach debit",           # ACH transfers (debit side)
    "ach payment",         # ACH payment transfers
    "electronic deposit",  # generic electronic deposit
    "online transfer",     # online banking transfer
    "internal transfer",   # same-institution transfer
    "autopay",             # automatic payment (often transfers)
    "auto pay",            # variant
]
```

### 2. Add Same-Institution Transfer Support

Currently, the reconciler requires `t1["institution_id"] != t2["institution_id"]`.
This misses NFCU-to-NFCU transfers (e.g., checking 1167 -> checking 0459
for mortgage funding). Modify the matching logic:

- Keep the different-institution check as the primary path
- Add a SECOND pass for same-institution, different-account transfers
  with stricter criteria:
  - Same institution
  - Different account_id
  - Same absolute amount
  - Opposite directions
  - Within 1 day (tighter window for same-institution)
  - At least one has a transfer keyword/category

### 3. Mortgage Overfunding Pattern

The owner transfers, say, $2,000/month to NFCU 0459, but the mortgage
payment is $1,700. The $300 difference is intentional savings buffer.

This is NOT something the reconciler should handle automatically.
Instead, add a comment block in `reconciliation.py` documenting this
known pattern and noting that the proper solution is in the forecasting
and categorization layers:

```python
# ── Known Patterns ──────────────────────────────────────────────────
# Mortgage overfunding: Owner transfers more than the mortgage payment
# to NFCU 0459 (dedicated mortgage funding account). The transfer is
# correctly tagged. The mortgage payment debit from 0459 is also
# correctly tagged. The excess balance in 0459 is visible in balance
# snapshots and represents earmarked savings, not spending.
#
# No special reconciliation logic needed — the existing same-institution
# transfer matching (added in P0-T03) handles the transfer-in, and the
# mortgage payment is a separate transaction that categorizes as
# "Mortgage" (excluded from spending by _EXCLUDED_FROM_SPEND).
```

### 4. Add Integration Tests

Create a new test file `tests/test_reconciliation.py`:

```python
"""Tests for transfer reconciliation logic."""

# Test 1: Basic cross-institution transfer
# NFCU checking debit $500 + Chase checking credit $500 within 2 days
# -> should be tagged as a pair

# Test 2: Same-institution transfer (new feature)
# NFCU 1167 debit $2000 + NFCU 0459 credit $2000 same day
# -> should be tagged as a pair

# Test 3: Amount mismatch - should NOT match
# NFCU debit $500 + Chase credit $501 -> no match

# Test 4: Same direction - should NOT match
# NFCU debit $500 + Chase debit $500 -> no match

# Test 5: Too far apart in time - should NOT match
# NFCU debit $500 (Jan 1) + Chase credit $500 (Jan 10) -> no match

# Test 6: No transfer keyword on either - should NOT match
# NFCU debit $100 "GROCERY STORE" + Chase credit $100 "REFUND" -> no match

# Test 7: Already tagged - should count as already_tagged, not newly_tagged
```

Implement these tests using an in-memory SQLite database. Set up the
schema by running `init_db()` from `dal.migrations`. Insert test
transactions directly, then call `reconcile_transfers()` and assert
on the returned stats dict and the `transfer_tag` values in the DB.

## Files to Modify

1. `dal/reconciliation.py` --- expand keywords, add same-institution support

## Files to Create

1. `tests/test_reconciliation.py` --- integration tests

## Files NOT to Modify

- `dal/categorization.py`
- `dal/cash_flow.py`
- `dal/reports.py`
- `dal/derived.py`
- Any frontend files
- Any connector files

## Constraints

- The same-institution matching must be a SEPARATE pass after the
  cross-institution pass (not intermixed) to avoid performance issues
  and false positives
- Same-institution matching uses a 1-day window (not 3 days)
- Do not change the integer-cents comparison logic (it's correct)
- Do not change the `processed_ids` deduplication logic
- Preserve the `dry_run` parameter behavior
- Tests must be runnable with `python -m pytest tests/test_reconciliation.py`
- Tests must not require any external database file (use in-memory SQLite)

## Done Checklist

- [ ] `_TRANSFER_KEYWORDS` expanded with all new keywords
- [ ] Same-institution transfer matching added as a second pass
- [ ] Same-institution pass uses 1-day window
- [ ] Known patterns comment block added
- [ ] `tests/test_reconciliation.py` created with all 7 test cases
- [ ] All tests pass
- [ ] Cross-institution matching behavior is unchanged

## Verification

After completion, Claude will:
1. Read the modified `reconciliation.py`
2. Read the test file
3. Run `python -m pytest tests/test_reconciliation.py -v`
4. Verify the same-institution logic is in a separate pass
5. Verify no existing behavior was broken
