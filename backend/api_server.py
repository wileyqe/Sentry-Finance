"""
backend/api_server.py — FastAPI application serving the finance dashboard.

Endpoints:
  - /api/accounts           — list accounts with latest balances
  - /api/transactions       — query transactions (filtered)
  - /api/balances/{id}/history — balance time series
  - /api/loan-details/{id}  — latest loan snapshot
  - /api/refresh/status     — current refresh state
  - /api/refresh/start      — trigger sync
  - /api/refresh/history    — past runs
  - /api/refresh/events     — SSE stream
  - /api/metrics/summary    — derived metrics
  - /api/staleness          — check what's stale

Design:
  - Binds to 127.0.0.1 only (local-first)
  - SQLite with WAL mode for concurrent reads
  - SSE for real-time refresh progress
"""

import asyncio
import json
import logging
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

# Ensure project root is on sys.path when running as script
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from dal.database import init_db, get_db, seed_institutions
from dal.transactions import get_transactions
from dal.balances import (
    get_all_latest_balances,
    get_balance_history,
    get_latest_loan_details,
)
from dal.refresh_log import (
    get_institution_statuses,
    get_refresh_history,
    get_current_run,
    get_run_events,
)
from dal.derived import get_summary_metrics
from dal.categorization import (
    list_categories as dal_list_categories,
    set_user_override,
    delete_user_override,
    backfill_uncategorized,
)
from dal.owners import (
    list_owners as dal_list_owners,
    create_owner,
    assign_account_owner,
    resolve_account_ids_for_view,
)
from dal.recurring import (
    detect_recurring,
    get_recurring as dal_get_recurring,
    get_mutations,
    dismiss_recurring,
    reactivate_recurring,
    get_monthly_recurring_total,
)
from dal.budgets import (
    get_budget_vs_actual,
    get_budget_summary,
    set_budget_target,
    initialize_month as budget_initialize_month,
    delete_budget,
    suggest_budget_targets,
)
from dal.bills import (
    get_upcoming_bills,
    get_overdue_bills,
    get_bills_summary,
)
from dal.forecasting import get_cash_flow_forecast
from dal.alerts import (
    evaluate_alerts,
    seed_default_rules,
    get_rules as dal_get_alert_rules,
    get_recent_alerts,
    set_rule_enabled,
    update_rule_threshold,
)
from dal.reports import (
    get_spending_by_category,
    get_cash_flow_report,
    get_net_worth_history,
    get_category_trend,
    export_transactions_csv,
    get_period_summary,
)
from dal.goals import (
    create_goal,
    get_goal,
    list_goals,
    update_goal_amount,
    delete_goal,
    sync_goal_balances,
    get_goals_summary,
)
from dal.performance import (
    get_portfolio_performance,
    get_all_accounts_performance,
)
from dal.allocation import get_allocation
from dal.debt import get_debt_summary, get_payoff_plan
from backend.refresh_orchestrator import (
    check_staleness,
    run_refresh,
    RefreshSession,
)
from backend.automation_worker import run_institution

log = logging.getLogger("sentry.backend.api")

# ── SSE Event Bus ────────────────────────────────────────────────────────────

_sse_subscribers: list[asyncio.Queue] = []
_sse_lock = threading.Lock()


def _broadcast_event(event_type: str, data: dict):
    """Broadcast an event to all SSE subscribers."""
    msg = {"type": event_type, "data": data, "timestamp": datetime.utcnow().isoformat()}
    with _sse_lock:
        for q in _sse_subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # Drop if subscriber is slow


# ── App Setup ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup."""
    init_db()
    seed_institutions()
    with get_db() as conn:
        seed_default_rules(conn)
    log.info("API server ready — database initialized")
    yield


app = FastAPI(
    title="Sentry Finance API",
    version="1.0.0",
    description="Local-first personal finance dashboard backend",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Account & Balance Endpoints ──────────────────────────────────────────────


@app.get("/api/accounts")
def list_accounts(view: str = Query("ours")):
    """List all accounts with their latest balances.

    Query params:
        view: "ours" (all), "mine" (my accounts), "theirs" (partner's)
    """
    with get_db() as conn:
        balances = get_all_latest_balances(conn)
        # Get account filter for view
        view_account_ids = resolve_account_ids_for_view(conn, view)

        if view_account_ids is not None:
            all_accounts = conn.execute(
                "SELECT id, institution_id, name, last4, type, owner_id "
                "FROM accounts WHERE is_active = 1 AND id IN ({})".format(
                    ",".join("?" for _ in view_account_ids)
                ),
                list(view_account_ids),
            ).fetchall()
        else:
            all_accounts = conn.execute(
                "SELECT id, institution_id, name, last4, type, owner_id "
                "FROM accounts WHERE is_active = 1"
            ).fetchall()
        all_accounts = [dict(r) for r in all_accounts]

    # Merge balances into accounts
    bal_map = {b["account_id"]: b for b in balances}
    for acct in all_accounts:
        bal = bal_map.get(acct["id"])
        acct["balance"] = bal["balance"] if bal else None
        acct["balance_as_of"] = bal["as_of"] if bal else None

    return {"accounts": all_accounts, "view": view}


@app.get("/api/balances/{account_id}/history")
def balance_history(
    account_id: str,
    start_date: str = Query(None),
    end_date: str = Query(None),
    limit: int = Query(365, le=1000),
):
    """Get balance history for an account."""
    with get_db() as conn:
        history = get_balance_history(conn, account_id, start_date, end_date, limit)
    return {"account_id": account_id, "history": history}


@app.get("/api/loan-details/{account_id}")
def loan_details(account_id: str):
    """Get latest loan details for an account."""
    with get_db() as conn:
        details = get_latest_loan_details(conn, account_id)
    return {"account_id": account_id, "details": details}


# ── Transaction Endpoints ────────────────────────────────────────────────────


@app.get("/api/transactions")
def list_transactions(
    account_id: str = Query(None),
    institution_id: str = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    status: str = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    view: str = Query("ours"),
):
    """Query transactions with optional filters."""
    with get_db() as conn:
        # Apply view filter: if a specific view is set and no explicit
        # account_id was requested, restrict to matching accounts
        effective_account_id = account_id
        if not account_id and view != "ours":
            view_ids = resolve_account_ids_for_view(conn, view)
            if view_ids is not None and len(view_ids) > 0:
                # Use the first matching account or pass all as filter
                # For now, fetch transactions for all matching accounts
                all_txns = []
                for vid in view_ids:
                    txns = get_transactions(
                        conn, vid, institution_id, start_date,
                        end_date, status, limit, offset,
                    )
                    all_txns.extend(txns)
                return {"transactions": all_txns[:limit], "count": min(len(all_txns), limit), "view": view}

        txns = get_transactions(
            conn,
            effective_account_id,
            institution_id,
            start_date,
            end_date,
            status,
            limit,
            offset,
        )
    return {"transactions": txns, "count": len(txns), "view": view}


# ── Refresh Endpoints ────────────────────────────────────────────────────────


@app.get("/api/staleness")
def staleness_check():
    """Check which institutions are stale."""
    return {"institutions": check_staleness()}


@app.get("/api/refresh/status")
def refresh_status():
    """Get current refresh state and per-institution progress."""
    with get_db() as conn:
        current = get_current_run(conn)
        statuses = get_institution_statuses(conn)
        events = []
        if current:
            events = get_run_events(conn, current["id"])

    return {
        "current_run": current,
        "institution_statuses": statuses,
        "events": events,
    }


_refresh_lock = threading.Lock()


@app.post("/api/refresh/start")
def start_refresh(trigger: str = "manual_sync"):
    """Trigger a new refresh session.

    Runs asynchronously in a background thread so the API
    remains responsive. Prevents concurrent executions.
    """
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="A refresh session is already in progress."
        )

    def _run_in_thread():
        try:
            session = RefreshSession(trigger=trigger)
            session.on_event(_broadcast_event)
            result = session.run(worker_fn=run_institution)
            _broadcast_event("refresh_complete", result)
        finally:
            _refresh_lock.release()

    thread = threading.Thread(target=_run_in_thread, daemon=True)
    thread.start()

    return {"status": "started", "trigger": trigger}


@app.get("/api/refresh/history")
def refresh_history(limit: int = Query(20, le=100)):
    """Get past refresh runs with summary stats."""
    with get_db() as conn:
        history = get_refresh_history(conn, limit)
    return {"runs": history}


# ── SSE Stream ───────────────────────────────────────────────────────────────


@app.get("/api/refresh/events")
async def refresh_event_stream():
    """Server-Sent Events stream for real-time refresh progress.

    Connect from frontend:
        const es = new EventSource('/api/refresh/events');
        es.onmessage = (e) => console.log(JSON.parse(e.data));
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    with _sse_lock:
        _sse_subscribers.append(queue)

    async def event_generator():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield (f"event: {msg['type']}\ndata: {json.dumps(msg)}\n\n")
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
        finally:
            with _sse_lock:
                _sse_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ── Metrics Endpoint ─────────────────────────────────────────────────────────


@app.get("/api/metrics/summary")
def metrics_summary(view: str = Query("ours")):
    """Get derived summary metrics, optionally scoped to a view."""
    with get_db() as conn:
        metrics = get_summary_metrics(conn)
    return {"metrics": metrics, "view": view}


# ── Owner Endpoints ──────────────────────────────────────────────────────────

# ── Categorization Endpoints ───────────────────────────────────────────────


@app.get("/api/categories")
def categories_list():
    """List all categories in use with transaction counts."""
    with get_db() as conn:
        cats = dal_list_categories(conn)
    return {"categories": cats}


@app.patch("/api/transactions/{txn_id}/category")
def transaction_set_category(txn_id: str, category: str = Query(...)):
    """Set a user override for a transaction's category."""
    with get_db() as conn:
        txn = conn.execute(
            "SELECT id FROM transactions WHERE id = ?", (txn_id,)
        ).fetchone()
        if not txn:
            raise HTTPException(status_code=404, detail=f"Transaction {txn_id} not found")
        set_user_override(conn, txn_id, category)
        conn.commit()
    return {"status": "updated", "txn_id": txn_id, "category": category}


@app.delete("/api/transactions/{txn_id}/category")
def transaction_clear_category(txn_id: str):
    """Remove a user override, reverting to rule-based categorization."""
    with get_db() as conn:
        delete_user_override(conn, txn_id)
        conn.commit()
    return {"status": "deleted", "txn_id": txn_id}


@app.post("/api/categorize/backfill")
def categorize_backfill():
    """Trigger backfill of all uncategorized transactions."""
    with get_db() as conn:
        stats = backfill_uncategorized(conn)
    return {"status": "complete", **stats}

# ── Recurring Transaction Endpoints ──────────────────────────────────────────


@app.get("/api/recurring")
def recurring_list(
    status: str = Query("active"),
    account_id: Optional[str] = Query(None),
):
    """List recurring transactions."""
    with get_db() as conn:
        items = dal_get_recurring(conn, status=status, account_id=account_id)
    return {"recurring": items, "count": len(items)}


@app.get("/api/recurring/{recurring_id}/mutations")
def recurring_mutations(recurring_id: str):
    """Get price change history for a recurring transaction."""
    with get_db() as conn:
        mutations = get_mutations(conn, recurring_id)
    return {"mutations": mutations}


@app.post("/api/recurring/scan")
def recurring_scan():
    """Trigger a full recurring transaction scan."""
    with get_db() as conn:
        stats = detect_recurring(conn)
    return {"status": "complete", **stats}


@app.patch("/api/recurring/{recurring_id}")
def recurring_update(recurring_id: str, action: str = Query(...)):
    """Dismiss or reactivate a recurring transaction.

    action: 'dismiss' or 'reactivate'
    """
    with get_db() as conn:
        if action == "dismiss":
            dismiss_recurring(conn, recurring_id)
        elif action == "reactivate":
            reactivate_recurring(conn, recurring_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
        conn.commit()
    return {"status": "updated", "recurring_id": recurring_id, "action": action}


@app.get("/api/recurring/summary")
def recurring_summary(account_id: Optional[str] = Query(None)):
    """Monthly recurring totals by category for budget baseline."""
    with get_db() as conn:
        totals = get_monthly_recurring_total(conn, account_id=account_id)
    return totals

# ── Budget Endpoints ─────────────────────────────────────────────────────────


@app.get("/api/budgets")
def budgets_vs_actual(
    month: str = Query(..., description="YYYY-MM"),
    owner_id: Optional[str] = Query(None),
):
    """Budget vs. actual spending for a month."""
    with get_db() as conn:
        details = get_budget_vs_actual(conn, month, owner_id=owner_id)
    return {"month": month, "categories": details}


@app.get("/api/budgets/summary")
def budgets_summary(
    month: str = Query(..., description="YYYY-MM"),
    owner_id: Optional[str] = Query(None),
):
    """High-level budget summary for a month."""
    with get_db() as conn:
        summary = get_budget_summary(conn, month, owner_id=owner_id)
    return summary


@app.put("/api/budgets/{category}")
def budgets_set_target(
    category: str,
    month: str = Query(..., description="YYYY-MM"),
    target: float = Query(...),
    owner_id: Optional[str] = Query(None),
):
    """Set or update a budget target for a category/month."""
    with get_db() as conn:
        set_budget_target(conn, category, month, target, owner_id=owner_id)
        conn.commit()
    return {"status": "updated", "category": category, "month": month, "target": target}


@app.post("/api/budgets/initialize")
def budgets_init_month(
    month: str = Query(..., description="YYYY-MM"),
    owner_id: Optional[str] = Query(None),
):
    """Initialize budget entries for a month from defaults."""
    with get_db() as conn:
        created = budget_initialize_month(conn, month, owner_id=owner_id)
        conn.commit()
    return {"status": "initialized", "month": month, "created": created}


@app.delete("/api/budgets/{category}")
def budgets_delete(
    category: str,
    month: str = Query(..., description="YYYY-MM"),
    owner_id: Optional[str] = Query(None),
):
    """Delete a budget entry."""
    with get_db() as conn:
        delete_budget(conn, category, month, owner_id=owner_id)
        conn.commit()
    return {"status": "deleted", "category": category, "month": month}


@app.get("/api/budgets/suggest")
def budgets_suggest(
    months_back: int = Query(3),
):
    """Suggest budget targets based on historical spending.

    Returns per-category suggestions with:
      avg_monthly, suggested_target (rounded to $25 with 10% buffer),
      recurring_baseline, has_recurring, months_with_data
    """
    with get_db() as conn:
        suggestions = suggest_budget_targets(conn, months_back=months_back)
    return {"suggestions": suggestions, "months_analyzed": months_back}


# ── Bill Tracking Endpoints ─────────────────────────────────────────────


@app.get("/api/bills/upcoming")
def bills_upcoming(
    days: int = Query(30),
    account_id: Optional[str] = Query(None),
):
    """List upcoming bills within the next N days."""
    with get_db() as conn:
        bills = get_upcoming_bills(conn, days=days, account_id=account_id)
    return {"bills": bills, "count": len(bills)}


@app.get("/api/bills/overdue")
def bills_overdue(
    account_id: Optional[str] = Query(None),
):
    """List all overdue bills."""
    with get_db() as conn:
        bills = get_overdue_bills(conn, account_id=account_id)
    return {"bills": bills, "count": len(bills)}


@app.get("/api/bills/summary")
def bills_summary_endpoint(
    days: int = Query(30),
    account_id: Optional[str] = Query(None),
):
    """Dashboard bill summary: counts and next bill due."""
    with get_db() as conn:
        summary = get_bills_summary(conn, days=days, account_id=account_id)
    return summary


# ── Forecast Endpoint ────────────────────────────────────────────────────────


@app.get("/api/forecast")
def cash_flow_forecast(
    months: int = Query(6, ge=1, le=24),
    history_months: int = Query(3, ge=1, le=12),
):
    """Project cash flow for the next N months.

    Uses recurring baselines + rolling historical average to project
    monthly income, spending, net, and running balance.
    """
    with get_db() as conn:
        forecast = get_cash_flow_forecast(
            conn, months=months, history_months=history_months
        )
    return forecast


# ── Alert Endpoints ──────────────────────────────────────────────────────────


@app.get("/api/alerts/rules")
def alert_rules_list():
    """List all configured alert rules."""
    with get_db() as conn:
        rules = dal_get_alert_rules(conn)
    return {"rules": rules}


@app.patch("/api/alerts/rules/{rule_id}")
def alert_rule_update(
    rule_id: str,
    enabled: Optional[bool] = Query(None),
    threshold: Optional[float] = Query(None),
):
    """Enable/disable an alert rule or update its threshold."""
    with get_db() as conn:
        rule = conn.execute(
            "SELECT id FROM alert_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        if not rule:
            raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
        if enabled is not None:
            set_rule_enabled(conn, rule_id, enabled)
        if threshold is not None:
            update_rule_threshold(conn, rule_id, threshold)
        conn.commit()
    return {"status": "updated", "rule_id": rule_id}


@app.get("/api/alerts/events")
def alert_events_list(
    limit: int = Query(50, le=200),
    rule_type: Optional[str] = Query(None),
):
    """List recently fired alert events."""
    with get_db() as conn:
        events = get_recent_alerts(conn, limit=limit, rule_type=rule_type)
    return {"events": events, "count": len(events)}


@app.post("/api/alerts/evaluate")
def alert_evaluate_now():
    """Manually trigger alert evaluation (normally runs after each refresh)."""
    with get_db() as conn:
        fired = evaluate_alerts(conn)
    return {"status": "complete", "fired": fired, "count": len(fired)}


# ── Report Endpoints ─────────────────────────────────────────────────────────


@app.get("/api/reports/spending")
def report_spending(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    account_id: Optional[str] = Query(None),
):
    """Spending breakdown by category for a date range."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_spending_by_category(conn, start_date, end_date, account_ids)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "categories": data,
        "total": round(sum(c["total_spent"] for c in data), 2),
    }


@app.get("/api/reports/cash-flow")
def report_cash_flow(
    months: int = Query(12, ge=1, le=60),
    account_id: Optional[str] = Query(None),
):
    """Monthly income vs. spending vs. net for the last N months."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_cash_flow_report(conn, months=months, account_ids=account_ids)
    return {"months": data, "count": len(data)}


@app.get("/api/reports/net-worth-history")
def report_net_worth_history(
    months: int = Query(24, ge=1, le=120),
):
    """Monthly net worth history: assets, liabilities, net."""
    with get_db() as conn:
        data = get_net_worth_history(conn, months=months)
    return {"history": data, "count": len(data)}


@app.get("/api/reports/category-trend")
def report_category_trend(
    category: str = Query(...),
    months: int = Query(12, ge=1, le=60),
    account_id: Optional[str] = Query(None),
):
    """Monthly spending trend for a specific category."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        data = get_category_trend(conn, category, months=months, account_ids=account_ids)
    return {"category": category, "trend": data}


@app.get("/api/reports/summary")
def report_period_summary(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    account_id: Optional[str] = Query(None),
):
    """High-level period summary: income, spending, net, top categories."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        summary = get_period_summary(conn, start_date, end_date, account_ids)
    return summary


@app.get("/api/export/transactions")
def export_transactions(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    account_id: Optional[str] = Query(None),
    institution_id: Optional[str] = Query(None),
):
    """Export transactions as CSV."""
    from fastapi.responses import Response

    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        csv_content = export_transactions_csv(
            conn,
            start_date=start_date,
            end_date=end_date,
            account_ids=account_ids,
            institution_id=institution_id,
        )
    filename = f"sentry_transactions_{start_date or 'all'}_to_{end_date or 'today'}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Owner Endpoints ──────────────────────────────────────────────────────────


@app.get("/api/owners")
def owners_list():
    """List all configured owners."""
    with get_db() as conn:
        owners = dal_list_owners(conn)
    return {"owners": owners}


@app.post("/api/owners")
def owners_create(owner_id: str = Query(...), display_name: str = Query(...)):
    """Create a new owner."""
    with get_db() as conn:
        create_owner(conn, owner_id, display_name)
        conn.commit()
    return {"status": "created", "owner_id": owner_id}


@app.patch("/api/accounts/{account_id}/owner")
def account_set_owner(account_id: str, owner_id: str = Query(None)):
    """Assign or clear an account's owner.

    Pass owner_id=null to make the account shared ("ours").
    """
    with get_db() as conn:
        # Verify account exists
        acct = conn.execute(
            "SELECT id FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if not acct:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        # Verify owner exists (if setting one)
        if owner_id:
            owner = conn.execute(
                "SELECT id FROM owners WHERE id = ?", (owner_id,)
            ).fetchone()
            if not owner:
                raise HTTPException(status_code=404, detail=f"Owner {owner_id} not found")

        assign_account_owner(conn, account_id, owner_id)
        conn.commit()
    return {"status": "updated", "account_id": account_id, "owner_id": owner_id}


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/api/health")
def health():
    """Health check endpoint."""
    with get_db() as conn:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
    return {
        "status": "ok",
        "schema_version": ver,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Savings Goals Endpoints ──────────────────────────────────────────────────────


@app.get("/api/goals")
def goals_list(
    owner_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """List savings goals with computed progress fields."""
    with get_db() as conn:
        goals = list_goals(conn, owner_id=owner_id, status=status)
    return {"goals": goals, "count": len(goals)}


@app.get("/api/goals/summary")
def goals_summary(
    owner_id: Optional[str] = Query(None),
):
    """Dashboard summary: total saved vs. target, trajectory counts."""
    with get_db() as conn:
        summary = get_goals_summary(conn, owner_id=owner_id)
    return summary


@app.get("/api/goals/{goal_id}")
def goal_detail(goal_id: int):
    """Get a single savings goal by ID."""
    with get_db() as conn:
        goal = get_goal(conn, goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    return goal


@app.post("/api/goals", status_code=201)
async def goal_create(request: Request):
    """Create a new savings goal."""
    body = await request.json()

    name = body.get("name")
    target_amount = body.get("target_amount")
    if not name or not target_amount:
        raise HTTPException(status_code=422, detail="name and target_amount are required")

    with get_db() as conn:
        goal_id = create_goal(
            conn,
            name=name,
            target_amount=float(target_amount),
            owner_id=body.get("owner_id"),
            current_amount=float(body.get("current_amount", 0)),
            deadline=body.get("deadline"),
            linked_account_id=body.get("linked_account_id"),
            notes=body.get("notes"),
        )
        goal = get_goal(conn, goal_id)
    return goal


@app.patch("/api/goals/{goal_id}/amount")
def goal_update_amount(
    goal_id: int,
    amount: float = Query(..., description="New current amount for the goal"),
):
    """Manually update the current saved amount for a goal."""
    with get_db() as conn:
        goal = get_goal(conn, goal_id)
        if not goal:
            raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
        result = update_goal_amount(conn, goal_id, amount)
    return result


@app.post("/api/goals/sync")
def goal_sync():
    """Sync all active goals with linked accounts from latest balance snapshots."""
    with get_db() as conn:
        updated = sync_goal_balances(conn)
    return {"status": "synced", "goals_updated": updated}


@app.delete("/api/goals/{goal_id}", status_code=204)
def goal_delete(goal_id: int):
    """Cancel (soft-delete) a savings goal."""
    with get_db() as conn:
        goal = get_goal(conn, goal_id)
        if not goal:
            raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
        delete_goal(conn, goal_id)


# ── Investment Performance Endpoints ────────────────────────────────────────────


@app.get("/api/investments/performance")
def investment_performance(
    account_id: Optional[str] = Query(None),
    period: str = Query("1y", enum=["1m", "3m", "6m", "1y", "2y", "3y", "ytd", "all"]),
    benchmark: str = Query("sp500", enum=["sp500", "total_market", "bonds"]),
):
    """Portfolio time-weighted return vs. benchmark.

    If account_id is omitted, returns performance for all investment accounts.
    """
    with get_db() as conn:
        if account_id:
            result = get_portfolio_performance(
                conn, account_id=account_id, period=period, benchmark=benchmark
            )
        else:
            result = get_all_accounts_performance(conn, period=period, benchmark=benchmark)
    return result


# ── Investment Allocation Endpoint ────────────────────────────────────────────────


@app.get("/api/investments/allocation")
def investment_allocation(
    account_id: Optional[str] = Query(None),
):
    """Sector, asset class, and account allocation for investment holdings."""
    account_ids = [account_id] if account_id else None
    with get_db() as conn:
        result = get_allocation(conn, account_ids=account_ids)
    return result


# ── Debt Payoff Endpoints ──────────────────────────────────────────────────────────


@app.get("/api/debt/summary")
def debt_summary():
    """Current liability snapshot: all debts, total owed, weighted average APR."""
    with get_db() as conn:
        summary = get_debt_summary(conn)
    return summary


@app.get("/api/debt/payoff")
def debt_payoff(
    extra_payment: float = Query(0.0, ge=0, description="Extra monthly payment above minimums"),
    strategy: str = Query("avalanche", enum=["avalanche", "snowball"]),
):
    """Debt payoff plan with avalanche vs. snowball comparison.

    Returns the requested strategy's schedule plus a side-by-side comparison
    showing interest and time savings.
    """
    with get_db() as conn:
        plan = get_payoff_plan(conn, extra_payment=extra_payment, strategy=strategy)
    return plan


# ── Run ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    from config.logging_config import setup_logging

    setup_logging()

    print("\n  🌐  Sentry Finance API")
    print("  📡  http://127.0.0.1:8000/docs")
    print()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
