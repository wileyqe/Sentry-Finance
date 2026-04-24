# P15-T04 Phase A — Per-Account Data Capture Proposal

> **Status:** Phase A complete (2026-04-18). NFCU walked live; Affirm /
> Fidelity / TSP / Chase / Acorns cataloged from existing code + priors.
> User wrap: "we have the details we came for."

## Session Summary

Deep dive on NFCU via screenshots (4 account-detail pages walked: Travel
Fund savings XXXX, Active Duty Checking XXXX, Visa Signature GO REWARDS
XXXX, New Vehicle Loan XXXX). NFCU surfaces a *remarkable* amount of
detail per account — every deposit account reveals APY + dividend
history, every loan reveals VIN / collateral / payoff amounts /
amortization progress, the CC reveals authorized-user spend limits.

The original T04 scope ("NFCU savings APY") turns out to be the tip of
the iceberg. The richer finding set is captured below, with each item
flagged **Now** / **Later** / **Skip** so Phase B stays contained while
not losing the big opportunities.

## Legend

- **Now** — scope into Phase B (T04 or a spun-out task).
- **Later** — valuable but non-trivial; queued (Phase 18+ or backlog).
- **Skip** — redundant with existing data or low value.
- **Already captured** — flagged for completeness; no work.

---

## NFCU — WALKED LIVE

### Savings (Travel Fund XXXX, detail page with SHOW MORE DETAILS expanded)

| Field | Status | Decision |
|---|---|---|
| Account Type ("Membership Share Savings") | Not captured | **Now** — fixes `accounts.yaml` config drift |
| Account Nickname ("Travel Fund") | Not captured | **Now** — better UI labels |
| Account Number (masked) | Stored via last4 | Skip |
| Routing Number | Not captured | Skip — per-institution, not per-account |
| Available Balance | Captured (one of them) | **Now** — capture *both* avail + current |
| Current Balance | Captured | Already (rename per above) |
| Last Statement Balance + ending date | Not captured | Skip — derivable |
| Previous Statement Cycle Average Balance | Not captured | Skip |
| **APY (0.250%)** | Not captured | **Now** — core T04 goal |
| Dividends Earned (per cycle) | Via transactions | Already captured |
| **Year-to-Date Dividends** | Not captured | **Now** — tax/income validation |
| **Last Year Dividends** | Not captured | **Now** — 1099-INT reconciliation |
| Date Opened | Not captured | **Now** — account-age signals |
| Direct Deposit MANAGE link | — | Skip |
| Beneficiaries | Not captured | Later — partner-planning visibility |

### Checking (Active Duty Checking XXXX)

Same layout as savings, plus:

| Field | Status | Decision |
|---|---|---|
| APY (0.050%) | Not captured | **Now** — checking pays dividends too; APY scope expands to all deposit accounts, not just savings |
| Overdraft Protection (MANAGE link) | Not captured | Later — enrollment status + linked account |
| Direct Deposit (Enrolled status string) | Not captured | **Now** — better than the savings MANAGE-only link |
| Order Checks | — | Skip |

**Config drift finding:** `accounts.yaml` lists `nfcu XXXX` as type
`savings`. The real portal shows it's "Active Duty Checking." Either
the config is stale or the user renumbered accounts. Flag for
reconciliation during Phase B.

### Credit Card (Visa Signature GO REWARDS XXXX)

| Field | Status | Decision |
|---|---|---|
| Current Balance | Captured | Already |
| Last Statement Balance + ending date | `statement_balance` in config | Already |
| Available Credit | `available_credit` in config | Already |
| **Cash Advance Available** | Not captured | **Now** — separate from credit |
| **Cash Advance Limit** | Not captured | **Now** — often has a different APR |
| Credit Limit + INCREASE LIMIT link | `credit_limit` in config | Already |
| Last Payment Amount + date | Via transactions | Already (transactions) |
| **14 Day Payoff Amount + through-date** | Not captured | **Now** — for scenario engine + mortgage simulator (T01) parity |
| Minimum Payment Due + due date | `minimum_payment` in config | Already (+ due date also worth capturing explicitly — **Now**) |
| Interest Rate (13.99% APR) | `purchase_apr` in config | Already |
| **Interest Charged YTD** | Not captured | **Now** — tax reconciliation |
| Date Opened (12/11/2010) | Not captured | **Now** |
| Cards on This Account — primary cardholder (name, last4) | Not captured | Later |
| **Cards on This Account — authorized users** (name, last4, spend limit, spent this period, available credit) | Not captured | Later — new `card_authorized_users` table |
| **10,142pts Rewards** button | `rewards_points` configured but regex doesn't match | **T03 FOLLOW-UP** (bug, see below) |

**🐛 T03 rewards regex bug (latent, follow-up required).** NFCU renders
the rewards count inside a button label formatted `"10,142pts Rewards"`
— digits → `pts` → `Rewards`. The T03 regex in
`extractors/nfcu_connector.py` (`Rewards?\s+Points?\s+Balance` etc.)
expects the label first and the number after. The live NFCU scrape will
silently miss rewards. Tests passed because they verify the DAL/pivot/UI
path, not the extractor regex. **Fix:** add `(\d[\d,]*)\s*pts\s+Rewards`
as a pattern and adjust `_extract_field_value` to accept number-before-
label. Scoped as **P15-T03b** follow-up.

### Auto Loan (New Vehicle Loan XXXX)

| Field | Status | Decision |
|---|---|---|
| Account Type ("New Vehicle Loan") | Partial | **Now** |
| **Collateral Type (TITLE/LIEN - VEHICLE)** | Not captured | **Now** — secured vs unsecured flag |
| **Collateral Description** + **VIN** | Not captured | **Now** — auto-populates P4-T06 `vehicle_assets` (manual entry → scraped) |
| Outstanding Loan Amount | Captured | Already |
| **Original Loan Amount** | `purchase_price` from config (guess) | **Now** — real value |
| Last Statement Balance | Not captured | Skip |
| **Today's Payoff Amount** | Not captured | **Now** — scenario engine |
| **14 Day Payoff Amount + date** | Not captured | **Now** — scenario engine |
| Last Payment Amount + date | Via transactions | Already |
| Monthly Payment Amount | `minimum_payment` | Already |
| **Payments Made (50)** | Not captured | **Now** — amortization progress |
| **Remaining Term (22 months)** | `term_months` from config | **Now** — authoritative value |
| **GAP (No/Yes)** | Not captured | **Now** — insurance flag |
| Current APR (2.040%) | `interest_rate` | Already |
| **Interest Charged YTD** | Not captured | **Now** — 1098 reconciliation |
| Daily Interest Accrual Amount | Not captured | Later — niche |
| Interest Accrued Since Last Payment | Not captured | Later — niche |

### Mortgage (XXXX) — NOT WALKED

Based on NFCU loan-page layout plus mortgage-specific priors, expect:
escrow balance, property tax accrual, insurance accrual, PMI flag (if
any), current APR, remaining term, original loan amount, Today's +
14-day payoff, Interest Charged YTD, property address. HomeSquad link
already powers home-value via P4-T01. **Deferred to T04 Phase B live
verification or to a follow-up task.**

---

## Other Institutions — NOT WALKED (priors from code + prior prompts)

### Affirm

- **APY (4.00%)** — already captured via P4-T03, in `loan_details`
  key-value. **Now — migrate to `apy_history` time-series** (core T04).
- BNPL contract APR / fees — not captured. **Later** if user cares.

### Chase

- No detail scraping today. Covered by T05 (expanded below).

### Fidelity

- **SPAXX cash-sweep 7-day SEC yield** — not captured. **Now** candidate
  if we extend T04 to investment cash sweeps (treat like a savings APY).
- Commissions / ticket charges / margin rates — captured at the account
  scope today? Unknown. **Later** pending walkthrough.
- Dividend schedule / projected income — **Later**.

### TSP

- Lifecycle fund allocation detail (% in G/F/C/S/I) — partial (balance
  only per P13-T08 buckets). **Later** (richer than T04 scope).
- YTD return per fund — **Later** (feeds deferred T02).
- Contribution-rate split (pre-tax vs Roth) — **Later**.
- Loan balance (TSP loan) — **Later** (none outstanding per user's
  accounts.yaml).

### Acorns

- Round-up rule config / multiplier — **Later**.
- Monthly subscription fee ($3/$5/tier) — **Later** (surfaces as
  recurring; low capture value).
- "Found Money" cashback — **Later**.

### DFAS / myPay

- Covered by P2-T04 parser; no new additions expected. **Skip** for now.

---

## Phase B Scope Lock

### Must-do (core T04)

1. `v30_apy_history` migration + `dal/apy_history.py` wrapper (invariants:
   `apy_rate ∈ [0, 100]`, ISO date, `source ∈ {scrape,manual,statement}`).
2. **NFCU all-deposit-account APY scraping** — not just savings. Every
   checking + every savings sub-account. Single `_scrape_deposit_apy`
   that fires from the SHOW MORE DETAILS → Dividend Details section.
3. **Affirm APY → `apy_history` migration** (drop old `loan_details`
   write; no back-compat shim per CLAUDE.md).
4. Seeder generates deterministic `apy_history` rows per deposit account.
5. `dal/freshness.py` includes `MAX(apy_history.as_of)` in the
   per-institution staleness calc.
6. Tests: DAL unit + golden-seed re-baseline (will shift due to new
   table rows).

### Stretch — "easy wins while we're scraping" (T04 scope extension)

Every field below lives on the SAME NFCU deposit-detail page as APY — so
extending the scraper once to grab them all is cheaper than N separate
passes. Estimated +1 day over the must-do scope.

- Deposit accounts: account_type, account_nickname, date_opened,
  dividends_ytd, last_year_dividends, available + current balance,
  direct_deposit_enrolled, overdraft_protection_enrolled
- Credit card: cash_advance_limit, 14_day_payoff, payment_due_date,
  interest_charged_ytd, date_opened
- Auto loan / mortgage: VIN, collateral_description, original_loan_amount,
  today's_payoff, 14_day_payoff, payments_made, remaining_term, gap_flag,
  interest_charged_ytd

**All of the above land in `loan_details` key-value** (latest-wins).
APY is the only time-series value.

### Spun out to separate tasks

- **P15-T03b** — Fix NFCU rewards regex (pts-before-label pattern).
  Tiny — half-day.
- **P15-T05** — Chase CC + checking detail scraping (expanded below).
- **P15-T06** — Account Details UI subsection surfacing everything above.
- **P15-T07** (new, if user approves) — VIN → `vehicle_assets`
  auto-populate on loan refresh. Touches P4-T06 writer path.
- **P15-T08** (new, if user approves) — `card_authorized_users` table
  + NFCU CC authorized-user scraping. Partner-visibility feature.

**User sign-off:** wrap confirmed 2026-04-18. Phase B proceeds with the
must-do list by default; stretch items are go/no-go per user's call at
Phase B kickoff.
