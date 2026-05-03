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


@pytest.mark.xfail(
    reason="FID-LS-005: current history parser does not emit Investment Income transactions",
    strict=True,
)
def test_dividend_rows_emit_investment_income_category_when_parsed():
    frame = parse_history_csv(FIXTURE_DIR / "history_2025_redacted.csv")
    dividend_rows = frame[frame["Action_Type"].eq("DIVIDEND")]
    assert not dividend_rows.empty
    assert set(dividend_rows["Category"]) == {"Investment Income"}


@pytest.mark.xfail(
    reason="FID-LS-011: _clean_number treats parenthesized negatives as zero",
    strict=True,
)
def test_positions_parser_handles_parenthesized_negative_currency_values():
    frame = parse_positions_csv(FIXTURE_DIR / "positions_mar_04_2026_redacted.csv")
    msft = frame[frame["Symbol"].eq("MSFT")].iloc[0]
    assert msft["Total Gain/Loss Dollar"] == -25.0
