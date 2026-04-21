"""
scripts/dummy_data/generator.py — Rolling generative dummy data for dev/demo.

## Purpose

Produce a hand-auditable, deterministic fixture set that always ends at a
caller-specified `end_date` (default: yesterday).  Re-running the seeder any
day rolls the window forward automatically; no frozen JSON fixtures.

## Design principles

- **Hand-auditable**: every amount is a round dollar value drawn from a
  small set of tiers (e.g. groceries ∈ {50, 75, 100, 125, 150}).  Totals
  for any month, quarter or year can be computed by hand and cross-checked
  against the UI.
- **Deterministic**: the RNG is seeded from `int(end_date.strftime("%Y%m%d"))`
  so identical end-dates produce byte-identical datasets.
- **Closure property**: for every account, `end_balance ≡ start_balance +
  Σ signed_amount`.  Generated balance snapshots walk forward from the start
  balance by applying transactions in date order; no drift possible.
- **Paired transfers**: every cross-account movement emits BOTH legs with
  matching amounts and dates 0–2 days apart, so `reconcile_transfers()`
  reliably tags them and they drop out of income/spending reports.
- **Refund seeding**: ~3% of groceries / dining generate a paired refund
  2–4 days later on the same account.  This is a regression guard for the
  bug that made refunds silently subtract from spending totals.
- **Sign convention**: `signed_amount` is negative for debits, positive
  for credits; `direction` is 'Debit' or 'Credit' to match.  The
  invariant in `dal.transactions.upsert_transactions()` will raise if any
  row drifts.

## Entry points

The seeder calls these pure functions in order:

    generate_transactions(end_date, years, rng) -> list[dict]
    generate_balance_snapshots(end_date, txns) -> list[dict]
    generate_budgets(end_date, years) -> list[dict]
    generate_credit_scores(end_date, years, rng) -> list[dict]
    generate_vehicle_valuations(end_date, years) -> list[dict]
    generate_payroll_snapshots(end_date, months=36) -> list[dict]

Every function takes `end_date: date` and returns a list of dicts matching
the shape the seeder expects.

## Expected round-number totals per year (monthly × 12)

    Income:
      Alex biweekly paycheck $4000 × 26 = $104,000
      Jordan monthly freelance $3500 × 12 = $42,000
      Brighton HYSA interest $45 × 12 = $540
      TOTAL gross income:                 $146,540

    Fixed spending (excl. transfers / loan service / CC payments):
      Mortgage interest $1500 × 12 = $18,000   [Mortgages]
      Utilities $200 × 12 = $2,400             [Utilities]
      Internet $80 × 12 = $960                 [Telephone Services]
      Phone $85 × 12 = $1,020                  [Telephone Services]
      Insurance $600 × 2 = $1,200              [Insurance]
      Subscriptions $16+$11 × 12 = $324        [Dues and Subscriptions]
      Amazon Prime annual $140                 [Dues and Subscriptions]
      Planet Fitness $25 × 12 = $300           [Dues and Subscriptions]

    Variable spending (weekly × 52):
      Groceries avg $100 × 52 = $5,200         [Groceries]
      Dining avg $47.50 × 52 = $2,470          [Restaurants/Dining]
      Gas avg $45 × 52 = $2,340                [Auto]
      Shopping avg $62.50 × 52 = $3,250        [Shopping]

    Total non-transfer spending ≈ $37,500 / year.
    Net savings ≈ $109,000 / year.

These numbers are approximate because RNG choice distribution may not
land exactly on the midpoint, but tier midpoints match the comments above.
The golden seed test pins a specific end-date and asserts exact totals.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Iterable

from dal.investments_writes import (
    record_investment_holdings,
    record_portfolio_snapshots,
)


# ── Account set ──────────────────────────────────────────────────────────────
# Mirrors Institutions.json.  Duplicated here so the generator can be used
# without the JSON fixture. Account ids use semantic slugs (not last4-style
# digit suffixes) so the dummy fixtures can't be mistaken for the post-v31
# opaque id scheme used by real accounts in accounts.yaml.

ACCOUNTS: list[dict] = [
    {"institution_id": "summit", "account_id": "summit_chk",
     "name": "Summit Checking", "type": "checking", "last4": "4501",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 6500},
    {"institution_id": "summit", "account_id": "summit_sav",
     "name": "Summit Emergency Savings", "type": "savings", "last4": "7823",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 10000},
    {"institution_id": "summit", "account_id": "summit_cc",
     "name": "Summit Visa Platinum", "type": "credit_card", "last4": "3341",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 0},
    {"institution_id": "summit", "account_id": "summit_mtg",
     "name": "Summit Home Mortgage", "type": "loan", "last4": "9102",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": -230000},
    {"institution_id": "summit", "account_id": "summit_auto",
     "name": "Summit Auto Loan", "type": "loan", "last4": "6655",
     "owner_id": "quintin", "is_active": False, "closed_at": "2025-04-15",
     "starting_balance": 0},
    {"institution_id": "coastal", "account_id": "coastal_chk",
     "name": "Coastal Checking", "type": "checking", "last4": "2210",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 3000},
    {"institution_id": "coastal", "account_id": "coastal_cc",
     "name": "Coastal Cash Rewards", "type": "credit_card", "last4": "8847",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 0},
    # P13 investments rebuild — investment accounts.
    {"institution_id": "acorns_synthetic", "account_id": "acorns_synthetic",
     "name": "Acorns Synthetic", "type": "investment", "last4": "ACRN",
     "tax_status": "taxable",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 0},
    {"institution_id": "fidelity_synthetic", "account_id": "fidelity_brokerage",
     "name": "Fidelity Brokerage", "type": "investment", "last4": "FBRK",
     "tax_status": "taxable",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 0},
    {"institution_id": "tsp_synthetic", "account_id": "tsp_synthetic",
     "name": "TSP Uniformed Services", "type": "retirement", "last4": "TSPR",
     "tax_status": "mixed",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 0},
    {"institution_id": "brighton", "account_id": "brighton_sav",
     "name": "Brighton HYSA", "type": "savings", "last4": "3300",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 3500},
    {"institution_id": "payflex", "account_id": "payflex_bnpl",
     "name": "PayFlex BNPL", "type": "loan", "last4": "BNPL",
     "owner_id": "quintin", "is_active": False, "closed_at": "2025-04-30",
     "starting_balance": 0},
]

# Fast lookup helpers
_BY_ID = {a["account_id"]: a for a in ACCOUNTS}


def accounts() -> list[dict]:
    """Return a copy of the canonical account list."""
    return [dict(a) for a in ACCOUNTS]


# ── Tiers for variable spending ──────────────────────────────────────────────

GROCERY_TIERS = [50, 75, 100, 125, 150]
DINING_TIERS = [25, 40, 55, 70]
GAS_TIERS = [30, 40, 50, 60]
SHOPPING_TIERS = [25, 50, 75, 100]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mk_rng(end_date: date) -> random.Random:
    """Deterministic RNG from end-date."""
    return random.Random(int(end_date.strftime("%Y%m%d")))


def _daterange(start: date, end: date) -> Iterable[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _txn(
    account_id: str,
    posting_date: date,
    signed_amount: int,
    description: str,
    category: str,
    *,
    institution_txn_id: str | None = None,
) -> dict:
    """Build a transaction dict matching the seeder's upsert payload shape."""
    amount = abs(signed_amount)
    direction = "Credit" if signed_amount >= 0 else "Debit"
    inst_id = _BY_ID[account_id]["institution_id"]
    return {
        "account_id": account_id,
        "institution_id": inst_id,
        "posting_date": posting_date.isoformat(),
        "transaction_date": posting_date.isoformat(),
        "amount": float(amount),
        "signed_amount": float(signed_amount),
        "direction": direction,
        "description": description,
        "category": category,
        "status": "posted",
        "raw_description": description,
        "institution_txn_id": institution_txn_id,
    }


# ── Transaction generation ───────────────────────────────────────────────────


def generate_transactions(
    end_date: date,
    years: int = 3,
    rng: random.Random | None = None,
) -> list[dict]:
    """
    Build the full transaction history ending at ``end_date`` and extending
    back ``years`` years.  Returns a list of dicts in the shape that
    ``dal.transactions.upsert_transactions()`` expects.

    The generator is deterministic given ``end_date``: identical end-dates
    produce byte-identical outputs.

    Patterns included:
      - Biweekly Alex paycheck ($4000 net → summit_chk)
      - Monthly Jordan freelance paycheck ($3500 net → coastal_chk)
      - Monthly mortgage interest ($1500 summit_chk → Mortgages)
      - Monthly utilities / internet / phone / fitness
      - Monthly Netflix + Spotify on summit credit card
      - Annual Amazon Prime on summit credit card
      - Semi-annual auto insurance
      - Monthly HYSA interest credit
      - Monthly paired transfers: checking → savings, checking → Brighton HYSA
      - Monthly Acorns auto-invest ($350), ~10 roundups ($5-$12), $1 fee
      - Monthly paired credit-card payments (both legs emitted)
      - Weekly variable groceries / dining / gas / shopping
      - ~3% refund pairs on groceries to exercise the sign-handling path
    """
    if rng is None:
        rng = _mk_rng(end_date)

    start_date = end_date - timedelta(days=years * 365)
    txns: list[dict] = []

    # ── Biweekly Alex paycheck (anchored on Fridays) ─────────────────────────
    # Find the first Friday >= start_date
    d = start_date
    while d.weekday() != 4:
        d += timedelta(days=1)
    while d <= end_date:
        txns.append(_txn(
            "summit_chk", d, 4000,
            "ACME CORP PAYROLL", "Paychecks/Salary",
        ))
        d += timedelta(days=14)

    # ── Monthly Jordan freelance paycheck (1st of month) ─────────────────────
    for d in _month_firsts(start_date, end_date):
        txns.append(_txn(
            "coastal_chk", d, 3500,
            "JORDAN FREELANCE ACH", "Paychecks/Salary",
        ))

    # ── Monthly mortgage payment (5th of month) ──────────────────────────────
    # Emits BOTH legs: debit from checking (category 'Mortgages'), credit to
    # the loan account (category 'Loan Payments').  Both categories live in
    # EXCLUDED_FROM_SPEND so the payment never hits cash-flow spending totals.
    for d in _day_of_month(start_date, end_date, 5):
        txns.append(_txn(
            "summit_chk", d, -1500,
            "SUMMIT HOME MORTGAGE", "Mortgages",
        ))
        txns.append(_txn(
            "summit_mtg", d, 1500,
            "PAYMENT RECEIVED", "Loan Payments",
        ))

    # ── Monthly utilities (10th) ─────────────────────────────────────────────
    for d in _day_of_month(start_date, end_date, 10):
        txns.append(_txn(
            "summit_chk", d, -200,
            "DUKE ENERGY ONLINE", "Utilities",
        ))

    # ── Monthly internet (12th) ──────────────────────────────────────────────
    for d in _day_of_month(start_date, end_date, 12):
        txns.append(_txn(
            "summit_chk", d, -80,
            "SPECTRUM INTERNET", "Telephone Services",
        ))

    # ── Monthly phone bill on Jordan's checking (18th) ───────────────────────
    for d in _day_of_month(start_date, end_date, 18):
        txns.append(_txn(
            "coastal_chk", d, -85,
            "T-MOBILE AUTOPAY", "Telephone Services",
        ))

    # ── Semi-annual auto insurance (Jan 1 / Jul 1) ───────────────────────────
    d = date(start_date.year, 1, 1)
    if d < start_date:
        d = date(start_date.year, 7, 1)
    while d <= end_date:
        if d >= start_date:
            txns.append(_txn(
                "summit_chk", d, -600,
                "GEICO AUTO INSURANCE", "Insurance",
            ))
        # advance 6 months
        if d.month == 1:
            d = date(d.year, 7, 1)
        else:
            d = date(d.year + 1, 1, 1)

    # ── Subscriptions on Summit Visa (8th Netflix, 15th Spotify) ─────────────
    for d in _day_of_month(start_date, end_date, 8):
        txns.append(_txn(
            "summit_cc", d, -16,
            "NETFLIX.COM", "Dues and Subscriptions",
        ))
    for d in _day_of_month(start_date, end_date, 15):
        txns.append(_txn(
            "summit_cc", d, -11,
            "SPOTIFY PREMIUM", "Dues and Subscriptions",
        ))

    # ── Amazon Prime annual (February 9) ─────────────────────────────────────
    d = date(start_date.year, 2, 9)
    while d <= end_date:
        if d >= start_date:
            txns.append(_txn(
                "summit_cc", d, -140,
                "AMAZON PRIME RENEWAL", "Dues and Subscriptions",
            ))
        d = date(d.year + 1, 2, 9)

    # ── Planet Fitness (20th) on Jordan checking ─────────────────────────────
    for d in _day_of_month(start_date, end_date, 20):
        txns.append(_txn(
            "coastal_chk", d, -25,
            "PLANET FITNESS", "Dues and Subscriptions",
        ))

    # ── Monthly HYSA interest credit (last day of month) ─────────────────────
    for d in _last_of_month(start_date, end_date):
        txns.append(_txn(
            "brighton_sav", d, 45,
            "BRIGHTON HYSA INTEREST", "Interest",
        ))

    # ── Paired transfers (both legs) ─────────────────────────────────────────
    # Emergency savings
    for d in _day_of_month(start_date, end_date, 3):
        txns.append(_txn(
            "summit_chk", d, -800,
            "TRANSFER TO SUMMIT SAVINGS", "Transfers",
        ))
        txns.append(_txn(
            "summit_sav", d, 800,
            "TRANSFER FROM SUMMIT CHECKING", "Transfers",
        ))
    # Brighton HYSA from Summit
    for d in _day_of_month(start_date, end_date, 4):
        txns.append(_txn(
            "summit_chk", d, -500,
            "TRANSFER TO BRIGHTON HYSA", "Transfers",
        ))
        # Credit lands on Brighton one day later
        landing = d + timedelta(days=1)
        if landing <= end_date:
            txns.append(_txn(
                "brighton_sav", landing, 500,
                "TRANSFER FROM SUMMIT CHECKING", "Transfers",
            ))
    # Brighton HYSA from Coastal
    for d in _day_of_month(start_date, end_date, 4):
        txns.append(_txn(
            "coastal_chk", d, -250,
            "TRANSFER TO BRIGHTON HYSA", "Transfers",
        ))
        landing = d + timedelta(days=1)
        if landing <= end_date:
            txns.append(_txn(
                "brighton_sav", landing, 250,
                "TRANSFER FROM COASTAL CHECKING", "Transfers",
            ))
    # ── Acorns Synthetic: fixed bank-side debits (P13-T03) ─────────────────
    # Monthly fee ($1 on the 1st) — true expense, stays in spending metrics.
    # Recurring auto-invest ($350 on the 4th) — investment contribution.
    # Roundups use RNG so they're generated AFTER the CC backfill block
    # to avoid shifting the shared RNG state for other transactions.
    for d in _day_of_month(start_date, end_date, 1):
        txns.append(_txn(
            "summit_chk", d, -1,
            "ACORNS MONTHLY FEE", "Investment Fees",
        ))
    for d in _day_of_month(start_date, end_date, 4):
        txns.append(_txn(
            "summit_chk", d, -350,
            "ACORNS INVEST TRANSFER", "Investments",
        ))

    # ── Paired credit card payments — payoff prior cycle's actual charges ───
    # Defer actual emission until after all spending is generated; see
    # "CC payment back-fill" block at the bottom of this function.

    # ── Weekly variable spending (Saturday) ──────────────────────────────────
    d = start_date
    while d.weekday() != 5:  # Saturday
        d += timedelta(days=1)

    refund_pending: list[tuple[date, str, int]] = []  # (earliest, acct, amt)

    while d <= end_date:
        # Groceries on Summit Visa
        g = rng.choice(GROCERY_TIERS)
        txns.append(_txn(
            "summit_cc", d, -g,
            "KROGER SUPERMARKET", "Groceries",
        ))
        # 3% chance of refund
        if rng.random() < 0.03:
            refund_amt = min(g, 25)  # small partial refund
            refund_date = d + timedelta(days=rng.randint(2, 4))
            if refund_date <= end_date:
                refund_pending.append((refund_date, "summit_cc", refund_amt))

        # Dining alternating across both CC accounts
        dining_amt = rng.choice(DINING_TIERS)
        dining_acct = "summit_cc" if rng.random() < 0.6 else "coastal_cc"
        txns.append(_txn(
            dining_acct, d, -dining_amt,
            "LOCAL DINER", "Restaurants/Dining",
        ))

        # Gas on Summit Visa
        gas_amt = rng.choice(GAS_TIERS)
        txns.append(_txn(
            "summit_cc", d, -gas_amt,
            "SHELL GAS STATION", "Auto",
        ))

        # Shopping on Summit Visa
        shop_amt = rng.choice(SHOPPING_TIERS)
        txns.append(_txn(
            "summit_cc", d, -shop_amt,
            "TARGET STORE", "Shopping",
        ))

        d += timedelta(days=7)

    # Emit the refund credits
    for refund_date, acct, amt in refund_pending:
        txns.append(_txn(
            acct, refund_date, amt,
            "KROGER REFUND", "Groceries",
        ))

    # ── CC payment back-fill (25th of each month) ───────────────────────────
    # For each credit card, scan the txns generated so far and emit a payment
    # equal to the prior cycle's NET activity (charges − refunds).  Using the
    # signed net rather than raw charges keeps the CC balance at ≈ 0 each
    # cycle even when 3% grocery refunds land inside the window — a raw-
    # charges payment would leave a +refund credit balance and violate the
    # `balance <= 0 on liabilities` integrity invariant.
    #
    # Prior-cycle payment txns are NOT in the window (they land on the prior
    # 25th, which is strictly before `prior = d - 30 days`), so the only
    # positive signed_amounts we can see in-window are refunds.
    cc_payment_specs: list[tuple[str, str, str]] = [
        ("summit_cc", "summit_chk", "SUMMIT VISA PAYMENT"),
        ("coastal_cc", "coastal_chk", "COASTAL CC PAYMENT"),
    ]
    for d in _day_of_month(start_date, end_date, 25):
        prior = d - timedelta(days=30)
        for cc_acct, chk_acct, chk_desc in cc_payment_specs:
            cycle_net = sum(
                t["signed_amount"] for t in txns
                if t["account_id"] == cc_acct
                and prior < date.fromisoformat(t["posting_date"]) <= d
            )
            # cycle_net < 0 means net charges (payable).  cycle_net >= 0
            # means the cycle had a net credit — skip payment so we don't
            # push the card into a negative (debt) balance artificially.
            if cycle_net >= 0:
                continue
            amt = round(-cycle_net)
            txns.append(_txn(
                chk_acct, d, -amt,
                chk_desc, "Credit Card Payments",
            ))
            txns.append(_txn(
                cc_acct, d, amt,
                "PAYMENT THANK YOU", "Credit Card Payments",
            ))

    # ── Acorns roundups (RNG-consuming, placed after CC backfill) ──────────
    # ~10 per month, $5-$12 each, scattered across the month.
    ACORNS_ROUNDUP_TIERS = [5, 6, 7, 8, 9, 10, 11, 12]
    for d in _month_firsts(start_date, end_date):
        month_end = (date(d.year + (d.month // 12), (d.month % 12) + 1, 1)
                     - timedelta(days=1))
        if month_end > end_date:
            month_end = end_date
        num_roundups = rng.randint(8, 12)
        for _ in range(num_roundups):
            day_offset = rng.randint(1, (month_end - d).days or 1)
            ru_date = d + timedelta(days=day_offset)
            if ru_date > end_date:
                continue
            ru_amt = rng.choice(ACORNS_ROUNDUP_TIERS)
            txns.append(_txn(
                "summit_chk", ru_date, -ru_amt,
                "ACORNS INVEST ROUNDUP", "Investments",
            ))

    # Sort by posting_date so balance walker can apply in order
    txns.sort(key=lambda t: (t["posting_date"], t["account_id"]))
    return txns


# ── Date iterators ───────────────────────────────────────────────────────────


def _month_firsts(start: date, end: date) -> Iterable[date]:
    """Yield first-of-month dates in [start, end]."""
    y, m = start.year, start.month
    if start.day > 1:
        # Advance to next month
        m += 1
        if m > 12:
            m = 1
            y += 1
    d = date(y, m, 1)
    while d <= end:
        yield d
        m += 1
        if m > 12:
            m = 1
            y += 1
        d = date(y, m, 1)


def _day_of_month(start: date, end: date, day: int) -> Iterable[date]:
    """Yield every date in [start, end] whose day-of-month equals ``day``."""
    y, m = start.year, start.month
    while True:
        try:
            d = date(y, m, day)
        except ValueError:  # e.g. Feb 30
            pass
        else:
            if start <= d <= end:
                yield d
            elif d > end:
                return
        m += 1
        if m > 12:
            m = 1
            y += 1


def _last_of_month(start: date, end: date) -> Iterable[date]:
    """Yield last-day-of-month dates in [start, end]."""
    import calendar as _cal
    y, m = start.year, start.month
    while True:
        last = _cal.monthrange(y, m)[1]
        d = date(y, m, last)
        if d >= start and d <= end:
            yield d
        elif d > end:
            return
        m += 1
        if m > 12:
            m = 1
            y += 1


# ── Balance snapshots ────────────────────────────────────────────────────────


def generate_balance_snapshots(
    end_date: date,
    txns: list[dict],
) -> list[dict]:
    """
    Walk every account day-by-day, apply transactions in chronological
    order, and emit a monthly balance snapshot on the first day of each
    month plus one final snapshot on ``end_date``.

    Closure property: for every cash/credit/loan account, the final
    snapshot equals ``starting_balance + Σ signed_amount`` over the full
    period.

    NOTE (P13 investments rebuild): the investment/retirement branch
    that bypassed the closure walk via `portfolio_by_acct` was removed
    when investment seeding was stripped.  Investment accounts will
    return in a future P13 task.
    """
    # Group txns by account
    by_acct: dict[str, list[dict]] = {}
    for t in txns:
        by_acct.setdefault(t["account_id"], []).append(t)

    snapshots: list[dict] = []
    for acct in ACCOUNTS:
        acct_id = acct["account_id"]
        bal = float(acct["starting_balance"])
        acct_txns = sorted(by_acct.get(acct_id, []),
                           key=lambda t: t["posting_date"])

        # Build a map: date → running balance after applying all txns on that day
        txn_idx = 0
        # Emit a snapshot on the first day of each month within the window
        # plus one snapshot on end_date.
        if not acct_txns:
            # No activity — just emit a single snapshot at end_date
            snapshots.append({
                "account_id": acct_id,
                "date": end_date.isoformat(),
                "balance_amount": round(bal, 2),
            })
            continue

        first_txn_date = date.fromisoformat(acct_txns[0]["posting_date"])
        # Emit starting snapshot at first-of-month of first_txn_date
        snap_date = date(first_txn_date.year, first_txn_date.month, 1)
        snapshots.append({
            "account_id": acct_id,
            "date": snap_date.isoformat(),
            "balance_amount": round(bal, 2),
        })

        # Walk forward one month at a time
        cursor_y, cursor_m = snap_date.year, snap_date.month
        while True:
            # Next month anchor
            cursor_m += 1
            if cursor_m > 12:
                cursor_m = 1
                cursor_y += 1
            next_anchor = date(cursor_y, cursor_m, 1)

            if next_anchor > end_date:
                break

            # Apply all txns strictly before next_anchor
            while (txn_idx < len(acct_txns)
                   and date.fromisoformat(acct_txns[txn_idx]["posting_date"]) < next_anchor):
                bal += float(acct_txns[txn_idx]["signed_amount"])
                txn_idx += 1

            snapshots.append({
                "account_id": acct_id,
                "date": next_anchor.isoformat(),
                "balance_amount": round(bal, 2),
            })

        # Apply any remaining txns up to end_date inclusive
        while (txn_idx < len(acct_txns)
               and date.fromisoformat(acct_txns[txn_idx]["posting_date"]) <= end_date):
            bal += float(acct_txns[txn_idx]["signed_amount"])
            txn_idx += 1

        # Final snapshot on end_date (only if not already emitted for that day)
        if not snapshots or snapshots[-1]["date"] != end_date.isoformat() \
                or snapshots[-1]["account_id"] != acct_id:
            snapshots.append({
                "account_id": acct_id,
                "date": end_date.isoformat(),
                "balance_amount": round(bal, 2),
            })

    return snapshots


# ── Budgets ──────────────────────────────────────────────────────────────────


# Base monthly targets — hand-auditable round dollars.
BUDGET_BASE: dict[str, int] = {
    "Groceries": 600,
    "Restaurants/Dining": 300,
    "Utilities": 250,
    "Telephone Services": 200,
    "Dues and Subscriptions": 60,
    "Auto": 250,
    "Shopping": 300,
    "Insurance": 150,
    "Mortgages": 1600,
}


def generate_budgets(end_date: date, years: int = 3) -> list[dict]:
    """
    Emit monthly budget rows for every category in ``BUDGET_BASE`` across
    the ``years``-year window ending at ``end_date``.  Targets drift up
    2% per year to exercise lifestyle-creep detection.
    """
    start_date = end_date - timedelta(days=years * 365)
    rows: list[dict] = []
    for d in _month_firsts(start_date, end_date):
        month = d.strftime("%Y-%m")
        year_offset = d.year - start_date.year
        for cat, base in BUDGET_BASE.items():
            # 2% growth per year, rounded to nearest $5
            target = base * (1.02 ** year_offset)
            target = round(target / 5) * 5
            rows.append({
                "category": cat,
                "month": month,
                "target_amount": float(target),
                # Budgets are household-only (V23) — no owner attribution.
                "owner_id": None,
            })
    return rows


# ── Credit scores ────────────────────────────────────────────────────────────


def generate_credit_scores(
    end_date: date,
    years: int = 3,
    rng: random.Random | None = None,
) -> list[dict]:
    """
    Monthly FICO scores for Quintin at both bureaus, with a gentle upward
    drift. Two parallel series — one pulled from the Summit relationship,
    one from the Coastal relationship — both attributed to quintin since
    quintin owns both. Each month adds rng.choice([-5, 0, 0, 0, 5]) and
    scores are rounded to the nearest 5.

    Amy is intentionally absent: she is a structural placeholder for the
    multi-user UI surfaces (no synthetic data attached). The dashboard
    credit-score card renders her slot as an empty state in the
    household view.
    """
    if rng is None:
        rng = _mk_rng(end_date)

    start_date = end_date - timedelta(days=years * 365)
    rows: list[dict] = []
    summit_score = 740
    coastal_score = 705

    for d in _month_firsts(start_date, end_date):
        score_date = d + timedelta(days=14)  # mid-month
        if score_date > end_date:
            continue
        summit_score = max(650, min(820, summit_score + rng.choice([-5, 0, 0, 0, 5])))
        coastal_score = max(650, min(820, coastal_score + rng.choice([-5, 0, 0, 0, 5])))
        rows.append({
            "owner_id": "quintin",
            "institution_id": "summit",
            "score": summit_score,
            "score_type": "FICO",
            "source": "TransUnion",
            "score_date": score_date.isoformat(),
        })
        rows.append({
            "owner_id": "quintin",
            "institution_id": "coastal",
            "score": coastal_score,
            "score_type": "FICO",
            "source": "TransUnion",
            "score_date": score_date.isoformat(),
        })
    return rows


# ── APY history (P15-T04 Phase B) ───────────────────────────────────────────
#
# Rolling monthly APY rows for the three deposit accounts whose rates the
# connectors scrape today. Linear values with ±2bps drift so charts in T06
# have a non-flat line to render. Deterministic via the shared RNG — same
# end_date produces identical output.
#
# Why this shape: the app stores APY as percent (4.00 = 4%), not fraction,
# and that's what the DAL invariant guard expects.

_APY_SEED_ACCOUNTS: list[dict] = [
    # Seeder fixtures use proxy institutions (summit, coastal) — real
    # Affirm / NFCU IDs aren't populated in Institutions.json. Summit
    # savings is the NFCU-savings analogue, Summit checking the NFCU-
    # checking analogue. If a high-yield proxy is added later, append
    # it here; the DAL invariant guard will still enforce [0, 100].
    {"account_id": "summit_sav", "base_pct": 0.25, "drift_bps": 2},
    {"account_id": "summit_chk", "base_pct": 0.05, "drift_bps": 1},
]


def generate_apy_history(
    end_date: date,
    years: int = 3,
    rng: random.Random | None = None,
) -> list[dict]:
    """One APY row per (account × month) over a rolling window.

    Rates drift ±(drift_bps / 100)% per month but never leave the
    plausible band for the account (e.g. Affirm stays > 3%, NFCU
    checking stays near zero). ``source='scrape'`` so the rows look
    like they came off a real connector run.
    """
    if rng is None:
        rng = _mk_rng(end_date)

    start_date = end_date - timedelta(days=years * 365)
    rows: list[dict] = []

    for acct in _APY_SEED_ACCOUNTS:
        current = acct["base_pct"]
        drift_pct = acct["drift_bps"] / 100.0  # bps → pct
        for d in _month_firsts(start_date, end_date):
            as_of = d + timedelta(days=14)  # mid-month snapshot
            if as_of > end_date:
                continue
            # Tight random walk around the base; clamp to non-negative.
            step = rng.choice([-drift_pct, 0.0, 0.0, drift_pct])
            current = max(0.0, round(current + step, 4))
            rows.append({
                "account_id": acct["account_id"],
                "apy_rate": current,
                "as_of": as_of.isoformat(),
                "source": "scrape",
            })
    return rows


# ── Investment history (P13-T03) ─────────────────────────────────────────────
#
# Rebuild of investment seeding for the Acorns Synthetic account.  Uses real
# yFinance historical prices (cached in benchmark_prices) so the synthetic
# portfolio tracks realistic market performance.

# Acorns default allocation (approximate)
_ACORNS_ALLOC = {"VOO": 0.55, "IJH": 0.15, "IJR": 0.15, "IXUS": 0.15}
_ACORNS_TICKERS = list(_ACORNS_ALLOC.keys())
_ACORNS_ACCT = "acorns_synthetic"


def _fetch_and_cache_prices(
    conn, tickers: list[str], start: date, end: date
) -> dict[str, dict[str, float]]:
    """Fetch daily closing prices from yFinance, caching in benchmark_prices.

    Returns {ticker: {date_str: close_price}}.  On subsequent runs, reads
    from cache and only fetches missing date ranges from yFinance.
    """
    import logging
    log = logging.getLogger("sentry.seeder.prices")

    result: dict[str, dict[str, float]] = {t: {} for t in tickers}

    # 1. Load cached prices
    rows = conn.execute(
        """SELECT ticker, price_date, close_price FROM benchmark_prices
           WHERE ticker IN ({}) AND price_date BETWEEN ? AND ?
           ORDER BY ticker, price_date""".format(
            ",".join("?" for _ in tickers)
        ),
        [*tickers, start.isoformat(), end.isoformat()],
    ).fetchall()

    for r in rows:
        result[r[0]][r[1]] = r[2]

    # 2. Check if we need fresh data — find tickers with < 50% coverage
    trading_days_approx = ((end - start).days * 5) // 7
    tickers_to_fetch = [
        t for t in tickers
        if len(result[t]) < trading_days_approx * 0.5
    ]

    if not tickers_to_fetch:
        log.info("  All %d tickers fully cached in benchmark_prices", len(tickers))
        return result

    # 3. Fetch from yFinance
    try:
        import yfinance as yf
    except ImportError:
        log.warning("  yfinance not installed — using fallback linear prices")
        return _fallback_linear_prices(tickers, start, end)

    log.info(
        "  Fetching %d tickers from yFinance (%s to %s)...",
        len(tickers_to_fetch), start, end,
    )
    try:
        # Fetch all tickers at once for efficiency
        df = yf.download(
            tickers_to_fetch,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            log.warning("  yFinance returned empty data — using fallback")
            return _fallback_linear_prices(tickers, start, end)

        # Handle single-ticker vs multi-ticker DataFrame shape
        if len(tickers_to_fetch) == 1:
            close_df = df[["Close"]].rename(columns={"Close": tickers_to_fetch[0]})
        else:
            close_df = df["Close"]

        # 4. Cache and collect
        inserts = []
        for ticker in tickers_to_fetch:
            if ticker not in close_df.columns:
                continue
            series = close_df[ticker].dropna()
            for ts, price in series.items():
                d_str = ts.strftime("%Y-%m-%d")
                result[ticker][d_str] = float(price)
                inserts.append((ticker, d_str, float(price)))

        if inserts:
            conn.executemany(
                """INSERT OR IGNORE INTO benchmark_prices
                   (ticker, price_date, close_price) VALUES (?, ?, ?)""",
                inserts,
            )
            conn.commit()
            log.info("  Cached %d price rows in benchmark_prices", len(inserts))

    except Exception as e:
        log.warning("  yFinance fetch failed: %s — using fallback", e)
        return _fallback_linear_prices(tickers, start, end)

    return result


def _fallback_linear_prices(
    tickers: list[str], start: date, end: date
) -> dict[str, dict[str, float]]:
    """Deterministic linear price drift when yFinance is unavailable."""
    # Base prices (approximate Jan 2023 values)
    bases = {
        "VOO": 380.0, "IJH": 250.0, "IJR": 98.0, "IXUS": 60.0,
        # Fidelity tickers
        "AAPL": 130.0, "MSFT": 240.0, "AMZN": 85.0, "GOOG": 90.0,
        "SPG": 115.0, "QQQM": 130.0, "TGT": 155.0, "SBUX": 100.0,
        # TSP funds
        "TSP_C": 55.0, "TSP_S": 55.0, "TSP_L2065": 10.0,
    }
    # Monthly drift
    drifts = {
        "VOO": 1.5, "IJH": 0.8, "IJR": 0.4, "IXUS": 0.3,
        # Fidelity tickers
        "AAPL": 2.0, "MSFT": 2.5, "AMZN": 1.8, "GOOG": 1.5,
        "SPG": 0.8, "QQQM": 1.8, "TGT": 0.5, "SBUX": 0.3,
        # TSP funds
        "TSP_C": 1.4, "TSP_S": 1.2, "TSP_L2065": 0.3,
    }

    result: dict[str, dict[str, float]] = {}
    ref = date(2023, 1, 1)
    d = start
    while d <= end:
        if d.weekday() < 5:  # trading days only
            months_from_ref = (d.year - ref.year) * 12 + (d.month - ref.month)
            d_str = d.isoformat()
            for t in tickers:
                if t not in result:
                    result[t] = {}
                result[t][d_str] = bases.get(t, 100.0) + drifts.get(t, 0.5) * months_from_ref
        d += timedelta(days=1)
    return result


def _closest_price(
    prices: dict[str, float], target_date: date, max_lookback: int = 5
) -> float | None:
    """Find the closest available price on or before target_date."""
    for offset in range(max_lookback + 1):
        d_str = (target_date - timedelta(days=offset)).isoformat()
        if d_str in prices:
            return prices[d_str]
    return None


def generate_acorns_investment_history(
    conn,
    txns: list[dict],
    end_date: date,
    years: int = 3,
) -> dict:
    """Generate positions_ledger and portfolio_snapshots for Acorns Synthetic.

    Reads the bank-side Acorns transactions from ``txns`` (already generated
    by generate_transactions), fetches real yFinance prices (or fallback),
    and produces per-transaction positions_ledger entries + weekly
    portfolio_snapshots.

    Args:
        conn: SQLite connection (for benchmark_prices cache + writes).
        txns: The full transaction list from generate_transactions().
        end_date: Seed window end date.
        years: Seed window length.

    Returns:
        dict with counts: {ledger_rows, snapshot_rows, prices_cached}.
    """
    from decimal import Decimal
    import logging
    log = logging.getLogger("sentry.seeder.acorns")

    start_date = end_date - timedelta(days=years * 365)

    # 1. Extract bank-side Acorns debits (transfers + roundups, NOT fees)
    acorns_debits = [
        t for t in txns
        if t["account_id"] == "summit_chk"
        and "ACORNS INVEST" in t["description"]
        and "FEE" not in t["description"]
        and t["signed_amount"] < 0
    ]
    acorns_debits.sort(key=lambda t: t["posting_date"])
    log.info("  %d Acorns bank debits found (transfers + roundups)", len(acorns_debits))

    # 2. Fetch/cache yFinance prices for the full window
    prices = _fetch_and_cache_prices(conn, _ACORNS_TICKERS, start_date, end_date)

    # 3. Build positions_ledger entries
    running_shares: dict[str, Decimal] = {t: Decimal("0") for t in _ACORNS_TICKERS}
    ledger_rows = []
    ledger_id = 0

    for txn in acorns_debits:
        txn_date = date.fromisoformat(txn["posting_date"])
        contribution = abs(txn["signed_amount"])  # dollars invested

        # Allocate across ETFs
        for ticker, alloc_pct in _ACORNS_ALLOC.items():
            alloc_dollars = contribution * alloc_pct
            price = _closest_price(prices.get(ticker, {}), txn_date)
            if price is None or price <= 0:
                continue

            shares_bought = Decimal(str(alloc_dollars)) / Decimal(str(price))
            shares_bought = shares_bought.quantize(Decimal("0.00001"))
            running_shares[ticker] += shares_bought

            ledger_id += 1
            is_first = running_shares[ticker] == shares_bought
            ledger_rows.append({
                "id": ledger_id,
                "account_id": _ACORNS_ACCT,
                "timestamp": f"{txn_date.isoformat()}T12:00:00",
                "ticker": ticker,
                "transaction_type": "INITIAL_BASELINE" if is_first else "IMPLIED_BUY",
                "share_delta": float(shares_bought),
                "new_total_shares": float(running_shares[ticker]),
                "yfinance_closing_price": price,
                "estimated_transaction_value": float(alloc_dollars),
                "share_delta_dec": str(shares_bought),
                "new_total_shares_dec": str(running_shares[ticker]),
                "source": "seeder",
                "bank_txn_id": None,  # linked after insertion
            })

    # 4. Write positions_ledger
    conn.executemany(
        """INSERT INTO positions_ledger
           (account_id, timestamp, ticker, transaction_type,
            share_delta, new_total_shares,
            yfinance_closing_price, estimated_transaction_value,
            share_delta_dec, new_total_shares_dec, source, bank_txn_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (r["account_id"], r["timestamp"], r["ticker"],
             r["transaction_type"], r["share_delta"], r["new_total_shares"],
             r["yfinance_closing_price"], r["estimated_transaction_value"],
             r["share_delta_dec"], r["new_total_shares_dec"],
             r["source"], r["bank_txn_id"])
            for r in ledger_rows
        ],
    )
    log.info("  %d positions_ledger rows inserted", len(ledger_rows))

    # 5. Generate weekly portfolio_snapshots (every Friday)
    snapshot_rows = []
    d = start_date
    # Advance to first Friday
    while d.weekday() != 4:
        d += timedelta(days=1)

    while d <= end_date:
        # Find the latest ledger state on or before this Friday
        total_value = 0.0
        for ticker in _ACORNS_TICKERS:
            # Current shares as of this date
            shares = Decimal("0")
            for lr in ledger_rows:
                if lr["ticker"] == ticker and lr["timestamp"][:10] <= d.isoformat():
                    shares = Decimal(lr["new_total_shares_dec"])
            price = _closest_price(prices.get(ticker, {}), d)
            if price and shares > 0:
                total_value += float(shares) * price

        if total_value > 0:
            snapshot_rows.append({
                "account_id": _ACORNS_ACCT,
                "timestamp": f"{d.isoformat()}T16:00:00",
                "total_account_value": round(total_value, 2),
                "cash_balance": 0.0,
            })

        d += timedelta(days=7)

    record_portfolio_snapshots(conn, snapshot_rows)
    log.info("  %d portfolio_snapshots rows inserted", len(snapshot_rows))

    # 6. Generate investment_holdings snapshots (every 2 days recent, weekly old)
    holding_rows = []
    d = start_date
    while d <= end_date:
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        months_ago = (end_date.year - d.year) * 12 + (end_date.month - d.month)
        step = 7 if months_ago > 6 else 2

        for ticker in _ACORNS_TICKERS:
            shares = Decimal("0")
            for lr in ledger_rows:
                if lr["ticker"] == ticker and lr["timestamp"][:10] <= d.isoformat():
                    shares = Decimal(lr["new_total_shares_dec"])
            if shares <= 0:
                continue
            price = _closest_price(prices.get(ticker, {}), d)
            if price is None:
                continue
            market_value = float(shares) * price
            # Acorns cost basis: sum of all transaction values up to this date
            cost = sum(
                lr["estimated_transaction_value"]
                for lr in ledger_rows
                if lr["ticker"] == ticker and lr["timestamp"][:10] <= d.isoformat()
            )
            holding_rows.append({
                "account_id": _ACORNS_ACCT,
                "date": d.isoformat(),
                "ticker": ticker,
                "shares": float(shares),
                "close_price": price,
                "market_value": round(market_value, 2),
                "cost_basis": round(cost, 2),
            })
        d += timedelta(days=step)

    record_investment_holdings(conn, holding_rows)
    log.info("  %d investment_holdings rows inserted", len(holding_rows))

    conn.commit()

    return {
        "ledger_rows": len(ledger_rows),
        "holding_rows": len(holding_rows),
        "snapshot_rows": len(snapshot_rows),
        "prices_cached": sum(len(v) for v in prices.values()),
    }


# ── Fidelity synthetic investment history (P13-T06) ──────────────────────────
#
# Individual equities, manual buys/sells, dividends, SPAXX cash position,
# and FIFO lot tracking.

_FIDELITY_TICKERS = {
    "AAPL": {"sector": "Technology",            "cap": "Large Cap"},
    "MSFT": {"sector": "Technology",            "cap": "Large Cap"},
    "AMZN": {"sector": "Consumer Discretionary","cap": "Large Cap"},
    "GOOG": {"sector": "Communication Services","cap": "Large Cap"},
    "SPG":  {"sector": "Real Estate",           "cap": "Large Cap"},
    "QQQM": {"sector": "Technology",            "cap": "Large Cap", "type": "ETF"},
    "TGT":  {"sector": "Consumer Staples",      "cap": "Mid Cap"},
    "SBUX": {"sector": "Consumer Discretionary", "cap": "Large Cap"},
}
_FIDELITY_TICKER_LIST = list(_FIDELITY_TICKERS.keys())
_FIDELITY_ACCT = "fidelity_brokerage"

# Approximate quarterly dividend schedule (months that pay)
_DIVIDEND_TICKERS = {
    "AAPL": [2, 5, 8, 11],   # Feb, May, Aug, Nov
    "MSFT": [3, 6, 9, 12],   # Mar, Jun, Sep, Dec
    "SPG":  [1, 4, 7, 10],   # Jan, Apr, Jul, Oct
    "TGT":  [3, 6, 9, 12],   # Mar, Jun, Sep, Dec
    "SBUX": [2, 5, 8, 11],   # Feb, May, Aug, Nov
}
# Approximate annual yield (used to compute quarterly dividend amount)
_DIVIDEND_YIELDS = {
    "AAPL": 0.005, "MSFT": 0.008, "SPG": 0.045, "TGT": 0.030, "SBUX": 0.025,
}


def _next_business_day(d: date) -> date:
    """Return d+1, skipping weekends."""
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def generate_fidelity_investment_history(
    conn,
    end_date: date,
    years: int = 3,
) -> dict:
    """Generate positions_ledger, investment_holdings, and portfolio_snapshots
    for the Fidelity Brokerage synthetic account.

    Produces:
      - Monthly $500 EFT deposits
      - 2-3 stock buys per month, rotating through 8 tickers
      - Quarterly dividends for 5 dividend-paying tickers
      - 2-3 sells per year (position trimming)
      - SPAXX cash balance tracking
      - Daily investment_holdings snapshots (every 2 days, weekly for old data)
      - Daily portfolio_snapshots

    Returns dict with counts: {ledger_rows, holding_rows, snapshot_rows, prices_cached}.
    """
    from decimal import Decimal, ROUND_HALF_UP
    import logging
    log = logging.getLogger("sentry.seeder.fidelity")

    start_date = end_date - timedelta(days=years * 365)
    rng = random.Random(420827)  # deterministic

    # 1. Fetch/cache yFinance prices for all Fidelity tickers
    prices = _fetch_and_cache_prices(conn, _FIDELITY_TICKER_LIST, start_date, end_date)
    prices_cached = sum(len(v) for v in prices.values())

    # 2. Build transaction timeline
    #    Running state per ticker: list of lots (for FIFO), total shares
    lots: dict[str, list[dict]] = {t: [] for t in _FIDELITY_TICKER_LIST}
    running_shares: dict[str, Decimal] = {t: Decimal("0") for t in _FIDELITY_TICKER_LIST}
    cash_balance = Decimal("0")  # SPAXX

    ledger_rows = []
    ledger_id_counter = 0

    def _add_ledger(ts, ticker, txn_type, share_delta, price_val,
                    cost_basis=None, realized_gain=None,
                    settlement=None, commission="0.00", fees="0.00"):
        nonlocal ledger_id_counter
        ledger_id_counter += 1
        row = {
            "account_id": _FIDELITY_ACCT,
            "timestamp": ts,
            "ticker": ticker,
            "transaction_type": txn_type,
            "share_delta": float(share_delta),
            "new_total_shares": float(running_shares[ticker]) if ticker in running_shares else 0.0,
            "yfinance_closing_price": float(price_val) if price_val else None,
            "estimated_transaction_value": abs(float(share_delta * Decimal(str(price_val)))) if price_val else 0.0,
            "share_delta_dec": str(share_delta),
            "new_total_shares_dec": str(running_shares[ticker]) if ticker in running_shares else "0",
            "source": "seeder",
            "bank_txn_id": None,
            "cost_basis_dec": str(cost_basis) if cost_basis is not None else None,
            "realized_gain_dec": str(realized_gain) if realized_gain is not None else None,
            "settlement_date": settlement,
            "commission_dec": commission,
            "fees_dec": fees,
        }
        ledger_rows.append(row)

    # Walk month by month
    current = date(start_date.year, start_date.month, 1)
    sell_count_this_year = 0
    current_year = current.year
    buy_ticker_idx = 0  # rotating index for buy selection

    while current <= end_date:
        if current.year != current_year:
            sell_count_this_year = 0
            current_year = current.year

        # ── Monthly deposit ($500 EFT on ~1st business day) ─────────
        deposit_day = current.replace(day=1)
        while deposit_day.weekday() >= 5:
            deposit_day += timedelta(days=1)
        if deposit_day <= end_date:
            cash_balance += Decimal("500")
            _add_ledger(
                f"{deposit_day.isoformat()}T09:00:00",
                "SPAXX", "DEPOSIT",
                Decimal("0"), None,
            )

        # ── Monthly buys (2-3 stocks) ─────────────────────────────
        num_buys = rng.choice([2, 2, 3])
        buy_day = current.replace(day=min(rng.randint(3, 8), 28))
        while buy_day.weekday() >= 5:
            buy_day += timedelta(days=1)

        if buy_day <= end_date:
            for _ in range(num_buys):
                ticker = _FIDELITY_TICKER_LIST[buy_ticker_idx % len(_FIDELITY_TICKER_LIST)]
                buy_ticker_idx += 1

                price = _closest_price(prices.get(ticker, {}), buy_day)
                if price is None or price <= 0:
                    continue

                buy_amount = Decimal(str(rng.randint(150, 400)))
                price_dec = Decimal(str(price))

                # Whole shares preferred, fractional for QQQM
                if ticker == "QQQM":
                    shares = (buy_amount / price_dec).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                else:
                    shares = Decimal(int(buy_amount / price_dec))
                    if shares < 1:
                        shares = Decimal("1")

                actual_cost = (shares * price_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if actual_cost > cash_balance:
                    continue  # not enough cash

                cash_balance -= actual_cost
                running_shares[ticker] += shares
                lots[ticker].append({
                    "date": buy_day.isoformat(),
                    "shares": shares,
                    "price": price_dec,
                    "cost": actual_cost,
                })

                is_first = running_shares[ticker] == shares
                _add_ledger(
                    f"{buy_day.isoformat()}T10:{rng.randint(0,59):02d}:00",
                    ticker,
                    "INITIAL_BASELINE" if is_first else "BUY",
                    shares, price,
                    cost_basis=actual_cost,
                    settlement=_next_business_day(buy_day).isoformat(),
                )

        # ── Quarterly dividends ──────────────────────────────────
        month_num = current.month
        for div_ticker, div_months in _DIVIDEND_TICKERS.items():
            if month_num not in div_months:
                continue
            if running_shares[div_ticker] <= 0:
                continue

            div_day = current.replace(day=min(rng.randint(15, 25), 28))
            while div_day.weekday() >= 5:
                div_day += timedelta(days=1)
            if div_day > end_date:
                continue

            price = _closest_price(prices.get(div_ticker, {}), div_day)
            if price is None:
                continue

            # quarterly dividend = shares × price × annual_yield / 4
            annual_yield = _DIVIDEND_YIELDS.get(div_ticker, 0.01)
            div_amount = (
                running_shares[div_ticker]
                * Decimal(str(price))
                * Decimal(str(annual_yield))
                / Decimal("4")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Record dividend as cash
            cash_balance += div_amount
            _add_ledger(
                f"{div_day.isoformat()}T08:00:00",
                div_ticker, "DIVIDEND",
                Decimal("0"), price,
                cost_basis=None,
            )

            # 40% chance of dividend reinvestment
            if rng.random() < 0.4 and div_amount > 5:
                reinvest_shares = (div_amount / Decimal(str(price))).quantize(
                    Decimal("0.001"), rounding=ROUND_HALF_UP
                )
                if reinvest_shares > 0:
                    cash_balance -= div_amount
                    running_shares[div_ticker] += reinvest_shares
                    lots[div_ticker].append({
                        "date": div_day.isoformat(),
                        "shares": reinvest_shares,
                        "price": Decimal(str(price)),
                        "cost": div_amount,
                    })
                    _add_ledger(
                        f"{div_day.isoformat()}T08:05:00",
                        div_ticker, "REINVESTMENT",
                        reinvest_shares, price,
                        cost_basis=div_amount,
                        settlement=_next_business_day(div_day).isoformat(),
                    )

        # ── Occasional sells (2-3 per year, in Q2/Q4) ───────────
        if month_num in (5, 6, 10, 11) and sell_count_this_year < 3:
            # Pick a ticker we own enough shares of
            sellable = [
                t for t in _FIDELITY_TICKER_LIST
                if running_shares[t] > 0 and len(lots[t]) > 0 and t != "QQQM"
            ]
            if sellable and rng.random() < 0.5:
                sell_ticker = rng.choice(sellable)
                sell_day = current.replace(day=min(rng.randint(10, 20), 28))
                while sell_day.weekday() >= 5:
                    sell_day += timedelta(days=1)
                if sell_day <= end_date:
                    price = _closest_price(prices.get(sell_ticker, {}), sell_day)
                    if price:
                        price_dec = Decimal(str(price))
                        # Sell 20-50% of position
                        sell_pct = Decimal(str(rng.randint(20, 50))) / Decimal("100")
                        sell_shares = (running_shares[sell_ticker] * sell_pct).quantize(
                            Decimal("1"), rounding=ROUND_HALF_UP
                        )
                        if sell_shares > 0 and sell_shares <= running_shares[sell_ticker]:
                            # FIFO lot matching
                            proceeds = (sell_shares * price_dec).quantize(Decimal("0.01"))
                            cost_basis_total = Decimal("0")
                            remaining_to_sell = sell_shares

                            new_lots = []
                            for lot in lots[sell_ticker]:
                                if remaining_to_sell <= 0:
                                    new_lots.append(lot)
                                    continue
                                if lot["shares"] <= remaining_to_sell:
                                    # consume entire lot
                                    cost_basis_total += lot["cost"]
                                    remaining_to_sell -= lot["shares"]
                                else:
                                    # partial lot consumption
                                    fraction = remaining_to_sell / lot["shares"]
                                    cost_basis_total += (lot["cost"] * fraction).quantize(Decimal("0.01"))
                                    lot["shares"] -= remaining_to_sell
                                    lot["cost"] = (lot["cost"] * (Decimal("1") - fraction)).quantize(Decimal("0.01"))
                                    remaining_to_sell = Decimal("0")
                                    new_lots.append(lot)

                            lots[sell_ticker] = new_lots
                            realized = proceeds - cost_basis_total

                            running_shares[sell_ticker] -= sell_shares
                            cash_balance += proceeds

                            _add_ledger(
                                f"{sell_day.isoformat()}T11:{rng.randint(0,59):02d}:00",
                                sell_ticker, "SELL",
                                -sell_shares, price,
                                cost_basis=cost_basis_total,
                                realized_gain=realized,
                                settlement=_next_business_day(sell_day).isoformat(),
                            )
                            sell_count_this_year += 1

        # Advance to next month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    # 3. Write positions_ledger
    if ledger_rows:
        conn.executemany(
            """INSERT INTO positions_ledger
               (account_id, timestamp, ticker, transaction_type,
                share_delta, new_total_shares,
                yfinance_closing_price, estimated_transaction_value,
                share_delta_dec, new_total_shares_dec, source, bank_txn_id,
                cost_basis_dec, realized_gain_dec, settlement_date,
                commission_dec, fees_dec)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (r["account_id"], r["timestamp"], r["ticker"],
                 r["transaction_type"], r["share_delta"], r["new_total_shares"],
                 r["yfinance_closing_price"], r["estimated_transaction_value"],
                 r["share_delta_dec"], r["new_total_shares_dec"],
                 r["source"], r["bank_txn_id"],
                 r["cost_basis_dec"], r["realized_gain_dec"],
                 r["settlement_date"], r["commission_dec"], r["fees_dec"])
                for r in ledger_rows
            ],
        )
    log.info("  %d positions_ledger rows inserted", len(ledger_rows))

    # 4. Generate investment_holdings snapshots
    #    Every 2 days for recent data (< 6 months), weekly for older
    holding_rows = []
    d = start_date
    while d <= end_date:
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue

        # Determine snapshot frequency
        months_ago = (end_date.year - d.year) * 12 + (end_date.month - d.month)
        if months_ago > 6:
            step = 7  # weekly
        else:
            step = 2  # every 2 days

        for ticker in _FIDELITY_TICKER_LIST:
            # Find shares as of this date
            shares = Decimal("0")
            for lr in ledger_rows:
                if lr["ticker"] == ticker and lr["timestamp"][:10] <= d.isoformat():
                    shares = Decimal(lr["new_total_shares_dec"])
            if shares <= 0:
                continue

            # Compute cost basis from ledger: sum of BUY cost_basis minus
            # cost consumed by SELLs, all up to this date.
            buy_cost = Decimal("0")
            sell_cost = Decimal("0")
            for lr in ledger_rows:
                if lr["ticker"] != ticker or lr["timestamp"][:10] > d.isoformat():
                    continue
                if lr["transaction_type"] in ("BUY", "REINVESTMENT", "INITIAL_BASELINE") and lr["cost_basis_dec"]:
                    buy_cost += Decimal(lr["cost_basis_dec"])
                elif lr["transaction_type"] == "SELL" and lr["cost_basis_dec"]:
                    sell_cost += Decimal(lr["cost_basis_dec"])
            total_cost = buy_cost - sell_cost

            price = _closest_price(prices.get(ticker, {}), d)
            if price is None:
                continue

            market_value = float(shares) * price
            holding_rows.append({
                "account_id": _FIDELITY_ACCT,
                "date": d.isoformat(),
                "ticker": ticker,
                "shares": float(shares),
                "close_price": price,
                "market_value": round(market_value, 2),
                "cost_basis": round(float(total_cost), 2),
            })

        d += timedelta(days=step)

    record_investment_holdings(conn, holding_rows)
    log.info("  %d investment_holdings rows inserted", len(holding_rows))

    # 5. Generate portfolio_snapshots (every Friday)
    snapshot_rows = []
    d = start_date
    while d.weekday() != 4:
        d += timedelta(days=1)

    while d <= end_date:
        total_value = 0.0
        for ticker in _FIDELITY_TICKER_LIST:
            shares = Decimal("0")
            for lr in ledger_rows:
                if lr["ticker"] == ticker and lr["timestamp"][:10] <= d.isoformat():
                    shares = Decimal(lr["new_total_shares_dec"])
            price = _closest_price(prices.get(ticker, {}), d)
            if price and shares > 0:
                total_value += float(shares) * price

        # Compute approximate cash balance as of this date
        approx_cash = Decimal("0")
        for lr in ledger_rows:
            if lr["timestamp"][:10] > d.isoformat():
                continue
            if lr["transaction_type"] == "DEPOSIT":
                approx_cash += Decimal("500")
            elif lr["transaction_type"] in ("BUY", "REINVESTMENT"):
                cb = Decimal(lr["cost_basis_dec"]) if lr["cost_basis_dec"] else Decimal("0")
                approx_cash -= cb
            elif lr["transaction_type"] == "SELL":
                approx_cash += Decimal(str(lr["estimated_transaction_value"]))
            elif lr["transaction_type"] == "DIVIDEND":
                # dividend cash = shares × price × yield / 4 (approximate)
                ticker = lr["ticker"]
                yd = _DIVIDEND_YIELDS.get(ticker, 0.01)
                p = lr["yfinance_closing_price"] or 0
                sd = Decimal(lr["new_total_shares_dec"]) if lr["new_total_shares_dec"] != "0" else Decimal("0")
                div_approx = (sd * Decimal(str(p)) * Decimal(str(yd)) / Decimal("4")).quantize(Decimal("0.01"))
                approx_cash += div_approx

        total_with_cash = total_value + max(float(approx_cash), 0)
        if total_with_cash > 0:
            snapshot_rows.append({
                "account_id": _FIDELITY_ACCT,
                "timestamp": f"{d.isoformat()}T16:00:00",
                "total_account_value": round(total_with_cash, 2),
                "cash_balance": round(max(float(approx_cash), 0), 2),
            })

        d += timedelta(days=7)

    record_portfolio_snapshots(conn, snapshot_rows)
    log.info("  %d portfolio_snapshots rows inserted", len(snapshot_rows))

    conn.commit()

    return {
        "ledger_rows": len(ledger_rows),
        "holding_rows": len(holding_rows),
        "snapshot_rows": len(snapshot_rows),
        "prices_cached": prices_cached,
    }


# ── TSP synthetic investment history ──────────────────────────────────────────
#
# Mirrors real TSP data shape: fixed unit counts per fund, daily price drift,
# no BUY/SELL events.  The real TSP connector produces the same pattern —
# units are constant, only prices move.

_TSP_FUNDS = {
    "TSP_C":     {"shares": 800.0,  "desc": "C Fund (S&P 500 match)"},
    "TSP_S":     {"shares": 600.0,  "desc": "S Fund (small/mid cap)"},
    "TSP_L2065": {"shares": 1800.0, "desc": "Lifecycle 2065"},
}
_TSP_TICKERS = list(_TSP_FUNDS.keys())
_TSP_ACCT = "tsp_synthetic"


def generate_tsp_investment_history(
    conn,
    end_date: date,
    years: int = 3,
) -> dict:
    """Generate investment_holdings and portfolio_snapshots for synthetic TSP.

    Models the real TSP data shape: fixed unit counts with daily price
    changes.  No positions_ledger entries (matches real TSP connector
    behavior where units don't change, only NAV prices move).

    Returns dict with counts: {holding_rows, snapshot_rows, prices_cached}.
    """
    import logging
    log = logging.getLogger("sentry.seeder.tsp")

    start_date = end_date - timedelta(days=years * 365)

    # 1. Fetch/cache prices (will use fallback linear drift for TSP_* tickers)
    prices = _fetch_and_cache_prices(conn, _TSP_TICKERS, start_date, end_date)

    # 2. Generate investment_holdings snapshots
    #    Every 2 days for recent data (< 6 months), weekly for older data
    holding_rows = []
    d = start_date
    while d <= end_date:
        if d.weekday() >= 5:  # skip weekends
            d += timedelta(days=1)
            continue

        months_ago = (end_date.year - d.year) * 12 + (end_date.month - d.month)
        step = 7 if months_ago > 6 else 2

        for ticker, info in _TSP_FUNDS.items():
            price = _closest_price(prices.get(ticker, {}), d)
            if price is None:
                continue
            shares = info["shares"]
            market_value = shares * price
            holding_rows.append({
                "account_id": _TSP_ACCT,
                "date": d.isoformat(),
                "ticker": ticker,
                "shares": shares,
                "close_price": price,
                "market_value": round(market_value, 2),
                "cost_basis": None,
            })

        d += timedelta(days=step)

    record_investment_holdings(conn, holding_rows)
    log.info("  %d investment_holdings rows inserted", len(holding_rows))

    # 3. Generate weekly portfolio_snapshots (every Friday)
    snapshot_rows = []
    d = start_date
    while d.weekday() != 4:  # advance to first Friday
        d += timedelta(days=1)

    while d <= end_date:
        total_value = 0.0
        for ticker, info in _TSP_FUNDS.items():
            price = _closest_price(prices.get(ticker, {}), d)
            if price:
                total_value += info["shares"] * price

        if total_value > 0:
            snapshot_rows.append({
                "account_id": _TSP_ACCT,
                "timestamp": f"{d.isoformat()}T16:00:00",
                "total_account_value": round(total_value, 2),
                "cash_balance": 0.0,  # TSP has no cash position
            })
        d += timedelta(days=7)

    record_portfolio_snapshots(conn, snapshot_rows)
    log.info("  %d portfolio_snapshots rows inserted", len(snapshot_rows))

    # 4. Generate tax_buckets (Traditional ~33%, Roth+Tax-exempt ~67%)
    #    Roth share drifts upward over the 3-year window (from ~62% to ~67%)
    #    since Roth was the more recent contribution source.
    bucket_rows = []
    d = start_date
    while d.weekday() != 4:  # advance to first Friday (same cadence as snapshots)
        d += timedelta(days=1)

    total_months = years * 12
    while d <= end_date:
        # Compute total account value at this date
        total_val = 0.0
        for ticker, info in _TSP_FUNDS.items():
            price = _closest_price(prices.get(ticker, {}), d)
            if price:
                total_val += info["shares"] * price

        if total_val > 0:
            # Roth share drifts from 62% to 67% over the window
            months_elapsed = (d.year - start_date.year) * 12 + (d.month - start_date.month)
            roth_pct = 0.62 + 0.05 * min(months_elapsed / total_months, 1.0)
            trad_pct = 1.0 - roth_pct

            trad_cents = round(total_val * trad_pct * 100)
            roth_cents = round(total_val * roth_pct * 100)

            as_of = d.isoformat()
            bucket_rows.append((_TSP_ACCT, "traditional", trad_cents, 1.0, as_of))
            bucket_rows.append((_TSP_ACCT, "roth",        roth_cents, 1.0, as_of))

        d += timedelta(days=7)

    conn.executemany(
        """INSERT OR REPLACE INTO tax_buckets
           (account_id, bucket_type, balance, vested_pct, as_of)
           VALUES (?, ?, ?, ?, ?)""",
        bucket_rows,
    )
    log.info("  %d tax_buckets rows inserted", len(bucket_rows))

    conn.commit()

    return {
        "holding_rows": len(holding_rows),
        "snapshot_rows": len(snapshot_rows),
        "bucket_rows": len(bucket_rows),
        "prices_cached": sum(len(v) for v in prices.values()),
    }


# ── Ticker metadata enrichment ─────────────────────────────────────────────

# All tickers across all investment accounts
_ALL_INVESTMENT_TICKERS = _ACORNS_TICKERS + _FIDELITY_TICKER_LIST + _TSP_TICKERS

_TICKER_METADATA_FALLBACK = {
    "VOO":  {"sector": "Blend",        "industry": "S&P 500 Index",           "asset_class": "ETF"},
    "IJH":  {"sector": "Blend",        "industry": "S&P MidCap 400 Index",    "asset_class": "ETF"},
    "IJR":  {"sector": "Blend",        "industry": "S&P SmallCap 600 Index",  "asset_class": "ETF"},
    "IXUS": {"sector": "Blend",        "industry": "International Developed", "asset_class": "ETF"},
    "AAPL": {"sector": "Technology",           "industry": "Consumer Electronics",     "asset_class": "Equity"},
    "MSFT": {"sector": "Technology",           "industry": "Software—Infrastructure",  "asset_class": "Equity"},
    "AMZN": {"sector": "Consumer Discretionary","industry": "Internet Retail",          "asset_class": "Equity"},
    "GOOG": {"sector": "Communication Services","industry": "Internet Content",         "asset_class": "Equity"},
    "SPG":  {"sector": "Real Estate",          "industry": "REIT—Retail",              "asset_class": "Equity"},
    "QQQM": {"sector": "Technology",           "industry": "Nasdaq-100 Index",         "asset_class": "ETF"},
    "TGT":  {"sector": "Consumer Staples",     "industry": "Discount Stores",          "asset_class": "Equity"},
    "SBUX": {"sector": "Consumer Discretionary","industry": "Restaurants",              "asset_class": "Equity"},
    # TSP funds
    "TSP_C":     {"sector": "Blend", "industry": "S&P 500 Match",      "asset_class": "TSP Fund"},
    "TSP_S":     {"sector": "Blend", "industry": "Small/Mid Cap Match", "asset_class": "TSP Fund"},
    "TSP_L2065": {"sector": "Blend", "industry": "Lifecycle 2065",     "asset_class": "TSP Fund"},
}


def enrich_ticker_metadata(conn, tickers: list[str] | None = None) -> int:
    """Fetch sector/industry/asset_class from yfinance, cache in ticker_metadata.

    Falls back to hardcoded metadata if yfinance is unavailable or fails.
    Skips tickers already updated in the last 30 days.

    Returns number of tickers enriched.
    """
    import logging
    log = logging.getLogger("sentry.seeder.metadata")

    if tickers is None:
        tickers = _ALL_INVESTMENT_TICKERS

    # Check which tickers need updating
    to_update = []
    for ticker in tickers:
        row = conn.execute(
            "SELECT last_updated FROM ticker_metadata WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        if row:
            last = row[0]
            if last and (date.today() - date.fromisoformat(last)).days < 30:
                continue
        to_update.append(ticker)

    if not to_update:
        log.info("  All %d tickers already up to date in ticker_metadata", len(tickers))
        return 0

    # Try yfinance first
    enriched = 0
    try:
        import yfinance as yf
        for ticker in to_update:
            try:
                info = yf.Ticker(ticker).info
                sector = info.get("sector", "")
                industry = info.get("industry", "")
                quote_type = info.get("quoteType", "")
                asset_class = "ETF" if quote_type == "ETF" else "Equity"
                if not sector:
                    # yfinance returned empty — use fallback
                    fb = _TICKER_METADATA_FALLBACK.get(ticker, {})
                    sector = fb.get("sector", "Unknown")
                    industry = fb.get("industry", "Unknown")
                    asset_class = fb.get("asset_class", asset_class)
                conn.execute(
                    """INSERT OR REPLACE INTO ticker_metadata
                       (ticker, sector, industry, asset_class, last_updated)
                       VALUES (?, ?, ?, ?, date('now'))""",
                    (ticker, sector, industry, asset_class),
                )
                enriched += 1
            except Exception as e:
                log.warning("  yfinance lookup failed for %s: %s — using fallback", ticker, e)
                fb = _TICKER_METADATA_FALLBACK.get(ticker, {})
                conn.execute(
                    """INSERT OR REPLACE INTO ticker_metadata
                       (ticker, sector, industry, asset_class, last_updated)
                       VALUES (?, ?, ?, ?, date('now'))""",
                    (ticker, fb.get("sector", "Unknown"),
                     fb.get("industry", "Unknown"),
                     fb.get("asset_class", "Equity")),
                )
                enriched += 1
    except ImportError:
        log.warning("  yfinance not installed — using fallback metadata")
        for ticker in to_update:
            fb = _TICKER_METADATA_FALLBACK.get(ticker, {})
            conn.execute(
                """INSERT OR REPLACE INTO ticker_metadata
                   (ticker, sector, industry, asset_class, last_updated)
                   VALUES (?, ?, ?, ?, date('now'))""",
                (ticker, fb.get("sector", "Unknown"),
                 fb.get("industry", "Unknown"),
                 fb.get("asset_class", "Equity")),
            )
            enriched += 1

    conn.commit()
    log.info("  %d tickers enriched in ticker_metadata", enriched)
    return enriched


# ── Vehicle valuations ───────────────────────────────────────────────────────


def generate_vehicle_valuations(
    end_date: date,
    years: int = 3,
) -> list[dict]:
    """
    Quarterly KBB valuations for the single demo vehicle (2021 RAV4).
    Straight-line depreciation from $26,500 to ~$20,000 over the window.
    """
    start_date = end_date - timedelta(days=years * 365)
    rows: list[dict] = []
    # Walk first-of-quarter dates
    y, q = start_date.year, (start_date.month - 1) // 3 + 1
    q_count = 0
    # Count quarters in window
    probe_y, probe_q = y, q
    while True:
        m = (probe_q - 1) * 3 + 1
        d = date(probe_y, m, 1)
        if d > end_date:
            break
        if d >= start_date:
            q_count += 1
        probe_q += 1
        if probe_q > 4:
            probe_q = 1
            probe_y += 1

    if q_count == 0:
        return rows

    start_value = 26500
    end_value = 20000
    step = (start_value - end_value) / max(q_count - 1, 1)

    idx = 0
    while True:
        m = (q - 1) * 3 + 1
        d = date(y, m, 1)
        if d > end_date:
            break
        if d >= start_date:
            val = round(start_value - step * idx, -2)  # round to nearest $100
            rows.append({
                "vehicle_id": "rav4_2021",
                "valuation_date": d.isoformat(),
                "estimated_value": float(val),
                "source": "KBB",
            })
            idx += 1
        q += 1
        if q > 4:
            q = 1
            y += 1
    return rows


# ── Payroll snapshots (myPay RAS substitute) ─────────────────────────────────


def generate_payroll_snapshots(
    end_date: date,
    months: int = 36,
) -> list[dict]:
    """
    Synthetic monthly myPay-style RAS rows ending at ``end_date``.
    Round values so pre-tax / effective-tax UI has deterministic inputs.
    """
    rows: list[dict] = []
    y, m = end_date.year, end_date.month
    for _ in range(months):
        pay_period = f"{y:04d}-{m:02d}"
        gross = 5200
        federal = 520
        state = 130
        sbp = 270
        dental = 45
        net = gross - federal - state - sbp - dental
        rows.append({
            "pay_period": pay_period,
            "source": "dummy_seeder",
            "gross_pay": float(gross),
            "federal_tax": float(federal),
            "state_tax": float(state),
            "sbp_premium": float(sbp),
            "health_insurance": 0.0,
            "dental_vision": float(dental),
            "other_deductions": 0.0,
            "net_pay": float(net),
        })
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    rows.reverse()
    return rows


def generate_amy_payroll_snapshots(
    end_date: date,
    months: int = 36,
) -> list[dict]:
    """
    Phase 14 Phase B — synthetic Amy W-2 payroll rows.

    Abstract labels only (no real employer name); values are deterministic
    round numbers so the effective-tax-rate UI has stable inputs. Amy's
    snapshots live alongside Quintin's in ``payroll_snapshots``, scoped by
    ``owner_id='amy'``.
    """
    rows: list[dict] = []
    y, m = end_date.year, end_date.month
    for _ in range(months):
        pay_period = f"{y:04d}-{m:02d}"
        gross = 4200
        federal = 336          # ~8%
        state = 84             # ~2%
        health = 120           # medical pre-tax
        dental = 22
        other = 0
        net = gross - federal - state - health - dental - other
        rows.append({
            "pay_period": pay_period,
            "source": "Primary W-2 source",
            "gross_pay": float(gross),
            "federal_tax": float(federal),
            "state_tax": float(state),
            "sbp_premium": 0.0,
            "health_insurance": float(health),
            "dental_vision": float(dental),
            "other_deductions": float(other),
            "net_pay": float(net),
        })
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    rows.reverse()
    return rows


def generate_income_source_registry() -> list[dict]:
    """
    Phase 14 Phase B — income_sources registry seed rows.

    Three entries exercise the classifier:

    1. Quintin — employer retirement match. bypass_cash_routing=1 draws a
       pseudo-edge straight to STORED_ILLIQUID. ``monthly_amount_cents``
       in match_rule_json drives the Sankey flow amount.
    2. Quintin — officiating (contractor-style, no withholding).
       ``estimated_tax_reserve_pct=0`` reflects Phase B's posture of not
       computing a reserve; the field is reserved for a future projection.
    3. Amy — W-2 withheld source. Matches the seeded Amy payroll rows by
       counterparty substring.
    """
    return [
        {
            "id": "seed_quintin_employer_match",
            "display_label": "Employer retirement match",
            "owner_id": "quintin",
            "tax_treatment": "employer_match_bypass",
            "default_category": "Retirement Income",
            "match_rule_json": {
                "counterparty_substring": "employer match",
                "owner_id": "quintin",
                "monthly_amount_cents": 26000,
            },
            "estimated_tax_reserve_pct": 0.0,
            "bypass_cash_routing": 1,
            "active": 1,
        },
        {
            "id": "seed_quintin_officiating",
            "display_label": "Officiating income",
            "owner_id": "quintin",
            "tax_treatment": "contractor_no_withholding",
            "default_category": "Officiating Income",
            "match_rule_json": {
                "category": "Officiating Income",
                "owner_id": "quintin",
            },
            "estimated_tax_reserve_pct": 0.0,
            "bypass_cash_routing": 0,
            "active": 1,
        },
        {
            "id": "seed_amy_w2",
            "display_label": "Amy W-2",
            "owner_id": "amy",
            "tax_treatment": "w2_withheld",
            "default_category": "Paychecks/Salary",
            "match_rule_json": {
                "counterparty_substring": "primary w-2 source",
                "owner_id": "amy",
            },
            "estimated_tax_reserve_pct": 0.0,
            "bypass_cash_routing": 0,
            "active": 1,
        },
    ]


# ── Institution metadata (replaces Institutions.json loading) ────────────────


def institution_rows() -> list[dict]:
    """
    Emit rows in the shape Institutions.json used to provide, so the seeder
    can insert institution + account records without a JSON fixture.
    """
    out = []
    for a in ACCOUNTS:
        out.append({
            "institution_id": a["institution_id"],
            "account_id": a["account_id"],
            "name": a["name"],
            "type": a["type"],
            "last4": a.get("last4"),
            "owner_id": a.get("owner_id"),
            "is_active": a.get("is_active", True),
            "closed_at": a.get("closed_at"),
            "tax_status": a.get("tax_status"),
        })
    return out


# ── Self-check entry point ───────────────────────────────────────────────────


def _summarize(end_date: date, years: int = 3) -> dict:
    """Return a small report of the generated dataset for sanity checks."""
    rng = _mk_rng(end_date)
    txns = generate_transactions(end_date, years, rng)
    return {
        "end_date": end_date.isoformat(),
        "years": years,
        "transaction_count": len(txns),
        "first_date": txns[0]["posting_date"] if txns else None,
        "last_date": txns[-1]["posting_date"] if txns else None,
    }


if __name__ == "__main__":
    import json as _json
    ed = date.today() - timedelta(days=1)
    print(_json.dumps(_summarize(ed), indent=2))
