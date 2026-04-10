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


# ── Account set ──────────────────────────────────────────────────────────────
# Mirrors Institutions.json.  Duplicated here so the generator can be used
# without the JSON fixture.

ACCOUNTS: list[dict] = [
    {"institution_id": "summit", "account_id": "summit_chk_4501",
     "name": "Summit Checking", "type": "checking",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 6500},
    {"institution_id": "summit", "account_id": "summit_sav_7823",
     "name": "Summit Emergency Savings", "type": "savings",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 10000},
    {"institution_id": "summit", "account_id": "summit_cc_3341",
     "name": "Summit Visa Platinum", "type": "credit_card",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 0},
    {"institution_id": "summit", "account_id": "summit_mtg_9102",
     "name": "Summit Home Mortgage", "type": "loan",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": -230000},
    {"institution_id": "summit", "account_id": "summit_auto_6655",
     "name": "Summit Auto Loan", "type": "loan",
     "owner_id": "quintin", "is_active": False, "closed_at": "2025-04-15",
     "starting_balance": 0},
    {"institution_id": "coastal", "account_id": "coastal_chk_2210",
     "name": "Coastal Checking", "type": "checking",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 3000},
    {"institution_id": "coastal", "account_id": "coastal_cc_8847",
     "name": "Coastal Cash Rewards", "type": "credit_card",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 0},
    # P13 investments rebuild — one investment account seeded.
    # Further sources (Fidelity, TSP, Vanguard) return in subsequent P13
    # tasks.  Acorns Synthetic starts with a $0 balance and is ready to
    # receive transfers from checking accounts (P13-T03).
    {"institution_id": "acorns_synthetic", "account_id": "acorns_synthetic_0000",
     "name": "Acorns Synthetic", "type": "investment",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 0},
    {"institution_id": "brighton", "account_id": "brighton_sav_3300",
     "name": "Brighton HYSA", "type": "savings",
     "owner_id": "quintin", "is_active": True, "closed_at": None,
     "starting_balance": 3500},
    {"institution_id": "payflex", "account_id": "payflex_bnpl_0001",
     "name": "PayFlex BNPL", "type": "loan",
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
      - Biweekly Alex paycheck ($4000 net → summit_chk_4501)
      - Monthly Jordan freelance paycheck ($3500 net → coastal_chk_2210)
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
            "summit_chk_4501", d, 4000,
            "ACME CORP PAYROLL", "Paychecks/Salary",
        ))
        d += timedelta(days=14)

    # ── Monthly Jordan freelance paycheck (1st of month) ─────────────────────
    for d in _month_firsts(start_date, end_date):
        txns.append(_txn(
            "coastal_chk_2210", d, 3500,
            "JORDAN FREELANCE ACH", "Paychecks/Salary",
        ))

    # ── Monthly mortgage payment (5th of month) ──────────────────────────────
    # Emits BOTH legs: debit from checking (category 'Mortgages'), credit to
    # the loan account (category 'Loan Payments').  Both categories live in
    # EXCLUDED_FROM_SPEND so the payment never hits cash-flow spending totals.
    for d in _day_of_month(start_date, end_date, 5):
        txns.append(_txn(
            "summit_chk_4501", d, -1500,
            "SUMMIT HOME MORTGAGE", "Mortgages",
        ))
        txns.append(_txn(
            "summit_mtg_9102", d, 1500,
            "PAYMENT RECEIVED", "Loan Payments",
        ))

    # ── Monthly utilities (10th) ─────────────────────────────────────────────
    for d in _day_of_month(start_date, end_date, 10):
        txns.append(_txn(
            "summit_chk_4501", d, -200,
            "DUKE ENERGY ONLINE", "Utilities",
        ))

    # ── Monthly internet (12th) ──────────────────────────────────────────────
    for d in _day_of_month(start_date, end_date, 12):
        txns.append(_txn(
            "summit_chk_4501", d, -80,
            "SPECTRUM INTERNET", "Telephone Services",
        ))

    # ── Monthly phone bill on Jordan's checking (18th) ───────────────────────
    for d in _day_of_month(start_date, end_date, 18):
        txns.append(_txn(
            "coastal_chk_2210", d, -85,
            "T-MOBILE AUTOPAY", "Telephone Services",
        ))

    # ── Semi-annual auto insurance (Jan 1 / Jul 1) ───────────────────────────
    d = date(start_date.year, 1, 1)
    if d < start_date:
        d = date(start_date.year, 7, 1)
    while d <= end_date:
        if d >= start_date:
            txns.append(_txn(
                "summit_chk_4501", d, -600,
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
            "summit_cc_3341", d, -16,
            "NETFLIX.COM", "Dues and Subscriptions",
        ))
    for d in _day_of_month(start_date, end_date, 15):
        txns.append(_txn(
            "summit_cc_3341", d, -11,
            "SPOTIFY PREMIUM", "Dues and Subscriptions",
        ))

    # ── Amazon Prime annual (February 9) ─────────────────────────────────────
    d = date(start_date.year, 2, 9)
    while d <= end_date:
        if d >= start_date:
            txns.append(_txn(
                "summit_cc_3341", d, -140,
                "AMAZON PRIME RENEWAL", "Dues and Subscriptions",
            ))
        d = date(d.year + 1, 2, 9)

    # ── Planet Fitness (20th) on Jordan checking ─────────────────────────────
    for d in _day_of_month(start_date, end_date, 20):
        txns.append(_txn(
            "coastal_chk_2210", d, -25,
            "PLANET FITNESS", "Dues and Subscriptions",
        ))

    # ── Monthly HYSA interest credit (last day of month) ─────────────────────
    for d in _last_of_month(start_date, end_date):
        txns.append(_txn(
            "brighton_sav_3300", d, 45,
            "BRIGHTON HYSA INTEREST", "Interest",
        ))

    # ── Paired transfers (both legs) ─────────────────────────────────────────
    # Emergency savings
    for d in _day_of_month(start_date, end_date, 3):
        txns.append(_txn(
            "summit_chk_4501", d, -800,
            "TRANSFER TO SUMMIT SAVINGS", "Transfers",
        ))
        txns.append(_txn(
            "summit_sav_7823", d, 800,
            "TRANSFER FROM SUMMIT CHECKING", "Transfers",
        ))
    # Brighton HYSA from Summit
    for d in _day_of_month(start_date, end_date, 4):
        txns.append(_txn(
            "summit_chk_4501", d, -500,
            "TRANSFER TO BRIGHTON HYSA", "Transfers",
        ))
        # Credit lands on Brighton one day later
        landing = d + timedelta(days=1)
        if landing <= end_date:
            txns.append(_txn(
                "brighton_sav_3300", landing, 500,
                "TRANSFER FROM SUMMIT CHECKING", "Transfers",
            ))
    # Brighton HYSA from Coastal
    for d in _day_of_month(start_date, end_date, 4):
        txns.append(_txn(
            "coastal_chk_2210", d, -250,
            "TRANSFER TO BRIGHTON HYSA", "Transfers",
        ))
        landing = d + timedelta(days=1)
        if landing <= end_date:
            txns.append(_txn(
                "brighton_sav_3300", landing, 250,
                "TRANSFER FROM COASTAL CHECKING", "Transfers",
            ))
    # ── Acorns Synthetic: fixed bank-side debits (P13-T03) ─────────────────
    # Monthly fee ($1 on the 1st) — true expense, stays in spending metrics.
    # Recurring auto-invest ($350 on the 4th) — investment contribution.
    # Roundups use RNG so they're generated AFTER the CC backfill block
    # to avoid shifting the shared RNG state for other transactions.
    for d in _day_of_month(start_date, end_date, 1):
        txns.append(_txn(
            "summit_chk_4501", d, -1,
            "ACORNS MONTHLY FEE", "Investment Fees",
        ))
    for d in _day_of_month(start_date, end_date, 4):
        txns.append(_txn(
            "summit_chk_4501", d, -350,
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
            "summit_cc_3341", d, -g,
            "KROGER SUPERMARKET", "Groceries",
        ))
        # 3% chance of refund
        if rng.random() < 0.03:
            refund_amt = min(g, 25)  # small partial refund
            refund_date = d + timedelta(days=rng.randint(2, 4))
            if refund_date <= end_date:
                refund_pending.append((refund_date, "summit_cc_3341", refund_amt))

        # Dining alternating across both CC accounts
        dining_amt = rng.choice(DINING_TIERS)
        dining_acct = "summit_cc_3341" if rng.random() < 0.6 else "coastal_cc_8847"
        txns.append(_txn(
            dining_acct, d, -dining_amt,
            "LOCAL DINER", "Restaurants/Dining",
        ))

        # Gas on Summit Visa
        gas_amt = rng.choice(GAS_TIERS)
        txns.append(_txn(
            "summit_cc_3341", d, -gas_amt,
            "SHELL GAS STATION", "Auto",
        ))

        # Shopping on Summit Visa
        shop_amt = rng.choice(SHOPPING_TIERS)
        txns.append(_txn(
            "summit_cc_3341", d, -shop_amt,
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
    # equal to the prior cycle's actual charges.  This guarantees the CC
    # balance returns to ≈ 0 each cycle (real autopay-full-balance behavior)
    # and is invariant to whatever charges the variable-spending block emits.
    cc_payment_specs: list[tuple[str, str, str]] = [
        ("summit_cc_3341", "summit_chk_4501", "SUMMIT VISA PAYMENT"),
        ("coastal_cc_8847", "coastal_chk_2210", "COASTAL CC PAYMENT"),
    ]
    for d in _day_of_month(start_date, end_date, 25):
        prior = d - timedelta(days=30)
        for cc_acct, chk_acct, chk_desc in cc_payment_specs:
            cycle_charges = sum(
                -t["signed_amount"] for t in txns
                if t["account_id"] == cc_acct
                and t["signed_amount"] < 0
                and prior < date.fromisoformat(t["posting_date"]) <= d
            )
            if cycle_charges <= 0:
                continue
            amt = round(cycle_charges)
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
                "summit_chk_4501", ru_date, -ru_amt,
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


# ── Investment history (P13-T03) ─────────────────────────────────────────────
#
# Rebuild of investment seeding for the Acorns Synthetic account.  Uses real
# yFinance historical prices (cached in benchmark_prices) so the synthetic
# portfolio tracks realistic market performance.

# Acorns default allocation (approximate)
_ACORNS_ALLOC = {"VOO": 0.55, "IJH": 0.15, "IJR": 0.15, "IXUS": 0.15}
_ACORNS_TICKERS = list(_ACORNS_ALLOC.keys())
_ACORNS_ACCT = "acorns_synthetic_0000"


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
    bases = {"VOO": 380.0, "IJH": 250.0, "IJR": 98.0, "IXUS": 60.0}
    # Monthly drift
    drifts = {"VOO": 1.5, "IJH": 0.8, "IJR": 0.4, "IXUS": 0.3}

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
        if t["account_id"] == "summit_chk_4501"
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
            snapshot_rows.append((
                _ACORNS_ACCT,
                f"{d.isoformat()}T16:00:00",
                round(total_value, 2),
                0.0,  # cash_balance
            ))

        d += timedelta(days=7)

    conn.executemany(
        """INSERT INTO portfolio_snapshots
           (account_id, timestamp, total_account_value, cash_balance)
           VALUES (?, ?, ?, ?)""",
        snapshot_rows,
    )
    log.info("  %d portfolio_snapshots rows inserted", len(snapshot_rows))

    conn.commit()

    return {
        "ledger_rows": len(ledger_rows),
        "snapshot_rows": len(snapshot_rows),
        "prices_cached": sum(len(v) for v in prices.values()),
    }


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
            "owner_id": a.get("owner_id"),
            "is_active": a.get("is_active", True),
            "closed_at": a.get("closed_at"),
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
