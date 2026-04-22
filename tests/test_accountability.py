"""
tests/test_accountability.py — Phase 14 Phase D unit tests.

Locks the accountability scorecard identity and the drift-source
detectors that populate the drilldown modal. These tests construct a
hand-buildable database with exactly the rows each identity term needs,
then assert dollar-exact equality.

Test cases (per P14-T04 prompt Verification § Task 6):

  1. test_identity_reconciles_perfectly — synthetic dataset where every
     identity term is known → unexplained == 0 and accounted_for_pct == 1.0.
  2. test_miscategorize_fires_uncategorized_drift — deliberately NULL a
     transaction's category → drift source "uncategorized_transactions"
     appears with the correct magnitude.
  3. test_stale_portfolio_snapshot_fires — portfolio snapshot older than
     2 days before end_date → drift source fires reporting the age.
  4. test_missing_payroll_snapshot_fires — paycheck-shaped deposit with
     no matching payroll_snapshots row → drift source fires.
  5. test_market_loss_reconciles_with_negative_term — month with
     investment losses: identity reconciles, market_value_delta_cents < 0.
  6. test_market_gain_reconciles_with_positive_term — symmetric check
     for gains: identity reconciles, market_value_delta_cents > 0.
  7. test_owner_scoping_excludes_other_owner — owner_id=quintin excludes
     amy-owned accounts from both sides of the identity.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.owners import create_owner
from dal.reports import get_accountability


# ── Helpers ──────────────────────────────────────────────────────────────────


def _temp_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


def _seed_institutions(conn):
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) "
        "VALUES ('testbank', 'Test Bank')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) "
        "VALUES ('testbroker', 'Test Broker')"
    )


def _make_account(conn, account_id, atype, owner_id):
    create_owner(conn, owner_id, owner_id.title())
    institution = "testbroker" if atype in ("investment", "retirement") else "testbank"
    # Unique (institution_id, last4): derive a 4-digit hash of account_id
    last4 = f"{abs(hash(account_id)) % 10_000:04d}"
    conn.execute(
        """
        INSERT INTO accounts
        (id, institution_id, name, type, last4, owner_id, is_active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (account_id, institution, account_id.upper(), atype, last4, owner_id),
    )


def _insert_txn(
    conn,
    *,
    txn_id,
    account_id,
    posting_date,
    amount_dollars,
    direction,
    category,
    description="Test",
    transfer_tag=None,
):
    signed = abs(amount_dollars) if direction == "Credit" else -abs(amount_dollars)
    institution_id = conn.execute(
        "SELECT institution_id FROM accounts WHERE id = ?",
        (account_id,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO transactions
        (id, account_id, institution_id, posting_date, amount,
         signed_amount, direction, description, category, status,
         transfer_tag, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted', ?,
                datetime('now'), datetime('now'))
        """,
        (
            txn_id, account_id, institution_id, posting_date,
            abs(amount_dollars), signed, direction, description,
            category, transfer_tag,
        ),
    )


def _insert_balance_snapshot(conn, account_id, as_of, balance_dollars):
    conn.execute(
        "INSERT INTO balance_snapshots (account_id, balance, as_of) "
        "VALUES (?, ?, ?)",
        (account_id, balance_dollars, as_of),
    )


def _insert_portfolio_snapshot(conn, account_id, timestamp, total_value, cash=0.0):
    conn.execute(
        "INSERT INTO portfolio_snapshots "
        "(account_id, timestamp, total_account_value, cash_balance) "
        "VALUES (?, ?, ?, ?)",
        (account_id, timestamp, total_value, cash),
    )


# ── Test 1: identity reconciles perfectly ────────────────────────────────────


def test_identity_reconciles_perfectly():
    """Build a period where every term is known exactly and assert the
    unexplained residual is $0.

    Scenario (owner 'quintin' only; window = 2026-03-01..2026-03-31):
      - Start: checking = $10,000, investment = $50,000
      - End:   checking = $11,500 (net +$1,500), investment = $52,500 (+$2,500)
      - Cash moves:
          income $3,000 (Salary) on Mar 5
          spend  $1,500 (Groceries) on Mar 10
          net cash retained in checking = $1,500 → matches balance Δ
      - Investment moves:
          user contribution $1,000 on Mar 15 (transfer with transfer_tag)
          market gain = $1,500 (rest of the $2,500 investment Δ)
          → market_value_delta_cents = 250,000 − 100,000 = 150,000 cents
      - No RE / vehicles.
      - Identity:
          NW_Δ = (1500 + 50000 end − 10000 + 50000 start + 2500)
               = $4,000
          = income(3000) − spend(1500) + market_Δ(1500) + 0 + 0
          = $3,000
      - Hmm, doesn't balance — because the $1,000 user contribution
        comes out of checking which would reduce the $1,500 retained.
        Re-spec: income 3000, spend 1500, contribute 1000. Net cash Δ = 500.
        So checking end = 10500, not 11500.
    """
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_institutions(conn)
            _make_account(conn, "t_chk", "checking", "quintin")
            _make_account(conn, "t_inv", "investment", "quintin")

            # Start-of-window balances (snapshots at date before 2026-03-01)
            _insert_balance_snapshot(conn, "t_chk", "2026-02-28", 10000.00)
            _insert_balance_snapshot(conn, "t_inv", "2026-02-28", 0.00)
            _insert_portfolio_snapshot(
                conn, "t_inv", "2026-02-28T16:00:00", 50000.00,
            )

            # In-window activity
            _insert_txn(
                conn, txn_id="tx_inc1", account_id="t_chk",
                posting_date="2026-03-05", amount_dollars=3000.00,
                direction="Credit", category="Salary",
                description="Paycheck",
            )
            _insert_txn(
                conn, txn_id="tx_spend1", account_id="t_chk",
                posting_date="2026-03-10", amount_dollars=1500.00,
                direction="Debit", category="Groceries",
                description="Grocer",
            )
            # User contribution: transfer from checking to brokerage with
            # transfer_tag. Paired with a same-day positions_ledger row
            # (share_delta > 0) so v_investment_contributions classifies
            # this as 'user_contribution'.
            _insert_txn(
                conn, txn_id="tx_contrib_d", account_id="t_chk",
                posting_date="2026-03-15", amount_dollars=1000.00,
                direction="Debit", category="Transfers",
                description="To brokerage", transfer_tag="xfer_contrib",
            )
            _insert_txn(
                conn, txn_id="tx_contrib_c", account_id="t_inv",
                posting_date="2026-03-15", amount_dollars=1000.00,
                direction="Credit", category="Transfers",
                description="From checking", transfer_tag="xfer_contrib",
            )
            conn.execute(
                "INSERT INTO positions_ledger "
                "(account_id, timestamp, ticker, transaction_type, "
                " share_delta, new_total_shares) "
                "VALUES ('t_inv', '2026-03-15T10:00:00', 'TEST', 'BUY', 10.0, 10.0)"
            )

            # End-of-window balances: checking $10,500, investment $52,500
            # (portfolio is $52,500 of which $2,500 is market gain on top of
            # the $50k start + $1k contribution − $0 sales).
            # Wait: $50,000 start + $1,000 contribution + $1,500 gain = $52,500
            _insert_balance_snapshot(conn, "t_chk", "2026-03-31", 10500.00)
            _insert_balance_snapshot(conn, "t_inv", "2026-03-31", 0.00)
            _insert_portfolio_snapshot(
                conn, "t_inv", "2026-03-31T16:00:00", 52500.00,
            )

            conn.commit()

            result = get_accountability(
                conn, "2026-03-01", "2026-03-31", owner_id="quintin",
            )

            # NW Δ = (checking 10500 + inv 52500) − (checking 10000 + inv 50000)
            #      = 63000 − 60000 = +3000
            assert result["net_worth_start_cents"] == 6_000_000, (
                f"expected NW start $60,000 cents 6000000, got {result['net_worth_start_cents']}"
            )
            assert result["net_worth_end_cents"] == 6_300_000
            assert result["net_worth_delta_cents"] == 300_000

            # Identity terms: in = 3000, spent = 1500, market_Δ = 1500
            terms = result["identity_terms"]
            assert terms["dollars_in_cents"] == 300_000, f"got {terms}"
            assert terms["dollars_spent_cents"] == 150_000, f"got {terms}"
            # Market value Δ = (52500 − 50000) − 1000 contribution = 1500
            assert terms["market_value_delta_cents"] == 150_000, f"got {terms}"
            assert terms["real_estate_delta_cents"] == 0
            assert terms["vehicle_delta_cents"] == 0

            # Unexplained: Δ − (in − spent + market + re + veh)
            #            = 3000 − (3000 − 1500 + 1500 + 0 + 0)
            #            = 3000 − 3000 = 0
            assert result["unexplained_cents"] == 0, (
                f"expected perfect reconciliation, got unexplained={result['unexplained_cents']}"
            )
            assert result["accounted_for_pct"] == 1.0
    finally:
        os.unlink(db)


# ── Test 2: uncategorized-transactions drift fires ───────────────────────────


def test_miscategorize_fires_uncategorized_drift():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_institutions(conn)
            _make_account(conn, "t_chk", "checking", "quintin")
            _insert_balance_snapshot(conn, "t_chk", "2026-02-28", 5000.00)
            _insert_balance_snapshot(conn, "t_chk", "2026-03-31", 4500.00)

            # One uncategorized $500 debit in the window
            _insert_txn(
                conn, txn_id="tx_uncat1", account_id="t_chk",
                posting_date="2026-03-12", amount_dollars=500.00,
                direction="Debit", category=None,
                description="Mystery charge",
            )
            conn.commit()

            result = get_accountability(
                conn, "2026-03-01", "2026-03-31", owner_id="quintin",
            )
            ids = [d["id"] for d in result["drift_sources"]]
            assert "uncategorized_transactions" in ids, (
                f"expected uncategorized drift, got {ids}"
            )
            drift = next(
                d for d in result["drift_sources"]
                if d["id"] == "uncategorized_transactions"
            )
            # Magnitude: $500 → 50,000 cents
            assert drift["magnitude_cents"] == 50_000, f"got {drift}"
            assert drift["severity"] == "warning"
            assert drift["fix_action"] == "recategorize"
            assert drift["fix_payload"]["transaction_ids"] == ["tx_uncat1"]
    finally:
        os.unlink(db)


# ── Test 3: stale portfolio snapshot fires ───────────────────────────────────


def test_stale_portfolio_snapshot_fires():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_institutions(conn)
            _make_account(conn, "t_inv", "investment", "quintin")

            # Portfolio snapshot 7 days older than end date (> 2-day threshold)
            _insert_portfolio_snapshot(
                conn, "t_inv", "2026-03-24T16:00:00", 10000.00,
            )
            conn.commit()

            result = get_accountability(
                conn, "2026-03-01", "2026-03-31", owner_id="quintin",
            )
            matching = [
                d for d in result["drift_sources"]
                if d["id"].startswith("stale_portfolio_snapshot::")
            ]
            assert matching, (
                f"expected stale portfolio drift, got ids={[d['id'] for d in result['drift_sources']]}"
            )
            drift = matching[0]
            assert drift["severity"] == "warning"
            assert drift["fix_action"] == "refresh_portfolio"
            assert drift["fix_payload"]["account_id"] == "t_inv"
            assert "7 days older" in drift["label"], f"got label={drift['label']!r}"
    finally:
        os.unlink(db)


# ── Test 4: missing payroll snapshot fires ───────────────────────────────────


def test_missing_payroll_snapshot_fires():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_institutions(conn)
            _make_account(conn, "t_chk", "checking", "quintin")

            # Paycheck-shaped deposit (Pension category) but NO
            # payroll_snapshots row. Drift should fire.
            _insert_txn(
                conn, txn_id="tx_pen1", account_id="t_chk",
                posting_date="2026-03-01", amount_dollars=4000.00,
                direction="Credit", category="Pension",
                description="Military Retired Pay",
            )
            _insert_balance_snapshot(conn, "t_chk", "2026-02-28", 1000.00)
            _insert_balance_snapshot(conn, "t_chk", "2026-03-31", 5000.00)
            conn.commit()

            result = get_accountability(
                conn, "2026-03-01", "2026-03-31", owner_id="quintin",
            )
            ids = [d["id"] for d in result["drift_sources"]]
            assert "missing_payroll_snapshot" in ids, (
                f"expected missing_payroll_snapshot, got {ids}"
            )
            drift = next(
                d for d in result["drift_sources"]
                if d["id"] == "missing_payroll_snapshot"
            )
            assert drift["severity"] == "warning"
            assert drift["fix_action"] == "upload_ras"
            assert "2026-03" in drift["fix_payload"]["missing_months"]
    finally:
        os.unlink(db)


# ── Test 5: market loss produces negative market_value_delta ─────────────────


def test_market_loss_reconciles_with_negative_term():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_institutions(conn)
            _make_account(conn, "t_inv", "investment", "quintin")
            # No banking activity — pure market move.
            _insert_portfolio_snapshot(
                conn, "t_inv", "2026-02-28T16:00:00", 20000.00,
            )
            _insert_portfolio_snapshot(
                conn, "t_inv", "2026-03-31T16:00:00", 18500.00,  # −$1,500
            )
            conn.commit()

            result = get_accountability(
                conn, "2026-03-01", "2026-03-31", owner_id="quintin",
            )
            terms = result["identity_terms"]
            assert terms["market_value_delta_cents"] == -150_000, (
                f"expected −$1,500 market delta, got {terms}"
            )
            # Identity: Δ(−1500) = in(0) − spent(0) + market(−1500) + … + unexplained(0)
            assert result["net_worth_delta_cents"] == -150_000
            assert result["unexplained_cents"] == 0
            assert result["accounted_for_pct"] == 1.0
    finally:
        os.unlink(db)


# ── Test 6: market gain produces positive market_value_delta ─────────────────


def test_market_gain_reconciles_with_positive_term():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_institutions(conn)
            _make_account(conn, "t_inv", "investment", "quintin")
            _insert_portfolio_snapshot(
                conn, "t_inv", "2026-02-28T16:00:00", 20000.00,
            )
            _insert_portfolio_snapshot(
                conn, "t_inv", "2026-03-31T16:00:00", 22300.00,  # +$2,300
            )
            conn.commit()

            result = get_accountability(
                conn, "2026-03-01", "2026-03-31", owner_id="quintin",
            )
            terms = result["identity_terms"]
            assert terms["market_value_delta_cents"] == 230_000, (
                f"expected +$2,300 market delta, got {terms}"
            )
            assert result["net_worth_delta_cents"] == 230_000
            assert result["unexplained_cents"] == 0
            assert result["accounted_for_pct"] == 1.0
    finally:
        os.unlink(db)


# ── Test 7: owner scoping excludes other owner ───────────────────────────────


def test_owner_scoping_excludes_other_owner():
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_institutions(conn)
            _make_account(conn, "t_q_chk", "checking", "quintin")
            _make_account(conn, "t_a_chk", "checking", "amy")

            # Quintin earns $3000, spends $1000 → net +$2000
            _insert_balance_snapshot(conn, "t_q_chk", "2026-02-28", 1000.00)
            _insert_balance_snapshot(conn, "t_q_chk", "2026-03-31", 3000.00)
            _insert_txn(
                conn, txn_id="tx_q_inc", account_id="t_q_chk",
                posting_date="2026-03-10", amount_dollars=3000.00,
                direction="Credit", category="Salary",
                description="Quintin pay",
            )
            _insert_txn(
                conn, txn_id="tx_q_sp", account_id="t_q_chk",
                posting_date="2026-03-15", amount_dollars=1000.00,
                direction="Debit", category="Groceries",
                description="Quintin grocer",
            )

            # Amy earns $5000, spends $500 (MUST be excluded from quintin's view)
            _insert_balance_snapshot(conn, "t_a_chk", "2026-02-28", 500.00)
            _insert_balance_snapshot(conn, "t_a_chk", "2026-03-31", 5000.00)
            _insert_txn(
                conn, txn_id="tx_a_inc", account_id="t_a_chk",
                posting_date="2026-03-12", amount_dollars=5000.00,
                direction="Credit", category="Salary",
                description="Amy pay",
            )
            _insert_txn(
                conn, txn_id="tx_a_sp", account_id="t_a_chk",
                posting_date="2026-03-18", amount_dollars=500.00,
                direction="Debit", category="Groceries",
                description="Amy grocer",
            )
            conn.commit()

            # Quintin-scoped: should see only his $2k net.
            result = get_accountability(
                conn, "2026-03-01", "2026-03-31", owner_id="quintin",
            )
            assert result["net_worth_start_cents"] == 100_000   # $1000
            assert result["net_worth_end_cents"] == 300_000     # $3000
            assert result["net_worth_delta_cents"] == 200_000   # +$2000
            terms = result["identity_terms"]
            assert terms["dollars_in_cents"] == 300_000, f"got {terms}"
            assert terms["dollars_spent_cents"] == 100_000, f"got {terms}"
            # Perfect reconciliation within Quintin's scope.
            assert result["unexplained_cents"] == 0

            # Household view: sees both.
            household = get_accountability(
                conn, "2026-03-01", "2026-03-31", owner_id=None,
            )
            # NW Δ = (3000 + 5000) − (1000 + 500) = 8000 − 1500 = 6500
            assert household["net_worth_delta_cents"] == 650_000
            assert household["identity_terms"]["dollars_in_cents"] == 800_000
            assert household["identity_terms"]["dollars_spent_cents"] == 150_000
    finally:
        os.unlink(db)


if __name__ == "__main__":
    test_identity_reconciles_perfectly()
    test_miscategorize_fires_uncategorized_drift()
    test_stale_portfolio_snapshot_fires()
    test_missing_payroll_snapshot_fires()
    test_market_loss_reconciles_with_negative_term()
    test_market_gain_reconciles_with_positive_term()
    test_owner_scoping_excludes_other_owner()
    print("All P14-T04 accountability tests passed.")
