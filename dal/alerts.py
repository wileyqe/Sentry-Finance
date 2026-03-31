"""
dal/alerts.py — Spending alert evaluation engine.

Evaluates configurable alert rules against live data after each refresh
and emits structured alert events.

Three built-in rule types:
  - budget_pct   : fires when category spending >= threshold% of monthly budget
  - large_txn    : fires when a single transaction amount >= threshold dollars
  - balance_low  : fires when an account balance drops below threshold dollars

Alert rules are stored in the `alert_rules` table (Schema V9).
Alerts fired are recorded in `alert_events` for deduplication within the
same calendar month (budget_pct) or 24-hour window (large_txn, balance_low).

Usage (called from automation_worker after a refresh):
    from dal.alerts import evaluate_alerts
    with get_db() as conn:
        fired = evaluate_alerts(conn, institution_id="chase")
    for alert in fired:
        broadcast_event("alert", alert)
"""

import hashlib
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("sentry.dal.alerts")


# ── Default Rule Definitions ─────────────────────────────────────────────────
# These are seeded on init if the alert_rules table is empty.

DEFAULT_RULES = [
    {
        "id": "budget_pct_warning",
        "rule_type": "budget_pct",
        "scope": "all_categories",
        "threshold": 80.0,
        "label": "Budget 80% warning",
        "enabled": 1,
    },
    {
        "id": "budget_pct_over",
        "rule_type": "budget_pct",
        "scope": "all_categories",
        "threshold": 100.0,
        "label": "Budget exceeded",
        "enabled": 1,
    },
    {
        "id": "large_txn_500",
        "rule_type": "large_txn",
        "scope": "all",
        "threshold": 500.0,
        "label": "Large transaction > $500",
        "enabled": 1,
    },
    {
        "id": "balance_low_500",
        "rule_type": "balance_low",
        "scope": "checking",
        "threshold": 500.0,
        "label": "Checking balance below $500",
        "enabled": 1,
    },
]


# ── Alert Seed ───────────────────────────────────────────────────────────────


def seed_default_rules(conn: sqlite3.Connection) -> int:
    """Insert default alert rules if the table is empty. Returns count seeded."""
    existing = conn.execute("SELECT COUNT(*) as n FROM alert_rules").fetchone()
    if existing and existing["n"] > 0:
        return 0

    for rule in DEFAULT_RULES:
        conn.execute(
            """
            INSERT OR IGNORE INTO alert_rules
                (id, rule_type, scope, threshold, label, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                rule["id"],
                rule["rule_type"],
                rule["scope"],
                rule["threshold"],
                rule["label"],
                rule["enabled"],
            ),
        )
    log.info("Seeded %d default alert rules", len(DEFAULT_RULES))
    return len(DEFAULT_RULES)


# ── Deduplication ─────────────────────────────────────────────────────────────


def _dedup_key(rule_id: str, context: str) -> str:
    """Hash a deduplication key for an alert event."""
    raw = f"{rule_id}:{context}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _already_fired(
    conn: sqlite3.Connection,
    rule_id: str,
    context: str,
    window_hours: int = 720,  # 30-day default (1 per month for budget alerts)
) -> bool:
    """Check if this rule+context combo fired within the dedup window."""
    dedup = _dedup_key(rule_id, context)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    row = conn.execute(
        "SELECT id FROM alert_events WHERE dedup_key = ? AND fired_at >= ?",
        (dedup, cutoff),
    ).fetchone()
    return row is not None


def _record_alert(
    conn: sqlite3.Connection,
    rule_id: str,
    context: str,
    payload: dict,
) -> None:
    """Record a fired alert event."""
    dedup = _dedup_key(rule_id, context)
    import json

    conn.execute(
        """
        INSERT OR IGNORE INTO alert_events (rule_id, context, payload, dedup_key)
        VALUES (?, ?, ?, ?)
        """,
        (rule_id, context, json.dumps(payload), dedup),
    )


# ── Rule Evaluators ───────────────────────────────────────────────────────────


def _eval_budget_pct(
    conn: sqlite3.Connection,
    rule: sqlite3.Row,
    month: str,
) -> list[dict]:
    """Fire when category spending crosses threshold% of its budget target."""
    from dal.budgets import get_budget_vs_actual

    fired = []
    categories = get_budget_vs_actual(conn, month)

    for cat in categories:
        if cat["target"] <= 0:
            continue
        pct = cat["pct_used"]
        if pct < rule["threshold"]:
            continue

        context = f"{month}:{cat['category']}"
        # Budget pct alerts dedup per calendar month (24h * 720 = 30 days)
        if _already_fired(conn, rule["id"], context, window_hours=672):
            continue

        alert = {
            "rule_id": rule["id"],
            "rule_type": "budget_pct",
            "label": rule["label"],
            "category": cat["category"],
            "month": month,
            "pct_used": pct,
            "actual": cat["actual"],
            "target": cat["target"],
            "threshold": rule["threshold"],
            "severity": "over" if pct >= 100 else "warning",
        }
        _record_alert(conn, rule["id"], context, alert)
        fired.append(alert)
        log.info(
            "Alert fired: %s — %s %.1f%% of budget ($%.2f / $%.2f)",
            rule["id"], cat["category"], pct, cat["actual"], cat["target"],
        )

    return fired


def _eval_large_txn(
    conn: sqlite3.Connection,
    rule: sqlite3.Row,
    institution_id: Optional[str] = None,
    hours_back: int = 25,
) -> list[dict]:
    """Fire when a single debit transaction exceeds the threshold amount."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()

    params: list = [rule["threshold"], cutoff]
    inst_filter = ""
    if institution_id:
        inst_filter = " AND institution_id = ?"
        params.append(institution_id)

    rows = conn.execute(
        f"""
        SELECT id, account_id, institution_id, posting_date,
               amount, description, category
        FROM transactions
        WHERE direction = 'Debit'
          AND amount >= ?
          AND created_at >= ?
          AND status = 'posted'
          AND transfer_tag IS NULL
          {inst_filter}
        ORDER BY amount DESC
        LIMIT 20
        """,
        params,
    ).fetchall()

    fired = []
    for txn in rows:
        context = txn["id"]
        if _already_fired(conn, rule["id"], context, window_hours=48):
            continue

        alert = {
            "rule_id": rule["id"],
            "rule_type": "large_txn",
            "label": rule["label"],
            "txn_id": txn["id"],
            "account_id": txn["account_id"],
            "institution_id": txn["institution_id"],
            "amount": txn["amount"],
            "description": txn["description"],
            "category": txn["category"],
            "posting_date": txn["posting_date"],
            "threshold": rule["threshold"],
            "severity": "info",
        }
        _record_alert(conn, rule["id"], context, alert)
        fired.append(alert)
        log.info(
            "Alert fired: %s — $%.2f at '%s'",
            rule["id"], txn["amount"], txn["description"],
        )

    return fired


def _eval_balance_low(
    conn: sqlite3.Connection,
    rule: sqlite3.Row,
) -> list[dict]:
    """Fire when a checking/savings balance drops below threshold."""
    scope = rule["scope"]  # "checking", "savings", or "all"

    # Build parameterized query — never interpolate scope directly into SQL
    params: list = [rule["threshold"]]
    type_filter = ""
    if scope in ("checking", "savings"):
        type_filter = " AND a.type = ?"
        params.append(scope)

    rows = conn.execute(
        f"""
        SELECT bs.account_id, bs.balance, a.name, a.type
        FROM balance_snapshots bs
        JOIN accounts a ON a.id = bs.account_id
        WHERE bs.id = (
            SELECT b2.id FROM balance_snapshots b2
            WHERE b2.account_id = bs.account_id
            ORDER BY b2.as_of DESC LIMIT 1
        )
          AND a.is_active = 1
          AND bs.balance < ?
          {type_filter}
        """,
        params,
    ).fetchall()

    fired = []
    for row in rows:
        context = f"{row['account_id']}:low"
        if _already_fired(conn, rule["id"], context, window_hours=24):
            continue

        alert = {
            "rule_id": rule["id"],
            "rule_type": "balance_low",
            "label": rule["label"],
            "account_id": row["account_id"],
            "account_name": row["name"],
            "account_type": row["type"],
            "balance": row["balance"],
            "threshold": rule["threshold"],
            "severity": "warning",
        }
        _record_alert(conn, rule["id"], context, alert)
        fired.append(alert)
        log.info(
            "Alert fired: %s — %s balance $%.2f below $%.2f",
            rule["id"], row["name"], row["balance"], rule["threshold"],
        )

    return fired


# ── Main Evaluator ────────────────────────────────────────────────────────────


def evaluate_alerts(
    conn: sqlite3.Connection,
    institution_id: Optional[str] = None,
) -> list[dict]:
    """
    Evaluate all enabled alert rules and return newly fired alerts.

    Call this after a successful refresh to surface actionable notifications.
    Fires are deduplicated to avoid alert spam.

    Args:
        conn: Active database connection.
        institution_id: Restrict large_txn checks to this institution if given.

    Returns:
        List of alert dicts that were newly fired (not previously seen).
    """
    try:
        rules = conn.execute(
            "SELECT * FROM alert_rules WHERE enabled = 1"
        ).fetchall()
    except sqlite3.OperationalError:
        # alert_rules table doesn't exist yet — schema not migrated
        log.debug("alert_rules table not found; skipping alert evaluation")
        return []

    fired_all: list[dict] = []
    month = datetime.now(timezone.utc).strftime("%Y-%m")

    for rule in rules:
        rtype = rule["rule_type"]
        try:
            if rtype == "budget_pct":
                fired_all.extend(_eval_budget_pct(conn, rule, month))
            elif rtype == "large_txn":
                fired_all.extend(_eval_large_txn(conn, rule, institution_id))
            elif rtype == "balance_low":
                fired_all.extend(_eval_balance_low(conn, rule))
            else:
                log.warning("Unknown alert rule type: %s", rtype)
        except Exception as e:
            log.error("Error evaluating rule %s: %s", rule["id"], e, exc_info=True)

    if fired_all:
        log.info("Alert evaluation complete: %d new alerts fired", len(fired_all))

    return fired_all


# ── CRUD ──────────────────────────────────────────────────────────────────────


def get_rules(conn: sqlite3.Connection) -> list[dict]:
    """Return all alert rules."""
    rows = conn.execute(
        "SELECT * FROM alert_rules ORDER BY rule_type, threshold"
    ).fetchall()
    return [dict(r) for r in rows]


def set_rule_enabled(
    conn: sqlite3.Connection, rule_id: str, enabled: bool
) -> None:
    """Enable or disable an alert rule."""
    conn.execute(
        "UPDATE alert_rules SET enabled = ?, updated_at = datetime('now') WHERE id = ?",
        (1 if enabled else 0, rule_id),
    )


def update_rule_threshold(
    conn: sqlite3.Connection, rule_id: str, threshold: float
) -> None:
    """Update the threshold value for an alert rule."""
    conn.execute(
        "UPDATE alert_rules SET threshold = ?, updated_at = datetime('now') WHERE id = ?",
        (threshold, rule_id),
    )


def get_recent_alerts(
    conn: sqlite3.Connection,
    limit: int = 50,
    rule_type: Optional[str] = None,
) -> list[dict]:
    """Return recently fired alert events."""
    import json

    params: list = []
    type_filter = ""
    if rule_type:
        type_filter = " AND ar.rule_type = ?"
        params.append(rule_type)

    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT ae.id, ae.rule_id, ar.rule_type, ar.label,
               ae.context, ae.payload, ae.fired_at
        FROM alert_events ae
        JOIN alert_rules ar ON ar.id = ae.rule_id
        WHERE 1=1 {type_filter}
        ORDER BY ae.fired_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    results = []
    for r in rows:
        item = dict(r)
        try:
            item["payload"] = json.loads(item["payload"])
        except (TypeError, ValueError):
            pass
        results.append(item)
    return results
