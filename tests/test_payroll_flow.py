"""
tests/test_payroll_flow.py — Phase 14 Phase A unit tests.

Covers `dal/payroll.get_flow_contribution`, `find_matching_deposit_tx_id`,
and the gross-paycheck decomposition that `dal/reports.get_flow_data`
folds into the Sankey response.

Test cases (per docs/prompts/Phase-14/P14-T01_gross-paycheck-sankey.md):

  1. test_get_flow_contribution_aggregates_by_owner — multiple owners
     with overlapping months return owner-scoped totals.
  2. test_withholdings_list_omits_zero_fields — a snapshot with $0
     dental/vision produces no `dental_vision` entry.
  3. test_deposit_match_excludes_transaction — synthetic payroll
     snapshot + matching net-pay transaction → `excluded_transaction_ids`
     contains the txn id; `income_categories` total excludes the deposit;
     `total_income` reflects gross.
  4. test_deposit_no_match_emits_decomposition_only — payroll row with
     no matching transaction emits decomposition; excluded list empty;
     `total_income` includes the full gross snapshot.
  5. test_transaction_no_payroll_falls_through — a deposit transaction
     without a payroll row contributes to `income_categories` at its
     own amount.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.owners import create_owner
from dal.payroll import find_matching_deposit_tx_id, get_flow_contribution
from dal.reports import get_flow_data


# ── Helpers ──────────────────────────────────────────────────────────────────


_passed = 0
_failed = 0
_errors: list[str] = []


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


def _temp_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


def _insert_payroll(
    conn: sqlite3.Connection,
    *,
    pay_period: str,
    source: str,
    owner_id: str | None = None,
    gross: float = 5200.0,
    federal: float = 520.0,
    state: float = 130.0,
    sbp: float = 270.0,
    health: float = 0.0,
    dental: float = 45.0,
    other: float = 0.0,
):
    net = gross - federal - state - sbp - health - dental - other
    conn.execute(
        """
        INSERT INTO payroll_snapshots
        (pay_period, source, owner_id, gross_pay, federal_tax, state_tax,
         sbp_premium, health_insurance, dental_vision, other_deductions,
         net_pay, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
        """,
        (pay_period, source, owner_id, gross, federal, state,
         sbp, health, dental, other, net),
    )


def _insert_account(conn, *, account_id: str, owner_id: str | None = None,
                     institution_id: str = "inst_test", last4: str = "0000"):
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, type, last4, owner_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (account_id, institution_id, account_id.upper(), "checking", last4, owner_id),
    )


def _insert_txn(
    conn: sqlite3.Connection,
    *,
    txn_id: str,
    account_id: str,
    posting_date: str,
    amount: float,
    merchant: str = "",
    description: str = "",
    category: str = "Paychecks/Salary",
    institution_id: str = "inst_test",
):
    direction = "Credit" if amount > 0 else "Debit"
    conn.execute(
        """
        INSERT INTO transactions
        (id, institution_id, account_id, amount, signed_amount, direction,
         posting_date, effective_month, merchant, description, category,
         status, transfer_tag)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted', NULL)
        """,
        (txn_id, institution_id, account_id, abs(amount), amount, direction,
         posting_date, posting_date[:7], merchant, description, category),
    )


def _setup_owners_and_account(conn, owner_id: str, account_id: str):
    create_owner(conn, owner_id, owner_id.title())
    conn.execute(
        "INSERT OR IGNORE INTO institutions (id, display_name) VALUES (?, ?)",
        ("inst_test", "Test Bank"),
    )
    _insert_account(conn, account_id=account_id, owner_id=owner_id)


# ── Tests ────────────────────────────────────────────────────────────────────


def test_get_flow_contribution_aggregates_by_owner():
    print("\n─── P14-T01.1: owner-scoped flow contribution ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            create_owner(conn, "alpha", "Alpha")
            create_owner(conn, "beta", "Beta")

            _insert_payroll(conn, pay_period="2026-01", source="archetype_alpha",
                            owner_id="alpha", gross=5200.0)
            _insert_payroll(conn, pay_period="2026-02", source="archetype_alpha",
                            owner_id="alpha", gross=5200.0)
            _insert_payroll(conn, pay_period="2026-01", source="archetype_beta",
                            owner_id="beta", gross=3000.0,
                            federal=300.0, state=75.0, sbp=0.0,
                            dental=0.0, health=0.0)
            conn.commit()

            household = get_flow_contribution(conn, "2026-01", "2026-02")
            _check(
                "household: 3 rows returned",
                len(household["payroll_rows"]) == 3,
                f"got {len(household['payroll_rows'])}",
            )
            _check(
                "household: total_gross_cents == $13,400.00",
                household["total_gross_cents"] == 1_340_000,
                f"got {household['total_gross_cents']}",
            )

            alpha = get_flow_contribution(conn, "2026-01", "2026-02", owner_id="alpha")
            _check(
                "alpha: 2 rows returned",
                len(alpha["payroll_rows"]) == 2,
                f"got {len(alpha['payroll_rows'])}",
            )
            _check(
                "alpha: total_gross_cents == $10,400.00",
                alpha["total_gross_cents"] == 1_040_000,
            )
            _check(
                "alpha: every row owner_id == 'alpha'",
                all(r["owner_id"] == "alpha" for r in alpha["payroll_rows"]),
            )

            beta = get_flow_contribution(conn, "2026-01", "2026-02", owner_id="beta")
            _check(
                "beta: 1 row returned",
                len(beta["payroll_rows"]) == 1,
            )
            _check(
                "beta: total_gross_cents == $3,000.00",
                beta["total_gross_cents"] == 300_000,
            )
    finally:
        os.unlink(db)


def test_withholdings_list_omits_zero_fields():
    print("\n─── P14-T01.2: zero-valued withholding fields omitted ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            # Snapshot with zero dental, zero health, zero other.
            _insert_payroll(conn, pay_period="2026-03", source="archetype_x",
                            owner_id=None,
                            gross=5200.0, federal=520.0, state=130.0,
                            sbp=270.0, health=0.0, dental=0.0, other=0.0)
            conn.commit()

            contrib = get_flow_contribution(conn, "2026-03", "2026-03")
            _check("one row returned", len(contrib["payroll_rows"]) == 1)
            row = contrib["payroll_rows"][0]
            kinds = [w["kind"] for w in row["withholdings"]]
            _check(
                "federal_tax present",
                "federal_tax" in kinds,
            )
            _check(
                "sbp_premium present",
                "sbp_premium" in kinds,
            )
            _check(
                "dental_vision OMITTED (zero)",
                "dental_vision" not in kinds,
                f"got {kinds}",
            )
            _check(
                "health OMITTED (zero)",
                "health" not in kinds,
            )
            _check(
                "other OMITTED (zero)",
                "other" not in kinds,
            )
            _check(
                "every withholding bucket is CONSUMED in Phase A",
                all(w["bucket"] == "CONSUMED" for w in row["withholdings"]),
            )
            # Amount sanity
            fed = next(w for w in row["withholdings"] if w["kind"] == "federal_tax")
            _check(
                "federal_tax cents == 52000",
                fed["cents"] == 52000,
                f"got {fed['cents']}",
            )
    finally:
        os.unlink(db)


def test_deposit_match_excludes_transaction():
    print("\n─── P14-T01.3: deposit-match excludes the transaction ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _setup_owners_and_account(conn, "quintin", "chk_q")

            # Payroll snapshot for archetype 'archetype_pay' Mar 2026
            _insert_payroll(conn, pay_period="2026-03", source="archetype_pay",
                            owner_id="quintin",
                            gross=5200.0, federal=520.0, state=130.0,
                            sbp=270.0, health=0.0, dental=45.0, other=0.0)

            # Matching net-pay deposit — merchant contains 'archetype_pay'
            _insert_txn(conn, txn_id="tx_match",
                        account_id="chk_q", posting_date="2026-03-01",
                        amount=4235.00,
                        merchant="ARCHETYPE_PAY DEPOSIT",
                        description="Direct deposit",
                        category="Paychecks/Salary")
            # Plus a separate non-matching income txn (should still appear)
            _insert_txn(conn, txn_id="tx_other",
                        account_id="chk_q", posting_date="2026-03-15",
                        amount=200.00, merchant="REFUND PROCESSOR",
                        description="Refund", category="Other Income")
            conn.commit()

            # Direct dedup helper
            match_id = find_matching_deposit_tx_id(
                conn, source_label="archetype_pay",
                pay_period="2026-03", owner_id="quintin",
            )
            _check(
                "find_matching_deposit_tx_id returns 'tx_match'",
                match_id == "tx_match",
                f"got {match_id!r}",
            )

            # Through get_flow_data
            data = get_flow_data(
                conn,
                start_date="2026-03-01", end_date="2026-03-31",
                owner_id="quintin",
            )
            decomp = data["payroll_decomposition"]
            _check(
                "excluded_transaction_ids contains tx_match",
                "tx_match" in decomp["excluded_transaction_ids"],
                f"got {decomp['excluded_transaction_ids']}",
            )
            # Matched row carries its matched_txn_id back
            _check(
                "matched row's matched_txn_id == 'tx_match'",
                any(
                    r["matched_txn_id"] == "tx_match"
                    for r in decomp["payroll_rows"]
                ),
                f"got matched_txn_ids={[r['matched_txn_id'] for r in decomp['payroll_rows']]}",
            )
            # Income categories: 'Paychecks/Salary' should be excluded (only
            # txn there was tx_match). 'Other Income' still present.
            cat_names = [c["category"] for c in data["income_categories"]]
            _check(
                "Paychecks/Salary dropped from income_categories",
                "Paychecks/Salary" not in cat_names,
                f"got {cat_names}",
            )
            _check(
                "Other Income still present",
                "Other Income" in cat_names,
            )
            # total_income = $200 other income + $5200 gross paycheck.
            # The matched net deposit row is excluded, so full gross is the
            # replacement income, not just gross-minus-net.
            _check(
                "total_income reflects full gross replacement ($5,400.00)",
                data["total_income"] == 5400.00,
                f"got {data['total_income']}",
            )
    finally:
        os.unlink(db)


def test_deposit_no_match_emits_decomposition_only():
    print("\n─── P14-T01.4: no-match emits decomposition only ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _setup_owners_and_account(conn, "quintin", "chk_q")

            # Payroll snapshot but NO matching transaction.
            _insert_payroll(conn, pay_period="2026-03", source="archetype_pay",
                            owner_id="quintin", gross=5200.0)
            # Unrelated income transaction in same window — should be
            # untouched by dedup.
            _insert_txn(conn, txn_id="tx_other",
                        account_id="chk_q", posting_date="2026-03-15",
                        amount=200.00, merchant="REFUND PROCESSOR",
                        description="Refund", category="Other Income")
            conn.commit()

            data = get_flow_data(
                conn,
                start_date="2026-03-01", end_date="2026-03-31",
                owner_id="quintin",
            )
            decomp = data["payroll_decomposition"]
            _check(
                "payroll_rows has 1 entry",
                len(decomp["payroll_rows"]) == 1,
            )
            _check(
                "excluded_transaction_ids is empty",
                decomp["excluded_transaction_ids"] == [],
                f"got {decomp['excluded_transaction_ids']}",
            )
            _check(
                "payroll row's matched_txn_id is None",
                decomp["payroll_rows"][0]["matched_txn_id"] is None,
                f"got {decomp['payroll_rows'][0]['matched_txn_id']}",
            )
            # No match means the payroll snapshot itself is the only visible
            # paycheck fact, so full gross is included alongside other income.
            _check(
                "total_income includes unmatched gross ($5,400.00)",
                data["total_income"] == 5400.00,
                f"got {data['total_income']}",
            )
            _check(
                "Other Income still in income_categories",
                any(c["category"] == "Other Income" for c in data["income_categories"]),
            )
    finally:
        os.unlink(db)


def test_transaction_no_payroll_falls_through():
    print("\n─── P14-T01.5: transaction without payroll snapshot falls through ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _setup_owners_and_account(conn, "quintin", "chk_q")

            # NO payroll snapshots. Just a deposit transaction.
            _insert_txn(conn, txn_id="tx_only",
                        account_id="chk_q", posting_date="2026-03-10",
                        amount=4000.00, merchant="ACME PAYROLL",
                        description="Bi-weekly pay",
                        category="Paychecks/Salary")
            conn.commit()

            data = get_flow_data(
                conn,
                start_date="2026-03-01", end_date="2026-03-31",
                owner_id="quintin",
            )
            decomp = data["payroll_decomposition"]
            _check(
                "payroll_rows is empty",
                decomp["payroll_rows"] == [],
            )
            _check(
                "excluded_transaction_ids is empty",
                decomp["excluded_transaction_ids"] == [],
            )
            _check(
                "total_income = $4,000 from transaction (unchanged)",
                data["total_income"] == 4000.00,
                f"got {data['total_income']}",
            )
            _check(
                "Paychecks/Salary appears in income_categories",
                any(c["category"] == "Paychecks/Salary"
                    for c in data["income_categories"]),
            )
    finally:
        os.unlink(db)


# ── Main ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    test_get_flow_contribution_aggregates_by_owner()
    test_withholdings_list_omits_zero_fields()
    test_deposit_match_excludes_transaction()
    test_deposit_no_match_emits_decomposition_only()
    test_transaction_no_payroll_falls_through()

    print(f"\n{'═' * 60}")
    print(f"  P14-T01 Phase A Tests: {_passed} passed, {_failed} failed")
    if _errors:
        print(f"  Failed: {', '.join(_errors)}")
    print(f"{'═' * 60}")
    sys.exit(1 if _failed else 0)
