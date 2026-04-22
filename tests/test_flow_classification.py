"""
tests/test_flow_classification.py — Phase 14 Phase B classifier tests.

Covers ``dal.flow_classification.classify`` and the broader
``get_flow_data`` bucket-totals invariant. Six classifier cases plus one
end-to-end invariant test against seeded data.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.flow_classification import BucketLabel, classify, match_rule_matches


# ── Unit tests for classify() ────────────────────────────────────────────────


def test_transfer_with_retirement_peer_is_illiquid():
    assert classify(
        category=None,
        account_type="checking",
        transfer_peer_account_type="retirement",
        is_transfer=True,
    ) == BucketLabel.STORED_ILLIQUID


def test_transfer_with_checking_peer_is_liquid():
    assert classify(
        category=None,
        account_type="savings",
        transfer_peer_account_type="checking",
        is_transfer=True,
    ) == BucketLabel.STORED_LIQUID


def test_transfer_to_brokerage_with_matched_buy_is_illiquid():
    assert classify(
        category=None,
        account_type="checking",
        transfer_peer_account_type="investment",
        brokerage_buy_matched=True,
        is_transfer=True,
    ) == BucketLabel.STORED_ILLIQUID


def test_transfer_to_brokerage_without_matched_buy_is_liquid():
    assert classify(
        category=None,
        account_type="checking",
        transfer_peer_account_type="investment",
        brokerage_buy_matched=False,
        is_transfer=True,
    ) == BucketLabel.STORED_LIQUID


def test_debit_groceries_is_consumed():
    assert classify(
        category="Groceries",
        account_type="credit_card",
    ) == BucketLabel.CONSUMED


def test_transfer_with_no_peer_defaults_to_consumed_with_warning(caplog):
    caplog.set_level(logging.WARNING, logger="sentry.dal.flow_classification")
    bucket = classify(
        category="Transfers",
        account_type="checking",
        transfer_peer_account_type=None,
        is_transfer=True,
    )
    assert bucket == BucketLabel.CONSUMED
    assert any("no resolved peer" in rec.message for rec in caplog.records), (
        "Expected a fail-loud warning about unresolved peer"
    )


def test_hsa_peer_is_illiquid():
    # HSA contributions go to the illiquid bucket regardless of buy-match.
    assert classify(
        category=None,
        account_type="checking",
        transfer_peer_account_type="hsa",
        is_transfer=True,
    ) == BucketLabel.STORED_ILLIQUID


def test_liability_peer_is_consumed():
    # Moving cash to a credit card / loan pays down a balance — CONSUMED.
    for peer in ("credit_card", "loan", "bnpl", "mortgage"):
        assert classify(
            category=None,
            account_type="checking",
            transfer_peer_account_type=peer,
            is_transfer=True,
        ) == BucketLabel.CONSUMED, f"{peer} peer expected CONSUMED"


# ── match_rule_matches ───────────────────────────────────────────────────────


def test_match_rule_requires_counterparty_or_category():
    # Empty rule — would match everything, so rejected.
    assert not match_rule_matches('{}', counterparty="anything", category="anything")


def test_match_rule_counterparty_substring_case_insensitive():
    rule = '{"counterparty_substring": "ACME"}'
    assert match_rule_matches(rule, counterparty="acme corp payroll")
    assert not match_rule_matches(rule, counterparty="other company")


def test_match_rule_category_exact_match():
    rule = '{"category": "Officiating Income"}'
    assert match_rule_matches(rule, category="Officiating Income")
    assert not match_rule_matches(rule, category="Paychecks/Salary")


def test_match_rule_owner_filter():
    rule = (
        '{"counterparty_substring": "acme", '
        '"owner_id": "quintin"}'
    )
    assert match_rule_matches(rule, counterparty="ACME CORP", owner_id="quintin")
    assert not match_rule_matches(rule, counterparty="ACME CORP", owner_id="amy")


# ── End-to-end invariant (small synthetic DB) ────────────────────────────────


@pytest.fixture
def tiny_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(Path(path))
        yield Path(path)
    finally:
        os.unlink(path)


def _seed_minimal_account(conn: sqlite3.Connection, acct_id: str, acct_type: str,
                          owner_id: str | None = None, last4: str = "0000"):
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) VALUES ('inst_t', 'Test')"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, type, last4, owner_id) "
        "VALUES (?, 'inst_t', ?, ?, ?, ?)",
        (acct_id, acct_id.upper(), acct_type, last4, owner_id),
    )


def _insert_txn(conn: sqlite3.Connection, *, txn_id: str, account_id: str,
                 posting_date: str, signed_amount: float,
                 category: str = "Uncategorized",
                 transfer_tag: str | None = None,
                 description: str = ""):
    direction = "Credit" if signed_amount > 0 else "Debit"
    conn.execute(
        """
        INSERT INTO transactions
        (id, institution_id, account_id, posting_date, effective_month,
         amount, signed_amount, direction, description, category,
         status, transfer_tag)
        VALUES (?, 'inst_t', ?, ?, ?, ?, ?, ?, ?, ?, 'posted', ?)
        """,
        (txn_id, account_id, posting_date, posting_date[:7],
         abs(signed_amount), signed_amount, direction, description,
         category, transfer_tag),
    )


def test_bucket_invariant_holds_on_synthetic_month(tiny_db):
    """End-to-end: income + spending + a transfer pair → bucket totals
    add up to total inflow within the $1 tolerance."""
    from dal.owners import create_owner
    from dal.reports import get_flow_data

    with get_db(tiny_db) as conn:
        create_owner(conn, "quintin", "Quintin")
        _seed_minimal_account(conn, "chk_q", "checking", owner_id="quintin", last4="0001")
        _seed_minimal_account(conn, "ret_q", "retirement", owner_id="quintin", last4="0002")

        # Income: $4,000 paycheck
        _insert_txn(
            conn, txn_id="t_in", account_id="chk_q",
            posting_date="2026-03-05", signed_amount=4000.00,
            category="Paychecks/Salary", description="Paycheck",
        )
        # Spending: $1,000 groceries
        _insert_txn(
            conn, txn_id="t_g", account_id="chk_q",
            posting_date="2026-03-10", signed_amount=-1000.00,
            category="Groceries", description="Kroger",
        )
        # Transfer to retirement: -$500 debit paired with +$500 credit
        _insert_txn(
            conn, txn_id="t_tr_d", account_id="chk_q",
            posting_date="2026-03-15", signed_amount=-500.00,
            category="Transfers", transfer_tag="tag1",
            description="Transfer to retirement",
        )
        _insert_txn(
            conn, txn_id="t_tr_c", account_id="ret_q",
            posting_date="2026-03-15", signed_amount=500.00,
            category="Transfers", transfer_tag="tag1",
            description="Transfer from checking",
        )
        conn.commit()

        data = get_flow_data(
            conn, start_date="2026-03-01", end_date="2026-03-31",
            owner_id="quintin",
        )

    b = data["bucket_totals_cents"]
    total_inflow = data["total_inflow_cents"]
    bucket_sum = b["CONSUMED"] + b["STORED_LIQUID"] + b["STORED_ILLIQUID"]

    # Groceries ($1,000) → CONSUMED
    assert b["CONSUMED"] >= 100_000, f"expected ≥$1,000 CONSUMED, got {b}"
    # Transfer to retirement ($500) → STORED_ILLIQUID
    assert b["STORED_ILLIQUID"] >= 50_000, f"expected ≥$500 illiquid, got {b}"
    # Invariant: bucket sum ≈ total inflow (±$1)
    assert abs(bucket_sum - total_inflow) <= 100, (
        f"Invariant broken: buckets={bucket_sum}¢, inflow={total_inflow}¢, "
        f"drift={bucket_sum - total_inflow}¢"
    )
