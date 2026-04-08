"""
dal/performance.py — Investment portfolio performance & benchmarking.

Computes time-weighted returns (TWR) for investment accounts and compares
against market benchmarks (S&P 500 via ^GSPC, total market via VTI).

Time-Weighted Return (TWR):
  TWR is the standard performance metric for investment accounts because it
  eliminates the distortion caused by external cash flows (contributions,
  withdrawals). Each sub-period return is computed as:

      R_i = (End_Value - Start_Value) / Start_Value

  The overall TWR chains sub-period returns multiplicatively:

      TWR = [(1 + R_1) × (1 + R_2) × ... × (1 + R_N)] - 1

  For Sentry's purposes, we compute monthly sub-periods using portfolio_snapshots
  (total_account_value at end of each month) since we don't have intraday
  cash flow timing data.

Benchmark data:
  We download benchmark prices via yfinance and store them in the
  `benchmark_prices` table (Schema V10). This is done lazily on first request
  for a given period.

Alpha:
  alpha = portfolio_TWR - benchmark_TWR
  Positive alpha means the portfolio outperformed the benchmark.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("sentry.dal.performance")

# Default benchmarks
BENCHMARKS = {
    "sp500": "^GSPC",
    "total_market": "VTI",
    "bonds": "BND",
}


# ── Benchmark Data ─────────────────────────────────────────────────────────────


def _ensure_benchmark_data(
    conn: sqlite3.Connection,
    ticker: str,
    start_date: str,
    end_date: str,
) -> bool:
    """
    Ensure benchmark price data exists for the requested period.
    Downloads missing data from yfinance and caches in benchmark_prices.
    Returns True if data is available, False if yfinance failed.
    """
    # Check if we already have data for this range
    existing = conn.execute(
        """
        SELECT MIN(price_date) as min_d, MAX(price_date) as max_d
        FROM benchmark_prices
        WHERE ticker = ?
          AND price_date >= ?
          AND price_date <= ?
        """,
        (ticker, start_date, end_date),
    ).fetchone()

    if existing and existing["min_d"] and existing["min_d"] <= start_date:
        return True  # Already cached

    try:
        import yfinance as yf
        import math

        log.info("Downloading benchmark %s (%s → %s)...", ticker, start_date, end_date)
        ticker_obj = yf.Ticker(ticker)
        hist = ticker_obj.history(start=start_date, end=end_date, auto_adjust=True)

        if hist.empty:
            log.warning("No benchmark data returned for %s", ticker)
            return False

        rows_inserted = 0
        for idx, row in hist.iterrows():
            close = row.get("Close", None)
            if close is None or (isinstance(close, float) and math.isnan(close)):
                continue
            price_date = idx.strftime("%Y-%m-%d")
            conn.execute(
                """
                INSERT OR IGNORE INTO benchmark_prices (ticker, price_date, close_price)
                VALUES (?, ?, ?)
                """,
                (ticker, price_date, float(close)),
            )
            rows_inserted += 1

        conn.commit()
        log.info("Cached %d %s benchmark prices", rows_inserted, ticker)
        return rows_inserted > 0

    except ImportError:
        log.warning("yfinance not available — benchmark comparison unavailable")
        return False
    except Exception as e:
        log.error("Failed to download benchmark %s: %s", ticker, e)
        return False


def get_benchmark_monthly_returns(
    conn: sqlite3.Connection,
    ticker: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    Get monthly benchmark returns for a ticker between start and end dates.

    Returns list of {month, start_price, end_price, monthly_return} oldest-first.
    """
    _ensure_benchmark_data(conn, ticker, start_date, end_date)

    rows = conn.execute(
        """
        SELECT strftime('%Y-%m', price_date) as month,
               MIN(close_price) as month_open,
               MAX(CASE WHEN price_date = (
                   SELECT MAX(price_date) FROM benchmark_prices b2
                   WHERE b2.ticker = benchmark_prices.ticker
                     AND strftime('%Y-%m', b2.price_date) = strftime('%Y-%m', benchmark_prices.price_date)
               ) THEN close_price END) as month_close
        FROM benchmark_prices
        WHERE ticker = ?
          AND price_date >= ?
          AND price_date <= ?
        GROUP BY month
        ORDER BY month ASC
        """,
        (ticker, start_date, end_date),
    ).fetchall()

    results = []
    prev_close = None
    for r in rows:
        if prev_close is None:
            prev_close = r["month_open"]
            continue
        if prev_close and r["month_close"]:
            monthly_return = (r["month_close"] - prev_close) / prev_close
            results.append({
                "month": r["month"],
                "start_price": round(prev_close, 4),
                "end_price": round(r["month_close"], 4),
                "monthly_return": round(monthly_return, 6),
            })
        prev_close = r["month_close"]

    return results


# ── Portfolio Monthly Values ──────────────────────────────────────────────────


def _get_portfolio_monthly_values(
    conn: sqlite3.Connection,
    account_id: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    Get end-of-month portfolio values for an account from portfolio_snapshots.

    Uses the latest snapshot per month within the date range.
    """
    rows = conn.execute(
        """
        SELECT strftime('%Y-%m', timestamp) as month,
               total_account_value
        FROM portfolio_snapshots
        WHERE account_id = ?
          AND timestamp >= ?
          AND timestamp <= ?
          AND total_account_value IS NOT NULL
          AND id = (
              SELECT id FROM portfolio_snapshots p2
              WHERE p2.account_id = portfolio_snapshots.account_id
                AND strftime('%Y-%m', p2.timestamp) = strftime('%Y-%m', portfolio_snapshots.timestamp)
              ORDER BY p2.timestamp DESC LIMIT 1
          )
        ORDER BY month ASC
        """,
        (account_id, start_date, end_date),
    ).fetchall()

    return [{"month": r["month"], "value": r["total_account_value"]} for r in rows]


# ── TWR Calculation ──────────────────────────────────────────────────────────


def _compute_twr(monthly_values: list[dict]) -> Optional[float]:
    """
    Compute time-weighted return from a list of {month, value} dicts.

    Uses end-of-consecutive-month pairs as sub-periods.
    Returns None if insufficient data (< 2 months).
    """
    if len(monthly_values) < 2:
        return None

    twr = 1.0
    for i in range(1, len(monthly_values)):
        start_val = monthly_values[i - 1]["value"]
        end_val = monthly_values[i]["value"]
        if start_val and start_val > 0:
            sub_period_return = (end_val - start_val) / start_val
            twr *= (1 + sub_period_return)

    return round(twr - 1.0, 6)


def _compute_benchmark_twr(monthly_returns: list[dict]) -> Optional[float]:
    """Compute TWR from a list of {monthly_return} dicts."""
    if not monthly_returns:
        return None
    twr = 1.0
    for r in monthly_returns:
        twr *= (1 + r["monthly_return"])
    return round(twr - 1.0, 6)


# ── Main Performance Function ─────────────────────────────────────────────────


def get_portfolio_performance(
    conn: sqlite3.Connection,
    account_id: str,
    period: str = "1y",
    benchmark: str = "sp500",
) -> dict:
    """
    Compute portfolio performance vs. a benchmark for a given period.

    Args:
        conn: DB connection
        account_id: Investment account to analyze
        period: One of "1m", "3m", "6m", "1y", "2y", "3y", "ytd", "all"
        benchmark: Key from BENCHMARKS dict ("sp500", "total_market", "bonds")

    Returns:
        {
          account_id, period, benchmark_ticker,
          start_date, end_date,
          portfolio_twr, benchmark_twr, alpha,
          monthly_portfolio: [{month, value}, ...],
          monthly_benchmark: [{month, start_price, end_price, monthly_return}, ...]
        }
    """
    # Compute date range
    today = datetime.now(timezone.utc)
    end_date = today.strftime("%Y-%m-%d")

    if period == "1m":
        start_date = (today - timedelta(days=31)).strftime("%Y-%m-%d")
    elif period == "3m":
        start_date = (today - timedelta(days=92)).strftime("%Y-%m-%d")
    elif period == "6m":
        start_date = (today - timedelta(days=183)).strftime("%Y-%m-%d")
    elif period == "1y":
        start_date = (today - timedelta(days=366)).strftime("%Y-%m-%d")
    elif period == "2y":
        start_date = (today - timedelta(days=731)).strftime("%Y-%m-%d")
    elif period == "3y":
        start_date = (today - timedelta(days=1096)).strftime("%Y-%m-%d")
    elif period == "ytd":
        start_date = f"{today.year}-01-01"
    else:  # "all"
        row = conn.execute(
            "SELECT MIN(timestamp) as min_t FROM portfolio_snapshots WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        start_date = (row["min_t"] or end_date)[:10]

    benchmark_ticker = BENCHMARKS.get(benchmark, benchmark)

    # Get portfolio monthly values
    portfolio_monthly = _get_portfolio_monthly_values(conn, account_id, start_date, end_date)
    portfolio_twr = _compute_twr(portfolio_monthly)

    # Get benchmark monthly returns
    benchmark_monthly = get_benchmark_monthly_returns(conn, benchmark_ticker, start_date, end_date)
    benchmark_twr = _compute_benchmark_twr(benchmark_monthly)

    # Compute alpha
    alpha = None
    if portfolio_twr is not None and benchmark_twr is not None:
        alpha = round(portfolio_twr - benchmark_twr, 6)

    # Current value
    latest = portfolio_monthly[-1]["value"] if portfolio_monthly else None
    start_value = portfolio_monthly[0]["value"] if portfolio_monthly else None

    log.info(
        "Performance %s [%s]: portfolio=%.2f%% benchmark(%s)=%.2f%% alpha=%.2f%%",
        account_id,
        period,
        (portfolio_twr or 0) * 100,
        benchmark_ticker,
        (benchmark_twr or 0) * 100,
        (alpha or 0) * 100,
    )

    return {
        "account_id": account_id,
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "benchmark_ticker": benchmark_ticker,
        "start_value": start_value,
        "end_value": latest,
        "portfolio_twr": portfolio_twr,
        "portfolio_twr_pct": round((portfolio_twr or 0) * 100, 2),
        "benchmark_twr": benchmark_twr,
        "benchmark_twr_pct": round((benchmark_twr or 0) * 100, 2),
        "alpha": alpha,
        "alpha_pct": round((alpha or 0) * 100, 2),
        "monthly_portfolio": portfolio_monthly,
        "monthly_benchmark": benchmark_monthly,
        "months_of_data": len(portfolio_monthly),
    }


def get_all_accounts_performance(
    conn: sqlite3.Connection,
    period: str = "1y",
    benchmark: str = "sp500",
    owner_id: str | None = None,
) -> list[dict]:
    """
    Performance summary for all active investment/retirement accounts.

    Returns a list of simplified performance dicts, sorted by portfolio_twr desc.
    """
    clauses = ["type IN ('investment', 'retirement')", "is_active = 1"]
    params = []
    from dal.owners import build_account_filter
    acct_sql, acct_params = build_account_filter(conn, owner_id, None, column="id")
    if acct_sql:
        # Helper prepends " AND "; this function uses a clauses list, so
        # strip the prefix.
        clauses.append(acct_sql.lstrip()[4:])
        params.extend(acct_params)

    where = " AND ".join(clauses)
    accounts = conn.execute(
        f"""
        SELECT id, name, type
        FROM accounts
        WHERE {where}
        """, params
    ).fetchall()

    results = []
    for acct in accounts:
        try:
            perf = get_portfolio_performance(conn, acct["id"], period=period, benchmark=benchmark)
            if perf["months_of_data"] >= 2:
                results.append({
                    "account_id": acct["id"],
                    "account_name": acct["name"],
                    "account_type": acct["type"],
                    "end_value": perf["end_value"],
                    "portfolio_twr": perf["portfolio_twr"],
                    "portfolio_twr_pct": perf["portfolio_twr_pct"],
                    "benchmark_twr_pct": perf["benchmark_twr_pct"],
                    "alpha_pct": perf["alpha_pct"],
                    "period": period,
                    "months_of_data": perf["months_of_data"],
                })
        except Exception as e:
            log.warning("Performance calc failed for %s: %s", acct["id"], e)

    results.sort(key=lambda x: (x.get("portfolio_twr") or -999), reverse=True)
    return results


# ── Contributions vs. Performance Decomposition (P6-T05) ────────────────────


def decompose_contributions_vs_performance(
    conn: sqlite3.Connection,
    year: int,
    account_ids: list[str] | None = None,
    owner_id: str | None = None,
) -> list[dict]:
    """
    For each investment/retirement account, decompose the year's value
    change into contributions (money in) vs. market performance (market gain).

    Uses the Simple Dietz method for performance return % — assumes
    contributions are timed at mid-year (contribution_weight = 0.5).
    This is an approximation; for more precision, Modified Dietz
    would weight each contribution by its actual timing.

    Note: TSP contributions come from payroll (not transfer-tagged),
    so net_contributions will be 0 for TSP. The entire total_gain
    will appear as performance_gain, which is correct given the
    data model limitation.

    Args:
        conn: DB connection
        year: Calendar year to analyze (e.g., 2025)
        account_ids: Optional filter; if None, uses all investment/retirement
                     accounts from the accounts table.

    Returns: list of dicts, one per account.
    """
    # 1. Determine account set. When both account_ids and owner_id are
    # supplied, an explicit account_ids list takes precedence (helper
    # contract) — this matches the common case where callers resolve
    # ownership upstream and want to reuse it.
    clauses = ["a.type IN ('investment', 'retirement')", "a.is_active = 1"]
    params = []
    from dal.owners import build_account_filter
    acct_sql, acct_params = build_account_filter(
        conn, owner_id, account_ids, column="a.id"
    )
    if acct_sql:
        clauses.append(acct_sql.lstrip()[4:])
        params.extend(acct_params)

    where = " AND ".join(clauses)
    accounts = conn.execute(
        f"""
        SELECT a.id, a.name, a.institution_id
        FROM accounts a
        WHERE {where}
        """,
        params,
    ).fetchall()

    results = []
    for acct in accounts:
        acct_id = acct["id"]
        acct_name = acct["name"]
        institution = acct["institution_id"] or ""

        # 2. Start value: last snapshot with as_of <= Jan 15 of target year
        start_row = conn.execute(
            """
            SELECT balance FROM balance_snapshots
            WHERE account_id = ? AND as_of <= ?
            ORDER BY as_of DESC LIMIT 1
            """,
            (acct_id, f"{year}-01-15"),
        ).fetchone()

        # 3. End value: last snapshot with as_of <= Dec 31 of target year
        end_row = conn.execute(
            """
            SELECT balance FROM balance_snapshots
            WHERE account_id = ? AND as_of <= ?
            ORDER BY as_of DESC LIMIT 1
            """,
            (acct_id, f"{year}-12-31"),
        ).fetchone()

        has_sufficient_data = bool(start_row and end_row)

        if not has_sufficient_data:
            results.append({
                "account_id": acct_id,
                "account_name": acct_name,
                "institution": institution,
                "start_value": None,
                "end_value": None,
                "total_gain": None,
                "net_contributions": 0.0,
                "performance_gain": None,
                "performance_return_pct": None,
                "contribution_count": 0,
                "has_sufficient_data": False,
            })
            continue

        start_value = round(start_row["balance"] or 0, 2)
        end_value = round(end_row["balance"] or 0, 2)

        # 4. Net contributions: transfer-tagged transactions into this account
        contrib_row = conn.execute(
            """
            SELECT COALESCE(SUM(signed_amount), 0) as net,
                   COUNT(CASE WHEN signed_amount > 0 THEN 1 END) as pos_count
            FROM transactions
            WHERE account_id = ?
              AND strftime('%Y', posting_date) = ?
              AND transfer_tag IS NOT NULL
              AND status = 'posted'
            """,
            (acct_id, str(year)),
        ).fetchone()

        net_contributions = round(contrib_row["net"] or 0, 2)
        contribution_count = contrib_row["pos_count"] or 0

        # 5. Decomposition
        total_gain = round(end_value - start_value, 2)
        performance_gain = round(total_gain - net_contributions, 2)

        # 6. Performance return % (Simple Dietz)
        denominator = start_value + (net_contributions * 0.5)
        if denominator > 0:
            performance_return_pct = round((performance_gain / denominator) * 100, 1)
        else:
            performance_return_pct = None

        results.append({
            "account_id": acct_id,
            "account_name": acct_name,
            "institution": institution,
            "start_value": start_value,
            "end_value": end_value,
            "total_gain": total_gain,
            "net_contributions": net_contributions,
            "performance_gain": performance_gain,
            "performance_return_pct": performance_return_pct,
            "contribution_count": contribution_count,
            "has_sufficient_data": True,
        })

    return results
