# P0-T02: Teach-the-System Flow (Backend)

## Context

You are working on Sentry Finance, a local-first personal finance app.
When transactions arrive with descriptions the system can't categorize
(e.g., "CHECK #1234" or cryptic ACH descriptions), they land as
"Uncategorized." The user needs a way to categorize these and teach
the system to recognize similar transactions in the future.

This task builds the backend (DAL + API) for the teach-the-system flow.
The frontend will be built in a later task.

## Starting State

- `dal/categorization.py` has a 4-layer engine: user override >
  keyword rules > bank category > Uncategorized
- A `category_overrides` table exists in the schema (V6 migration)
- `dal/recurring.py` detects recurring transactions by merchant +
  frequency analysis
- `dal/merchant_normalizer.py` normalizes merchant names
- `backend/routers/` contains API route files

## Requirements

### 1. User Categorization Rule API

Create a new set of DAL functions in a new file `dal/user_rules.py`:

```python
def create_user_rule(
    conn,
    transaction_id: str,       # the transaction that triggered this
    category: str,             # user-assigned category
    merchant_name: str,        # user-assigned merchant name (e.g., "City Water")
    match_type: str,           # "exact_amount", "amount_range", "description"
    match_value: dict,         # depends on match_type (see below)
) -> int:
    """Create a user categorization rule.

    match_type + match_value:
      "exact_amount"  -> {"amount": 105.00, "tolerance": 2.00}
      "amount_range"  -> {"min_amount": 45.00, "max_amount": 65.00}
      "description"   -> {"pattern": "CHECK.*1234"}  (rare, for specific payors)

    Rules are stored in a new table and applied during categorization
    AFTER user overrides but BEFORE keyword rules.
    """
```

```python
def apply_user_rules(conn, transaction: dict) -> str | None:
    """Try to match a transaction against user-created rules.
    Returns the category if matched, None otherwise."""
```

```python
def get_user_rules(conn) -> list[dict]:
    """List all user-created categorization rules."""
```

```python
def delete_user_rule(conn, rule_id: int) -> None:
    """Delete a user rule."""
```

### 2. New Database Table

Create a new migration file `dal/migrations/v13_user_rules.py`:

```sql
CREATE TABLE IF NOT EXISTS user_categorization_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    merchant_name TEXT NOT NULL,
    match_type TEXT NOT NULL,          -- "exact_amount", "amount_range", "description"
    match_amount REAL,                 -- for exact_amount matching
    match_tolerance REAL DEFAULT 2.0,  -- for exact_amount: +/- tolerance
    match_min_amount REAL,             -- for amount_range matching
    match_max_amount REAL,             -- for amount_range matching
    match_pattern TEXT,                -- for description matching (regex)
    source_account_id TEXT,            -- optional: only match in this account
    is_recurring INTEGER DEFAULT 0,    -- user marked this as recurring
    occurrence_count INTEGER DEFAULT 0,-- how many times this rule has matched
    created_from_txn_id TEXT,          -- the transaction that spawned this rule
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

Update `SCHEMA_VERSION` to 13 in `dal/migrations/__init__.py`.

### 3. Integration with Categorization Engine

Modify `dal/categorization.py` to add user rules as layer 1.5
(after user overrides, before keyword rules):

```
1. User override (category_overrides table) -- per-transaction
2. User rules (user_categorization_rules table) -- pattern-based  <-- NEW
3. Keyword rules (categories.yaml)
4. Bank-provided category
5. Fallback: "Uncategorized"
```

When a user rule matches, it should also set the `merchant` field on
the transaction (if the transactions table has one) or update the
description normalization.

### 4. API Endpoints

Create a new router file `backend/routers/user_rules.py`:

- `POST /api/transactions/{txn_id}/categorize` --- apply category +
  merchant name to a transaction and optionally create a rule
  Request body:
  ```json
  {
    "category": "Utilities",
    "merchant_name": "City of Anytown Water",
    "create_rule": true,
    "match_type": "amount_range",
    "match_value": {"min_amount": 45.00, "max_amount": 65.00},
    "mark_recurring": true
  }
  ```

- `GET /api/user-rules` --- list all user rules
- `DELETE /api/user-rules/{rule_id}` --- delete a rule

### 5. Recurring Integration

When `mark_recurring` is true in the categorize request:
- Create the user categorization rule as above
- Also create an entry in `recurring_transactions` table with:
  - merchant = the user-provided merchant_name
  - category = the user-provided category
  - frequency = estimated from match_type (monthly for checks in
    a consistent range, quarterly if amount suggests it, or let
    the existing `detect_recurring()` pick it up on next scan)
  - status = "active"
  - amount_stable = 1 if exact_amount, 0 if amount_range

## Files to Create

1. `dal/user_rules.py` --- new DAL module
2. `dal/migrations/v13_user_rules.py` --- schema migration
3. `backend/routers/user_rules.py` --- API router

## Files to Modify

1. `dal/categorization.py` --- insert user rules as layer 1.5
2. `dal/migrations/__init__.py` --- register v13, update SCHEMA_VERSION
3. `backend/api_server.py` --- register the new router

## Files NOT to Modify

- `config/categories.yaml` --- keyword rules are separate from user rules
- `dal/recurring.py` --- use its existing functions, don't modify them
- `dal/derived.py` --- not relevant to this task
- Any frontend files
- Any connector/extractor files

## Constraints

- Follow the existing code patterns exactly:
  - Use `sqlite3.Connection` parameter style (not ORM)
  - Use `logging.getLogger("sentry.dal.user_rules")` naming
  - Use `get_db()` context manager in API routes
  - Row factory returns dicts (sqlite3.Row)
- The migration must be idempotent (use IF NOT EXISTS)
- User rules must not break existing categorization for transactions
  that already have categories --- only apply to "Uncategorized"
  transactions or when explicitly re-categorizing
- When a user rule matches, log it: `log.debug("User rule %d matched: %s -> %s", ...)`
- API routes follow existing patterns in `backend/routers/` --- look at
  any existing router for the style (FastAPI dependency injection, etc.)

## Done Checklist

- [ ] `dal/user_rules.py` exists with create, apply, get, delete functions
- [ ] `dal/migrations/v13_user_rules.py` creates the table
- [ ] `dal/migrations/__init__.py` registers v13 and SCHEMA_VERSION = 13
- [ ] `dal/categorization.py` calls `apply_user_rules()` as layer 1.5
- [ ] `backend/routers/user_rules.py` exposes 3 API endpoints
- [ ] `backend/api_server.py` registers the new router
- [ ] POST categorize endpoint updates the transaction AND optionally
      creates a rule AND optionally creates a recurring entry
- [ ] No existing categorization behavior is broken

## Verification

After completion, Claude will:
1. Read all created/modified files
2. Verify the migration SQL is valid
3. Verify the categorization priority order is correct
4. Verify API endpoint signatures match the specification
5. Check that existing router patterns are followed
6. Run `python -c "from dal.user_rules import *"` to verify imports
