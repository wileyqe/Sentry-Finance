"""
dal/recurring.py — Recurring transaction detection engine.

Scans transaction history to identify:
  - Fixed subscriptions (Netflix, Disney+, etc.)
  - Bills (mortgage, utilities, insurance)
  - Regular transfers (loan payments, CC payments)
  - Income patterns (payroll, benefits)

Tracks price changes (mutations) and auto-deactivates cancelled items.
"""

import hashlib
import logging
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("sentry.dal.recurring")


# ── Frequency Classification ────────────────────────────────────────────────

FREQUENCY_BANDS = [
    (5, 9, "weekly"),
    (12, 16, "biweekly"),
    (25, 35, "monthly"),
    (55, 70, "bimonthly"),
    (80, 100, "quarterly"),
    (170, 200, "semiannual"),
    (350, 380, "annual"),
]


def classify_frequency(avg_interval: float) -> Optional[str]:
    """Classify an average interval (days) into a named frequency."""
    for lo, hi, name in FREQUENCY_BANDS:
        if lo <= avg_interval <= hi:
            return name
    return None


# ── Merchant Normalization ───────────────────────────────────────────────────

# Patterns to strip from descriptions to create stable merchant keys
_STRIP_PATTERNS = [
    re.compile(r"\b(XX|xx)[\-]?\d{3,}", re.IGNORECASE),      # card suffixes: XX0483, XX-9035
    re.compile(r"\b\d{3}[\-]\d{3}[\-]\d{4}\b"),               # phone numbers
    re.compile(r"#\d+"),                                        # store numbers: #330
    re.compile(r"\*[A-Z0-9]{6,}"),                             # reference IDs: *S34C22SD3
    re.compile(r"\b[A-Z]{2}\s*$"),                             # trailing state codes
    re.compile(r"\s*-\s*\d{4}\s*$"),                           # trailing account: - 0837
    re.compile(r"\bWEB ID:.*$", re.IGNORECASE),                # WEB ID suffixes
    re.compile(r"\bPPD ID:.*$", re.IGNORECASE),                # PPD ID suffixes
    re.compile(r"DEBIT-DC\s+\d{4}\s*", re.IGNORECASE),        # DEBIT-DC 0483
    re.compile(r"POS DEBIT-DC\s+\d{4}\s*", re.IGNORECASE),    # POS DEBIT-DC 0483
    re.compile(r"\bnull\b", re.IGNORECASE),                    # literal "null"
    re.compile(r"\b\d{1,2}/\d{1,2}\b"),                       # date references: 10/16
    re.compile(r"\bHTTPS?:?\S*", re.IGNORECASE),               # URLs
    re.compile(r"\s+"),                                         # collapse whitespace
]

# Known merchant aliases → canonical name
_MERCHANT_ALIASES = {
    "amzn mktp": "amazon",
    "amazon reta": "amazon",
    "amazon mktpl": "amazon",
    "amazon.com": "amazon",
    "amazon ret": "amazon",
    "amazon mark": "amazon",
    "amz*": "amazon",
    "wm supercenter": "walmart",
    "wal-mart": "walmart",
    "mcdonald's": "mcdonalds",
    "dd *doordash": "doordash",
    "sq *aaronmybarber": "aaronmybarber",
    "coursra": "coursera",
}


def normalize_merchant(description: str) -> str:
    """Create a stable merchant key from a transaction description.

    Strips noise (card numbers, ref IDs, store numbers, state codes)
    and normalizes to lowercase for grouping.
    """
    if not description:
        return ""
    s = description.strip().lower()
    # Collapse whitespace early so alias matching works on "amzn  mktp" etc.
    s = re.sub(r"\s+", " ", s)

    # Apply alias mapping (check prefixes)
    for alias, canonical in _MERCHANT_ALIASES.items():
        if s.startswith(alias) or f" {alias}" in s:
            s = canonical
            break

    # Strip noise patterns
    for pat in _STRIP_PATTERNS:
        s = pat.sub(" ", s)

    return s.strip()[:40]  # cap at 40 chars for key stability


def _make_recurring_id(account_id: str, merchant_key: str) -> str:
    """Generate a deterministic ID for a recurring transaction entry."""
    raw = f"{account_id}|{merchant_key}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"rec:{h}"


# ── Detection Algorithm ─────────────────────────────────────────────────────


def detect_recurring(conn: sqlite3.Connection) -> dict:
    """Scan all transactions and detect/update recurring patterns.

    Returns:
        {"created": int, "updated": int, "deactivated": int}
    """
    stats = {"created": 0, "updated": 0, "deactivated": 0}
    now = datetime.now(timezone.utc)

    # Fetch all posted transactions
    rows = conn.execute("""
        SELECT id, account_id, institution_id, posting_date, amount,
               signed_amount, description, category
        FROM transactions
        WHERE status = 'posted'
        ORDER BY posting_date
    """).fetchall()

    # Group by (account_id, normalized merchant)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        merchant = normalize_merchant(r["description"] or "")
        if not merchant:
            continue
        key = (r["account_id"], merchant)
        try:
            datetime.strptime(r["posting_date"], "%Y-%m-%d")
            groups[key].append(dict(r))
        except (ValueError, TypeError):
            continue

    # Analyze each group
    for (account_id, merchant), txns in groups.items():
        if len(txns) < 3:
            continue

        # Sort by date
        txns.sort(key=lambda t: t["posting_date"])
        dates = [datetime.strptime(t["posting_date"], "%Y-%m-%d") for t in txns]
        intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]

        if not intervals:
            continue

        avg_interval = sum(intervals) / len(intervals)
        frequency = classify_frequency(avg_interval)

        if frequency is None:
            continue  # Not a recognizable frequency

        # Amount analysis
        amounts = [t["amount"] for t in txns]
        min_amt, max_amt = min(amounts), max(amounts)
        latest_amount = amounts[-1]
        avg_amount = sum(amounts) / len(amounts)

        # Amount stability: stable if range is < 5% of average (or < $2 absolute)
        if avg_amount > 0:
            amt_range_pct = (max_amt - min_amt) / avg_amount
        else:
            amt_range_pct = 0
        amount_stable = 1 if (amt_range_pct < 0.05 or (max_amt - min_amt) < 2.0) else 0

        expected_amount = round(avg_amount, 2) if amount_stable else None
        last_date = txns[-1]["posting_date"]
        next_expected = (dates[-1] + timedelta(days=round(avg_interval))).strftime("%Y-%m-%d")
        category = txns[-1].get("category", "Uncategorized")

        rec_id = _make_recurring_id(account_id, merchant)

        # Check if already exists
        existing = conn.execute(
            "SELECT id, expected_amount, status FROM recurring_transactions WHERE id = ?",
            (rec_id,),
        ).fetchone()

        if existing is None:
            # Create new recurring entry
            conn.execute("""
                INSERT INTO recurring_transactions
                    (id, account_id, merchant, category, frequency,
                     avg_interval, expected_amount, amount_stable,
                     last_amount, last_date, next_expected,
                     occurrence_count, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """, (
                rec_id, account_id, merchant, category, frequency,
                round(avg_interval, 1), expected_amount, amount_stable,
                latest_amount, last_date, next_expected, len(txns),
            ))
            stats["created"] += 1
        else:
            # Update existing entry
            old_amount = existing["expected_amount"]

            # Detect mutation (price change) for stable-amount items
            if (
                old_amount is not None
                and expected_amount is not None
                and abs(old_amount - expected_amount) > 0.01
                and abs(old_amount - expected_amount) / old_amount > 0.02
            ):
                conn.execute("""
                    INSERT INTO recurring_mutations
                        (recurring_id, old_amount, new_amount, description)
                    VALUES (?, ?, ?, ?)
                """, (
                    rec_id,
                    old_amount,
                    expected_amount,
                    f"{merchant} price change: ${old_amount:.2f} -> ${expected_amount:.2f}",
                ))
                log.info(
                    "Mutation detected: %s %s -> %s",
                    merchant, old_amount, expected_amount,
                )

            conn.execute("""
                UPDATE recurring_transactions
                SET category = ?, frequency = ?, avg_interval = ?,
                    expected_amount = ?, amount_stable = ?,
                    last_amount = ?, last_date = ?, next_expected = ?,
                    occurrence_count = ?, status = 'active',
                    updated_at = datetime('now')
                WHERE id = ?
            """, (
                category, frequency, round(avg_interval, 1),
                expected_amount, amount_stable,
                latest_amount, last_date, next_expected, len(txns),
                rec_id,
            ))
            stats["updated"] += 1

    # Deactivate recurring items that haven't appeared in 2× their interval
    active = conn.execute(
        "SELECT id, next_expected, avg_interval FROM recurring_transactions "
        "WHERE status = 'active'"
    ).fetchall()

    for rec in active:
        if rec["next_expected"] is None:
            continue
        try:
            next_dt = datetime.strptime(rec["next_expected"], "%Y-%m-%d")
            grace = timedelta(days=rec["avg_interval"] * 2)
            if now > next_dt + grace:
                conn.execute(
                    "UPDATE recurring_transactions SET status = 'inactive', "
                    "updated_at = datetime('now') WHERE id = ?",
                    (rec["id"],),
                )
                stats["deactivated"] += 1
        except (ValueError, TypeError):
            continue

    log.info(
        "Recurring scan: %d created, %d updated, %d deactivated",
        stats["created"], stats["updated"], stats["deactivated"],
    )

    # Auto-link recurring payments to loan/liability accounts (P3-T02)
    try:
        link_stats = link_recurring_to_loans(conn)
        log.info(
            "Loan linking: %d linked, %d already linked, %d unlinked",
            link_stats["linked"], link_stats["already_linked"], link_stats["unlinked"],
        )
    except Exception as e:
        log.warning("Loan linking failed (non-fatal): %s", e)

    return stats


# ── Query Functions ──────────────────────────────────────────────────────────


def get_recurring(
    conn: sqlite3.Connection,
    status: str = "active",
    account_id: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> list[dict]:
    """List recurring transactions, optionally filtered."""
    clauses = ["status = ?"]
    params: list = [status]

    if account_id:
        clauses.append("account_id = ?")
        params.append(account_id)
    elif owner_id:
        from dal.owners import build_account_filter
        acct_sql, acct_params = build_account_filter(conn, owner_id, None)
        if acct_sql:
            # Helper prepends " AND "; this function uses a clauses list.
            clauses.append(acct_sql.lstrip()[4:])
            params.extend(acct_params)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT * FROM recurring_transactions WHERE {where} "
        f"ORDER BY frequency, merchant",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_mutations(
    conn: sqlite3.Connection, recurring_id: str
) -> list[dict]:
    """Get price change history for a recurring transaction."""
    rows = conn.execute(
        "SELECT * FROM recurring_mutations WHERE recurring_id = ? "
        "ORDER BY detected_at DESC",
        (recurring_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def dismiss_recurring(conn: sqlite3.Connection, recurring_id: str) -> None:
    """Mark a recurring item as dismissed (user hides it)."""
    conn.execute(
        "UPDATE recurring_transactions SET status = 'dismissed', "
        "updated_at = datetime('now') WHERE id = ?",
        (recurring_id,),
    )


def reactivate_recurring(conn: sqlite3.Connection, recurring_id: str) -> None:
    """Re-enable a dismissed or inactive recurring item."""
    conn.execute(
        "UPDATE recurring_transactions SET status = 'active', "
        "updated_at = datetime('now') WHERE id = ?",
        (recurring_id,),
    )


def get_monthly_recurring_total(
    conn: sqlite3.Connection,
    account_id: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> dict:
    """Sum of active recurring by category for budget baseline.

    Returns:
        {"total": float, "by_category": {category: amount}}
    """
    clauses = ["status = 'active'", "amount_stable = 1"]
    params: list = []

    if account_id:
        clauses.append("account_id = ?")
        params.append(account_id)
    elif owner_id:
        from dal.owners import build_account_filter
        acct_sql, acct_params = build_account_filter(conn, owner_id, None)
        if acct_sql:
            clauses.append(acct_sql.lstrip()[4:])
            params.extend(acct_params)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT category, frequency, expected_amount "
        f"FROM recurring_transactions WHERE {where}",
        params,
    ).fetchall()

    # Normalize all amounts to monthly
    MONTHLY_FACTORS = {
        "weekly": 4.33,
        "biweekly": 2.17,
        "monthly": 1.0,
        "bimonthly": 0.5,
        "quarterly": 0.333,
        "semiannual": 0.167,
        "annual": 0.083,
    }

    by_category: dict[str, float] = defaultdict(float)
    total = 0.0

    for r in rows:
        if r["expected_amount"] is None:
            continue
        factor = MONTHLY_FACTORS.get(r["frequency"], 1.0)
        monthly = r["expected_amount"] * factor
        by_category[r["category"] or "Uncategorized"] += monthly
        total += monthly

    return {
        "total": round(total, 2),
        "by_category": {k: round(v, 2) for k, v in sorted(by_category.items())},
    }


# ── Loan Linking ─────────────────────────────────────────────────────────────


from dal.category_classifications import LOAN_CATEGORIES as _LOAN_CATEGORIES


def link_recurring_to_loans(conn: sqlite3.Connection) -> dict:
    """
    Auto-link recurring payments to their source loan/liability accounts.

    Uses a matching heuristic (precedence order):
      1. Same institution + category match
      2. Cross-institution category + amount match
      3. Manual override preservation (never overwrite existing links)

    Returns:
        {"linked": int, "already_linked": int, "unlinked": int}
    """
    stats = {"linked": 0, "already_linked": 0, "unlinked": 0}

    # Get all active recurring items with loan-related categories
    recurring_items = conn.execute("""
        SELECT r.id, r.account_id, r.merchant, r.category,
               r.expected_amount, r.linked_account_id
        FROM recurring_transactions r
        WHERE r.status = 'active'
          AND r.expected_amount IS NOT NULL
    """).fetchall()

    # Get all liability accounts with their institutions and balances
    liability_accounts = conn.execute("""
        SELECT a.id, a.name, a.type, a.institution_id,
               ABS(bs.balance) as balance
        FROM accounts a
        JOIN balance_snapshots bs ON bs.account_id = a.id
        WHERE a.type IN ('credit_card', 'loan', 'bnpl')
          AND a.is_active = 1
          AND bs.id = (
              SELECT id FROM balance_snapshots b2
              WHERE b2.account_id = a.id
              ORDER BY b2.as_of DESC LIMIT 1
          )
    """).fetchall()

    # Get institution_id for each account_id
    account_institutions: dict[str, str] = {}
    acct_rows = conn.execute(
        "SELECT id, institution_id FROM accounts"
    ).fetchall()
    for a in acct_rows:
        account_institutions[a["id"]] = a["institution_id"]

    # Get monthly payment from loan_details if available
    loan_payments: dict[str, Optional[float]] = {}
    for la in liability_accounts:
        row = conn.execute("""
            SELECT field_value FROM loan_details
            WHERE account_id = ? AND LOWER(field_name) IN ('monthly_payment', 'payment_amount', 'minimum payment')
            ORDER BY as_of DESC LIMIT 1
        """, (la["id"],)).fetchone()
        if row and row["field_value"]:
            try:
                val = float(str(row["field_value"]).replace("$", "").replace(",", "").strip())
                loan_payments[la["id"]] = val
            except (ValueError, TypeError):
                loan_payments[la["id"]] = None
        else:
            loan_payments[la["id"]] = None

    for rec in recurring_items:
        cat = rec["category"] or ""

        # Skip if already linked (manual override preservation)
        if rec["linked_account_id"]:
            stats["already_linked"] += 1
            continue

        # Only attempt linking for loan-related categories
        if cat not in _LOAN_CATEGORIES:
            stats["unlinked"] += 1
            continue

        rec_institution = account_institutions.get(rec["account_id"])
        rec_amount = rec["expected_amount"] or 0
        matched_account_id = None

        # ── Strategy 1: Same institution + category ──────────────────
        for la in liability_accounts:
            if la["institution_id"] == rec_institution:
                # Match type to category
                if _category_matches_type(cat, la["type"]):
                    matched_account_id = la["id"]
                    break

        # ── Strategy 2: Cross-institution category + amount ──────────
        if not matched_account_id:
            for la in liability_accounts:
                if not _category_matches_type(cat, la["type"]):
                    continue
                # Check amount proximity
                known_payment = loan_payments.get(la["id"])
                if known_payment and known_payment > 0:
                    if abs(rec_amount - known_payment) / known_payment <= 0.2:
                        matched_account_id = la["id"]
                        break
                else:
                    # Derive estimated payment from balance/rate
                    # For a rough match, just check if amount is reasonable
                    # relative to balance (monthly payment typically 1-5% of balance)
                    balance = la["balance"] or 0
                    if balance > 0:
                        pct = rec_amount / balance
                        if 0.005 <= pct <= 0.15:
                            matched_account_id = la["id"]
                            break

        if matched_account_id:
            conn.execute(
                "UPDATE recurring_transactions SET linked_account_id = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (matched_account_id, rec["id"]),
            )
            stats["linked"] += 1
            log.info(
                "Linked recurring '%s' → account '%s'",
                rec["merchant"], matched_account_id,
            )
        else:
            stats["unlinked"] += 1

    log.info(
        "Recurring loan linking: %d linked, %d already linked, %d unlinked",
        stats["linked"], stats["already_linked"], stats["unlinked"],
    )
    return stats


def _category_matches_type(category: str, account_type: str) -> bool:
    """Check if a recurring category matches a liability account type."""
    mapping = {
        "Mortgage": {"loan"},
        "Auto Loan": {"loan"},
        "Student Loan": {"loan"},
        "Loan Payment": {"loan", "bnpl"},
        "Credit Card Payments": {"credit_card"},
    }
    allowed_types = mapping.get(category, set())
    return account_type in allowed_types


def get_recurring_with_payoff(conn: sqlite3.Connection, owner_id: Optional[str] = None) -> list[dict]:
    """
    Return active recurring transactions enriched with payoff dates.

    For linked recurring items:
      - If the linked account has a maturity_date in loan_details,
        include it as "ends_at" in the result
      - Include the linked account's current balance and APR

    Returns list of dicts, each with recurring fields plus:
        linked_account_name, linked_balance, linked_apr,
        ends_at, months_remaining, total_remaining
    """
    
    from dal.owners import build_account_filter
    acct_filter, acct_params = build_account_filter(
        conn, owner_id, None, column="r.account_id"
    )
    params = list(acct_params)

    rows = conn.execute(f"""
        SELECT r.*,
               a.name as linked_account_name,
               ABS(bs.balance) as linked_balance
        FROM recurring_transactions r
        LEFT JOIN accounts a ON a.id = r.linked_account_id
        LEFT JOIN balance_snapshots bs ON bs.account_id = r.linked_account_id
            AND bs.id = (
                SELECT id FROM balance_snapshots b2
                WHERE b2.account_id = r.linked_account_id
                ORDER BY b2.as_of DESC LIMIT 1
            )
        WHERE r.status = 'active'
        {acct_filter}
        ORDER BY r.frequency, r.merchant
    """, params).fetchall()

    now = datetime.now(timezone.utc)
    result = []
    for r in rows:
        item = dict(r)
        linked_id = r["linked_account_id"]

        item["linked_account_name"] = r["linked_account_name"] if linked_id else None
        item["linked_balance"] = round(r["linked_balance"] or 0, 2) if linked_id else None
        item["linked_apr"] = None
        item["ends_at"] = None
        item["months_remaining"] = None
        item["total_remaining"] = None

        if linked_id:
            # Get APR
            from dal.debt import _get_loan_apr
            apr = _get_loan_apr(conn, linked_id)
            item["linked_apr"] = apr

            # Get maturity date
            mat_row = conn.execute("""
                SELECT field_value FROM loan_details
                WHERE account_id = ? AND LOWER(field_name) = 'maturity_date'
                ORDER BY as_of DESC LIMIT 1
            """, (linked_id,)).fetchone()

            if mat_row and mat_row["field_value"]:
                raw = mat_row["field_value"].strip()
                # Normalize date format
                ends_at = None
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m"):
                    try:
                        dt = datetime.strptime(raw, fmt)
                        ends_at = dt.strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue

                if ends_at:
                    item["ends_at"] = ends_at
                    mat_dt = datetime.strptime(ends_at, "%Y-%m-%d")
                    months_rem = max(0, (mat_dt.year - now.year) * 12 + (mat_dt.month - now.month))
                    item["months_remaining"] = months_rem

                    # Estimated total remaining payments
                    monthly_amount = r["expected_amount"] or 0
                    factor = {
                        "weekly": 4.33, "biweekly": 2.17, "monthly": 1.0,
                        "bimonthly": 0.5, "quarterly": 0.333,
                        "semiannual": 0.167, "annual": 0.083,
                    }.get(r["frequency"], 1.0)
                    monthly_payment = monthly_amount * factor
                    item["total_remaining"] = round(monthly_payment * months_rem, 2)

        result.append(item)

    return result

