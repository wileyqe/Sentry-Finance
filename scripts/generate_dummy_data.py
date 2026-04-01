"""Generate deterministic dummy data for the Sentry Finance demo app."""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

SEED = 42
random.seed(SEED)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "dummy_data"
START = date(2023, 1, 1)
END = date(2025, 12, 31)

OWNERS = [{"id": "alex", "display_name": "Alex"}, {"id": "jordan", "display_name": "Jordan"}]

STARTING_BALANCES = {
    "summit_chk_4501": 5200.00,
    "summit_sav_7823": 12500.00,
    "summit_cc_3341": -320.00,
    "summit_mtg_9102": -230100.00,
    "summit_auto_6655": -16400.00,
    "coastal_chk_2210": 2800.00,
    "coastal_cc_8847": 0.00,
    "vanguard_inv_5501": 98000.00,
    "vanguard_ret_5502": 72000.00,
    "greenleaf_inv_1001": 4200.00,
    "brighton_sav_3300": 3500.00,
    "payflex_bnpl_0001": 0.00,
}

TARGET_END_BALANCES = {
    "summit_chk_4501": 8245.00,
    "summit_sav_7823": 22100.00,
    "summit_cc_3341": -487.00,
    "summit_mtg_9102": -218450.00,
    "summit_auto_6655": 0.00,
    "coastal_chk_2210": 3820.00,
    "coastal_cc_8847": 0.00,
    "vanguard_inv_5501": 145200.00,
    "vanguard_ret_5502": 89400.00,
    "greenleaf_inv_1001": 8750.00,
    "brighton_sav_3300": 11600.00,
    "payflex_bnpl_0001": 0.00,
}

ACCOUNT_ROWS = [
    {"institution_id": "summit", "account_id": "summit_chk_4501", "name": "Summit Checking", "type": "checking", "balance": 8245.00, "owner_id": "alex"},
    {"institution_id": "summit", "account_id": "summit_sav_7823", "name": "Summit Emergency Savings", "type": "savings", "balance": 22100.00, "owner_id": "alex"},
    {"institution_id": "summit", "account_id": "summit_cc_3341", "name": "Summit Visa Platinum", "type": "credit_card", "balance": -487.00, "owner_id": None},
    {"institution_id": "summit", "account_id": "summit_mtg_9102", "name": "Summit Home Mortgage", "type": "loan", "balance": -218450.00, "owner_id": "alex"},
    {"institution_id": "summit", "account_id": "summit_auto_6655", "name": "Summit Auto Loan", "type": "loan", "balance": 0.00, "owner_id": "alex", "is_active": False, "closed_at": "2025-04-15"},
    {"institution_id": "coastal", "account_id": "coastal_chk_2210", "name": "Coastal Checking", "type": "checking", "balance": 3820.00, "owner_id": "jordan"},
    {"institution_id": "coastal", "account_id": "coastal_cc_8847", "name": "Coastal Cash Rewards", "type": "credit_card", "balance": 0.00, "owner_id": "jordan"},
    {"institution_id": "vanguard_prime", "account_id": "vanguard_inv_5501", "name": "Vanguard Brokerage", "type": "investment", "balance": 145200.00, "owner_id": "alex"},
    {"institution_id": "vanguard_prime", "account_id": "vanguard_ret_5502", "name": "Vanguard 401k Rollover", "type": "investment", "balance": 89400.00, "owner_id": "alex"},
    {"institution_id": "greenleaf", "account_id": "greenleaf_inv_1001", "name": "Greenleaf Invest", "type": "investment", "balance": 8750.00, "owner_id": "jordan"},
    {"institution_id": "brighton", "account_id": "brighton_sav_3300", "name": "Brighton HYSA", "type": "savings", "balance": 11600.00, "owner_id": None},
    {"institution_id": "payflex", "account_id": "payflex_bnpl_0001", "name": "PayFlex BNPL", "type": "loan", "balance": 0.00, "owner_id": "jordan", "is_active": False, "closed_at": "2025-04-30"},
]

MERCHANTS = {
    "Groceries": ["KROGER #1234", "ALDI BLOOMINGTON", "TRADER JOES #567", "MEIJER #42"],
    "Restaurants/Dining": ["CHICK-FIL-A #1892", "CHIPOTLE ONLINE", "FIRST WATCH BLOOMINGTON", "DOORDASH*DASHPASS", "LOCAL TACO HOUSE"],
    "Gasoline/Fuel": ["SHELL OIL 34821", "CIRCLE K #1456", "SPEEDWAY 02814", "MARATHON #5541"],
    "General Merchandise": ["AMAZON.COM*AB12CD", "TARGET #1234", "WALMART SC #5678", "HOMEGOODS #0912"],
    "Entertainment": ["AMC BLOOMINGTON 12", "SPOTIFY STORE", "STEAMGAMES.COM", "NETFLIX.COM"],
    "Clothing/Shoes": ["OLD NAVY #1445", "DSW SHOES #221", "H&M STORE 1132"],
    "Personal Care": ["ULTA #2201", "TARGET BEAUTY", "SEPHORA ONLINE"],
    "Healthcare/Medical": ["CVS PHARMACY 0912", "IU HEALTH CLINIC", "WALGREENS RX #331"],
    "Home Improvement": ["LOWES #1843", "ACE HARDWARE 143", "HOME DEPOT 0412"],
}

UNCATEGORIZED_MERCHANTS = [
    "TXN*8847261-REF",
    "POS PURCHASE 11/15",
    "MISC DEBIT 042",
    "ACH TRACE 664813",
    "WEB PMT 92015",
    "CARD 5417 AUTH",
    "TEL DR 000883",
    "CHECKCARD 7714",
]

BUDGET_BASELINES = {
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
    "Charitable Giving": 50,
}


@dataclass
class LoanState:
    balance: float
    annual_rate: float


def month_iter():
    current = date(START.year, START.month, 1)
    while current <= END:
        yield current.year, current.month
        current = date(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1)


def month_end(year: int, month: int) -> date:
    return date(year + (month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)


def semi_monthly_dates():
    for year, month in month_iter():
        yield date(year, month, 1)
        yield date(year, month, 15)


def quarterly_dates():
    return [
        date(2023, 1, 1), date(2023, 4, 1), date(2023, 7, 1), date(2023, 10, 1),
        date(2024, 1, 1), date(2024, 4, 1), date(2024, 7, 1), date(2024, 10, 1),
        date(2025, 1, 1), date(2025, 4, 1), date(2025, 7, 1), date(2025, 12, 31),
    ]


def choose_day(year: int, month: int, start_day: int, end_day: int) -> date:
    return date(year, month, random.randint(start_day, min(end_day, month_end(year, month).day)))


def add_tx(rows: list[dict], account_id: str, when: date, amount: float, merchant: str, category: str) -> None:
    rows.append({"account_id": account_id, "date": when.isoformat(), "amount": round(amount, 2), "merchant": merchant, "category": category})


def jitter(amount: float, spread: float) -> float:
    return round(amount + random.uniform(-spread, spread), 2)


def distribute_total(total: float, count: int) -> list[float]:
    if count <= 1:
        return [round(total, 2)]
    weights = [random.uniform(0.15, 1.0) for _ in range(count)]
    values = [round(total * w / sum(weights), 2) for w in weights]
    values[-1] = round(values[-1] + total - sum(values), 2)
    return values


def balance_as_of(starting_balance: float, transactions: list[dict], cutoff: date) -> float:
    return round(starting_balance + sum(tx["amount"] for tx in transactions if date.fromisoformat(tx["date"]) <= cutoff), 2)


def build_alex_paychecks(rows: list[dict]) -> None:
    current = date(2023, 1, 6)
    bases = {2023: 2158.0, 2024: 2222.0, 2025: 2288.0}
    while current <= END:
        add_tx(rows, "summit_chk_4501", current, jitter(bases[current.year], 5.0), "ACME CORP PAYROLL", "Paychecks/Salary")
        current += timedelta(days=14)


def build_jordan_income(rows: list[dict]) -> None:
    for year, month in month_iter():
        if (year == 2023 and month in {8, 9, 10}) or (year == 2024 and month in {6, 7, 8, 9}):
            continue
        base = 3467.0 if year == 2023 or (year == 2024 and month < 10) else 3667.0
        add_tx(rows, "coastal_chk_2210", date(year, month, 1), jitter(base, 50.0), "JORDAN FREELANCE ACH", "Paychecks/Salary")


def build_tax_refunds(rows: list[dict]) -> None:
    add_tx(rows, "summit_chk_4501", date(2023, 3, 15), 2400.0, "IRS TREAS 310", "Tax Refund")
    add_tx(rows, "summit_chk_4501", date(2024, 3, 14), 2100.0, "IRS TREAS 310", "Tax Refund")
    add_tx(rows, "summit_chk_4501", date(2025, 3, 18), 1800.0, "IRS TREAS 310", "Tax Refund")


def utility_amount(month: int) -> float:
    if month in {12, 1, 2}:
        return round(random.uniform(135, 165), 2)
    if month in {6, 7, 8}:
        return round(random.uniform(120, 155), 2)
    return round(random.uniform(85, 125), 2)


def build_fixed_bills(rows: list[dict]) -> None:
    mortgage = LoanState(STARTING_BALANCES["summit_mtg_9102"], 0.0425)
    auto = LoanState(STARTING_BALANCES["summit_auto_6655"], 0.039)
    for year, month in month_iter():
        first = date(year, month, 1)
        fifteenth = date(year, month, 15)
        add_tx(rows, "summit_chk_4501", first, -1478.0, "Summit Home Mortgage", "Mortgages")
        mtg_interest = round(abs(mortgage.balance) * mortgage.annual_rate / 12.0, 2)
        mortgage.balance = round(mortgage.balance + (1478.0 - mtg_interest), 2)
        add_tx(rows, "summit_mtg_9102", first, -mtg_interest, "Summit Mortgage Interest", "Interest")
        add_tx(rows, "summit_mtg_9102", first, 1478.0, "Summit Home Mortgage", "Loan Payments")
        if fifteenth <= date(2025, 4, 15):
            auto_interest = round(abs(auto.balance) * auto.annual_rate / 12.0, 2)
            payment = round(abs(auto.balance) + auto_interest, 2) if fifteenth == date(2025, 4, 15) else 612.0
            auto.balance = round(auto.balance + (payment - auto_interest), 2)
            add_tx(rows, "summit_chk_4501", fifteenth, -payment, "Summit Auto Loan", "Loan Payments")
            add_tx(rows, "summit_auto_6655", fifteenth, -auto_interest, "Summit Auto Interest", "Interest")
            add_tx(rows, "summit_auto_6655", fifteenth, payment, "Summit Auto Loan", "Loan Payments")
        add_tx(rows, "summit_chk_4501", date(year, month, 5), -utility_amount(month), "DUKE ENERGY ONLINE", "Utilities")
        add_tx(rows, "summit_chk_4501", date(year, month, 12), -79.99, "SPECTRUM INTERNET", "Telephone Services")
        add_tx(rows, "coastal_chk_2210", date(year, month, 18), -85.0, "T-MOBILE AUTOPAY", "Telephone Services")
        add_tx(rows, "coastal_chk_2210", date(year, month, 20), -25.0, "PLANET FITNESS", "Dues and Subscriptions")
        add_tx(rows, "summit_cc_3341", date(year, month, 8), -15.99, "NETFLIX", "Dues and Subscriptions")
        add_tx(rows, "summit_cc_3341", date(year, month, 15), -10.99, "SPOTIFY", "Dues and Subscriptions")
        if month == 2:
            add_tx(rows, "summit_cc_3341", date(year, 2, 9), -139.0, "AMAZON PRIME", "Dues and Subscriptions")
        if month in {1, 7}:
            add_tx(rows, "summit_chk_4501", first, -624.0, "GEICO AUTO", "Insurance")
    adjustment = round(TARGET_END_BALANCES["summit_mtg_9102"] - mortgage.balance, 2)
    if abs(adjustment) > 0.01:
        add_tx(rows, "summit_mtg_9102", date(2025, 12, 31), adjustment, "Summit Principal Adjustment", "Loan Payments")
        add_tx(rows, "summit_chk_4501", date(2025, 12, 31), -adjustment, "Summit Principal Adjustment", "Transfers")


def add_variable_spend(rows: list[dict], year: int, month: int, account_id: str, category: str, total: float, count_range: tuple[int, int]) -> None:
    if total <= 0:
        return
    count = max(1, random.randint(*count_range) * 3)
    for piece in distribute_total(total, count):
        add_tx(rows, account_id, choose_day(year, month, 2, 27), -piece, random.choice(MERCHANTS[category]), category)


def build_alex_variable_spending(rows: list[dict]) -> None:
    for index, (year, month) in enumerate(month_iter()):
        holiday = month in {11, 12}
        groceries = random.uniform(450, 600)
        dining = random.uniform(80, 200) * (1.4 if holiday else 1.0)
        merch = random.uniform(50, 300) * (1.6 if holiday else 1.0)
        add_variable_spend(rows, year, month, "summit_chk_4501", "Groceries", groceries * 0.7, (3, 4))
        add_variable_spend(rows, year, month, "summit_cc_3341", "Groceries", groceries * 0.3, (1, 2))
        add_variable_spend(rows, year, month, "summit_chk_4501", "Gasoline/Fuel", random.uniform(120, 180), (3, 4))
        add_variable_spend(rows, year, month, "summit_chk_4501", "Restaurants/Dining", dining * 0.55, (1, 3))
        add_variable_spend(rows, year, month, "summit_cc_3341", "Restaurants/Dining", dining * 0.45, (1, 3))
        add_variable_spend(rows, year, month, "summit_cc_3341", "General Merchandise", merch, (1, 4))
        if random.random() > 0.35:
            add_variable_spend(rows, year, month, "summit_chk_4501", "Healthcare/Medical", random.uniform(0, 150), (1, 1))
        if random.random() > 0.45:
            add_variable_spend(rows, year, month, "summit_chk_4501", "Home Improvement", random.uniform(0, 200), (1, 1))
        if holiday:
            for _ in range(random.randint(2, 3)):
                category = random.choice(["Charitable Giving", "General Merchandise"])
                merchant = "LOCAL GIFT SHOP" if category == "General Merchandise" else "COMMUNITY FUND"
                add_tx(rows, "summit_cc_3341", choose_day(year, month, 10, 24), -round(random.uniform(30, 150), 2), merchant, category)
        if index % 5 == 0:
            add_tx(rows, "summit_chk_4501", choose_day(year, month, 6, 24), -round(random.uniform(18, 72), 2), random.choice(UNCATEGORIZED_MERCHANTS), "Uncategorized")


def jordan_balance_target(year: int, month: int) -> float | None:
    return {
        "2023-08": -1050.0, "2023-09": -2100.0, "2023-10": -3200.0, "2023-11": -3000.0,
        "2023-12": -2500.0, "2024-01": -1800.0, "2024-02": -900.0, "2024-03": -200.0,
        "2024-04": 0.0, "2024-06": -1550.0, "2024-07": -3350.0, "2024-08": -5000.0,
        "2024-09": -6350.0, "2024-10": -6500.0, "2024-11": -5750.0, "2024-12": -5100.0,
        "2025-01": -4100.0, "2025-02": -3550.0, "2025-03": -2950.0, "2025-04": -2400.0,
        "2025-05": -1850.0, "2025-06": -1250.0, "2025-07": -700.0, "2025-08": -350.0,
        "2025-09": -100.0, "2025-10": 0.0, "2025-11": 0.0, "2025-12": 0.0,
    }.get(f"{year:04d}-{month:02d}")


def build_jordan_variable_spending(rows: list[dict]) -> None:
    prev_balance = STARTING_BALANCES["coastal_cc_8847"]
    for index, (year, month) in enumerate(month_iter()):
        employed = not ((year == 2023 and month in {8, 9, 10}) or (year == 2024 and month in {6, 7, 8, 9}))
        holiday = month in {11, 12}
        trend = 1.0 + (index / 35.0) * 0.18
        groceries = random.uniform(300, 450)
        dining = random.uniform(150, 350) * trend * (1.4 if holiday else 1.0)
        entertainment = random.uniform(50, 200) * (0.5 if not employed else 1.0)
        clothing = random.uniform(0, 150) * (0.5 if not employed else 1.0)
        merch = random.uniform(50, 250) * (1.6 if holiday else 1.0)
        care = random.uniform(30, 60)
        grocery_check, grocery_cc = (groceries * 0.6, groceries * 0.4) if employed else (groceries * 0.12, groceries * 0.88)
        dining_check, dining_cc = (dining * 0.3, dining * 0.7) if employed else (dining * 0.05, dining * 0.95)
        add_variable_spend(rows, year, month, "coastal_chk_2210", "Groceries", grocery_check, (1, 2))
        add_variable_spend(rows, year, month, "coastal_cc_8847", "Groceries", grocery_cc, (2, 3))
        add_variable_spend(rows, year, month, "coastal_chk_2210", "Restaurants/Dining", dining_check, (1, 2))
        add_variable_spend(rows, year, month, "coastal_cc_8847", "Restaurants/Dining", dining_cc, (3, 6))
        add_variable_spend(rows, year, month, "coastal_cc_8847", "Entertainment", entertainment, (1, 3))
        add_variable_spend(rows, year, month, "coastal_cc_8847", "Clothing/Shoes", clothing, (1, 2))
        add_variable_spend(rows, year, month, "coastal_cc_8847", "General Merchandise", merch, (1, 3))
        add_variable_spend(rows, year, month, "coastal_cc_8847", "Personal Care", care, (1, 2))
        if not employed:
            add_variable_spend(rows, year, month, "coastal_cc_8847", "General Merchandise", random.uniform(250, 400), (2, 3))
        if holiday:
            for _ in range(random.randint(2, 3)):
                add_tx(rows, "coastal_cc_8847", choose_day(year, month, 12, 24), -round(random.uniform(35, 145), 2), "BOUTIQUE HOLIDAY SHOP", random.choice(["General Merchandise", "Charitable Giving"]))
        if index % 7 == 0:
            add_tx(rows, "coastal_cc_8847", choose_day(year, month, 5, 22), -round(random.uniform(14, 68), 2), random.choice(UNCATEGORIZED_MERCHANTS), "Uncategorized")
        key = f"{year:04d}-{month:02d}"
        charges = round(sum(-tx["amount"] for tx in rows if tx["account_id"] == "coastal_cc_8847" and tx["date"].startswith(key)), 2)
        target = jordan_balance_target(year, month) or 0.0
        payment = max(0.0, round(target - prev_balance + charges, 2))
        if payment:
            add_tx(rows, "coastal_chk_2210", date(year, month, 28), -payment, "Coastal CC Payment", "Credit Card Payments")
            add_tx(rows, "coastal_cc_8847", date(year, month, 28), payment, "Coastal CC Payment", "Credit Card Payments")
        prev_balance = round(prev_balance - charges + payment, 2)


def build_shared_transfers(rows: list[dict]) -> None:
    for year, month in month_iter():
        employed = not ((year == 2023 and month in {8, 9, 10}) or (year == 2024 and month in {6, 7, 8, 9}))
        sav_amount = 800.0 if date(year, month, 1) >= date(2025, 5, 1) else random.choice([400.0, 450.0, 500.0, 550.0, 600.0])
        add_tx(rows, "summit_chk_4501", date(year, month, 3), -sav_amount, "Transfer to Summit Savings", "Transfers")
        add_tx(rows, "summit_sav_7823", date(year, month, 3), sav_amount, "Transfer from Summit Checking", "Transfers")
        add_tx(rows, "summit_chk_4501", date(year, month, 4), -500.0, "Transfer to Brighton HYSA", "Transfers")
        add_tx(rows, "brighton_sav_3300", date(year, month, 4), 500.0, "Transfer from Summit Checking", "Transfers")
        if employed:
            add_tx(rows, "coastal_chk_2210", date(year, month, 4), -250.0, "Transfer to Brighton HYSA", "Transfers")
            add_tx(rows, "brighton_sav_3300", date(year, month, 4), 250.0, "Transfer from Coastal Checking", "Transfers")


def build_shared_cc_payments(rows: list[dict]) -> None:
    add_tx(rows, "summit_chk_4501", date(2023, 1, 25), -320.0, "Summit Visa Payment", "Credit Card Payments")
    add_tx(rows, "summit_cc_3341", date(2023, 1, 25), 320.0, "Summit Visa Payment", "Credit Card Payments")
    for year, month in month_iter():
        prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
        key = f"{prev_year:04d}-{prev_month:02d}"
        charges = round(sum(-tx["amount"] for tx in rows if tx["account_id"] == "summit_cc_3341" and tx["date"].startswith(key) and tx["amount"] < 0), 2)
        if charges:
            add_tx(rows, "summit_chk_4501", date(year, month, 25), -charges, "Summit Visa Payment", "Credit Card Payments")
            add_tx(rows, "summit_cc_3341", date(year, month, 25), charges, "Summit Visa Payment", "Credit Card Payments")


def build_investment_contributions(rows: list[dict]) -> None:
    for year, month in month_iter():
        add_tx(rows, "summit_chk_4501", date(year, month, 6), -400.0, "Transfer to Vanguard Brokerage", "Transfers")
        add_tx(rows, "vanguard_inv_5501", date(year, month, 6), 400.0, "Transfer from Summit Checking", "Transfers")
        if not ((year == 2023 and month in {8, 9, 10}) or (year == 2024 and month in {6, 7, 8, 9})):
            add_tx(rows, "coastal_chk_2210", date(year, month, 6), -100.0, "Greenleaf Auto-Invest", "Transfers")
            add_tx(rows, "greenleaf_inv_1001", date(year, month, 6), 100.0, "Transfer from Coastal Checking", "Transfers")


def build_one_time_events(rows: list[dict]) -> None:
    for amount, merchant, day in zip([1125.4, 1044.6, 1030.0], ["SKYBOUND AIR", "LAKEVIEW RESORT", "VACAY RIDESHARE"], [15, 15, 16]):
        add_tx(rows, "summit_cc_3341", date(2023, 5, day), -amount, merchant, "Travel")
    add_tx(rows, "summit_chk_4501", date(2024, 4, 10), -5800.0, "ALL SEASONS HEATING", "Home Maintenance")
    add_tx(rows, "payflex_bnpl_0001", date(2024, 11, 1), -1100.0, "BEST BUY via PayFlex", "Electronics")
    for when, amount in zip([date(2024, 11, 30), date(2024, 12, 31), date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31), date(2025, 4, 30)], [183.33, 183.33, 183.33, 183.33, 183.34, 183.34]):
        add_tx(rows, "coastal_chk_2210", when, -amount, "PayFlex Payment", "Loan Payments")
        add_tx(rows, "payflex_bnpl_0001", when, amount, "PayFlex Payment", "Loan Payments")
    for amount, merchant, day in zip([1265.1, 1210.3, 1099.6, 925.0], ["SKYBOUND AIR", "OCEANBREEZE HOTEL", "COASTAL CAR RENTAL", "BEACH DINING"], [10, 10, 11, 12]):
        add_tx(rows, "summit_cc_3341", date(2025, 7, day), -amount, merchant, "Travel")


def build_hysa_interest(rows: list[dict]) -> None:
    hysa_rows = [tx for tx in rows if tx["account_id"] == "brighton_sav_3300"]
    for year, month in month_iter():
        as_of = month_end(year, month)
        interest = round(balance_as_of(STARTING_BALANCES["brighton_sav_3300"], hysa_rows, as_of - timedelta(days=1)) * 0.045 / 12.0, 2)
        add_tx(rows, "brighton_sav_3300", as_of, interest, "Brighton HYSA Interest", "Interest")
        hysa_rows.append(rows[-1])


def reconcile_final_balances(rows: list[dict]) -> None:
    for account_id, merchant, category in [
        ("summit_sav_7823", "Year-End Savings Adjustment", "Transfers"),
        ("brighton_sav_3300", "Year-End HYSA Adjustment", "Transfers"),
        ("coastal_chk_2210", "Household Settlement", "Transfers"),
        ("summit_chk_4501", "Year-End Cash Sweep", "Transfers"),
        ("summit_cc_3341", "December Statement Credit", "Credit Card Payments"),
    ]:
        current = balance_as_of(STARTING_BALANCES[account_id], [tx for tx in rows if tx["account_id"] == account_id], END)
        diff = round(TARGET_END_BALANCES[account_id] - current, 2)
        if abs(diff) > 0.01:
            add_tx(rows, account_id, date(2025, 12, 31), diff, merchant, category)
    for account_id, payoff_day, merchant in [("summit_auto_6655", date(2025, 4, 15), "Auto Loan Payoff Adjustment"), ("payflex_bnpl_0001", date(2025, 4, 30), "PayFlex Payoff Adjustment")]:
        balance = balance_as_of(STARTING_BALANCES[account_id], [tx for tx in rows if tx["account_id"] == account_id], END)
        if abs(balance) > 0.01:
            add_tx(rows, account_id, payoff_day, -balance, merchant, "Loan Payments")


def sort_transactions(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (row["date"], row["account_id"], row["merchant"], row["amount"]))


def generate_transactions() -> list[dict]:
    rows: list[dict] = []
    build_alex_paychecks(rows)
    build_jordan_income(rows)
    build_tax_refunds(rows)
    build_fixed_bills(rows)
    build_alex_variable_spending(rows)
    build_jordan_variable_spending(rows)
    build_shared_transfers(rows)
    build_investment_contributions(rows)
    build_one_time_events(rows)
    build_shared_cc_payments(rows)
    build_hysa_interest(rows)
    reconcile_final_balances(rows)
    rows = sort_transactions(rows)
    return rows


def derive_balance_snapshots(transactions: list[dict]) -> list[dict]:
    snapshots = []
    for account in ACCOUNT_ROWS:
        aid = account["account_id"]
        if account["type"] == "investment":
            continue
        dates = [d for d in semi_monthly_dates() if aid != "payflex_bnpl_0001" or date(2024, 11, 1) <= d <= date(2025, 4, 30)]
        own_rows = [tx for tx in transactions if tx["account_id"] == aid]
        for snap_date in dates:
            snapshots.append({"account_id": aid, "date": snap_date.isoformat(), "balance_amount": balance_as_of(STARTING_BALANCES[aid], own_rows, snap_date)})
    return snapshots


def price_point(points: list[tuple[date, float]], current: date, noise: float) -> float:
    if current <= points[0][0]:
        return points[0][1]
    if current >= points[-1][0]:
        return points[-1][1]
    for left, right in zip(points, points[1:]):
        if left[0] <= current <= right[0]:
            ratio = (current - left[0]).days / (right[0] - left[0]).days
            return round((left[1] + (right[1] - left[1]) * ratio) * (1 + math.sin((current.month + ratio) * 2.0) * noise), 2)
    return round(points[-1][1], 2)


def monthly_price_series() -> dict[str, dict[str, float]]:
    anchors = {
        "VTI": [(date(2023, 1, 1), 196.0), (date(2024, 6, 1), 215.0), (date(2024, 10, 1), 198.0), (date(2025, 12, 1), 248.0)],
        "VXUS": [(date(2023, 1, 1), 52.0), (date(2024, 6, 1), 56.0), (date(2024, 10, 1), 51.0), (date(2025, 12, 1), 61.0)],
        "BND": [(date(2023, 1, 1), 72.0), (date(2024, 6, 1), 73.0), (date(2024, 10, 1), 71.0), (date(2025, 12, 1), 74.0)],
        "VFIFX": [(date(2023, 1, 1), 24.0), (date(2024, 6, 1), 26.0), (date(2024, 10, 1), 24.0), (date(2025, 12, 1), 29.0)],
        "VOO": [(date(2023, 1, 1), 360.0), (date(2024, 6, 1), 395.0), (date(2024, 10, 1), 365.0), (date(2025, 12, 1), 455.0)],
        "IJH": [(date(2023, 1, 1), 245.0), (date(2024, 6, 1), 268.0), (date(2024, 10, 1), 248.0), (date(2025, 12, 1), 302.0)],
        "IXUS": [(date(2023, 1, 1), 60.0), (date(2024, 6, 1), 65.0), (date(2024, 10, 1), 59.0), (date(2025, 12, 1), 71.0)],
    }
    result = defaultdict(dict)
    for year, month in month_iter():
        current = date(year, month, 1)
        key = current.isoformat()[:7]
        for ticker, points in anchors.items():
            result[ticker][key] = price_point(points, current, 0.012)
    return result


def generate_portfolio_data() -> tuple[list[dict], list[dict]]:
    prices = monthly_price_series()
    snapshots, holdings = [], []
    brokerage, rollover, greenleaf = {"VTI": 250.0, "VXUS": 470.0, "BND": 210.0}, {"VFIFX": 3000.0}, {"VOO": 4.6667, "IJH": 5.1429, "IXUS": 21.0}
    employed_months = {f"{y:04d}-{m:02d}" for y, m in month_iter() if not ((y == 2023 and m in {8, 9, 10}) or (y == 2024 and m in {6, 7, 8, 9}))}
    for year, month in month_iter():
        current = date(year, month, 1)
        key = current.isoformat()[:7]
        for ticker, allocation in {"VTI": 0.50, "VXUS": 0.25, "BND": 0.15}.items():
            brokerage[ticker] += round((400.0 * allocation) / prices[ticker][key], 6)
        gross = sum(brokerage[t] * prices[t][key] for t in brokerage)
        cash = gross * 0.025
        total = gross + cash
        if key == "2025-12":
            scale = TARGET_END_BALANCES["vanguard_inv_5501"] / total
            brokerage = {ticker: shares * scale for ticker, shares in brokerage.items()}
            gross = sum(brokerage[t] * prices[t][key] for t in brokerage)
            cash = TARGET_END_BALANCES["vanguard_inv_5501"] * 0.025
            total = gross + cash
        snapshots.append({"account_id": "vanguard_inv_5501", "timestamp": f"{current.isoformat()}T00:00:00", "total_account_value": round(total, 2), "cash_balance": round(cash, 2)})
        for ticker in ["VTI", "VXUS", "BND"]:
            holdings.append({"account_id": "vanguard_inv_5501", "date": current.isoformat(), "ticker": ticker, "shares": round(brokerage[ticker], 6), "close_price": prices[ticker][key], "market_value": round(brokerage[ticker] * prices[ticker][key], 2)})
        holdings.append({"account_id": "vanguard_inv_5501", "date": current.isoformat(), "ticker": "CASH", "shares": 1.0, "close_price": round(cash * 0.8, 2), "market_value": round(cash * 0.8, 2)})
        holdings.append({"account_id": "vanguard_inv_5501", "date": current.isoformat(), "ticker": "VMFXX", "shares": 1.0, "close_price": round(cash * 0.2, 2), "market_value": round(cash * 0.2, 2)})
        r_gross = rollover["VFIFX"] * prices["VFIFX"][key]
        r_cash = r_gross * 0.01
        r_total = r_gross + r_cash
        if key == "2025-12":
            scale = TARGET_END_BALANCES["vanguard_ret_5502"] / r_total
            rollover["VFIFX"] *= scale
            r_gross = rollover["VFIFX"] * prices["VFIFX"][key]
            r_cash = TARGET_END_BALANCES["vanguard_ret_5502"] * 0.01
            r_total = r_gross + r_cash
        snapshots.append({"account_id": "vanguard_ret_5502", "timestamp": f"{current.isoformat()}T00:00:00", "total_account_value": round(r_total, 2), "cash_balance": round(r_cash, 2)})
        holdings.append({"account_id": "vanguard_ret_5502", "date": current.isoformat(), "ticker": "VFIFX", "shares": round(rollover["VFIFX"], 6), "close_price": prices["VFIFX"][key], "market_value": round(rollover["VFIFX"] * prices["VFIFX"][key], 2)})
        holdings.append({"account_id": "vanguard_ret_5502", "date": current.isoformat(), "ticker": "CASH", "shares": 1.0, "close_price": round(r_cash * 0.5, 2), "market_value": round(r_cash * 0.5, 2)})
        holdings.append({"account_id": "vanguard_ret_5502", "date": current.isoformat(), "ticker": "STABLE", "shares": 1.0, "close_price": round(r_cash * 0.5, 2), "market_value": round(r_cash * 0.5, 2)})
        if key in employed_months:
            for ticker, allocation in {"VOO": 0.40, "IJH": 0.30, "IXUS": 0.30}.items():
                greenleaf[ticker] += round((100.0 * allocation) / prices[ticker][key], 6)
        g_total = sum(greenleaf[t] * prices[t][key] for t in greenleaf)
        if key == "2025-12":
            scale = TARGET_END_BALANCES["greenleaf_inv_1001"] / g_total
            greenleaf = {ticker: shares * scale for ticker, shares in greenleaf.items()}
            g_total = sum(greenleaf[t] * prices[t][key] for t in greenleaf)
        snapshots.append({"account_id": "greenleaf_inv_1001", "timestamp": f"{current.isoformat()}T00:00:00", "total_account_value": round(g_total, 2), "cash_balance": 0.0})
        for ticker in ["VOO", "IJH", "IXUS"]:
            holdings.append({"account_id": "greenleaf_inv_1001", "date": current.isoformat(), "ticker": ticker, "shares": round(greenleaf[ticker], 6), "close_price": prices[ticker][key], "market_value": round(greenleaf[ticker] * prices[ticker][key], 2)})
        holdings.append({"account_id": "greenleaf_inv_1001", "date": current.isoformat(), "ticker": "CASH", "shares": 0.0, "close_price": 0.0, "market_value": 0.0})
    return snapshots, holdings


def generate_credit_scores() -> list[dict]:
    rows, alex, jordan = [], [758, 759, 760, 760, 761, 762, 762, 763, 764, 765, 766, 766, 767, 768, 768, 769, 769, 770, 770, 771, 772, 772, 773, 774, 774, 775, 775, 776, 776, 777, 777, 778, 778, 779, 779, 776], [715, 718, 720, 719, 716, 714, 712, 703, 697, 690, 693, 698, 704, 709, 715, 717, 714, 702, 690, 681, 674, 670, 673, 678, 684, 690, 696, 701, 706, 710, 714, 717, 719, 720, 720, 720]
    for idx, (year, month) in enumerate(month_iter()):
        rows.append({"owner_id": "alex", "institution_id": "summit", "score": max(755, min(780, alex[idx] + random.randint(-2, 2))), "score_type": "FICO", "source": "TransUnion", "score_date": date(year, month, 15).isoformat()})
        rows.append({"owner_id": "jordan", "institution_id": "coastal", "score": max(670, min(730, jordan[idx] + random.randint(-4, 4))), "score_type": "FICO", "source": "TransUnion", "score_date": date(year, month, 15).isoformat()})
    rows[-2]["score"], rows[-1]["score"] = 776, 720
    return rows


def generate_recurring_transactions() -> list[dict]:
    return [
        {"account_id": "summit_chk_4501", "merchant": "Summit Home Mortgage", "category": "Mortgages", "expected_amount": -1478.0, "frequency": "monthly", "last_date": "2025-12-01", "next_date": "2026-01-01"},
        {"account_id": "summit_chk_4501", "merchant": "Summit Auto Loan", "category": "Loan Payments", "expected_amount": -612.0, "frequency": "monthly", "last_date": "2025-04-15", "next_date": "2025-05-15", "status": "completed"},
        {"account_id": "summit_chk_4501", "merchant": "DUKE ENERGY ONLINE", "category": "Utilities", "expected_amount": -128.0, "frequency": "monthly", "last_date": "2025-12-05", "next_date": "2026-01-05"},
        {"account_id": "summit_chk_4501", "merchant": "SPECTRUM INTERNET", "category": "Telephone Services", "expected_amount": -79.99, "frequency": "monthly", "last_date": "2025-12-12", "next_date": "2026-01-12"},
        {"account_id": "coastal_chk_2210", "merchant": "T-MOBILE AUTOPAY", "category": "Telephone Services", "expected_amount": -85.0, "frequency": "monthly", "last_date": "2025-12-18", "next_date": "2026-01-18"},
        {"account_id": "summit_chk_4501", "merchant": "GEICO AUTO", "category": "Insurance", "expected_amount": -624.0, "frequency": "semi-annual", "last_date": "2025-07-01", "next_date": "2026-01-01"},
        {"account_id": "summit_cc_3341", "merchant": "NETFLIX", "category": "Dues and Subscriptions", "expected_amount": -15.99, "frequency": "monthly", "last_date": "2025-12-08", "next_date": "2026-01-08"},
        {"account_id": "summit_cc_3341", "merchant": "SPOTIFY", "category": "Dues and Subscriptions", "expected_amount": -10.99, "frequency": "monthly", "last_date": "2025-12-15", "next_date": "2026-01-15"},
        {"account_id": "summit_cc_3341", "merchant": "AMAZON PRIME", "category": "Dues and Subscriptions", "expected_amount": -139.0, "frequency": "annual", "last_date": "2025-02-09", "next_date": "2026-02-09"},
        {"account_id": "coastal_chk_2210", "merchant": "PLANET FITNESS", "category": "Dues and Subscriptions", "expected_amount": -25.0, "frequency": "monthly", "last_date": "2025-12-20", "next_date": "2026-01-20"},
        {"account_id": "summit_chk_4501", "merchant": "Summit Visa Payment", "category": "Credit Card Payments", "expected_amount": -900.0, "frequency": "monthly", "last_date": "2025-12-25", "next_date": "2026-01-25"},
        {"account_id": "coastal_chk_2210", "merchant": "Coastal CC Payment", "category": "Credit Card Payments", "expected_amount": -350.0, "frequency": "monthly", "last_date": "2025-12-28", "next_date": "2026-01-28"},
        {"account_id": "summit_chk_4501", "merchant": "Transfer to Summit Savings", "category": "Transfers", "expected_amount": -800.0, "frequency": "monthly", "last_date": "2025-12-03", "next_date": "2026-01-03"},
        {"account_id": "summit_chk_4501", "merchant": "Transfer to Brighton HYSA", "category": "Transfers", "expected_amount": -500.0, "frequency": "monthly", "last_date": "2025-12-04", "next_date": "2026-01-04"},
        {"account_id": "coastal_chk_2210", "merchant": "Transfer to Brighton HYSA", "category": "Transfers", "expected_amount": -250.0, "frequency": "monthly", "last_date": "2025-12-04", "next_date": "2026-01-04"},
        {"account_id": "brighton_sav_3300", "merchant": "Brighton HYSA Interest", "category": "Interest", "expected_amount": 43.5, "frequency": "monthly", "last_date": "2025-12-31", "next_date": "2026-01-31"},
        {"account_id": "summit_chk_4501", "merchant": "Transfer to Vanguard Brokerage", "category": "Transfers", "expected_amount": -400.0, "frequency": "monthly", "last_date": "2025-12-06", "next_date": "2026-01-06"},
        {"account_id": "coastal_chk_2210", "merchant": "Greenleaf Auto-Invest", "category": "Transfers", "expected_amount": -100.0, "frequency": "monthly", "last_date": "2025-12-06", "next_date": "2026-01-06"},
    ]


def interpolate_series(points: list[tuple[date, float]], current: date) -> float:
    return price_point(points, current, 0.0)


def generate_budgets() -> list[dict]:
    rows = []
    for year, month in month_iter():
        inflation = 1.0 if year == 2023 else (1.03 if year == 2024 else 1.0609)
        for category, amount in BUDGET_BASELINES.items():
            rows.append({"category": category, "target_amount": round(amount * inflation, 2), "month": f"{year:04d}-{month:02d}"})
    return rows


def validate(transactions: list[dict], balance_snapshots: list[dict], portfolio_snapshots: list[dict]) -> list[str]:
    issues = []
    account_ids = {row["account_id"] for row in ACCOUNT_ROWS}
    for tx in transactions:
        if tx["account_id"] not in account_ids:
            issues.append(f"orphan transaction {tx['account_id']}")
        if not (START <= date.fromisoformat(tx["date"]) <= END):
            issues.append(f"date out of range {tx['date']}")
    for account in [row["account_id"] for row in ACCOUNT_ROWS if row["type"] != "investment"]:
        computed = balance_as_of(STARTING_BALANCES[account], [tx for tx in transactions if tx["account_id"] == account], END)
        tolerance = 1.0 if account == "payflex_bnpl_0001" else 50.0
        if abs(computed - TARGET_END_BALANCES[account]) > tolerance:
            issues.append(f"balance mismatch {account}: {computed:.2f} vs {TARGET_END_BALANCES[account]:.2f}")
    end_values = {row["account_id"]: row["total_account_value"] for row in portfolio_snapshots if row["timestamp"].startswith("2025-12-01")}
    for account in ("vanguard_inv_5501", "vanguard_ret_5502", "greenleaf_inv_1001"):
        if abs(end_values[account] - TARGET_END_BALANCES[account]) / TARGET_END_BALANCES[account] > 0.05:
            issues.append(f"portfolio mismatch {account}")
    running = STARTING_BALANCES["coastal_cc_8847"]
    peak = 0.0
    monthly = defaultdict(float)
    for tx in transactions:
        if tx["account_id"] == "coastal_cc_8847":
            monthly[tx["date"][:7]] += tx["amount"]
    for key in sorted(monthly):
        running = round(running + monthly[key], 2)
        peak = min(peak, running)
    if not (-6100.0 <= peak <= -5500.0):
        issues.append(f"Jordan CC peak outside range: {peak:.2f}")
    if len(balance_snapshots) < 780:
        issues.append(f"too few balance snapshots: {len(balance_snapshots)}")
    return issues


def write_json(name: str, payload: object) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / name).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def main() -> None:
    transactions = generate_transactions()
    portfolio_snapshots, holdings = generate_portfolio_data()
    balance_snapshots = derive_balance_snapshots(transactions)
    for account in ("vanguard_inv_5501", "vanguard_ret_5502", "greenleaf_inv_1001"):
        lookup = {row["timestamp"][:10]: row["total_account_value"] for row in portfolio_snapshots if row["account_id"] == account}
        for snap_date in semi_monthly_dates():
            balance_snapshots.append({"account_id": account, "date": snap_date.isoformat(), "balance_amount": round(lookup[snap_date.replace(day=1).isoformat()], 2)})
    balance_snapshots = sorted(balance_snapshots, key=lambda row: (row["account_id"], row["date"]))
    files = {
        "Institutions.json": ACCOUNT_ROWS,
        "transactions_dense.json": transactions,
        "transactions.json": transactions[:500],
        "balance_snapshots.json": balance_snapshots,
        "portfolio_snapshots.json": portfolio_snapshots,
        "Investment_holdings.json": holdings,
        "recurring_transactions.json": generate_recurring_transactions(),
        "loan_details.json": [
            {"account_id": "summit_mtg_9102", "interest_rate": 4.25, "minimum_payment": 1478.0, "origination_date": "2020-09-15", "due_date_day": 1, "purchase_price": 285000, "term_months": 360},
            {"account_id": "summit_auto_6655", "interest_rate": 3.9, "minimum_payment": 612.0, "origination_date": "2021-06-01", "due_date_day": 15, "purchase_price": 32500, "term_months": 60},
            {"account_id": "payflex_bnpl_0001", "interest_rate": 0.0, "minimum_payment": 183.33, "origination_date": "2024-11-01", "due_date_day": 1, "purchase_price": 1100, "term_months": 6},
        ],
        "budgets.json": generate_budgets(),
        "savings_goals.json": [
            {"name": "Emergency Fund", "target_amount": 25000.0, "current_amount": 22100.0, "target_date": "2026-06-30", "linked_account_id": "summit_sav_7823"},
            {"name": "Vacation Fund", "target_amount": 5000.0, "current_amount": 3200.0, "target_date": "2026-07-01", "linked_account_id": "brighton_sav_3300"},
            {"name": "Jordan Student Loan Payoff", "target_amount": 6000.0, "current_amount": 6000.0, "target_date": "2025-10-31", "linked_account_id": None},
        ],
        "credit_scores.json": generate_credit_scores(),
        "vehicle_assets.json": [{"id": "rav4_2021", "make": "Toyota", "model": "RAV4", "year": 2021, "purchase_date": "2021-06-15", "purchase_price": 32500.0}],
        "vehicle_valuations.json": [{"vehicle_id": "rav4_2021", "valuation_date": current.isoformat(), "estimated_value": round(interpolate_series([(date(2023, 1, 1), 26500.0), (date(2024, 1, 1), 24000.0), (date(2025, 1, 1), 21800.0), (date(2025, 12, 31), 20200.0)], current), 2), "source": "KBB"} for current in quarterly_dates()],
        "real_estate.json": [{"name": "Primary Residence", "estimated_value": round(interpolate_series([(date(2023, 1, 1), 295000.0), (date(2024, 1, 1), 305000.0), (date(2025, 1, 1), 312000.0), (date(2025, 12, 31), 318000.0)], current), 2), "linked_loan_id": "summit_mtg_9102", "source": "estimate", "as_of": current.isoformat()} for current in quarterly_dates()],
        "owners.json": OWNERS,
        "app_settings.json": {"multi_user_enabled": True, "refresh_intervals": {}, "notification_preferences": {"budget_alerts": True, "staleness_alerts": True, "document_nudges": True, "bill_reminders": True}, "expected_monthly_docs": [], "expected_annual_docs": [], "archival_months": 36},
    }
    issues = validate(transactions, balance_snapshots, portfolio_snapshots)
    print("Validation:")
    if issues:
        for issue in issues:
            print(f"  FAIL: {issue}")
        raise SystemExit(1)
    for name, payload in files.items():
        write_json(name, payload)
    running = STARTING_BALANCES["coastal_cc_8847"]
    peak = 0.0
    monthly = defaultdict(float)
    for tx in transactions:
        if tx["account_id"] == "coastal_cc_8847":
            monthly[tx["date"][:7]] += tx["amount"]
    for key in sorted(monthly):
        running = round(running + monthly[key], 2)
        peak = min(peak, running)
    print(f"Seed: {SEED}")
    print(f"Total transactions: {len(transactions)}")
    print(f"Accounts: {len(ACCOUNT_ROWS)}")
    print(f"Owners: {len(OWNERS)}")
    print(f"Balance snapshots: {len(balance_snapshots)}")
    print(f"Portfolio snapshots: {len(portfolio_snapshots)}")
    print(f"Investment holdings: {len(holdings)}")
    print(f"Alex Dec 2025 checking: {balance_as_of(STARTING_BALANCES['summit_chk_4501'], [tx for tx in transactions if tx['account_id'] == 'summit_chk_4501'], END):.2f}")
    print(f"Jordan Dec 2025 checking: {balance_as_of(STARTING_BALANCES['coastal_chk_2210'], [tx for tx in transactions if tx['account_id'] == 'coastal_chk_2210'], END):.2f}")
    print(f"Jordan CC peak: {abs(peak):.2f}")
    print(f"Mortgage Dec 2025: {balance_as_of(STARTING_BALANCES['summit_mtg_9102'], [tx for tx in transactions if tx['account_id'] == 'summit_mtg_9102'], END):.2f}")
    print(f"Vanguard Brokerage Dec 2025: {next(row['total_account_value'] for row in portfolio_snapshots if row['account_id'] == 'vanguard_inv_5501' and row['timestamp'].startswith('2025-12-01')):.2f}")


if __name__ == "__main__":
    main()
