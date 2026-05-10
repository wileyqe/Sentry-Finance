from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import get_db, init_db  # noqa: E402
from dal.fidelity_investment_writes import (  # noqa: E402
    EFT_MARKER_TICKER,
    FIDELITY_LEDGER_SOURCE,
    write_fidelity_investment_state,
)
from scripts.ingest_fidelity_history import (  # noqa: E402
    parse_history_csv,
    parse_positions_csv,
    reconstruct_daily_ledger,
)


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "fidelity"
ACCOUNT_ID = "fidelity_brokerage"


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    p = Path(path)
    init_db(p)
    with get_db(p) as conn:
        conn.execute(
            "INSERT INTO institutions (id, display_name) VALUES ('fidelity','Fidelity')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type) "
            "VALUES (?, 'fidelity', 'Fidelity Brokerage', '1234', 'investment')",
            (ACCOUNT_ID,),
        )
        conn.commit()
    yield p
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture(scope="module")
def fidelity_fixture_state():
    history_frames = [
        parse_history_csv(path)
        for path in sorted(FIXTURE_DIR.glob("history_*_redacted.csv"))
    ]
    history = pd.concat(history_frames, ignore_index=True).sort_values("Run Date")
    positions = parse_positions_csv(FIXTURE_DIR / "positions_mar_04_2026_redacted.csv")
    daily, _tickers = reconstruct_daily_ledger(history.copy(), positions)
    return history, positions, _snapshot_from_daily(daily, positions)


def _snapshot_from_daily(daily: pd.DataFrame, positions: pd.DataFrame) -> pd.DataFrame:
    snapshot = daily.copy()
    price_by_ticker = {
        row["Symbol"].upper(): float(row["Last Price"] or 0.0)
        for _, row in positions.iterrows()
        if str(row["Symbol"]).upper() not in {"SPAXX", "FDRXX"}
    }
    value_columns = []
    for shares_col in [col for col in snapshot.columns if col.endswith("_Shares")]:
        ticker = shares_col.removesuffix("_Shares").upper()
        price = price_by_ticker.get(ticker, 0.0)
        price_col = f"{ticker}_ClosePrice"
        value_col = f"{ticker}_Value"
        snapshot[price_col] = price
        snapshot[value_col] = (snapshot[shares_col].astype(float) * price).round(2)
        value_columns.append(value_col)

    snapshot["Total_Equity_Value"] = snapshot[value_columns].sum(axis=1).round(2)
    snapshot["Total_Account_Value"] = (
        snapshot["Total_Equity_Value"] + snapshot["Cash_Balance"].astype(float)
    ).round(2)
    return snapshot


def _write_fixture_state(db: Path, fidelity_fixture_state):
    history, positions, snapshot = fidelity_fixture_state
    with get_db(db) as conn:
        result = write_fidelity_investment_state(
            conn,
            account_id=ACCOUNT_ID,
            history=history,
            positions=positions,
            snapshot=snapshot,
        )
        conn.commit()
    return result


def test_fidelity_writer_persists_holdings_snapshots_and_ledger_rows(
    db,
    fidelity_fixture_state,
):
    history, _positions, snapshot = fidelity_fixture_state

    result = _write_fixture_state(db, fidelity_fixture_state)

    expected_tickers = {
        col.removesuffix("_Shares")
        for col in snapshot.columns
        if col.endswith("_Shares") and not col.startswith(("SPAXX", "FDRXX"))
    }
    expected_security_events = history[
        history["Action_Type"].isin(["BOUGHT", "REINVESTMENT", "EXPIRED", "SOLD"])
        & ~history["Symbol"].isin(["SPAXX", "FDRXX", ""])
    ]
    expected_eft_events = history[history["Action_Type"].isin(["DEPOSIT", "WITHDRAWAL"])]
    expected_baselines = len(
        [
            ticker
            for ticker in expected_tickers
            if float(snapshot.iloc[0][f"{ticker}_Shares"]) > 0
        ]
    )

    with get_db(db) as conn:
        holding_count = conn.execute(
            "SELECT COUNT(*) FROM investment_holdings WHERE account_id = ?",
            (ACCOUNT_ID,),
        ).fetchone()[0]
        snapshot_count = conn.execute(
            "SELECT COUNT(*) FROM portfolio_snapshots WHERE account_id = ?",
            (ACCOUNT_ID,),
        ).fetchone()[0]
        ledger_count = conn.execute(
            "SELECT COUNT(*) FROM positions_ledger WHERE account_id = ? AND source = ?",
            (ACCOUNT_ID, FIDELITY_LEDGER_SOURCE),
        ).fetchone()[0]

    assert result == {
        "holdings": len(snapshot) * len(expected_tickers),
        "snapshots": len(snapshot),
        "ledger_rows": expected_baselines
        + len(expected_security_events)
        + len(expected_eft_events),
    }
    assert holding_count == result["holdings"]
    assert snapshot_count == result["snapshots"]
    assert ledger_count == result["ledger_rows"]


def test_fidelity_writer_is_idempotent_and_preserves_existing_bank_links(
    db,
    fidelity_fixture_state,
):
    _write_fixture_state(db, fidelity_fixture_state)
    with get_db(db) as conn:
        deposit_marker = conn.execute(
            """SELECT id FROM positions_ledger
               WHERE account_id = ? AND source = ? AND transaction_type = 'DEPOSIT'
               ORDER BY timestamp LIMIT 1""",
            (ACCOUNT_ID, FIDELITY_LEDGER_SOURCE),
        ).fetchone()
        buy_marker = conn.execute(
            """SELECT id FROM positions_ledger
               WHERE account_id = ? AND source = ? AND transaction_type = 'BUY'
               ORDER BY timestamp LIMIT 1""",
            (ACCOUNT_ID, FIDELITY_LEDGER_SOURCE),
        ).fetchone()
        conn.execute(
            "UPDATE positions_ledger SET bank_txn_id = 'bank_txn_1' WHERE id = ?",
            (deposit_marker["id"],),
        )
        conn.execute(
            "UPDATE positions_ledger SET bank_txn_id = 'bank_txn_2' WHERE id = ?",
            (buy_marker["id"],),
        )
        conn.commit()

    first_counts = _table_counts(db)
    _write_fixture_state(db, fidelity_fixture_state)
    second_counts = _table_counts(db)

    with get_db(db) as conn:
        preserved_deposit = conn.execute(
            "SELECT bank_txn_id FROM positions_ledger WHERE id = ?",
            (deposit_marker["id"],),
        ).fetchone()["bank_txn_id"]
        preserved_buy = conn.execute(
            "SELECT bank_txn_id FROM positions_ledger WHERE id = ?",
            (buy_marker["id"],),
        ).fetchone()["bank_txn_id"]

    assert second_counts == first_counts
    assert preserved_deposit == "bank_txn_1"
    assert preserved_buy == "bank_txn_2"


def _table_counts(db: Path) -> dict[str, int]:
    with get_db(db) as conn:
        return {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE account_id = ?",
                (ACCOUNT_ID,),
            ).fetchone()[0]
            for table in [
                "investment_holdings",
                "portfolio_snapshots",
                "positions_ledger",
            ]
        }


def test_fidelity_writer_maps_canonical_actions_and_eft_markers(
    db,
    fidelity_fixture_state,
):
    _write_fixture_state(db, fidelity_fixture_state)

    with get_db(db) as conn:
        action_types = {
            row["transaction_type"]
            for row in conn.execute(
                """SELECT transaction_type FROM positions_ledger
                   WHERE account_id = ? AND source = ?""",
                (ACCOUNT_ID, FIDELITY_LEDGER_SOURCE),
            ).fetchall()
        }
        eft_rows = conn.execute(
            """SELECT ticker, transaction_type, share_delta, new_total_shares,
                      bank_txn_id, estimated_transaction_value
               FROM positions_ledger
               WHERE account_id = ? AND source = ?
                 AND transaction_type IN ('DEPOSIT', 'WITHDRAWAL')
               ORDER BY transaction_type""",
            (ACCOUNT_ID, FIDELITY_LEDGER_SOURCE),
        ).fetchall()

    assert {"INITIAL_BASELINE", "BUY", "REINVESTMENT", "EXPIRED"} <= action_types
    assert {row["transaction_type"] for row in eft_rows} == {"DEPOSIT", "WITHDRAWAL"}
    for row in eft_rows:
        assert row["ticker"] == EFT_MARKER_TICKER
        assert row["share_delta"] == 0.0
        assert row["new_total_shares"] == 0.0
        assert row["bank_txn_id"] is None
        assert row["estimated_transaction_value"] != 0.0


def test_fidelity_writer_keeps_cash_equivalents_out_of_holdings_and_ledger(
    db,
    fidelity_fixture_state,
):
    """Contract: SPAXX/FDRXX never receive equity rows or cost basis,
    and ``positions_ledger.cost_basis_dec`` stays null until evidenced
    by trade/reinvestment receipts (P17-T30 / P17-T32)."""
    _write_fixture_state(db, fidelity_fixture_state)

    with get_db(db) as conn:
        cash_holdings = conn.execute(
            """SELECT COUNT(*) FROM investment_holdings
               WHERE account_id = ? AND ticker IN ('SPAXX', 'FDRXX')""",
            (ACCOUNT_ID,),
        ).fetchone()[0]
        cash_security_ledger = conn.execute(
            """SELECT COUNT(*) FROM positions_ledger
               WHERE account_id = ? AND ticker IN ('SPAXX', 'FDRXX')""",
            (ACCOUNT_ID,),
        ).fetchone()[0]
        ledger_cost_basis_claims = conn.execute(
            """SELECT COUNT(*) FROM positions_ledger
               WHERE account_id = ? AND source = ? AND cost_basis_dec IS NOT NULL""",
            (ACCOUNT_ID, FIDELITY_LEDGER_SOURCE),
        ).fetchone()[0]
        cash_holdings_cost_basis_claims = conn.execute(
            """SELECT COUNT(*) FROM investment_holdings
               WHERE account_id = ? AND ticker IN ('SPAXX', 'FDRXX')
                 AND cost_basis IS NOT NULL""",
            (ACCOUNT_ID,),
        ).fetchone()[0]

    assert cash_holdings == 0
    assert cash_security_ledger == 0
    # Ledger basis remains evidence-based (trade/reinvest only) — the
    # Positions CSV provides per-position basis, not lot-forming basis.
    assert ledger_cost_basis_claims == 0
    # And cash equivalents never receive basis even via the new path.
    assert cash_holdings_cost_basis_claims == 0


def test_fidelity_writer_persists_per_position_cost_basis_on_holdings(
    db,
    fidelity_fixture_state,
):
    """P17-T30 / FID-LS-006: live Fidelity per-position basis must reach
    ``investment_holdings.cost_basis`` for non-cash positions that hold
    shares; SPAXX/FDRXX must remain blank-basis cash sweeps."""
    _, positions, _ = fidelity_fixture_state
    _write_fixture_state(db, fidelity_fixture_state)

    expected = {
        str(row["Symbol"]).upper(): float(row["Cost Basis Total"])
        for _, row in positions.iterrows()
        if str(row["Symbol"]).upper() not in {"SPAXX", "FDRXX", ""}
    }

    with get_db(db) as conn:
        latest_date = conn.execute(
            "SELECT MAX(date) FROM investment_holdings WHERE account_id = ?",
            (ACCOUNT_ID,),
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT ticker, shares, cost_basis FROM investment_holdings
               WHERE account_id = ? AND date = ?""",
            (ACCOUNT_ID, latest_date),
        ).fetchall()

    holdings_by_ticker = {r["ticker"]: r for r in rows}

    # Every non-cash ticker the fixture currently holds (>0 shares on
    # the latest snapshot row) must carry the Positions CSV basis.
    for ticker, basis in expected.items():
        assert ticker in holdings_by_ticker, (
            f"{ticker} expected in latest holdings"
        )
        held = holdings_by_ticker[ticker]
        if held["shares"] > 0:
            assert held["cost_basis"] == pytest.approx(basis, abs=0.01), (
                f"{ticker} cost_basis mismatch: "
                f"{held['cost_basis']!r} vs {basis!r}"
            )

    # And the ledger remains evidence-based.
    with get_db(db) as conn:
        ledger_basis = conn.execute(
            """SELECT COUNT(*) FROM positions_ledger
               WHERE account_id = ? AND source = ? AND cost_basis_dec IS NOT NULL""",
            (ACCOUNT_ID, FIDELITY_LEDGER_SOURCE),
        ).fetchone()[0]
    assert ledger_basis == 0


def test_fidelity_writer_does_not_emit_basis_for_zero_share_baseline_rows(
    db,
    fidelity_fixture_state,
):
    """A reconstructed-history row with zero shares for a ticker must
    not stamp cost basis — basis only attaches when the position
    actually holds shares on that date."""
    _write_fixture_state(db, fidelity_fixture_state)

    with get_db(db) as conn:
        zero_share_with_basis = conn.execute(
            """SELECT COUNT(*) FROM investment_holdings
               WHERE account_id = ? AND shares = 0 AND cost_basis IS NOT NULL""",
            (ACCOUNT_ID,),
        ).fetchone()[0]
    assert zero_share_with_basis == 0


def test_fidelity_writer_falls_back_to_average_cost_when_total_is_blank(
    db,
    fidelity_fixture_state,
):
    """P17-T30: when ``Cost Basis Total`` is blank but
    ``Average Cost Basis`` and ``Quantity`` are present, the writer
    should derive the per-position basis from the fallback signal
    rather than dropping basis entirely."""
    import numpy as np

    history, positions, snapshot = fidelity_fixture_state
    fallback = positions.copy()
    target_idx = fallback.index[fallback["Symbol"].eq("AAPL")][0]
    # Simulate a Fidelity export where Cost Basis Total is missing for
    # a non-cash position but Average Cost Basis is still populated.
    # Parser already coerced these columns to float; use NaN to mimic
    # blank cells in the cleaned frame.
    fallback.loc[target_idx, "Cost Basis Total"] = np.nan
    fallback.loc[target_idx, "Average Cost Basis"] = 95.0
    # Quantity column was already cleaned to a float earlier in the
    # parser path; confirm it still exposes a usable value.
    fallback.loc[target_idx, "Quantity"] = 10.0

    with get_db(db) as conn:
        write_fidelity_investment_state(
            conn,
            account_id=ACCOUNT_ID,
            history=history,
            positions=fallback,
            snapshot=snapshot,
        )
        conn.commit()
        latest_date = conn.execute(
            "SELECT MAX(date) FROM investment_holdings WHERE account_id = ?",
            (ACCOUNT_ID,),
        ).fetchone()[0]
        aapl = conn.execute(
            """SELECT cost_basis FROM investment_holdings
               WHERE account_id = ? AND date = ? AND ticker = 'AAPL'""",
            (ACCOUNT_ID, latest_date),
        ).fetchone()

    assert aapl["cost_basis"] == pytest.approx(950.0, abs=0.01)


def test_fidelity_writer_preserves_settlement_dates_when_present(
    db,
    fidelity_fixture_state,
):
    _write_fixture_state(db, fidelity_fixture_state)

    with get_db(db) as conn:
        row = conn.execute(
            """SELECT settlement_date FROM positions_ledger
               WHERE account_id = ? AND source = ?
                 AND ticker = 'AAPL' AND transaction_type = 'BUY'""",
            (ACCOUNT_ID, FIDELITY_LEDGER_SOURCE),
        ).fetchone()

    assert row["settlement_date"] == "2024-02-07"


def test_fidelity_writer_rejects_multi_account_positions_export(
    db,
    fidelity_fixture_state,
):
    history, positions, snapshot = fidelity_fixture_state
    multi = positions.copy()
    multi.loc[multi.index[0], "Account Number"] = "X<other>"

    with get_db(db) as conn:
        with pytest.raises(ValueError, match="multiple account numbers"):
            write_fidelity_investment_state(
                conn,
                account_id=ACCOUNT_ID,
                history=history,
                positions=multi,
                snapshot=snapshot,
            )
