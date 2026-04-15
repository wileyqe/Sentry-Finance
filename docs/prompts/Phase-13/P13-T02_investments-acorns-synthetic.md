# P13-T02: Investments — Acorns Synthetic account exists

## Context

P13-T01 shipped a clean strip of the investments feature: three DAL
modules deleted, one router renamed, the `InvestmentsPage` reduced to
a ~30-line empty state, and the seeder emptied of investment
generation. The dev DB ended P13-T01 with zero investment accounts
and zero rows in every investment-surface table.

The user wants to rebuild incrementally, one data source at a time.
The first source is a synthetic account called **"Acorns Synthetic"**
(verbatim name). The user's scope direction for this iteration was
deliberately narrow:

> "The account just needs to exist. Next we'll work on transferring
> money from checking accounts to it. Make it exist. Make it ready
> to receive funds. That is all."

So this task is not about holdings, tickers, portfolio snapshots,
performance, or allocation. It is about adding a single investment
account row to the canonical seed data, making sure the re-seed
cycle preserves it, and giving it a minimal visible surface in the
UI. A future **P13-T03** will wire checking → Acorns Synthetic
transfers.

## Starting State

- Branch `investments-rebuild` at commit `9ef66a3`
  (`feat(investments)!: P13-T01 strip investments to shell`).
- `scripts/dummy_data/generator.py::ACCOUNTS` contained 9 entries
  (no investment or retirement), with a tombstone comment noting
  the P13-T01 removal of three investment accounts.
- `scripts/seed_dummy_data.py::main()` had a hard-reset block that
  DELETEd every investment/retirement account and cascaded through
  `balance_snapshots`, `transactions`, `recurring_transactions`,
  `loan_details`, and `savings_goals`. Safe for P13-T01 but would
  prevent a canonical investment account from surviving a re-seed.
- `frontend/src/pages/InvestmentsPage.tsx` was a ~30-line empty-state
  shell — no API calls, just an icon + title + copy.
- `frontend/src/lib/institutionNames.ts` had a hardcoded
  `INSTITUTION_DISPLAY_NAMES` dict with a fallback of returning the
  raw key unchanged (no title-case fallback). An unknown
  `acorns_synthetic` would render as literal "acorns_synthetic".
- `backend/routers/accounts.py::GET /api/accounts` already returned
  every account regardless of type and threaded `owner_id`. No
  backend changes needed.

## Task

### 1. Seeder — add one canonical investment account

`scripts/dummy_data/generator.py::ACCOUNTS` — replace the P13-T01
tombstone comment with a new entry:

```python
{"institution_id": "acorns_synthetic", "account_id": "acorns_synthetic_0000",
 "name": "Acorns Synthetic", "type": "investment",
 "owner_id": "quintin", "is_active": True, "closed_at": None,
 "starting_balance": 0},
```

`seed_institutions_and_accounts()` auto-creates the
`acorns_synthetic` institution row from unique `institution_id`s in
`ACCOUNTS`. Its display name comes from
`inst_id.replace("_", " ").title()`, which yields "Acorns Synthetic"
— exactly the desired value.

`generate_balance_snapshots()` iterates `ACCOUNTS`. For an account
with no transactions (as is the case for Acorns Synthetic in this
iteration), it emits a single snapshot at `end_date` with
`starting_balance = 0`. No additional seeder logic required.

### 2. Seeder — shrink the hard-reset block

`scripts/seed_dummy_data.py::main()` — remove the
`inv_retire_ids` cascade loop. Keep the five `DELETE FROM` calls
that wipe the investment-surface tables (`investment_holdings`,
`portfolio_snapshots`, `positions_ledger`, `ticker_metadata`,
`benchmark_prices`) since they must stay empty on every re-seed.

The `accounts` table is owned by `seed_institutions_and_accounts()`
upstream; it upserts the canonical list and deactivates
non-canonical rows (`is_active = 0`) so they disappear from the
UI without needing an explicit DELETE. Child tables
(`balance_snapshots`, `transactions`, `recurring_transactions`,
`loan_details`, `savings_goals`) are already wiped by their own
seed functions later in `main()`, so no cascade is needed here
either.

### 3. Frontend — list investment accounts on the Investments page

Rewrite `frontend/src/pages/InvestmentsPage.tsx` (previously ~30
lines of empty state) to:

- Consume `useView()` so the owner chip still filters the page.
- Call `useOwnerApi<{ accounts: Account[] }>("/api/accounts")`.
- Filter client-side to `type === "investment" || type === "retirement"`.
- Handle three states:
  - **Loading:** neutral "Loading investment accounts…" placeholder.
  - **Error:** one-line "Could not load investment accounts" message.
  - **Empty (zero investment accounts):** fall back to a small
    `EmptyShell` component that mirrors the P13-T01 empty-state
    copy, adjusted to say "No investment accounts seeded yet".
  - **Populated:** one `card-l1` card per account, each showing:
    - `trending_up` material icon on the left.
    - Account name (bold, `text-lg`).
    - Institution display name via `institutionDisplayName()`
      (uppercase subtitle).
    - Balance via `formatCurrency()` (right-aligned, `text-2xl`).
    - Status line below the balance: "Ready to receive funds"
      when the balance is zero, otherwise "Active".

The component uses `card-l1` (the project's canonical Tailwind
card class, found in `frontend/src/index.css` line 201 and used
across `BudgetsPage`, `AccountsPage`, `CashFlowPage`). It reuses
`formatCurrency` from `@/lib/formatCurrency` and
`institutionDisplayName` from `@/lib/institutionNames` — no new
format utilities introduced.

### 4. Frontend — institution display name mapping

`frontend/src/lib/institutionNames.ts::INSTITUTION_DISPLAY_NAMES`
gains one entry: `acorns_synthetic: "Acorns Synthetic"`. Without
it, the fallback path returns the raw key, which would render as
literal "acorns_synthetic" in the subtitle.

### 5. Documentation

- This prompt file.
- `docs/ROADMAP.md` — Phase 13 section: flip `P13-T02` from `[ ]`
  to `[v]` with a short verification note. Add a `[ ]` placeholder
  entry for P13-T03 ("Wire checking → Acorns Synthetic transfers").
- `docs/ARCHITECTURE.md` §4.2 — update the "Investment (dormant
  during P13 rebuild)" note to reflect the new partial state: one
  active account, five tables still empty, investment total
  priority rule still dormant pending the analytical rebuild.

## Verification

### 1. Backend import clean

```bash
python -c "from backend.api_server import app; print('OK')"
```

Must print `OK`.

### 2. Seed runs clean

```bash
SENTRY_DB_PATH=data/dummy.db python scripts/seed_dummy_data.py
```

Must complete without a traceback. The table summary should show
`accounts` at 21 rows (up from 20 in P13-T01); `investment_holdings`
and `portfolio_snapshots` remain at 0 rows.

### 3. SQL check — one account, still zero holdings

```bash
python -c "
import sqlite3
conn = sqlite3.connect('data/dummy.db')
cur = conn.cursor()
print('inv_retire_active',
      cur.execute(\"SELECT COUNT(*) FROM accounts WHERE type IN ('investment','retirement') AND is_active=1\").fetchone()[0])
print('acorns_synthetic',
      cur.execute(\"SELECT id,name,type,institution_id,owner_id,is_active FROM accounts WHERE id='acorns_synthetic_0000'\").fetchone())
print('latest balance',
      cur.execute(\"SELECT balance,as_of FROM balance_snapshots WHERE account_id='acorns_synthetic_0000' ORDER BY as_of DESC LIMIT 1\").fetchone())
print('holdings', cur.execute('SELECT COUNT(*) FROM investment_holdings').fetchone()[0])
print('portfolio', cur.execute('SELECT COUNT(*) FROM portfolio_snapshots').fetchone()[0])
"
```

Expected:
- `inv_retire_active = 1`
- `acorns_synthetic` row contains the correct id / name / type /
  institution / owner / is_active=1
- Latest balance for the account is `(0.0, <end_date>)`
- `holdings` and `portfolio` both `0`

### 4. Backend API check

```bash
curl -s http://127.0.0.1:8000/api/accounts | python -c "
import sys, json
data = json.load(sys.stdin)
accts = data.get('accounts', data) if isinstance(data, dict) else data
inv = [a for a in accts if a.get('type') in ('investment','retirement')]
print('investment accounts:', len(inv))
for a in inv:
    print(' ', a.get('id'), a.get('name'), a.get('institution_id'), 'balance=', a.get('balance'))
"
```

Expected: exactly one row, id `acorns_synthetic_0000`, name
"Acorns Synthetic", institution_id `acorns_synthetic`, balance
`0` or `0.0`.

### 5. Frontend page renders the card

Open `http://localhost:1420/investments`. Expected:

- One `card-l1` card rendered.
- `trending_up` icon on the left.
- Title "Acorns Synthetic", subtitle "ACORNS SYNTHETIC".
- "$0.00" balance on the right.
- Sub-text "Ready to receive funds" below the balance.
- Sidebar "Investments" entry is highlighted/active.
- DevTools Network tab: one `/api/accounts` call plus the usual
  bootstrap calls. No `/api/investments/*` calls (those endpoints
  were removed in P13-T01 and have not been re-added).

### 6. Full pytest suite

```bash
python -m pytest tests/ --tb=short
```

Must be 210 passed / 0 failed. Adding an account with zero
transactions does not change the golden-seed fingerprint or the
transaction count — if either fails, re-baseline and note the
drift in the Post-Implementation section below.

### 7. Idempotent re-seed

Re-run `scripts/seed_dummy_data.py` a second time. Output and SQL
counts must match the first run. No duplicate account, no
foreign-key errors, no "row already exists" warnings.

## Post-Implementation Notes

Filled in when the task lands and is marked `[v]` in ROADMAP.
Record actual outcomes, any surprises during verification, and
any follow-ups discovered during implementation that are not
already captured in the P13-T03 placeholder.
