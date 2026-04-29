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
TRUSTED_DB_FINGERPRINT = "a85afac26ed33fe17f605617c34ef42cbaff0984c2faada6e4b43290405099ba"


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
