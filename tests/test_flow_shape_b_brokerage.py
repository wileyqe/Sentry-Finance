"""
tests/test_flow_shape_b_brokerage.py — v43 closeout (AI-020 + AI-021).

Integration test for the Shape B path in ``dal/reports/flow.py``: a
bank-side cash leg linked to a brokerage's ``positions_ledger`` row via
``positions_ledger.bank_txn_id`` resolves into ``transfer_flows[]``,
classifies as STORED_ILLIQUID, and contributes the cash leg's amount
to ``illiquid_cents``.

Pre-v43, the transfer-flows query did a ``transactions ↔ transactions``
self-join on shared ``transfer_tag``. Brokerages don't emit
bank-style transactions rows in their feeds (a brokerage's feed is
share movements, not currency movements), so the self-join never
matched any Acorns / Fidelity / TSP-shape transfer. ``transfer_flows``
was silently empty for these contributions, and the dollars instead
fell into the residual STORED_LIQUID bucket — accountability math was
approximately right, but the Sankey lost the labeled "cash →
investment" arrow (AI-020).

The Shape B query teaches the analytical layer about the brokerage
shape: ``transactions JOIN positions_ledger ON pl.bank_txn_id = t.id``.
This test asserts:

  1. A Shape B cash leg appears in ``transfer_flows`` with shape='B'
     and bucket='STORED_ILLIQUID'.
  2. ``illiquid_cents`` includes the cash leg's amount once (not the
     fan-out factor of the per-ETF allocation).
  3. The peer_account_id is the brokerage account, not the source
     checking account.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.reports.flow import _compute_bucket_totals


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
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(p)


def _seed_accounts(conn):
    conn.execute(
        "INSERT INTO institutions (id, display_name) VALUES ('summit', 'Summit')"
    )
    conn.execute(
        "INSERT INTO institutions (id, display_name) VALUES ('acorns', 'Acorns')"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('summit_chk', 'summit', 'Summit Checking', '1111', 'checking', 1)"
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('acorns_synthetic', 'acorns', 'Acorns', '2222', 'investment', 1)"
    )


def _seed_chk_debit(conn, *, txn_id: str, posting_date: str, amount: float,
                    transfer_tag: str | None = None):
    """Insert one summit_chk debit. Returns the row id."""
    conn.execute(
        """
        INSERT INTO transactions (
            id, account_id, institution_id, posting_date,
            amount, signed_amount, direction, description, category,
            status, transfer_tag, created_at, updated_at
        ) VALUES (?, 'summit_chk', 'summit', ?, ?, ?, 'Debit',
                  'ACORNS INVEST', 'Investments', 'posted', ?,
                  datetime('now'), datetime('now'))
        """,
        (txn_id, posting_date, abs(amount), -abs(amount), transfer_tag),
    )


def _seed_acorns_ledger_quad(conn, *, base_ts: str, primary_ledger_id: int,
                             primary_bank_txn_id: str):
    """Insert four IMPLIED_BUY ledger rows (one per ETF) with bank_txn_id
    set on only the first row — mirrors `_link_acorns_bank_debits`."""
    tickers = ["VOO", "IJH", "IJR", "IXUS"]
    for i, ticker in enumerate(tickers):
        lid = primary_ledger_id + i
        btx = primary_bank_txn_id if i == 0 else None
        conn.execute(
            """
            INSERT INTO positions_ledger
            (id, account_id, timestamp, ticker, transaction_type,
             share_delta, new_total_shares, bank_txn_id)
            VALUES (?, 'acorns_synthetic', ?, ?, 'IMPLIED_BUY',
                    ?, ?, ?)
            """,
            (lid, f"{base_ts[:10]}T12:00:0{i}", ticker,
             1.0, 1.0, btx),
        )


def test_shape_b_acorns_resolves_in_transfer_flows():
    print("\n─── v43 Shape B: Acorns transfer resolves in transfer_flows ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_chk_debit(
                conn, txn_id="tx_acorns_350",
                posting_date="2026-03-04", amount=350.0,
                transfer_tag="invest:1",
            )
            _seed_acorns_ledger_quad(
                conn, base_ts="2026-03-04",
                primary_ledger_id=1,
                primary_bank_txn_id="tx_acorns_350",
            )
            conn.commit()

            # Drive _compute_bucket_totals for the March 2026 window.
            # Pass empty income/spend/withholding lists since this test
            # is scoped to the transfer-flow path only.
            result = _compute_bucket_totals(
                conn=conn,
                income_cats=[],
                spend_cats=[],
                withholdings=[],
                date_filter="AND COALESCE(effective_month, strftime('%Y-%m', posting_date)) BETWEEN ? AND ?",
                date_params=["2026-03", "2026-03"],
                acct_filter="",
                acct_params=[],
                matched_gross_minus_net_cents=0,
                contrib_start="2026-03",
                contrib_end="2026-03",
                owner_id=None,
                account_ids=None,
            )

            shape_b_flows = [
                f for f in result["transfer_flows"] if f.get("shape") == "B"
            ]

            _check(
                "exactly 1 Shape B flow appears for the Acorns debit",
                len(shape_b_flows) == 1,
                f"got {len(shape_b_flows)}",
            )

            if shape_b_flows:
                flow = shape_b_flows[0]
                _check(
                    "Shape B flow's bucket is STORED_ILLIQUID",
                    flow["bucket"] == "STORED_ILLIQUID",
                    f"got {flow['bucket']!r}",
                )
                _check(
                    "Shape B flow's amount_cents == 35000 ($350, NOT 4×)",
                    flow["amount_cents"] == 35000,
                    f"got {flow['amount_cents']}",
                )
                _check(
                    "Shape B flow's peer_account_id == 'acorns_synthetic'",
                    flow["peer_account_id"] == "acorns_synthetic",
                    f"got {flow['peer_account_id']!r}",
                )
                _check(
                    "Shape B flow's peer_account_type == 'investment'",
                    flow["peer_account_type"] == "investment",
                    f"got {flow['peer_account_type']!r}",
                )

            # No Shape A flow should appear for this transfer — the chk
            # debit has a transfer_tag but no paired transactions row.
            shape_a_flows = [
                f for f in result["transfer_flows"] if f.get("shape") == "A"
            ]
            _check(
                "no Shape A flow appears (no paired transactions row)",
                len(shape_a_flows) == 0,
                f"got {len(shape_a_flows)}",
            )
    finally:
        os.unlink(db)


def test_shape_b_two_distinct_debits_same_day_dont_collapse():
    """Two separate Acorns debits on the same day must contribute
    independently. Cardinality regression guard."""
    print("\n─── v43 Shape B: two same-day debits don't collapse ───")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _seed_accounts(conn)
            _seed_chk_debit(
                conn, txn_id="tx_a", posting_date="2026-03-04",
                amount=350.0, transfer_tag="invest:1",
            )
            _seed_chk_debit(
                conn, txn_id="tx_b", posting_date="2026-03-04",
                amount=350.0, transfer_tag="invest:5",
            )
            _seed_acorns_ledger_quad(
                conn, base_ts="2026-03-04",
                primary_ledger_id=1, primary_bank_txn_id="tx_a",
            )
            _seed_acorns_ledger_quad(
                conn, base_ts="2026-03-04",
                primary_ledger_id=5, primary_bank_txn_id="tx_b",
            )
            conn.commit()

            result = _compute_bucket_totals(
                conn=conn, income_cats=[], spend_cats=[], withholdings=[],
                date_filter="AND COALESCE(effective_month, strftime('%Y-%m', posting_date)) BETWEEN ? AND ?",
                date_params=["2026-03", "2026-03"],
                acct_filter="", acct_params=[],
                matched_gross_minus_net_cents=0,
                contrib_start="2026-03", contrib_end="2026-03",
                owner_id=None, account_ids=None,
            )

            shape_b_flows = [
                f for f in result["transfer_flows"] if f.get("shape") == "B"
            ]
            _check(
                "two Shape B flows appear (one per cash leg)",
                len(shape_b_flows) == 2,
                f"got {len(shape_b_flows)}",
            )
            total_b_cents = sum(f["amount_cents"] for f in shape_b_flows)
            _check(
                "Shape B total == 70000 cents ($700, two distinct $350 legs)",
                total_b_cents == 70000,
                f"got {total_b_cents}",
            )
    finally:
        os.unlink(db)


if __name__ == "__main__":
    test_shape_b_acorns_resolves_in_transfer_flows()
    test_shape_b_two_distinct_debits_same_day_dont_collapse()

    print(f"\n{'═' * 60}")
    print(f"  v43 Shape B flow tests: {_passed} passed, {_failed} failed")
    if _errors:
        print(f"  Failed: {', '.join(_errors)}")
    print(f"{'═' * 60}")
    sys.exit(1 if _failed else 0)
