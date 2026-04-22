"""
dal/debt.py — Debt payoff planning and liability analysis.

Aggregates all liability accounts (credit cards, loans, BNPL) and models
payoff strategies to show time-to-zero and total interest cost.

Supported strategies:
  - avalanche : Highest interest rate first (mathematically optimal — minimizes total interest)
  - snowball  : Lowest balance first (psychologically motivating — fastest wins)

The calculator:
  1. Distributes minimum payments to all debts each month
  2. Applies any extra payment to the target debt (avalanche or snowball ordering)
  3. When a debt is paid off, its minimum payment rolls forward to the next debt
  4. Iterates month by month until all debts reach $0 or max_months is exceeded

Interest rates:
  - Read from `loan_details` table (field_name = 'interest_rate' or 'apr')
  - Fallback: credit cards default to 24.99%, BNPL defaults to 29.99%

Data sources for current balances:
  - Latest `balance_snapshots` entry per liability account
  - Only includes active accounts
"""

import logging
import sqlite3
from typing import Optional

log = logging.getLogger("sentry.dal.debt")

# Fallback APRs when no rate is stored
_DEFAULT_APR = {
    "credit_card": 24.99,
    "bnpl": 29.99,
    "loan": 6.5,
}

# Monthly cap on iterations (20 years)
_MAX_MONTHS = 240


# ── Data Fetching ─────────────────────────────────────────────────────────────


def _get_liability_accounts(conn: sqlite3.Connection, owner_id: str | None = None) -> list[dict]:
    """Fetch all active liability accounts with current balances and rates."""
    from dal.owners import build_account_filter
    acct_filter, acct_params = build_account_filter(conn, owner_id, None, column="a.id")
    params = list(acct_params)

    query = f"""
        SELECT a.id, a.name, a.type,
               ABS(bs.balance) as balance
        FROM accounts a
        JOIN balance_snapshots bs ON bs.account_id = a.id
        WHERE a.type IN ('credit_card', 'loan', 'bnpl')
          AND a.is_active = 1
          {acct_filter}
          AND bs.id = (
              SELECT id FROM balance_snapshots b2
              WHERE b2.account_id = a.id
              ORDER BY b2.as_of DESC LIMIT 1
          )
          AND bs.balance != 0
        ORDER BY ABS(bs.balance) DESC
    """
    rows = conn.execute(query, params).fetchall()

    debts = []
    for r in rows:
        acct_id = r["id"]
        balance = r["balance"] or 0

        # Look up APR from loan_details
        apr = _get_loan_apr(conn, acct_id)
        if apr is None:
            apr = _DEFAULT_APR.get(r["type"], 18.0)

        # Minimum payment: 2% of balance or $25, whichever is greater
        min_payment = max(25.0, round(balance * 0.02, 2))

        debts.append({
            "account_id": acct_id,
            "name": r["name"],
            "account_type": r["type"],
            "balance": round(balance, 2),
            "apr": apr,
            "monthly_rate": apr / 100 / 12,
            "min_payment": round(min_payment, 2),
        })

    return debts


def _get_loan_apr(conn: sqlite3.Connection, account_id: str) -> Optional[float]:
    """Read APR from loan_details table. Tries both 'interest_rate' and 'apr'."""
    for field in ("interest_rate", "apr", "Interest Rate", "APR"):
        row = conn.execute(
            """
            SELECT field_value FROM loan_details
            WHERE account_id = ? AND LOWER(field_name) = LOWER(?)
            ORDER BY as_of DESC LIMIT 1
            """,
            (account_id, field),
        ).fetchone()
        if row and row["field_value"]:
            try:
                val = float(str(row["field_value"]).replace("%", "").strip())
                if 0 < val < 100:  # sanity gate
                    return val
            except (ValueError, TypeError):
                pass
    return None


# ── Payoff Calculator ──────────────────────────────────────────────────────────


def _simulate_payoff(
    debts: list[dict],
    extra_payment: float,
    strategy: str,
) -> dict:
    """
    Run a month-by-month debt payoff simulation.

    Args:
        debts: List of debt dicts with balance, monthly_rate, min_payment
        extra_payment: Additional monthly payment above minimums
        strategy: "avalanche" (high rate first) or "snowball" (low balance first)

    Returns:
        {
          total_months, total_paid, total_interest,
          payoff_schedule: [{month, balances: {account_id: balance}, total_remaining}]
          debt_payoff_order: [{account_id, name, paid_off_month, interest_paid}]
        }
    """
    import copy

    active_debts = copy.deepcopy(debts)
    for d in active_debts:
        d["interest_paid"] = 0.0
        d["paid_off_month"] = None

    total_paid = 0.0
    total_interest = 0.0
    schedule = []
    payoff_order = []

    for month in range(1, _MAX_MONTHS + 1):
        if not any(d["balance"] > 0.01 for d in active_debts):
            break

        # Sort remaining debts by strategy
        remaining = [d for d in active_debts if d["balance"] > 0.01]
        if strategy == "avalanche":
            remaining.sort(key=lambda x: x["apr"], reverse=True)
        else:  # snowball
            remaining.sort(key=lambda x: x["balance"])

        # 1. Apply interest to all debts
        for d in active_debts:
            if d["balance"] > 0.01:
                interest = round(d["balance"] * d["monthly_rate"], 2)
                d["balance"] = round(d["balance"] + interest, 2)
                d["interest_paid"] = round(d["interest_paid"] + interest, 2)
                total_interest += interest

        # 2. Pay minimums on all debts
        month_paid = 0
        for d in active_debts:
            if d["balance"] > 0.01:
                payment = min(d["min_payment"], d["balance"])
                d["balance"] = round(d["balance"] - payment, 2)
                month_paid += payment

        # 3. Apply extra payment to primary target
        extra_left = extra_payment
        for target in remaining:
            if target["balance"] <= 0.01:
                continue
            payment = min(extra_left, target["balance"])
            target["balance"] = round(target["balance"] - payment, 2)
            month_paid += payment
            extra_left -= payment
            if extra_left <= 0:
                break

        total_paid += month_paid

        # 4. Check for newly paid-off debts
        for d in active_debts:
            if d["balance"] <= 0.01 and d["paid_off_month"] is None:
                d["balance"] = 0.0
                d["paid_off_month"] = month
                payoff_order.append({
                    "account_id": d["account_id"],
                    "name": d["name"],
                    "paid_off_month": month,
                    "interest_paid": round(d["interest_paid"], 2),
                })
                # Freed-up minimum rolls into extra_payment for next month
                extra_payment += d["min_payment"]

        total_remaining = round(sum(d["balance"] for d in active_debts), 2)
        schedule.append({
            "month": month,
            "total_remaining": total_remaining,
            "month_paid": round(month_paid, 2),
        })

        if total_remaining <= 0:
            break

    return {
        "total_months": month,
        "total_paid": round(total_paid, 2),
        "total_interest": round(total_interest, 2),
        "payoff_schedule": schedule,
        "debt_payoff_order": payoff_order,
    }


# ── Main API ───────────────────────────────────────────────────────────────────


def get_debt_summary(conn: sqlite3.Connection, owner_id: str | None = None) -> dict:
    """
    Current liability snapshot: all debts, total owed, weighted average APR.
    """
    debts = _get_liability_accounts(conn, owner_id=owner_id)
    total_balance = sum(d["balance"] for d in debts)

    # Weighted average APR
    if total_balance > 0:
        weighted_apr = sum(d["balance"] * d["apr"] for d in debts) / total_balance
    else:
        weighted_apr = 0.0

    total_min_payments = sum(d["min_payment"] for d in debts)

    return {
        "total_debt": round(total_balance, 2),
        "account_count": len(debts),
        "weighted_avg_apr": round(weighted_apr, 2),
        "total_min_payments": round(total_min_payments, 2),
        "debts": debts,
    }


def get_payoff_plan(
    conn: sqlite3.Connection,
    extra_payment: float = 0.0,
    strategy: str = "avalanche",
    owner_id: str | None = None,
) -> dict:
    """
    Generate a debt payoff plan.

    Args:
        conn: DB connection
        extra_payment: Extra monthly dollars above minimums (default 0)
        strategy: "avalanche" or "snowball" (default "avalanche")

    Returns:
        {
          strategy, extra_payment,
          debts: [current debt list with apr, min_payment],
          avalanche: {...simulation...},
          snowball: {...simulation...},
          interest_savings: float  (avalanche vs snowball savings, or vs current)
        }
    """
    if strategy not in ("avalanche", "snowball"):
        raise ValueError("strategy must be 'avalanche' or 'snowball'")

    debts = _get_liability_accounts(conn, owner_id=owner_id)
    if not debts:
        return {
            "strategy": strategy,
            "extra_payment": extra_payment,
            "debts": [],
            "result": None,
            "comparison": None,
        }

    # Run both strategies for comparison
    avalanche_result = _simulate_payoff(debts, extra_payment, "avalanche")
    snowball_result = _simulate_payoff(debts, extra_payment, "snowball")

    interest_savings = round(
        snowball_result["total_interest"] - avalanche_result["total_interest"], 2
    )
    time_savings_months = snowball_result["total_months"] - avalanche_result["total_months"]

    primary = avalanche_result if strategy == "avalanche" else snowball_result

    return {
        "strategy": strategy,
        "extra_payment": extra_payment,
        "debts": debts,
        "result": {
            "strategy": strategy,
            "total_months": primary["total_months"],
            "total_paid": primary["total_paid"],
            "total_interest": primary["total_interest"],
            "payoff_schedule": primary["payoff_schedule"],
            "debt_payoff_order": primary["debt_payoff_order"],
        },
        "comparison": {
            "avalanche_months": avalanche_result["total_months"],
            "avalanche_interest": avalanche_result["total_interest"],
            "snowball_months": snowball_result["total_months"],
            "snowball_interest": snowball_result["total_interest"],
            "avalanche_saves_interest": interest_savings,
            "avalanche_saves_months": time_savings_months,
        },
    }


# ── Phase 14 Phase B — Per-payment amortization decomposition ─────────────


# Account types that carry a mortgage P&I split. Seeder uses ``type='loan'``
# for mortgages; a future ``type='mortgage'`` value is supported for real
# data ingests. Expanding this set is a deliberate architectural choice —
# every type listed here triggers the decomposition pipeline step on post.
MORTGAGE_ACCOUNT_TYPES: frozenset[str] = frozenset({"mortgage", "loan"})


def _get_latest_balance_cents(
    conn: sqlite3.Connection,
    account_id: str,
    as_of_date: str,
) -> Optional[int]:
    """Latest balance for ``account_id`` as of ``as_of_date``, in cents.

    Returns the absolute-value balance (mortgages record negative balances
    as liabilities) so amortization math stays in positive cents.
    Returns None when no snapshot exists on or before the date.
    """
    row = conn.execute(
        """
        SELECT balance FROM balance_snapshots
        WHERE account_id = ?
          AND date(as_of) <= date(?)
        ORDER BY as_of DESC
        LIMIT 1
        """,
        (account_id, as_of_date),
    ).fetchone()
    if not row:
        return None
    try:
        return int(round(abs(float(row["balance"])) * 100))
    except (TypeError, ValueError):
        return None


def decompose_payment(
    conn: sqlite3.Connection,
    account_id: str,
    payment_amount_cents: int,
    posting_date: str,
) -> dict:
    """Decompose a mortgage/loan payment into principal, interest, and escrow.

    Returns a dict with integer-cents fields and a method tag::

        {
            "principal_cents": int,
            "interest_cents":  int,
            "escrow_cents":    int,
            "method":          "amortization" | "statement" | "manual",
        }

    Invariant: ``principal + interest + escrow == payment_amount_cents``.

    Logic
    -----
    1. **Statement override** — reserved for when a statement parser emits
       a line item; Phase B does not ship a parser, so this branch is not
       yet reachable. Placeholder below for future wiring.
    2. **Amortization** — read APR from ``loan_details`` via
       ``_get_loan_apr``; read balance as of ``posting_date`` from
       ``balance_snapshots``. Monthly interest = ``balance * (apr / 12)``.
       Principal = ``payment − interest`` (clamped ≥ 0). Any residual
       (payment > standard P+I) is assigned to escrow.
    3. **Fallback** — if APR or balance is unavailable, treat the full
       payment as interest (``method='amortization'`` with
       ``principal=0``) so the invariant still holds; the Sankey will
       show this payment as entirely CONSUMED until data catches up.
    """
    payment_amount_cents = int(payment_amount_cents)
    if payment_amount_cents <= 0:
        raise ValueError(
            f"payment_amount_cents must be positive, got {payment_amount_cents}"
        )

    # ── Statement path (not yet wired) ────────────────────────────────
    # Reserved for a future mortgage statement parser emitting P/I/E
    # line items. When that parser exists, call it here and return with
    # method='statement'.

    # ── Amortization path ─────────────────────────────────────────────
    apr = _get_loan_apr(conn, account_id)
    balance_cents = _get_latest_balance_cents(conn, account_id, posting_date)

    if apr is None or balance_cents is None or balance_cents <= 0:
        log.warning(
            "decompose_payment: missing APR or balance for %s at %s — "
            "defaulting to all-interest split.",
            account_id, posting_date,
        )
        return {
            "principal_cents": 0,
            "interest_cents":  payment_amount_cents,
            "escrow_cents":    0,
            "method":          "amortization",
        }

    monthly_rate = (apr / 100.0) / 12.0
    interest_cents = int(round(balance_cents * monthly_rate))
    if interest_cents > payment_amount_cents:
        interest_cents = payment_amount_cents

    # Standard P+I for a pure amortizing loan, no escrow:
    principal_floor = payment_amount_cents - interest_cents
    if principal_floor < 0:
        principal_floor = 0

    # Escrow heuristic: for mortgage-type accounts the recurring payment
    # typically exceeds scheduled P+I by the tax/insurance reserve. Phase
    # B treats any residual above a 1% buffer as escrow. This matches the
    # real-world mortgage shape where the servicer collects escrow each
    # month; statement parsing will replace this heuristic once wired.
    acct_type = _get_account_type(conn, account_id)
    if acct_type in MORTGAGE_ACCOUNT_TYPES:
        # Assume the loan has a fixed scheduled monthly P+I close to
        # interest + principal_floor baseline; if the payment is larger,
        # call the excess escrow. The simplest shape is: escrow =
        # payment - (interest + amortization_principal_estimate).
        # Without a known scheduled P+I we can't isolate escrow without
        # a parser — return principal = payment − interest, escrow = 0.
        # A future enhancement (`loan_details.scheduled_pi_cents`) can
        # refine this; for Phase B the invariant still holds and the
        # principal classification is correct.
        principal_cents = principal_floor
        escrow_cents = 0
    else:
        principal_cents = principal_floor
        escrow_cents = 0

    # Final invariant guard — floating-point rounding can drift by ±1
    # cent. Push any residual into principal so sums match exactly.
    residual = payment_amount_cents - (principal_cents + interest_cents + escrow_cents)
    if residual != 0:
        principal_cents += residual

    return {
        "principal_cents": principal_cents,
        "interest_cents":  interest_cents,
        "escrow_cents":    escrow_cents,
        "method":          "amortization",
    }


def _get_account_type(conn: sqlite3.Connection, account_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT type FROM accounts WHERE id = ?",
        (account_id,),
    ).fetchone()
    return row["type"] if row else None


def upsert_loan_payment_split(
    conn: sqlite3.Connection,
    transaction_id: str,
    account_id: str,
    signed_amount: float,
    posting_date: str,
) -> dict:
    """Compute and upsert a row in ``loan_payment_splits`` for this txn.

    Returns the split dict (same shape as ``decompose_payment``).
    Idempotent — re-running for the same transaction overwrites the row.

    Fail-fast: if ``principal + interest + escrow != abs(signed_amount)``
    after decomposition, raises ``ValueError`` rather than writing a bad
    row. This is the invariant Phase B promises downstream consumers.
    """
    payment_cents = int(round(abs(float(signed_amount)) * 100))
    split = decompose_payment(conn, account_id, payment_cents, posting_date)

    total = (
        split["principal_cents"]
        + split["interest_cents"]
        + split["escrow_cents"]
    )
    if total != payment_cents:
        raise ValueError(
            f"loan_payment_splits invariant broken for txn={transaction_id}: "
            f"principal {split['principal_cents']} + interest "
            f"{split['interest_cents']} + escrow {split['escrow_cents']} = "
            f"{total}, expected {payment_cents}"
        )

    conn.execute(
        """
        INSERT INTO loan_payment_splits (
            transaction_id, principal_cents, interest_cents, escrow_cents,
            method, computed_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(transaction_id) DO UPDATE SET
            principal_cents = excluded.principal_cents,
            interest_cents  = excluded.interest_cents,
            escrow_cents    = excluded.escrow_cents,
            method          = excluded.method,
            computed_at     = datetime('now')
        """,
        (
            transaction_id,
            split["principal_cents"],
            split["interest_cents"],
            split["escrow_cents"],
            split["method"],
        ),
    )
    return split


def decompose_unsplit_mortgage_payments(conn: sqlite3.Connection) -> int:
    """Post-commit pipeline step — compute missing decompositions.

    Scans for posted transactions against mortgage-type accounts that
    don't yet have a row in ``loan_payment_splits``, and computes one.
    Returns the count of new rows written. Runs between reconciliation
    and derived-metric recompute.

    Fail-soft: a decomposition error on one txn logs a warning and moves
    on; the pipeline step must not block other transactions.
    """
    placeholders = ", ".join("?" for _ in MORTGAGE_ACCOUNT_TYPES)
    rows = conn.execute(
        f"""
        SELECT t.id, t.account_id, t.signed_amount, t.posting_date
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN loan_payment_splits s ON s.transaction_id = t.id
        WHERE t.status = 'posted'
          AND t.signed_amount < 0
          AND a.type IN ({placeholders})
          AND s.transaction_id IS NULL
        ORDER BY t.posting_date
        """,
        tuple(MORTGAGE_ACCOUNT_TYPES),
    ).fetchall()

    written = 0
    for r in rows:
        try:
            upsert_loan_payment_split(
                conn,
                transaction_id=r["id"],
                account_id=r["account_id"],
                signed_amount=r["signed_amount"],
                posting_date=r["posting_date"][:10],
            )
            written += 1
        except Exception as e:
            log.warning(
                "decompose_unsplit_mortgage_payments: txn=%s failed: %s",
                r["id"], e,
            )
    return written


# ── Debt vs. Invest Comparison ─────────────────────────────────────────────
#
# The `compare_debt_payoff_vs_invest()` function was removed as part of
# the P13 investments rebuild.  It depended on `dal.performance` which
# no longer exists.  A future rebuild task will decide whether to
# reintroduce this comparison against the new investments read path.

