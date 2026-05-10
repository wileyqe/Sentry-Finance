from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ingest_fidelity_history import (  # noqa: E402
    FidelityMultiAccountError,
    _classify_action,
    parse_history_csv,
    parse_positions_csv,
    reset_unknown_action_verbs,
    unknown_action_verbs,
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

    # Scope to history fixtures that match the Positions snapshot's
    # reconstructable window (parser START_DATE = 2024-01-01). The 2023
    # SELL fixture (history_2023_redacted.csv) is a pre-window
    # closed-position sample for FID-LS-013 parser tests; it does not
    # belong in the cost-basis writer round-trip because its sells
    # affect tickers (TTT/WWW/XYZ/ZZZ) that the Mar 2026 snapshot does
    # not carry.
    history_files_in_window = [
        path
        for path in _history_files()
        if path.name != "history_2023_redacted.csv"
    ]
    history_frames = [parse_history_csv(path) for path in history_files_in_window]
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


# ---------------------------------------------------------------------------
# P17-T31 contract tests
# ---------------------------------------------------------------------------


# FID-LS-002 — action-verb classification matrix
@pytest.mark.parametrize(
    ("raw_action", "expected"),
    [
        ("YOU BOUGHT DUMMY LARGE CAP INC (AAPL) (Cash)", "BOUGHT"),
        ("YOU SOLD DUMMY LARGE CAP INC (AAPL) (Cash)", "SOLD"),
        (
            "REINVESTMENT FIDELITY GOVERNMENT MONEY MARKET (SPAXX) (Cash)",
            "REINVESTMENT",
        ),
        (
            "DIVIDEND RECEIVED FIDELITY GOVERNMENT MONEY MARKET (SPAXX) (Cash)",
            "DIVIDEND",
        ),
        (
            "SHORT-TERM CAP GAIN DISTRIBUTION DUMMY FUND (QQQM) (Cash)",
            "DIVIDEND",
        ),
        (
            "LONG-TERM CAP GAIN DISTRIBUTION DUMMY INDEX ETF (VOO) (Cash)",
            "DIVIDEND",
        ),
        ("Electronic Funds Transfer Received (Cash)", "DEPOSIT"),
        ("Electronic Funds Transfer Paid (Cash)", "WITHDRAWAL"),
        ("EXPIRED DUMMY RIGHTS POSITION (XZZZ) (Cash)", "EXPIRED"),
    ],
)
def test_classify_action_covers_every_live_shape_contract_verb(raw_action, expected):
    """FID-LS-002: every action-verb substring named in
    ``live-shape-contract.md`` section 1 must classify to its canonical
    category. Includes the SHORT-TERM and LONG-TERM CAP GAIN
    DISTRIBUTION variants observed in the redacted fixtures."""
    assert _classify_action(raw_action) == expected


def test_classify_action_records_unknown_verbs_in_structured_counter():
    """FID-LS-002: an unrecognized verb must fall to ``OTHER`` *and*
    register in the module-level unknown-action counter so silent
    fallthrough cannot hide a new Fidelity action family."""
    reset_unknown_action_verbs()
    assert _classify_action("FOREIGN TAX WITHHELD ON DIVIDENDS") == "OTHER"
    assert _classify_action("MARGIN INTEREST DEBIT") == "OTHER"
    # Same verb twice → counter increments rather than dedupes.
    assert _classify_action("FOREIGN TAX WITHHELD ON DIVIDENDS") == "OTHER"
    counter = unknown_action_verbs()
    assert counter.get("FOREIGN TAX WITHHELD ON DIVIDENDS") == 2
    assert counter.get("MARGIN INTEREST DEBIT") == 1


def test_parse_history_csv_resets_unknown_action_counter_per_pass():
    """FID-LS-002: the unknown-action counter is per-parse-pass. A
    clean fixture must leave the counter empty so a follow-on parse of
    a noisier file shows only that file's noise."""
    reset_unknown_action_verbs()
    _classify_action("UNKNOWN FAMILY ACTION")
    assert unknown_action_verbs() == {"UNKNOWN FAMILY ACTION": 1}

    # parse_history_csv must reset on each call.
    parse_history_csv(FIXTURE_DIR / "history_2025_redacted.csv")
    assert unknown_action_verbs() == {}


# FID-LS-008 — three-decimal precision contract
def test_three_decimal_quantity_precision_contract():
    """FID-LS-008: live history fractional quantities must round-trip
    through the parser at >= 3 decimal places without truncation. This
    is a regression guard for future writers; the existing fixtures
    pin 0.196 and 0.755 deliberately."""
    parsed = [parse_history_csv(path) for path in _history_files()]
    quantities: list[float] = []
    for frame in parsed:
        # Restrict to share-changing rows so cash-only DIVIDEND rows
        # (Quantity 0.000 with non-zero Amount) do not mask the contract.
        share_rows = frame[frame["Action_Type"].isin({"BOUGHT", "REINVESTMENT", "SOLD"})]
        quantities.extend(float(value) for value in share_rows["Quantity"])

    # The fixtures must continue to expose at least one quantity whose
    # third decimal is non-zero (truncating to two decimals would lose
    # the 6 in 0.196 and the 5 in 0.755).
    third_decimal_significant = [
        q for q in quantities if abs(round(q, 2) - q) > 1e-9
    ]
    assert third_decimal_significant, (
        "fixtures must preserve at least one fractional quantity whose "
        "third decimal is significant; the parser must not truncate it."
    )


# FID-LS-010 — header/footer/encoding contract
def test_history_parser_tolerates_utf8_bom_and_drops_footer_disclaimer_rows(tmp_path):
    """FID-LS-010: live exports are saved with a UTF-8 BOM and contain
    footer/disclaimer rows where ``Run Date`` is not parseable. The
    parser must read the BOM via ``utf-8-sig``, find the ``Run Date``
    header (which sits two blank lines down from the file start in the
    live shape), and drop disclaimer rows whose ``Run Date`` does not
    match ``MM/DD/YYYY``. Pinning this prevents a future replacement
    with a naive ``pd.read_csv(filepath)``."""
    fixture = (
        "﻿\n"
        "\n"
        "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
        "Commission ($),Fees ($),Accrued Interest ($),Amount ($),"
        "Cash Balance ($),Settlement Date\n"
        '01/02/2024,"YOU BOUGHT DUMMY LARGE CAP INC (AAPL) (Cash)",AAPL,'
        '"DUMMY LARGE CAP INC",Cash,100.00,0.196,,,,-19.60,980.40,01/03/2024\n'
        '"informational disclaimer footer line that should be dropped"\n'
        '"For more information, go to Fidelity.com."\n'
        '\n'
        'Date downloaded 01/01/2099 12:00 am\n'
    )
    path = tmp_path / "fixture.csv"
    # Write with utf-8-sig so the BOM is real on disk, not just the
    # in-string ``﻿`` sentinel.
    path.write_text(fixture, encoding="utf-8-sig")

    df = parse_history_csv(path)
    assert len(df) == 1
    assert df.iloc[0]["Action_Type"] == "BOUGHT"
    assert df.iloc[0]["Symbol"] == "AAPL"
    # Footer rows must not survive Run Date date-coercion.
    assert df["Run Date"].notna().all()


def test_naive_read_csv_replacement_would_fail_history_contract(tmp_path):
    """FID-LS-010: pin the failure modes a naive
    ``pd.read_csv(filepath)`` (or ``pd.read_csv(filepath, skiprows=2)``)
    introduces. A future agent who simplifies the parser to that
    one-liner must trip this test, because the live shape carries
    footer disclaimer rows and dollar-formatted numerics that a naive
    read does not strip."""
    import pandas as pd

    fixture = (
        "\n"
        "\n"
        "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
        "Commission ($),Fees ($),Accrued Interest ($),Amount ($),"
        "Cash Balance ($),Settlement Date\n"
        '01/02/2024,"YOU BOUGHT DUMMY LARGE CAP INC (AAPL) (Cash)",AAPL,'
        '"DUMMY LARGE CAP INC",Cash,"$1,234.56",0.196,,,,'
        '"-$1,234.56",980.40,01/03/2024\n'
        '"informational disclaimer footer line"\n'
        '"For more information, go to Fidelity.com."\n'
        '\n'
        'Date downloaded 01/01/2099 12:00 am\n'
    )
    path = tmp_path / "naive.csv"
    path.write_text(fixture, encoding="utf-8")

    # Naive read keeps the footer disclaimer rows as data (Run Date
    # not parseable, so they leak through as strings) and leaves
    # ``$1,234.56`` as a comma-formatted string. Both are silent
    # regressions if the hardened parser is replaced.
    naive = pd.read_csv(path)
    assert len(naive) > 1, (
        "naive read keeps footer rows as data; hardened parser drops them"
    )
    naive_price = naive.loc[0, "Price ($)"]
    assert isinstance(naive_price, str), (
        "naive read leaves currency strings unparsed"
    )
    assert "," in naive_price

    # The hardened parser drops the footer rows and cleans currencies.
    hardened = parse_history_csv(path)
    assert len(hardened) == 1
    assert hardened.loc[0, "Price ($)"] == 1234.56
    assert hardened.loc[0, "Amount ($)"] == -1234.56


# FID-LS-011 — money formatting (verify-only; T30 already shipped the
# parenthesized-negative parsing). These tests assert the *positions
# round-trip* lands as a negative number all the way through to the
# downstream consumer.
def test_positions_round_trip_negative_gain_loss_reaches_consumer_as_negative():
    """FID-LS-011 verify-only (closed by P17-T30): a parenthesized
    negative ``Total Gain/Loss Dollar`` in a positions fixture must
    arrive at a downstream consumer as a *negative number*, not zero.
    This is the receipt that protected against the previous
    ``_clean_number`` bug, where ``($25.00)`` collapsed to 0.0 and the
    Investments UI silently showed a flat line for a losing position."""
    frame = parse_positions_csv(
        FIXTURE_DIR / "positions_mar_04_2026_redacted.csv"
    )
    msft = frame[frame["Symbol"].eq("MSFT")].iloc[0]
    # Direct parse — the value is a Python float, not a string.
    assert msft["Total Gain/Loss Dollar"] == -25.0
    assert isinstance(msft["Total Gain/Loss Dollar"], float)

    # Round-trip into pandas-derived integer cents (the canonical money
    # representation per CLAUDE.md guardrails). Cents must preserve the
    # negative sign.
    cents = int(round(msft["Total Gain/Loss Dollar"] * 100))
    assert cents == -2500


def test_clean_number_handles_scientific_notation_if_emitted():
    """FID-LS-011 (live-shape contract §3): scientific notation is
    listed as a tolerated input. Verify-only — pin the behavior so a
    future ``_clean_number`` rewrite cannot silently regress it."""
    from scripts.ingest_fidelity_history import _clean_number

    assert _clean_number("1e3") == 1000.0
    assert _clean_number("1.5e-2") == pytest.approx(0.015)
    # Decorated scientific notation (highly unlikely from Fidelity but
    # defensible behavior) survives the dollar/comma strip.
    assert _clean_number("$1.5e3 ") == 1500.0


# FID-LS-012 — multi-account scoping
def test_positions_parser_refuses_silent_multi_account_merge():
    """FID-LS-012: when a positions CSV contains rows from more than
    one Fidelity ``Account Number`` and no explicit account filter is
    supplied, the parser must raise ``FidelityMultiAccountError``
    rather than silently merge the accounts into one downstream
    record."""
    fixture = FIXTURE_DIR / "positions_two_accounts_redacted.csv"
    with pytest.raises(FidelityMultiAccountError) as excinfo:
        parse_positions_csv(fixture)

    message = str(excinfo.value)
    assert "X<redacted>" in message
    assert "X<redacted_2>" in message


def test_positions_parser_scopes_to_expected_account_number():
    """FID-LS-012: the parser must scope cleanly to the requested
    account when ``expected_account_number`` is supplied, and the
    returned frame must contain *only* that account's rows."""
    fixture = FIXTURE_DIR / "positions_two_accounts_redacted.csv"

    primary = parse_positions_csv(fixture, expected_account_number="X<redacted>")
    secondary = parse_positions_csv(fixture, expected_account_number="X<redacted_2>")

    # Each scope contains only its own rows (no silent merge).
    assert set(primary["Account Number"]) == {"X<redacted>"}
    assert set(secondary["Account Number"]) == {"X<redacted_2>"}

    # Partially-overlapping ticker subsets prove silent merge would be
    # detectable: AAPL only in primary, QQQM only in secondary.
    primary_symbols = set(primary["Symbol"])
    secondary_symbols = set(secondary["Symbol"])
    assert "AAPL" in primary_symbols and "AAPL" not in secondary_symbols
    assert "QQQM" in secondary_symbols and "QQQM" not in primary_symbols


def test_positions_parser_raises_when_expected_account_not_in_file():
    """FID-LS-012: passing an ``expected_account_number`` that does
    not appear in the file is a hard failure, not a silent
    empty-frame, so the caller cannot mis-attribute holdings."""
    fixture = FIXTURE_DIR / "positions_two_accounts_redacted.csv"
    with pytest.raises(FidelityMultiAccountError):
        parse_positions_csv(fixture, expected_account_number="X<not_in_file>")


def test_single_account_positions_fixture_does_not_require_filter():
    """FID-LS-012: backward-compatibility — a single-account positions
    CSV must continue to parse without an explicit
    ``expected_account_number``."""
    frame = parse_positions_csv(
        FIXTURE_DIR / "positions_mar_04_2026_redacted.csv"
    )
    # Drop empty strings (footer rows) before the uniqueness check.
    accounts = {
        a for a in frame["Account Number"].fillna("").str.strip() if a
    }
    assert accounts == {"X<redacted>"}


# FID-LS-013 — SELL/closed-position regression
def test_sell_fixture_classifies_as_sold():
    """FID-LS-013: ``YOU SOLD`` rows in
    ``history_2023_redacted.csv`` must classify as ``Action_Type ==
    SOLD``. The 2023 fixture is the redacted SELL/closed-position
    sample; it covers tickers the household no longer holds, with
    negative quantities and positive cash amounts (sale proceeds), so
    sold-out lots and realized-gain shape are exercised at parse
    time."""
    frame = parse_history_csv(FIXTURE_DIR / "history_2023_redacted.csv")

    sold = frame[frame["Action_Type"].eq("SOLD")]
    assert len(sold) == 8, "fixture must capture all 8 SELL rows"

    # SELL rows have negative quantities (shares leaving the account)
    # and positive amounts (sale proceeds entering as cash).
    assert (sold["Quantity"] < 0).all()
    assert (sold["Amount ($)"] > 0).all()

    # Settlement date is present on SELL rows (T+2 after Run Date).
    settlement = sold["Settlement Date"].fillna("").str.strip()
    assert (settlement != "").all()

    # No rows fell to OTHER — the sell verbs are recognized.
    assert "OTHER" not in set(frame["Action_Type"])


def test_sell_fixture_preserves_pii_redaction_invariants():
    """FID-LS-013: ensure the redacted SELL fixture contains *no*
    references to real Fidelity tickers/companies that could be tied
    back to the household's actual closed positions, and that the file
    is committed as a deterministic dummy. This is a literal-string
    PII check, complementing the repo-wide ``scripts/pii_scan.py``."""
    text = (FIXTURE_DIR / "history_2023_redacted.csv").read_text(encoding="utf-8")
    # The raw 2023 export named real companies. None of those names
    # may survive into the tracked fixture.
    forbidden = [
        "TRACTOR SUPPLY",
        "TRADE DESK",
        "STARBUCKS",
        "MICROSOFT CORP",
        "IQIYI",
        "ETF SER SOLUTIONS",
        "CROWDSTRIKE",
        "APPLE INC",
    ]
    for token in forbidden:
        assert token not in text, (
            f"redacted SELL fixture must not contain real-ticker name "
            f"{token!r}; redact before committing."
        )
