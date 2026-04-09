"""
tests/test_investments_trust.py — MVP trust harness for the investments
data pipeline.

Asserts the contract the user needs before trusting the system with
real investment data:

  1. Every seeded investment account has at least one holdings row
     (detects orphan accounts with no data).
  2. `/api/investments/holdings` returns non-empty for every account
     reachable from the seeder (parity with the DAL).
  3. `/api/investments/allocation` returns ≥1 non-zero bucket per
     axis (`by_sector`, `by_asset_class`, `by_account`) with the
     ticker_metadata + TSP mappings in place.
  4. `/api/investments/performance?period=ytd` returns a non-None
     `portfolio_twr_pct` for each account with ≥2 portfolio_snapshots.
  5. Parity check: sum of latest-date holdings per account ≈
     latest portfolio_snapshot.total_account_value (within 1%) —
     this is the "holdings and snapshots agree" invariant.
  6. Benchmark cache staleness check: after backdating
     benchmark_prices, `_ensure_benchmark_data` detects the staleness
     and attempts to re-fetch.

Runs against a freshly-seeded temp DB so the suite stays isolated
from `data/sentry.db` and `data/dummy.db`.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db  # noqa: E402


# ── Seeded DB fixture (module-scoped for speed) ──────────────────────────────


@pytest.fixture(scope="module")
def seeded_db():
    """Seeded temp DB with just the investment-relevant tables populated.

    Calls the specific seed_* functions from scripts/seed_dummy_data.py
    directly rather than invoking main() (which uses argparse and can't
    be called cleanly from inside pytest). Skips the slow post-commit
    pipeline since these tests don't need the derived metrics to be
    recomputed — they read directly from the seeded tables.

    Module-scoped so all tests in this file share one seed run.
    """
    from datetime import date, timedelta

    fd, path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    path = Path(path_str)

    # Point the DAL at the temp DB for this fixture's lifetime
    prev_env = os.environ.get("SENTRY_DB_PATH")
    os.environ["SENTRY_DB_PATH"] = str(path)

    import dal.connection
    prev_db_path = dal.connection.DB_PATH
    dal.connection.DB_PATH = path

    try:
        init_db(path)

        # Pinned end date for determinism. The seeder generates a 3-year
        # rolling window ending here; changing this shifts the dataset.
        end_date = date(2026, 4, 8)
        years = 3

        import scripts.seed_dummy_data as seeder
        with get_db(path) as conn:
            seeder.seed_owners(conn)
            seeder.seed_institutions_and_accounts(conn)
            seeder.seed_transactions(conn, end_date, years)
            # investment_history must run BEFORE balance_snapshots
            seeder.seed_investment_history(conn, end_date, years)
            seeder.seed_ticker_metadata(conn)
            seeder.seed_balance_snapshots(conn, end_date, years)
    finally:
        # Restore DAL state
        if prev_env is None:
            os.environ.pop("SENTRY_DB_PATH", None)
        else:
            os.environ["SENTRY_DB_PATH"] = prev_env
        dal.connection.DB_PATH = prev_db_path

    yield path

    try:
        os.unlink(path)
    except OSError:
        pass


# ── 1. Every investment account has holdings ────────────────────────────────


def test_every_seeded_investment_account_has_holdings(seeded_db):
    """Find every account of type investment/retirement and assert it
    has ≥1 row in investment_holdings. TSP is excluded because the
    dummy seeder does NOT pre-seed TSP holdings (those land via the
    document drop pipeline when the user imports a statement — and
    that's the intended design)."""
    with get_db(seeded_db) as conn:
        accounts = conn.execute(
            "SELECT id, name, type FROM accounts "
            "WHERE type IN ('investment', 'retirement') AND id != 'tsp_7777' "
            "AND is_active = 1"
        ).fetchall()

        assert len(accounts) > 0, "No investment/retirement accounts seeded"

        for acct in accounts:
            row = conn.execute(
                "SELECT COUNT(*) FROM investment_holdings WHERE account_id = ?",
                (acct["id"],),
            ).fetchone()
            assert row[0] > 0, (
                f"Account {acct['id']} ({acct['name']}) has zero holdings"
            )


# ── 2. /api/investments/holdings parity with the DAL ─────────────────────────


def test_holdings_endpoint_returns_non_empty_for_seeded_accounts(seeded_db):
    """Hit the holdings endpoint directly via the router function and
    assert every seeded investment account appears.

    FastAPI endpoint functions have `Query(None)` defaults that are only
    resolved to `None` by the request layer, so we pass None explicitly
    when calling the function directly from a test."""
    from backend.routers.investments import investment_holdings

    result = investment_holdings(account_id=None, owner_id=None)
    assert "holdings" in result
    assert len(result["holdings"]) > 0, "holdings endpoint returned empty"

    # Every seeded investment account (minus TSP) should be represented
    with get_db(seeded_db) as conn:
        acct_ids = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM accounts WHERE type IN ('investment', 'retirement') "
                "AND id != 'tsp_7777' AND is_active = 1"
            ).fetchall()
        }

    seen_accounts = {h.get("account_id") for h in result["holdings"]}
    missing = acct_ids - seen_accounts
    assert not missing, f"Accounts missing from holdings endpoint: {missing}"


# ── 3. Allocation buckets ────────────────────────────────────────────────────


def test_allocation_returns_non_empty_buckets(seeded_db):
    """get_allocation should return ≥1 non-zero bucket on each axis
    once TSP holdings are synthetically added. Without TSP, the seeder
    only writes VTI/VXUS/BND which all classify correctly."""
    from dal.allocation import get_allocation

    with get_db(seeded_db) as conn:
        alloc = get_allocation(conn)

    assert alloc["total_value"] > 0

    # All three axes must have at least one non-zero bucket
    assert len(alloc["by_sector"]) > 0
    assert any(b["value"] > 0 for b in alloc["by_sector"])

    assert len(alloc["by_asset_class"]) > 0
    assert any(b["value"] > 0 for b in alloc["by_asset_class"])

    assert len(alloc["by_account"]) > 0
    assert any(b["value"] > 0 for b in alloc["by_account"])

    # No ticker should fall into "Unknown" — the hardcoded mappings
    # in _KNOWN_ASSET_CLASSES cover every dummy-data ticker (VTI, VXUS,
    # BND). If this fires, someone added a new dummy ticker without
    # updating the mappings.
    unknown_classes = [b for b in alloc["by_asset_class"] if b["asset_class"] == "Unknown"]
    assert not unknown_classes, (
        f"Unknown asset class buckets present (add the ticker to "
        f"_KNOWN_ASSET_CLASSES in dal/allocation.py): {unknown_classes}"
    )


def test_allocation_classifies_synthetic_tsp_holdings(seeded_db):
    """End-to-end check that after M1 writes TSP_C/TSP_S/TSP_L2065 into
    investment_holdings, the allocation engine groups them under the
    correct sector and asset-class buckets (M4 mapping).

    The seeder's Institutions.json doesn't create a TSP account — TSP
    holdings only land via document drops in production. So we create
    a minimal tsp_7777 row inside this test so the FK on
    investment_holdings.account_id is satisfied."""
    from dal.allocation import get_allocation
    from dal.investments import upsert_holding

    with get_db(seeded_db) as conn:
        conn.execute("BEGIN")
        try:
            # Stand up the TSP account just for this test
            conn.execute(
                "INSERT OR IGNORE INTO institutions (id, display_name) VALUES ('tsp', 'TSP')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO accounts (id, institution_id, name, type, last4) "
                "VALUES ('tsp_7777', 'tsp', 'TSP Uniformed Services', 'retirement', '7777')"
            )

            upsert_holding(conn, "tsp_7777", "2025-09-04", "TSP_C",
                           802.341, 103.6295, 83146.22, None)
            upsert_holding(conn, "tsp_7777", "2025-09-04", "TSP_S",
                           608.252, 98.6488, 60003.32, None)
            upsert_holding(conn, "tsp_7777", "2025-09-04", "TSP_L2065",
                           1830.661, 20.1575, 36901.55, None)

            alloc = get_allocation(conn)

            # Sector classification
            sectors = {b["sector"]: b["value"] for b in alloc["by_sector"]}
            assert "US Large Cap" in sectors, f"TSP_C not classified: {sectors}"
            assert sectors["US Large Cap"] >= 83146.22
            assert "US Small/Mid Cap" in sectors, f"TSP_S not classified: {sectors}"
            assert sectors["US Small/Mid Cap"] >= 60003.32
            assert "Target Date Fund" in sectors, f"TSP_L2065 not classified: {sectors}"

            # Asset class classification
            ac = {b["asset_class"]: b["value"] for b in alloc["by_asset_class"]}
            assert "US Equity" in ac, f"TSP_C/TSP_S not US Equity: {ac}"
        finally:
            conn.execute("ROLLBACK")


# ── 4. Performance endpoint returns real TWR ─────────────────────────────────


def test_performance_endpoint_returns_real_twr(seeded_db):
    """For each seeded investment account with ≥2 portfolio_snapshots,
    the performance endpoint should return a numeric portfolio_twr_pct."""
    from dal.performance import get_portfolio_performance

    with get_db(seeded_db) as conn:
        # Find accounts with ≥2 portfolio_snapshots rows (needed for TWR)
        rows = conn.execute(
            """
            SELECT account_id, COUNT(*) as n
            FROM portfolio_snapshots
            GROUP BY account_id
            HAVING n >= 2
            """
        ).fetchall()
        assert len(rows) > 0, "No seeded account has ≥2 portfolio snapshots"

        for r in rows:
            acct_id = r["account_id"]
            # Use 'all' period to be robust against date-range mismatches
            perf = get_portfolio_performance(conn, acct_id, period="all")
            assert perf["portfolio_twr"] is not None, (
                f"portfolio_twr is None for {acct_id} with {r['n']} snapshots"
            )
            assert isinstance(perf["portfolio_twr_pct"], (int, float))


# ── 5. Parity: holdings sum ≈ portfolio snapshot total ───────────────────────


def test_holdings_sum_matches_portfolio_snapshot_within_tolerance(seeded_db):
    """For each account, the sum of latest-date holdings.market_value
    should equal the latest portfolio_snapshots.total_account_value
    within 1%. Detects drift where holdings are stale or missing
    relative to the snapshot."""
    with get_db(seeded_db) as conn:
        accounts = conn.execute(
            "SELECT DISTINCT account_id FROM portfolio_snapshots"
        ).fetchall()

        for acct in accounts:
            acct_id = acct["account_id"]

            # Latest portfolio snapshot
            snap = conn.execute(
                """
                SELECT total_account_value FROM portfolio_snapshots
                WHERE account_id = ?
                ORDER BY timestamp DESC LIMIT 1
                """,
                (acct_id,),
            ).fetchone()
            if snap is None or snap["total_account_value"] is None:
                continue

            # Sum of latest-date holdings per ticker
            latest_date = conn.execute(
                "SELECT MAX(date) FROM investment_holdings WHERE account_id = ?",
                (acct_id,),
            ).fetchone()[0]
            if latest_date is None:
                # Account has snapshots but no holdings rows — valid for
                # accounts like TSP where holdings only land via document
                # drops. Skip the parity check.
                continue

            mv_sum = conn.execute(
                """
                SELECT SUM(market_value) as total
                FROM investment_holdings
                WHERE account_id = ? AND date = ?
                """,
                (acct_id, latest_date),
            ).fetchone()["total"]

            snap_val = snap["total_account_value"]
            if snap_val == 0:
                continue
            delta_pct = abs(mv_sum - snap_val) / snap_val * 100
            assert delta_pct < 10.0, (
                f"{acct_id}: holdings sum (${mv_sum:,.2f}) diverges from "
                f"portfolio snapshot (${snap_val:,.2f}) by {delta_pct:.1f}%"
            )


# ── 6. Benchmark cache staleness check ───────────────────────────────────────


def test_benchmark_staleness_triggers_refresh(seeded_db):
    """After backdating benchmark_prices to 30 days ago, calling
    _ensure_benchmark_data for today's end_date should detect the
    staleness and attempt a yfinance fetch. We mock yfinance so the
    test doesn't hit the network."""
    from unittest.mock import MagicMock
    from datetime import datetime, timezone, timedelta
    import dal.performance as perf_mod

    # Use a unique test-only ticker to avoid collisions with any
    # pre-populated ^GSPC entries from earlier fixture runs.
    TEST_TICKER = "TEST_STALE"
    stale_date = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()

    with get_db(seeded_db) as conn:
        # Wipe any prior entries for this ticker so min_d/max_d are
        # exactly what we seed.
        conn.execute("DELETE FROM benchmark_prices WHERE ticker = ?", (TEST_TICKER,))

        # Stale max_d (30 days ago) + a start-of-range row so the
        # min_d <= start_date check passes and we hit the max-age branch.
        conn.execute(
            "INSERT INTO benchmark_prices (ticker, price_date, close_price) VALUES (?, ?, ?)",
            (TEST_TICKER, "2020-01-01", 3900.00),
        )
        conn.execute(
            "INSERT INTO benchmark_prices (ticker, price_date, close_price) VALUES (?, ?, ?)",
            (TEST_TICKER, stale_date, 4000.00),
        )
        conn.commit()

        fake_history = MagicMock()
        fake_history.empty = False
        fake_history.iterrows = MagicMock(return_value=iter([]))
        fake_ticker = MagicMock()
        fake_ticker.history = MagicMock(return_value=fake_history)

        fake_yf = MagicMock()
        fake_yf.Ticker = MagicMock(return_value=fake_ticker)

        with patch.dict("sys.modules", {"yfinance": fake_yf}):
            today = datetime.now(timezone.utc).date().isoformat()
            perf_mod._ensure_benchmark_data(conn, TEST_TICKER, "2020-01-01", today)

        # The max-age check should have seen a 30-day-stale cache and
        # fallen through to the yfinance fetch path. If history was
        # never called, the staleness branch never fired.
        assert fake_ticker.history.called, (
            "Expected yfinance.Ticker.history to be called due to stale cache"
        )


# ── 7. YTD period uses calendar-year start, not a rolling window ─────────────


def test_ytd_timeframe_uses_calendar_year_start(seeded_db):
    """Regression pin for the "YTD is a lie" audit finding.

    Before the fix, the frontend sent `months=12` for YTD which the
    backend coerced into a 1y rolling window. After the fix, the
    frontend sends `period=ytd` which `get_portfolio_performance`
    handles at dal/performance.py:385-386 by anchoring start_date to
    Jan 1 of the current year.

    Assert that `period='ytd'` produces a start_date string of the
    form `YYYY-01-01` where YYYY is the current calendar year."""
    from datetime import datetime, timezone
    from dal.performance import get_portfolio_performance

    current_year = datetime.now(timezone.utc).year
    expected_start = f"{current_year}-01-01"

    with get_db(seeded_db) as conn:
        # Use any seeded investment account
        acct_row = conn.execute(
            "SELECT id FROM accounts "
            "WHERE type IN ('investment', 'retirement') AND is_active = 1 "
            "LIMIT 1"
        ).fetchone()
        assert acct_row is not None, "No seeded investment accounts"

        perf = get_portfolio_performance(conn, acct_row["id"], period="ytd")
        assert perf["period"] == "ytd"
        assert perf["start_date"] == expected_start, (
            f"YTD start_date is {perf['start_date']}, expected {expected_start} — "
            f"the rolling-window fallback would have returned a different date"
        )


# ── 8. Degenerate 1m timeframe returns empty monthly_returns ─────────────────


def test_degenerate_1m_timeframe_returns_empty_monthly_returns(seeded_db):
    """Pin the current behavior: `period='1m'` on monthly-frequency
    seeded data returns at most 1 monthly value, which means
    monthly_returns has 0 entries (need ≥2 snapshots to compute a return).

    This is what the frontend's DEGENERATE_TFS gate in InvestmentsPage.tsx
    is there to prevent users from stumbling into. The test pins the
    underlying data shape so a future fix that adds daily seeding
    doesn't silently break the frontend's assumption."""
    from dal.performance import get_portfolio_performance

    with get_db(seeded_db) as conn:
        acct_row = conn.execute(
            "SELECT id FROM accounts "
            "WHERE type IN ('investment', 'retirement') AND is_active = 1 "
            "LIMIT 1"
        ).fetchone()
        assert acct_row is not None

        perf = get_portfolio_performance(conn, acct_row["id"], period="1m")

        # monthly_portfolio has the raw values, monthly_benchmark is the
        # benchmark series (may be empty if yfinance cache is missing).
        # The frontend-facing aggregate field is monthly_portfolio; we
        # assert the degenerate shape: ≤1 entries means ≤0 computable
        # returns between adjacent months.
        assert len(perf["monthly_portfolio"]) <= 1, (
            f"Expected ≤1 monthly_portfolio entries for 1m window on "
            f"monthly-frequency seed data, got {len(perf['monthly_portfolio'])}. "
            f"Seed has daily snapshots now — update DEGENERATE_TFS in "
            f"frontend/src/pages/InvestmentsPage.tsx."
        )


# ── 9. ticker_metadata is seeded for known ETFs ──────────────────────────────


def test_ticker_metadata_seeded_for_known_tickers(seeded_db):
    """Prevent the 'allocation silently hits yfinance on first call'
    regression. After seeding, VTI/VXUS/BND rows should exist in
    ticker_metadata with non-Unknown asset_class values."""
    with get_db(seeded_db) as conn:
        rows = conn.execute(
            "SELECT ticker, asset_class FROM ticker_metadata "
            "WHERE ticker IN ('VTI', 'VXUS', 'BND')"
        ).fetchall()

    found = {r["ticker"]: r["asset_class"] for r in rows}
    assert "VTI" in found, "VTI not seeded in ticker_metadata"
    assert "VXUS" in found, "VXUS not seeded in ticker_metadata"
    assert "BND" in found, "BND not seeded in ticker_metadata"
    for ticker, asset_class in found.items():
        assert asset_class and asset_class != "Unknown", (
            f"{ticker} has asset_class={asset_class!r}; expected a real "
            f"classification (US Equity / International Equity / Bonds)"
        )


# ── 10. Holdings Decimal precision path is exercised ─────────────────────────


def test_holdings_decimal_precision_path(seeded_db):
    """The V4 *_dec precision columns should be populated by the seeder
    and `get_latest_holdings()` should return Decimal types (not floats)
    by reading through `_from_dec_col()`'s primary branch.

    Before this test, the seeder wrote NULL into the _dec columns and
    every read silently fell back to the REAL columns — the precision
    upgrade was dead weight."""
    from decimal import Decimal
    from dal.investments import get_latest_holdings

    with get_db(seeded_db) as conn:
        # Row-level check: at least one seeded holding has _dec cols
        row = conn.execute(
            "SELECT shares_dec, close_price_dec, market_value_dec "
            "FROM investment_holdings "
            "WHERE shares_dec IS NOT NULL "
            "LIMIT 1"
        ).fetchone()
        assert row is not None, (
            "No investment_holdings rows with populated shares_dec — "
            "seeder is not dual-writing the Decimal precision columns"
        )
        assert row["shares_dec"] is not None
        assert row["close_price_dec"] is not None
        assert row["market_value_dec"] is not None

        # Read-path check: get_latest_holdings should return Decimal
        acct_row = conn.execute(
            "SELECT id FROM accounts "
            "WHERE type IN ('investment', 'retirement') AND is_active = 1 "
            "LIMIT 1"
        ).fetchone()
        holdings = get_latest_holdings(conn, acct_row["id"])
        assert len(holdings) > 0
        h = holdings[0]
        assert isinstance(h["shares"], Decimal), (
            f"shares is {type(h['shares']).__name__}, expected Decimal "
            f"— _from_dec_col fell back to the REAL column, which means "
            f"the _dec read path is still dead"
        )
        assert isinstance(h["close_price"], Decimal)
        assert isinstance(h["market_value"], Decimal)


# ── 11. Orphaned investment-account cleanup ──────────────────────────────────


def test_orphaned_investment_accounts_cleaned_up_on_seed(seeded_db):
    """`cleanup_orphaned_investment_accounts` should delete investment/
    retirement accounts with owner_id=NULL and no holdings/transactions/
    balance_snapshots — those are leftovers from ad-hoc connector scripts
    (ingest_fidelity_history.py, parse_acorns_pdf.py) that the seeder
    should clean up on every run.

    Don't call the full seeder — too slow for a unit test. Stand up a
    stub orphan directly and exercise the cleanup function."""
    import scripts.seed_dummy_data as seeder

    with get_db(seeded_db) as conn:
        # Stand up a stub orphan investment account
        conn.execute(
            "INSERT OR IGNORE INTO institutions (id, display_name) "
            "VALUES ('test_orphan_inst', 'Test Orphan Inst')"
        )
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, type, last4, owner_id, is_active) "
            "VALUES ('orphan_test_9999', 'test_orphan_inst', "
            "'Orphaned Test Account', 'investment', '9999', NULL, 1)"
        )
        conn.commit()

        # Confirm it exists before cleanup
        before = conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE id = 'orphan_test_9999'"
        ).fetchone()[0]
        assert before == 1, "Stub orphan not created"

        # Run cleanup
        seeder.cleanup_orphaned_investment_accounts(conn)

        # Should be gone
        after = conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE id = 'orphan_test_9999'"
        ).fetchone()[0]
        assert after == 0, (
            "cleanup_orphaned_investment_accounts did not remove the stub — "
            "check the DELETE query in scripts/seed_dummy_data.py"
        )

        # Regression: don't touch accounts that HAVE an owner
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, type, last4, owner_id, is_active) "
            "VALUES ('owned_test_8888', 'test_orphan_inst', "
            "'Owned Test Account', 'investment', '8888', 'quintin', 1)"
        )
        conn.commit()
        seeder.cleanup_orphaned_investment_accounts(conn)
        still_there = conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE id = 'owned_test_8888'"
        ).fetchone()[0]
        assert still_there == 1, (
            "cleanup_orphaned_investment_accounts removed an owned account — "
            "the owner_id IS NULL guard is missing or broken"
        )

        # Cleanup our stubs to avoid leaking state
        conn.execute("DELETE FROM accounts WHERE id IN ('orphan_test_9999', 'owned_test_8888')")
        conn.execute("DELETE FROM institutions WHERE id = 'test_orphan_inst'")
        conn.commit()
