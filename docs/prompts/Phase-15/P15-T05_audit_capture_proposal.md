# P15-T05 Phase A — Chase Per-Account Data Capture Proposal

> **Status:** Phase A complete (2026-04-19). Chase walked live via shared
> Chrome session (user drove navigation; Claude captured DOM dumps +
> observed screenshots). Two accounts reviewed: XXXX Premier Plus
> Checking and XXXX Slate Edge credit card. User wrap: agreed scope +
> drops. Ready for Phase B.

## Session Summary

The plan framed Chase as "CC XXXX / Checking XXXX" — both were wrong.
Account XXXX is actually **Premier Plus Checking** (URL `/DDA/CHK`,
header "PREMIER PLUS CKG"). Account XXXX is **Slate Edge credit card**
(URL `/accountDetails/details/creditCard`, header "Slate Edge"). The
"Sapphire" label in `accounts.yaml` is a holdover from an earlier
synthetic-data iteration and was never real. Phase B must rewrite both
entries, not just add `loan_details` lists to them.

Chase surfaces a meaningful amount of per-account metadata once you
know where to look — the default "account tile click" lands on the
**transaction activity view**, which carries balance + transfers but
almost no metadata. The richer view lives one click deeper via the
**More → Account details** dropdown in the left rail (checking) or the
equivalent on the CC. This matters: the Phase B scraper must navigate
to the details sub-URL, not settle on the activity page.

Compared to the NFCU detail pages (which expose APR, VIN, collateral,
dividends YTD, 14-day payoff, etc. all on one dense screen), Chase's
details view is noticeably thinner. A few fields the plan wanted —
`14_day_payoff`, `ytd_interest`, `date_opened` — simply aren't
surfaced on this view. User accepted the drop rather than chase them
across other screens; interest-charge data is derivable from
transactions already, and Slate Edge's $0 balance makes payoff math
trivial anyway.

## Legend

- **Now** — scope into Phase B.
- **Drop** — agreed out of scope (not surfaced on Chase, or user
  decision).
- **Already captured** — redundant with Phase 1 balance scrape.

---

## XXXX — Premier Plus Checking (WALKED LIVE)

Navigation: dashboard → click account tile → **More** dropdown →
**Account details**. Lands on
`secure.chase.com/web/auth/dashboard#/dashboard/summary/details/<id>/DDA/CHK`.

DOM is mostly label-then-value on consecutive lines, with one
interposing timestamp line for "Available balance":

```
Available balance
as of 12:00 AM ET on 04/17/2026
$4,172.97
Present balance
$4,172.97
Interest rate
0.01%
Interest in 2026
$0.03
Last statement date
Mar 18, 2026
```

Field catalogue:

| Scraped key           | On-page label       | Regex candidate                               | Decision | Notes |
| --------------------- | ------------------- | --------------------------------------------- | -------- | ----- |
| `available_balance`   | Available balance   | `Available\s+balance`                         | **Now**  | 50-char gap tolerant — interposing "as of ..." timestamp |
| `present_balance`     | Present balance     | `Present\s+balance`                           | **Now**  | equals `available_balance` on this account; kept as first-class field so CC shape (current vs. available distinct) stays consistent |
| `apy`                 | Interest rate       | `Interest\s+rate` (Chase) \| `APY` (generic)  | **Now**  | Chase calls it "Interest rate" not "APY". Routes to `apy_history` via result_writer unchanged |
| `ytd_interest`        | Interest in {{year}}| `Interest\s+in\s+\d{4}`                       | **Now**  | year is dynamic in the label — regex must not pin it |
| `last_statement_date` | Last statement date | `Last\s+statement\s+date`                     | **Now**  | ISO-date normalization handled downstream (as today) |
| `date_opened`         | —                   | —                                             | Drop     | Not surfaced on Chase details view; user decision |
| `direct_deposit_enrolled` | —               | —                                             | Drop     | Not surfaced; user confirmed static = yes, not worth scraping |
| `overdraft_protection`| Overdraft protection| —                                             | Drop     | Per T05 plan decision #7 |
| `current_balance`     | —                   | —                                             | Already captured | Phase 1 balance scrape writes `balance_snapshots` |

---

## XXXX — Slate Edge credit card (WALKED LIVE)

Navigation: dashboard → click account tile → Account Details tab/link.
Lands on
`secure.chase.com/web/auth/dashboard#/dashboard/accountDetails/details/creditCard;params=CARD,BAC,<id>,CARD-BAC-001`.

Layout is a two-column right-aligned label / left-aligned value grid.
Several labels are rendered as underlined `<a>` tooltip links
("Available credit", "Total credit limit", "Cash advance limit",
"Remaining statement balance"). Observed quirk: the initial
`inner_text` dump dropped those `<a>`-wrapped labels — likely a
render-timing issue, since screenshots taken after the page settled
showed them clearly. **Phase B scraper must wait for
DOM-content-loaded before reading body text**, and if the issue
recurs, fall back to a `page.wait_for_selector` on one of the `<a>`
labels before dumping `inner_text`.

```
Account Information
Current balance                    $0.00
Pending charges                    Not available
Available credit                   $6,800.00
Total credit limit                 $6,800.00
Next closing date                  Apr 20, 2026
Balance on last statement          $0.00 on Aug 20, 2025
Remaining statement balance        $0.00
Payments are due on the 17th of every month.
Recent Payment Activity
Last payment                       $465.95 was paid on Sep 17, 2025
Minimum payment                    $0.00 is due on Apr 17, 2026
Automatic Payments                 On
Cash Advance
Cash advance balance               $0.00
Available for cash advance         $1,360.00
Cash advance limit                 $1,360.00
APR as of Apr 19, 2026
Purchase APR                       0.00%
Cash advance APR                   28.49%
```

Field catalogue:

| Scraped key                   | On-page label                | Regex candidate                                   | Decision | Notes |
| ----------------------------- | ---------------------------- | ------------------------------------------------- | -------- | ----- |
| `purchase_apr`                | Purchase APR                 | `Purchase\s+APR` \| `Interest\s+Rate`             | **Now**  | Canonical key across institutions per T05 plan decision #6 |
| `cash_advance_apr`            | Cash advance APR             | `Cash\s+advance\s+APR`                            | **Now**  | 28.49% on Slate Edge vs. 0.00% purchase — highlights rate-shop value |
| `credit_limit`                | Total credit limit           | `Total\s+credit\s+limit` \| `Credit\s+Limit`      | **Now**  | — |
| `available_credit`            | Available credit             | `\bAvailable\s+credit\b`                          | **Now**  | word-boundary to avoid matching "Available for cash advance" |
| `cash_advance_limit`          | Cash advance limit           | `Cash\s+advance\s+limit`                          | **Now**  | — |
| `cash_advance_available`      | Available for cash advance   | `Available\s+for\s+cash\s+advance`                | **Now**  | — |
| `cash_advance_balance`        | Cash advance balance         | `Cash\s+advance\s+balance`                        | **Now**  | — |
| `minimum_payment`             | Minimum payment              | `Minimum\s+payment`                               | **Now**  | value line: "$0.00 is due on Apr 17, 2026" — regex captures the dollar amount with trailing-text tolerance |
| `payment_due_date`            | Minimum payment              | `\$[\d,]+\.\d{2}\s+is\s+due\s+on\s+([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})` | **Now** | value-first capture from the same "Minimum payment" line |
| `statement_balance`           | Balance on last statement    | `Balance\s+on\s+last\s+statement`                 | **Now**  | value shape "$X.XX on <date>"; Phase B stores the full string, downstream parses |
| `remaining_statement_balance` | Remaining statement balance  | `Remaining\s+statement\s+balance`                 | **Now**  | bonus find; useful for paydown-suggestion logic in T06 |
| `next_closing_date`           | Next closing date            | `Next\s+closing\s+date`                           | **Now**  | bonus find; lets alerts fire pre-statement |
| `last_payment`                | Last payment                 | `Last\s+payment`                                  | **Now**  | value: "$465.95 was paid on Sep 17, 2025" — captured as full string, parsing deferred to T06 UI |
| `automatic_payments`          | Automatic Payments           | `Automatic\s+Payments`                            | **Now**  | value: "On" / "Off" |
| `14_day_payoff`               | —                            | —                                                 | Drop     | Not surfaced anywhere on Chase CC; drop per user decision |
| `ytd_interest`                | —                            | —                                                 | Drop     | Not surfaced; derivable from `INTEREST CHARGED` transaction rows. User decision |
| `date_opened`                 | —                            | —                                                 | Drop     | Not surfaced; consistent with XXXX drop |
| `current_balance`             | Current balance              | —                                                 | Already captured | Phase 1 balance scrape |
| `rewards_points`              | —                            | —                                                 | N/A      | Per roadmap: Slate Edge is not a rewards card |

---

## Cross-cutting findings for Phase B

1. **`accounts.yaml` rewrite, not append.** XXXX → `type: checking`,
   `name: "Premier Plus Checking"`. XXXX → `type: credit`,
   `name: "Slate Edge"`. Current names ("Sapphire", "Checking") are
   both wrong.

2. **Two different navigation paths.** Checking uses the left-rail
   **More → Account details** dropdown. The CC Account Details view
   is reached via a different tab/link from the CC main view. The
   `_scrape_account_details` method needs per-account-type navigation
   logic (or a retry: try both, pick whichever surfaces labels).

3. **Render-timing race on the CC details view.** Some labels are
   `<a>` tooltip links that may not be in `inner_text` immediately.
   Wait strategy: `page.wait_for_selector("a:has-text('Total credit
   limit')", timeout=5000)` before reading body text on CC pages. On
   checking, no race observed — the NFCU-style wait is sufficient.

4. **No NFCU-style DOM split-rendering on Chase.** Dollar amounts
   render as single text nodes. No `$\n1,292\n.\n36` normalizer
   needed.

5. **APY routing is free.** `result_writer.py` already splits `apy`
   out of `loan_details` into `apy_history`. Chase's scraped
   `{"apy": "0.01%"}` dict emission inherits this without connector
   changes.

6. **`payment_due_date` is a value-first capture.** The "Minimum
   payment" line carries both amount and due date:
   `"$0.00 is due on Apr 17, 2026"`. Use the T03b value-first
   convention (regex with its own capture group) to extract the date
   without a second label.

7. **Console paste is blocked by Chase.** DevTools workaround:
   `allow pasting` + Enter once per session. Logged for future
   manual audits; no impact on Phase B (the scraper doesn't use the
   console).

## Raw artifacts

Stored under `raw_exports/chase/` (gitignored):

- `audit_XXXX_activity.txt` — transaction-activity view (confirms
  XXXX identity via URL; not the Phase B target page)
- `audit_XXXX_details.txt` — Account Details view (Phase B target)
- `audit_XXXX_details_findings.md` — per-field notes
- `audit_XXXX_details.txt` — CC Account Details view
- `audit_XXXX_findings.md` — per-field notes
