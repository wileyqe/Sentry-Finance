"""
dal/goals.py — Savings goal management.

Savings goals let you track progress toward a named financial target
(emergency fund, vacation, down payment, etc.) with an optional deadline
and linked savings account.

Schema: `savings_goals` table (V10)

Goal lifecycle:
  created → active → (completed | cancelled)

Progress tracking:
  - If a `linked_account_id` is set, `current_amount` is auto-synced from the
    latest balance snapshot for that account whenever the goal is queried.
  - Without a linked account, `current_amount` is updated manually via
    `update_goal_amount()`.

On-track logic:
  - If no deadline: status is simply the completion percentage.
  - If deadline set: compute the daily savings rate needed and compare against
    the net monthly savings rate from `derived_summaries`. If the user is
    saving fast enough, they are "on_track"; otherwise "behind".
"""

import logging
import sqlite3
from datetime import datetime, date
from typing import Optional

log = logging.getLogger("sentry.dal.goals")


# ── CRUD ──────────────────────────────────────────────────────────────────────


def create_goal(
    conn: sqlite3.Connection,
    name: str,
    target_amount: float,
    owner_id: Optional[str] = None,
    current_amount: float = 0.0,
    deadline: Optional[str] = None,
    linked_account_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> int:
    """Create a new savings goal. Returns the new goal ID."""
    cursor = conn.execute(
        """
        INSERT INTO savings_goals
            (name, target_amount, current_amount, deadline,
             linked_account_id, owner_id, notes, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (name, target_amount, current_amount, deadline,
         linked_account_id, owner_id, notes),
    )
    goal_id = cursor.lastrowid
    log.info("Created savings goal '%s' (id=%d) target=$%.2f", name, goal_id, target_amount)
    return goal_id


def get_goal(conn: sqlite3.Connection, goal_id: int) -> Optional[dict]:
    """Retrieve a single goal by ID with computed progress fields."""
    row = conn.execute(
        "SELECT * FROM savings_goals WHERE id = ?", (goal_id,)
    ).fetchone()
    if not row:
        return None
    return _enrich_goal(conn, dict(row))


def list_goals(
    conn: sqlite3.Connection,
    owner_id: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict]:
    """List goals, optionally filtered by owner and/or status."""
    clauses = []
    params: list = []

    if owner_id is not None:
        clauses.append("owner_id = ?")
        params.append(owner_id)
    if status:
        clauses.append("status = ?")
        params.append(status)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM savings_goals {where} ORDER BY created_at DESC",
        params,
    ).fetchall()

    return [_enrich_goal(conn, dict(r)) for r in rows]


def update_goal_amount(
    conn: sqlite3.Connection,
    goal_id: int,
    new_amount: float,
    auto_complete: bool = True,
) -> dict:
    """
    Manually set the current_amount for a goal.

    If auto_complete=True and new_amount >= target_amount, marks the goal
    'completed' automatically.
    """
    goal = conn.execute(
        "SELECT target_amount, status FROM savings_goals WHERE id = ?",
        (goal_id,),
    ).fetchone()
    if not goal:
        raise ValueError(f"Goal {goal_id} not found")

    new_status = goal["status"]
    if auto_complete and new_amount >= goal["target_amount"] and goal["status"] == "active":
        new_status = "completed"
        log.info("Goal %d marked completed (%.2f >= target %.2f)", goal_id, new_amount, goal["target_amount"])

    conn.execute(
        """
        UPDATE savings_goals
        SET current_amount = ?, status = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (new_amount, new_status, goal_id),
    )
    return get_goal(conn, goal_id)


def update_goal(
    conn: sqlite3.Connection,
    goal_id: int,
    **kwargs,
) -> dict:
    """
    Update goal fields. Accepted kwargs:
    name, target_amount, deadline, notes, status, linked_account_id
    """
    allowed = {"name", "target_amount", "deadline", "notes", "status", "linked_account_id", "owner_id"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_goal(conn, goal_id)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [goal_id]
    conn.execute(
        f"UPDATE savings_goals SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
        params,
    )
    return get_goal(conn, goal_id)


def delete_goal(conn: sqlite3.Connection, goal_id: int) -> None:
    """Soft-delete a goal by marking it cancelled."""
    conn.execute(
        "UPDATE savings_goals SET status = 'cancelled', updated_at = datetime('now') WHERE id = ?",
        (goal_id,),
    )


# ── Auto-sync from linked account ─────────────────────────────────────────────


def sync_goal_balances(conn: sqlite3.Connection) -> int:
    """
    For all active goals with a linked_account_id, update current_amount
    from the latest balance_snapshots record for that account.

    Returns the number of goals updated.
    """
    goals = conn.execute(
        """
        SELECT id, linked_account_id, target_amount
        FROM savings_goals
        WHERE status = 'active' AND linked_account_id IS NOT NULL
        """
    ).fetchall()

    updated = 0
    for g in goals:
        snap = conn.execute(
            """
            SELECT balance FROM balance_snapshots
            WHERE account_id = ?
            ORDER BY as_of DESC LIMIT 1
            """,
            (g["linked_account_id"],),
        ).fetchone()

        if snap is None:
            continue

        balance = max(0.0, snap["balance"] or 0.0)
        new_status = "active"
        if balance >= g["target_amount"]:
            new_status = "completed"
            log.info(
                "Goal %d auto-completed: linked account balance $%.2f >= target $%.2f",
                g["id"], balance, g["target_amount"],
            )

        conn.execute(
            """
            UPDATE savings_goals
            SET current_amount = ?, status = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (balance, new_status, g["id"]),
        )
        updated += 1

    return updated


# ── Progress Enrichment ──────────────────────────────────────────────────────


def _enrich_goal(conn: sqlite3.Connection, goal: dict) -> dict:
    """Add computed progress fields to a goal dict."""
    target = goal.get("target_amount") or 0
    current = goal.get("current_amount") or 0
    remaining = max(0.0, target - current)
    pct_complete = round(current / target * 100, 1) if target > 0 else 0

    goal["remaining"] = round(remaining, 2)
    goal["pct_complete"] = pct_complete

    deadline = goal.get("deadline")
    if deadline and goal.get("status") == "active":
        try:
            deadline_dt = datetime.strptime(deadline, "%Y-%m-%d").date()
            today = date.today()
            days_left = (deadline_dt - today).days

            if days_left <= 0:
                goal["days_remaining"] = 0
                goal["monthly_savings_needed"] = None
                goal["trajectory"] = "overdue"
            else:
                months_left = max(days_left / 30.44, 0.1)
                monthly_needed = round(remaining / months_left, 2) if remaining > 0 else 0

                # Get actual avg monthly net from derived_summaries
                avg_net = _get_avg_monthly_net(conn)

                goal["days_remaining"] = days_left
                goal["monthly_savings_needed"] = monthly_needed
                goal["trajectory"] = (
                    "on_track"
                    if avg_net >= monthly_needed
                    else "behind"
                )
                goal["avg_monthly_net"] = round(avg_net, 2)
        except (ValueError, TypeError):
            goal["days_remaining"] = None
            goal["monthly_savings_needed"] = None
            goal["trajectory"] = "unknown"
    else:
        goal["days_remaining"] = None
        goal["monthly_savings_needed"] = None
        goal["trajectory"] = "no_deadline" if goal.get("status") == "active" else goal.get("status", "unknown")

    return goal


def _get_avg_monthly_net(conn: sqlite3.Connection, months: int = 3) -> float:
    """Estimate average monthly net savings over the last N months."""
    rows = conn.execute(
        f"""
        SELECT
            SUM(CASE WHEN direction = 'Credit' AND transfer_tag IS NULL THEN signed_amount ELSE 0 END) as income,
            SUM(CASE WHEN direction = 'Debit' AND transfer_tag IS NULL THEN amount ELSE 0 END) as spending
        FROM transactions
        WHERE status = 'posted'
          AND posting_date >= date('now', '-{months} months')
          AND COALESCE(category, 'Uncategorized') NOT IN ('Transfers', 'Credit Card Payments')
        """
    ).fetchone()

    if not rows:
        return 0.0

    income = rows["income"] or 0
    spending = rows["spending"] or 0
    net = max(0.0, income - spending)
    return round(net / months, 2)


# ── Summary ────────────────────────────────────────────────────────────────────


def get_goals_summary(conn: sqlite3.Connection, owner_id: Optional[str] = None) -> dict:
    """
    Dashboard summary of all goals.

    Returns:
      {
        total_goals, active_goals, completed_goals,
        total_target, total_saved, overall_pct,
        goals_on_track, goals_behind, goals_no_deadline
      }
    """
    goals = list_goals(conn, owner_id=owner_id)
    active = [g for g in goals if g["status"] == "active"]
    completed = [g for g in goals if g["status"] == "completed"]

    total_target = sum(g["target_amount"] for g in active)
    total_saved = sum(g["current_amount"] or 0 for g in active)

    on_track = sum(1 for g in active if g.get("trajectory") == "on_track")
    behind = sum(1 for g in active if g.get("trajectory") == "behind")
    no_deadline = sum(1 for g in active if g.get("trajectory") == "no_deadline")

    return {
        "total_goals": len(goals),
        "active_goals": len(active),
        "completed_goals": len(completed),
        "total_target": round(total_target, 2),
        "total_saved": round(total_saved, 2),
        "overall_pct": round(total_saved / total_target * 100, 1) if total_target > 0 else 0,
        "goals_on_track": on_track,
        "goals_behind": behind,
        "goals_no_deadline": no_deadline,
    }
