"""
tests/test_golden_seed.py — Phase 10 hand-auditable rolling-generator wall.

Pins the rolling generator to a fixed end-date and asserts exact totals
for every category in every full year of the window.  These totals were
computed by hand from the generator's design (see the per-year breakdown
in the generator's module docstring) and verified against the live
generator output before being committed.

If the generator's RNG sequence ever shifts, this test will catch it
immediately — far before a user notices a graph change.

The pinned end-date is **2026-01-15** with **years=3**, producing a
1577-transaction history starting at **2023-01-18** (the first Friday
plus surrounding monthly fixtures) through **2026-01-15**.

Determinism guarantee: the same (end_date, years) pair MUST produce
byte-identical output.  We hash the (date, account, signed_amount,
description) tuples and assert the fingerprint is stable.
"""

import hashlib
from collections import defaultdict
from datetime import date

import pytest

from scripts.dummy_data.generator import (
    ACCOUNTS,
    generate_transactions,
    generate_balance_snapshots,
    generate_budgets,
    generate_credit_scores,
    generate_investment_history,
    generate_payroll_snapshots,
    generate_vehicle_valuations,
)


# ── Pinned inputs ────────────────────────────────────────────────────────────

PIN_END_DATE = date(2026, 1, 15)
PIN_YEARS = 3
EXPECTED_FIRST_DATE = "2023-01-18"
EXPECTED_LAST_DATE = "2026-01-15"
EXPECTED_TXN_COUNT = 1577

# Stable fingerprint for the canonical pin.  Recomputed if the generator
# logic changes — but only if intentional.  See _fingerprint() below.
EXPECTED_FINGERPRINT = "37581d9944c4"

# Per-year, per-category SIGNED totals from the deterministic run.
# Negative numbers are spending; positive numbers are income / refunds /
# transfer credits / loan payments received on the loan side.
#
# Years with full 12-month coverage in the pinned window: 2024 and 2025.
# 2023 starts mid-January (start_date = 2023-01-15) so it's a partial year.
# 2026 ends 2026-01-15 so it's also partial.
EXPECTED_YEAR_TOTALS: dict[int, dict[str, float]] = {
    2024: {
        "Auto":                   -2170.00,
        "Credit Card Payments":       0.00,
        "Dues and Subscriptions":  -764.00,
        "Groceries":              -5100.00,
        "Insurance":              -1200.00,
        "Interest":                 540.00,
        "Loan Payments":          18000.00,
        "Mortgages":             -18000.00,
        "Paychecks/Salary":      146000.00,
        "Restaurants/Dining":     -2350.00,
        "Shopping":               -3025.00,
        "Telephone Services":     -1980.00,
        "Transfers":                  0.00,
        "Utilities":              -2400.00,
    },
    2025: {
        "Auto":                   -2370.00,
        "Credit Card Payments":       0.00,
        "Dues and Subscriptions":  -764.00,
        "Groceries":              -4900.00,
        "Insurance":              -1200.00,
        "Interest":                 540.00,
        "Loan Payments":          18000.00,
        "Mortgages":             -18000.00,
        "Paychecks/Salary":      146000.00,
        "Restaurants/Dining":     -2590.00,
        "Shopping":               -3675.00,
        "Telephone Services":     -1980.00,
        "Transfers":                  0.00,
        "Utilities":              -2400.00,
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _fingerprint(txns: list[dict]) -> str:
    """Stable 12-char hash of (date, account, signed_amount, description)
    tuples in deterministic order.  Sensitive to ANY change in the
    generator's RNG sequence."""
    h = hashlib.sha256()
    for t in sorted(
        txns,
        key=lambda x: (x["posting_date"], x["account_id"], x["signed_amount"], x["description"]),
    ):
        h.update(
            f"{t['account_id']}|{t['posting_date']}|{t['signed_amount']}|{t['description']}".encode()
        )
    return h.hexdigest()[:12]


def _per_year_category_totals(txns: list[dict]) -> dict[int, dict[str, float]]:
    """Aggregate signed_amount by (year, category)."""
    out: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in txns:
        yr = int(t["posting_date"][:4])
        cat = t["category"]
        out[yr][cat] += float(t["signed_amount"])
    return {yr: dict(cats) for yr, cats in out.items()}


# ── Test fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def pinned_txns():
    """Generate the canonical pinned dataset once per module."""
    return generate_transactions(end_date=PIN_END_DATE, years=PIN_YEARS)


# ── Test 1: total transaction count is locked ───────────────────────────────


def test_pinned_total_txn_count(pinned_txns):
    assert len(pinned_txns) == EXPECTED_TXN_COUNT, (
        f"Pinned dataset produced {len(pinned_txns)} txns, expected "
        f"{EXPECTED_TXN_COUNT}.  Did the generator's RNG sequence shift?"
    )


# ── Test 2: first/last dates are locked ─────────────────────────────────────


def test_pinned_first_and_last_dates(pinned_txns):
    first = min(t["posting_date"] for t in pinned_txns)
    last = max(t["posting_date"] for t in pinned_txns)
    assert first == EXPECTED_FIRST_DATE, (
        f"First date {first} != expected {EXPECTED_FIRST_DATE}"
    )
    assert last == EXPECTED_LAST_DATE, (
        f"Last date {last} != expected {EXPECTED_LAST_DATE}"
    )


# ── Test 3: deterministic fingerprint ───────────────────────────────────────


def test_pinned_fingerprint_is_stable(pinned_txns):
    fp = _fingerprint(pinned_txns)
    assert fp == EXPECTED_FINGERPRINT, (
        f"Fingerprint drifted: got {fp}, expected {EXPECTED_FINGERPRINT}.\n"
        f"Either intentionally update EXPECTED_FINGERPRINT (and re-verify "
        f"the EXPECTED_YEAR_TOTALS table by hand) or revert the generator "
        f"change."
    )


# ── Test 4: same end-date produces byte-identical output ────────────────────


def test_generator_is_deterministic_on_repeat():
    """Generating twice with the same end_date must produce identical
    fingerprints — no RNG bleed across runs."""
    a = generate_transactions(end_date=PIN_END_DATE, years=PIN_YEARS)
    b = generate_transactions(end_date=PIN_END_DATE, years=PIN_YEARS)
    assert _fingerprint(a) == _fingerprint(b)


# ── Test 5: full-year category totals match the hand-audited table ──────────


def test_pinned_year_category_totals(pinned_txns):
    actual = _per_year_category_totals(pinned_txns)

    for yr, cat_map in EXPECTED_YEAR_TOTALS.items():
        actual_cats = actual.get(yr, {})

        # Every expected category must be present
        for cat, expected_total in cat_map.items():
            actual_total = round(actual_cats.get(cat, 0.0), 2)
            assert actual_total == expected_total, (
                f"{yr} {cat}: expected ${expected_total:,.2f}, "
                f"got ${actual_total:,.2f}"
            )

        # And there should be no extra categories that drift in unexpectedly
        extra = set(actual_cats.keys()) - set(cat_map.keys())
        assert not extra, (
            f"{yr}: unexpected new categories appeared: {sorted(extra)}"
        )


# ── Test 6: every signed_amount is a whole-dollar amount ────────────────────


def test_all_amounts_are_round_dollars(pinned_txns):
    """Hand-auditability requires every txn to be a whole dollar.  No
    arbitrary float amounts allowed."""
    bad = [
        t for t in pinned_txns
        if float(t["signed_amount"]) != round(float(t["signed_amount"]))
    ]
    assert not bad, (
        f"{len(bad)} transactions had non-integer signed_amount values. "
        f"Examples: {bad[:3]}"
    )


# ── Test 7: sign convention holds for every generated txn ───────────────────


def test_sign_convention_invariant(pinned_txns):
    """Every generator-emitted row must satisfy:
        signed_amount < 0  ⟺  direction='Debit'
        signed_amount > 0  ⟺  direction='Credit'
    so the upsert invariant check never fires for generator output."""
    for t in pinned_txns:
        s = float(t["signed_amount"])
        d = t["direction"]
        if s < 0:
            assert d == "Debit", (
                f"Row with signed_amount={s} has direction={d!r} (should be 'Debit'): {t}"
            )
        elif s > 0:
            assert d == "Credit", (
                f"Row with signed_amount={s} has direction={d!r} (should be 'Credit'): {t}"
            )


# ── Test 8: paired transfers / mortgage / CC payments balance to zero ───────


def test_paired_categories_sum_to_zero_per_year(pinned_txns):
    """Categories that exist in both legs of a transfer must sum to
    zero across each year — proves both legs are emitted with matching
    amounts and dates within the same calendar year."""
    actual = _per_year_category_totals(pinned_txns)
    for yr in (2024, 2025):
        cats = actual[yr]
        for paired_cat in ("Transfers", "Credit Card Payments"):
            assert abs(cats.get(paired_cat, 0.0)) < 0.01, (
                f"{yr} {paired_cat} should sum to ~0 (paired legs), "
                f"got ${cats.get(paired_cat, 0.0):,.2f}"
            )

        # Mortgages debit + Loan Payments credit should also offset
        net_loan = cats.get("Mortgages", 0.0) + cats.get("Loan Payments", 0.0)
        assert abs(net_loan) < 0.01, (
            f"{yr}: Mortgages + Loan Payments should sum to ~0, got ${net_loan:,.2f}"
        )


# ── Test 9: 2024 design totals (income + spending bands) ────────────────────


def test_2024_design_totals(pinned_txns):
    """The generator's docstring promises specific full-year design totals.
    Pin them in 2024 (a fully-covered year) so the table never silently
    drifts."""
    actual = _per_year_category_totals(pinned_txns)[2024]

    # Income side: Alex biweekly $4000 × 26 = $104,000
    #              Jordan monthly $3500 × 12 = $42,000
    #              Total Paychecks/Salary = $146,000
    assert actual["Paychecks/Salary"] == 146000.0

    # HYSA interest $45 × 12 = $540
    assert actual["Interest"] == 540.0

    # Mortgage $1500 × 12 = -$18,000 paid out, +$18,000 received on the
    # loan account → net 0
    assert actual["Mortgages"] == -18000.0
    assert actual["Loan Payments"] == 18000.0

    # Utilities $200 × 12 = -$2,400
    assert actual["Utilities"] == -2400.0

    # Insurance $600 × 2 (semiannual) = -$1,200
    assert actual["Insurance"] == -1200.0


# ── Test 10: structural fixtures generate without errors ────────────────────


def test_structural_generators_smoke(pinned_txns):
    """generate_balance_snapshots / budgets / credit / investment / payroll
    must run cleanly for the pinned end-date and return non-empty lists."""
    snaps = generate_balance_snapshots(PIN_END_DATE, pinned_txns)
    assert isinstance(snaps, list) and len(snaps) > 0
    # Every account should appear at least once
    snap_accts = {s["account_id"] for s in snaps}
    expected_accts = {a["account_id"] for a in ACCOUNTS}
    assert snap_accts == expected_accts, (
        f"Snapshots missing accounts: {expected_accts - snap_accts}"
    )

    budgets = generate_budgets(PIN_END_DATE, PIN_YEARS)
    assert isinstance(budgets, list) and len(budgets) > 0

    import random
    rng = random.Random(20260115)
    credit = generate_credit_scores(PIN_END_DATE, PIN_YEARS, rng)
    assert isinstance(credit, list) and len(credit) > 0

    rng2 = random.Random(20260115)
    holdings, portfolio = generate_investment_history(PIN_END_DATE, PIN_YEARS, rng2)
    assert isinstance(holdings, list) and len(holdings) > 0
    assert isinstance(portfolio, list) and len(portfolio) > 0

    vehicles = generate_vehicle_valuations(PIN_END_DATE, PIN_YEARS)
    assert isinstance(vehicles, list)

    payroll = generate_payroll_snapshots(PIN_END_DATE, months=24)
    assert isinstance(payroll, list) and len(payroll) > 0


# ── Test 11: closure property — balances reconcile end-to-end ───────────────


def test_balance_closure_property(pinned_txns):
    """For every account, the final snapshot balance must equal:
        starting_balance + Σ signed_amount over the full window.
    """
    snaps = generate_balance_snapshots(PIN_END_DATE, pinned_txns)

    # Build account → final snapshot
    final_by_acct: dict[str, float] = {}
    for s in snaps:
        a = s["account_id"]
        d = s["date"]
        if a not in final_by_acct or d > final_by_acct.get(f"_d_{a}", ""):
            final_by_acct[a] = float(s["balance_amount"])
            final_by_acct[f"_d_{a}"] = d

    for acct in ACCOUNTS:
        a = acct["account_id"]
        if a not in final_by_acct:
            continue
        starting = float(acct["starting_balance"])
        delta = sum(
            float(t["signed_amount"]) for t in pinned_txns if t["account_id"] == a
        )
        expected = round(starting + delta, 2)
        actual_final = round(final_by_acct[a], 2)
        # Balance walker may emit final snapshot AT end_date if there are
        # txns; the snapshot value should match starting + delta within $0.01
        assert abs(actual_final - expected) < 0.01, (
            f"{a}: closure property violated. starting={starting}, "
            f"delta={delta}, expected_final={expected}, snapshot_final={actual_final}"
        )
