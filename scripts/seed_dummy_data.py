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

from dal.apy_history import record_apy_history
from dal.balances import record_balance, record_loan_details
from dal.credit_scores import record_credit_score
from dal.database import init_db, get_db
from dal.real_estate import record_real_estate_valuations
from dal.vehicles import add_valuation, add_vehicle
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

    canonical_acct_ids = [r["account_id"] for r in rows]
    canonical_inst_ids = sorted({r["institution_id"] for r in rows})

    # ── Stale-account scrub ──────────────────────────────────────────
    # Hard-delete any non-canonical accounts left over from prior
    # real-connector sessions (chase, nfcu, amex, acorns, fidelity,
    # tsp, affirm, rocket, etc).  These pre-date the multi-user
    # owner_id migration and carry owner_id=NULL, so they need to go
    # for dev-mode owner filtering to stay clean.  Canonical rows are
    # preserved.  Child rows are cascade-deleted first so the accounts
    # DELETE doesn't fail on FK constraints.
    if canonical_acct_ids:
        ph = ",".join("?" * len(canonical_acct_ids))
        stale_ids = [
            r[0]
            for r in conn.execute(
                f"SELECT id FROM accounts WHERE id NOT IN ({ph})",
                canonical_acct_ids,
            ).fetchall()
        ]
    else:
        stale_ids = []

    scrubbed = 0
    if stale_ids:
        stale_ph = ",".join("?" * len(stale_ids))
        child_tables = [
            ("balance_snapshots", "account_id"),
            ("transactions", "account_id"),
            ("recurring_transactions", "account_id"),
            ("loan_details", "account_id"),
            ("investment_holdings", "account_id"),
            ("portfolio_snapshots", "account_id"),
            ("positions_ledger", "account_id"),
            ("savings_goals", "linked_account_id"),
        ]
        for table, col in child_tables:
            try:
                conn.execute(
                    f"DELETE FROM {table} WHERE {col} IN ({stale_ph})",
                    stale_ids,
                )
            except Exception as e:
                log.warning(
                    "  scrub: could not clean %s.%s (%s) — continuing",
                    table, col, e,
                )

        conn.execute(
            f"DELETE FROM accounts WHERE id IN ({stale_ph})",
            stale_ids,
        )
        scrubbed = len(stale_ids)
        conn.commit()

    # ── Canonical institutions ───────────────────────────────────────
    inst_ids = set()
    for row in rows:
        inst_id = row["institution_id"]
        if inst_id not in inst_ids:
            conn.execute(
                """INSERT OR IGNORE INTO institutions
                   (id, display_name, refresh_interval_hours, mfa_expected,
                    extraction_method, is_synthetic)
                   VALUES (?, ?, 24, 'none', 'dummy', 1)""",
                (inst_id, inst_id.replace("_", " ").title()),
            )
            conn.execute(
                "INSERT OR IGNORE INTO institution_refresh_status (institution_id) VALUES (?)",
                (inst_id,),
            )
            inst_ids.add(inst_id)

    # ── Stale institutions scrub ─────────────────────────────────────
    # 1. Drop stale *synthetic* institutions no longer in the canonical set.
    # 2. Drop any *real* institutions that crept in during pipeline testing.
    # Net effect: after re-seed the DB contains only canonical synthetic
    # institutions — a clean, known state.
    # institution_refresh_status has a FK on institution_id, so clean
    # that side first.
    if canonical_inst_ids:
        ph = ",".join("?" * len(canonical_inst_ids))
        try:
            # Stale synthetic institutions (renamed / removed from fixtures)
            conn.execute(
                f"DELETE FROM institution_refresh_status "
                f"WHERE institution_id NOT IN ({ph}) "
                f"AND institution_id IN ("
                f"  SELECT id FROM institutions WHERE is_synthetic = 1"
                f")",
                canonical_inst_ids,
            )
            conn.execute(
                f"DELETE FROM institutions "
                f"WHERE id NOT IN ({ph}) AND is_synthetic = 1",
                canonical_inst_ids,
            )
            # Real institutions from pipeline testing
            conn.execute(
                "DELETE FROM institution_refresh_status "
                "WHERE institution_id IN ("
                "  SELECT id FROM institutions WHERE is_synthetic = 0"
                ")"
            )
            conn.execute(
                "DELETE FROM institutions WHERE is_synthetic = 0"
            )
        except Exception as e:
            log.warning("  scrub: could not clean stale institutions (%s)", e)

    # ── Canonical accounts ───────────────────────────────────────────
    for row in rows:
        is_active = row.get("is_active", True)
        closed_at = row.get("closed_at")
        last4 = row.get("last4") or "XXXX"
        conn.execute(
            """INSERT OR REPLACE INTO accounts
               (id, institution_id, name, last4, type, owner_id, is_active,
                closed_at, is_synthetic, tax_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (
                row["account_id"],
                row["institution_id"],
                row["name"],
                last4,
                row["type"],
                row.get("owner_id"),
                1 if is_active else 0,
                closed_at,
                row.get("tax_status"),
            ),
        )

    conn.commit()
    log.info(
        "  %d institutions, %d accounts seeded (%d stale non-canonical scrubbed)",
        len(inst_ids), len(rows), scrubbed,
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


def seed_acorns_investments(conn, end_date: date, years: int):
    """Seed Acorns Synthetic investment history from bank-side debits."""
    log.info("Seeding Acorns investment history...")

    # Re-generate the transaction list (same RNG → same output) to pass
    # to the investment history generator so it knows which debits exist.
    rng = gen._mk_rng(end_date)
    txns = gen.generate_transactions(end_date, years=years, rng=rng)

    result = gen.generate_acorns_investment_history(conn, txns, end_date, years)
    log.info(
        "  ledger=%d, holdings=%d, snapshots=%d, prices_cached=%d",
        result["ledger_rows"], result.get("holding_rows", 0),
        result["snapshot_rows"], result["prices_cached"],
    )

    # Link bank-side Acorns debits to positions_ledger via transfer_tag.
    # For each Acorns transfer/roundup debit in the transactions table,
    # find the positions_ledger rows from the same date and set the
    # transfer_tag to "invest:{ledger_id}".
    acorns_txns = conn.execute("""
        SELECT id, posting_date, amount
        FROM transactions
        WHERE account_id = 'summit_chk'
          AND description LIKE '%ACORNS INVEST%'
          AND description NOT LIKE '%FEE%'
          AND direction = 'Debit'
        ORDER BY posting_date
    """).fetchall()

    linked = 0
    for txn_row in acorns_txns:
        txn_id = txn_row[0]
        txn_date = txn_row[1][:10]

        # Find the first unlinked positions_ledger entry from same date
        ledger_row = conn.execute("""
            SELECT id FROM positions_ledger
            WHERE account_id = 'acorns_synthetic'
              AND timestamp LIKE ?
              AND bank_txn_id IS NULL
            ORDER BY id LIMIT 1
        """, (f"{txn_date}%",)).fetchone()

        if ledger_row:
            ledger_id = ledger_row[0]
            conn.execute(
                "UPDATE transactions SET transfer_tag = ?, investment_link = ? WHERE id = ?",
                (f"invest:{ledger_id}", str(ledger_id), txn_id),
            )
            conn.execute(
                "UPDATE positions_ledger SET bank_txn_id = ? WHERE id = ?",
                (txn_id, ledger_id),
            )
            linked += 1

    conn.commit()
    log.info("  %d bank debits linked to positions_ledger (transfer_tag set)", linked)


def seed_fidelity_investments(conn, end_date: date, years: int):
    """Seed Fidelity Brokerage synthetic investment history."""
    log.info("Seeding Fidelity investment history...")
    result = gen.generate_fidelity_investment_history(conn, end_date, years)
    log.info(
        "  ledger=%d, holdings=%d, snapshots=%d, prices_cached=%d, dividend_txns=%d",
        result["ledger_rows"], result["holding_rows"],
        result["snapshot_rows"], result["prices_cached"],
        result.get("dividend_txns", 0),
    )


def seed_tsp_investments(conn, end_date: date, years: int):
    """Seed synthetic TSP retirement account investment history."""
    log.info("Seeding TSP investment history...")
    result = gen.generate_tsp_investment_history(conn, end_date, years)
    log.info(
        "  holdings=%d, snapshots=%d, prices_cached=%d",
        result["holding_rows"], result["snapshot_rows"],
        result["prices_cached"],
    )


def seed_ticker_metadata(conn):
    """Enrich ticker_metadata for all investment tickers."""
    log.info("Enriching ticker metadata...")
    enriched = gen.enrich_ticker_metadata(conn)
    log.info("  %d tickers enriched", enriched)


def ensure_fund_composition(conn):
    """Ensure fund_composition and fund_sector_weights reference rows are current.

    Uses DELETE + INSERT to guarantee both tables reflect the latest
    decomposition weights.  Safe to re-run.
    """
    from dal.migrations.v27_fund_composition import _COMPOSITION_ROWS
    from dal.migrations.v28_fund_sector_weights import _SECTOR_ROWS
    cur = conn.cursor()

    cur.execute("DELETE FROM fund_composition")
    cur.executemany(
        "INSERT INTO fund_composition "
        "(ticker, asset_class, weight, geography, cap_class, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        _COMPOSITION_ROWS,
    )
    log.info("  fund_composition: %d reference rows written", len(_COMPOSITION_ROWS))

    cur.execute("DELETE FROM fund_sector_weights")
    cur.executemany(
        "INSERT INTO fund_sector_weights "
        "(ticker, sector, weight, source) "
        "VALUES (?, ?, ?, ?)",
        _SECTOR_ROWS,
    )
    log.info("  fund_sector_weights: %d reference rows written", len(_SECTOR_ROWS))

    conn.commit()


def seed_balance_snapshots(conn, end_date: date, years: int):
    """
    Generate balance snapshots via closure-preserving walk over txns.

    NOTE (P13 investments rebuild): the investment/retirement override
    path that pulled balances from `portfolio_snapshots` was removed
    along with investment seeding.  Non-investment accounts walk
    transactions as before.
    """
    log.info("Seeding balance snapshots...")

    # Unconditional cleanup — any rows from earlier seeder generations
    # (dummy_seed_history, dummy_seed_current, …) would otherwise survive
    # and produce a fused-regime net worth chart with phantom cliffs/jumps.
    conn.execute("DELETE FROM balance_snapshots")

    rng = gen._mk_rng(end_date)
    txns = gen.generate_transactions(end_date, years=years, rng=rng)

    rows = gen.generate_balance_snapshots(end_date, txns)

    for row in rows:
        record_balance(
            conn,
            account_id=row["account_id"],
            balance=row["balance_amount"],
            as_of=row["date"],
            refresh_run_id="dummy_seed",
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
               (category, month, target_amount, owner_id)
               VALUES (?, ?, ?, ?)""",
            (row["category"], row["month"], row["target_amount"], row["owner_id"]),
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
               (name, target_amount, current_amount, deadline,
                linked_account_id, status, owner_id)
               VALUES (?, ?, ?, ?, ?, 'active', 'quintin')""",
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
        non_null = {k: str(v) for k, v in fields.items() if v is not None}
        if non_null:
            record_loan_details(
                conn,
                account_id=acct_id,
                details=non_null,
                as_of=as_of,
                refresh_run_id="dummy_seed",
            )
            count += len(non_null)

    conn.commit()
    log.info("  %d loan detail KV rows seeded", count)


# ── Investment seeding removed (P13 investments rebuild) ────────────────────
# `seed_investment_history`, `seed_ticker_metadata`, and
# `cleanup_orphaned_investment_accounts` were deleted as part of the
# ground-up investments rebuild.  A future P13 task will reintroduce
# investment seeding against the new read path, starting with an
# "Acorns Synthetic" account.


def seed_apy_history(conn, end_date: date, years: int):
    """Generate rolling APY snapshots for the proxy deposit accounts.

    P15-T04 Phase B: APY moved from the key-value ``loan_details`` table
    into its own time-series ``apy_history``. This seeder gives the
    future T06 UI trend data to render and exercises the
    ``record_apy_history`` invariant path on the same code path a live
    connector would hit.
    """
    log.info("Seeding APY history...")

    conn.execute("DELETE FROM apy_history")

    rng = gen._mk_rng(end_date)
    rows = gen.generate_apy_history(end_date, years, rng)
    for row in rows:
        record_apy_history(
            conn,
            account_id=row["account_id"],
            apy_rate=row["apy_rate"],
            as_of=row["as_of"],
            source=row["source"],
        )
    conn.commit()
    log.info("  %d apy_history rows seeded", len(rows))


def seed_loan_details_stretch(conn, end_date: date):
    """Stamp latest-wins stretch fields the NFCU scraper will capture.

    P15-T04 Phase B ships regex patterns for cash-advance limits,
    payoff amounts, collateral info, payments-made, and similar loan
    and credit-card detail fields. Seeding a representative row per
    account lets the future T06 UI render the full detail panel off
    dummy data.
    """
    log.info("Seeding loan_details stretch fields...")

    as_of = end_date.isoformat()

    # Credit-card stretch (summit_cc is the NFCU-CC proxy).
    record_loan_details(
        conn,
        account_id="summit_cc",
        details={
            "cash_advance_limit": "5000.00",
            "cash_advance_available": "5000.00",
            "14_day_payoff": "2451.33",
            "payment_due_date": "05/08/2026",
            "ytd_interest": "42.18",
            "date_opened": "12/11/2010",
        },
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )

    # Auto loan stretch (summit_auto is the NFCU auto-loan proxy).
    record_loan_details(
        conn,
        account_id="summit_auto",
        details={
            "payoff_today": "18432.11",
            "14_day_payoff": "18510.47",
            "payments_made": "50",
            "ytd_interest": "188.52",
            "collateral_type": "TITLE/LIEN - VEHICLE",
            "collateral_description": "2020 HONDA CIVIC",
            "vin": "1HGFAKEDUMMY00001",
            "gap_flag": "Yes",
            "date_opened": "03/15/2022",
        },
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )

    # Mortgage stretch (summit_mtg is the NFCU-mortgage proxy).
    record_loan_details(
        conn,
        account_id="summit_mtg",
        details={
            "payoff_today": "412330.22",
            "14_day_payoff": "413201.15",
            "payments_made": "36",
            "ytd_interest": "5212.88",
            "escrow_balance": "3420.55",
            "collateral_description": "123 Demo Lane, Exampleton",
            "date_opened": "04/02/2023",
        },
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )

    # Deposit stretch — summit_chk (checking) and summit_sav
    # (savings). APY intentionally NOT seeded here; it lives in
    # apy_history via seed_apy_history.
    record_loan_details(
        conn,
        account_id="summit_chk",
        details={
            "available_balance": "2431.18",
            "dividends_ytd": "0.82",
            "last_year_dividends": "2.14",
            "date_opened": "07/18/2016",
            "direct_deposit_enrolled": "Enrolled",
        },
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )
    record_loan_details(
        conn,
        account_id="summit_sav",
        details={
            "available_balance": "8230.44",
            "dividends_ytd": "15.22",
            "last_year_dividends": "48.16",
            "date_opened": "07/18/2016",
        },
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )

    conn.commit()
    log.info("  loan_details stretch fields seeded across 5 accounts")


def seed_credit_card_rewards(conn, end_date: date):
    """Stamp the NFCU-proxy credit card with a current rewards_points balance.

    P15-T03 chose the key-value ``loan_details`` shape (latest-wins) over a
    new time-series table, so one row per card is enough to exercise the
    live ``record_loan_details`` path and surface the rewards chip on the
    Accounts page.
    """
    log.info("Seeding credit card rewards...")

    # Wipe any prior seeded rewards rows so re-runs stay deterministic.
    conn.execute(
        "DELETE FROM loan_details WHERE field_name = 'rewards_points' "
        "AND refresh_run_id = 'dummy_seed'"
    )

    # summit_cc is the NFCU-proxy card; Coastal (Chase proxy) is
    # intentionally skipped to mirror real config where only NFCU scrapes
    # rewards today (Chase detail scraping tracked as P15-T05).
    record_loan_details(
        conn,
        account_id="summit_cc",
        details={"rewards_points": "8450"},
        as_of=end_date.isoformat(),
        refresh_run_id="dummy_seed",
    )

    conn.commit()
    log.info("  rewards_points seeded for summit_cc")


def seed_credit_scores(conn, end_date: date, years: int):
    """Generate monthly credit score time series."""
    log.info("Seeding credit scores...")

    conn.execute("DELETE FROM credit_scores")

    rng = gen._mk_rng(end_date)
    rows = gen.generate_credit_scores(end_date, years, rng)
    for row in rows:
        record_credit_score(
            conn,
            score=row["score"],
            score_type=row.get("score_type", "FICO"),
            source=row.get("source", "TransUnion"),
            institution_id=row["institution_id"],
            score_date=row["score_date"],
            owner_id=row.get("owner_id"),
        )

    conn.commit()
    log.info("  %d credit scores seeded", len(rows))


def seed_real_estate(conn):
    """Load real_estate.json (structural fixture: quarterly home valuations)."""
    log.info("Seeding real estate valuations...")

    conn.execute("DELETE FROM real_estate")

    rows = load_json("real_estate.json")
    record_real_estate_valuations(
        conn,
        [
            {
                "name": row["name"],
                "estimated_value": row["estimated_value"],
                "linked_loan_id": row.get("linked_loan_id"),
                "source": row.get("source", "estimate"),
                "as_of": row["as_of"],
                "owner_id": "quintin",
            }
            for row in rows
        ],
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
        add_vehicle(
            conn,
            vehicle_id=row["id"],
            make=row["make"],
            model=row["model"],
            year=row["year"],
            purchase_date=row["purchase_date"],
            purchase_price=row["purchase_price"],
            owner_id="quintin",
        )

    valuations = gen.generate_vehicle_valuations(end_date, years)
    for row in valuations:
        add_valuation(
            conn,
            vehicle_id=row["vehicle_id"],
            valuation_date=row["valuation_date"],
            estimated_value=row["estimated_value"],
            source=row.get("source", "KBB"),
        )

    conn.commit()
    log.info("  %d vehicles, %d valuations seeded", len(assets), len(valuations))


def seed_payroll_snapshots(conn, end_date: date):
    """Generate synthetic myPay RAS rows for both household payees."""
    log.info("Seeding synthetic payroll snapshots...")

    # Quintin — existing military pay/pension archetype.
    quintin_rows = gen.generate_payroll_snapshots(end_date, months=36)
    for row in quintin_rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO payroll_snapshots
            (pay_period, source, gross_pay, federal_tax, state_tax,
             sbp_premium, health_insurance, dental_vision,
             other_deductions, net_pay, raw_json, owner_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 'quintin')
            """,
            (
                row["pay_period"], row["source"],
                row["gross_pay"], row["federal_tax"], row["state_tax"],
                row["sbp_premium"], row["health_insurance"],
                row["dental_vision"], row["other_deductions"],
                row["net_pay"],
            ),
        )

    # Phase 14 Phase B — Amy W-2 archetype.
    amy_rows = gen.generate_amy_payroll_snapshots(end_date, months=36)
    for row in amy_rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO payroll_snapshots
            (pay_period, source, gross_pay, federal_tax, state_tax,
             sbp_premium, health_insurance, dental_vision,
             other_deductions, net_pay, raw_json, owner_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 'amy')
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
    log.info(
        "  %d Quintin + %d Amy payroll snapshots seeded",
        len(quintin_rows), len(amy_rows),
    )


def seed_income_sources(conn):
    """Phase 14 Phase B — seed the income_sources registry.

    Populates a small fixture set that exercises every classifier path:
    a bypass-routed employer match (→ STORED_ILLIQUID pseudo-edge), a
    contractor source with no withholding, and a W-2 source for Amy.
    Idempotent via INSERT OR REPLACE on the stable seed ids from
    ``gen.generate_income_source_registry``.
    """
    log.info("Seeding income_sources registry (Phase 14 Phase B)...")

    from dal import income_sources as income_sources_dal

    rows = gen.generate_income_source_registry()
    for row in rows:
        existing = income_sources_dal.get_by_id(conn, row["id"])
        if existing:
            income_sources_dal.update(
                conn,
                row["id"],
                display_label=row["display_label"],
                tax_treatment=row["tax_treatment"],
                default_category=row["default_category"],
                match_rule=row["match_rule_json"],
                estimated_tax_reserve_pct=row["estimated_tax_reserve_pct"],
                bypass_cash_routing=bool(row["bypass_cash_routing"]),
                active=bool(row["active"]),
            )
        else:
            income_sources_dal.create(
                conn,
                source_id=row["id"],
                display_label=row["display_label"],
                owner_id=row["owner_id"],
                tax_treatment=row["tax_treatment"],
                default_category=row["default_category"],
                match_rule=row["match_rule_json"],
                estimated_tax_reserve_pct=row["estimated_tax_reserve_pct"],
                bypass_cash_routing=bool(row["bypass_cash_routing"]),
                active=bool(row["active"]),
            )
    conn.commit()
    log.info("  %d income_sources seeded", len(rows))


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
        # P13 investments rebuild — clear the investment-surface tables
        # on every re-seed.  The `accounts` table is owned by
        # seed_institutions_and_accounts() above; canonical investment
        # accounts (currently just Acorns Synthetic) stay, and stale
        # non-canonical rows from prior runs are already deactivated
        # there (is_active=0).  Child tables (balance_snapshots,
        # transactions, etc.) are wiped by their own seed functions
        # later in main(), so we don't cascade here.
        conn.execute("DELETE FROM investment_holdings")
        conn.execute("DELETE FROM portfolio_snapshots")
        conn.execute("DELETE FROM positions_ledger")
        conn.execute("DELETE FROM ticker_metadata")
        conn.execute("DELETE FROM benchmark_prices")
        conn.commit()
        # P13-T03: seed Acorns investment history (positions_ledger +
        # portfolio_snapshots) using bank-side Acorns debits and real
        # yFinance prices.  Needs txns already in the DB for linkage.
        seed_acorns_investments(conn, end_date, years)
        seed_fidelity_investments(conn, end_date, years)
        seed_tsp_investments(conn, end_date, years)
        seed_ticker_metadata(conn)
        ensure_fund_composition(conn)
        seed_balance_snapshots(conn, end_date, years)
        seed_budgets(conn, end_date, years)
        seed_recurring_transactions(conn, end_date)
        seed_savings_goals(conn)
        seed_loan_details(conn, end_date)
        seed_credit_card_rewards(conn, end_date)
        seed_loan_details_stretch(conn, end_date)
        seed_apy_history(conn, end_date, years)
        seed_credit_scores(conn, end_date, years)
        seed_real_estate(conn)
        seed_vehicle_assets(conn, end_date, years)
        seed_payroll_snapshots(conn, end_date)
        seed_income_sources(conn)
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
