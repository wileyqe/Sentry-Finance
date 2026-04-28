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


def test_shape_a_transfer_to_brokerage_is_liquid_fallback():
    # The classifier's brokerage branch is reserved for the (currently
    # empty) Shape A case where a future broker emits a paired
    # transactions row on the brokerage account. Without proof the
    # cash bought shares, fallback is STORED_LIQUID.
    #
    # Acorns / Fidelity / TSP-shape Shape B transfers (where the
    # brokerage emits ledger rows instead) bypass this classifier
    # entirely — see dal/reports/flow.py's Shape B path which always
    # classifies STORED_ILLIQUID via the bank_txn_id linkage.
    assert classify(
        category=None,
        account_type="checking",
        transfer_peer_account_type="investment",
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


# ── AI-015 regression: spending categories must opt into INCOME_EXCL_FROM_INC ─


def test_seeder_spending_categories_excluded_from_income():
    """Every spending category the seeder emits must be in
    INCOME_EXCL_FROM_INC, otherwise a refund (positive signed_amount in
    that category) would inflate income on every page using the canonical
    income filter (`signed_amount > 0 AND category NOT IN
    INCOME_EXCL_FROM_INC`).

    This is a static regression — it parses the seeder source instead of
    running it — so adding a new spending category to ``BUDGET_BASE`` or
    to ``dummy_data/recurring_transactions.json`` without also adding it
    to ``INCOME_EXCL_FROM_INC`` fails this test.
    """
    import json
    import re

    from dal.category_classifications import (
        INCOME_EXCL_FROM_INC,
        INCOME_CATEGORIES,
        TRANSFER_CATEGORIES,
    )

    spending_cats: set[str] = set()

    # Source 1: BUDGET_BASE (every key is a budgeted spending category).
    gen_src = (ROOT / "scripts" / "dummy_data" / "generator.py").read_text(
        encoding="utf-8"
    )
    m = re.search(r"BUDGET_BASE:\s*dict\[str,\s*int\]\s*=\s*\{([^}]*)\}", gen_src)
    assert m, "Could not locate BUDGET_BASE in generator.py — test needs update"
    for kv in re.finditer(r'"([^"]+)"\s*:\s*\d+', m.group(1)):
        spending_cats.add(kv.group(1))

    # Source 2: outflow rows in recurring_transactions.json.
    recurring = json.loads(
        (ROOT / "dummy_data" / "recurring_transactions.json").read_text(
            encoding="utf-8"
        )
    )
    for row in recurring:
        cat = row.get("category")
        # We treat outflow as anything that is not categorically income/transfer.
        # Rows with avg_amount < 0 are explicit outflows.
        if not cat:
            continue
        if cat in INCOME_CATEGORIES or cat in TRANSFER_CATEGORIES:
            continue
        avg = row.get("avg_amount", 0)
        if isinstance(avg, (int, float)) and avg < 0:
            spending_cats.add(cat)
        # Also include rows where category isn't income/transfer but no
        # explicit sign — these are the recurring bills (utilities, insurance).
        elif "amount" not in row:
            spending_cats.add(cat)

    missing = spending_cats - INCOME_EXCL_FROM_INC
    assert not missing, (
        "AI-015 regression: seeder spending categories are missing from "
        f"INCOME_EXCL_FROM_INC: {sorted(missing)}. Add each to the set in "
        "dal/category_classifications.py — otherwise a refund in that "
        "category will inflate income on every page using the canonical "
        "income filter."
    )
