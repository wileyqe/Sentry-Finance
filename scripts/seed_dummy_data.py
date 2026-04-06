"""
scripts/seed_dummy_data.py — Load all dummy_data JSON files into the SQLite DB.

This script seeds fictitious institutions and accounts from Institutions.json,
then bulk-inserts data from all dummy_data/*.json files into the dev database.

Safe to re-run: clears seeded data first, uses transactions within each batch.

Usage:
    $env:SENTRY_DB_PATH = "data\sentry-dev.db"; python scripts/seed_dummy_data.py
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

from dal.database import init_db, get_db

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

DUMMY_DIR = Path(_PROJECT_ROOT) / "dummy_data"

# Build a global account_id → institution_id map from Institutions.json
def _build_acct_inst_map() -> dict:
    path = DUMMY_DIR / "Institutions.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {row["account_id"]: row["institution_id"] for row in data}

ACCT_INST_MAP = _build_acct_inst_map()


def load_json(filename: str):
    """Load a JSON file from the dummy_data directory."""
    path = DUMMY_DIR / filename
    if not path.exists():
        log.warning("  ⚠  %s not found, skipping", filename)
        return [] if filename.endswith(".json") else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Seed Functions ───────────────────────────────────────────────────────────

def seed_owners(conn):
    """Load owners from owners.json into the owners table."""
    log.info("👤 Seeding owners...")
    rows = load_json("owners.json")
    for row in rows:
        conn.execute(
            "INSERT OR IGNORE INTO owners (id, display_name) VALUES (?, ?)",
            (row["id"], row["display_name"]),
        )
    conn.commit()
    log.info("  ✓ %d owners seeded", len(rows))


def seed_institutions_and_accounts(conn):
    """Load institutions and accounts from Institutions.json."""
    log.info("🏦 Seeding institutions & accounts...")

    rows = load_json("Institutions.json")

    # Collect unique institution IDs
    inst_ids = set()
    for row in rows:
        inst_id = row["institution_id"]
        if inst_id not in inst_ids:
            conn.execute(
                """INSERT OR IGNORE INTO institutions
                   (id, display_name, refresh_interval_hours, mfa_expected, extraction_method)
                   VALUES (?, ?, 24, 'none', 'dummy')""",
                (inst_id, inst_id.replace("_", " ").title()),
            )
            # Also seed refresh status
            conn.execute(
                "INSERT OR IGNORE INTO institution_refresh_status (institution_id) VALUES (?)",
                (inst_id,),
            )
            inst_ids.add(inst_id)

    # Seed accounts
    for row in rows:
        is_active = row.get("is_active", True)
        closed_at = row.get("closed_at")
        conn.execute(
            """INSERT OR IGNORE INTO accounts
               (id, institution_id, name, last4, type, owner_id, is_active, closed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["account_id"],
                row["institution_id"],
                row["name"],
                row["account_id"].split("_")[-1],  # last4 from account_id
                row["type"],
                row.get("owner_id"),
                1 if is_active else 0,
                closed_at,
            ),
        )

    conn.commit()
    log.info("  ✓ %d institutions, %d accounts seeded", len(inst_ids), len(rows))


def seed_transactions(conn):
    """Load transactions through the real upsert pipeline.

    Routes all dummy transactions through `upsert_transactions()` — the
    same code path used by real connectors.  This ensures categorization,
    deduplication, and identity hashing all behave identically.
    """
    from dal.transactions import upsert_transactions

    log.info("📋 Seeding transactions...")

    # Clean both dummy-prefixed rows AND legacy non-prefixed rows for
    # accounts that belong to the dummy dataset.  This ensures re-runs
    # don't create duplicates even if an earlier script version omitted
    # the dummy_ prefix on IDs.
    conn.execute("DELETE FROM transactions WHERE id LIKE 'dummy_%'")
    dummy_accounts = list(ACCT_INST_MAP.keys())
    if dummy_accounts:
        placeholders = ",".join("?" * len(dummy_accounts))
        conn.execute(
            f"DELETE FROM transactions WHERE account_id IN ({placeholders})",
            dummy_accounts,
        )
    conn.commit()

    # transactions_dense.json is a superset of transactions.json — only
    # load the dense file when it exists to avoid duplicate rows.
    dense_path = DUMMY_DIR / "transactions_dense.json"
    files = ["transactions_dense.json"] if dense_path.exists() else ["transactions.json"]

    total = 0
    for filename in files:
        rows = load_json(filename)

        # Build transaction dicts in the same format as result_writer output
        txn_dicts = []
        for row in rows:
            acct_id = row["account_id"]
            inst_id = ACCT_INST_MAP.get(acct_id, acct_id.split("_")[0])
            raw_amount = row["amount"]
            amount = abs(raw_amount)
            signed_amount = raw_amount
            # Use the same direction enum as the real pipeline (Credit/Debit)
            direction = "Credit" if raw_amount >= 0 else "Debit"
            posting_date = row["date"]
            merchant = row.get("merchant", "")
            category = row.get("category", "Uncategorized")

            txn_dicts.append({
                "account_id": acct_id,
                "institution_id": inst_id,
                "posting_date": posting_date,
                "transaction_date": posting_date,
                "amount": amount,
                "signed_amount": signed_amount,
                "direction": direction,
                "description": merchant,      # merchant as description (matches real CSV flow)
                "category": category,
                "status": "posted",
                "raw_description": merchant,
            })

        # Feed through the real upsert pipeline — gets deterministic IDs,
        # deduplication, categorization, and attribution for free.
        stats = upsert_transactions(conn, txn_dicts)
        conn.commit()

        log.info(
            "  ✓ %s: %d rows (inserted=%d, updated=%d, unchanged=%d)",
            filename, len(rows),
            stats["inserted"], stats["updated"], stats["unchanged"],
        )
        total += stats["inserted"] + stats["updated"]

    log.info("  Total transactions seeded: %d", total)


def seed_balance_snapshots(conn):
    """Load balance_snapshots.json."""
    log.info("📊 Seeding balance snapshots...")

    conn.execute("DELETE FROM balance_snapshots WHERE refresh_run_id = 'dummy_seed'")

    rows = load_json("balance_snapshots.json")
    for row in rows:
        conn.execute(
            """INSERT INTO balance_snapshots
               (account_id, balance, as_of, refresh_run_id)
               VALUES (?, ?, ?, 'dummy_seed')""",
            (row["account_id"], row["balance_amount"], row["date"]),
        )

    conn.commit()
    log.info("  ✓ %d balance snapshots seeded", len(rows))


def seed_budgets(conn):
    """Load budgets.json into the budgets table."""
    log.info("💰 Seeding budgets...")

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
        acct_id = row["account_id"]
        rec_id = f"dummy_{uuid.uuid4().hex[:12]}"

        freq_map = {
            "monthly": 30, "semi-annual": 182, "weekly": 7,
            "quarterly": 91, "annual": 365,
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
        linked = row.get("linked_account_id")
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
        acct_id = row["account_id"]
        as_of = row.get("origination_date", "2026-03-01")

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

    conn.execute("DELETE FROM investment_holdings")

    rows = load_json("Investment_holdings.json")
    for row in rows:
        conn.execute(
            """INSERT INTO investment_holdings
               (account_id, date, ticker, shares, close_price, market_value)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (row["account_id"], row["date"], row["ticker"],
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
        conn.execute(
            """INSERT INTO portfolio_snapshots
               (account_id, timestamp, total_account_value, cash_balance)
               VALUES (?, ?, ?, ?)""",
            (row["account_id"], row["timestamp"], row["total_account_value"],
             row.get("cash_balance", 0)),
        )

    conn.commit()
    log.info("  ✓ %d portfolio snapshots seeded", len(rows))


def seed_credit_scores(conn):
    """Load credit_scores.json."""
    log.info("📊 Seeding credit scores...")

    conn.execute("DELETE FROM credit_scores")

    rows = load_json("credit_scores.json")
    for row in rows:
        conn.execute(
            """INSERT INTO credit_scores
               (institution_id, score, score_type, source, score_date)
               VALUES (?, ?, ?, ?, ?)""",
            (row["institution_id"], row["score"],
             row.get("score_type", "FICO"), row.get("source", "TransUnion"),
             row["score_date"]),
        )

    conn.commit()
    log.info("  ✓ %d credit scores seeded", len(rows))


def seed_real_estate(conn):
    """Load real_estate.json into the flat real_estate table."""
    log.info("🏠 Seeding real estate valuations...")

    conn.execute("DELETE FROM real_estate")

    rows = load_json("real_estate.json")
    for row in rows:
        conn.execute(
            """INSERT INTO real_estate
               (name, estimated_value, linked_loan_id, source, as_of)
               VALUES (?, ?, ?, ?, ?)""",
            (row["name"], row["estimated_value"], row.get("linked_loan_id"),
             row.get("source", "estimate"), row["as_of"]),
        )

    conn.commit()
    log.info("  ✓ %d real estate valuation rows seeded", len(rows))


def seed_vehicle_assets(conn):
    """Load vehicle_assets.json and vehicle_valuations.json."""
    log.info("🚗 Seeding vehicle assets...")

    conn.execute("DELETE FROM vehicle_valuations")
    conn.execute("DELETE FROM vehicle_assets")

    assets = load_json("vehicle_assets.json")
    for row in assets:
        conn.execute(
            """INSERT OR IGNORE INTO vehicle_assets
               (id, make, model, year, purchase_date, purchase_price)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (row["id"], row["make"], row["model"], row["year"],
             row["purchase_date"], row["purchase_price"]),
        )

    valuations = load_json("vehicle_valuations.json")
    for row in valuations:
        conn.execute(
            """INSERT INTO vehicle_valuations
               (vehicle_id, valuation_date, estimated_value, source)
               VALUES (?, ?, ?, ?)""",
            (row["vehicle_id"], row["valuation_date"],
             row["estimated_value"], row.get("source", "KBB")),
        )

    conn.commit()
    log.info("  ✓ %d vehicles, %d valuations seeded", len(assets), len(valuations))


def seed_payroll_snapshots(conn):
    """
    Seed synthetic myPay RAS rows for the most recent 36 months.

    The dummy seeder does NOT ingest real myPay PDFs (the RAS parser path is
    only exercised by `tests/test_t04_mypay.py`).  Without these synthetic
    rows the new Phase 9 pre-tax / effective-tax UI sections in the Monthly
    Review and Yearly Wrap-Up would have nothing to display.

    Source is tagged 'dummy_seeder' rather than 'mypay_ras' so the rows are
    distinguishable from real ingest if the user later drops a real RAS.
    """
    from datetime import date

    log.info("💰 Seeding synthetic payroll snapshots (myPay RAS substitute)...")

    today = date.today()
    inserted = 0

    # Walk back 36 months from the current month
    for i in range(36):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        pay_period = f"{y:04d}-{m:02d}"

        # Constant numbers — realistic O-5 retiree pension shape (rounded).
        gross_pay = 5200.00
        federal_tax = 520.00
        state_tax = 130.00
        sbp_premium = 270.00
        health_insurance = 0.00       # TRICARE for Life
        dental_vision = 45.00
        other_deductions = 0.00
        net_pay = (
            gross_pay
            - federal_tax
            - state_tax
            - sbp_premium
            - health_insurance
            - dental_vision
            - other_deductions
        )

        conn.execute(
            """
            INSERT OR REPLACE INTO payroll_snapshots
            (pay_period, source, gross_pay, federal_tax, state_tax,
             sbp_premium, health_insurance, dental_vision,
             other_deductions, net_pay, raw_json)
            VALUES (?, 'dummy_seeder', ?, ?, ?, ?, ?, ?, ?, ?, '{}')
            """,
            (
                pay_period, gross_pay, federal_tax, state_tax,
                sbp_premium, health_insurance, dental_vision,
                other_deductions, net_pay,
            ),
        )
        inserted += 1

    conn.commit()
    log.info("  ✓ %d payroll snapshots seeded", inserted)


def seed_app_settings(conn):
    """Load app_settings.json."""
    log.info("⚙️  Seeding app settings...")

    settings = load_json("app_settings.json")
    if not settings:
        return

    for key, value in settings.items():
        str_val = json.dumps(value)
        conn.execute(
            """INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)""",
            (key, str_val),
        )

    conn.commit()
    log.info("  ✓ %d app settings seeded", len(settings))


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("  Sentry Finance — Dummy Data Seeder")
    log.info("=" * 60)
    log.info("")

    # Initialize DB (runs migrations)
    init_db()

    with get_db() as conn:
        # Seed owners first (FK target)
        seed_owners(conn)
        log.info("")

        # Seed institutions & accounts from Institutions.json
        seed_institutions_and_accounts(conn)
        log.info("")

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
        seed_credit_scores(conn)
        log.info("")
        seed_real_estate(conn)
        log.info("")
        seed_vehicle_assets(conn)
        log.info("")
        seed_payroll_snapshots(conn)
        log.info("")
        seed_app_settings(conn)

    # ── Run post-commit pipeline (same as real connectors) ────────────
    log.info("")
    log.info("🔄 Running post-commit pipeline (categorization → reconciliation → derived → alerts → goals)...")
    from backend.result_writer import run_post_commit_pipeline

    seeded_institutions = set(ACCT_INST_MAP.values())
    for inst_id in sorted(seeded_institutions):
        log.info("  ▶ Pipeline for %s...", inst_id)
        try:
            results = run_post_commit_pipeline(inst_id)
            log.info("    ✓ %s done: %s", inst_id, results)
        except Exception as e:
            log.warning("    ⚠ Pipeline failed for %s (non-fatal): %s", inst_id, e)

    # Also backfill merchant column for normalized merchant names
    log.info("")
    log.info("🏪 Backfilling merchant names...")
    try:
        from dal.merchant_normalizer import backfill_merchant_column
        with get_db() as conn:
            updated = backfill_merchant_column(conn)
            log.info("  ✓ %d merchants normalized", updated)
    except Exception as e:
        log.warning("  ⚠ Merchant backfill failed (non-fatal): %s", e)

    log.info("")
    log.info("=" * 60)
    log.info("  ✅ All dummy data loaded and pipeline complete!")
    log.info("=" * 60)

    # Print summary
    log.info("")
    with get_db() as conn:
        for table in [
            "owners", "institutions", "accounts",
            "transactions", "balance_snapshots", "budgets",
            "recurring_transactions", "savings_goals", "loan_details",
            "investment_holdings", "portfolio_snapshots",
            "credit_scores", "real_estate", "vehicle_assets",
        ]:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
                log.info("  %-30s %d rows", table, count)
            except Exception:
                log.info("  %-30s (table not found)", table)


if __name__ == "__main__":
    main()
