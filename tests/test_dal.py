"""
tests/test_dal.py — Data Access Layer tests.

Unit tests (safe for CI):
  All schema/upsert/balance/loan/refresh/state-machine tests spin up a
  temporary file-based SQLite DB via tempfile.mkstemp() and delete it
  in the finally block.  They NEVER touch data/sentry.db.

Integration tests (read-only, skipped if DB absent):
  test_production_db() and test_derived_metrics() open data/sentry.db
  in the default get_db() context.  They issue only SELECT queries and
  recompute derived_summaries (idempotent).  They are intentionally
  excluded from automated CI and must be run manually.
"""

import sqlite3
import tempfile
import os
import sys
from pathlib import Path

# Add project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db, DB_PATH, SCHEMA_VERSION
from dal.transactions import (
    compute_txn_id,
    upsert_transactions,
    soft_delete_missing,
    get_transactions,
)
from dal.balances import (
    record_balance,
    get_latest_balance,
    get_balance_history,
    record_loan_details,
    get_latest_loan_details,
)
from dal.refresh_log import (
    create_refresh_run,
    update_run_state,
    create_refresh_event,
    update_refresh_event,
    update_institution_status,
    get_institution_statuses,
    get_current_run,
    get_run_events,
)
from dal.derived import (
    recompute_account_metrics,
    recompute_net_worth,
    get_summary_metrics,
)
from dal.owners import (
    create_owner,
    list_owners,
    assign_account_owner,
    get_account_owner,
    resolve_account_ids_for_view,
)
from dal.categorization import (
    categorize,
    set_user_override,
    get_user_override,
    backfill_uncategorized,
    reload_rules,
)
from dal.recurring import (
    normalize_merchant,
    classify_frequency,
    detect_recurring,
    get_recurring,
    dismiss_recurring,
    reactivate_recurring,
    get_monthly_recurring_total,
)
from dal.budgets import (
    get_defaults as budget_get_defaults,
    get_budget,
    set_budget_target,
    initialize_month as budget_initialize_month,
    get_budget_vs_actual,
    get_budget_summary,
    reload_config as budget_reload_config,
)
from dal.bills import (
    get_upcoming_bills,
    get_overdue_bills,
    get_bills_summary,
)
from backend.state_machine import (
    RefreshState,
    InstitutionState,
    ErrorClass,
    validate_transition,
    validate_inst_transition,
    classify_error,
)


def _temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


# ── Counters ─────────────────────────────────────────────────────────────────
_passed = 0
_failed = 0
_errors = []


def _check(name: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✔  {name}")
    else:
        _failed += 1
        msg = f"  ✗  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        _errors.append(name)


# ── Test: Schema + WAL ───────────────────────────────────────────────────────


def test_schema():
    print("\n─── Schema + WAL ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            ver = conn.execute("PRAGMA user_version").fetchone()[0]
            _check(
                "Schema version",
                ver == SCHEMA_VERSION,
                f"got {ver}, expected {SCHEMA_VERSION}",
            )

            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            _check("WAL mode", mode == "wal", f"got {mode}")

            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            _check("Foreign keys enabled", fk == 1)

            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            expected = {
                "institutions",
                "accounts",
                "transactions",
                "balance_snapshots",
                "loan_details",
                "refresh_runs",
                "refresh_events",
                "institution_refresh_status",
                "derived_summaries",
                "portfolio_snapshots",
                "positions_ledger",
                "investment_holdings",
                "real_estate",
                "owners",
                "category_overrides",
                "recurring_transactions",
                "recurring_mutations",
                "budgets",
            }
            _check(
                "All 18 tables created",
                set(tables) >= expected,
                f"missing: {expected - set(tables)}",
            )
    finally:
        os.unlink(db)


# ── Test: Transaction Identity ───────────────────────────────────────────────


def test_txn_identity():
    print("\n─── Transaction Identity ───")

    # With institution-provided ID
    tid = compute_txn_id(
        "nfcu", "nfcu_REDACTED", "2026-02-15", 50.0, "Test", institution_txn_id="ABC123"
    )
    _check("Institution ID preserved", tid == "nfcu:ABC123")

    # Without institution ID — deterministic hash
    t1 = compute_txn_id("nfcu", "nfcu_REDACTED", "2026-02-15", 50.0, "Grocery Store")
    t2 = compute_txn_id("nfcu", "nfcu_REDACTED", "2026-02-15", 50.0, "Grocery Store")
    _check("Deterministic hash", t1 == t2)
    _check("Hash format", t1.startswith("nfcu:h:"))

    # Different amounts → different IDs
    t3 = compute_txn_id("nfcu", "nfcu_REDACTED", "2026-02-15", 51.0, "Grocery Store")
    _check("Different amount → different ID", t1 != t3)

    # Whitespace normalization
    t4 = compute_txn_id("nfcu", "nfcu_REDACTED", "2026-02-15", 50.0, "  Grocery  Store  ")
    _check("Whitespace normalization", t1 == t4)


# ── Test: Upsert Logic ──────────────────────────────────────────────────────


def test_upsert():
    print("\n─── Upsert Logic ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            # Seed test institution + account
            conn.execute(
                "INSERT INTO institutions (id, display_name) "
                "VALUES ('test', 'Test Bank')"
            )
            conn.execute(
                "INSERT INTO accounts "
                "(id, institution_id, name, last4, type) "
                "VALUES ('test_1234', 'test', 'Checking', '1234', "
                "'checking')"
            )
            conn.commit()

            # Insert
            txns = [
                {
                    "account_id": "test_1234",
                    "institution_id": "test",
                    "posting_date": "2026-02-15",
                    "amount": 50.0,
                    "signed_amount": -50.0,
                    "direction": "Debit",
                    "description": "Coffee Shop",
                    "status": "posted",
                }
            ]
            stats = upsert_transactions(conn, txns)
            _check("Insert new transaction", stats["inserted"] == 1)

            # Duplicate → unchanged
            stats2 = upsert_transactions(conn, txns)
            _check(
                "Duplicate → unchanged",
                stats2["unchanged"] == 1 and stats2["inserted"] == 0,
            )

            # Pending → posted promotion
            pending = [
                {
                    "account_id": "test_1234",
                    "institution_id": "test",
                    "posting_date": "2026-02-16",
                    "amount": 30.0,
                    "signed_amount": -30.0,
                    "direction": "Debit",
                    "description": "Gas Station",
                    "status": "pending",
                }
            ]
            upsert_transactions(conn, pending)

            posted = [
                {
                    "account_id": "test_1234",
                    "institution_id": "test",
                    "posting_date": "2026-02-16",
                    "amount": 30.0,
                    "signed_amount": -30.0,
                    "direction": "Debit",
                    "description": "Gas Station",
                    "status": "posted",
                }
            ]
            stats3 = upsert_transactions(conn, posted)
            _check("Pending → posted promotion", stats3["updated"] == 1)

            # Query
            results = get_transactions(conn, account_id="test_1234")
            _check("Query returns transactions", len(results) == 2)

            conn.commit()
    finally:
        os.unlink(db)


# ── Test: Soft Delete ────────────────────────────────────────────────────────


def test_soft_delete():
    print("\n─── Soft Delete ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO institutions (id, display_name) VALUES ('test', 'Test')"
            )
            conn.execute(
                "INSERT INTO accounts "
                "(id, institution_id, name, last4, type) "
                "VALUES ('test_1234', 'test', 'C', '1234', "
                "'checking')"
            )

            txns = [
                {
                    "account_id": "test_1234",
                    "institution_id": "test",
                    "posting_date": "2026-02-15",
                    "amount": 50.0,
                    "signed_amount": -50.0,
                    "direction": "Debit",
                    "description": "Txn A",
                },
                {
                    "account_id": "test_1234",
                    "institution_id": "test",
                    "posting_date": "2026-02-15",
                    "amount": 75.0,
                    "signed_amount": -75.0,
                    "direction": "Debit",
                    "description": "Txn B",
                },
            ]
            upsert_transactions(conn, txns)
            conn.commit()

            # Keep only Txn A
            keep_id = compute_txn_id("test", "test_1234", "2026-02-15", 50.0, "Txn A")
            deleted = soft_delete_missing(conn, "test_1234", {keep_id})
            _check("Soft delete marks missing", deleted == 1)

            # Verify status
            row = conn.execute(
                "SELECT status FROM transactions WHERE id != ?", (keep_id,)
            ).fetchone()
            _check("Deleted status set", row and row["status"] == "deleted")

            conn.commit()
    finally:
        os.unlink(db)


# ── Test: Balances ───────────────────────────────────────────────────────────


def test_balances():
    print("\n─── Balances ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO institutions (id, display_name) VALUES ('test', 'Test')"
            )
            conn.execute(
                "INSERT INTO accounts "
                "(id, institution_id, name, last4, type) "
                "VALUES ('test_1234', 'test', 'C', '1234', "
                "'checking')"
            )
            conn.commit()

            record_balance(conn, "test_1234", 1500.50, "2026-02-15T10:00:00")
            record_balance(conn, "test_1234", 1450.25, "2026-02-16T10:00:00")
            conn.commit()

            latest = get_latest_balance(conn, "test_1234")
            _check("Latest balance correct", latest and latest["balance"] == 1450.25)

            history = get_balance_history(conn, "test_1234")
            _check("Balance history length", len(history) == 2)
            _check("Balance history order (ASC)", history[0]["balance"] == 1500.50)
    finally:
        os.unlink(db)


# ── Test: Loan Details ───────────────────────────────────────────────────────


def test_loan_details():
    print("\n─── Loan Details ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO institutions (id, display_name) VALUES ('test', 'Test')"
            )
            conn.execute(
                "INSERT INTO accounts "
                "(id, institution_id, name, last4, type) "
                "VALUES ('test_3533', 'test', 'Loan', '3533', "
                "'loan')"
            )
            conn.commit()

            record_loan_details(
                conn,
                "test_3533",
                {"apr": "4.5%", "remaining": "$18,000"},
                "2026-02-15T10:00:00",
            )
            conn.commit()

            details = get_latest_loan_details(conn, "test_3533")
            _check("Loan details retrieved", len(details) == 2)
            _check("APR field correct", details.get("apr") == "4.5%")
    finally:
        os.unlink(db)


# ── Test: Refresh Logging ────────────────────────────────────────────────────


def test_refresh_log():
    print("\n─── Refresh Logging ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO institutions (id, display_name) VALUES ('test', 'Test')"
            )
            conn.execute(
                "INSERT INTO institution_refresh_status "
                "(institution_id) VALUES ('test')"
            )
            conn.commit()

            # Create run
            run_id = create_refresh_run(conn, "manual_sync")
            _check("Run created", run_id is not None)
            conn.commit()

            # Create event
            evt = create_refresh_event(conn, run_id, "test", "STARTED")
            _check("Event created", evt is not None)
            conn.commit()

            # Update event
            update_refresh_event(
                conn,
                evt,
                "COMPLETED",
                txn_inserted=10,
                txn_updated=2,
                duration_seconds=5.3,
            )
            conn.commit()

            # Check events
            events = get_run_events(conn, run_id)
            _check("Event recorded", len(events) == 1)
            _check("Event stats correct", events[0]["txn_inserted"] == 10)

            # Update run state
            update_run_state(conn, run_id, "SUCCESS")
            conn.commit()

            current = get_current_run(conn)
            _check("Run state updated", current and current["state"] == "SUCCESS")

            # Update institution status
            update_institution_status(conn, "test", success=True)
            conn.commit()

            statuses = get_institution_statuses(conn)
            _check(
                "Institution status updated",
                len(statuses) >= 1 and statuses[0]["consecutive_failures"] == 0,
            )
    finally:
        os.unlink(db)


# ── Test: State Machine ─────────────────────────────────────────────────────


def test_state_machine():
    print("\n─── State Machine ───")

    # Valid transitions
    _check(
        "IDLE → EVALUATING valid",
        validate_transition(RefreshState.IDLE, RefreshState.EVALUATING_STALENESS),
    )

    _check(
        "RUNNING → SUCCESS valid",
        validate_transition(RefreshState.RUNNING, RefreshState.SUCCESS),
    )

    # Invalid transitions
    _check(
        "IDLE → RUNNING invalid",
        not validate_transition(RefreshState.IDLE, RefreshState.RUNNING),
    )

    _check(
        "SUCCESS → RUNNING invalid",
        not validate_transition(RefreshState.SUCCESS, RefreshState.RUNNING),
    )

    # Error classification
    _check(
        "Timeout classified",
        classify_error("Connection timed out") == ErrorClass.TIMEOUT,
    )

    _check("Fatal classified", classify_error("credential_invalid") == ErrorClass.FATAL)

    _check(
        "Network classified",
        classify_error("Connection refused by host") == ErrorClass.NETWORK,
    )


# ── Test: Ownership ─────────────────────────────────────────────────────────


def test_ownership():
    print("\n─── Ownership ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            # V5 schema: owners table exists
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name = 'owners'"
                ).fetchall()
            ]
            _check("owners table exists", "owners" in tables)

            # V5 schema: owner_id column on accounts
            acct_cols = [
                r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()
            ]
            _check("owner_id column on accounts", "owner_id" in acct_cols)

            # Create owners
            create_owner(conn, "alice", "Alice")
            create_owner(conn, "bob", "Bob")
            conn.commit()

            owners = list_owners(conn)
            _check("Two owners created", len(owners) == 2)
            _check(
                "Owner names correct",
                {o["id"] for o in owners} == {"alice", "bob"},
            )

            # Idempotent insert
            create_owner(conn, "alice", "Alice")
            conn.commit()
            owners2 = list_owners(conn)
            _check("Idempotent owner insert", len(owners2) == 2)

            # Seed test institution + accounts
            conn.execute(
                "INSERT INTO institutions (id, display_name) "
                "VALUES ('test', 'Test Bank')"
            )
            conn.execute(
                "INSERT INTO accounts "
                "(id, institution_id, name, last4, type) "
                "VALUES ('test_1111', 'test', 'Alice Checking', '1111', 'checking')"
            )
            conn.execute(
                "INSERT INTO accounts "
                "(id, institution_id, name, last4, type) "
                "VALUES ('test_2222', 'test', 'Bob Savings', '2222', 'savings')"
            )
            conn.execute(
                "INSERT INTO accounts "
                "(id, institution_id, name, last4, type) "
                "VALUES ('test_3333', 'test', 'Joint Checking', '3333', 'checking')"
            )
            conn.commit()

            # Assign owners
            assign_account_owner(conn, "test_1111", "alice")
            assign_account_owner(conn, "test_2222", "bob")
            # test_3333 stays NULL (shared / "ours")
            conn.commit()

            # Verify assignments
            _check("Alice's account assigned", get_account_owner(conn, "test_1111") == "alice")
            _check("Bob's account assigned", get_account_owner(conn, "test_2222") == "bob")
            _check("Shared account is NULL", get_account_owner(conn, "test_3333") is None)

            # View resolution: "ours" returns None (no filter)
            ours_ids = resolve_account_ids_for_view(conn, "ours")
            _check("'ours' view returns None (no filter)", ours_ids is None)

            # Temporarily patch the primary_owner for testing
            import dal.owners as owners_mod
            original_cache = owners_mod._config_cache
            owners_mod._config_cache = {"primary_owner": "alice", "owners": []}

            try:
                # View resolution: "mine" (alice) = alice's account + shared
                mine_ids = resolve_account_ids_for_view(conn, "mine")
                _check(
                    "'mine' view includes alice + shared",
                    mine_ids is not None and
                    "test_1111" in mine_ids and
                    "test_3333" in mine_ids and
                    "test_2222" not in mine_ids,
                    f"got {mine_ids}",
                )

                # View resolution: "theirs" = bob's account + shared
                theirs_ids = resolve_account_ids_for_view(conn, "theirs")
                _check(
                    "'theirs' view includes bob + shared",
                    theirs_ids is not None and
                    "test_2222" in theirs_ids and
                    "test_3333" in theirs_ids and
                    "test_1111" not in theirs_ids,
                    f"got {theirs_ids}",
                )
            finally:
                # Restore original config
                owners_mod._config_cache = original_cache

            # Clear owner (back to shared)
            assign_account_owner(conn, "test_1111", None)
            conn.commit()
            _check("Owner cleared to shared", get_account_owner(conn, "test_1111") is None)

    finally:
        os.unlink(db)


# ── Test: Categorization ───────────────────────────────────────────────────


def test_categorization():
    print("\n─── Categorization ───")
    db = _temp_db()
    try:
        # Ensure rules are loaded
        reload_rules()

        # Layer 2: Keyword matching
        _check(
            "Kroger → Groceries",
            categorize("KROGER #330 BLOOMINGTON") == "Groceries",
            f"got {categorize('KROGER #330 BLOOMINGTON')}",
        )
        _check(
            "DFAS → Paychecks/Salary",
            categorize("DFAS-CLEVELAND   RET ALT") == "Paychecks/Salary",
            f"got {categorize('DFAS-CLEVELAND   RET ALT')}",
        )
        _check(
            "Amazon → General Merchandise",
            categorize("AMZN Mktp US*S34C22SD3 Amzn.com/billWA") == "General Merchandise",
            f"got {categorize('AMZN Mktp US*S34C22SD3 Amzn.com/billWA')}",
        )
        _check(
            "DoorDash → Restaurants/Dining",
            categorize("DD *DOORDASHDOUBLE DOORDASH.COM CA") == "Restaurants/Dining",
            f"got {categorize('DD *DOORDASHDOUBLE DOORDASH.COM CA')}",
        )
        _check(
            "Shell → Gasoline/Fuel",
            categorize("SHELL OIL130212350 BLOOMINGTON IN") == "Gasoline/Fuel",
            f"got {categorize('SHELL OIL130212350 BLOOMINGTON IN')}",
        )

        # Layer 3: Bank-provided category preserved
        _check(
            "Bank category preserved",
            categorize("some unknown desc", bank_category="Loans") == "Loans",
        )

        # Bank category ignored if Uncategorized
        _check(
            "Uncategorized bank cat falls through",
            categorize("KROGER #330", bank_category="Uncategorized") == "Groceries",
        )

        # Layer 4: Fallback
        _check(
            "Unknown → Uncategorized",
            categorize("totally unknown merchant xyz") == "Uncategorized",
        )

        # User overrides with DB
        init_db(db)
        with get_db(db) as conn:
            # Seed institution + account + transaction
            conn.execute(
                "INSERT INTO institutions (id, display_name) "
                "VALUES ('test', 'Test Bank')"
            )
            conn.execute(
                "INSERT INTO accounts (id, institution_id, name, last4, type) "
                "VALUES ('test_9999', 'test', 'Test Acct', '9999', 'checking')"
            )
            conn.execute(
                "INSERT INTO transactions (id, account_id, institution_id, "
                "posting_date, amount, signed_amount, direction, description, "
                "category, status, created_at, updated_at) "
                "VALUES ('txn_test_1', 'test_9999', 'test', '2026-01-01', "
                "50.0, -50.0, 'Debit', 'KROGER #330', 'Groceries', "
                "'posted', datetime('now'), datetime('now'))"
            )
            conn.commit()

            # Layer 1: User override wins over keyword match
            set_user_override(conn, "txn_test_1", "Personal Care")
            conn.commit()

            override = get_user_override(conn, "txn_test_1")
            _check("User override stored", override == "Personal Care")

            result = categorize(
                "KROGER #330", conn=conn, txn_id="txn_test_1"
            )
            _check(
                "User override wins over keyword",
                result == "Personal Care",
                f"got {result}",
            )

            # Backfill test
            conn.execute(
                "INSERT INTO transactions (id, account_id, institution_id, "
                "posting_date, amount, signed_amount, direction, description, "
                "category, status, created_at, updated_at) "
                "VALUES ('txn_test_2', 'test_9999', 'test', '2026-01-02', "
                "30.0, -30.0, 'Debit', 'SHELL OIL STATION', 'Uncategorized', "
                "'posted', datetime('now'), datetime('now'))"
            )
            conn.execute(
                "INSERT INTO transactions (id, account_id, institution_id, "
                "posting_date, amount, signed_amount, direction, description, "
                "category, status, created_at, updated_at) "
                "VALUES ('txn_test_3', 'test_9999', 'test', '2026-01-03', "
                "99.0, -99.0, 'Debit', 'mystery vendor abc', 'nan', "
                "'posted', datetime('now'), datetime('now'))"
            )
            conn.commit()

            stats = backfill_uncategorized(conn)
            _check("Backfill matched some", stats["matched"] >= 1)
            _check("Backfill cleaned nan", stats["cleaned_nan"] >= 1)

            # Verify the Shell transaction got categorized
            cat = conn.execute(
                "SELECT category FROM transactions WHERE id = 'txn_test_2'"
            ).fetchone()["category"]
            _check(
                "Backfill: Shell → Gasoline/Fuel",
                cat == "Gasoline/Fuel",
                f"got {cat}",
            )

    finally:
        os.unlink(db)


# ── Test: Recurring Transaction Detection ─────────────────────────────────


def test_recurring():
    print("\n─── Recurring Detection ───")
    db = _temp_db()
    try:
        init_db(db)

        # Test merchant normalization
        _check(
            "Normalize strips card suffix",
            "amazon" in normalize_merchant("AMZN Mktp US*S34C22SD3 Amzn.com/billWA"),
        )
        _check(
            "Normalize strips DEBIT-DC prefix",
            "debit-dc" not in normalize_merchant("DEBIT-DC 0483 KROGER #330 BLOOMINGTON IN"),
        )

        # Test frequency classification
        _check("Weekly classified", classify_frequency(7) == "weekly")
        _check("Monthly classified", classify_frequency(30) == "monthly")
        _check("Quarterly classified", classify_frequency(90) == "quarterly")
        _check("Irregular returns None", classify_frequency(45) is None)

        with get_db(db) as conn:
            # Seed institution + account
            conn.execute(
                "INSERT INTO institutions (id, display_name) "
                "VALUES ('test', 'Test Bank')"
            )
            conn.execute(
                "INSERT INTO accounts (id, institution_id, name, last4, type) "
                "VALUES ('test_9999', 'test', 'Test Acct', '9999', 'checking')"
            )

            # Create a monthly recurring pattern (Netflix-like)
            for i in range(6):
                month = i + 1
                date = f"2026-{month:02d}-15"
                conn.execute(
                    "INSERT INTO transactions "
                    "(id, account_id, institution_id, posting_date, amount, "
                    "signed_amount, direction, description, category, status, "
                    "created_at, updated_at) "
                    "VALUES (?, 'test_9999', 'test', ?, 15.99, -15.99, "
                    "'Debit', 'NETFLIX.COM 866-5797172 CA', "
                    "'Dues and Subscriptions', 'posted', "
                    "datetime('now'), datetime('now'))",
                    (f"txn_netflix_{i}", date),
                )

            # Create another pattern with varying amounts (groceries)
            for i in range(4):
                month = i + 1
                date = f"2026-{month:02d}-10"
                amt = 50.0 + (i * 10)  # 50, 60, 70, 80
                conn.execute(
                    "INSERT INTO transactions "
                    "(id, account_id, institution_id, posting_date, amount, "
                    "signed_amount, direction, description, category, status, "
                    "created_at, updated_at) "
                    "VALUES (?, 'test_9999', 'test', ?, ?, ?, "
                    "'Debit', 'KROGER #330 BLOOMINGTON IN', "
                    "'Groceries', 'posted', "
                    "datetime('now'), datetime('now'))",
                    (f"txn_kroger_{i}", date, amt, -amt),
                )
            conn.commit()

            # Run detection
            stats = detect_recurring(conn)
            _check("Detection created entries", stats["created"] >= 1)

            # Check active recurring
            active = get_recurring(conn, status="active")
            _check("Active recurring found", len(active) >= 1)

            # Find the Netflix entry
            netflix = [r for r in active if "netflix" in r["merchant"]]
            _check("Netflix detected", len(netflix) == 1)
            if netflix:
                _check(
                    "Netflix is monthly",
                    netflix[0]["frequency"] == "monthly",
                    f"got {netflix[0]['frequency']}",
                )
                _check(
                    "Netflix amount stable",
                    netflix[0]["amount_stable"] == 1,
                )

            # Test dismiss/reactivate lifecycle
            if active:
                rec_id = active[0]["id"]
                dismiss_recurring(conn, rec_id)
                conn.commit()
                dismissed = get_recurring(conn, status="dismissed")
                _check("Dismiss works", any(r["id"] == rec_id for r in dismissed))

                reactivate_recurring(conn, rec_id)
                conn.commit()
                reactivated = get_recurring(conn, status="active")
                _check("Reactivate works", any(r["id"] == rec_id for r in reactivated))

            # Monthly total
            totals = get_monthly_recurring_total(conn)
            _check("Monthly total computed", totals["total"] >= 0)

    finally:
        os.unlink(db)


# ── Test: Budgets ───────────────────────────────────────────────────────


def test_budgets():
    print("\n─── Budgets ───")
    db = _temp_db()
    try:
        init_db(db)
        budget_reload_config()

        # Defaults loaded from config
        defaults = budget_get_defaults()
        _check("Defaults loaded", len(defaults) > 10, f"got {len(defaults)}")
        _check("Groceries default exists", "Groceries" in defaults)

        with get_db(db) as conn:
            # Seed institution + account + transactions
            conn.execute(
                "INSERT INTO institutions (id, display_name) "
                "VALUES ('test', 'Test Bank')"
            )
            conn.execute(
                "INSERT INTO accounts (id, institution_id, name, last4, type) "
                "VALUES ('test_9999', 'test', 'Test Acct', '9999', 'checking')"
            )

            # Insert spending transactions for 2026-01
            conn.execute(
                "INSERT INTO transactions (id, account_id, institution_id, "
                "posting_date, amount, signed_amount, direction, description, "
                "category, status, created_at, updated_at) "
                "VALUES ('txn_b1', 'test_9999', 'test', '2026-01-05', "
                "120.0, -120.0, 'Debit', 'KROGER #330', 'Groceries', "
                "'posted', datetime('now'), datetime('now'))"
            )
            conn.execute(
                "INSERT INTO transactions (id, account_id, institution_id, "
                "posting_date, amount, signed_amount, direction, description, "
                "category, status, created_at, updated_at) "
                "VALUES ('txn_b2', 'test_9999', 'test', '2026-01-10', "
                "45.0, -45.0, 'Debit', 'DOORDASH', 'Restaurants/Dining', "
                "'posted', datetime('now'), datetime('now'))"
            )
            conn.commit()

            # Budget vs actual with defaults (no explicit budget set)
            bva = get_budget_vs_actual(conn, "2026-01")
            _check("Budget vs actual returns data", len(bva) > 0)

            # Find groceries
            grocery = [b for b in bva if b["category"] == "Groceries"]
            _check("Groceries in budget", len(grocery) == 1)
            if grocery:
                _check(
                    "Groceries actual = 120",
                    grocery[0]["actual"] == 120.0,
                    f"got {grocery[0]['actual']}",
                )
                _check(
                    "Groceries has target from defaults",
                    grocery[0]["target"] == defaults["Groceries"],
                )

            # Set a custom budget target
            set_budget_target(conn, "Groceries", "2026-01", 200.0)
            conn.commit()

            bva2 = get_budget_vs_actual(conn, "2026-01")
            grocery2 = [b for b in bva2 if b["category"] == "Groceries"]
            _check(
                "Custom target applied",
                grocery2[0]["target"] == 200.0,
                f"got {grocery2[0]['target']}" if grocery2 else "missing",
            )

            # Initialize month from defaults
            created = budget_initialize_month(conn, "2026-02")
            conn.commit()
            _check("Initialize month creates entries", created > 10)

            budget_feb = get_budget(conn, "2026-02")
            _check(
                "February budget has entries",
                len(budget_feb) > 10,
                f"got {len(budget_feb)}",
            )

            # Summary
            summary = get_budget_summary(conn, "2026-01")
            _check("Summary total_spent > 0", summary["total_spent"] > 0)
            _check("Summary has month", summary["month"] == "2026-01")

    finally:
        os.unlink(db)


# ── Test: Bill Tracking ──────────────────────────────────────────────


def test_bills():
    print("\n─── Bill Tracking ───")
    db = _temp_db()
    try:
        init_db(db)

        with get_db(db) as conn:
            # Seed institution + account
            conn.execute(
                "INSERT INTO institutions (id, display_name) "
                "VALUES ('test', 'Test Bank')"
            )
            conn.execute(
                "INSERT INTO accounts (id, institution_id, name, last4, type) "
                "VALUES ('test_9999', 'test', 'Test Acct', '9999', 'checking')"
            )

            # Insert a recurring transaction that's "due soon"
            from datetime import datetime, timedelta
            tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
            past = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
            future = (datetime.utcnow() + timedelta(days=20)).strftime("%Y-%m-%d")

            # Due tomorrow (due_soon)
            conn.execute(
                "INSERT INTO recurring_transactions "
                "(id, account_id, merchant, category, frequency, avg_interval, "
                "expected_amount, amount_stable, last_amount, last_date, "
                "next_expected, occurrence_count, status) "
                "VALUES ('rec_1', 'test_9999', 'netflix', 'Entertainment', "
                "'monthly', 30.0, 15.99, 1, 15.99, '2026-01-01', ?, 6, 'active')",
                (tomorrow,),
            )
            # Overdue
            conn.execute(
                "INSERT INTO recurring_transactions "
                "(id, account_id, merchant, category, frequency, avg_interval, "
                "expected_amount, amount_stable, last_amount, last_date, "
                "next_expected, occurrence_count, status) "
                "VALUES ('rec_2', 'test_9999', 'duke energy', 'Utilities', "
                "'monthly', 30.0, 120.00, 1, 120.00, '2025-12-01', ?, 4, 'active')",
                (past,),
            )
            # Upcoming (20 days out)
            conn.execute(
                "INSERT INTO recurring_transactions "
                "(id, account_id, merchant, category, frequency, avg_interval, "
                "expected_amount, amount_stable, last_amount, last_date, "
                "next_expected, occurrence_count, status) "
                "VALUES ('rec_3', 'test_9999', 't-mobile', 'Telephone', "
                "'monthly', 30.0, 150.00, 1, 150.00, '2026-01-01', ?, 5, 'active')",
                (future,),
            )
            conn.commit()

            # Test upcoming bills
            bills = get_upcoming_bills(conn, days=30)
            _check("Upcoming bills found", len(bills) == 3)

            due_soon = [b for b in bills if b["status"] == "due_soon"]
            _check("Due soon count", len(due_soon) == 1)

            overdue = [b for b in bills if b["status"] == "overdue"]
            _check("Overdue count", len(overdue) == 1)

            # Test overdue endpoint
            overdue_bills = get_overdue_bills(conn)
            _check("Overdue bills found", len(overdue_bills) >= 1)

            # Test summary
            summary = get_bills_summary(conn, days=30)
            _check("Summary has counts", summary["upcoming_count"] >= 0)
            _check("Summary has total", summary["total_upcoming_amount"] > 0)
            _check(
                "Summary next_bill exists",
                summary["next_bill"] is not None,
            )

    finally:
        os.unlink(db)


# ── Integration Test: Production DB Integrity ───────────────────────────────
# READ-ONLY. Opens data/sentry.db with get_db() (default path).
# Safe: only SELECT queries. Skipped automatically if DB doesn't exist.
# Do NOT run in CI — run manually: python tests/test_dal.py


def test_production_db():
    print("\n─── [INTEGRATION] Production DB Integrity (after migration) ───")

    if not DB_PATH.exists():
        print("  ⚠  Production DB not found, skipping")
        return

    with get_db() as conn:
        # Transaction count
        count = conn.execute("SELECT COUNT(*) as c FROM transactions").fetchone()["c"]
        _check("Transactions migrated", count >= 600, f"got {count}, expected ≥600")

        # Per-account check
        rows = conn.execute(
            "SELECT account_id, COUNT(*) as c "
            "FROM transactions GROUP BY account_id "
            "ORDER BY c DESC"
        ).fetchall()
        print(f"\n  Account breakdown:")
        for r in rows:
            print(f"    {r['account_id']:25s} {r['c']:5d} txns")

        _check("Multiple accounts present", len(rows) >= 4)

        # Check no NULL posting dates
        nulls = conn.execute(
            "SELECT COUNT(*) as c FROM transactions WHERE posting_date IS NULL"
        ).fetchone()["c"]
        _check("No NULL posting dates", nulls == 0)

        # Check all accounts have institution_id
        orphans = conn.execute(
            "SELECT COUNT(*) as c FROM transactions WHERE institution_id IS NULL"
        ).fetchone()["c"]
        _check("No orphan transactions", orphans == 0)

        # Date range
        dr = conn.execute(
            "SELECT MIN(posting_date) as mn, MAX(posting_date) as mx FROM transactions"
        ).fetchone()
        print(f"\n  Date range: {dr['mn']} → {dr['mx']}")
        _check("Date range spans > 1 month", dr["mn"] != dr["mx"])

        # Schema version
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        _check("Schema version", ver == SCHEMA_VERSION)


# ── Integration Test: Derived Metrics ───────────────────────────────────────
# Idempotent: recompute_account_metrics writes to derived_summaries only.
# Still only meaningful against a populated sentry.db — skip in CI.


def test_derived_metrics():
    print("\n─── [INTEGRATION] Derived Metrics ───")

    if not DB_PATH.exists():
        print("  ⚠  Production DB not found, skipping")
        return

    with get_db() as conn:
        # Get an account with data
        acct = conn.execute(
            "SELECT account_id FROM transactions "
            "GROUP BY account_id "
            "ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()

        if acct:
            account_id = acct["account_id"]
            recompute_account_metrics(conn, account_id)
            conn.commit()

            metrics = get_summary_metrics(conn)
            _check("Metrics computed", len(metrics) > 0, f"got {len(metrics)} metrics")
            print(f"    Computed for: {account_id}")
            for k, v in list(metrics.items())[:4]:
                print(f"      {k}: {v['value']:.2f}")
        else:
            _check("Metrics computed", False, "no transactions")


# ── Run All ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Sentry Finance DAL Test Suite")
    print("=" * 60)

    test_schema()
    test_txn_identity()
    test_upsert()
    test_soft_delete()
    test_balances()
    test_loan_details()
    test_refresh_log()
    test_state_machine()
    test_ownership()
    test_categorization()
    test_recurring()
    test_budgets()
    test_bills()
    test_production_db()
    test_derived_metrics()

    print("\n" + "=" * 60)
    print(f"  Results: {_passed} passed, {_failed} failed")
    if _errors:
        print(f"  Failed: {', '.join(_errors)}")
    print("=" * 60)

    sys.exit(1 if _failed else 0)
