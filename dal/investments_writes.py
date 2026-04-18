"""
dal/investments_writes.py — Write wrappers for investment snapshot
tables (``investment_holdings``, ``portfolio_snapshots``).

The sibling ``dal/investments.py`` holds the read APIs for the
investments tab; keeping writes separate avoids swelling that module
past 1.2k lines and mirrors the split between ``dal/balances.py`` and
``dal/derived.py`` on the banking side.

Part of the Phase-17 parity pass: seeder and live connectors share one
validated write path, mirroring the ``dal.transactions.upsert_transactions``
choke-point pattern. Caller commits.
"""

import sqlite3

# A rounded market_value can drift from shares*close_price by up to 0.01
# absolute due to ``round(x, 2)`` in the generator; we allow the larger
# of 1¢ or 0.1% of notional so the invariant catches real drift (wrong
# price or wrong share count) without tripping on rounding.
_MV_ABS_TOLERANCE = 0.01
_MV_REL_TOLERANCE = 0.001


def _assert_holding_invariant(row: dict) -> None:
    for key in ("account_id", "date", "ticker", "shares"):
        if key not in row:
            raise ValueError(
                f"investment_holdings row missing required key {key!r}: {row!r}"
            )

    shares = row["shares"]
    if not isinstance(shares, (int, float)) or shares < 0:
        raise ValueError(
            f"investment_holdings.shares must be >= 0, got {shares!r}. "
            f"account={row['account_id']!r} date={row['date']!r} "
            f"ticker={row['ticker']!r}"
        )

    price = row.get("close_price")
    if price is not None and (not isinstance(price, (int, float)) or price < 0):
        raise ValueError(
            f"investment_holdings.close_price must be >= 0 when present, "
            f"got {price!r}. account={row['account_id']!r} "
            f"date={row['date']!r} ticker={row['ticker']!r}"
        )

    mv = row.get("market_value")
    if mv is not None and (not isinstance(mv, (int, float)) or mv < 0):
        raise ValueError(
            f"investment_holdings.market_value must be >= 0 when present, "
            f"got {mv!r}. account={row['account_id']!r} "
            f"date={row['date']!r} ticker={row['ticker']!r}"
        )

    if shares > 0 and price is not None and mv is not None:
        expected = shares * price
        tolerance = max(_MV_ABS_TOLERANCE, _MV_REL_TOLERANCE * expected)
        if abs(mv - expected) > tolerance:
            raise ValueError(
                f"investment_holdings.market_value {mv!r} disagrees with "
                f"shares*close_price {expected:.4f} beyond tolerance "
                f"{tolerance:.4f}. account={row['account_id']!r} "
                f"date={row['date']!r} ticker={row['ticker']!r}"
            )


def record_investment_holdings(
    conn: sqlite3.Connection,
    holdings: list[dict],
    refresh_run_id: str | None = None,  # noqa: ARG001 — accepted for future parity
) -> dict:
    """Upsert a batch of ``investment_holdings`` rows.

    Each dict must contain: ``account_id``, ``date``, ``ticker``,
    ``shares``. Optional: ``close_price``, ``market_value``,
    ``cost_basis``.

    Uses ``INSERT OR REPLACE`` on the ``(account_id, date, ticker)``
    UNIQUE index so re-running the seeder or a connector with the same
    key cleanly replaces the stored row.

    Invariants enforced per row before any write:

    * ``shares >= 0``.
    * ``close_price >= 0`` when present.
    * ``market_value >= 0`` when present.
    * When all three of ``shares``, ``close_price``, ``market_value``
      are present and ``shares > 0``:
      ``|market_value - shares*close_price| <=
       max(0.01, 0.001 * shares*close_price)``.

    ``refresh_run_id`` is accepted for symmetry with
    ``dal.transactions.upsert_transactions`` / ``record_balance``.
    ``investment_holdings`` does not persist it today.

    Returns ``{"inserted_or_replaced": int}``. Caller commits.
    """
    if not holdings:
        return {"inserted_or_replaced": 0}

    for row in holdings:
        _assert_holding_invariant(row)

    params = [
        (
            row["account_id"],
            row["date"],
            row["ticker"],
            float(row["shares"]),
            row.get("close_price"),
            row.get("market_value"),
            row.get("cost_basis"),
        )
        for row in holdings
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO investment_holdings
               (account_id, date, ticker, shares, close_price,
                market_value, cost_basis)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        params,
    )
    return {"inserted_or_replaced": len(params)}


def _assert_snapshot_invariant(row: dict) -> None:
    for key in ("account_id", "timestamp", "total_account_value"):
        if key not in row:
            raise ValueError(
                f"portfolio_snapshots row missing required key {key!r}: {row!r}"
            )

    total = row["total_account_value"]
    if not isinstance(total, (int, float)) or total < 0:
        raise ValueError(
            f"portfolio_snapshots.total_account_value must be >= 0, got "
            f"{total!r}. account={row['account_id']!r} "
            f"timestamp={row['timestamp']!r}"
        )

    cash = row.get("cash_balance", 0.0)
    if cash is None:
        return
    if not isinstance(cash, (int, float)) or cash < 0:
        raise ValueError(
            f"portfolio_snapshots.cash_balance must be >= 0 when present, "
            f"got {cash!r}. account={row['account_id']!r} "
            f"timestamp={row['timestamp']!r}"
        )
    if cash > total:
        raise ValueError(
            f"portfolio_snapshots.cash_balance {cash!r} exceeds "
            f"total_account_value {total!r}. account={row['account_id']!r} "
            f"timestamp={row['timestamp']!r}"
        )


def record_portfolio_snapshots(
    conn: sqlite3.Connection,
    snapshots: list[dict],
) -> dict:
    """Insert a batch of ``portfolio_snapshots`` rows.

    Each dict must contain: ``account_id``, ``timestamp``,
    ``total_account_value``. Optional: ``cash_balance`` (default
    ``0.0``).

    ``portfolio_snapshots`` has no UNIQUE constraint — snapshots are
    append-only by ``timestamp``. Callers that need replace-on-key
    semantics (e.g. the TSP connector) should ``DELETE`` the prior
    row before calling.

    Invariants enforced per row:

    * ``total_account_value >= 0``.
    * ``cash_balance >= 0`` when present.
    * ``cash_balance <= total_account_value`` when both present.

    Returns ``{"inserted": int}``. Caller commits.
    """
    if not snapshots:
        return {"inserted": 0}

    for row in snapshots:
        _assert_snapshot_invariant(row)

    params = [
        (
            row["account_id"],
            row["timestamp"],
            float(row["total_account_value"]),
            float(row.get("cash_balance") or 0.0),
        )
        for row in snapshots
    ]
    conn.executemany(
        """INSERT INTO portfolio_snapshots
               (account_id, timestamp, total_account_value, cash_balance)
           VALUES (?, ?, ?, ?)""",
        params,
    )
    return {"inserted": len(params)}


def record_portfolio_snapshot(
    conn: sqlite3.Connection,
    account_id: str,
    timestamp: str,
    total_account_value: float,
    cash_balance: float = 0.0,
) -> None:
    """Single-row convenience wrapper around
    :func:`record_portfolio_snapshots`.

    Used by the Acorns and TSP connectors which scrape one snapshot per
    refresh — mirrors the ergonomics of ``dal.balances.record_balance``.
    Caller commits.
    """
    record_portfolio_snapshots(
        conn,
        [
            {
                "account_id": account_id,
                "timestamp": timestamp,
                "total_account_value": total_account_value,
                "cash_balance": cash_balance,
            }
        ],
    )
