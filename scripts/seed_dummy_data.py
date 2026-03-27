"""
scripts/seed_dummy_data.py — Load all dummy_data JSON files into the SQLite DB.

This script remaps the legacy account IDs used in the dummy JSON files to the
real DB account IDs (which follow the {institution}_{last4} format from
accounts.yaml), then bulk-inserts data into each table.

Safe to re-run: clears seeded data first, uses transactions within each batch.

Usage:
    python scripts/seed_dummy_data.py
"""

import json
import logging
import sys
import uuid
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dal.database import init_db, get_db, seed_institutions

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

DUMMY_DIR = Path(_PROJECT_ROOT) / "dummy_data"

# ── Account ID Mapping ──────────────────────────────────────────────────────
# Maps dummy JSON account IDs → real DB account IDs (from accounts.yaml)
ACCOUNT_MAP = {
    "chase_chk_001":    "chase_8115",
    "chase_cc_001":     "chase_8973",
    "nfcu_sav_001":     "nfcu_1167",
    "nfcu_auto_001":    "nfcu_3533",
    "amex_cc_001":      "amex_0001",
    "rocket_mtg_001":   "rocket_0001",
    "fidelity_inv_001": "fidelity_0827",
    "acorns_inv_001":   "acorns_0000",
}

# Institution inference from account ID
def _inst_from_account(acct_id: str) -> str:
    return acct_id.split("_")[0]


def remap(acct_id: str) -> str:
    """Remap a dummy account ID to the real DB ID."""
    mapped = ACCOUNT_MAP.get(acct_id)
    if mapped is None:
        log.warning("  ⚠  Unknown account_id '%s', keeping as-is", acct_id)
        return acct_id
    return mapped


def load_json(filename: str) -> list:
    path = DUMMY_DIR / filename
    if not path.exists():
        log.warning("  ⚠  %s not found, skipping", filename)
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Seed Functions ───────────────────────────────────────────────────────────

def seed_transactions(conn):
    """Load transactions.json and transactions_dense.json."""
    log.info("📋 Seeding transactions...")

    # Clear existing seeded transactions (ones with dummy_ prefix)
    conn.execute("DELETE FROM transactions WHERE id LIKE 'dummy_%'")

    count = 0
    for filename in ("transactions.json", "transactions_dense.json"):
        rows = load_json(filename)
        for row in rows:
            acct_id = remap(row["account_id"])
            inst_id = _inst_from_account(acct_id)
            amount = row["amount"]
            signed_amount = amount
            direction = "inflow" if amount >= 0 else "outflow"
            posting_date = row["date"]
            merchant = row.get("merchant", "")
            category = row.get("category", "Uncategorized")

            txn_id = f"dummy_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """INSERT OR IGNORE INTO transactions
                   (id, account_id, institution_id, posting_date, amount,
                    signed_amount, direction, description, merchant, category, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted')""",
                (txn_id, acct_id, inst_id, posting_date, abs(amount),
                 signed_amount, direction, merchant, merchant, category),
            )
            count += 1
        log.info("  ✓ %s: %d rows", filename, len(rows))

    conn.commit()
    log.info("  Total transactions seeded: %d", count)


def seed_balance_snapshots(conn):
    """Load balance_snapshots.json."""
    log.info("📊 Seeding balance snapshots...")

    # Clear dummy-seeded snapshots
    conn.execute("DELETE FROM balance_snapshots WHERE refresh_run_id = 'dummy_seed'")

    rows = load_json("balance_snapshots.json")
    for row in rows:
        acct_id = remap(row["account_id"])
        conn.execute(
            """INSERT INTO balance_snapshots
               (account_id, balance, as_of, refresh_run_id)
               VALUES (?, ?, ?, 'dummy_seed')""",
            (acct_id, row["balance_amount"], row["date"]),
        )

    conn.commit()
    log.info("  ✓ %d balance snapshots seeded", len(rows))


def seed_budgets(conn):
    """Load budgets.json into the budgets table."""
    log.info("💰 Seeding budgets...")

    conn.execute("DELETE FROM budgets WHERE created_at LIKE 'dummy%' OR 1=1")
    # Just clear all budgets since we're seeding from scratch
    conn.execute("DELETE FROM budgets")

    rows = load_json("budgets.json")
    for row in rows:
        conn.execute(
            """INSERT INTO budgets
               (category, month, target_amount)
               VALUES (?, ?, ?)""",
            (row["category"], row["month"], row["target_amount"]),
        )

    conn.commit()
    log.info("  ✓ %d budget targets seeded", len(rows))


def seed_recurring_transactions(conn):
    """Load recurring_transactions.json."""
    log.info("🔄 Seeding recurring transactions...")

    conn.execute("DELETE FROM recurring_transactions WHERE id LIKE 'dummy_%'")

    rows = load_json("recurring_transactions.json")
    for row in rows:
        acct_id = remap(row["account_id"])
        rec_id = f"dummy_{uuid.uuid4().hex[:12]}"

        # Map frequency to avg_interval days
        freq_map = {
            "monthly": 30,
            "semi-annual": 182,
            "weekly": 7,
            "quarterly": 91,
            "annual": 365,
        }
        avg_interval = freq_map.get(row.get("frequency", "monthly"), 30)

        conn.execute(
            """INSERT INTO recurring_transactions
               (id, account_id, merchant, category, frequency, avg_interval,
                expected_amount, amount_stable, last_amount, last_date,
                next_expected, occurrence_count, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 6, 'active')""",
            (rec_id, acct_id, row["merchant"], row.get("category", ""),
             row.get("frequency", "monthly"), avg_interval,
             row.get("expected_amount", 0),
             row.get("expected_amount", 0),
             row.get("last_date", ""),
             row.get("next_date", "")),
        )

    conn.commit()
    log.info("  ✓ %d recurring transactions seeded", len(rows))


def seed_savings_goals(conn):
    """Load savings_goals.json."""
    log.info("🎯 Seeding savings goals...")

    conn.execute("DELETE FROM savings_goals")

    rows = load_json("savings_goals.json")
    for row in rows:
        linked = remap(row["linked_account_id"]) if row.get("linked_account_id") else None
        conn.execute(
            """INSERT INTO savings_goals
               (name, target_amount, current_amount, deadline, linked_account_id, status)
               VALUES (?, ?, ?, ?, ?, 'active')""",
            (row["name"], row["target_amount"], row.get("current_amount", 0),
             row.get("target_date"), linked),
        )

    conn.commit()
    log.info("  ✓ %d savings goals seeded", len(rows))


def seed_loan_details(conn):
    """Load loan_details.json into the KV-style loan_details table."""
    log.info("🏦 Seeding loan details...")

    conn.execute("DELETE FROM loan_details WHERE refresh_run_id = 'dummy_seed'")

    rows = load_json("loan_details.json")
    count = 0
    for row in rows:
        acct_id = remap(row["account_id"])
        as_of = row.get("origination_date", "2026-03-01")

        # Insert each field as a separate KV row
        fields = {
            "interest_rate": row.get("interest_rate"),
            "minimum_payment": row.get("minimum_payment"),
            "origination_date": row.get("origination_date"),
            "purchase_price": row.get("purchase_price"),
            "term_months": row.get("term_months"),
        }
        for field_name, field_value in fields.items():
            if field_value is not None:
                conn.execute(
                    """INSERT INTO loan_details
                       (account_id, field_name, field_value, as_of, refresh_run_id)
                       VALUES (?, ?, ?, ?, 'dummy_seed')""",
                    (acct_id, field_name, str(field_value), as_of),
                )
                count += 1

    conn.commit()
    log.info("  ✓ %d loan detail KV rows seeded", count)


def seed_investment_holdings(conn):
    """Load Investment_holdings.json."""
    log.info("📈 Seeding investment holdings...")

    conn.execute("DELETE FROM investment_holdings WHERE created_at LIKE 'dummy%' OR 1=1")
    conn.execute("DELETE FROM investment_holdings")

    rows = load_json("Investment_holdings.json")
    for row in rows:
        acct_id = remap(row["account_id"])
        conn.execute(
            """INSERT INTO investment_holdings
               (account_id, date, ticker, shares, close_price, market_value)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (acct_id, row["date"], row["ticker"],
             row["shares"], row["close_price"], row["market_value"]),
        )

    conn.commit()
    log.info("  ✓ %d investment holding rows seeded", len(rows))


def seed_portfolio_snapshots(conn):
    """Load portfolio_snapshots.json."""
    log.info("📉 Seeding portfolio snapshots...")

    conn.execute("DELETE FROM portfolio_snapshots")

    rows = load_json("portfolio_snapshots.json")
    for row in rows:
        acct_id = remap(row["account_id"])
        conn.execute(
            """INSERT INTO portfolio_snapshots
               (account_id, timestamp, total_account_value, cash_balance)
               VALUES (?, ?, ?, ?)""",
            (acct_id, row["timestamp"], row["total_account_value"],
             row.get("cash_balance", 0)),
        )

    conn.commit()
    log.info("  ✓ %d portfolio snapshots seeded", len(rows))


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("  Sentry Finance — Dummy Data Seeder")
    log.info("=" * 60)
    log.info("")

    # Initialize DB and seed institutions (picks up new amex/rocket)
    init_db()
    seed_institutions()
    log.info("")

    with get_db() as conn:
        seed_transactions(conn)
        log.info("")
        seed_balance_snapshots(conn)
        log.info("")
        seed_budgets(conn)
        log.info("")
        seed_recurring_transactions(conn)
        log.info("")
        seed_savings_goals(conn)
        log.info("")
        seed_loan_details(conn)
        log.info("")
        seed_investment_holdings(conn)
        log.info("")
        seed_portfolio_snapshots(conn)

    log.info("")
    log.info("=" * 60)
    log.info("  ✅ All dummy data loaded successfully!")
    log.info("=" * 60)

    # Print summary
    log.info("")
    with get_db() as conn:
        for table in [
            "transactions", "balance_snapshots", "budgets",
            "recurring_transactions", "savings_goals", "loan_details",
            "investment_holdings", "portfolio_snapshots",
        ]:
            count = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            log.info("  %-25s %d rows", table, count)


if __name__ == "__main__":
    main()
