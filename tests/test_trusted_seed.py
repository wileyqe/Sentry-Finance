import json
import os
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

from scripts.dummy_data import generator as gen
from scripts.dummy_data.trusted_seed import (
    TRUSTED_REFERENCE_DATE,
    TRUSTED_SEED_END_DATE,
    TRUSTED_SEED_VERSION,
    TRUSTED_SEED_YEARS,
)


ROOT = Path(__file__).resolve().parent.parent
TRUSTED_DB_FINGERPRINT = "f061229325d607ffd06e8ea22dee2831a2db18bd91f140c16c88982548c8b9ec"


def _run_seed(db_path: Path) -> dict:
    env = os.environ.copy()
    env["SENTRY_DB_PATH"] = str(db_path)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_dummy_data.py")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Trusted Synthetic Seeder" in f"{proc.stdout}\n{proc.stderr}"
    conn = sqlite3.connect(db_path)
    try:
        payload = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'trusted_seed_manifest'"
        ).fetchone()[0]
        return json.loads(payload)
    finally:
        conn.close()


def test_trusted_seed_constants_are_canonical():
    assert TRUSTED_SEED_VERSION == "trusted-2026-04-27-v1"
    assert TRUSTED_SEED_END_DATE.isoformat() == "2026-04-27"
    assert TRUSTED_REFERENCE_DATE.isoformat() == "2026-04-28"
    assert TRUSTED_SEED_YEARS == 3


def test_trusted_seed_repeats_full_db_fingerprint(tmp_path):
    first_path = tmp_path / "trusted-a.db"
    first = _run_seed(first_path)
    second = _run_seed(tmp_path / "trusted-b.db")
    first_again = _run_seed(first_path)

    assert first["seed_version"] == TRUSTED_SEED_VERSION
    assert first["end_date"] == TRUSTED_SEED_END_DATE.isoformat()
    assert first["reference_date"] == TRUSTED_REFERENCE_DATE.isoformat()
    assert first["years"] == TRUSTED_SEED_YEARS
    assert first["database_fingerprint"] == TRUSTED_DB_FINGERPRINT
    assert first["database_fingerprint"] == second["database_fingerprint"]
    assert first["database_fingerprint"] == first_again["database_fingerprint"]
    assert first["row_counts"] == second["row_counts"]
    assert first["row_counts"] == first_again["row_counts"]


def test_trusted_investment_seed_is_round_and_explainable(tmp_path):
    db_path = tmp_path / "trusted-investments.db"
    manifest = _run_seed(db_path)

    assert manifest["row_counts"]["investment_holdings"] == 570
    assert manifest["row_counts"]["portfolio_snapshots"] == 114
    assert manifest["row_counts"]["positions_ledger"] == 555
    assert manifest["row_counts"]["tax_buckets"] == 76

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        latest = {
            row["account_id"]: row
            for row in conn.execute(
                """
                WITH latest AS (
                    SELECT account_id, MAX(timestamp) AS ts
                    FROM portfolio_snapshots
                    GROUP BY account_id
                )
                SELECT p.account_id, p.timestamp, p.total_account_value, p.cash_balance
                FROM portfolio_snapshots p
                JOIN latest l
                  ON l.account_id = p.account_id
                 AND l.ts = p.timestamp
                """
            )
        }
        assert latest["acorns_synthetic"]["timestamp"] == "2026-04-27T16:00:00"
        assert latest["acorns_synthetic"]["total_account_value"] == 28_000
        assert latest["fidelity_brokerage"]["total_account_value"] == 86_000
        assert latest["tsp_synthetic"]["total_account_value"] == 154_000
        assert all(row["cash_balance"] == 0 for row in latest.values())

        transfer_rows = conn.execute(
            """
            SELECT description, COUNT(*) AS count, SUM(signed_amount) AS total,
                   SUM(CASE WHEN transfer_tag IS NOT NULL THEN 1 ELSE 0 END) AS tagged
            FROM transactions
            WHERE description IN (
                'ACORNS INVEST TRANSFER',
                'FIDELITY EFT TRANSFER',
                'TSP CONTRIBUTION TRANSFER'
            )
            GROUP BY description
            """
        ).fetchall()
        transfers = {row["description"]: row for row in transfer_rows}
        assert transfers["ACORNS INVEST TRANSFER"]["count"] == 36
        assert transfers["ACORNS INVEST TRANSFER"]["total"] == -18_000
        assert transfers["FIDELITY EFT TRANSFER"]["count"] == 36
        assert transfers["FIDELITY EFT TRANSFER"]["total"] == -36_000
        assert transfers["TSP CONTRIBUTION TRANSFER"]["count"] == 36
        assert transfers["TSP CONTRIBUTION TRANSFER"]["total"] == -54_000
        assert all(row["tagged"] == 36 for row in transfers.values())

        removed_ledger_types = conn.execute(
            """
            SELECT COUNT(*) FROM positions_ledger
            WHERE transaction_type IN ('DIVIDEND', 'REINVESTMENT', 'SELL', 'DEPOSIT')
            """
        ).fetchone()[0]
        assert removed_ledger_types == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM positions_ledger WHERE bank_txn_id IS NOT NULL"
        ).fetchone()[0] == 108

        distinct_prices = conn.execute(
            "SELECT COUNT(DISTINCT close_price), MIN(close_price), MAX(close_price) FROM benchmark_prices"
        ).fetchone()
        assert tuple(distinct_prices) == (1, 100.0, 100.0)

        bad_holdings = conn.execute(
            """
            SELECT COUNT(*) FROM investment_holdings
            WHERE close_price != 100.0
               OR ABS(market_value - cost_basis) > 0.005
               OR ABS(market_value - shares * close_price) > 0.01
            """
        ).fetchone()[0]
        assert bad_holdings == 0

        latest_buckets = conn.execute(
            """
            SELECT bucket_type, balance
            FROM tax_buckets
            WHERE account_id = 'tsp_synthetic'
              AND as_of = '2026-04-27'
            ORDER BY bucket_type
            """
        ).fetchall()
        assert [(row["bucket_type"], row["balance"]) for row in latest_buckets] == [
            ("roth", 10_010_000),
            ("traditional", 5_390_000),
        ]
    finally:
        conn.close()


def test_synthetic_price_and_metadata_paths_are_fixture_only(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", None)
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            """
            CREATE TABLE benchmark_prices (
                ticker TEXT,
                price_date TEXT,
                close_price REAL,
                UNIQUE(ticker, price_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE ticker_metadata (
                ticker TEXT PRIMARY KEY,
                sector TEXT,
                industry TEXT,
                asset_class TEXT,
                last_updated TEXT
            )
            """
        )

        prices = gen._fetch_and_cache_prices(
            conn,
            ["VOO"],
            date(2026, 4, 24),
            date(2026, 4, 27),
        )
        assert prices["VOO"]
        assert set(prices["VOO"].values()) == {100.0}
        assert conn.execute("SELECT COUNT(*) FROM benchmark_prices").fetchone()[0] > 0

        written = gen.enrich_ticker_metadata(
            conn,
            ["VOO"],
            reference_date=TRUSTED_REFERENCE_DATE,
        )
        assert written == 1
        row = conn.execute(
            "SELECT sector, industry, asset_class, last_updated FROM ticker_metadata WHERE ticker = 'VOO'"
        ).fetchone()
        assert row == ("Blend", "S&P 500 Index", "ETF", "2026-04-28")
    finally:
        conn.close()
