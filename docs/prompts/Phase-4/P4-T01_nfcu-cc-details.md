# P4-T01: NFCU Credit Card Detail Scraping

## Context

You are working on Sentry Finance, a local-first personal finance app.
The NFCU connector (`extractors/nfcu_connector.py`) already has a fully
functional Phase 3 loan detail scraper (`_scrape_loan_details()`) that
navigates to loan account pages and extracts fields like APR, maturity date,
monthly payment, etc. using regex patterns on normalized `inner_text`.

Credit cards at NFCU have a similar account detail page, but the data
points differ: APR (purchase and cash-advance may differ), credit limit,
minimum payment due, payment due date, available credit, and rewards points.
These fields are **not** currently scraped because credit card accounts
are not configured with `wants_loan_details: true` in `owner_config.yaml`.

The `loan_details` table already supports credit card fields — it uses a
generic key-value schema (`account_id`, `field_name`, `field_value`, `as_of`).
No schema changes needed.

## Starting State

- `extractors/nfcu_connector.py` has `_scrape_loan_details()` with regex
  extraction for loan fields (APR, maturity_date, monthly_payment, etc.)
- `loan_details` table: key-value store with `(account_id, field_name, field_value, as_of)`
- `dal/balances.py` has `record_loan_details()` that persists field-value pairs
- `config/owner_config.yaml` defines account configs; credit card accounts
  exist but lack `loan_details` entries
- NFCU renders dollar amounts as split DOM elements (handled by the
  existing text normalization in `_scrape_loan_details()`)

## Task

### 1. Add Credit Card Field Patterns

In `_scrape_loan_details()`, extend the `field_patterns` dict with credit
card-specific fields:

```python
# Credit card fields (added to existing field_patterns dict)
"credit_limit": [
    r"Credit\s+Limit",
    r"Total\s+Credit\s+Line",
],
"available_credit": [
    r"Available\s+Credit",
    r"Credit\s+Available",
],
"minimum_payment": [
    r"Minimum\s+Payment\s+Due",
    r"Minimum\s+Payment",
    r"Min(?:imum)?\s+Due",
],
"purchase_apr": [
    r"Purchase\s+APR",
    r"Purchase\s+Rate",
],
"cash_advance_apr": [
    r"Cash\s+Advance\s+APR",
    r"Cash\s+Advance\s+Rate",
],
"rewards_points": [
    r"Rewards?\s+Points?\s+Balance",
    r"Points?\s+Balance",
    r"Available\s+Points",
],
"statement_balance": [
    r"Statement\s+Balance",
    r"Previous\s+Statement",
    r"Last\s+Statement",
],
```

The existing `_extract_field_value()` helper already handles dollar amounts,
percentages, and dates with its multi-format regex. These new patterns
will work with the existing extraction without modification.

### 2. Update Account Configuration

Add credit card `loan_details` entries to the relevant credit card account
in `config/owner_config.yaml`. The field names must match the keys in
`field_patterns`:

```yaml
- name: "NFCU Visa Signature"
  last4: "XXXX"   # actual last4
  type: credit_card
  balance: true
  transactions: true
  loan_details:
    - apr                  # existing pattern, will match "APR" on CC pages
    - credit_limit
    - available_credit
    - minimum_payment
    - payment_due          # existing pattern, already in field_patterns
    - purchase_apr
    - cash_advance_apr
    - rewards_points
    - statement_balance
```

### 3. Add Fallback for "APR" on Credit Cards

The existing `apr` pattern matches "Current APR", "APR", and "Annual
Percentage Rate". Credit card pages may show multiple APR lines (purchase
vs. cash advance). Ensure the generic `apr` field captures the **first**
APR match (which is typically the purchase APR), and the dedicated
`purchase_apr` and `cash_advance_apr` fields capture their specific values.

If `purchase_apr` resolves to a value but `apr` does not, copy `purchase_apr`
into `apr` before persisting:

```python
if details.get("purchase_apr") and not details.get("apr"):
    details["apr"] = details["purchase_apr"]
```

## Files to Modify

1. `extractors/nfcu_connector.py` — add CC field patterns, APR fallback
2. `config/owner_config.yaml` — add `loan_details` to CC account(s)

## Files NOT to Modify

- `dal/balances.py` — `record_loan_details()` already handles any field name
- `dal/migrations/` — no schema changes needed
- Any frontend files
- Other connector files

## Constraints

- Credit card `_scrape_loan_details()` reuses the **same** code path as
  loans — no separate function needed. The only change is adding patterns
  and enabling the config.
- The split-DOM text normalization (`$\n1,292\n.\n36` → `$1,292.36`) already
  handles credit card pages since they use the same NFCU rendering engine.
- `_extract_field_value()` must NOT be modified — it already handles all
  the value formats needed (dollars, percentages, dates, plain numbers).
- If a field is not found on the page, it should be stored as `None`
  (existing behavior — don't change this).
- The rewards points value is a plain integer (no `$` prefix, no `%` suffix).
  The existing regex in `_extract_field_value()` includes a plain number
  fallback that will handle this.

## Done Checklist

- [ ] Credit card field patterns added to `field_patterns` in `_scrape_loan_details()`
- [ ] `purchase_apr` → `apr` fallback logic added
- [ ] Credit card account in `owner_config.yaml` has `loan_details` configured
- [ ] Existing loan scraping is NOT broken (regression check)
- [ ] `record_loan_details()` called with new field names (no changes to DAL needed)

## Verification

After completion, Claude will:
1. Read `extractors/nfcu_connector.py` and verify new patterns exist in `field_patterns`
2. Read `config/owner_config.yaml` and verify CC account has `loan_details`
3. Verify no changes to `_extract_field_value()` or `dal/balances.py`
4. Run import check: `python -c "from extractors.nfcu_connector import NFCUConnector"`
5. Verify the APR fallback logic is present
