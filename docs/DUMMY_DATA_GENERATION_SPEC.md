# Sentry Finance — Dummy Data Generation Specification

> **Purpose:** This document is a self-contained specification for an AI system
> to generate a Python script (`scripts/generate_dummy_data.py`) that produces
> all JSON data files needed to seed the Sentry Finance personal finance app
> with 3 years of realistic, multi-user household financial data.
>
> **Output:** A single Python script that, when run, writes all required JSON
> files into the `dummy_data/` directory. The script must be deterministic
> (seeded RNG) so re-runs produce identical output.

---

## 0. Design Overview (Phase 10)

`scripts/seed_dummy_data.py` is the **single command** for populating the
synthetic database. As of Phase 17 it is a canonical trusted fixture, not a
rolling demo seed. These invariants govern the design --- change any of them
and the regression walls in `tests/test_golden_seed.py`,
`tests/test_cashflow_invariants.py`, and the number-trust audit will break.

- **Canonical dates.** The public seeder always emits
  `seed_version = trusted-2026-04-27-v1`, `end_date = 2026-04-27`,
  `reference_date = 2026-04-28`, and `years = 3`. Hidden CLI overrides are
  only for test harnesses; product/dev docs should treat the canonical seed as
  the single synthetic truth.
- **Deterministic manifest.** Every run writes the seed manifest to
  `app_settings.trusted_seed_manifest` and to generated
  `data/trusted_seed_manifest.json`. The manifest records row counts,
  normalized table fingerprints, and the full DB fingerprint.
- **No live market/network inputs.** Synthetic seeding uses deterministic
  fixture/fallback prices and ticker metadata only. yFinance is disabled on
  the seed path.
- **Canonical investment proof fixture.** Investment accounts are seeded from
  round starting balances plus monthly transfers only: Acorns `$10,000` +
  `$500/mo`, Fidelity `$50,000` + `$1,000/mo`, and TSP `$100,000` +
  `$1,500/mo`. The canonical seed emits no investment growth/losses,
  dividends, sells, roundups, account fees, or price-driven variance.
  Holdings, snapshots, tax buckets, and ledger rows are formula-derived from
  those starting balances and transfers.
- **Deterministic IDs and timestamps.** Recurring IDs, reconciliation transfer
  tags, generated metadata timestamps, and post-commit derived outputs are
  stable under the trusted reference date.
- **Round dollars only.** Every amount is drawn from a fixed tier set
  (`{50, 75, 100, 125, 150}` for groceries, etc.) so monthly totals are
  hand-auditable. No arbitrary floats.
- **Pipeline parity.** Generated transactions feed through
  `dal.transactions.upsert_transactions()` --- the **same** code path used
  by live institution connectors --- and then through
  `backend.result_writer.run_post_commit_pipeline()` for
  categorization → reconciliation → recurring detection → derived
  recompute. Anything you observe on a live refresh applies equally to
  the dummy dataset.
- **Sign-handling exercised.** ~3% of grocery/dining purchases emit a
  paired refund a few days later (positive amount in a spending
  category). This is the regression guard for the Phase 10
  cash-flow-mismatch bug --- see `docs/ARCHITECTURE.md` §4.6 Sign Convention.
- **Transfer reconciliation exercised.** Every cross-account transfer
  emits both legs with matched amounts within 1--3 days, which gives
  `dal/reconciliation.py` something real to bind.

Configuration data (owners, institutions, recurring patterns, savings
goals, real estate, vehicles) still lives as static JSON in `dummy_data/`.
Time-series data (transactions, balance snapshots, budgets, credit scores,
investment holdings, portfolio snapshots, vehicle valuations) is
**generated**, not stored. Re-running the seeder resets the DB to the same
trusted fixture and should produce the same full fingerprint.

The rest of this document is the original narrative specification that
seeded the design. Load it when writing a new generator module or
debugging a determinism failure; skip it for routine seeder work. Some dates,
owner names, and old market-return story beats below are legacy narrative
scaffolding, not current canonical seed constants.

---

## 1. Narrative Overview

The data tells the story of a two-person household over 3 calendar years
(2023-01-01 through 2025-12-31). The two people are:

### Alex (Primary Owner — `owner_id: "alex"`)

- **Income:** Salaried professional, $78,000/year at start. Gets a 3% raise
  each January (2024: $80,340; 2025: $82,750). Paid biweekly (26 paychecks/year).
  Net pay per paycheck ≈ 72% of gross (taxes, insurance, retirement).
- **Profile:** Financially stable. Consistent saver. Carries no credit card
  balance month-to-month. Manages the mortgage, auto loan, and primary
  investment accounts.
- **Vehicle:** 2020 Honda Civic, purchased June 2021 for $30,000. Financed
  through Valley Auto Loan. Depreciates ~12% year 1, ~10%/year thereafter.
  All identity fields (make/model/year/VIN/price/date) are SYNTHETIC and
  must not match any real vehicle owned by the household. The synthetic
  VIN lives in `dummy_data/vehicle_assets.json` and is allowlisted in
  `scripts/pii_scan.py`; new VINs anywhere else trip the scanner.

### Jordan (Partner — `owner_id: "jordan"`)

- **Income:** Contract/freelance work, $52,000/year baseline. Paid monthly
  (1st of month). Has two income gaps:
  - **Gap 1:** 2023-08 through 2023-10 (3 months, no income). Triggered by
    contract ending. Picks up a new contract in November.
  - **Gap 2:** 2024-06 through 2024-09 (4 months, no income). Layoff from
    agency. During this gap, credit card debt accumulates. Gets a new position
    in October at $55,000/year (small raise, reflecting market re-entry).
- **Profile:** Tends to spend more on dining and entertainment. During income
  gaps, essential spending continues on credit cards, building balances of
  $3,000–$6,000 that take 4–8 months to pay down after income resumes.
- **Credit score impact:** Score dips ~30 points during/after each gap (high
  utilization), recovers over 6–9 months.

### Household Events Timeline

| Date | Event | Financial Impact |
|------|-------|-----------------|
| 2023-01 | Data starts. Both working. | Baseline spending patterns |
| 2023-03 | Tax refund (federal) | +$2,400 to Alex checking |
| 2023-05 | Summer vacation | $3,200 one-time travel spend (shared) |
| 2023-08 | Jordan Gap 1 starts | Jordan income → $0; CC spending rises |
| 2023-10 | Jordan Gap 1 ends | Jordan resumes income Nov 1 |
| 2023-11 | Holiday spending spike | +40% on dining/gifts/merchandise for Nov-Dec |
| 2024-01 | Alex raise (3%) | Biweekly net increases ~$50 |
| 2024-03 | Tax refund (federal) | +$2,100 to Alex checking |
| 2024-04 | Home repair: new HVAC | $5,800 one-time (Alex checking) |
| 2024-06 | Jordan Gap 2 starts | Jordan income → $0; heavier CC accumulation |
| 2024-09 | Jordan Gap 2 ends | Jordan starts $55k job in October |
| 2024-10 | Market dip (Q3 2024) | Investment values drop ~8% in Oct, recover by Dec |
| 2024-11 | BNPL purchase (Jordan) | $1,100 electronics via Affirm, 6 monthly payments |
| 2025-01 | Alex raise (3%) | Biweekly net increases ~$50 |
| 2025-03 | Tax refund (federal) | +$1,800 to Alex checking |
| 2025-04 | Auto loan paid off | Alex auto loan reaches $0, freed cash goes to savings |
| 2025-07 | Family vacation | $4,500 one-time travel (shared) |
| 2025-10 | Jordan CC debt fully cleared | First month at $0 balance since Gap 2 |
| 2025-12 | Data ends | Year-end state for all accounts |

---

## 2. Institution & Account Structure

### Institutions

Create **6 fictional institutions**. Do NOT use real institution names from the
existing codebase (no NFCU, Chase, Fidelity, etc.).

| `institution_id` | `display_name` | Notes |
|---|---|---|
| `summit` | Summit Credit Union | Banking (checking, savings, CC, mortgage, auto) |
| `coastal` | Coastal Bank | Banking (checking, CC) |
| `vanguard_prime` | Vanguard Prime | Brokerage & retirement |
| `greenleaf` | Greenleaf Investing | Micro-investing (like Acorns) |
| `brighton` | Brighton Savings | High-yield savings |
| `payflex` | PayFlex | BNPL provider |

### Accounts

| `account_id` | Institution | Owner | Type | Name | Notes |
|---|---|---|---|---|---|
| `summit_chk_4501` | summit | alex | checking | Summit Checking | Primary household account, Alex payroll deposits here |
| `summit_sav_7823` | summit | alex | savings | Summit Emergency Savings | Emergency fund target: $25,000 |
| `summit_cc_3341` | summit | **null** (shared) | credit_card | Summit Visa Platinum | Shared household card, always paid in full |
| `summit_mtg_9102` | summit | alex | loan | Summit Home Mortgage | 30-year fixed, 4.25%, originated 2020-09 |
| `summit_auto_6655` | summit | alex | loan | Summit Auto Loan | 60-month, 3.9%, originated 2021-06, pays off April 2025 |
| `coastal_chk_2210` | coastal | jordan | checking | Coastal Checking | Jordan payroll deposits here |
| `coastal_cc_8847` | coastal | jordan | credit_card | Coastal Cash Rewards | Jordan's card — carries balance during gaps |
| `vanguard_inv_5501` | vanguard_prime | alex | investment | Vanguard Brokerage | Index fund portfolio |
| `vanguard_ret_5502` | vanguard_prime | alex | investment | Vanguard 401k Rollover | Retirement account (no new contributions) |
| `greenleaf_inv_1001` | greenleaf | jordan | investment | Greenleaf Invest | Small auto-invest account |
| `brighton_sav_3300` | brighton | **null** (shared) | savings | Brighton HYSA | Shared high-yield savings |
| `payflex_bnpl_0001` | payflex | jordan | loan | PayFlex BNPL | Active only during BNPL contract (Nov 2024–Apr 2025) |

**Note on `owner_id`:** Accounts with `owner_id = null` are shared household
accounts visible in every view (Mine, Partner, Household).

---

## 3. Target End-State Balances (December 31, 2025)

These are the **exact** balances the data must produce. Use these to validate.

| Account | Dec 31 2025 Balance | Notes |
|---|---|---|
| `summit_chk_4501` | $8,245.00 | Stable checking buffer |
| `summit_sav_7823` | $22,100.00 | Emergency fund (grew faster after auto loan payoff) |
| `summit_cc_3341` | -$487.00 | December charges, will be paid Jan |
| `summit_mtg_9102` | -$218,450.00 | ~$12K principal paid over 3 years |
| `summit_auto_6655` | $0.00 | Paid off April 2025 (`is_active = 0`, `closed_at = "2025-04-15"`) |
| `coastal_chk_2210` | $3,820.00 | Jordan checking |
| `coastal_cc_8847` | $0.00 | Finally paid off Oct 2025 |
| `vanguard_inv_5501` | $145,200.00 | Growth from contributions + market returns |
| `vanguard_ret_5502` | $89,400.00 | Market returns only, no contributions |
| `greenleaf_inv_1001` | $8,750.00 | Small but growing |
| `brighton_sav_3300` | $11,600.00 | HYSA accumulation |
| `payflex_bnpl_0001` | $0.00 | Paid off April 2025 (`is_active = 0`, `closed_at = "2025-04-30"`) |

### Net Worth Trajectory (approximate month-end)

| Date | Net Worth | Key Driver |
|---|---|---|
| 2023-01 | ~$28,000 | Starting position (mortgage drags it down) |
| 2023-06 | ~$34,000 | Steady saving + investment growth |
| 2023-12 | ~$42,000 | Recovery after Gap 1, holiday spending offset |
| 2024-06 | ~$52,000 | Growth before Gap 2 |
| 2024-10 | ~$45,000 | Gap 2 + market dip bottom |
| 2024-12 | ~$55,000 | Recovery begins |
| 2025-06 | ~$68,000 | Auto loan payoff frees cash, strong saves |
| 2025-12 | ~$81,000 | Best position, all debt cleared except mortgage |

---

## 4. JSON File Specifications

All files are written to the `dummy_data/` directory. Dates are ISO format
(`YYYY-MM-DD`). Amounts use **signed values**: negative = money out (debits,
loan balances), positive = money in (credits, asset balances).

### 4.1 `Institutions.json`

Array of account objects representing the **current** (end-of-2025) state.

```json
[
  {
    "institution_id": "summit",
    "account_id": "summit_chk_4501",
    "name": "Summit Checking",
    "type": "checking",
    "balance": 8245.00,
    "owner_id": "alex"
  },
  ...
]
```

**Fields:**
- `institution_id`: string — FK to institutions table
- `account_id`: string — PK for accounts table
- `name`: string — display name
- `type`: one of `"checking"`, `"savings"`, `"credit_card"`, `"loan"`, `"investment"`
- `balance`: number — current balance (negative for liabilities)
- `owner_id`: string or `null` — owner FK

Include **all 12 accounts** from the table above. For `summit_auto_6655` and
`payflex_bnpl_0001`, set `balance: 0.0` and add `"is_active": false` and
`"closed_at": "2025-04-15"` / `"2025-04-30"` respectively.

### 4.2 `transactions_dense.json`

Array of individual transactions spanning 2023-01-01 to 2025-12-31.

```json
[
  {
    "account_id": "summit_chk_4501",
    "date": "2023-01-06",
    "amount": 2158.00,
    "merchant": "ACME CORP PAYROLL",
    "category": "Paychecks/Salary"
  },
  {
    "account_id": "summit_chk_4501",
    "date": "2023-01-08",
    "amount": -125.43,
    "merchant": "KROGER #1234",
    "category": "Groceries"
  },
  ...
]
```

**Transaction generation rules:**

#### Income Transactions

| Stream | Account | Frequency | Amount Pattern | Category |
|---|---|---|---|---|
| Alex salary | summit_chk_4501 | Biweekly (every other Friday) | ~$2,158 net (2023), ~$2,222 (2024), ~$2,288 (2025). Add ±$5 jitter per check. | Paychecks/Salary |
| Jordan freelance | coastal_chk_2210 | Monthly (1st) | ~$3,467/mo (2023), $0 during gaps, ~$3,667/mo (Oct 2024+). ±$50 jitter. | Paychecks/Salary |
| HYSA interest | brighton_sav_3300 | Monthly (last day) | Balance × 4.5% APY ÷ 12, rounded to cents | Interest |
| Tax refund | summit_chk_4501 | Annual (mid-March) | $2,400 (2023), $2,100 (2024), $1,800 (2025) | Tax Refund |

#### Recurring Expenses (monthly unless noted)

| Merchant | Account | Day | Amount | Category | Notes |
|---|---|---|---|---|---|
| Summit Home Mortgage | summit_chk_4501 | 1st | -$1,478.00 | Mortgages | Fixed P&I |
| Summit Auto Loan | summit_chk_4501 | 15th | -$612.00 | Loan Payments | Stops after April 2025 |
| DUKE ENERGY | summit_chk_4501 | 5th | -$85 to -$165 (seasonal) | Utilities | Higher Jun-Aug, Dec-Feb |
| SPECTRUM INTERNET | summit_chk_4501 | 12th | -$79.99 | Telephone Services | |
| T-MOBILE | coastal_chk_2210 | 18th | -$85.00 | Telephone Services | |
| GEICO AUTO | summit_chk_4501 | 1st (semi-annual: Jan, Jul) | -$624.00 | Insurance | |
| NETFLIX | summit_cc_3341 | 8th | -$15.99 | Dues and Subscriptions | |
| SPOTIFY | summit_cc_3341 | 15th | -$10.99 | Dues and Subscriptions | |
| AMAZON PRIME | summit_cc_3341 | Annual (Feb) | -$139.00 | Dues and Subscriptions | |
| PLANET FITNESS | coastal_chk_2210 | 20th | -$25.00 | Dues and Subscriptions | |
| Summit Visa Payment | summit_chk_4501 | 25th | Varies (= prior month CC charges) | Credit Card Payments | Always paid in full |
| Coastal CC Payment | coastal_chk_2210 | 28th | Varies (see Jordan debt narrative) | Credit Card Payments | Min payment during gaps |

#### Variable Spending (per month, distributed across random dates)

Generate these as **individual transactions** on random dates throughout each
month. Vary the merchant names (pick from the examples or invent similar ones).

**Alex's spending (from summit_chk_4501 and summit_cc_3341):**

| Category | Monthly Range | Account Split | Notes |
|---|---|---|---|
| Groceries | $450–$600 | 70% checking, 30% shared CC | 4–6 transactions/month |
| Gasoline/Fuel | $120–$180 | checking | 3–4 fill-ups/month |
| Restaurants/Dining | $80–$200 | mix | 2–5 transactions |
| General Merchandise | $50–$300 | shared CC | 1–4 transactions |
| Healthcare/Medical | $0–$150 | checking | 0–1 transactions (sporadic) |
| Home Improvement | $0–$200 | checking | 0–1 transactions |

**Jordan's spending (from coastal_chk_2210 and coastal_cc_8847):**

| Category | Monthly Range | Account Split | Notes |
|---|---|---|---|
| Groceries | $300–$450 | 60% checking, 40% CC | 3–5 transactions |
| Restaurants/Dining | $150–$350 | 70% CC | 4–8 transactions (higher than Alex) |
| Entertainment | $50–$200 | CC | 1–3 transactions |
| Clothing/Shoes | $0–$150 | CC | 0–2 transactions |
| General Merchandise | $50–$250 | CC | 1–3 transactions |
| Personal Care | $30–$60 | CC | 1–2 transactions |

**During Jordan's income gaps:** Spending continues but shifts almost entirely
to `coastal_cc_8847`. Reduce discretionary (entertainment, clothing) by ~50%,
but groceries and essentials stay constant. This causes CC balance to grow
$1,000–$1,500/month during gaps.

**Jordan's CC debt paydown after gaps:**
- After income resumes, Jordan pays minimum + $300–$500 extra per month
- Gap 1 peak: ~$3,200 (CC balance Nov 2023), paid off by Mar 2024
- Gap 2 peak: ~$5,800 (CC balance Oct 2024), paid off by Oct 2025

#### Shared Expenses (brighton_sav_3300)

- Monthly transfer in from summit_chk_4501: $500 (savings contribution)
- Monthly transfer in from coastal_chk_2210: $250 (when Jordan has income)
- These are `category: "Transfers"` on the source accounts, and matching
  positive transfers on brighton_sav_3300

#### One-Time Events (from narrative timeline)

Generate these as single transactions on the specified dates:
- 2023-05-15: Vacation flights/hotel — 2–3 transactions totaling $3,200 on summit_cc_3341, `category: "Travel"`
- 2024-04-10: HVAC replacement — $5,800 on summit_chk_4501, `category: "Home Maintenance"`, merchant "ALL SEASONS HEATING"
- 2024-11-01: PayFlex BNPL purchase — $1,100, merchant "BEST BUY via PayFlex", `category: "Electronics"` (initial charge on payflex_bnpl_0001)
- 2024-11 to 2025-04: 6 monthly BNPL payments of $183.33+interest on payflex_bnpl_0001, `category: "Loan Payments"`
- 2025-07-10: Family vacation — 3–4 transactions totaling $4,500 on summit_cc_3341, `category: "Travel"`

#### Holiday Spending Spikes

November and December of each year: increase General Merchandise by +60%,
Restaurants/Dining by +40%, and add 2–3 "gift" transactions ($30–$150 each)
categorized as `"Charitable Giving"` or `"General Merchandise"`.

#### Transfer Transactions

For every transfer between accounts, generate **two** matching transactions:
- A negative (outflow) on the source account
- A positive (inflow) on the destination account
- Both with `category: "Transfers"` and matching amounts
- Same date

Key transfers:
- Alex → Summit Savings: $400–$600/month from checking (increases to $800/month after auto loan payoff in May 2025)
- Alex → Brighton HYSA: $500/month from checking
- Jordan → Brighton HYSA: $250/month (when employed)
- Alex CC payment: Full balance monthly from summit_chk_4501 to summit_cc_3341
- Jordan CC payment: Varies (full when employed, minimum during gaps)
- Investment contributions: see section 4.4

#### Merchant Name Variety

Use realistic merchant names that match the patterns in the categorization
rules. Examples per category:

- **Groceries:** "KROGER #1234", "ALDI ANYTOWN", "TRADER JOES #567", "MEIJER #42"
- **Restaurants/Dining:** "CHICK-FIL-A #1892", "CHIPOTLE ONLINE", "FIRST WATCH ANYTOWN", "DOORDASH*DASHPASS"
- **Gasoline/Fuel:** "SHELL OIL 34821", "CIRCLE K #1456", "SPEEDWAY 02814"
- **General Merchandise:** "AMAZON.COM*AB12CD", "TARGET #1234", "WALMART SC #5678"
- **Utilities:** "DUKE ENERGY ONLINE", "CITY OF ANYTOWN UTIL"
- **Telephone Services:** "SPECTRUM INTERNET", "T-MOBILE AUTOPAY"

Use 3–5 variants per category so merchant analysis shows realistic grouping.

#### Transaction Volume Target

Aim for approximately **4,500–5,500 total transactions** across all accounts
over the 3-year period. This breaks down roughly as:
- Alex checking: ~1,800 (income + bills + spending)
- Alex/shared CC: ~900
- Jordan checking: ~700
- Jordan CC: ~700
- Savings/HYSA: ~200 (transfers + interest)
- Loans: ~150 (payments)
- Investments: ~50 (contributions)

### 4.3 `balance_snapshots.json`

**Semi-monthly** snapshots (1st and 15th of each month) for every account,
for all 36 months.

```json
[
  {
    "account_id": "summit_chk_4501",
    "date": "2023-01-01",
    "balance_amount": 5200.00
  },
  ...
]
```

**Generation approach:**
1. Set starting balances for Jan 1, 2023 (see Starting Balances below).
2. For each snapshot date, compute the running balance by summing all
   transactions up to that date from the starting balance.
3. Loan balances are negative. Credit card balances are negative.
4. Investment account balances should track the portfolio_snapshots values.

**Starting Balances (January 1, 2023):**

| Account | Jan 1 2023 Balance |
|---|---|
| summit_chk_4501 | $5,200.00 |
| summit_sav_7823 | $12,500.00 |
| summit_cc_3341 | -$320.00 |
| summit_mtg_9102 | -$230,100.00 |
| summit_auto_6655 | -$16,400.00 |
| coastal_chk_2210 | $2,800.00 |
| coastal_cc_8847 | $0.00 |
| vanguard_inv_5501 | $98,000.00 |
| vanguard_ret_5502 | $72,000.00 |
| greenleaf_inv_1001 | $4,200.00 |
| brighton_sav_3300 | $3,500.00 |
| payflex_bnpl_0001 | $0.00 |

**Note:** Balance snapshots for `payflex_bnpl_0001` only exist from 2024-11
through 2025-04.

### 4.4 `portfolio_snapshots` (canonical trusted investment seed)

The active seeder writes account-level investment snapshots directly into the
SQLite `portfolio_snapshots` table. It no longer writes JSON files for this
surface and no longer models market returns.

**Canonical contract:**

| Account | Starting balance | Monthly transfer | Final balance on 2026-04-27 |
|---|---:|---:|---:|
| `acorns_synthetic` | `$10,000` | `$500` | `$28,000` |
| `fidelity_brokerage` | `$50,000` | `$1,000` | `$86,000` |
| `tsp_synthetic` | `$100,000` | `$1,500` | `$154,000` |

Snapshot dates are formula-derived: seed start date, each monthly contribution
posting date, and the canonical end date. Each snapshot has
`cash_balance = 0.0`; `total_account_value` is exactly starting balance plus
all contributions through that date. The trusted fixture currently emits 114
rows: 38 dates across 3 accounts.

### 4.5 `investment_holdings` (canonical trusted investment seed)

The active seeder writes per-ticker holdings directly into SQLite. Every ticker
uses a flat deterministic close price of `$100.00`; market value and cost basis
are equal for every holding row.

**Allocation contract:**

| Account | Tickers | Allocation |
|---|---|---|
| `acorns_synthetic` | `VOO`, `IJH`, `IJR`, `IXUS` | `55%`, `15%`, `15%`, `15%` |
| `fidelity_brokerage` | `AAPL`, `MSFT`, `AMZN`, `GOOG`, `SPG`, `QQQM`, `TGT`, `SBUX` | equal weight |
| `tsp_synthetic` | `TSP_C`, `TSP_S`, `TSP_L2065` | `50%`, `30%`, `20%` |

The trusted fixture currently emits 570 `investment_holdings` rows, 555
`positions_ledger` rows, 11,730 flat `benchmark_prices` rows, 15
`ticker_metadata` rows, and 76 TSP `tax_buckets` rows. The canonical seed emits
no investment account dividends, sells, reinvestments, SPAXX interest, Acorns
roundups, or Acorns account fees. Those live-data concepts remain in production
lineage/tests, but they are not part of the canonical audit fixture.

### 4.6 `recurring_transactions.json`

Known recurring patterns the system should detect.

```json
[
  {
    "account_id": "summit_chk_4501",
    "merchant": "Summit Home Mortgage",
    "category": "Mortgages",
    "expected_amount": -1478.00,
    "frequency": "monthly",
    "last_date": "2025-12-01",
    "next_date": "2026-01-01"
  },
  ...
]
```

Generate entries for all recurring expenses from the table in section 4.2,
plus:
- HYSA interest (monthly)
- Investment auto-contributions (monthly)
- Savings transfers (monthly)

Set `last_date` to the most recent occurrence in 2025-12, and `next_date`
to the expected next occurrence in 2026-01.

For the auto loan: `status: "completed"` with `last_date: "2025-04-15"`.

### 4.7 `loan_details.json`

Loan metadata as key-value fields.

```json
[
  {
    "account_id": "summit_mtg_9102",
    "interest_rate": 4.25,
    "minimum_payment": 1478.00,
    "origination_date": "2020-09-15",
    "due_date_day": 1,
    "purchase_price": 285000,
    "term_months": 360
  },
  {
    "account_id": "summit_auto_6655",
    "interest_rate": 3.9,
    "minimum_payment": 612.00,
    "origination_date": "2021-06-01",
    "due_date_day": 15,
    "purchase_price": 32500,
    "term_months": 60
  },
  {
    "account_id": "payflex_bnpl_0001",
    "interest_rate": 0.0,
    "minimum_payment": 183.33,
    "origination_date": "2024-11-01",
    "due_date_day": 1,
    "purchase_price": 1100,
    "term_months": 6
  }
]
```

### 4.8 `budgets.json`

Monthly budget targets. Generate for **every month** from 2023-01 to 2025-12
(36 months). Use these baseline targets:

```json
{
  "Groceries": 550,
  "Restaurants/Dining": 400,
  "Utilities": 200,
  "Telephone Services": 170,
  "Gasoline/Fuel": 160,
  "General Merchandise": 400,
  "Entertainment": 150,
  "Dues and Subscriptions": 80,
  "Healthcare/Medical": 100,
  "Clothing/Shoes": 100,
  "Home Improvement": 150,
  "Personal Care": 60,
  "Automotive Expenses": 50,
  "Charitable Giving": 50
}
```

Increase all targets by 3% each January (2024, 2025) to reflect inflation
adjustments.

Format:
```json
[
  {"category": "Groceries", "target_amount": 550.0, "month": "2023-01"},
  ...
]
```

### 4.9 `savings_goals.json`

```json
[
  {
    "name": "Emergency Fund",
    "target_amount": 25000.00,
    "current_amount": 22100.00,
    "target_date": "2026-06-30",
    "linked_account_id": "summit_sav_7823"
  },
  {
    "name": "Vacation Fund",
    "target_amount": 5000.00,
    "current_amount": 3200.00,
    "target_date": "2026-07-01",
    "linked_account_id": "brighton_sav_3300"
  },
  {
    "name": "Jordan Student Loan Payoff",
    "target_amount": 6000.00,
    "current_amount": 6000.00,
    "target_date": "2025-10-31",
    "linked_account_id": null
  }
]
```

### 4.10 `credit_scores.json` *(NEW — not in current seed script)*

Monthly credit score snapshots for both owners.

```json
[
  {
    "owner_id": "alex",
    "institution_id": "summit",
    "score": 762,
    "score_type": "FICO",
    "source": "TransUnion",
    "score_date": "2023-01-15"
  },
  ...
]
```

**Alex's score trajectory:**
- Range: 755–780. Very stable. Slight upticks as mortgage ages.
- Pattern: Starts 758, ends 776. Gradual, boring growth. ±3 monthly noise.

**Jordan's score trajectory:**
- Baseline (employed, no debt): 710–730
- During/after Gap 1: drops to ~690 (high utilization). Recovers to 715 by Mar 2024.
- During/after Gap 2: drops to ~670 (higher utilization, longer gap). Recovers to 720 by Dec 2025.
- Monthly ±5 noise on top of trend.

Generate one score per person per month (on the 15th).

### 4.11 `vehicle_assets.json` *(NEW — not in current seed script)*

```json
[
  {
    "id": "civic_2020",
    "make": "Honda",
    "model": "Civic",
    "year": 2020,
    "purchase_date": "2021-06-01",
    "purchase_price": 30000.00
  }
]
```

### 4.12 `vehicle_valuations.json` *(NEW — not in current seed script)*

Quarterly valuations showing depreciation.

```json
[
  {
    "vehicle_id": "civic_2020",
    "valuation_date": "2023-01-01",
    "estimated_value": 26500.00,
    "source": "KBB"
  },
  ...
]
```

Depreciation curve: ~$26,500 (Jan 2023) → ~$24,000 (Jan 2024) →
~$21,800 (Jan 2025) → ~$20,200 (Dec 2025). Quarterly entries, smooth decline.

### 4.13 `real_estate.json` *(NEW — not in current seed script)*

Quarterly home valuations.

```json
[
  {
    "name": "Primary Residence",
    "estimated_value": 295000.00,
    "linked_loan_id": "summit_mtg_9102",
    "source": "estimate",
    "as_of": "2023-01-01"
  },
  ...
]
```

**Trajectory:** $295,000 (Jan 2023) → $305,000 (Jan 2024) → $312,000
(Jan 2025) → $318,000 (Dec 2025). Quarterly entries, steady appreciation
~3%/year.

### 4.14 `owners.json` *(NEW — not in current seed script)*

```json
[
  {"id": "alex", "display_name": "Alex"},
  {"id": "jordan", "display_name": "Jordan"}
]
```

### 4.15 `app_settings.json` *(NEW — not in current seed script)*

```json
{
  "multi_user_enabled": true,
  "refresh_intervals": {},
  "notification_preferences": {
    "budget_alerts": true,
    "staleness_alerts": true,
    "document_nudges": true,
    "bill_reminders": true
  },
  "expected_monthly_docs": [],
  "expected_annual_docs": [],
  "archival_months": 36
}
```

---

## 5. Script Requirements

### 5.1 Architecture

The generated script (`scripts/generate_dummy_data.py`) must:

1. **Be a single Python file** with no external dependencies beyond the
   standard library (use `json`, `random`, `datetime`, `math`, `hashlib`).
2. **Use a fixed random seed** (`random.seed(42)`) for deterministic output.
3. **Write all JSON files** to the `dummy_data/` directory (resolved relative
   to the script's parent directory).
4. **Print a summary** of what was generated (file names, record counts).
5. **Be runnable standalone:** `python scripts/generate_dummy_data.py`

### 5.2 Internal Structure

Organize the script with clear sections:

```python
# 1. Configuration constants (accounts, amounts, dates, etc.)
# 2. Helper functions (date generation, amount jitter, price curves)
# 3. Transaction generators (one function per income/expense stream)
# 4. Balance snapshot generator (derived from transactions)
# 5. Investment data generators
# 6. Supplementary data generators (credit scores, vehicles, real estate)
# 7. Main orchestration function
# 8. File writers
```

### 5.3 Validation

After generating all data, the script should run internal validation:

1. **Balance reconciliation:** For each non-investment account, verify that
   `starting_balance + sum(transactions) ≈ ending_balance` (within $50 tolerance
   for rounding).
2. **No orphan transactions:** Every `account_id` in transactions exists in
   Institutions.json.
3. **Date range:** All transaction dates fall within 2023-01-01 to 2025-12-31.
4. **Investment values:** End-of-period portfolio values match target within 5%.
5. Print validation results before writing files.

### 5.4 Balance Snapshot Derivation

**Critical:** Balance snapshots must be **derived from transactions**, not
independently generated. The script should:

1. Set starting balances for each account on 2023-01-01.
2. Sort all transactions by date.
3. For each snapshot date (1st and 15th), compute the cumulative balance.
4. For investment accounts, use portfolio_snapshots values instead.

This ensures the data is internally consistent.

---

## 6. Seed Script Updates

After `generate_dummy_data.py` produces the JSON files, the existing
`scripts/seed_dummy_db.py` needs to be updated to also seed the new data
types. **Include these updates in the generation script's output or as
a separate section of instructions.**

New seeding functions needed in `seed_dummy_db.py`:

```python
def seed_owners(conn):
    """Seed owners from owners.json"""
    data = _load("owners.json")
    for owner in data:
        conn.execute(
            "INSERT OR IGNORE INTO owners (id, display_name) VALUES (?, ?)",
            (owner["id"], owner["display_name"]))
    conn.commit()

def seed_credit_scores(conn):
    """Seed credit scores from credit_scores.json"""
    data = _load("credit_scores.json")
    for row in data:
        conn.execute("""
            INSERT INTO credit_scores
                (score, score_type, source, institution_id, score_date, as_of)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (row["score"], row["score_type"], row["source"],
              row["institution_id"], row["score_date"], row["score_date"]))
    conn.commit()

def seed_vehicle_assets(conn):
    """Seed vehicles and valuations."""
    vehicles = _load("vehicle_assets.json")
    for v in vehicles:
        conn.execute("""
            INSERT OR REPLACE INTO vehicle_assets
                (id, make, model, year, purchase_date, purchase_price)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (v["id"], v["make"], v["model"], v["year"],
              v["purchase_date"], v["purchase_price"]))
    valuations = _load("vehicle_valuations.json")
    for val in valuations:
        conn.execute("""
            INSERT INTO vehicle_valuations
                (vehicle_id, valuation_date, estimated_value, source)
            VALUES (?, ?, ?, ?)
        """, (val["vehicle_id"], val["valuation_date"],
              val["estimated_value"], val["source"]))
    conn.commit()

def seed_real_estate(conn):
    """Seed real estate valuations."""
    data = _load("real_estate.json")
    for row in data:
        conn.execute("""
            INSERT INTO real_estate
                (name, estimated_value, linked_loan_id, source, as_of)
            VALUES (?, ?, ?, ?, ?)
        """, (row["name"], row["estimated_value"],
              row.get("linked_loan_id"), row.get("source", "estimate"),
              row["as_of"]))
    conn.commit()

def seed_app_settings(conn):
    """Seed app settings from app_settings.json"""
    import json as _json
    data = _load("app_settings.json")
    for key, value in data.items():
        conn.execute("""
            INSERT OR REPLACE INTO app_settings (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
        """, (key, _json.dumps(value)))
    conn.commit()
```

**Updated seeding order** (in `seed_dummy_data()` function):
1. `seed_owners(conn)` — must come before accounts (FK dependency)
2. `seed_accounts(conn)` — update to use `owner_id` from JSON
3. `seed_current_balances(conn)`
4. `seed_balance_snapshots(conn)`
5. `seed_transactions(conn)`
6. `seed_acorns_investments(conn)`, `seed_fidelity_investments(conn)`,
   `seed_tsp_investments(conn)` — write the canonical no-market investment
   fixture
7. `seed_loan_details(conn)`
8. `seed_budgets(conn)`
9. `seed_recurring_transactions(conn)`
10. `seed_savings_goals(conn)`
11. `seed_credit_scores(conn)`
12. `seed_vehicle_assets(conn)`
13. `seed_real_estate(conn)`
14. `seed_app_settings(conn)`
15. `backfill_merchant_column(conn)`
16. `rebuild_merchant_snapshots(conn)`

---

## 7. Checksum / Verification Table

After generation, the script must print this verification summary:

| Metric | Expected Value |
|---|---|
| Total transactions | ~1,600 after post-commit pipeline |
| Accounts | 12 |
| Owners | 2 |
| Balance snapshots | 269 |
| Portfolio snapshots | 114 (3 accounts × 38 formula dates) |
| Investment holdings | 570 |
| Positions ledger | 555 |
| Recurring patterns | 49 |
| Budget entries | 324 |
| Credit scores | 72 (2 people × 36 months) |
| Vehicle valuations | 12 (quarterly × 3 years) |
| Real estate valuations | 12 (quarterly × 3 years) |
| Loan detail records | 53 monthly rows across 3 loans |
| Savings goals | 3 |
| Alex Dec 2025 checking balance | $8,245.00 ± $50 |
| Jordan Dec 2025 checking balance | $3,820.00 ± $50 |
| Jordan CC peak (Gap 2) | $5,500–$6,100 |
| Jordan CC Dec 2025 | $0.00 |
| Mortgage Dec 2025 | -$218,450 ± $500 |
| Acorns Synthetic latest | $28,000.00 |
| Fidelity Brokerage latest | $86,000.00 |
| TSP Uniformed Services latest | $154,000.00 |

---

## 8. What This Data Exercises

Every feature from Phases 0–7 should be visible with this data:

| Phase | Feature | What Exercises It |
|---|---|---|
| P0 | Categorization rules | Merchant names matching categories.yaml patterns |
| P0 | Transfer detection | Paired transfer transactions between accounts |
| P0 | Data freshness | institution_refresh_status timestamps |
| P1 | Emergency fund metric | summit_sav_7823 balance ÷ 6-month spending average |
| P1 | Debt-to-income ratio | Mortgage + auto loan + CC payments ÷ income |
| P1 | Interest cost tracking | Mortgage and auto loan interest from loan_details |
| P1 | Net worth velocity | 36 months of net worth history with clear trend |
| P2 | Document drop | (No dummy docs needed — UI handles this) |
| P3 | Seasonal income | Jordan's income gaps create seasonal patterns |
| P3 | Recurring-to-loan linking | Auto loan payment → summit_auto_6655 |
| P3 | Scenario projection | Enough history for baseline projection |
| P3 | Debt payoff vs invest | Active mortgage + historical auto loan |
| P4 | Credit score history | 36 months of scores for both owners |
| P4 | Vehicle equity | Depreciating Civic vs. auto loan balance |
| P5 | All dashboard KPIs | Net worth, savings rate, emergency runway, credit scores |
| P5 | Transaction teaching | Some "Uncategorized" transactions (5–10 total) to trigger the teach flow |
| P6 | Lifestyle creep | Jordan's dining spending grows over time |
| P6 | Contributions vs performance | Canonical investment contributions are isolated from market gains; market gains are intentionally absent in the trusted fixture |
| P6 | Monthly review | Full month of data for any selected month |
| P6 | Yearly wrap-up | Complete annual data for 2023, 2024, 2025 |
| P7 | Multi-user scoping | Two owners, shared accounts, different financial profiles |
| P7 | Settings page | app_settings seeded with multi_user_enabled = true |
| P7 | View selector | Mine/Partner/Household all show different data |

### Uncategorized Transactions

Intentionally leave **8–12 transactions** across the 3 years with
`category: "Uncategorized"` and unusual merchant names (e.g.,
"TXN*8847261-REF", "POS PURCHASE 11/15", "MISC DEBIT 042"). These let users
test the "teach the system" categorization flow.

---

## 9. Summary

This specification describes a Python script that generates ~15 JSON files
containing 3 years of realistic two-person household financial data. The data
features:

- **One stable earner** (Alex) with consistent saving and investing
- **One variable earner** (Jordan) with two income gaps causing credit card
  debt accumulation and recovery
- **Canonical investment proof fixture** with round starting balances and monthly transfers only
- **Life events** (vacations, home repair, BNPL purchase, auto loan payoff)
- **Seasonal patterns** (utility costs, holiday spending)
- **Multi-user ownership** with shared and individual accounts
- **Predictable end-state balances** for verification

The generated data exercises every feature from Phases 0–7 of the Sentry
Finance platform.
