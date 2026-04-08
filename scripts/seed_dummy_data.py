"""
scripts/seed_dummy_data.py — Rolling generative dummy data seeder.

This script seeds the dev database with a deterministic, hand-auditable
fixture set that ALWAYS ends at ``end_date`` (default: yesterday).

Re-running any day rolls the window forward automatically; no frozen
JSON fixtures.  Override the end-date with --end-date for reproducibility
in tests.

Transactions route through the real ``upsert_transactions`` pipeline
(same code path as live connectors) and the full post-commit pipeline
runs per institution.  Structural fixtures (owners, recurring patterns,
goals, real estate, loans, app settings) still live in ``dummy_data/``
as JSON — only historical time-series data is generated.

Usage:
    # Roll forward to yesterday (default)
    SENTRY_DB_PATH=data/dummy.db python scripts/seed_dummy_data.py

    # Pin to a specific end-date (deterministic for tests)
    SENTRY_DB_PATH=data/dummy.db python scripts/seed_dummy_data.py \\
        --end-date 2026-04-05 --years 3
"""

import argparse
import json
import logging
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dal.database import init_db, get_db
from scripts.dummy_data import generator as gen

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

DUMMY_DIR = Path(_PROJECT_ROOT) / "dummy_data"

# Global institution map — built at seed-time from the generator's
# canonical account list, not from JSON.
ACCT_INST_MAP: dict[str, str] = {}


def load_json(filename: str):
    """Load a JSON file from the dummy_data directory (structural fixtures only)."""
    path = DUMMY_DIR / filename
    if not path.exists():
        log.warning("  !  %s not found, skipping", filename)
        return [] if filename.endswith(".json") else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Seed Functions ───────────────────────────────────────────────────────────

def seed_owners(conn):
    """Load owners from owners.json into the owners table."""
    log.info("Seeding owners...")
    rows = load_json("owners.json")
    for row in rows:
        conn.execute(
            "INSERT OR IGNORE INTO owners (id, display_name) VALUES (?, ?)",
            (row["id"], row["display_name"]),
        )
    conn.commit()
    log.info("  %d owners seeded", len(rows))


def seed_institutions_and_accounts(conn):
    """Seed institutions and accounts from the generator's canonical list."""
    log.info("Seeding institutions & accounts...")

    rows = gen.institution_rows()
    global ACCT_INST_MAP
    ACCT_INST_MAP = {r["account_id"]: r["institution_id"] for r in rows}

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
            conn.execute(
                "INSERT OR IGNORE INTO institution_refresh_status (institution_id) VALUES (?)",
                (inst_id,),
            )
            inst_ids.add(inst_id)

    for row in rows:
        is_active = row.get("is_active", True)
        closed_at = row.get("closed_at")
        # INSERT OR REPLACE: also re-activate accounts whose is_active was
        # previously toggled off by the ghost-deactivation pass below.
        conn.execute(
            """INSERT OR REPLACE INTO accounts
               (id, institution_id, name, last4, type, owner_id, is_active, closed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["account_id"],
                row["institution_id"],
                row["name"],
                row["account_id"].split("_")[-1],
                row["type"],
                row.get("owner_id"),
                1 if is_active else 0,
                closed_at,
            ),
        )

    # Deactivate any pre-existing real-account stubs that aren't part of the
    # canonical dummy set.  Without this, /api/accounts returns a dozen
    # "Pending $0.00" rows for NFCU/Chase/Fidelity/etc. left over from
    # earlier sessions.
    canonical_ids = list(ACCT_INST_MAP.keys())
    if canonical_ids:
        placeholders = ",".join("?" * len(canonical_ids))
        cur = conn.execute(
            f"UPDATE accounts SET is_active=0 "
            f"WHERE id NOT IN ({placeholders}) AND is_active = 1",
            canonical_ids,
        )
        deactivated = cur.rowcount
    else:
        deactivated = 0

    conn.commit()
    log.info(
        "  %d institutions, %d accounts seeded (%d non-canonical accounts deactivated)",
        len(inst_ids), len(rows), deactivated,
    )


def seed_transactions(conn, end_date: date, years: int):
    """Generate transactions and route through the real upsert pipeline."""
    from dal.transactions import upsert_transactions

    log.info("Seeding transactions (end_date=%s, years=%d)...", end_date.isoformat(), years)

    # Clean dummy-prefixed rows, rows for the accounts owned by the
    # dummy dataset, AND any rows belonging to the dummy institutions
    # (catches legacy closed-account rows from earlier seeder runs).
    conn.execute("DELETE FROM transactions WHERE id LIKE 'dummy_%'")
    dummy_accounts = list(ACCT_INST_MAP.keys())
    if dummy_accounts:
        placeholders = ",".join("?" * len(dummy_accounts))
        conn.execute(
            f"DELETE FROM transactions WHERE account_id IN ({placeholders})",
            dummy_accounts,
        )
    dummy_institutions = list(set(ACCT_INST_MAP.values()))
    if dummy_institutions:
        placeholders = ",".join("?" * len(dummy_institutions))
        conn.execute(
            f"DELETE FROM transactions WHERE institution_id IN ({placeholders})",
            dummy_institutions,
        )
    conn.commit()

    rng = gen._mk_rng(end_date)
    txn_dicts = gen.generate_transactions(end_date, years=years, rng=rng)

    stats = upsert_transactions(conn, txn_dicts)
    conn.commit()

    log.info(
        "  generated %d rows (inserted=%d, updated=%d, unchanged=%d)",
        len(txn_dicts),
        stats["inserted"], stats["updated"], stats["unchanged"],
    )


def seed_balance_snapshots(conn, end_date: date, years: int):
    """
    Generate balance snapshots via closure-preserving walk over txns.

    Investment / retirement accounts pull their snapshots from
    portfolio_snapshots (seeded just before this step) so the three
    "investment total" surfaces — Investments page, Accounts page,
    and net worth chart — all reconcile to a single series.
    """
    log.info("Seeding balance snapshots...")

    # Unconditional cleanup — any rows from earlier seeder generations
    # (dummy_seed_history, dummy_seed_current, …) would otherwise survive
    # and produce a fused-regime net worth chart with phantom cliffs/jumps.
    conn.execute("DELETE FROM balance_snapshots")

    rng = gen._mk_rng(end_date)
    txns = gen.generate_transactions(end_date, years=years, rng=rng)

    # Pull portfolio_snapshots for investment/retirement accounts so the
    # generator can use them in lieu of the closure walk.
    portfolio_by_acct: dict[str, list[tuple[str, float]]] = {}
    for row in conn.execute(
        "SELECT account_id, substr(timestamp, 1, 10) AS d, "
        "       total_account_value + COALESCE(cash_balance, 0) "
        "FROM portfolio_snapshots "
        "ORDER BY account_id, timestamp"
    ):
        portfolio_by_acct.setdefault(row[0], []).append((row[1], float(row[2])))

    rows = gen.generate_balance_snapshots(
        end_date, txns, portfolio_by_acct=portfolio_by_acct
    )

    for row in rows:
        conn.execute(
            """INSERT INTO balance_snapshots
               (account_id, balance, as_of, refresh_run_id)
               VALUES (?, ?, ?, 'dummy_seed')""",
            (row["account_id"], row["balance_amount"], row["date"]),
        )

    conn.commit()
    log.info("  %d balance snapshots seeded", len(rows))


def seed_budgets(conn, end_date: date, years: int):
    """Generate monthly budget rows."""
    log.info("Seeding budgets...")

    conn.execute("DELETE FROM budgets")

    rows = gen.generate_budgets(end_date, years)
    for row in rows:
        conn.execute(
            """INSERT INTO budgets
               (category, month, target_amount)
               VALUES (?, ?, ?)""",
            (row["category"], row["month"], row["target_amount"]),
        )

    conn.commit()
    log.info("  %d budget targets seeded", len(rows))


def seed_recurring_transactions(conn, end_date: date):
    """
    Load recurring patterns from recurring_transactions.json and rewrite
    the stale last_date / next_date fields relative to ``end_date``.

    The JSON fixture defines the recurring pattern catalog; only the date
    anchors are recomputed so the UI shows sensible next-expected dates
    that roll with the rest of the dataset.
    """
    log.info("Seeding recurring transactions...")

    conn.execute("DELETE FROM recurring_transactions WHERE id LIKE 'dummy_%'")

    rows = load_json("recurring_transactions.json")
    for row in rows:
        acct_id = row["account_id"]
        rec_id = f"dummy_{uuid.uuid4().hex[:12]}"

        freq_map = {
            "monthly": 30, "semi-annual": 182, "weekly": 7,
            "quarterly": 91, "annual": 365,
        }
        freq = row.get("frequency", "monthly")
        avg_interval = freq_map.get(freq, 30)

        # Recompute last_date / next_date relative to end_date so the
        # rolling window keeps the "next expected" field sensible.
        last_date = (end_date - timedelta(days=2)).isoformat()
        next_date = (end_date + timedelta(days=avg_interval - 2)).isoformat()

        conn.execute(
            """INSERT INTO recurring_transactions
               (id, account_id, merchant, category, frequency, avg_interval,
                expected_amount, amount_stable, last_amount, last_date,
                next_expected, occurrence_count, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 6, 'active')""",
            (rec_id, acct_id, row["merchant"], row.get("category", ""),
             freq, avg_interval,
             row.get("expected_amount", 0),
             row.get("expected_amount", 0),
             last_date,
             next_date),
        )

    conn.commit()
    log.info("  %d recurring transactions seeded", len(rows))


def seed_savings_goals(conn):
    """Load savings_goals.json (structural fixture, no dates to roll)."""
    log.info("Seeding savings goals...")

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
    log.info("  %d savings goals seeded", len(rows))


def seed_loan_details(conn, end_date: date):
    """Load loan_details.json into the KV-style loan_details table."""
    log.info("Seeding loan details...")

    conn.execute("DELETE FROM loan_details WHERE refresh_run_id = 'dummy_seed'")

    rows = load_json("loan_details.json")
    count = 0
    for row in rows:
        acct_id = row["account_id"]
        as_of = end_date.isoformat()

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
    log.info("  %d loan detail KV rows seeded", count)


def seed_investment_history(conn, end_date: date, years: int):
    """Generate investment holdings and portfolio snapshots."""
    log.info("Seeding investment holdings + portfolio snapshots...")

    conn.execute("DELETE FROM investment_holdings")
    conn.execute("DELETE FROM portfolio_snapshots")

    rng = gen._mk_rng(end_date)
    holdings, portfolio = gen.generate_investment_history(end_date, years, rng)

    for row in holdings:
        conn.execute(
            """INSERT INTO investment_holdings
               (account_id, date, ticker, shares, close_price, market_value)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (row["account_id"], row["date"], row["ticker"],
             row["shares"], row["close_price"], row["market_value"]),
        )

    for row in portfolio:
        conn.execute(
            """INSERT INTO portfolio_snapshots
               (account_id, timestamp, total_account_value, cash_balance)
               VALUES (?, ?, ?, ?)""",
            (row["account_id"], row["timestamp"], row["total_account_value"],
             row.get("cash_balance", 0)),
        )

    conn.commit()
    log.info("  %d holdings, %d portfolio snapshots seeded",
             len(holdings), len(portfolio))


def seed_credit_scores(conn, end_date: date, years: int):
    """Generate monthly credit score time series."""
    log.info("Seeding credit scores...")

    conn.execute("DELETE FROM credit_scores")

    rng = gen._mk_rng(end_date)
    rows = gen.generate_credit_scores(end_date, years, rng)
    for row in rows:
        conn.execute(
            """INSERT INTO credit_scores
               (institution_id, score, score_type, source, score_date, owner_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (row["institution_id"], row["score"],
             row.get("score_type", "FICO"), row.get("source", "TransUnion"),
             row["score_date"], row.get("owner_id")),
        )

    conn.commit()
    log.info("  %d credit scores seeded", len(rows))


def seed_real_estate(conn):
    """Load real_estate.json (structural fixture: quarterly home valuations)."""
    log.info("Seeding real estate valuations...")

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
    log.info("  %d real estate valuation rows seeded", len(rows))


def seed_vehicle_assets(conn, end_date: date, years: int):
    """Load vehicle_assets.json (static) and generate vehicle_valuations."""
    log.info("Seeding vehicle assets + valuations...")

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

    valuations = gen.generate_vehicle_valuations(end_date, years)
    for row in valuations:
        conn.execute(
            """INSERT INTO vehicle_valuations
               (vehicle_id, valuation_date, estimated_value, source)
               VALUES (?, ?, ?, ?)""",
            (row["vehicle_id"], row["valuation_date"],
             row["estimated_value"], row.get("source", "KBB")),
        )

    conn.commit()
    log.info("  %d vehicles, %d valuations seeded", len(assets), len(valuations))


def seed_payroll_snapshots(conn, end_date: date):
    """Generate synthetic myPay RAS rows (pension data)."""
    log.info("Seeding synthetic payroll snapshots...")

    rows = gen.generate_payroll_snapshots(end_date, months=36)
    for row in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO payroll_snapshots
            (pay_period, source, gross_pay, federal_tax, state_tax,
             sbp_premium, health_insurance, dental_vision,
             other_deductions, net_pay, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
            """,
            (
                row["pay_period"], row["source"],
                row["gross_pay"], row["federal_tax"], row["state_tax"],
                row["sbp_premium"], row["health_insurance"],
                row["dental_vision"], row["other_deductions"],
                row["net_pay"],
            ),
        )

    conn.commit()
    log.info("  %d payroll snapshots seeded", len(rows))


def seed_app_settings(conn):
    """Load app_settings.json."""
    log.info("Seeding app settings...")

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
    log.info("  %d app settings seeded", len(settings))


# ── Main ─────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sentry Finance dummy data seeder")
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD). Defaults to yesterday — the dataset rolls "
             "forward on each run. Pin to a specific date for reproducible test runs.",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=3,
        help="Years of history to generate (default: 3).",
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    if args.end_date:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    else:
        end_date = date.today() - timedelta(days=1)

    years = args.years

    log.info("=" * 60)
    log.info("  Sentry Finance - Dummy Data Seeder")
    log.info("=" * 60)
    log.info("  end_date = %s", end_date.isoformat())
    log.info("  years    = %d", years)
    log.info("  start    = %s", (end_date - timedelta(days=years * 365)).isoformat())
    log.info("")

    # Initialize DB (runs migrations)
    init_db()

    with get_db() as conn:
        seed_owners(conn)
        seed_institutions_and_accounts(conn)
        seed_transactions(conn, end_date, years)
        # investment_history must run BEFORE balance_snapshots so the
        # latter can pull portfolio_snapshots from the DB and use them
        # for investment/retirement account balances.
        seed_investment_history(conn, end_date, years)
        seed_balance_snapshots(conn, end_date, years)
        seed_budgets(conn, end_date, years)
        seed_recurring_transactions(conn, end_date)
        seed_savings_goals(conn)
        seed_loan_details(conn, end_date)
        seed_credit_scores(conn, end_date, years)
        seed_real_estate(conn)
        seed_vehicle_assets(conn, end_date, years)
        seed_payroll_snapshots(conn, end_date)
        seed_app_settings(conn)

    # ── Run post-commit pipeline (same as real connectors) ────────────
    log.info("")
    log.info("Running post-commit pipeline (categorization -> reconciliation "
             "-> derived -> alerts -> goals)...")
    from backend.result_writer import run_post_commit_pipeline

    seeded_institutions = set(ACCT_INST_MAP.values())
    for inst_id in sorted(seeded_institutions):
        log.info("  Pipeline for %s...", inst_id)
        try:
            results = run_post_commit_pipeline(inst_id)
            log.info("    %s done: %s", inst_id, results)
        except Exception as e:
            log.warning("    Pipeline failed for %s (non-fatal): %s", inst_id, e)

    # Also backfill merchant column for normalized merchant names
    log.info("")
    log.info("Backfilling merchant names...")
    try:
        from dal.merchant_normalizer import backfill_merchant_column
        with get_db() as conn:
            updated = backfill_merchant_column(conn)
            log.info("  %d merchants normalized", updated)
    except Exception as e:
        log.warning("  Merchant backfill failed (non-fatal): %s", e)

    log.info("")
    log.info("=" * 60)
    log.info("  All dummy data loaded and pipeline complete!")
    log.info("=" * 60)
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

        # ── Post-seed integrity assertions ──────────────────────────────
        dups = conn.execute(
            "SELECT account_id, as_of, COUNT(*) FROM balance_snapshots "
            "GROUP BY account_id, as_of HAVING COUNT(*) > 1"
        ).fetchall()
        if dups:
            raise RuntimeError(
                f"Seeder integrity check failed: {len(dups)} duplicate "
                f"(account_id, as_of) pairs in balance_snapshots — first 5: {dups[:5]}"
            )

        # Liability accounts must have non-positive balances
        bad_signs = conn.execute(
            "SELECT bs.account_id, bs.as_of, bs.balance "
            "FROM balance_snapshots bs JOIN accounts a ON a.id = bs.account_id "
            "WHERE a.type IN ('credit_card', 'loan', 'bnpl', 'mortgage') "
            "  AND bs.balance > 0 LIMIT 5"
        ).fetchall()
        if bad_signs:
            raise RuntimeError(
                f"Seeder integrity check failed: liability account has "
                f"positive balance — first 5: {bad_signs}"
            )

        log.info("")
        log.info("  Integrity checks passed (no duplicate snapshots, "
                 "all liabilities non-positive)")


if __name__ == "__main__":
    main()
