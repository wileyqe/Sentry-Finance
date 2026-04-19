# P15-T05 — Chase Detail Scraping (Phase B build)

## Context

NFCU finished T03 + T04 with per-account enrichment writing through
`loan_details` + the Phase B `apy_history` table. Chase had no analog:
balances, transaction CSVs, and a VantageScore scrape, but nothing on
per-card APRs, credit limits, statement balances, APY, or next-closing
dates. T05 closes that gap for the two configured Chase accounts.
Phase A (`docs/prompts/Phase-15/P15-T05_audit_capture_proposal.md`)
walked the live Chase portal and spec'd the Phase B field catalogue;
this document is the build outcome.

Intended outcome: after a Chase refresh, `loan_details` carries rows
for Chase checking 8973 (APY routed to `apy_history` via
`result_writer`) and Chase credit card 8115 (APR, credit limits, cash
advance lines, statement + payment info). Surfacing lives in T06.

## Starting State

- `extractors/chase_connector.py` had 3 phases: balances, transaction
  CSVs, credit score. No detail scrape. Class docstring claimed 2
  phases and was already stale.
- `accounts.yaml` had both Chase entries mis-named AND mis-typed:
  8973 listed as "Sapphire / credit", 8115 listed as "Checking". Phase
  A confirmed 8973 is actually **Premier Plus Checking** and 8115 is
  **Slate Edge** credit card — the original "Sapphire" label was stale
  synthetic-data naming.
- `extractors/selector_registry.yaml` had `chase.login/overview/download/popups/logout`
  groups but no detail-page selectors.
- Phase A audit artifacts + throwaway helper (`scripts/audit_chase.py`,
  `raw_exports/chase/audit_*.txt`) cleaned up at user request after
  the capture proposal landed.
- Baseline suite: 280 tests green before T05.

## Task

### What shipped

- **`accounts.yaml` rewrite.** Both Chase entries rebuilt from scratch:
  8973 → `name: Premier Plus Checking, type: checking` with a
  5-field `loan_details` list (available_balance, present_balance,
  apy, ytd_interest, last_statement_date). 8115 →
  `name: Slate Edge, type: credit` with a 14-field list covering
  APRs, credit limits, cash advance lines, statement balances,
  payment info, and closing date.
- **`chase.detail.*` selector group.** Three selector subgroups:
  `more_dropdown` (left-rail More button, checking nav), `account_details_link`
  (direct Account details link for CC + menu item for checking), and
  `cc_hydration_anchor` (stability anchor for the render-lagged
  `<a>` tooltip labels on the CC detail view).
- **`_scrape_account_details` method.** Mirrors NFCU's
  `_scrape_loan_details` shape but with Chase-specific navigation:
  click account tile → land on activity view → navigate via direct
  link or More dropdown to the details sub-URL → wait for CC
  hydration anchor if credit-type → dump `inner_text("body")` →
  regex via `field_patterns` → accumulate into
  `self._result_loan_details`. Per-account try/except isolation.
- **`_navigate_to_account_details` helper.** Two-attempt strategy:
  direct link first (CC), More-dropdown fallback (checking). Uses
  `resilient_find` with `allow_ai=False` so the AI backstop isn't
  spammed on early rollouts.
- **`_extract_field_value` staticmethod on ChaseConnector.** Chase-local
  copy of NFCU's helper, diverged in two ways driven by Phase A
  findings:
  1. Walks by **line boundaries** (`[^\n]*\n(?:[^\n$%]*\n)?`) instead
     of a flexible char gap. Chase puts label and value on separate
     lines, with an optional subtitle line between (e.g. "as of 12:00
     AM ET on 04/17/2026" between "Available balance" and its value).
     Line-boundary walking prevents subtitle fragments from being
     captured as the value.
  2. **No plain-number fallback** in the value alternation, and
     **case-sensitive flag matching** via inline `(?-i:...)`. Both
     prevent subtitle collisions — the plain-number branch was
     grabbing "12" from "12:00 AM", and the flag branch was grabbing
     the lowercase word "on" from "on 04/17/2026" before the real
     dollar value on the next line.
- **Phase 3 wired into `_trigger_export`.** Inserted between Phase 2
  (transactions) and the former Phase 3 (credit score), which is now
  Phase 4. Gated on `a.wants_loan_details` — same property NFCU uses,
  works unchanged for non-loan types since Phase B of T04.
- **`tests/test_chase_extractor.py`.** 19 tests covering every field
  in the Phase A catalogue: 5 checking (incl. the interposing-timestamp
  regression case) + 12 CC (incl. the value-first payment_due_date
  capture from the minimum-payment line) + 2 negative cases.

### Explicitly dropped (from original plan scope)

Per Phase A walkthrough + user decisions:

- `14_day_payoff` — not surfaced on Chase CC details view.
- `ytd_interest` (CC) — not surfaced; derivable from `INTEREST
  CHARGED` transaction rows.
- `date_opened` — not surfaced on either account.
- `direct_deposit_enrolled` — not surfaced; user confirmed static =
  yes, not worth scraping.
- `overdraft_protection` — already dropped at plan time (decision #7
  in the upstream plan).
- `rewards_points` — Slate Edge is not a rewards card.

### Surprises + what we learned

- **Accounts config was wrong, not just incomplete.** Walking the
  live portal flipped both account identities. Phase B had to do a
  full rewrite of the Chase yaml block, not a targeted append.
- **Chase hides metadata behind one more click than NFCU.** The
  default tile click lands on transaction activity; detail metadata
  lives at `…/summary/details/…` (checking) or
  `…/accountDetails/details/…` (CC). Two distinct nav paths required
  a two-attempt strategy in `_navigate_to_account_details` rather
  than one reusable flow.
- **Chase's CC details view render-lags its `<a>` tooltip labels.**
  The initial `inner_text` dump during the audit missed "Total credit
  limit" and "Available credit" even though a screenshot taken
  seconds later showed them clearly. Phase B scraper waits for a
  selector anchor before reading on `type == 'credit'` accounts.
- **Console paste is blocked on Chase's DevTools.** Workaround:
  `allow pasting` + Enter in the console once per session, then
  Ctrl+V works. Surfaced during Phase A; no impact on scraper code.
- **NFCU's regex helper needed structural changes for Chase.** The
  `.{0,50}?` flexible gap approach works on NFCU because NFCU's DOM
  doesn't interpose subtitle lines between label and value. Chase
  does (the "as of 12:00 AM ET on 04/17/2026" line), and every
  alternative in the value capture — plain number, case-insensitive
  flag, slash date — had some fragment in that subtitle to collide
  with. Line-boundary walking is the right shape for Chase; NFCU's
  helper stays unchanged.

## Verification

1. **Unit tests:** `pytest tests/test_chase_extractor.py -x
   --tb=short` — 19/19 pass.
2. **Full suite:** `pytest tests/ --tb=short` — 299/299 pass (280
   baseline + 19 new). Zero regressions.
3. **Config shape:** `accounts.yaml` entries for Chase now carry
   correct names, types, and full `loan_details` lists.
4. **Live Chase refresh:** deferred to the next normal refresh
   cycle. Logs should show `── Phase 3: Account Details (2
   accounts) ──` followed by per-field `✔` or `✗` lines. Remaining
   risk is the CC hydration wait; if labels still miss after 5s,
   tune the timeout or the anchor selectors.
5. **DB spot-check (post live refresh):**
   - `SELECT * FROM loan_details WHERE account_id LIKE 'chase_%'
     ORDER BY as_of DESC LIMIT 20;` — rows for `chase_REDACTED` and
     `chase_REDACTED` with today's `as_of`.
   - `SELECT * FROM apy_history WHERE account_id = 'chase_REDACTED';` —
     a row with `source='scrape'` (since 8973 returns an "Interest
     rate" of 0.01%).
   - No `apy` key in `loan_details` rows (`result_writer` strips it).
6. **ROADMAP:** flipped `[ ]` → `[v]` with verification date +
   prompt-file path.
