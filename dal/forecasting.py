"""
dal/forecasting.py — Cash flow forecasting engine.

Projects future monthly income, spending, and running balance N months
forward by combining two data sources:

  1. Known recurring transactions (baseline — high confidence)
     - Active recurring items from recurring_transactions table
     - Normalized to monthly amounts by frequency

  2. Discretionary rolling average (remaining spend — moderate confidence)
     - Last M months of actual spending per category
     - Subtract recurring baseline to avoid double-counting
     - Categories excluded from budgeting (Transfers, etc.) are excluded

Algorithm per month:
  projected_income   = avg monthly income (last M months, non-transfer credits)
  projected_spending = recurring_monthly_total + avg_discretionary_monthly
  projected_balance  = prev_balance + projected_income - projected_spending

Returns a list of monthly forecast dicts, one per projected month.

Seasonal income model (P3-T01):
  Decomposes income into 4 stream types (flat, episodic, seasonal) and
  produces per-month composite income projections with lump-sum exclusion.
"""

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Optional

log = logging.getLogger("sentry.dal.forecasting")

# Attribution-aware month expression (mirrors dal/cash_flow.py)
_EM = "COALESCE(effective_month, strftime('%Y-%m', posting_date))"

# ── Category sets — imported from canonical single source of truth ────────────
from dal.category_classifications import (
    EXCLUDED_FROM_FORECAST as _EXCLUDED_CATEGORIES,
    NON_PROJECTION_INCOME as _NON_PROJECTION_INCOME_CATEGORIES,
)

# Category → stream mapping for seasonal income model
_STREAM_MAP = {
    "Military Pension": "pension",
    "VA Benefits": "disability",
    "VA Disability": "disability",
    "VA Education Benefits": "education",
    "Officiating Income": "officiating",
}

# Frequency → monthly multiplier
_MONTHLY_FACTORS = {
    "weekly": 4.33,
    "biweekly": 2.17,
    "monthly": 1.0,
    "bimonthly": 0.5,
    "quarterly": 0.333,
    "semiannual": 0.167,
    "annual": 0.083,
}


# ── Outlier Detection ────────────────────────────────────────────────────────


def _exclude_outliers(
    amounts: list[float],
    threshold_multiplier: float = 3.0,
) -> tuple[list[float], list[float]]:
    """
    Split amounts into normal and outlier lists.

    A transaction is an outlier if it exceeds threshold_multiplier × the median
    of all amounts in the series.

    Args:
        amounts: List of transaction amounts (absolute values expected).
        threshold_multiplier: Multiplier applied to the median to define
            the outlier boundary (default 3.0).

    Returns:
        (normal, outliers) — two lists of floats.
    """
    if len(amounts) < 3:
        return list(amounts), []

    med = median(amounts)
    if med <= 0:
        return list(amounts), []

    threshold = med * threshold_multiplier
    normal = []
    outliers = []
    for a in amounts:
        if a > threshold:
            outliers.append(a)
        else:
            normal.append(a)
    return normal, outliers


# ── Seasonal Income Model ────────────────────────────────────────────────────


def build_seasonal_income_model(
    conn: sqlite3.Connection,
    lookback_years: int = 2,
) -> dict:
    """
    Build a composite income model with per-stream seasonal curves.

    Analyzes historical transactions by income sub-category to produce
    monthly coefficients for seasonal streams.

    Returns:
    {
        "streams": {
            "pension": {"type": "flat", "monthly": float},
            "disability": {"type": "flat", "monthly": float},
            "education": {"type": "episodic", "monthly": float, "active_months": [...]},
            "officiating": {
                "type": "seasonal",
                "annual_total": float,
                "monthly_coefficients": {1: 0.15, 2: 0.12, ..., 12: 0.0},
            },
        },
        "composite_monthly": {1: float, 2: float, ..., 12: float},
        "avg_monthly_total": float,
        "income_model": str,
        "excluded_transactions": [...],
        "projection_note": str,
    }
    """
    from dal.category_classifications import INCOME_CATEGORIES as _INCOME_CATEGORIES

    now = datetime.now(timezone.utc)
    cutoff = f"{now.year - lookback_years}-{now.month:02d}-01"

    # ── Step 0: Fetch all income transactions in lookback window ──────
    income_cats = list(_INCOME_CATEGORIES)
    placeholders = ", ".join("?" for _ in income_cats)

    all_txns = conn.execute(
        f"""
        SELECT posting_date, category, signed_amount
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND posting_date >= ?
          AND signed_amount > 0
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') IN ({placeholders})
        ORDER BY posting_date
        """,
        [cutoff] + income_cats,
    ).fetchall()

    excluded_transactions: list[dict] = []

    # ── Step 0a: Exclude non-projection categories ───────────────────
    working_txns = []
    for t in all_txns:
        cat = t["category"] or "Uncategorized"
        if cat in _NON_PROJECTION_INCOME_CATEGORIES:
            excluded_transactions.append({
                "date": t["posting_date"],
                "category": cat,
                "amount": round(t["signed_amount"], 2),
                "reason": "non_projection_category",
            })
        else:
            working_txns.append(t)

    # ── Check for sufficient history ─────────────────────────────────
    if not working_txns:
        return _flat_fallback_model(excluded_transactions, "no_income_data")

    dates = [datetime.strptime(t["posting_date"], "%Y-%m-%d") for t in working_txns]
    earliest = min(dates)
    latest = max(dates)
    months_span = (latest.year - earliest.year) * 12 + (latest.month - earliest.month)
    if months_span < 12:
        return _flat_fallback_model(excluded_transactions, "flat_insufficient_data")

    # ── Step 1: Group transactions by stream ─────────────────────────
    stream_txns: dict[str, list[dict]] = defaultdict(list)
    for t in working_txns:
        cat = t["category"] or "Uncategorized"
        stream_name = _STREAM_MAP.get(cat, "other")
        stream_txns[stream_name].append({
            "date": t["posting_date"],
            "month": int(t["posting_date"][5:7]),
            "amount": t["signed_amount"],
        })

    # ── Step 2: Build per-stream models ──────────────────────────────
    streams: dict[str, dict] = {}
    years_in_window = max(1, lookback_years)

    # -- Flat streams (pension, disability, other) ─────────────────────
    for stream_name in ("pension", "disability", "other"):
        txns = stream_txns.get(stream_name, [])
        if not txns:
            if stream_name != "other":
                streams[stream_name] = {"type": "flat", "monthly": 0.0}
            continue

        amounts = [t["amount"] for t in txns]
        normal, outliers = _exclude_outliers(amounts)

        # Record outliers as excluded
        if outliers:
            # Match outlier amounts back to transactions for dates
            outlier_set = list(outliers)
            for t in txns:
                if t["amount"] in outlier_set:
                    cat = _get_category_for_stream(stream_name)
                    excluded_transactions.append({
                        "date": t["date"],
                        "category": cat,
                        "amount": round(t["amount"], 2),
                        "reason": "outlier_lump_sum",
                    })
                    outlier_set.remove(t["amount"])

        monthly_avg = round(sum(normal) / max(1, len(normal)), 2) if normal else 0.0
        # Adjust: if we have many transactions per month, compute per-month averages
        months_with_income = len(set(t["date"][:7] for t in txns if t["amount"] in normal or not outliers))
        if months_with_income > 0 and normal:
            monthly_avg = round(sum(normal) / months_with_income, 2)

        streams[stream_name] = {"type": "flat", "monthly": monthly_avg}

    # -- Episodic stream (education) ──────────────────────────────────
    edu_txns = stream_txns.get("education", [])
    if edu_txns:
        # Identify which months have education income
        month_years: dict[int, set[int]] = defaultdict(set)
        month_totals: dict[int, list[float]] = defaultdict(list)
        for t in edu_txns:
            dt = datetime.strptime(t["date"], "%Y-%m-%d")
            month_years[dt.month].add(dt.year)
            month_totals[dt.month].append(t["amount"])

        all_years = set()
        for t in edu_txns:
            all_years.add(datetime.strptime(t["date"], "%Y-%m-%d").year)
        num_years = max(1, len(all_years))

        # Active months = months where income appeared in >50% of years
        active_months = sorted(
            m for m, years in month_years.items()
            if len(years) / num_years > 0.5
        )

        # Average of non-zero months
        active_amounts = []
        for m in active_months:
            active_amounts.extend(month_totals.get(m, []))
        monthly_avg = round(sum(active_amounts) / max(1, len(active_months)), 2) if active_amounts else 0.0

        streams["education"] = {
            "type": "episodic",
            "monthly": monthly_avg,
            "active_months": active_months,
        }
    else:
        streams["education"] = {
            "type": "episodic",
            "monthly": 0.0,
            "active_months": [],
        }

    # -- Seasonal stream (officiating) ────────────────────────────────
    off_txns = stream_txns.get("officiating", [])
    if off_txns:
        amounts = [t["amount"] for t in off_txns]
        normal, outliers = _exclude_outliers(amounts)

        # Record outliers
        if outliers:
            outlier_set = list(outliers)
            for t in off_txns:
                if t["amount"] in outlier_set:
                    excluded_transactions.append({
                        "date": t["date"],
                        "category": "Officiating Income",
                        "amount": round(t["amount"], 2),
                        "reason": "outlier_lump_sum",
                    })
                    outlier_set.remove(t["amount"])

        # Build normal-only transaction list for coefficient computation
        normal_set = list(normal)
        normal_txns = []
        for t in off_txns:
            if t["amount"] in normal_set:
                normal_txns.append(t)
                normal_set.remove(t["amount"])

        # Monthly totals for coefficient computation
        month_totals: dict[int, float] = defaultdict(float)
        for t in normal_txns:
            month_totals[t["month"]] += t["amount"]

        grand_total = sum(month_totals.values())
        coefficients = {}
        for m in range(1, 13):
            if grand_total > 0:
                coefficients[m] = round(month_totals.get(m, 0.0) / grand_total, 4)
            else:
                coefficients[m] = 0.0

        # Annual total: average of available years, using filtered amounts
        year_totals: dict[int, float] = defaultdict(float)
        for t in normal_txns:
            yr = int(t["date"][:4])
            year_totals[yr] += t["amount"]

        if year_totals:
            # Use most recent complete year, or average if none complete
            current_year = now.year
            complete_years = {y: t for y, t in year_totals.items() if y < current_year}
            if complete_years:
                annual_total = round(sum(complete_years.values()) / len(complete_years), 2)
            else:
                annual_total = round(sum(year_totals.values()) / len(year_totals), 2)
        else:
            annual_total = 0.0

        streams["officiating"] = {
            "type": "seasonal",
            "annual_total": annual_total,
            "monthly_coefficients": coefficients,
        }
    else:
        streams["officiating"] = {
            "type": "seasonal",
            "annual_total": 0.0,
            "monthly_coefficients": {m: 0.0 for m in range(1, 13)},
        }

    # ── Step 3: Composite monthly projections ────────────────────────
    composite_monthly: dict[int, float] = {}
    for m in range(1, 13):
        total = 0.0
        # Flat streams
        for sn in ("pension", "disability", "other"):
            s = streams.get(sn)
            if s:
                total += s["monthly"]
        # Episodic
        edu = streams.get("education", {})
        if edu.get("type") == "episodic":
            if m in edu.get("active_months", []):
                total += edu["monthly"]
        # Seasonal
        off = streams.get("officiating", {})
        if off.get("type") == "seasonal":
            coeff = off.get("monthly_coefficients", {}).get(m, 0.0)
            total += off.get("annual_total", 0.0) * coeff

        composite_monthly[m] = round(total, 2)

    avg_monthly_total = round(sum(composite_monthly.values()) / 12, 2)

    # ── Projection note ──────────────────────────────────────────────
    excl_count = len(excluded_transactions)
    excl_total = sum(e["amount"] for e in excluded_transactions)
    if excl_count > 0:
        # Build detail breakdown
        by_reason: dict[str, int] = defaultdict(int)
        for e in excluded_transactions:
            if e["reason"] == "outlier_lump_sum":
                cat = e["category"]
                by_reason[f"{cat} outliers"] += 1
            else:
                by_reason[e["category"]] += 1
        details = ", ".join(f"{count} {label}" for label, count in by_reason.items())
        projection_note = (
            f"Excluded {excl_count} transactions totaling ${excl_total:,.2f} from income model "
            f"({details}). These are in the historical record but not projected to recur."
        )
    else:
        projection_note = "No transactions excluded from income model."

    # Remove "other" stream if it's zero
    if streams.get("other", {}).get("monthly", 0) == 0:
        streams.pop("other", None)

    return {
        "streams": streams,
        "composite_monthly": composite_monthly,
        "avg_monthly_total": avg_monthly_total,
        "income_model": "seasonal",
        "excluded_transactions": excluded_transactions,
        "projection_note": projection_note,
    }


def _flat_fallback_model(
    excluded_transactions: list[dict],
    reason: str,
) -> dict:
    """Return a degenerate seasonal model when data is insufficient."""
    return {
        "streams": {},
        "composite_monthly": {m: 0.0 for m in range(1, 13)},
        "avg_monthly_total": 0.0,
        "income_model": reason,
        "excluded_transactions": excluded_transactions,
        "projection_note": f"Insufficient data for seasonal model ({reason}).",
    }


def _get_category_for_stream(stream_name: str) -> str:
    """Reverse-lookup: stream name → representative category string."""
    reverse = {v: k for k, v in _STREAM_MAP.items()}
    return reverse.get(stream_name, stream_name)


# ── Balance & Recurring Helpers ──────────────────────────────────────────────


def _get_current_balance(
    conn: sqlite3.Connection,
    account_ids: Optional[list[str]] = None,
) -> float:
    """Sum of latest balances across liquid accounts (checking + savings).

    Honors the ``None`` vs ``[]`` distinction (see
    ``dal/owners.build_account_filter`` for rationale): an explicit empty
    list means "no matching accounts" and must return 0, not leak all
    liquid balances.
    """
    if account_ids is not None and len(account_ids) == 0:
        return 0.0
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        rows = conn.execute(
            f"""
            SELECT bs.balance
            FROM balance_snapshots bs
            JOIN accounts a ON a.id = bs.account_id
            WHERE a.type IN ('checking', 'savings')
              AND a.id IN ({placeholders})
              AND bs.id = (
                  SELECT id FROM balance_snapshots b2
                  WHERE b2.account_id = bs.account_id
                  ORDER BY b2.as_of DESC LIMIT 1
              )
            """,
            account_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT bs.balance
            FROM balance_snapshots bs
            JOIN accounts a ON a.id = bs.account_id
            WHERE a.type IN ('checking', 'savings')
              AND bs.id = (
                  SELECT id FROM balance_snapshots b2
                  WHERE b2.account_id = bs.account_id
                  ORDER BY b2.as_of DESC LIMIT 1
              )
            """
        ).fetchall()

    return sum((r["balance"] or 0) for r in rows)


def _get_recurring_monthly_total(
    conn: sqlite3.Connection,
    account_ids: Optional[list[str]] = None,
    target_month: Optional[str] = None,
) -> float:
    """Monthly total of active, stable-amount recurring expenses.

    Args:
        conn: DB connection.
        account_ids: Restrict to specific accounts.
        target_month: If set (YYYY-MM), exclude recurring items whose
            linked loan has a maturity_date on or before this month.
    """
    clauses = [
        "status = 'active'",
        "amount_stable = 1",
        "expected_amount IS NOT NULL",
    ]
    params: list = []

    # Honor None vs [] — see dal/owners.build_account_filter.
    if account_ids is not None and len(account_ids) == 0:
        return 0.0
    if account_ids:
        placeholders = ", ".join("?" for _ in account_ids)
        clauses.append(f"account_id IN ({placeholders})")
        params.extend(account_ids)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""SELECT frequency, expected_amount, category, linked_account_id
            FROM recurring_transactions WHERE {where}""",
        params,
    ).fetchall()

    # If target_month is set, look up maturity dates for linked accounts.
    # Single IN(...) fetch replaces the previous cache-as-you-loop shape,
    # which reverted to N+1 the moment the cache guard was removed.
    maturity_cache: dict[str, Optional[str]] = {}
    if target_month:
        linked_ids = {
            r["linked_account_id"]
            for r in rows
            if "linked_account_id" in r.keys() and r["linked_account_id"]
        }
        if linked_ids:
            placeholders_m = ", ".join("?" for _ in linked_ids)
            # Default every linked account to None so lookups below stay O(1)
            # even for accounts with no maturity_date row.
            maturity_cache = {lid: None for lid in linked_ids}
            for mat_row in conn.execute(
                f"""
                SELECT account_id, field_value FROM (
                    SELECT account_id, field_value,
                           ROW_NUMBER() OVER (
                             PARTITION BY account_id ORDER BY as_of DESC
                           ) AS rn
                      FROM loan_details
                     WHERE account_id IN ({placeholders_m})
                       AND LOWER(field_name) = 'maturity_date'
                ) ranked
                 WHERE rn = 1
                   AND field_value IS NOT NULL
                """,
                list(linked_ids),
            ).fetchall():
                maturity_cache[mat_row["account_id"]] = _normalize_date(mat_row["field_value"])

    total = 0.0
    for r in rows:
        cat = r["category"] or "Uncategorized"
        if cat in _EXCLUDED_CATEGORIES:
            continue

        # Check if this recurring item's linked loan is paid off by target_month
        if target_month:
            linked = r["linked_account_id"] if "linked_account_id" in r.keys() else None
            if linked:
                maturity = maturity_cache.get(linked)
                if maturity and target_month >= maturity[:7]:
                    continue  # Loan paid off — skip this recurring expense

        factor = _MONTHLY_FACTORS.get(r["frequency"], 1.0)
        total += (r["expected_amount"] or 0) * factor

    return round(total, 2)


def _normalize_date(raw: str) -> Optional[str]:
    """Normalize various date formats to YYYY-MM-DD."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _get_rolling_averages(
    conn: sqlite3.Connection,
    months_back: int = 3,
    account_ids: Optional[list[str]] = None,
) -> tuple[float, float]:
    """
    Compute rolling average monthly income and discretionary spending.

    Returns:
        (avg_income, avg_discretionary_spending)  — both positive floats
    """
    excluded_list = list(_EXCLUDED_CATEGORIES)
    excl_placeholders = ", ".join("?" for _ in excluded_list)

    base_params: list = excluded_list
    acct_filter = ""
    # Honor None vs [] — see dal/owners.build_account_filter.
    if account_ids is not None and len(account_ids) == 0:
        return (0.0, 0.0)
    if account_ids:
        acct_placeholders = ", ".join("?" for _ in account_ids)
        acct_filter = f" AND account_id IN ({acct_placeholders})"
        base_params = excluded_list + account_ids

    # Monthly spending (debits only, excluding excluded categories)
    spend_rows = conn.execute(
        f"""
        SELECT {_EM} as month,
               SUM(amount) as total
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND posting_date >= date('now', '-{months_back} months')
          AND direction = 'Debit'
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
          {acct_filter}
        GROUP BY month
        """,
        base_params,
    ).fetchall()

    # Monthly income (credits only, excluding excluded categories)
    income_rows = conn.execute(
        f"""
        SELECT {_EM} as month,
               SUM(signed_amount) as total
        FROM transactions
        WHERE status = 'posted'
          AND posting_date IS NOT NULL
          AND posting_date >= date('now', '-{months_back} months')
          AND direction = 'Credit'
          AND transfer_tag IS NULL
          AND COALESCE(category, 'Uncategorized') NOT IN ({excl_placeholders})
          {acct_filter}
        GROUP BY month
        """,
        base_params,
    ).fetchall()

    spend_vals = [r["total"] or 0 for r in spend_rows if r["total"]]
    income_vals = [r["total"] or 0 for r in income_rows if r["total"]]

    avg_spending = sum(spend_vals) / len(spend_vals) if spend_vals else 0
    avg_income = sum(income_vals) / len(income_vals) if income_vals else 0

    return round(avg_income, 2), round(avg_spending, 2)


# ── Cash Flow Forecast ───────────────────────────────────────────────────────


def get_cash_flow_forecast(
    conn: sqlite3.Connection,
    months: int = 6,
    history_months: int = 3,
    account_ids: Optional[list[str]] = None,
    use_seasonal: bool = False,
) -> dict:
    """
    Project cash flow for the next N months.

    Args:
        conn: Active database connection.
        months: Number of months to project forward (default 6).
        history_months: Months of history to use for rolling averages.
        account_ids: Restrict to specific accounts (None = all).
        use_seasonal: Use seasonal income model (P3-T01) instead of flat average.

    Returns:
        {
          "current_balance": float,
          "recurring_monthly": float,
          "avg_income": float,
          "avg_discretionary": float,
          "income_model": "flat" | "seasonal",
          "months": [
            {
              "month": "YYYY-MM",
              "projected_income": float,
              "projected_spending": float,
              "projected_net": float,
              "projected_balance": float,
            }, ...
          ]
        }
    """
    current_balance = _get_current_balance(conn, account_ids)
    avg_income, avg_total_spending = _get_rolling_averages(
        conn, history_months, account_ids
    )

    # Build seasonal income model if requested
    seasonal_model = None
    income_model_name = "flat"
    if use_seasonal:
        seasonal_model = build_seasonal_income_model(conn)
        if seasonal_model.get("income_model") == "seasonal":
            income_model_name = "seasonal"

    now = datetime.now(timezone.utc)
    running_balance = current_balance
    forecast = []

    for i in range(1, months + 1):
        # Advance month
        total_months = now.month + i - 1
        year = now.year + total_months // 12
        month = (total_months % 12) or 12
        if total_months % 12 == 0:
            year -= 1
        month_str = f"{year}-{month:02d}"

        # Income: seasonal per-month or flat average
        if income_model_name == "seasonal" and seasonal_model:
            month_income = seasonal_model["composite_monthly"].get(month, avg_income)
        else:
            month_income = avg_income

        # Spending: use target_month to respect loan payoff dates (P3-T02)
        recurring_monthly = _get_recurring_monthly_total(
            conn, account_ids, target_month=month_str
        )
        discretionary = max(0.0, round(avg_total_spending - recurring_monthly, 2))
        projected_monthly_spending = round(recurring_monthly + discretionary, 2)

        net = round(month_income - projected_monthly_spending, 2)
        running_balance = round(running_balance + net, 2)

        forecast.append({
            "month": month_str,
            "projected_income": round(month_income, 2),
            "projected_spending": projected_monthly_spending,
            "projected_net": net,
            "projected_balance": running_balance,
        })

    # Compute summary values for backward compatibility
    recurring_monthly_summary = _get_recurring_monthly_total(conn, account_ids)
    discretionary_summary = max(0.0, round(avg_total_spending - recurring_monthly_summary, 2))

    log.info(
        "Forecast inputs: balance=%.2f recurring=%.2f avg_income=%.2f model=%s",
        current_balance,
        recurring_monthly_summary,
        avg_income,
        income_model_name,
    )

    return {
        "current_balance": round(current_balance, 2),
        "recurring_monthly": recurring_monthly_summary,
        "avg_income": avg_income,
        "avg_discretionary": discretionary_summary,
        "history_months_used": history_months,
        "income_model": income_model_name,
        "months": forecast,
    }
