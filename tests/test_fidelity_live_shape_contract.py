from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ingest_fidelity_history import (  # noqa: E402
    _classify_action,
    parse_history_csv,
    parse_positions_csv,
)


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "fidelity"

HISTORY_COLUMNS = [
    "Run Date",
    "Action",
    "Symbol",
    "Description",
    "Type",
    "Price ($)",
    "Quantity",
    "Commission ($)",
    "Fees ($)",
    "Accrued Interest ($)",
    "Amount ($)",
    "Cash Balance ($)",
    "Settlement Date",
]

POSITIONS_COLUMNS = [
    "Account Number",
    "Account Name",
    "Symbol",
    "Description",
    "Quantity",
    "Last Price",
    "Last Price Change",
    "Current Value",
    "Today's Gain/Loss Dollar",
    "Today's Gain/Loss Percent",
    "Total Gain/Loss Dollar",
    "Total Gain/Loss Percent",
    "Percent Of Account",
    "Cost Basis Total",
    "Average Cost Basis",
    "Type",
]

OBSERVED_ACTION_VERBS = {
    "CAP GAIN",
    "DIVIDEND RECEIVED",
    "ELECTRONIC FUNDS TRANSFER PAID",
    "ELECTRONIC FUNDS TRANSFER RECEIVED",
    "EXPIRED",
    "REINVESTMENT",
    "YOU BOUGHT",
}


def _history_files() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("history_*_redacted.csv"))


def _history_header_index(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if "Run Date" in line:
            return index
    raise AssertionError(f"{path.name} has no history header")


def _read_history_rows(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header_index = _history_header_index(path)
    rows = list(csv.DictReader(lines[header_index:]))
    return [
        row
        for row in rows
        if re.match(r"\d{2}/\d{2}/\d{4}", (row.get("Run Date") or "").strip())
    ]


def _action_verb(action: str) -> str:
    action_upper = action.upper().strip()
    if "YOU BOUGHT" in action_upper:
        return "YOU BOUGHT"
    if "REINVESTMENT" in action_upper:
        return "REINVESTMENT"
    if "YOU SOLD" in action_upper:
        return "YOU SOLD"
    if "DIVIDEND RECEIVED" in action_upper:
        return "DIVIDEND RECEIVED"
    if "CAP GAIN" in action_upper:
        return "CAP GAIN"
    if "ELECTRONIC FUNDS TRANSFER RECEIVED" in action_upper:
        return "ELECTRONIC FUNDS TRANSFER RECEIVED"
    if "ELECTRONIC FUNDS TRANSFER PAID" in action_upper:
        return "ELECTRONIC FUNDS TRANSFER PAID"
    if "EXPIRED" in action_upper:
        return "EXPIRED"
    return "OTHER"


def test_history_fixtures_preserve_column_order_header_noise_and_footer_noise():
    for path in _history_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        header_index = _history_header_index(path)
        assert header_index == 2
        assert lines[header_index].split(",") == HISTORY_COLUMNS

        all_rows = list(csv.DictReader(lines[header_index:]))
        valid_rows = _read_history_rows(path)
        assert valid_rows
        assert len(all_rows) > len(valid_rows)

        for row in valid_rows:
            assert list(row) == HISTORY_COLUMNS
            assert row["Description"]


def test_positions_fixture_preserves_column_order_redaction_and_cash_sweep_shape():
    path = FIXTURE_DIR / "positions_mar_04_2026_redacted.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert rows
    assert list(rows[0]) == POSITIONS_COLUMNS
    assert {row["Account Number"] for row in rows} == {"X<redacted>"}

    spaxx_rows = [
        row for row in rows if row["Symbol"].replace("*", "").upper() == "SPAXX"
    ]
    assert len(spaxx_rows) == 1
    spaxx = spaxx_rows[0]
    assert spaxx["Cost Basis Total"] == ""
    assert spaxx["Average Cost Basis"] == ""
    assert spaxx["Current Value"].endswith(" ")


def test_observed_action_verbs_are_represented_in_redacted_history_fixtures():
    observed = {
        _action_verb(row["Action"])
        for path in _history_files()
        for row in _read_history_rows(path)
    }
    assert OBSERVED_ACTION_VERBS <= observed


def test_current_history_parser_classifies_observed_verbs_without_other_bucket():
    parsed = [parse_history_csv(path) for path in _history_files()]
    action_types = set()
    for frame in parsed:
        action_types.update(frame["Action_Type"].dropna().unique())

    assert {
        "BOUGHT",
        "DEPOSIT",
        "DIVIDEND",
        "EXPIRED",
        "REINVESTMENT",
        "WITHDRAWAL",
    } <= action_types
    assert "OTHER" not in action_types


def test_parser_already_classifies_plausible_unobserved_sell_verbs():
    assert _classify_action("YOU SOLD DUMMY LARGE CAP INC (AAPL) (Cash)") == "SOLD"


def test_spaxx_dividend_and_reinvestment_pair_is_structurally_distinguishable():
    parsed = [parse_history_csv(path) for path in _history_files()]
    spaxx_rows = []
    for frame in parsed:
        spaxx_rows.extend(
            frame[frame["Symbol"].str.upper().eq("SPAXX")][
                ["Action", "Action_Type", "Quantity", "Amount ($)"]
            ].to_dict("records")
        )

    assert any(row["Action_Type"] == "DIVIDEND" for row in spaxx_rows)
    assert any(row["Action_Type"] == "REINVESTMENT" for row in spaxx_rows)
    assert any(row["Quantity"] > 0 for row in spaxx_rows)


def test_fractional_share_precision_survives_current_history_parser():
    parsed = [parse_history_csv(path) for path in _history_files()]
    bought_quantities = []
    for frame in parsed:
        buys = frame[frame["Action_Type"].eq("BOUGHT")]
        bought_quantities.extend(float(value) for value in buys["Quantity"])

    assert any(abs(quantity - 0.196) < 0.000001 for quantity in bought_quantities)
    assert any(abs(quantity - 0.755) < 0.000001 for quantity in bought_quantities)


def test_positions_parser_keeps_spaxx_cash_sweep_distinguishable():
    frame = parse_positions_csv(FIXTURE_DIR / "positions_mar_04_2026_redacted.csv")
    assert set(frame["Symbol"]) >= {"SPAXX", "AAPL", "VOO", "QQQM", "MSFT"}

    spaxx = frame[frame["Symbol"].eq("SPAXX")].iloc[0]
    assert spaxx["Current Value"] == 500.0
    assert spaxx["Cost Basis Total"] == 0.0
    assert spaxx["Average Cost Basis"] == 0.0


def test_dividend_rows_emit_investment_income_via_writer():
    """FID-LS-005: dividend/cap-gain rows produce Investment Income transactions
    via the income writer (replaces parser-level xfail)."""
    import os
    import tempfile

    from dal.database import init_db, get_db
    from dal.fidelity_dividend_income import write_fidelity_dividend_income
    from dal.owners import create_owner

    frame = parse_history_csv(FIXTURE_DIR / "history_2025_redacted.csv")
    dividend_rows = frame[frame["Action_Type"].eq("DIVIDEND")]
    assert not dividend_rows.empty, "Fixture must contain DIVIDEND rows"

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(Path(db_path))
        with get_db(Path(db_path)) as conn:
            create_owner(conn, "quintin", "Quintin")
            conn.execute(
                "INSERT OR IGNORE INTO institutions (id, display_name) "
                "VALUES ('fidelity', 'Fidelity')"
            )
            conn.execute(
                "INSERT INTO accounts (id, institution_id, name, type, last4, owner_id) "
                "VALUES ('fid_brok', 'fidelity', 'Fidelity Brokerage', 'investment', '0000', 'quintin')"
            )
            result = write_fidelity_dividend_income(
                conn, account_id="fid_brok", history=frame,
            )
            conn.commit()
            assert result["written"] == len(dividend_rows), (
                f"Expected {len(dividend_rows)} written, got {result['written']}"
            )
            txns = conn.execute(
                "SELECT category FROM transactions WHERE category = 'Investment Income'"
            ).fetchall()
            assert len(txns) == len(dividend_rows)
            assert all(t["category"] == "Investment Income" for t in txns)
    finally:
        os.unlink(db_path)


def test_positions_parser_handles_parenthesized_negative_currency_values():
    """FID-LS-011: parenthesized negatives in Fidelity Positions CSV
    (used for losses in Total Gain/Loss Dollar) must round-trip as
    negative numbers, not zeros."""
    frame = parse_positions_csv(FIXTURE_DIR / "positions_mar_04_2026_redacted.csv")
    msft = frame[frame["Symbol"].eq("MSFT")].iloc[0]
    assert msft["Total Gain/Loss Dollar"] == -25.0


def test_clean_number_covers_fidelity_money_format_edge_cases():
    """P17-T30 / FID-LS-011: ``_clean_number`` must tolerate every
    money format observed in live Fidelity Positions CSVs."""
    from scripts.ingest_fidelity_history import _clean_number

    # SPAXX/FDRXX blanks
    assert _clean_number("") == 0.0
    assert _clean_number(" ") == 0.0
    assert _clean_number(None) == 0.0
    # Comma + dollar grouping with trailing space
    assert _clean_number("$1,000.00 ") == 1000.0
    # Wrapping double quotes (csv quote artifact)
    assert _clean_number('"$1,234.56"') == 1234.56
    # Parenthesized negatives — raw and decorated
    assert _clean_number("($25.00)") == -25.0
    assert _clean_number("($1,234.56)") == -1234.56
    # ``Processing`` sentinel
    assert _clean_number("Processing") == 0.0


def test_fidelity_writer_replaces_loan_details_cost_basis_path(tmp_path):
    """P17-T30 / FID-LS-006: per-position cost basis must reach
    ``investment_holdings.cost_basis`` directly. The legacy aggregate
    write to ``loan_details.cost_basis`` must no longer be emitted by
    the live Fidelity ingest path."""
    import os
    import tempfile

    from dal.database import get_db, init_db
    from dal.fidelity_investment_writes import write_fidelity_investment_state
    from scripts.ingest_fidelity_history import (
        parse_history_csv,
        parse_positions_csv,
        reconstruct_daily_ledger,
    )

    history_frames = [
        parse_history_csv(path) for path in _history_files()
    ]
    history = (
        __import__("pandas").concat(history_frames, ignore_index=True)
        .sort_values("Run Date")
    )
    positions = parse_positions_csv(
        FIXTURE_DIR / "positions_mar_04_2026_redacted.csv"
    )
    daily, _ = reconstruct_daily_ledger(history.copy(), positions)

    # Build a snapshot frame with prices/values from the positions CSV
    # so the writer's invariant (mv ≈ shares*price) holds.
    snapshot = daily.copy()
    price_by_ticker = {
        str(r["Symbol"]).upper(): float(r["Last Price"] or 0.0)
        for _, r in positions.iterrows()
        if str(r["Symbol"]).upper() not in {"SPAXX", "FDRXX"}
    }
    value_columns = []
    for col in [c for c in snapshot.columns if c.endswith("_Shares")]:
        ticker = col.removesuffix("_Shares").upper()
        price = price_by_ticker.get(ticker, 0.0)
        snapshot[f"{ticker}_ClosePrice"] = price
        snapshot[f"{ticker}_Value"] = (
            snapshot[col].astype(float) * price
        ).round(2)
        value_columns.append(f"{ticker}_Value")
    snapshot["Total_Equity_Value"] = snapshot[value_columns].sum(axis=1).round(2)
    snapshot["Total_Account_Value"] = (
        snapshot["Total_Equity_Value"] + snapshot["Cash_Balance"].astype(float)
    ).round(2)

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(__import__("pathlib").Path(db_path))
        with get_db(__import__("pathlib").Path(db_path)) as conn:
            conn.execute(
                "INSERT INTO institutions (id, display_name) VALUES ('fidelity','Fidelity')"
            )
            conn.execute(
                "INSERT INTO accounts (id, institution_id, name, last4, type) "
                "VALUES ('fid_brok', 'fidelity', 'Fidelity', '0000', 'investment')"
            )
            write_fidelity_investment_state(
                conn,
                account_id="fid_brok",
                history=history,
                positions=positions,
                snapshot=snapshot,
            )
            conn.commit()

            # The investments source-of-truth path is populated …
            with_basis = conn.execute(
                """SELECT COUNT(*) FROM investment_holdings
                   WHERE account_id = 'fid_brok' AND cost_basis IS NOT NULL"""
            ).fetchone()[0]
            assert with_basis > 0

            # … and the legacy aggregate ``loan_details.cost_basis`` row
            # is NOT emitted by the live writer path.
            legacy_rows = conn.execute(
                """SELECT COUNT(*) FROM loan_details
                   WHERE account_id = 'fid_brok' AND field_name = 'cost_basis'"""
            ).fetchone()[0]
            assert legacy_rows == 0
    finally:
        os.unlink(db_path)


def test_fidelity_connector_no_longer_writes_loan_details_cost_basis():
    """P17-T30: the connector's positions-CSV ingest path must not
    contain a ``record_loan_details(... 'cost_basis' ...)`` call.

    Quarantines the legacy aggregate Fidelity write so a future
    refactor cannot silently re-introduce it."""
    from pathlib import Path as _Path

    connector_src = (
        _Path(__file__).resolve().parents[1]
        / "extractors"
        / "fidelity_connector.py"
    ).read_text(encoding="utf-8")
    assert "record_loan_details" not in connector_src, (
        "fidelity_connector.py must not call record_loan_details — "
        "per-position cost basis lives on investment_holdings.cost_basis."
    )
