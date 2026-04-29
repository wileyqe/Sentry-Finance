"""
scripts/dummy_data/generator.py — Trusted synthetic data generator.

## Purpose

Produce a hand-auditable, deterministic fixture set for the canonical trusted
seed. The public seeder pins `end_date` and `reference_date`; test harnesses
may pass alternate dates, but normal product/dev workflows should treat the
canonical seed as the single synthetic truth.

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
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": -22000},
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
      - Monthly investment transfers: Acorns $500, Fidelity $1000, TSP $1500
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
    # Flat $95/mo approximates 4.25% APY on the $32K trailing balance
    # (average across the 3-year window lands slightly lower, but the
    # flat value keeps txn values deterministic and matches the APY
    # story surfaced in the Account Details panel).
    for d in _last_of_month(start_date, end_date):
        txns.append(_txn(
            "brighton_sav", d, 95,
            "BRIGHTON HYSA INTEREST", "Interest",
        ))

    # ── Summit dividend credits (last day of month) ──────────────────────────
    # Low-yield credit-union dividends — kept nominal so the Details
    # panel's YTD numbers reflect the APY story (0.29% on summit_sav
    # ≈ $7/mo on a $29K avg balance; 0.05% on summit_chk ≈ $5/mo on a
    # $120K avg balance). Category is "Interest" so it rolls into the
    # same Sankey income bucket as HYSA interest.
    for d in _last_of_month(start_date, end_date):
        txns.append(_txn(
            "summit_sav", d, 7,
            "SUMMIT SHARE DIVIDEND", "Interest",
        ))
        txns.append(_txn(
            "summit_chk", d, 5,
            "SUMMIT CHECKING DIVIDEND", "Interest",
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
    # Canonical Shape-B investment transfers. The investment seeder links
    # each bank-side debit to one positions_ledger row and stamps
    # transfer_tag so cash-flow paths exclude them from spending.
    for spec in TRUSTED_INVESTMENT_ACCOUNT_SPECS.values():
        amount_dollars = spec["monthly_cents"] // 100
        for d in trusted_investment_contribution_dates(start_date, end_date):
            txns.append(_txn(
                spec["source_account_id"], d, -amount_dollars,
                spec["description"], "Investments",
                institution_txn_id=trusted_investment_txn_id(spec["account_id"], d),
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


def _first_business_day(d: date) -> date:
    """Return d, moved forward to Monday if it falls on a weekend."""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def trusted_investment_contribution_dates(start: date, end: date) -> list[date]:
    """Monthly canonical investment transfer dates in [start, end]."""
    dates: list[date] = []
    for first in _month_firsts(start, end):
        d = _first_business_day(first)
        if start <= d <= end:
            dates.append(d)
    return dates


def trusted_investment_txn_id(account_id: str, contribution_date: date) -> str:
    """Stable institution transaction id for a canonical investment transfer."""
    return f"trusted_invest_{account_id}_{contribution_date.isoformat()}"


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
    # checking analogue. Brighton is the high-yield proxy; fidelity
    # brokerage represents the SPAXX money-market-fund 7-day yield on
    # the cash sweep position. DAL invariant guard enforces [0, 100].
    {"account_id": "summit_sav", "base_pct": 0.25, "drift_bps": 2},
    {"account_id": "summit_chk", "base_pct": 0.05, "drift_bps": 1},
    {"account_id": "brighton_sav", "base_pct": 4.25, "drift_bps": 3},
    {"account_id": "fidelity_brokerage", "base_pct": 4.30, "drift_bps": 4},
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
# Canonical trusted investment seeding uses round starting balances, monthly
# transfer rows, and flat fixture prices. Market-like behavior is intentionally
# excluded from this seed.

# Acorns default allocation (approximate)
_ACORNS_ALLOC = {"VOO": 0.55, "IJH": 0.15, "IJR": 0.15, "IXUS": 0.15}
_ACORNS_TICKERS = list(_ACORNS_ALLOC.keys())
_ACORNS_ACCT = "acorns_synthetic"


def _cache_prices(conn, prices: dict[str, dict[str, float]]) -> int:
    inserts = [
        (ticker, price_date, close_price)
        for ticker, rows in prices.items()
        for price_date, close_price in rows.items()
    ]
    if not inserts:
        return 0
    conn.executemany(
        """INSERT OR REPLACE INTO benchmark_prices
           (ticker, price_date, close_price) VALUES (?, ?, ?)""",
        inserts,
    )
    conn.commit()
    return len(inserts)


def _fetch_and_cache_prices(
    conn,
    tickers: list[str],
    start: date,
    end: date,
    *,
    use_live: bool = False,
) -> dict[str, dict[str, float]]:
    """Return daily closing prices, caching in benchmark_prices.

    Trusted synthetic seeding calls this with ``use_live=False`` so the seed is
    network-free and repeatable while still exercising the investment read
    paths that expect cached benchmark prices.
    """
    import logging
    log = logging.getLogger("sentry.seeder.prices")

    if not use_live:
        prices = _fallback_flat_prices(tickers, start, end)
        cached = _cache_prices(conn, prices)
        log.info("  Cached %d deterministic fixture price rows", cached)
        return prices

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
        log.warning("  yfinance not installed — using flat fixture prices")
        prices = _fallback_flat_prices(tickers, start, end)
        _cache_prices(conn, prices)
        return prices

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
            prices = _fallback_flat_prices(tickers, start, end)
            _cache_prices(conn, prices)
            return prices

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
        prices = _fallback_flat_prices(tickers, start, end)
        _cache_prices(conn, prices)
        return prices

    return result


def _fallback_flat_prices(
    tickers: list[str], start: date, end: date
) -> dict[str, dict[str, float]]:
    """Deterministic flat prices for the canonical trusted fixture."""
    result: dict[str, dict[str, float]] = {}
    d = start
    while d <= end:
        if d.weekday() < 5:  # trading days only
            d_str = d.isoformat()
            for ticker in tickers:
                result.setdefault(ticker, {})[d_str] = TRUSTED_INVESTMENT_FIXED_PRICE
        d += timedelta(days=1)
    return result

def generate_acorns_investment_history(
    conn,
    end_date: date,
    years: int = 3,
) -> dict:
    """Generate canonical no-market investment history for Acorns Synthetic."""
    return _generate_trusted_investment_account_history(
        conn, _ACORNS_ACCT, end_date, years
    )


# ── Fidelity synthetic investment universe ───────────────────────────────────

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
    """Generate canonical no-market investment history for Fidelity."""
    return _generate_trusted_investment_account_history(
        conn, _FIDELITY_ACCT, end_date, years
    )

# ── TSP synthetic investment universe ─────────────────────────────────────────

_TSP_FUNDS = {
    "TSP_C":     {"shares": 800.0,  "desc": "C Fund (S&P 500 match)"},
    "TSP_S":     {"shares": 600.0,  "desc": "S Fund (small/mid cap)"},
    "TSP_L2065": {"shares": 1800.0, "desc": "Lifecycle 2065"},
}
_TSP_TICKERS = list(_TSP_FUNDS)
_TSP_ACCT = "tsp_synthetic"


TRUSTED_INVESTMENT_FIXED_PRICE = 100.0
TRUSTED_INVESTMENT_ACCOUNT_SPECS = {
    _ACORNS_ACCT: {
        "account_id": _ACORNS_ACCT,
        "source_account_id": "summit_chk",
        "starting_cents": 1_000_000,
        "monthly_cents": 50_000,
        "description": "ACORNS INVEST TRANSFER",
        "contribution_type": "IMPLIED_BUY",
        "allocations": {
            "VOO": "0.55",
            "IJH": "0.15",
            "IJR": "0.15",
            "IXUS": "0.15",
        },
    },
    _FIDELITY_ACCT: {
        "account_id": _FIDELITY_ACCT,
        "source_account_id": "summit_chk",
        "starting_cents": 5_000_000,
        "monthly_cents": 100_000,
        "description": "FIDELITY EFT TRANSFER",
        "contribution_type": "BUY",
        "allocations": {ticker: "0.125" for ticker in _FIDELITY_TICKER_LIST},
    },
    _TSP_ACCT: {
        "account_id": _TSP_ACCT,
        "source_account_id": "summit_chk",
        "starting_cents": 10_000_000,
        "monthly_cents": 150_000,
        "description": "TSP CONTRIBUTION TRANSFER",
        "contribution_type": "BUY",
        "allocations": {
            "TSP_C": "0.50",
            "TSP_S": "0.30",
            "TSP_L2065": "0.20",
        },
    },
}


def _snapshot_dates_for_investment_seed(start: date, end: date) -> list[date]:
    dates = [start, *trusted_investment_contribution_dates(start, end), end]
    return sorted(set(dates))


def _cents_to_decimal(cents: int):
    from decimal import Decimal
    return Decimal(cents) / Decimal("100")


def _allocation_cents(total_cents: int, allocations: dict[str, str]) -> dict[str, int]:
    from decimal import Decimal, ROUND_HALF_UP

    tickers = list(allocations)
    allocated: dict[str, int] = {}
    running = 0
    for ticker in tickers[:-1]:
        cents = int(
            (Decimal(total_cents) * Decimal(allocations[ticker])).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        allocated[ticker] = cents
        running += cents
    allocated[tickers[-1]] = total_cents - running
    return allocated


def _generate_trusted_investment_account_history(
    conn,
    account_id: str,
    end_date: date,
    years: int,
) -> dict:
    """Generate the canonical no-market investment history for one account."""
    from decimal import Decimal
    import logging

    spec = TRUSTED_INVESTMENT_ACCOUNT_SPECS[account_id]
    log = logging.getLogger(f"sentry.seeder.{account_id}")
    start_date = end_date - timedelta(days=years * 365)
    tickers = list(spec["allocations"])
    fixed_price = Decimal(str(TRUSTED_INVESTMENT_FIXED_PRICE))
    prices = _fetch_and_cache_prices(conn, tickers, start_date, end_date)

    running_shares = {ticker: Decimal("0") for ticker in tickers}
    cumulative_cost = {ticker: Decimal("0.00") for ticker in tickers}
    ledger_rows: list[dict] = []
    links_to_apply: list[tuple[str, str, str]] = []

    def add_ledger_rows(
        event_date: date,
        total_cents: int,
        transaction_type: str,
        *,
        link_bank_txn: bool = False,
    ) -> None:
        allocated = _allocation_cents(total_cents, spec["allocations"])
        primary_ticker = tickers[0]
        for ticker in tickers:
            amount = _cents_to_decimal(allocated[ticker])
            shares = (amount / fixed_price).quantize(Decimal("0.00001"))
            running_shares[ticker] += shares
            cumulative_cost[ticker] += amount
            timestamp = f"{event_date.isoformat()}T09:00:00"
            ledger_rows.append({
                "account_id": account_id,
                "timestamp": timestamp,
                "ticker": ticker,
                "transaction_type": transaction_type,
                "share_delta": float(shares),
                "new_total_shares": float(running_shares[ticker]),
                "yfinance_closing_price": float(fixed_price),
                "estimated_transaction_value": float(amount),
                "share_delta_dec": str(shares),
                "new_total_shares_dec": str(running_shares[ticker]),
                "source": "seeder",
                "bank_txn_id": None,
                "cost_basis_dec": str(amount.quantize(Decimal("0.01"))),
                "realized_gain_dec": None,
                "settlement_date": _next_business_day(event_date).isoformat(),
                "commission_dec": "0.00",
                "fees_dec": "0.00",
            })
            if link_bank_txn and ticker == primary_ticker:
                links_to_apply.append((
                    timestamp,
                    ticker,
                    trusted_investment_txn_id(account_id, event_date),
                ))

    add_ledger_rows(start_date, spec["starting_cents"], "INITIAL_BASELINE")
    for contribution_date in trusted_investment_contribution_dates(start_date, end_date):
        add_ledger_rows(
            contribution_date,
            spec["monthly_cents"],
            spec["contribution_type"],
            link_bank_txn=True,
        )

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

    linked = 0
    for timestamp, ticker, institution_txn_id in links_to_apply:
        ledger = conn.execute(
            """
            SELECT id FROM positions_ledger
            WHERE account_id = ? AND timestamp = ? AND ticker = ?
            """,
            (account_id, timestamp, ticker),
        ).fetchone()
        txn = conn.execute(
            "SELECT id FROM transactions WHERE institution_txn_id = ?",
            (institution_txn_id,),
        ).fetchone()
        if ledger is None or txn is None:
            continue
        ledger_id = ledger["id"]
        txn_id = txn["id"]
        tag = f"invest:{account_id}:{timestamp[:10]}"
        conn.execute(
            "UPDATE transactions SET transfer_tag = ?, investment_link = ? WHERE id = ?",
            (tag, str(ledger_id), txn_id),
        )
        conn.execute(
            "UPDATE positions_ledger SET bank_txn_id = ? WHERE id = ?",
            (txn_id, ledger_id),
        )
        linked += 1

    snapshot_dates = _snapshot_dates_for_investment_seed(start_date, end_date)
    holdings: list[dict] = []
    snapshots: list[dict] = []
    contribution_dates = trusted_investment_contribution_dates(start_date, end_date)

    for snap_date in snapshot_dates:
        total_cents = spec["starting_cents"] + (
            spec["monthly_cents"]
            * sum(1 for d in contribution_dates if d <= snap_date)
        )
        allocated_total = _allocation_cents(total_cents, spec["allocations"])
        total_value = Decimal("0.00")
        for ticker in tickers:
            market_value = _cents_to_decimal(allocated_total[ticker])
            shares = (market_value / fixed_price).quantize(Decimal("0.00001"))
            total_value += market_value
            holdings.append({
                "account_id": account_id,
                "date": snap_date.isoformat(),
                "ticker": ticker,
                "shares": float(shares),
                "close_price": float(fixed_price),
                "market_value": float(market_value),
                "cost_basis": float(market_value),
            })
        snapshots.append({
            "account_id": account_id,
            "timestamp": f"{snap_date.isoformat()}T16:00:00",
            "total_account_value": float(total_value),
            "cash_balance": 0.0,
        })

    record_investment_holdings(conn, holdings)
    record_portfolio_snapshots(conn, snapshots)

    bucket_rows = []
    if account_id == _TSP_ACCT:
        for snap in snapshots:
            total_cents = int(round(float(snap["total_account_value"]) * 100))
            traditional_cents = int(round(total_cents * 0.35))
            roth_cents = total_cents - traditional_cents
            as_of = snap["timestamp"][:10]
            bucket_rows.append((account_id, "traditional", traditional_cents, 1.0, as_of))
            bucket_rows.append((account_id, "roth", roth_cents, 1.0, as_of))
        conn.executemany(
            """INSERT OR REPLACE INTO tax_buckets
               (account_id, bucket_type, balance, vested_pct, as_of)
               VALUES (?, ?, ?, ?, ?)""",
            bucket_rows,
        )

    conn.commit()
    log.info(
        "  canonical investment rows: ledger=%d, holdings=%d, snapshots=%d, linked=%d",
        len(ledger_rows), len(holdings), len(snapshots), linked,
    )
    return {
        "ledger_rows": len(ledger_rows),
        "holding_rows": len(holdings),
        "snapshot_rows": len(snapshots),
        "bucket_rows": len(bucket_rows),
        "prices_cached": sum(len(v) for v in prices.values()),
        "linked_txns": linked,
        "dividend_txns": 0,
    }


def generate_tsp_investment_history(
    conn,
    end_date: date,
    years: int = 3,
) -> dict:
    """Generate canonical no-market investment history for synthetic TSP."""
    return _generate_trusted_investment_account_history(
        conn, _TSP_ACCT, end_date, years
    )

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


def enrich_ticker_metadata(
    conn,
    tickers: list[str] | None = None,
    *,
    reference_date: date | None = None,
    use_live: bool = False,
) -> int:
    """Cache sector/industry/asset_class in ticker_metadata.

    Trusted synthetic seeding writes deterministic fallback metadata and stamps
    ``last_updated`` with the canonical reference date.  ``use_live=True`` is
    available for ad-hoc market experiments only.

    Returns number of tickers enriched.
    """
    import logging
    log = logging.getLogger("sentry.seeder.metadata")

    if tickers is None:
        tickers = _ALL_INVESTMENT_TICKERS
    if reference_date is None:
        reference_date = date.today()

    def _write_fallback(ticker: str) -> None:
        fb = _TICKER_METADATA_FALLBACK.get(ticker, {})
        conn.execute(
            """INSERT OR REPLACE INTO ticker_metadata
               (ticker, sector, industry, asset_class, last_updated)
               VALUES (?, ?, ?, ?, ?)""",
            (
                ticker,
                fb.get("sector", "Unknown"),
                fb.get("industry", "Unknown"),
                fb.get("asset_class", "Equity"),
                reference_date.isoformat(),
            ),
        )

    if not use_live:
        for ticker in tickers:
            _write_fallback(ticker)
        conn.commit()
        log.info("  %d deterministic metadata rows written", len(tickers))
        return len(tickers)

    # Check which tickers need updating
    to_update = []
    for ticker in tickers:
        row = conn.execute(
            "SELECT last_updated FROM ticker_metadata WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        if row:
            last = row[0]
            if last and (reference_date - date.fromisoformat(last)).days < 30:
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
                       VALUES (?, ?, ?, ?, ?)""",
                    (ticker, sector, industry, asset_class, reference_date.isoformat()),
                )
                enriched += 1
            except Exception as e:
                log.warning("  yfinance lookup failed for %s: %s — using fallback", ticker, e)
                _write_fallback(ticker)
                enriched += 1
    except ImportError:
        log.warning("  yfinance not installed — using fallback metadata")
        for ticker in to_update:
            _write_fallback(ticker)
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
    Quarterly KBB valuations for the single demo vehicle.
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
                "vehicle_id": "civic_2020",
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
            # AI-026: source label must overlap with at least one paycheck
            # transaction's description so find_matching_deposit_tx_id can
            # link the snapshot to its real deposit (the Sankey gross-up
            # path). "ACME CORP PAYROLL" matches the biweekly Quintin
            # paycheck transactions emitted by generate_transactions
            # (line 252). Live equivalent uses source='mypay_ras' which
            # would only match if the deposit description contains "mypay"
            # or "ras"; that gap is documented in the lineage YAML.
            "source": "ACME CORP PAYROLL",
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
    Phase 14 Phase B + C — income_sources registry seed rows.

    Phase B entries exercise the classifier:

    1. Quintin — employer retirement match. bypass_cash_routing=1 draws a
       pseudo-edge straight to STORED_ILLIQUID. ``monthly_amount_cents``
       in match_rule_json drives the Sankey flow amount.
    2. Quintin — officiating (contractor-style, no withholding).
       ``estimated_tax_reserve_pct=0`` reflects Phase B's posture of not
       computing a reserve; the field is reserved for a future projection.
    3. Amy — W-2 withheld source. Matches the seeded Amy payroll rows by
       counterparty substring.

    Phase C entries register dividend/interest archetypes so the Sankey
    groups and drawsthem as first-class income sources rather than
    miscellaneous "Interest"/"Investment Income" leaf nodes:

    4. Quintin — HYSA / bank interest. match_rule category='Interest'
       catches the seeded Brighton HYSA deposits AND would catch any future
       real bank-interest category. bypass_cash_routing=0 — these have a
       cash leg, they're not pseudo-flows.
    5. Quintin — Fidelity dividends. match_rule category='Investment Income'
       catches the Phase C generator's new per-dividend transaction rows.
       A future tax-projection path would set estimated_tax_reserve_pct>0.
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
        {
            "id": "seed_quintin_bank_interest",
            "display_label": "Bank interest (HYSA)",
            "owner_id": "quintin",
            "tax_treatment": "interest_dividend",
            "default_category": "Interest",
            "match_rule_json": {
                "category": "Interest",
                "owner_id": "quintin",
            },
            "estimated_tax_reserve_pct": 0.0,
            "bypass_cash_routing": 0,
            "active": 1,
        },
        {
            "id": "seed_quintin_fidelity_dividends",
            "display_label": "Investment dividends",
            "owner_id": "quintin",
            "tax_treatment": "interest_dividend",
            "default_category": "Investment Income",
            "match_rule_json": {
                "category": "Investment Income",
                "owner_id": "quintin",
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
