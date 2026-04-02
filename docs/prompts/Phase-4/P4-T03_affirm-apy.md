# P4-T03: Affirm HYSA APY Scraping

## Context

You are working on Sentry Finance, a local-first personal finance app.
The Affirm connector (`extractors/affirm_connector.py`) already scrapes HYSA
(High-Yield Savings Account) balance and transactions from `https://www.affirm.com/u/savings`.

The savings page displays the current APY (Annual Percentage Yield) near
the balance — typically something like "4.00% APY" or "Earn 4.00% APY".
This value is **not** currently captured. Storing the APY enables:
- Dashboard display near the HYSA balance ("earning 4.00% APY")
- Interest projection in the forecasting engine
- Historical APY tracking to observe rate changes over time

## Starting State

- `extractors/affirm_connector.py` has `_scrape_hysa()` which calls
  `_extract_savings_balance()` to get available/current/pending balances
  using JavaScript `page.evaluate()` on the savings page DOM
- `_extract_savings_balance()` returns `{"available": float, "current": float, "pending": float}`
- `dal/balances.py` has `record_loan_details()` which stores arbitrary
  key-value pairs in the `loan_details` table — this can be reused for APY
- The `loan_details` table uses a generic `(account_id, field_name, field_value, as_of)` schema

## Task

### 1. Extract APY from the Savings Page

Modify `_extract_savings_balance()` to also capture the APY value.
Add an APY regex to the existing JavaScript `page.evaluate()` block:

```javascript
// APY (near the balance, e.g., "4.00% APY" or "Earn 4.00% APY")
const apyMatch = body.match(
    /(\d+\.\d{1,2})\s*%\s*APY/i
);
if (apyMatch)
    data.apy = parseFloat(apyMatch[1]);
```

Update the return type docstring to include `apy: float | None`.

### 2. Persist APY to `loan_details`

In `_scrape_hysa()`, after recording the balance, persist the APY:

```python
apy = balances.get("apy")
if apy is not None:
    with get_db() as conn:
        record_loan_details(
            conn,
            account_id,
            {"apy": f"{apy}%"},
            run_id=getattr(self, '_current_run_id', None),
        )
        conn.commit()
    print(f"  📈  HYSA APY: {apy}%")
```

### 3. API Endpoint

Add to `backend/routers/reports.py` (or wherever account details are surfaced):

```python
@router.get("/api/accounts/{account_id}/details")
def account_details(account_id: str):
    """Return loan_details fields for an account (APR, APY, etc.)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT field_name, field_value, as_of
               FROM loan_details
               WHERE account_id = ?
               ORDER BY as_of DESC""",
            (account_id,),
        ).fetchall()

    # Deduplicate: latest value per field
    seen = {}
    for r in rows:
        if r["field_name"] not in seen:
            seen[r["field_name"]] = {
                "value": r["field_value"],
                "as_of": r["as_of"],
            }

    return {"account_id": account_id, "details": seen}
```

**Note:** This endpoint is generic — it will also serve credit card details
from P4-T01 and loan details from existing scraping. No Affirm-specific
logic in the API.

## Files to Modify

1. `extractors/affirm_connector.py` — add APY extraction + persistence
2. `backend/routers/reports.py` — add generic account details endpoint

## Files NOT to Modify

- `dal/balances.py` — `record_loan_details()` already handles this
- `dal/migrations/` — no schema changes; `loan_details` is generic
- `config/owner_config.yaml` — no config changes; APY is extracted alongside
  the balance for all savings accounts
- Any frontend files
- Other connector files

## Constraints

- APY extraction should handle edge cases:
  - "4.00% APY" (standard)
  - "Earn 4.00% APY" (marketing copy)
  - APY not visible on page (graceful `None` — log but don't error)
- APY is stored as a string with `%` suffix in `loan_details.field_value`
  (consistent with how APR is stored for loans)
- If APY is `None` (not found), skip persistence — don't store null values
- APY scraping failure must NOT block balance or transaction extraction

## Done Checklist

- [ ] `_extract_savings_balance()` returns `apy` in its result dict
- [ ] `_scrape_hysa()` persists APY to `loan_details` when present
- [ ] APY extraction handles missing APY gracefully
- [ ] Generic `GET /api/accounts/{account_id}/details` endpoint added
- [ ] Existing balance and transaction scraping unchanged
- [ ] Print output includes APY when found

## Verification

After completion, Claude will:
1. Read `affirm_connector.py` and verify APY regex in `_extract_savings_balance()`
2. Verify APY persistence uses `record_loan_details()`
3. Run import check: `python -c "from extractors.affirm_connector import AffirmConnector"`
4. Verify the API endpoint returns a generic details dict
5. Verify no changes to `_extract_savings_transactions()` or balance logic
