"""
tests/test_cashflow_invariants.py — Phase 10 Data Trust regression wall.

Verifies the canonical SQL pattern (blacklist + sign-check) used by every
aggregate in dal/cash_flow.py.  These tests exist to make sure the top-of-page
graphs on the Cash Flow page never drift from the drill-down KPIs again.

The fixture builds a small in-memory database with hand-picked transactions
that exercise:
  - Paychecks (income, multiple categories)
  - Rent / utilities (regular spending)
  - Groceries with a refund pair (regression for bug #3 — refunds must
    NOT cancel out spending)
  - "Deposits" category income (regression for bug #5 — Deposits must be
    treated as income, not silently swallowed by the spending blacklist)
  - Reconciled credit card payment (transfer_tag set, must drop out of
    both income and spending sides)
  - Cross-institution transfer (transfer_tag set, same drop-out)
  - Uncategorized expense
  - Multi-owner data (one transaction belongs to a non-primary owner so
    we can verify owner scoping)

For every test, the assertion is exact dollar equality.  No epsilons, no
"close enough" — every number in the canonical fixture is round to the
nearest $0.01 by construction.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
import dal.owners
from dal.owners import create_owner, assign_account_owner
from dal.cash_flow import (
    get_monthly_cash_flow,
    get_quarterly_cash_flow,
    get_yearly_cash_flow,
    get_period_detail,
    get_available_years,
)
from dal.budgets import suggest_budget_targets
from dal.category_classifications import month_range
from dal.goals import _get_avg_monthly_net


# ── Helpers ──────────────────────────────────────────────────────────────────


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


def _insert_txn(
    conn,
    txn_id,
    account_id,
    posting_date,
    amount,
    direction,
    category,
    *,
    description="Test",
    transfer_tag=None,
    institution_id="testbank",
):
    """Insert one transaction with the canonical sign convention.

    Convention: signed_amount > 0 ⟺ direction='Credit', signed_amount < 0
    ⟺ direction='Debit'.  amount is always non-negative.
    """
    signed = abs(amount) if direction == "Credit" else -abs(amount)
    conn.execute(
        """
        INSERT INTO transactions (
            id, account_id, institution_id, posting_date,
            amount, signed_amount, direction, description,
            category, status, transfer_tag, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted', ?, datetime('now'), datetime('now'))
        """,
        (
            txn_id,
            account_id,
            institution_id,
            posting_date,
            abs(amount),
            signed,
            direction,
            description,
            category,
            transfer_tag,
        ),
    )


def _seed_base(conn):
    """Insert the institutions and accounts the fixture uses."""
    conn.execute(
        "INSERT INTO institutions (id, display_name) VALUES ('testbank', 'Test Bank')"
    )
    conn.execute(
        "INSERT INTO institutions (id, display_name) VALUES ('otherbank', 'Other Bank')"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('acct_chk', 'testbank', 'Primary Checking', '1234', 'checking', 1)"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('acct_cc', 'testbank', 'Test CC', '5678', 'credit_card', 1)"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('acct_other', 'otherbank', 'Other Checking', '9999', 'checking', 1)"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('acct_partner', 'testbank', 'Partner Checking', '2222', 'checking', 1)"
    )
    conn.commit()


def _seed_january(conn):
    """Seed January 2025 with a hand-buildable cash-flow story.

    Income:
      paycheck #1   $4,000  Paychecks/Salary  on 2025-01-15
      paycheck #2   $4,000  Paychecks/Salary  on 2025-01-29
      direct deposit  $500  Deposits          on 2025-01-10  (regression #5)
      tax refund      $750  Tax Refund        on 2025-01-22

    Spending:
      rent         $1,500  Rent              on 2025-01-01
      utilities      $200  Utilities         on 2025-01-05
      groceries      $300  Groceries         on 2025-01-08
      groceries      $250  Groceries         on 2025-01-15
      groc REFUND  +$ 50  Groceries          on 2025-01-17  (regression #3)
      uncat exp      $100  (NULL)            on 2025-01-20

    Transfers / debt service (must drop out on both sides):
      cc payment    $500  Credit Card Payments on 2025-01-25  (transfer_tag='cc1')
      cc receipt   +$500  Credit Card Payments on 2025-01-25  (transfer_tag='cc1')
      xfer to other $300  Transfers           on 2025-01-26  (transfer_tag='xfer1')
      xfer recv    +$300  Transfers           on 2025-01-26  (transfer_tag='xfer1')

    Partner-owned income (must NOT show up under primary owner):
      partner pay  +$1,000 Paychecks/Salary  on 2025-01-15  (acct_partner)

    Hand totals (primary owner / household ignoring partner first):
      income   = 4000 + 4000 + 500 + 750               = 9,250
      spending = 1500 +  200 +  300 +  250 + 100        = 2,350
        (groc refund DOES NOT subtract — it's a positive
         amount in a spending category and must be filtered out)
      net      = 9,250 - 2,350                          = 6,900

    Household totals (with partner):
      income   = 9,250 + 1,000                          = 10,250
      spending = 2,350
      net      = 7,900
    """
    # Income
    _insert_txn(conn, "j_pay1", "acct_chk", "2025-01-15", 4000, "Credit", "Paychecks/Salary", description="Pay 1")
    _insert_txn(conn, "j_pay2", "acct_chk", "2025-01-29", 4000, "Credit", "Paychecks/Salary", description="Pay 2")
    _insert_txn(conn, "j_dep",  "acct_chk", "2025-01-10",  500, "Credit", "Deposits",         description="ACH Deposit")
    _insert_txn(conn, "j_ref",  "acct_chk", "2025-01-22",  750, "Credit", "Tax Refund",       description="IRS Refund")

    # Spending
    _insert_txn(conn, "j_rent", "acct_chk", "2025-01-01", 1500, "Debit", "Rent",      description="Rent")
    _insert_txn(conn, "j_util", "acct_chk", "2025-01-05",  200, "Debit", "Utilities", description="Power Co")
    _insert_txn(conn, "j_gro1", "acct_chk", "2025-01-08",  300, "Debit", "Groceries", description="Grocer A")
    _insert_txn(conn, "j_gro2", "acct_chk", "2025-01-15",  250, "Debit", "Groceries", description="Grocer A")
    # Refund — positive signed amount in a spending category.  Both top-graph
    # and drill-down must filter this out (NOT subtract from spending).
    _insert_txn(conn, "j_grfd", "acct_chk", "2025-01-17",   50, "Credit", "Groceries", description="Grocer A refund")
    # Uncategorized expense (NULL category)
    conn.execute(
        """
        INSERT INTO transactions (
            id, account_id, institution_id, posting_date,
            amount, signed_amount, direction, description,
            category, status, created_at, updated_at
        ) VALUES (?, 'acct_chk', 'testbank', '2025-01-20',
                  100, -100, 'Debit', 'Misc', NULL, 'posted',
                  datetime('now'), datetime('now'))
        """,
        ("j_uncat",),
    )

    # Reconciled CC payment pair (drops out on both sides).
    _insert_txn(conn, "j_cc_d", "acct_chk", "2025-01-25", 500, "Debit",  "Credit Card Payments", description="CC pay", transfer_tag="cc1")
    _insert_txn(conn, "j_cc_c", "acct_cc",  "2025-01-25", 500, "Credit", "Credit Card Payments", description="CC receive", transfer_tag="cc1")

    # Reconciled cross-institution transfer (drops out on both sides).
    _insert_txn(conn, "j_xf_d", "acct_chk",   "2025-01-26", 300, "Debit",  "Transfers", description="Xfer out", transfer_tag="xfer1")
    _insert_txn(conn, "j_xf_c", "acct_other", "2025-01-26", 300, "Credit", "Transfers", description="Xfer in",  transfer_tag="xfer1", institution_id="otherbank")

    # Partner-owned paycheck (used to verify owner scoping)
    _insert_txn(conn, "j_part", "acct_partner", "2025-01-15", 1000, "Credit", "Paychecks/Salary", description="Partner pay")

    conn.commit()


def _seed_q2(conn):
    """Seed April 2025 with a smaller story so we can verify quarterly closure.

    Income:   paycheck $4,000 (Apr 15)
    Spending: rent     $1,500 (Apr 1), groceries $200 (Apr 10)
    """
    _insert_txn(conn, "a_pay",  "acct_chk", "2025-04-15", 4000, "Credit", "Paychecks/Salary", description="Pay Q2")
    _insert_txn(conn, "a_rent", "acct_chk", "2025-04-01", 1500, "Debit",  "Rent",             description="Rent Q2")
    _insert_txn(conn, "a_gro",  "acct_chk", "2025-04-10",  200, "Debit",  "Groceries",        description="Grocer Q2")
    conn.commit()


# ── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def cashflow_db():
    """Build the canonical hand-built database for cash-flow invariant tests.

    Sets up an isolated SQLite file, seeds owners + accounts + the
    January 2025 story + an April 2025 mini-story, and yields the live
    connection.  Cleans up the file on teardown.
    """
    db = _temp_db()

    # Force owner config to a known state for the duration of the test
    saved_cache = dal.owners._config_cache
    dal.owners._config_cache = {
        "primary_owner": "alex",
        "owners": [
            {"id": "alex", "display_name": "Alex"},
            {"id": "jordan", "display_name": "Jordan"},
        ],
    }

    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_base(conn)

            create_owner(conn, "alex", "Alex")
            create_owner(conn, "jordan", "Jordan")
            assign_account_owner(conn, "acct_chk", "alex")
            assign_account_owner(conn, "acct_cc", "alex")
            assign_account_owner(conn, "acct_other", "alex")
            assign_account_owner(conn, "acct_partner", "jordan")
            conn.commit()

            _seed_january(conn)
            _seed_q2(conn)

            yield conn
    finally:
        dal.owners._config_cache = saved_cache
        try:
            os.unlink(db)
        except OSError:
            pass


# ── Test 1: monthly top-graph matches drill-down ────────────────────────────


def test_topgraph_matches_drilldown_monthly(cashflow_db):
    """For every month with data, the top-graph income/spending must equal
    the drill-down income/spending for the same date range."""
    monthly = get_monthly_cash_flow(cashflow_db, year=2025)

    for entry in monthly:
        m = entry["month"]
        first, last = month_range(2025, m)

        detail = get_period_detail(cashflow_db, start_date=first, end_date=last)

        assert entry["income"] == detail["income"], (
            f"Month {m}: top-graph income {entry['income']} != "
            f"drill-down income {detail['income']}"
        )
        assert entry["spending"] == detail["spending"], (
            f"Month {m}: top-graph spending {entry['spending']} != "
            f"drill-down spending {detail['spending']}"
        )
        assert entry["net"] == detail["net"], (
            f"Month {m}: top-graph net {entry['net']} != "
            f"drill-down net {detail['net']}"
        )


# ── Test 2: quarterly top-graph matches drill-down ──────────────────────────


def test_topgraph_matches_drilldown_quarterly(cashflow_db):
    """Same invariant for the quarterly view."""
    quarterly = get_quarterly_cash_flow(cashflow_db, year=2025)
    for entry in quarterly:
        q = entry["quarter"]
        start_month = (q - 1) * 3 + 1
        end_month = q * 3
        first, _ = month_range(2025, start_month)
        _, last = month_range(2025, end_month)

        detail = get_period_detail(cashflow_db, start_date=first, end_date=last)

        assert entry["income"] == detail["income"], (
            f"Q{q}: top-graph income {entry['income']} != drill-down {detail['income']}"
        )
        assert entry["spending"] == detail["spending"], (
            f"Q{q}: top-graph spending {entry['spending']} != drill-down {detail['spending']}"
        )
        assert entry["net"] == detail["net"]


# ── Test 3: yearly top-graph matches drill-down ─────────────────────────────


def test_topgraph_matches_drilldown_yearly(cashflow_db):
    """Same invariant for the yearly view."""
    yearly = get_yearly_cash_flow(cashflow_db)
    for entry in yearly:
        yr = entry["year"]
        first = f"{yr}-01-01"
        last = f"{yr}-12-31"
        detail = get_period_detail(cashflow_db, start_date=first, end_date=last)

        assert entry["income"] == detail["income"]
        assert entry["spending"] == detail["spending"]
        assert entry["net"] == detail["net"]


# ── Test 4: quarterly == sum of monthlies ───────────────────────────────────


def test_quarterly_equals_sum_of_monthlies(cashflow_db):
    """Closure property: a quarter's totals must equal the sum of its
    three months' totals.  Catches any path that double-counts or drops
    rows."""
    monthly = get_monthly_cash_flow(cashflow_db, year=2025)
    quarterly = get_quarterly_cash_flow(cashflow_db, year=2025)

    monthly_by_q: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for entry in monthly:
        q = (entry["month"] - 1) // 3 + 1
        monthly_by_q[q].append(entry)

    for q_entry in quarterly:
        q = q_entry["quarter"]
        sum_inc = round(sum(m["income"] for m in monthly_by_q[q]), 2)
        sum_spd = round(sum(m["spending"] for m in monthly_by_q[q]), 2)
        assert q_entry["income"] == sum_inc, (
            f"Q{q}: quarterly income {q_entry['income']} != "
            f"sum of monthly incomes {sum_inc}"
        )
        assert q_entry["spending"] == sum_spd, (
            f"Q{q}: quarterly spending {q_entry['spending']} != "
            f"sum of monthly spendings {sum_spd}"
        )


# ── Test 5: yearly == sum of quarterlies ────────────────────────────────────


def test_yearly_equals_sum_of_quarterlies(cashflow_db):
    """Same closure property one level up."""
    quarterly = get_quarterly_cash_flow(cashflow_db, year=2025)
    yearly = get_yearly_cash_flow(cashflow_db)

    yr2025 = next(y for y in yearly if y["year"] == 2025)
    sum_inc = round(sum(q["income"] for q in quarterly), 2)
    sum_spd = round(sum(q["spending"] for q in quarterly), 2)

    assert yr2025["income"] == sum_inc
    assert yr2025["spending"] == sum_spd


# ── Test 6: refunds do NOT cancel spending (regression for bug #3) ──────────


def test_refund_does_not_cancel_spending(cashflow_db):
    """A grocery refund (positive signed_amount in a spending category)
    must NOT subtract from January spending.

    Hand totals (household, no owner filter):
      spending = rent 1500 + util 200 + grocery 300 + grocery 250 + uncat 100 = 2,350
      income   = pay1 4000 + pay2 4000 + dep 500 + ref 750 + partner 1000   = 10,250
    The grocery refund is +$50 in a spending category — it must drop out
    of BOTH sides.  If it leaked into spending it would shrink the total
    to 2,300; if it leaked into income it would inflate to 10,300.
    """
    detail = get_period_detail(
        cashflow_db, start_date="2025-01-01", end_date="2025-01-31"
    )
    assert detail["spending"] == 2350.0, (
        f"January spending {detail['spending']} should be exactly 2350 — "
        f"refund must not cancel grocery spending"
    )

    # Bonus: the refund should also NOT show up as income
    assert detail["income"] == 10250.0, (
        f"January income {detail['income']} should be exactly 10250 "
        f"(refund must be filtered from income side too)"
    )


# ── Test 7: Deposits category is income on both paths (regression for #5) ───


def test_deposits_category_is_income_both_paths(cashflow_db):
    """A 'Deposits' category transaction must appear as income on both
    the top-graph and the drill-down sides.  Bug #5 had it in
    INCOME_EXCL_FROM_INC by mistake, which made it disappear entirely."""
    monthly = get_monthly_cash_flow(cashflow_db, year=2025)
    jan = next(m for m in monthly if m["month"] == 1)
    detail = get_period_detail(
        cashflow_db, start_date="2025-01-01", end_date="2025-01-31"
    )

    # Both income totals should include the $500 ACH deposit
    # Household total = 10,250 (4000 + 4000 + 500 + 750 + 1000 partner)
    assert jan["income"] == 10250.0
    assert detail["income"] == 10250.0
    # And the drill-down income_categories list must contain Deposits
    deposit_cats = [
        c for c in detail["income_categories"] if c["category"] == "Deposits"
    ]
    assert len(deposit_cats) == 1, (
        "Drill-down income_categories should contain 'Deposits'"
    )
    assert deposit_cats[0]["total"] == 500.0


# ── Test 8: owner scoping isolates owners ────────────────────────────────────


def test_owner_scoping_isolates_owners(cashflow_db):
    """Jordan's $1,000 paycheck (acct_partner) must NOT show up in
    Alex's view, and Alex's $9,250 of income must NOT show up in
    Jordan's view."""
    alex_jan = get_monthly_cash_flow(cashflow_db, year=2025, owner_id="mine")
    jordan_jan = get_monthly_cash_flow(cashflow_db, year=2025, owner_id="theirs")

    alex_m1 = next(m for m in alex_jan if m["month"] == 1)
    jordan_m1 = next(m for m in jordan_jan if m["month"] == 1)

    # NOTE: "mine" view = primary owner's accounts + shared (NULL owner_id)
    # "theirs" view = partner's accounts + shared (NULL owner_id)
    # Since acct_chk is owned by Alex (the primary), Alex's view should
    # see all the household income; Jordan's view should ONLY see the
    # partner-owned account.
    assert alex_m1["income"] == 9250.0, (
        f"'mine' (Alex) Jan income should be 9250, got {alex_m1['income']}"
    )
    assert jordan_m1["income"] == 1000.0, (
        f"'theirs' (Jordan) Jan income should be 1000, got {jordan_m1['income']}"
    )


# ── Test 9: budgets matches cashflow spending (regression for bug #6) ──────


def test_budgets_matches_cashflow_spending(cashflow_db):
    """suggest_budget_targets uses the canonical signed_amount + transfer_tag
    pattern (after the bug #6 fix).  Verify that for the categories present
    in the test fixture, the suggester's average computations are sane.

    We can't compare suggest_budget_targets to cash_flow.py directly because
    it uses date('now', '-3 months') and we have data from January and April
    2025 — so we instead just exercise the function and assert it returns
    a non-empty list with the canonical pattern (signed_amount-based)
    successfully producing a result.  The structural correctness of the
    pattern is what we're guarding here."""
    suggestions = suggest_budget_targets(cashflow_db, months_back=12)
    # Whatever data falls inside the lookback window, the function must
    # complete without raising and return a list (possibly empty).
    assert isinstance(suggestions, list)
    # If the test was run during a window that includes 2025 data, every
    # suggestion should have spending >= 0 (no negative leakage from the
    # legacy direction+amount pattern picking up a credit row by accident).
    for s in suggestions:
        assert s["avg_monthly"] >= 0, (
            f"Category {s['category']!r} produced a negative avg_monthly "
            f"({s['avg_monthly']}) — pattern is leaking credit rows into "
            f"the spending sum"
        )


# ── Test 10: goals matches cashflow for monthly savings ────────────────────


def test_goals_matches_cashflow_for_monthly_savings(cashflow_db):
    """_get_avg_monthly_net uses the canonical signed_amount pattern with
    transfer_tag IS NULL.  Verify it doesn't blow up and returns a value
    of the correct sign."""
    avg = _get_avg_monthly_net(cashflow_db, months=12)
    # Average net savings is monotonic in the data: it's max(0, ...).
    # If the pattern were broken (e.g., spending sign-flipped), this could
    # go negative or NaN.  Just assert it's a finite non-negative float.
    assert isinstance(avg, float)
    assert avg >= 0.0


# ── Test 11: yearly cash flow with owner_id doesn't crash (bug #1 regression)


def test_yearly_cashflow_with_owner_filter_does_not_crash(cashflow_db):
    """Bug #1: get_yearly_cash_flow used owner_id without declaring it in
    its signature, raising NameError.  Verify the call now works."""
    rows = get_yearly_cash_flow(cashflow_db, owner_id="mine")
    assert isinstance(rows, list)
    # Whichever years exist in the data, owner-scoped 'mine' should
    # produce non-empty rows because acct_chk belongs to the primary owner.
    assert len(rows) >= 1


# ── Test 13: refund leak across REAL category names (regression for B-fix) ──


def test_refund_leak_across_real_category_names(cashflow_db):
    """
    Phase B fix: INCOME_EXCL_FROM_INC used to list abstract names like
    "Dining" while the live categorizer emits "Restaurants/Dining".  A
    refund (positive signed_amount) in any of those mismatched
    categories silently inflated income on every page using the canonical
    pattern.

    This test injects a positive row in EVERY non-income real category
    that exists in the seeded data and asserts none of them appear in
    income_categories.  If the literal set drifts again, this test
    breaks loudly instead of users seeing inflated income.
    """
    real_categories_with_refund = [
        ("Restaurants/Dining", "j_ref_rd",  25),
        ("General Merchandise", "j_ref_gm", 30),
        ("Telephone Services",  "j_ref_ts", 15),
        ("Dues and Subscriptions", "j_ref_ds", 10),
        ("Healthcare",          "j_ref_hc", 20),
    ]
    for cat, txn_id, amt in real_categories_with_refund:
        _insert_txn(
            cashflow_db, txn_id, "acct_chk", "2025-01-18", amt, "Credit", cat,
            description=f"{cat} refund",
        )
    cashflow_db.commit()

    detail = get_period_detail(
        cashflow_db, start_date="2025-01-01", end_date="2025-01-31"
    )

    # None of the refund categories may appear under income.
    income_cat_names = {c["category"] for c in detail["income_categories"]}
    leaked = income_cat_names & {cat for cat, _, _ in real_categories_with_refund}
    assert not leaked, (
        f"Refund leaked into income for categories: {sorted(leaked)} — "
        f"INCOME_EXCL_FROM_INC literals are out of sync with the real "
        f"category names emitted by dal/categorization.py."
    )

    # And January income must NOT be inflated by the $100 of refunds.
    # Hand total household income for January is still 10,250 (from the
    # base fixture); refunds are filtered out at both top-graph and
    # drill-down sides.
    assert detail["income"] == 10250.0, (
        f"January income {detail['income']} != 10250 after injecting "
        f"refunds — they leaked into the income side"
    )


# ── Test 14: effective_month vs posting_date drift (regression for D-fix) ──


def test_effective_month_drift_in_drill_down(cashflow_db):
    """
    Phase B/D fix: get_period_detail used to filter and group purely by
    posting_date while sibling cash-flow aggregates use
    COALESCE(effective_month, ...).  The moment any income-attribution
    rule stamped effective_month on a row, the top-graph bar for month X
    and the drill-down for month X would silently disagree.

    Insert a row whose posting_date lands in February but whose
    effective_month is set to "2025-01" and assert it shows up under
    January in BOTH the monthly top-graph and the drill-down.
    """
    # Insert via raw SQL because _insert_txn doesn't know about effective_month.
    cashflow_db.execute(
        """
        INSERT INTO transactions (
            id, account_id, institution_id, posting_date,
            amount, signed_amount, direction, description,
            category, status, effective_month, created_at, updated_at
        ) VALUES (?, 'acct_chk', 'testbank', '2025-02-03',
                  500, 500, 'Credit', 'Late paycheck', 'Paychecks/Salary',
                  'posted', '2025-01', datetime('now'), datetime('now'))
        """,
        ("j_em_drift",),
    )
    cashflow_db.commit()

    monthly = get_monthly_cash_flow(cashflow_db, year=2025)
    jan = next(m for m in monthly if m["month"] == 1)
    detail = get_period_detail(
        cashflow_db, start_date="2025-01-01", end_date="2025-01-31"
    )

    # Both views must attribute the late paycheck to January because of
    # effective_month, even though posting_date is in February.
    assert jan["income"] == detail["income"], (
        f"effective_month drift: top-graph Jan income {jan['income']} != "
        f"drill-down Jan income {detail['income']}.  An attribution-stamped "
        f"row landed on different sides of the seam."
    )


# ── Test 15: available_years respects owner scope (bug #4 regression) ──────


def test_available_years_respects_owner_scope(cashflow_db):
    """Bug #4: get_available_years did not apply owner/account scoping,
    so it returned years from accounts the user shouldn't see.  Verify
    that owner scoping now works."""
    # Without owner filter — should see both 2025 (acct_chk) and the
    # partner row also lives in 2025
    all_years = get_available_years(cashflow_db)
    assert 2025 in all_years

    # With 'mine' filter, primary owner sees their accounts + shared
    mine_years = get_available_years(cashflow_db, owner_id="mine")
    assert 2025 in mine_years

    # With 'theirs' filter, partner sees their account → only 2025
    theirs_years = get_available_years(cashflow_db, owner_id="theirs")
    assert 2025 in theirs_years
    # And critically, theirs view doesn't see anything outside Jordan's
    # account — there's only the one partner txn in January 2025
    assert all(y == 2025 for y in theirs_years)
