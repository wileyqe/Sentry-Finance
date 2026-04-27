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
from dal.investment_details import record_investment_details
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

    # AI-010: emit a paired summit_chk debit for each Fidelity DEPOSIT
    # ledger row so the cash-flow Sankey sees the outflow leg. Live
    # ingestion of a real Fidelity EFT would emit BOTH legs (checking
    # debit + ledger DEPOSIT); the synthetic generator only writes the
    # ledger side, so cash-flow reports were synthetically blind to the
    # outflow until now. Mirrors the Acorns triple-coupling pattern in
    # `seed_acorns_investments` above. transfer_tag links the two legs
    # and excludes them from spending/income aggregates.
    from dal.transactions import upsert_transactions

    deposit_rows = conn.execute(
        """
        SELECT id, timestamp FROM positions_ledger
        WHERE account_id = 'fidelity_brokerage'
          AND transaction_type = 'DEPOSIT'
          AND ticker = 'SPAXX'
          AND share_delta = 0
          AND bank_txn_id IS NULL
        ORDER BY timestamp
        """
    ).fetchall()

    eft_txns: list[dict] = []
    for r in deposit_rows:
        date_str = r["timestamp"][:10]
        eft_txns.append(
            {
                "account_id": "summit_chk",
                "institution_id": "summit",
                "posting_date": date_str,
                "transaction_date": date_str,
                "amount": 500.0,
                "signed_amount": -500.0,
                "direction": "Debit",
                "description": "FIDELITY EFT TRANSFER",
                "category": "Investments",
                "status": "posted",
                "raw_description": "FIDELITY EFT TRANSFER",
                "merchant": "FIDELITY",
                "institution_txn_id": f"fid_eft_{date_str}",
            }
        )

    linked = 0
    if eft_txns:
        upsert_transactions(conn, eft_txns)
        # Backfill transfer_tag + investment_link on the just-inserted
        # rows. Match by institution_txn_id since the row id isn't
        # easily available from upsert_transactions return shape.
        for r in deposit_rows:
            date_str = r["timestamp"][:10]
            ledger_id = r["id"]
            cur = conn.execute(
                "SELECT id FROM transactions WHERE institution_txn_id = ?",
                (f"fid_eft_{date_str}",),
            ).fetchone()
            if cur is None:
                continue
            txn_id = cur[0]
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
    log.info(
        "  %d Fidelity EFT bank-side mirrors written, %d linked to ledger",
        len(eft_txns), linked,
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
            "monthly": 30, "semiannual": 182, "weekly": 7,
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
    account lets the T06 UI render the full detail panel off dummy
    data.

    P15-T06 fix: stretch fields for loans are now derived from the
    account's actual seeded balance + configured rate so the panel's
    numbers reconcile with the balance shown on the row. Static
    stubs (VIN, collateral, date_opened) stay static — they're
    identity fields, not balance-dependent.
    """
    log.info("Seeding loan_details stretch fields...")

    as_of = end_date.isoformat()

    def _latest_balance(acct: str) -> float:
        row = conn.execute(
            "SELECT balance FROM balance_snapshots "
            "WHERE account_id = ? ORDER BY as_of DESC LIMIT 1",
            (acct,),
        ).fetchone()
        return float(row["balance"]) if row else 0.0

    def _mortgage_stretch(acct: str, rate: float, origination: date) -> dict:
        """Derive payoff / payments_made / ytd_interest from state."""
        principal_outstanding = abs(_latest_balance(acct))
        if principal_outstanding == 0:
            # Paid off — drop the balance-dependent fields entirely.
            return {}
        daily_interest = principal_outstanding * rate / 365
        months_elapsed = max(
            0,
            (end_date.year - origination.year) * 12
            + (end_date.month - origination.month),
        )
        # YTD interest: assume constant avg balance across the YTD
        # months; a +/- few-hundred-dollar skew is fine for a
        # stretch field.
        ytd_months = end_date.month
        ytd_interest = principal_outstanding * rate / 12 * ytd_months
        return {
            "payoff_today": f"{principal_outstanding + daily_interest:.2f}",
            "14_day_payoff": f"{principal_outstanding + 14 * daily_interest:.2f}",
            "payments_made": str(months_elapsed),
            "ytd_interest": f"{ytd_interest:.2f}",
        }

    def _next_payment_due_date(statement_day: int) -> str:
        """Return MM/DD/YYYY for the next occurrence of ``statement_day``.

        Credit cards render this so it rolls with end_date rather than
        pinning a calendar string. If end_date is past the current
        month's statement day we advance to next month.
        """
        from calendar import monthrange
        y, m = end_date.year, end_date.month
        if end_date.day >= statement_day:
            m += 1
            if m > 12:
                m = 1
                y += 1
        # Clamp to month length (Feb / short months).
        day = min(statement_day, monthrange(y, m)[1])
        return f"{m:02d}/{day:02d}/{y}"

    def _credit_card_stretch(
        acct: str, apr: float, statement_day: int,
    ) -> dict:
        """Derive credit-card panel fields from canonical sources.

        14_day_payoff: abs(balance) + 14 * daily interest at APR.
        payment_due_date: next statement_day relative to end_date.
        ytd_interest: SUM of Interest-category transactions on the
            account this year (typically debits — interest charged).
        """
        balance = abs(_latest_balance(acct))
        daily = balance * apr / 365
        year = end_date.year
        ytd_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM transactions "
            "WHERE account_id = ? "
            "AND category = 'Interest' "
            "AND posting_date BETWEEN ? AND ?",
            (acct, f"{year}-01-01", f"{year}-12-31"),
        ).fetchone()
        ytd_interest = float(ytd_row["total"] or 0.0)
        out = {
            "14_day_payoff": f"{balance + 14 * daily:.2f}",
            "payment_due_date": _next_payment_due_date(statement_day),
            "ytd_interest": f"{ytd_interest:.2f}",
        }
        return out

    # Credit-card stretch (summit_cc is the NFCU-CC proxy).
    # Identity-only fields (cash_advance_limit / cash_advance_available /
    # date_opened) stay as synthetic stubs — they're not drift-sensitive.
    # Balance-dependent + calendar-dependent fields derive from canonical
    # sources via _credit_card_stretch so re-seeds stay coherent.
    summit_cc = {
        "cash_advance_limit": "5000.00",     # identity-only
        "cash_advance_available": "5000.00", # identity-only
        "date_opened": "01/01/2011",         # identity-only
    }
    summit_cc.update(_credit_card_stretch(
        "summit_cc", apr=0.1799, statement_day=8,
    ))
    record_loan_details(
        conn,
        account_id="summit_cc",
        details=summit_cc,
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )

    # Coastal_cc (Chase-rewards proxy). Same derivation + identity
    # pattern so the details panel isn't empty on Chase-shaped cards.
    coastal_cc = {
        "cash_advance_limit": "3000.00",
        "cash_advance_available": "3000.00",
        "date_opened": "01/01/2018",
    }
    coastal_cc.update(_credit_card_stretch(
        "coastal_cc", apr=0.2199, statement_day=15,
    ))
    record_loan_details(
        conn,
        account_id="coastal_cc",
        details=coastal_cc,
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )

    # Auto loan stretch (summit_auto). collateral_type is a categorical
    # label describing the loan, not the specific asset — safe to stay
    # in the loan KV. Vehicle identity (vin / make / model / year /
    # gap / purchase_*) lives on vehicle_assets and is denylisted here.
    auto_stretch = {
        "collateral_type": "TITLE/LIEN - VEHICLE",
    }
    auto_stretch.update(_mortgage_stretch(
        "summit_auto", rate=0.039, origination=date(2021, 6, 1),
    ))
    record_loan_details(
        conn,
        account_id="summit_auto",
        details=auto_stretch,
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )

    # Mortgage stretch (summit_mtg). escrow_balance is an identity-only
    # stub until a real connector starts scraping monthly escrow accrual.
    mtg_stretch = {
        "escrow_balance": "3420.55",
    }
    mtg_stretch.update(_mortgage_stretch(
        "summit_mtg", rate=0.0425, origination=date(2020, 9, 1),
    ))
    record_loan_details(
        conn,
        account_id="summit_mtg",
        details=mtg_stretch,
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )

    # Deposit + cash-sweep stretch — summit_chk, summit_sav, brighton_sav
    # (HYSA proxy), fidelity_brokerage (SPAXX cash). APY intentionally NOT
    # seeded here; it lives in apy_history via seed_apy_history. Interest
    # / dividends fields are derived from actual seeded transactions so
    # the panel numbers reconcile with the rows shown on Cash Flow and
    # the HYSA/SPAXX monthly walks.

    def _investment_cash_balance(acct: str) -> float:
        """Return SPAXX / money-market cash position from investment_holdings.

        For investment accounts the canonical cash figure lives in
        investment_holdings.cash_balance, not balance_snapshots (which
        tracks only bank-side debits on Fidelity and reads as $0). Use
        this path so the Details panel's Available Balance matches the
        row's displayed cash position.
        """
        from dal.investments import get_holdings
        for h in get_holdings(conn):
            if h.get("account_id") == acct:
                return float(h.get("cash_balance") or 0.0)
        return 0.0

    def _sum_interest_income(acct: str, year: int, desc_like: str | None = None) -> float:
        """Sum Interest + Investment Income credits on an account for a year."""
        clause = ""
        params: list = [acct, f"{year}-01-01", f"{year}-12-31"]
        if desc_like:
            clause = " AND description LIKE ?"
            params.append(desc_like)
        row = conn.execute(
            "SELECT COALESCE(SUM(signed_amount), 0) AS total FROM transactions "
            "WHERE account_id = ? "
            "AND category IN ('Interest', 'Investment Income') "
            "AND posting_date BETWEEN ? AND ? "
            "AND signed_amount > 0"
            f"{clause}",
            params,
        ).fetchone()
        return round(float(row["total"] or 0.0), 2)

    def _deposit_stretch(acct: str, date_opened: str,
                          direct_deposit: bool = False,
                          spaxx_only: bool = False) -> dict:
        # Pick the correct balance source: investment accounts hold cash
        # in investment_holdings, not balance_snapshots.
        balance = (
            _investment_cash_balance(acct) if spaxx_only
            else _latest_balance(acct)
        )
        year = end_date.year
        desc_like = "%SPAXX%" if spaxx_only else None
        ytd = _sum_interest_income(acct, year, desc_like)
        last_year = _sum_interest_income(acct, year - 1, desc_like)
        out = {
            "available_balance": f"{balance:.2f}",
            "dividends_ytd": f"{ytd:.2f}",
            "last_year_dividends": f"{last_year:.2f}",
            "date_opened": date_opened,
        }
        if direct_deposit:
            out["direct_deposit_enrolled"] = "Enrolled"
        return out

    # date_opened values below are SYNTHETIC 1st-of-year stubs (PR0 PII
    # scrub). They identify the account, not a real open date.
    record_loan_details(
        conn,
        account_id="summit_chk",
        details=_deposit_stretch("summit_chk", "01/01/2016", direct_deposit=True),
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )
    record_loan_details(
        conn,
        account_id="summit_sav",
        details=_deposit_stretch("summit_sav", "01/01/2016"),
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )
    record_loan_details(
        conn,
        account_id="brighton_sav",
        details=_deposit_stretch("brighton_sav", "01/01/2022"),
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )
    # Fidelity brokerage: surface SPAXX sweep yield only (exclude equity
    # dividend income so the Cash-row panel tells the cash-position story
    # without being inflated by TGT/SPG/etc. dividends).
    record_loan_details(
        conn,
        account_id="fidelity_brokerage",
        details=_deposit_stretch(
            "fidelity_brokerage", "01/01/2021", spaxx_only=True,
        ),
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )

    conn.commit()
    log.info("  loan_details stretch fields seeded across 7 accounts")


def seed_investment_details(conn, end_date: date):
    """Seed P15-T09 ``investment_details`` for the three investment accounts.

    Mirrors what each scraper would emit on a refresh:

    * **Acorns**: round-ups YTD + lifetime (account-level, fund_ticker
      NULL) plus per-ETF YTD return for the four held positions.
    * **Fidelity**: SPAXX 7-day SEC yield + per-equity YTD return for
      every position currently held in ``investment_holdings``.
    * **TSP**: per-fund YTD return + ``fund_name`` label for each
      held fund (G/F/C/S/I + L-vintages).

    Values are deterministic strings so the rendered Details panel is
    stable across re-seeds. The panel's Sparkline reuse is deferred to
    a later phase (needs ≥3 distinct ``as_of`` dates) — T09 captures
    one rolling number per refresh.
    """
    log.info("Seeding investment details (P15-T09)...")

    as_of = end_date.isoformat()

    # Wipe any previously seeded rows for clean re-runs.
    conn.execute(
        "DELETE FROM investment_details WHERE refresh_run_id = 'dummy_seed'"
    )

    # ── Acorns: round-ups (account-level) + per-ETF YTD ────────────
    record_investment_details(
        conn,
        "acorns_synthetic",
        {
            "round_up_ytd": "$48.20",
            "round_up_lifetime": "$1,250.40",
        },
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )
    acorns_etfs = {
        "VOO": "+12.4%",
        "IJH": "+8.6%",
        "IJR": "+5.1%",
        "IXUS": "+4.8%",
    }
    for ticker, ytd in acorns_etfs.items():
        record_investment_details(
            conn,
            "acorns_synthetic",
            {"ytd_return": ytd},
            fund_ticker=ticker,
            as_of=as_of,
            refresh_run_id="dummy_seed",
        )

    # ── Fidelity: SPAXX SEC yield + per-equity YTD ─────────────────
    record_investment_details(
        conn,
        "fidelity_brokerage",
        {"sec_yield": "4.32%"},
        fund_ticker="SPAXX",
        as_of=as_of,
        refresh_run_id="dummy_seed",
    )
    fidelity_equities = {
        "AAPL": "+18.2%",
        "AMZN": "+22.1%",
        "GOOG": "+9.4%",
        "MSFT": "+15.7%",
        "QQQM": "+13.5%",
        "SBUX": "-3.2%",
        "SPG": "+6.0%",
        "TGT": "-8.1%",
    }
    for ticker, ytd in fidelity_equities.items():
        record_investment_details(
            conn,
            "fidelity_brokerage",
            {"ytd_return": ytd},
            fund_ticker=ticker,
            as_of=as_of,
            refresh_run_id="dummy_seed",
        )

    # ── TSP: per-fund YTD + fund_name labels ───────────────────────
    tsp_funds = {
        "TSP_C": ("+12.40%", "C Fund"),
        "TSP_S": ("+8.10%", "S Fund"),
        "TSP_L2065": ("+9.85%", "L 2065"),
    }
    for ticker, (ytd, name) in tsp_funds.items():
        record_investment_details(
            conn,
            "tsp_synthetic",
            {"ytd_return": ytd, "fund_name": name},
            fund_ticker=ticker,
            as_of=as_of,
            refresh_run_id="dummy_seed",
        )

    conn.commit()
    log.info(
        "  investment_details seeded: 2 account-level + %d fund rows",
        len(acorns_etfs) + 1 + len(fidelity_equities) + len(tsp_funds),
    )


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
    """Load real_estate.json (structural fixture: quarterly home valuations).

    ``address`` / ``purchase_price`` / ``purchase_date`` (added in v37)
    are the canonical home for property identity that used to live in
    the loan_details KV. The composer reads the latest non-null value
    per column, so we pass them on every seeded row.
    """
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
                "address": row.get("address"),
                "purchase_price": row.get("purchase_price"),
                "purchase_date": row.get("purchase_date"),
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
            linked_loan_id=row.get("linked_loan_id"),
            vin=row.get("vin"),
            gap_insurance=row.get("gap_insurance"),
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

    from dal.payroll import record_payroll_snapshot

    # Quintin — existing military pay/pension archetype.
    quintin_rows = gen.generate_payroll_snapshots(end_date, months=36)
    for row in quintin_rows:
        record_payroll_snapshot(
            conn,
            pay_period=row["pay_period"],
            source=row["source"],
            owner_id="quintin",
            gross_pay=row["gross_pay"],
            federal_tax=row["federal_tax"],
            state_tax=row["state_tax"],
            sbp_premium=row["sbp_premium"],
            health_insurance=row["health_insurance"],
            dental_vision=row["dental_vision"],
            other_deductions=row["other_deductions"],
            net_pay=row["net_pay"],
        )

    # Phase 14 Phase B — Amy W-2 archetype.
    amy_rows = gen.generate_amy_payroll_snapshots(end_date, months=36)
    for row in amy_rows:
        record_payroll_snapshot(
            conn,
            pay_period=row["pay_period"],
            source=row["source"],
            owner_id="amy",
            gross_pay=row["gross_pay"],
            federal_tax=row["federal_tax"],
            state_tax=row["state_tax"],
            sbp_premium=row["sbp_premium"],
            health_insurance=row["health_insurance"],
            dental_vision=row["dental_vision"],
            other_deductions=row["other_deductions"],
            net_pay=row["net_pay"],
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
        # Assets must seed BEFORE loan_details so that the denylist
        # check in record_loan_details (which queries vehicle_assets /
        # real_estate by linked_loan_id) sees the relationship and
        # refuses misrouted collateral-identity writes.
        seed_real_estate(conn)
        seed_vehicle_assets(conn, end_date, years)
        seed_loan_details(conn, end_date)
        seed_credit_card_rewards(conn, end_date)
        seed_loan_details_stretch(conn, end_date)
        seed_apy_history(conn, end_date, years)
        seed_investment_details(conn, end_date)
        seed_credit_scores(conn, end_date, years)
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

        # Single-source-of-truth invariants. The DAL denylist catches
        # new writes; this assert protects against legacy rows that
        # might have survived a partial re-seed.
        from dal.balances import COLLATERAL_FIELDS
        placeholders = ",".join("?" * len(COLLATERAL_FIELDS))
        bad_collateral = conn.execute(
            f"""SELECT ld.account_id, ld.field_name, ld.field_value
               FROM loan_details ld
               WHERE ld.field_name IN ({placeholders})
                 AND (
                   EXISTS (SELECT 1 FROM vehicle_assets v
                           WHERE v.linked_loan_id = ld.account_id)
                   OR
                   EXISTS (SELECT 1 FROM real_estate r
                           WHERE r.linked_loan_id = ld.account_id)
                 )
               LIMIT 5""",
            tuple(sorted(COLLATERAL_FIELDS)),
        ).fetchall()
        if bad_collateral:
            raise RuntimeError(
                f"Seeder integrity check failed: {len(bad_collateral)} "
                f"collateral-identity field(s) found in loan_details for "
                f"loans with a linked asset — they belong on "
                f"vehicle_assets / real_estate. First 5: {bad_collateral}"
            )

        # Every secured loan should resolve a composer-level collateral
        # bundle. Quick smoke: any loan with a linked asset but no
        # resolvable vehicle row AND no resolvable real_estate row is
        # an orphaned link.
        orphans = conn.execute(
            """SELECT a.id FROM accounts a
               WHERE a.type IN ('loan', 'mortgage')
                 AND EXISTS (SELECT 1 FROM loan_details ld
                             WHERE ld.account_id = a.id)
                 AND NOT EXISTS (SELECT 1 FROM vehicle_assets v
                                 WHERE v.linked_loan_id = a.id)
                 AND NOT EXISTS (SELECT 1 FROM real_estate r
                                 WHERE r.linked_loan_id = a.id)
                 AND a.id NOT IN ('payflex_bnpl')"""
        ).fetchall()
        if orphans:
            raise RuntimeError(
                f"Seeder integrity check failed: loan(s) have "
                f"loan_details but no linked asset — {[r['id'] for r in orphans]}. "
                f"Either link an asset or add the account_id to the "
                f"unsecured-loan allowlist in this check."
            )

        # Credit-card payment_due_date must be in the future relative
        # to the seeder's end_date — otherwise the UI shows "Past Due"
        # the moment it loads. The derivation helper enforces this;
        # this assert protects against a regression that reintroduces
        # a pinned calendar string.
        from datetime import date as _date
        end_date_iso = _date.today().isoformat()  # fallback only
        # Re-parse the argparse end_date from the runtime; main() scoped
        # it but we are in the verification block. We can recover it by
        # looking at the most recent balance_snapshots.as_of.
        latest_row = conn.execute(
            "SELECT MAX(as_of) AS latest FROM balance_snapshots"
        ).fetchone()
        if latest_row and latest_row["latest"]:
            end_date_iso = latest_row["latest"][:10]
        stale_due = conn.execute(
            """SELECT ld.account_id, ld.field_value
               FROM loan_details ld
               JOIN accounts a ON a.id = ld.account_id
               WHERE ld.field_name = 'payment_due_date'
                 AND a.type IN ('credit_card', 'credit')"""
        ).fetchall()
        for r in stale_due:
            # field_value is MM/DD/YYYY
            try:
                mm, dd, yyyy = r["field_value"].split("/")
                due_iso = f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
            except (ValueError, AttributeError):
                raise RuntimeError(
                    f"Seeder integrity check failed: unparseable "
                    f"payment_due_date {r['field_value']!r} on {r['account_id']}"
                )
            if due_iso < end_date_iso:
                raise RuntimeError(
                    f"Seeder integrity check failed: payment_due_date "
                    f"{r['field_value']} on {r['account_id']} is BEFORE "
                    f"end_date {end_date_iso} — did a regression pin a "
                    f"calendar string again?"
                )

        log.info("")
        log.info("  Integrity checks passed (snapshots unique, "
                 "liabilities non-positive, no collateral drift, "
                 "no orphaned secured loans, no stale due dates)")


if __name__ == "__main__":
    main()
