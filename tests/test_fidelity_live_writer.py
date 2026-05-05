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
        marker = conn.execute(
            """SELECT id FROM positions_ledger
               WHERE account_id = ? AND source = ? AND transaction_type = 'DEPOSIT'
               ORDER BY timestamp LIMIT 1""",
            (ACCOUNT_ID, FIDELITY_LEDGER_SOURCE),
        ).fetchone()
        conn.execute(
            "UPDATE positions_ledger SET bank_txn_id = 'bank_txn_1' WHERE id = ?",
            (marker["id"],),
        )
        conn.commit()

    first_counts = _table_counts(db)
    _write_fixture_state(db, fidelity_fixture_state)
    second_counts = _table_counts(db)

    with get_db(db) as conn:
        preserved = conn.execute(
            "SELECT bank_txn_id FROM positions_ledger WHERE id = ?",
            (marker["id"],),
        ).fetchone()["bank_txn_id"]

    assert second_counts == first_counts
    assert preserved == "bank_txn_1"


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
        cost_basis_claims = conn.execute(
            """SELECT COUNT(*) FROM positions_ledger
               WHERE account_id = ? AND source = ? AND cost_basis_dec IS NOT NULL""",
            (ACCOUNT_ID, FIDELITY_LEDGER_SOURCE),
        ).fetchone()[0]
        holdings_cost_basis_claims = conn.execute(
            """SELECT COUNT(*) FROM investment_holdings
               WHERE account_id = ? AND cost_basis IS NOT NULL""",
            (ACCOUNT_ID,),
        ).fetchone()[0]

    assert cash_holdings == 0
    assert cash_security_ledger == 0
    assert cost_basis_claims == 0
    assert holdings_cost_basis_claims == 0


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

    assert row["settlement_date"] == "02/07/2024"


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
