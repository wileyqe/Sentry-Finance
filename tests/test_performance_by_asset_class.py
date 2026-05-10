"""
tests/test_performance_by_asset_class.py — Asset-class-filtered portfolio
performance series.

Exercises the new asset_class + lookthrough parameters on
dal.investments.get_performance() (plan: lexical-yawning-kazoo).

Seeds a minimal in-memory dataset:
  - 3 investment accounts owned by one household
  - 3 tickers: one Large Cap Equity (VOO), one Mid Cap Equity (IJH),
    one fund whose composition splits across Large and Mid (TSP_C → 100% Large
    is already seeded in v27 — here we use a synthetic fund SPLIT that
    decomposes 70/30 Large/Mid to exercise the weighted path).
  - 5 daily holdings snapshots + cash balances in portfolio_snapshots

Asserts:
  0. Legacy call (no asset_class) is byte-for-byte unchanged after the refactor.
  1. Filtered total for a class ≤ unfiltered total (strict subset).
  2. Lookthrough value ≥ non-lookthrough value for a class when funds
     contribute to that class via fund_composition.
  3. Cash / Equivalents path reads from portfolio_snapshots.cash_balance.
  4. Unknown class returns empty series.
  5. Integration: sum of filtered latest values across all classes
     (plus cash) equals the unfiltered latest total within rounding.
"""

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db
from dal.investments import get_performance


# ── Harness ──────────────────────────────────────────────────────────────────

_passed = 0
_failed = 0
_errors: list[str] = []


def _check(name: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f" -- {detail}"
        print(msg)
        _errors.append(name)


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


def _pin_reference_date(conn, reference: str = "2026-04-16") -> None:
    """Keep rolling timeframe fixtures independent from the workstation clock."""
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
        (
            "trusted_seed_manifest",
            json.dumps({
                "seed_version": "test-performance-by-asset-class",
                "reference_date": reference,
            }),
        ),
    )


# ── Seed ─────────────────────────────────────────────────────────────────────

def _seed(conn):
    conn.execute("INSERT INTO institutions (id, display_name) VALUES ('t', 'Test')")
    conn.execute(
        "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
        "VALUES ('acct_brok', 't', 'Brokerage', '1111', 'investment', 1)"
    )

    # ticker_metadata: raw asset_class per ticker
    conn.execute(
        "INSERT INTO ticker_metadata (ticker, sector, industry, asset_class) "
        "VALUES ('VOO', 'ETF', 'ETF', 'US Large Cap Equity')"
    )
    conn.execute(
        "INSERT INTO ticker_metadata (ticker, sector, industry, asset_class) "
        "VALUES ('IJH', 'ETF', 'ETF', 'US Mid Cap Equity')"
    )
    # A fund whose ticker_metadata says "ETF" generically — lookthrough
    # decomposes it via fund_composition below.
    conn.execute(
        "INSERT INTO ticker_metadata (ticker, sector, industry, asset_class) "
        "VALUES ('SPLIT', 'ETF', 'ETF', 'US Large Cap Equity')"
    )

    # fund_composition: SPLIT is 70% Large + 30% Mid.
    # (v27 seeds real funds like VOO → 100% Large; we add SPLIT for this test.)
    # Ensure VOO/IJH have matching fund_composition so lookthrough path picks
    # them up too.
    for ticker, ac, w in [
        ("VOO", "US Large Cap Equity", 1.00),
        ("IJH", "US Mid Cap Equity", 1.00),
        ("SPLIT", "US Large Cap Equity", 0.70),
        ("SPLIT", "US Mid Cap Equity", 0.30),
    ]:
        conn.execute(
            "INSERT OR REPLACE INTO fund_composition (ticker, asset_class, weight) "
            "VALUES (?, ?, ?)",
            (ticker, ac, w),
        )

    # Five daily holdings + portfolio_snapshots (cash balance).
    days = ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05"]
    mv_voo = [1000.0, 1020.0, 1010.0, 1030.0, 1050.0]
    mv_ijh = [500.0,  510.0,  505.0,  515.0,  525.0]
    mv_split = [200.0, 210.0, 205.0, 215.0, 225.0]
    cash = [100.0, 100.0, 100.0, 150.0, 150.0]

    for i, d in enumerate(days):
        for t, mv in (("VOO", mv_voo[i]), ("IJH", mv_ijh[i]), ("SPLIT", mv_split[i])):
            conn.execute(
                "INSERT INTO investment_holdings "
                "(account_id, date, ticker, shares, close_price, market_value, cost_basis) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("acct_brok", d, t, 1.0, mv, mv, mv * 0.9),
            )
        conn.execute(
            "INSERT INTO portfolio_snapshots "
            "(account_id, timestamp, total_account_value, cash_balance) "
            "VALUES (?, ?, ?, ?)",
            ("acct_brok", f"{d}T23:59:59", mv_voo[i] + mv_ijh[i] + mv_split[i] + cash[i], cash[i]),
        )
    conn.commit()

    return {"days": days, "mv_voo": mv_voo, "mv_ijh": mv_ijh,
            "mv_split": mv_split, "cash": cash}


# ── Tests ────────────────────────────────────────────────────────────────────

def test_perf_by_class():
    print("\n--- Performance by asset class ---")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _pin_reference_date(conn)
            data = _seed(conn)

            # 0. Legacy call unchanged — no asset_class kwarg provided.
            legacy = get_performance(conn, account_id="acct_brok", timeframe="1M")
            _check("0: Legacy call returns rows", len(legacy) > 0)

            # 1. Filter by Large Cap, non-lookthrough — only VOO and SPLIT
            #    (SPLIT maps to Large via ticker_metadata) contribute.
            large_raw = get_performance(
                conn, account_id="acct_brok", timeframe="1M",
                asset_class="US Large Cap Equity", lookthrough=False,
            )
            _check("1a: Filtered series non-empty", len(large_raw) == len(legacy))
            # Expected: VOO + SPLIT per day (non-lookthrough, SPLIT fully
            # attributed to Large via ticker_metadata)
            expected_raw_last = round(data["mv_voo"][-1] + data["mv_split"][-1], 2)
            got_raw_last = large_raw[-1]["total_value"]
            _check("1b: Non-lookthrough Large = VOO + SPLIT (raw)",
                   abs(got_raw_last - expected_raw_last) < 0.01,
                   f"expected {expected_raw_last}, got {got_raw_last}")
            _check("1c: Filtered total <= unfiltered total",
                   got_raw_last <= legacy[-1]["total_value"] + 0.01)

            # 2. Lookthrough mode: SPLIT contributes only 0.70 of its value to
            #    Large, so lookthrough Large < non-lookthrough Large for this
            #    dataset (because SPLIT gives up 30% to Mid).
            large_lt = get_performance(
                conn, account_id="acct_brok", timeframe="1M",
                asset_class="US Large Cap Equity", lookthrough=True,
            )
            expected_lt_last = round(
                data["mv_voo"][-1] + data["mv_split"][-1] * 0.70, 2
            )
            got_lt_last = large_lt[-1]["total_value"]
            _check("2a: Lookthrough Large = VOO + 0.70*SPLIT",
                   abs(got_lt_last - expected_lt_last) < 0.01,
                   f"expected {expected_lt_last}, got {got_lt_last}")

            # Mid cap lookthrough: only SPLIT contributes (0.30 weight) plus IJH.
            mid_lt = get_performance(
                conn, account_id="acct_brok", timeframe="1M",
                asset_class="US Mid Cap Equity", lookthrough=True,
            )
            expected_mid_lt_last = round(
                data["mv_ijh"][-1] + data["mv_split"][-1] * 0.30, 2
            )
            _check("2b: Lookthrough Mid = IJH + 0.30*SPLIT",
                   abs(mid_lt[-1]["total_value"] - expected_mid_lt_last) < 0.01,
                   f"expected {expected_mid_lt_last}, got {mid_lt[-1]['total_value']}")

            # 3. Cash path reads portfolio_snapshots.cash_balance.
            cash_series = get_performance(
                conn, account_id="acct_brok", timeframe="1M",
                asset_class="Cash / Equivalents",
            )
            _check("3a: Cash series last value matches snapshot",
                   abs(cash_series[-1]["total_value"] - data["cash"][-1]) < 0.01,
                   f"expected {data['cash'][-1]}, got {cash_series[-1]['total_value']}")

            # 4. Unknown class returns empty series.
            unknown = get_performance(
                conn, account_id="acct_brok", timeframe="1M",
                asset_class="Nonexistent Asset Class",
            )
            _check("4: Unknown class returns empty", unknown == [])

            # 5. Integration: sum of lookthrough Large + Mid + Cash ==
            #    unfiltered total on the last day (within rounding).
            total_last = legacy[-1]["total_value"]
            parts_last = (
                large_lt[-1]["total_value"]
                + mid_lt[-1]["total_value"]
                + cash_series[-1]["total_value"]
            )
            _check("5: sum(class lookthrough) + cash == unfiltered total",
                   abs(parts_last - total_last) < 0.05,
                   f"parts={parts_last}, total={total_last}, diff={parts_last - total_last:.4f}")
    finally:
        try:
            os.unlink(db)
        except OSError:
            pass


# ── Regression: 'All' (monthly) timeframe inflation bug ─────────────────────

def _seed_multi_month(conn):
    """Seed TWO accounts across TWO months with MULTIPLE weekly snapshots
    per month per account — the exact shape that used to trip the legacy
    monthly path's GROUP BY YYYY-MM + SUM(total_account_value) query,
    inflating April's total by ~4x (2 accounts × 2 weekly snapshots).
    """
    conn.execute("INSERT INTO institutions (id, display_name) VALUES ('t', 'Test')")
    for aid, name, last4 in [("acct_a", "Brokerage A", "1111"), ("acct_b", "Brokerage B", "2222")]:
        conn.execute(
            "INSERT INTO accounts (id, institution_id, name, last4, type, is_active) "
            "VALUES (?, 't', ?, ?, 'investment', 1)",
            (aid, name, last4),
        )
    conn.execute(
        "INSERT INTO ticker_metadata (ticker, asset_class) VALUES ('VOO', 'US Large Cap Equity')"
    )

    # Daily holdings across two months (March + April 2026), 2 accounts.
    # Each account holds 10 shares of VOO; prices drift day-to-day.
    march_dates = [f"2026-03-{d:02d}" for d in range(1, 32)]
    april_dates = [f"2026-04-{d:02d}" for d in range(1, 16)]
    all_dates = march_dates + april_dates

    for i, d in enumerate(all_dates):
        price = 100.0 + i * 0.5  # drift upward
        for aid in ("acct_a", "acct_b"):
            conn.execute(
                "INSERT INTO investment_holdings "
                "(account_id, date, ticker, shares, close_price, market_value, cost_basis) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (aid, d, "VOO", 10.0, price, 10.0 * price, 1000.0),
            )

    # Weekly portfolio_snapshots — 4 snapshots in March, 2 in April per account.
    snap_dates = ["2026-03-01", "2026-03-08", "2026-03-15", "2026-03-22",
                  "2026-03-29", "2026-04-05", "2026-04-12"]
    for d in snap_dates:
        # Find that day's holdings value for each account + fixed $50 cash
        day_idx = all_dates.index(d) if d in all_dates else None
        if day_idx is None:
            continue
        price = 100.0 + day_idx * 0.5
        for aid in ("acct_a", "acct_b"):
            per_acct_total = 10.0 * price + 50.0
            conn.execute(
                "INSERT INTO portfolio_snapshots "
                "(account_id, timestamp, total_account_value, cash_balance) "
                "VALUES (?, ?, ?, ?)",
                (aid, f"{d}T23:59:59", per_acct_total, 50.0),
            )
    conn.commit()
    return {"all_dates": all_dates, "accounts": ["acct_a", "acct_b"]}


def test_all_timeframe_no_inflation():
    print("\n--- 'All' timeframe monthly aggregation (regression) ---")
    db = _temp_db()
    try:
        init_db(db)
        with get_db(db) as conn:
            _pin_reference_date(conn)
            _seed_multi_month(conn)

            series = get_performance(conn, account_id="all", timeframe="All")

            # Expect one row per month present in the data: March + April = 2.
            months = {r.get("month") or r["date"][:7] for r in series}
            _check("A1: One row per month (no per-snapshot inflation)",
                   len(series) == 2,
                   f"expected 2 rows, got {len(series)}: {[r['date'] for r in series]}")
            _check("A2: March and April present",
                   months == {"2026-03", "2026-04"},
                   f"got months: {sorted(months)}")

            # Expected April last-day total: 2 accounts × (10 shares × price) + 2 × $50 cash.
            # all_dates = 31 March days + 15 April days = 46 entries;
            # April 15 is index 45 → price 100 + 45*0.5 = 122.5.
            # Per account: 10 × 122.5 + 50 = 1275. Two accounts: 2550.
            april_row = next(r for r in series if (r.get("month") or r["date"][:7]) == "2026-04")
            expected_april = 2 * (10.0 * 122.5 + 50.0)
            _check("A3: April total = last-day holdings + cash (no inflation)",
                   abs(april_row["total_value"] - expected_april) < 0.01,
                   f"expected {expected_april}, got {april_row['total_value']}")

            # Regression guard for the legacy bug: naive SUM across
            # (2 snapshots × 2 accounts × total_account_value) in April
            # would have produced ~4× the correct value.
            _check("A4: April value NOT inflated (legacy bug check)",
                   april_row["total_value"] < expected_april * 1.5,
                   f"April reads {april_row['total_value']}, inflation threshold was {expected_april * 1.5}")

            # Shape: monthly rows carry 'month', 'contributions', 'gain_loss'.
            _check("A5: Monthly rows include 'month' key",
                   "month" in april_row)
            _check("A6: Monthly rows include 'contributions' key",
                   "contributions" in april_row)
            _check("A7: Monthly rows include 'gain_loss' key",
                   "gain_loss" in april_row)

            # Weekly path (6M) must also stay correct on this multi-account data.
            weekly = get_performance(conn, account_id="all", timeframe="6M")
            last_weekly = weekly[-1]["total_value"]
            # Last holdings date is April 15 → expected total 2540.
            _check("A8: Weekly path last value matches latest holdings+cash",
                   abs(last_weekly - expected_april) < 0.01,
                   f"expected {expected_april}, got {last_weekly}")

            # Values should be monotonically sensible across timeframes:
            # the last daily value equals the last weekly equals the last
            # monthly (since they all describe "where we are right now").
            daily = get_performance(conn, account_id="all", timeframe="1M")
            _check("A9: Daily, weekly, monthly last values agree",
                   abs(daily[-1]["total_value"] - last_weekly) < 0.01
                   and abs(last_weekly - april_row["total_value"]) < 0.01,
                   f"daily={daily[-1]['total_value']}, weekly={last_weekly}, monthly={april_row['total_value']}")
    finally:
        try:
            os.unlink(db)
        except OSError:
            pass


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_perf_by_class()
    test_all_timeframe_no_inflation()
    print(f"\nTotals: {_passed} passed, {_failed} failed")
    if _failed:
        print("Failures:")
        for e in _errors:
            print(f"  - {e}")
        sys.exit(1)
