"""Seed the dummy SQLite database from dummy_data JSON fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "dummy_data"
DB_PATH = PROJECT_ROOT / "data" / "dummy.db"
os.environ["SENTRY_DB_PATH"] = str(DB_PATH)

from dal.database import get_db, init_db  # noqa: E402
from dal.merchant_normalizer import backfill_merchant_column, rebuild_merchant_snapshots  # noqa: E402


def _load(filename: str):
    with (DATA_DIR / filename).open(encoding="utf-8") as handle:
        return json.load(handle)


def _tx_hash(tx: dict) -> str:
    raw = f"{tx['account_id']}|{tx['date']}|{tx['amount']}|{tx['merchant']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _last4(account_id: str) -> str:
    return account_id.rsplit("_", 1)[-1][-4:].rjust(4, "0")


def seed_owners(conn) -> None:
    rows = _load("owners.json")
    conn.executemany(
        "INSERT OR IGNORE INTO owners (id, display_name) VALUES (?, ?)",
        [(row["id"], row["display_name"]) for row in rows],
    )
    conn.commit()
    print(f"  seeded owners: {len(rows)}")


def seed_accounts(conn) -> None:
    labels = {
        "summit": "Summit Credit Union",
        "coastal": "Coastal Bank",
        "vanguard_prime": "Vanguard Prime",
        "greenleaf": "Greenleaf Investing",
        "brighton": "Brighton Savings",
        "payflex": "PayFlex",
    }
    rows = _load("Institutions.json")
    for row in rows:
        conn.execute("INSERT OR IGNORE INTO institutions (id, display_name) VALUES (?, ?)", (row["institution_id"], labels[row["institution_id"]]))
        conn.execute(
            """
            INSERT OR REPLACE INTO accounts
                (id, institution_id, name, last4, type, owner_id, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["account_id"],
                row["institution_id"],
                row["name"],
                _last4(row["account_id"]),
                row["type"],
                row.get("owner_id"),
                0 if row.get("is_active") is False else 1,
            ),
        )
    conn.commit()
    print(f"  seeded accounts: {len(rows)}")


def seed_current_balances(conn) -> None:
    rows = _load("Institutions.json")
    for row in rows:
        conn.execute("INSERT INTO balance_snapshots (account_id, balance, as_of, refresh_run_id) VALUES (?, ?, ?, 'dummy_seed_current')", (row["account_id"], row["balance"], "2025-12-31"))
    conn.commit()
    print(f"  seeded current balances: {len(rows)}")


def seed_balance_snapshots(conn) -> None:
    rows = _load("balance_snapshots.json")
    for row in rows:
        conn.execute("INSERT INTO balance_snapshots (account_id, balance, as_of, refresh_run_id) VALUES (?, ?, ?, 'dummy_seed_history')", (row["account_id"], row["balance_amount"], row["date"]))
    conn.commit()
    print(f"  seeded balance snapshots: {len(rows)}")


def seed_transactions(conn) -> None:
    rows = _load("transactions_dense.json")
    institutions = {row["account_id"]: row["institution_id"] for row in _load("Institutions.json")}
    for row in rows:
        amount = row["amount"]
        conn.execute(
            """
            INSERT OR REPLACE INTO transactions
                (id, institution_id, account_id, posting_date, amount, signed_amount, direction, description, merchant, category, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted')
            """,
            (
                _tx_hash(row),
                institutions[row["account_id"]],
                row["account_id"],
                row["date"],
                abs(amount),
                amount,
                "inflow" if amount > 0 else "outflow",
                row["merchant"],
                row["merchant"],
                row["category"],
            ),
        )
    conn.commit()
    print(f"  seeded transactions: {len(rows)}")


def seed_investment_holdings(conn) -> None:
    rows = _load("Investment_holdings.json")
    for row in rows:
        conn.execute(
            """
            INSERT INTO investment_holdings
                (account_id, date, ticker, shares, close_price, market_value)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (row["account_id"], row["date"], row["ticker"], row["shares"], row["close_price"], row["market_value"]),
        )
    conn.commit()
    print(f"  seeded investment holdings: {len(rows)}")


def seed_portfolio_snapshots(conn) -> None:
    rows = _load("portfolio_snapshots.json")
    for row in rows:
        conn.execute(
            "INSERT INTO portfolio_snapshots (account_id, timestamp, total_account_value, cash_balance) VALUES (?, ?, ?, ?)",
            (row["account_id"], row["timestamp"], row["total_account_value"], row["cash_balance"]),
        )
    conn.commit()
    print(f"  seeded portfolio snapshots: {len(rows)}")


def seed_loan_details(conn) -> None:
    rows = _load("loan_details.json")
    for row in rows:
        for field in ("interest_rate", "minimum_payment", "origination_date", "due_date_day", "purchase_price", "term_months"):
            conn.execute(
                "INSERT INTO loan_details (account_id, field_name, field_value, as_of, refresh_run_id) VALUES (?, ?, ?, ?, 'dummy_seed')",
                (row["account_id"], field, str(row[field]), row["origination_date"]),
            )
    conn.commit()
    print(f"  seeded loan detail records: {len(rows)}")


def seed_budgets(conn) -> None:
    rows = _load("budgets.json")
    for row in rows:
        conn.execute("INSERT INTO budgets (category, target_amount, month, owner_id) VALUES (?, ?, ?, NULL)", (row["category"], row["target_amount"], row["month"]))
    conn.commit()
    print(f"  seeded budgets: {len(rows)}")


def seed_recurring_transactions(conn) -> None:
    rows = _load("recurring_transactions.json")
    freq_days = {"monthly": 30.0, "semi-annual": 182.0, "annual": 365.0}
    for idx, row in enumerate(rows):
        conn.execute(
            """
            INSERT INTO recurring_transactions
                (id, account_id, merchant, category, frequency, avg_interval, expected_amount, amount_stable, last_amount, last_date, next_expected, occurrence_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 12, ?)
            """,
            (
                f"dummy_rec_{idx:03d}",
                row["account_id"],
                row["merchant"],
                row["category"],
                row["frequency"],
                freq_days.get(row["frequency"], 30.0),
                row["expected_amount"],
                row["expected_amount"],
                row["last_date"],
                row["next_date"],
                row.get("status", "active"),
            ),
        )
    conn.commit()
    print(f"  seeded recurring transactions: {len(rows)}")


def seed_savings_goals(conn) -> None:
    rows = _load("savings_goals.json")
    for row in rows:
        conn.execute(
            "INSERT INTO savings_goals (name, target_amount, current_amount, deadline, linked_account_id, owner_id, status) VALUES (?, ?, ?, ?, ?, ?, 'active')",
            (row["name"], row["target_amount"], row["current_amount"], row["target_date"], row.get("linked_account_id"), None if row["linked_account_id"] else "jordan"),
        )
    conn.commit()
    print(f"  seeded savings goals: {len(rows)}")


def seed_credit_scores(conn) -> None:
    rows = _load("credit_scores.json")
    for row in rows:
        conn.execute(
            "INSERT INTO credit_scores (score, score_type, source, institution_id, score_date, as_of) VALUES (?, ?, ?, ?, ?, ?)",
            (row["score"], row["score_type"], row["source"], row["institution_id"], row["score_date"], row["score_date"]),
        )
    conn.commit()
    print(f"  seeded credit scores: {len(rows)}")


def seed_vehicle_assets(conn) -> None:
    vehicles = _load("vehicle_assets.json")
    valuations = _load("vehicle_valuations.json")
    for row in vehicles:
        conn.execute(
            "INSERT OR REPLACE INTO vehicle_assets "
            "(id, make, model, year, purchase_date, purchase_price, linked_loan_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"], row["make"], row["model"], row["year"],
                row["purchase_date"], row["purchase_price"],
                row.get("linked_loan_id"),
            ),
        )
    for row in valuations:
        conn.execute(
            "INSERT INTO vehicle_valuations (vehicle_id, valuation_date, estimated_value, source, as_of) VALUES (?, ?, ?, ?, ?)",
            (row["vehicle_id"], row["valuation_date"], row["estimated_value"], row["source"], row["valuation_date"]),
        )
    conn.commit()
    print(f"  seeded vehicles: {len(vehicles)} assets, {len(valuations)} valuations")


def seed_real_estate(conn) -> None:
    rows = _load("real_estate.json")
    for row in rows:
        conn.execute(
            "INSERT INTO real_estate (name, estimated_value, linked_loan_id, source, as_of) VALUES (?, ?, ?, ?, ?)",
            (row["name"], row["estimated_value"], row.get("linked_loan_id"), row.get("source", "estimate"), row["as_of"]),
        )
    conn.commit()
    print(f"  seeded real estate rows: {len(rows)}")


def seed_app_settings(conn) -> None:
    rows = _load("app_settings.json")
    for key, value in rows.items():
        conn.execute("INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?, ?, datetime('now'))", (key, json.dumps(value)))
    conn.commit()
    print(f"  seeded app settings: {len(rows)}")


def seed_dummy_data() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    print(f"Creating fresh dummy database at {DB_PATH}")
    init_db()
    with get_db() as conn:
        seed_owners(conn)
        seed_accounts(conn)
        seed_current_balances(conn)
        seed_balance_snapshots(conn)
        seed_transactions(conn)
        seed_investment_holdings(conn)
        seed_portfolio_snapshots(conn)
        seed_loan_details(conn)
        seed_budgets(conn)
        seed_recurring_transactions(conn)
        seed_savings_goals(conn)
        seed_credit_scores(conn)
        seed_vehicle_assets(conn)
        seed_real_estate(conn)
        seed_app_settings(conn)
        print("  normalizing merchants...")
        print(f"  merchant names normalized: {backfill_merchant_column(conn)}")
        print(f"  merchant snapshots rebuilt: {rebuild_merchant_snapshots(conn)}")
    print(f"Dummy database ready: {DB_PATH}")


if __name__ == "__main__":
    seed_dummy_data()
