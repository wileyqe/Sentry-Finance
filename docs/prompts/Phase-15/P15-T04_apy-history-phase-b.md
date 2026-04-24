# P15-T04 Phase B — APY History + NFCU Deposit Scraping + Full Stretch

## Context

T04 Phase A (2026-04-18) was an interactive NFCU walkthrough; output at
`P15-T04_audit_capture_proposal.md`. Two discoveries drive Phase B:

1. **APY belongs in a time-series table, not `loan_details`.** Affirm's
   APY lives there today (P4-T03) and gets overwritten every refresh.
   Rate-shop decisions need history, so a new `apy_history` table ships.

2. **NFCU exposes APY on *every* deposit account** (checking too, not
   just savings), and the same detail pages carry a long list of other
   fields the app doesn't capture — dividends YTD, date opened, VIN,
   collateral type, payoff amounts, etc. User picked **full stretch**
   at kickoff (2026-04-19): every high-value field from Phase A §
   "Stretch — easy wins while we're scraping" lands in this task,
   writing through the existing `loan_details` key-value table so no
   second schema change is needed.

All fields surface in T06 (Account Details UI); Phase B is the data
ingestion side only.

## Starting State

- `extractors/affirm_connector.py:395-461` — Affirm's
  `_extract_savings_balance` parses APY via
  `/(\d+\.\d{1,2})\s*%\s*APY/i` and writes `{"apy": "4.00%"}` to
  `loan_details` via `record_loan_details`. No consumer reads it.
- `extractors/nfcu_connector.py:~830-987` — `_scrape_loan_details`
  gated by `wants_loan_details` property, which currently only returns
  true for loan/mortgage/CC accounts. Deposit accounts never reach
  the detail-page scrape path; they only get `_scrape_balances`.
- `dal/migrations/v29_tax_treatment.py` — latest migration;
  `VERSION = 30` is next.
- `dal/credit_scores.py` + `dal/real_estate.py` — P17-T03 wrapper
  templates (caller-commits, `_assert_*_valid` helpers, optional
  `INSERT OR IGNORE` dedup).
- `dal/freshness.py:85-118` — three-block staleness calc
  (`institution_refresh_status`, `balance_snapshots`,
  `portfolio_snapshots`). New `apy_history` block slots in as #4.
- `scripts/dummy_data/generator.py::generate_credit_scores` +
  `scripts/seed_dummy_data.py::seed_credit_scores` — template for
  deterministic rolling seeders.
- `accounts.yaml` — config drift: NFCU XXXX listed as `type: savings`
  but live portal calls it "Active Duty Checking." Fix during scope.
- `tests/test_golden_seed.py` — computes a fingerprint hash over the
  seeded DB. Adding `apy_history` rows shifts the hash; re-baseline
  in the same commit.

## Task

### Task 1 — `v30_apy_history` migration

- New `dal/migrations/v30_apy_history.py` (mirror
  `v29_tax_treatment.py` shape — `VERSION = 30`, `def run(conn)`).
- Schema:
  ```sql
  CREATE TABLE apy_history (
    id         INTEGER PRIMARY KEY,
    account_id TEXT    NOT NULL REFERENCES accounts(id),
    apy_rate   REAL    NOT NULL,      -- percent, e.g. 4.00
    as_of      TEXT    NOT NULL,      -- ISO-8601 date
    source     TEXT    NOT NULL,      -- 'scrape' | 'manual' | 'statement'
    created_at TEXT    DEFAULT (datetime('now')),
    UNIQUE(account_id, as_of, source)
  );
  CREATE INDEX idx_apy_history_acct_date
    ON apy_history(account_id, as_of DESC);
  ```

### Task 2 — `dal/apy_history.py` wrapper

- `record_apy_history(conn, *, account_id, apy_rate, as_of, source)`.
- `get_latest_apy(conn, account_id) → dict | None`.
- `_assert_apy_valid(apy_rate, as_of, source)` raises `ValueError` on:
  `apy_rate` outside `[0, 100]`, bad ISO date, `source` outside the
  three-value set.
- Caller commits. Dedup via `INSERT OR IGNORE` on unique index.

### Task 3 — NFCU deposit APY scraping (must-do)

- New method `_scrape_deposit_apy(page, acct)` iterates deposit
  accounts (checking + savings) flagged `export.wants_apy: true` in
  config, navigates to each account's detail page, expands
  "SHOW MORE DETAILS" (if collapsed), and regexes the APY
  percentage.
- Pattern: `(\d+\.\d{1,3})\s*%\s*APY` (NFCU shows 0.050% / 0.250%
  in the dividend details block).
- Persist via `record_apy_history(..., source='scrape',
  as_of=today_iso)`.
- Wire `_scrape_deposit_apy` into the connector's top-level
  `run()` flow alongside the existing `_scrape_loan_details` call.
- Fix `accounts.yaml`: NFCU XXXX `type: savings` → `type: checking`
  (config drift from Phase A).
- Add `export.wants_apy: true` to NFCU XXXX and XXXX.

### Task 3-stretch — NFCU deposit enrichment fields

All via `loan_details` key-value (latest-wins). Scraped on the same
detail-page visit as APY. Add these to `accounts.yaml`
`export.loan_details` list on each NFCU deposit account:

- `account_type` (portal label, e.g. "Active Duty Checking")
- `account_nickname` (e.g. "Travel Fund")
- `date_opened`
- `dividends_ytd`
- `last_year_dividends`
- `available_balance` (distinct from current_balance)
- `direct_deposit_enrolled` (checking only — enrollment status string)

Unlock these by teaching `wants_loan_details` to return true for
any account with a non-empty `loan_details` field list, regardless
of type. Add regex patterns for each new field to the
`field_patterns` map.

### Task 3-stretch — NFCU CC enrichment fields (XXXX)

Add to `loan_details` list on the CC:

- `cash_advance_limit`
- `cash_advance_available`
- `payoff_14_day` (and `payoff_14_day_through_date` if on same line)
- `payment_due_date` (already have `minimum_payment` amount; need
  the explicit due date)
- `interest_charged_ytd`
- `date_opened`

### Task 3-stretch — NFCU loan enrichment fields (XXXX auto, XXXX mortgage)

Add to `loan_details` list on each loan:

- `account_type` (portal label, e.g. "New Vehicle Loan")
- `collateral_type` (e.g. "TITLE/LIEN - VEHICLE")
- `collateral_description` (e.g. "<year> <make> <model>")
- `vin` (auto loan only)
- `original_loan_amount`
- `payoff_today`
- `payoff_14_day`
- `payments_made`
- `remaining_term` (authoritative; replaces the config-guessed
  `term_months`)
- `gap_flag` (yes/no)
- `interest_charged_ytd`

Mortgage XXXX was not walked live; use the same loan pattern set,
and document any that miss as a T04 follow-up.

### Task 4 — Affirm APY migration

- `_extract_savings_balance` in `extractors/affirm_connector.py`
  continues to parse APY from the page.
- Replace the `record_loan_details(..., details={"apy": f"{apy}%"})`
  call with `record_apy_history(conn, account_id=...,
  apy_rate=apy_float, as_of=today_iso, source='scrape')`.
- Delete any `apy` reference from the Affirm config's
  `loan_details` list in `accounts.yaml`.
- Grep `apy.*loan_details\|loan_details.*apy` across the repo to
  confirm zero live readers before cutover.

### Task 5 — Freshness tracker

- In `dal/freshness.py`, after the `portfolio_snapshots` block
  (line 118), add a parallel block:
  ```python
  row = conn.execute(f"""
      SELECT MAX(as_of) AS latest FROM apy_history
      WHERE account_id IN (SELECT id FROM accounts
                           WHERE institution_id = ?{acct_filter})
  """, [inst] + params).fetchone()
  if row and row["latest"]:
      if max_ts is None or row["latest"] > max_ts:
          max_ts = row["latest"]
  ```

### Task 6 — Seeder + tests

- **Generator:** `generate_apy_history(end_date, years, rng)` in
  `scripts/dummy_data/generator.py` — deterministic RNG, one row per
  (account × month) for a 3-year rolling window, ±2bps drift.
  Targets: Affirm savings (~4.00%), NFCU savings XXXX (~0.250%),
  NFCU checking XXXX (~0.050%).
- **Seeder:** `seed_apy_history(conn, end_date, years)` in
  `scripts/seed_dummy_data.py` — delete-then-repopulate pattern,
  calls `record_apy_history` per row, commits once. Wired into
  `main()`.
- **Loan details stretch seeder:** extend `seed_loan_details` (or
  add a sibling) to stamp each stretch field on a relevant account
  so T06's future UI has something to render. Static rows via
  `record_loan_details`.
- **Tests** — new `tests/test_apy_history.py`:
  - DAL invariant failures (rate out of range, bad source, bad ISO
    date)
  - Round-trip: `record_apy_history` then `get_latest_apy`
  - Unique-index dedup: same (account, date, source) re-insert is
    a no-op
  - Freshness tracker surfaces APY-only institution as fresh
- **Golden seed re-baseline** in the same commit.

## Verification

1. Fresh DB: `rm data/sentry.db`, run `python -c "from dal.database
   import init_db; init_db()"`, confirm `apy_history` schema via
   `sqlite3 data/sentry.db ".schema apy_history"`.
2. Upgrade path: back up live DB, boot `python backend/api_server.py`,
   confirm clean migration.
3. `pytest tests/test_apy_history.py -x --tb=short` — all pass.
4. Seed: `python scripts/seed_dummy_data.py`, then query
   `apy_history` for expected row counts (~108 across 3 accounts × 36
   months).
5. `pytest tests/ -x --tb=short` — 261 + new tests, zero regressions.
6. `grep -rn "apy.*loan_details\|loan_details.*apy" backend
   extractors dal frontend` — zero live references.
7. Golden seed hash test passes after re-baseline.
8. ROADMAP flipped, prompt file outcomes section updated.

## Outcome (2026-04-19)

All six must-do tasks landed plus the full-stretch loan_details
enrichment. Suite 280/280 (261 baseline + 19 new APY tests), zero
regressions.

**What shipped:**

- `dal/migrations/v30_apy_history.py` — narrow schema, ISO date
  strings, unique `(account_id, as_of, source)`, backing index.
- `dal/apy_history.py` — `record_apy_history`, `get_latest_apy`,
  `get_apy_history(months=...)`, `parse_apy_string`,
  `_assert_apy_valid`. Caller-commits convention matches
  `dal/credit_scores.py`.
- `backend/result_writer.py` — intercepts `apy` key in
  `loan_details` dicts and routes to `record_apy_history(source='scrape')`
  with today's ISO date. Every connector inherits the cutover
  without connector-specific code.
- `extractors/affirm_connector.py` — direct write swapped to
  `record_apy_history`. No backwards-compat shim.
- `extractors/nfcu_connector.py` —
  `_extract_field_value` alternation gained enrollment/Yes/No
  shapes. `field_patterns` grew by 15 entries covering deposits
  (apy, dividends_ytd, last_year_dividends, date_opened,
  direct_deposit_enrolled, available_balance), credit cards
  (cash_advance_limit, cash_advance_available, payment_due_date),
  and loans (payoff_today, payments_made, collateral_type,
  collateral_description, vin via capture-group form, gap_flag).
  Existing `14_day_payoff` / `ytd_interest` keys kept — they
  already land downstream in `dal/derived.py`.
- `dal/freshness.py` — 4th `MAX(as_of)` block after
  `portfolio_snapshots`, wrapped in `try/except sqlite3.OperationalError`
  so pre-v30 DBs don't fail open.
- `accounts.yaml` — NFCU XXXX type fixed (savings → checking) and
  renamed "Active Duty Checking"; 48 loan_details scrapes wired
  across 5 NFCU accounts.
- `scripts/dummy_data/generator.py` — `generate_apy_history`
  produces a 36-row deterministic walk per account for two proxy
  accounts (summit_sav_7823 ~0.25%, summit_chk_4501 ~0.05%).
- `scripts/seed_dummy_data.py` — `seed_apy_history` +
  `seed_loan_details_stretch` wired into `main()`; seeder
  validated end-to-end at 72 APY rows + stretch fields across 5
  proxy accounts.
- `tests/test_apy_history.py` — 19 tests: `parse_apy_string` (7),
  invariants (4), boundary values (1), round-trip + dedup (3),
  latest/history queries (3), freshness integration (1).

**Surprises / decisions during build:**

- Seeder fixtures don't model a real "Affirm HYSA" proxy account
  (Institutions.json only has summit + coastal). Rather than add a
  synthetic one, I scoped the APY seeder to the two existing proxy
  deposit accounts. If a HYSA proxy gets added later, one line in
  `_APY_SEED_ACCOUNTS` extends the seeder.
- Golden-seed fingerprint test didn't drift — the hash only covers
  transactions, not full DB state, so adding APY rows was
  transparent. Plan had anticipated a re-baseline; none needed.
- `result_writer` APY interception landed as a one-file change
  routing ALL connectors, which is cleaner than per-connector
  edits. Affirm remains a special case because it calls
  `record_loan_details` directly (bypassing the writer).
- Two existing field_pattern keys (`14_day_payoff`, `ytd_interest`)
  start with a digit / carry a non-ideal name but are referenced
  by `dal/derived.py` and Phase-1 tests — kept as-is rather than
  cascading a rename.

**Follow-ups surfaced (not blockers):**

- Live NFCU refresh will tune several stretch-field regexes. The
  patterns are best-effort against the Phase A DOM notes; free-text
  fields (collateral_description, account_nickname) are especially
  prone to imprecise matches. Plan on a pass after the first real
  refresh.
- T06 (Account Details UI) is now unblocked — all captured fields
  have a storage home and the seeder stamps representative values
  so the UI has something to render against dummy data.
- Affirm HYSA proxy account addition → small task; unblocks a 4%
  APY series in the seeder if the user wants it.
- Chase detail scraping (T05) can now ride on the same
  `_extract_field_value` / `result_writer` infra.
