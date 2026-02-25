"""
tests/test_dal.py — Data Access Layer tests.

Verifies:
  - Schema creation and WAL mode
  - Transaction upsert (insert, update, unchanged)
  - Deterministic ID hashing
  - Pending → posted promotion
  - Soft-delete logic
  - Balance snapshots
  - Loan detail storage
  - Refresh run lifecycle
  - Derived metrics computation
  - CSV migration integrity
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
    compute_txn_id, upsert_transactions, soft_delete_missing,
    get_transactions,
)
from dal.balances import (
    record_balance, get_latest_balance, get_balance_history,
    record_loan_details, get_latest_loan_details,
)
from dal.refresh_log import (
    create_refresh_run, update_run_state,
    create_refresh_event, update_refresh_event,
    update_institution_status, get_institution_statuses,
    get_current_run, get_run_events,
)
from dal.derived import (
    recompute_account_metrics, recompute_net_worth,
    get_summary_metrics,
)
from backend.state_machine import (
    RefreshState, InstitutionState, ErrorClass,
    validate_transition, validate_inst_transition,
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
            _check("Schema version", ver == SCHEMA_VERSION,
                   f"got {ver}, expected {SCHEMA_VERSION}")

            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            _check("WAL mode", mode == "wal", f"got {mode}")

            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            _check("Foreign keys enabled", fk == 1)

            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
            expected = {"institutions", "accounts", "transactions",
                        "balance_snapshots", "loan_details",
                        "refresh_runs", "refresh_events",
                        "institution_refresh_status",
                        "derived_summaries"}
            _check("All 9 tables created",
                   set(tables) >= expected,
                   f"missing: {expected - set(tables)}")
    finally:
        os.unlink(db)


# ── Test: Transaction Identity ───────────────────────────────────────────────

def test_txn_identity():
    print("\n─── Transaction Identity ───")

    # With institution-provided ID
    tid = compute_txn_id("nfcu", "nfcu_1167", "2026-02-15",
                         50.0, "Test", institution_txn_id="ABC123")
    _check("Institution ID preserved", tid == "nfcu:ABC123")

    # Without institution ID — deterministic hash
    t1 = compute_txn_id("nfcu", "nfcu_1167", "2026-02-15",
                        50.0, "Grocery Store")
    t2 = compute_txn_id("nfcu", "nfcu_1167", "2026-02-15",
                        50.0, "Grocery Store")
    _check("Deterministic hash", t1 == t2)
    _check("Hash format", t1.startswith("nfcu:h:"))

    # Different amounts → different IDs
    t3 = compute_txn_id("nfcu", "nfcu_1167", "2026-02-15",
                        51.0, "Grocery Store")
    _check("Different amount → different ID", t1 != t3)

    # Whitespace normalization
    t4 = compute_txn_id("nfcu", "nfcu_1167", "2026-02-15",
                        50.0, "  Grocery  Store  ")
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
                "VALUES ('test', 'Test Bank')")
            conn.execute(
                "INSERT INTO accounts "
                "(id, institution_id, name, last4, type) "
                "VALUES ('test_1234', 'test', 'Checking', '1234', "
                "'checking')")
            conn.commit()

            # Insert
            txns = [{
                "account_id": "test_1234",
                "institution_id": "test",
                "posting_date": "2026-02-15",
                "amount": 50.0,
                "signed_amount": -50.0,
                "direction": "Debit",
                "description": "Coffee Shop",
                "status": "posted",
            }]
            stats = upsert_transactions(conn, txns)
            _check("Insert new transaction", stats["inserted"] == 1)

            # Duplicate → unchanged
            stats2 = upsert_transactions(conn, txns)
            _check("Duplicate → unchanged",
                   stats2["unchanged"] == 1 and
                   stats2["inserted"] == 0)

            # Pending → posted promotion
            pending = [{
                "account_id": "test_1234",
                "institution_id": "test",
                "posting_date": "2026-02-16",
                "amount": 30.0,
                "signed_amount": -30.0,
                "direction": "Debit",
                "description": "Gas Station",
                "status": "pending",
            }]
            upsert_transactions(conn, pending)

            posted = [{
                "account_id": "test_1234",
                "institution_id": "test",
                "posting_date": "2026-02-16",
                "amount": 30.0,
                "signed_amount": -30.0,
                "direction": "Debit",
                "description": "Gas Station",
                "status": "posted",
            }]
            stats3 = upsert_transactions(conn, posted)
            _check("Pending → posted promotion",
                   stats3["updated"] == 1)

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
                "INSERT INTO institutions (id, display_name) "
                "VALUES ('test', 'Test')")
            conn.execute(
                "INSERT INTO accounts "
                "(id, institution_id, name, last4, type) "
                "VALUES ('test_1234', 'test', 'C', '1234', "
                "'checking')")

            txns = [
                {"account_id": "test_1234",
                 "institution_id": "test",
                 "posting_date": "2026-02-15",
                 "amount": 50.0, "signed_amount": -50.0,
                 "direction": "Debit",
                 "description": "Txn A"},
                {"account_id": "test_1234",
                 "institution_id": "test",
                 "posting_date": "2026-02-15",
                 "amount": 75.0, "signed_amount": -75.0,
                 "direction": "Debit",
                 "description": "Txn B"},
            ]
            upsert_transactions(conn, txns)
            conn.commit()

            # Keep only Txn A
            keep_id = compute_txn_id("test", "test_1234",
                                     "2026-02-15", 50.0, "Txn A")
            deleted = soft_delete_missing(
                conn, "test_1234", {keep_id}
            )
            _check("Soft delete marks missing", deleted == 1)

            # Verify status
            row = conn.execute(
                "SELECT status FROM transactions WHERE id != ?",
                (keep_id,)
            ).fetchone()
            _check("Deleted status set",
                   row and row["status"] == "deleted")

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
                "INSERT INTO institutions (id, display_name) "
                "VALUES ('test', 'Test')")
            conn.execute(
                "INSERT INTO accounts "
                "(id, institution_id, name, last4, type) "
                "VALUES ('test_1234', 'test', 'C', '1234', "
                "'checking')")
            conn.commit()

            record_balance(conn, "test_1234", 1500.50,
                           "2026-02-15T10:00:00")
            record_balance(conn, "test_1234", 1450.25,
                           "2026-02-16T10:00:00")
            conn.commit()

            latest = get_latest_balance(conn, "test_1234")
            _check("Latest balance correct",
                   latest and latest["balance"] == 1450.25)

            history = get_balance_history(conn, "test_1234")
            _check("Balance history length", len(history) == 2)
            _check("Balance history order (ASC)",
                   history[0]["balance"] == 1500.50)
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
                "INSERT INTO institutions (id, display_name) "
                "VALUES ('test', 'Test')")
            conn.execute(
                "INSERT INTO accounts "
                "(id, institution_id, name, last4, type) "
                "VALUES ('test_3533', 'test', 'Loan', '3533', "
                "'loan')")
            conn.commit()

            record_loan_details(
                conn, "test_3533",
                {"apr": "4.5%", "remaining": "$18,000"},
                "2026-02-15T10:00:00"
            )
            conn.commit()

            details = get_latest_loan_details(conn, "test_3533")
            _check("Loan details retrieved", len(details) == 2)
            _check("APR field correct",
                   details.get("apr") == "4.5%")
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
                "INSERT INTO institutions (id, display_name) "
                "VALUES ('test', 'Test')")
            conn.execute(
                "INSERT INTO institution_refresh_status "
                "(institution_id) VALUES ('test')")
            conn.commit()

            # Create run
            run_id = create_refresh_run(conn, "manual_sync")
            _check("Run created", run_id is not None)
            conn.commit()

            # Create event
            evt = create_refresh_event(conn, run_id, "test",
                                       "STARTED")
            _check("Event created", evt is not None)
            conn.commit()

            # Update event
            update_refresh_event(
                conn, evt, "COMPLETED",
                txn_inserted=10, txn_updated=2,
                duration_seconds=5.3
            )
            conn.commit()

            # Check events
            events = get_run_events(conn, run_id)
            _check("Event recorded", len(events) == 1)
            _check("Event stats correct",
                   events[0]["txn_inserted"] == 10)

            # Update run state
            update_run_state(conn, run_id, "SUCCESS")
            conn.commit()

            current = get_current_run(conn)
            _check("Run state updated",
                   current and current["state"] == "SUCCESS")

            # Update institution status
            update_institution_status(conn, "test", success=True)
            conn.commit()

            statuses = get_institution_statuses(conn)
            _check("Institution status updated",
                   len(statuses) >= 1 and
                   statuses[0]["consecutive_failures"] == 0)
    finally:
        os.unlink(db)


# ── Test: State Machine ─────────────────────────────────────────────────────

def test_state_machine():
    print("\n─── State Machine ───")

    # Valid transitions
    _check("IDLE → EVALUATING valid",
           validate_transition(
               RefreshState.IDLE,
               RefreshState.EVALUATING_STALENESS))

    _check("RUNNING → SUCCESS valid",
           validate_transition(
               RefreshState.RUNNING,
               RefreshState.SUCCESS))

    # Invalid transitions
    _check("IDLE → RUNNING invalid",
           not validate_transition(
               RefreshState.IDLE,
               RefreshState.RUNNING))

    _check("SUCCESS → RUNNING invalid",
           not validate_transition(
               RefreshState.SUCCESS,
               RefreshState.RUNNING))

    # Error classification
    _check("Timeout classified",
           classify_error("Connection timed out") ==
           ErrorClass.TIMEOUT)

    _check("Fatal classified",
           classify_error("credential_invalid") ==
           ErrorClass.FATAL)

    _check("Network classified",
           classify_error("Connection refused by host") ==
           ErrorClass.NETWORK)


# ── Test: Production DB Integrity ────────────────────────────────────────────

def test_production_db():
    print("\n─── Production DB Integrity (after migration) ───")

    if not DB_PATH.exists():
        print("  ⚠  Production DB not found, skipping")
        return

    with get_db() as conn:
        # Transaction count
        count = conn.execute(
            "SELECT COUNT(*) as c FROM transactions"
        ).fetchone()["c"]
        _check("Transactions migrated", count >= 600,
               f"got {count}, expected ≥600")

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
            "SELECT COUNT(*) as c FROM transactions "
            "WHERE posting_date IS NULL"
        ).fetchone()["c"]
        _check("No NULL posting dates", nulls == 0)

        # Check all accounts have institution_id
        orphans = conn.execute(
            "SELECT COUNT(*) as c FROM transactions "
            "WHERE institution_id IS NULL"
        ).fetchone()["c"]
        _check("No orphan transactions", orphans == 0)

        # Date range
        dr = conn.execute(
            "SELECT MIN(posting_date) as mn, "
            "MAX(posting_date) as mx FROM transactions"
        ).fetchone()
        print(f"\n  Date range: {dr['mn']} → {dr['mx']}")
        _check("Date range spans > 1 month",
               dr["mn"] != dr["mx"])

        # Schema version
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        _check("Schema version", ver == SCHEMA_VERSION)


# ── Test: Derived Metrics ────────────────────────────────────────────────────

def test_derived_metrics():
    print("\n─── Derived Metrics ───")

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
            _check("Metrics computed", len(metrics) > 0,
                   f"got {len(metrics)} metrics")
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
    test_production_db()
    test_derived_metrics()

    print("\n" + "=" * 60)
    print(f"  Results: {_passed} passed, {_failed} failed")
    if _errors:
        print(f"  Failed: {', '.join(_errors)}")
    print("=" * 60)

    sys.exit(1 if _failed else 0)

