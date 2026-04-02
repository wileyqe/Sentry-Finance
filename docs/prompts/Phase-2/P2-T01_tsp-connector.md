# P2-T01: TSP Connector with MFA Bridge

## Context

You are working on Sentry Finance, a local-first personal finance app.
The TSP (Thrift Savings Plan) account holds the single largest investment
position in the household portfolio (~10x the next largest account). It
currently gets data only from manually dropped PDF statements via
`scripts/ingest_tsp.py`. This means TSP data can be weeks or months stale.

The goal of this task is to build a Tier 2 (semi-automated) connector for
TSP that logs in via browser automation, handles MFA by routing it through
the dashboard UI (not the terminal), scrapes per-fund balances, and feeds
the data into the standard post-commit pipeline.

**Before writing a single line of code:** Navigate to my.tsp.gov in a real
browser and observe the actual login flow. Note the exact field IDs or
selectors for: username input, password input, submit button, MFA code
input, and MFA submit button. The UI may have changed and the selectors
in this prompt are best-guess approximations — your observed selectors
always take precedence.

---

## Architecture: How Connectors Work

Every connector extends `InstitutionConnector` from
`skills/institution_connector.py`. The lifecycle:

1. `_is_session_valid(page)` — navigate to export URL, return True if
   already authenticated
2. If not valid: `_perform_login(page, credentials)` — fill username/password
3. `_wait_for_mfa(page)` — poll until past login/MFA screens
4. `_trigger_export(page, accounts)` — scrape data, store in
   `self._result_balances` and `self._result_loan_details`, return files list

The orchestrator then calls `persist_connector_result(institution_id, result)`
and `run_post_commit_pipeline(institution_id)` in `backend/automation_worker.py`.

The connector registry is in `extractors/__init__.py`:
```python
CONNECTOR_REGISTRY: dict[str, callable] = {
    "nfcu":     lambda: _lazy("extractors.nfcu_connector",     "NFCUConnector"),
    # ...
    # "tsp":    lambda: _lazy("extractors.tsp_connector",      "TSPConnector"),  # commented out
}
```

---

## MFA Bridge Design

Unlike Tier 1 connectors (which use SMS OTP auto-capture or just wait for
user to complete MFA in the browser without a notification), TSP requires
an authenticator app code that the user must manually enter. Rather than
forcing the user to watch a terminal, the bridge:

1. **Connector side:** When it hits the MFA screen, calls
   `broadcast_event("mfa_required", {"institution": "tsp", "prompt": "Enter your TSP authenticator code"})`,
   then blocks on a `threading.Event` waiting for the code.

2. **API side:** New endpoint `POST /api/mfa/submit` accepts
   `{"institution": "tsp", "code": "123456"}`, stores the code in a
   module-level bridge, and signals the event.

3. **Frontend side:** The SSE stream already delivers all broadcast events.
   When a `mfa_required` event arrives with `institution: "tsp"`, show a
   modal/overlay with a 6-digit input field. On submit, POST to
   `/api/mfa/submit`. Dismiss the modal after submission.

The MFA bridge module (`backend/mfa_bridge.py`) is the thread-safe
intermediary. It holds a single pending code slot — only one MFA can be
active at a time (serial connector execution guarantees this).

---

## Starting State

### Files that exist (do NOT create, understand and extend):
- `skills/institution_connector.py` — base class
- `extractors/__init__.py` — connector registry (TSP entry commented out)
- `backend/events.py` — `broadcast_event(type, data)` function
- `backend/api_server.py` — router registration (must add mfa router)
- `scripts/ingest_tsp.py` — existing TSP PDF parser (reference for data model)
- `selector_registry.yaml` — CSS selectors per institution (add TSP section)
- `accounts.yaml` — account configs per institution (add TSP section)

### TSP account in the database:
- Account ID: `tsp_7777`
- Type: `retirement`
- Institution ID: `tsp`
- Funds held: L 2065, C Fund, S Fund (approximately)
- No new contributions (retired — balance changes only from market movement)

### What `ingest_tsp.py` persists (replicate this pattern):
```python
# balance_snapshots (total value)
record_balance(conn, "tsp_7777", total_value, now)

# portfolio_snapshots (total + cash)
conn.execute("""
    INSERT INTO portfolio_snapshots
        (account_id, timestamp, total_account_value, cash_balance)
    VALUES (?, ?, ?, ?)
""", ("tsp_7777", now, total_value, 0.0))
```

---

## Task

### 1. Create `backend/mfa_bridge.py`

Thread-safe MFA code exchange between the blocking connector thread and
the API endpoint handler:

```python
"""
backend/mfa_bridge.py — Thread-safe MFA code exchange.

Used by connectors that require interactive MFA codes during automation.
Only one MFA session can be active at a time (serial connector execution).
"""

import threading
import logging

log = logging.getLogger("sentry.backend.mfa_bridge")

_pending_event: threading.Event = threading.Event()
_pending_code: str | None = None
_pending_institution: str | None = None
_bridge_lock = threading.Lock()


def wait_for_code(institution: str, timeout_seconds: int = 300) -> str | None:
    """Block until a code is submitted for this institution, or timeout.

    Called from the connector thread. Returns the code or None on timeout.
    """
    global _pending_institution, _pending_code
    with _bridge_lock:
        _pending_institution = institution
        _pending_code = None
        _pending_event.clear()

    log.info("MFA bridge: waiting for code for %s (timeout=%ds)", institution, timeout_seconds)
    got_it = _pending_event.wait(timeout=timeout_seconds)

    with _bridge_lock:
        code = _pending_code
        _pending_institution = None
        _pending_code = None

    if not got_it:
        log.warning("MFA bridge: timeout waiting for %s code", institution)
        return None

    log.info("MFA bridge: code received for %s", institution)
    return code


def submit_code(institution: str, code: str) -> bool:
    """Submit a code from the API endpoint. Returns False if wrong institution."""
    global _pending_code
    with _bridge_lock:
        if _pending_institution != institution:
            log.warning(
                "MFA bridge: submitted code for %s but waiting for %s",
                institution, _pending_institution
            )
            return False
        _pending_code = code
        _pending_event.set()
    return True


def is_pending(institution: str | None = None) -> bool:
    """Return True if an MFA code is currently being awaited."""
    with _bridge_lock:
        if institution is None:
            return _pending_institution is not None
        return _pending_institution == institution
```

### 2. Create `backend/routers/mfa.py`

```python
"""MFA bridge API endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.mfa_bridge import submit_code, is_pending

router = APIRouter(tags=["mfa"])


class MFASubmit(BaseModel):
    institution: str
    code: str


@router.post("/api/mfa/submit")
def submit_mfa_code(body: MFASubmit):
    """Submit an MFA code from the dashboard UI to the waiting connector."""
    if not is_pending(body.institution):
        raise HTTPException(
            status_code=409,
            detail=f"No MFA is currently pending for '{body.institution}'."
        )
    success = submit_code(body.institution, body.code)
    if not success:
        raise HTTPException(status_code=409, detail="Institution mismatch.")
    return {"status": "accepted"}


@router.get("/api/mfa/status")
def mfa_status():
    """Check whether an MFA code is currently being awaited."""
    return {"pending": is_pending(), "institution": None}
    # Note: intentionally doesn't expose which institution to keep it simple.
    # Frontend learns the institution from the SSE mfa_required event.
```

### 3. Register the MFA router in `backend/api_server.py`

Add the import and `app.include_router(mfa.router)`:

```python
from backend.routers import (
    accounts,
    transactions,
    refresh,
    budgets,
    recurring,
    alerts,
    reports,
    goals,
    investments,
    cash_flow,
    user_rules,
    freshness,
    mfa,         # ← add this
)

# ...

app.include_router(mfa.router)   # ← add this
```

### 4. Create `extractors/tsp_connector.py`

**Before writing selectors:** Browse my.tsp.gov and observe:
- The login URL (likely `https://my.tsp.gov/` or `/tsp/login/`)
- Username field selector
- Password field selector
- Submit button selector
- Post-login: MFA screen vs. landing on account overview
- If MFA required: the code input field selector and submit selector
- Account overview page: where the total balance and per-fund breakdown live

Structure:

```python
"""
extractors/tsp_connector.py — TSP Tier 2 connector with MFA bridge.

Tier 2: logs in automatically but pauses at MFA and routes the code
request through the dashboard SSE stream + API endpoint. Session reuse
via persistent browser profile minimizes MFA frequency.

Account: TSP Uniformed Services (7777)
Institution ID: tsp
"""

import logging
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from skills.institution_connector import InstitutionConnector, AccountConfig
from backend.events import broadcast_event
from backend.mfa_bridge import wait_for_code
from dal.database import get_db
from dal.balances import record_balance

log = logging.getLogger("sentry.extractors.tsp")

TSP_LOGIN_URL = "https://my.tsp.gov/"          # Verify this before deploying
TSP_ACCOUNT_URL = "https://my.tsp.gov/tsp/acctoverview.do"   # Verify


class TSPConnector(InstitutionConnector):

    @property
    def institution(self) -> str:
        return "tsp"

    @property
    def display_name(self) -> str:
        return "Thrift Savings Plan"

    @property
    def export_url(self) -> str:
        return TSP_ACCOUNT_URL

    @property
    def login_url(self) -> str:
        return TSP_LOGIN_URL

    def _perform_login(self, page: Page, credentials: dict | None = None) -> bool:
        """Navigate to login page, fill credentials, submit."""
        page.goto(self.login_url, wait_until="domcontentloaded", timeout=30000)
        # TODO: fill in verified selectors from tsp.gov
        # username_sel = "#username"  # verify
        # password_sel = "#password"  # verify
        # submit_sel = "button[type=submit]"  # verify
        ...
        return True

    def _wait_for_mfa(self, page: Page, timeout_seconds: int = 300) -> bool:
        """Override base MFA wait to route through SSE bridge instead of terminal."""
        # Check if we're already past MFA
        if self._is_post_login(page):
            return True

        # Detect whether we're on an MFA screen
        # TODO: adjust selector to actual TSP MFA code input field
        mfa_sel = "input[name='code'], input[id*='otp'], input[id*='mfa'], input[autocomplete='one-time-code']"
        try:
            page.wait_for_selector(mfa_sel, timeout=5000)
        except PlaywrightTimeout:
            # Not on an MFA screen — might already be past it
            if self._is_post_login(page):
                return True
            log.warning("[tsp] Expected MFA screen but didn't find it; proceeding")
            return False

        # Signal the dashboard that we need a code
        broadcast_event("mfa_required", {
            "institution": "tsp",
            "prompt": "Enter your TSP authenticator app code to continue."
        })
        log.info("[tsp] MFA bridge activated — waiting for code from dashboard")

        # Block until the user submits a code via /api/mfa/submit
        code = wait_for_code("tsp", timeout_seconds=timeout_seconds)
        if code is None:
            log.error("[tsp] MFA bridge timed out — no code received")
            return False

        # Fill the code and submit
        # TODO: adjust to actual TSP MFA selectors
        mfa_input = page.query_selector(mfa_sel)
        if mfa_input:
            mfa_input.fill(code)
        submit = page.query_selector("button[type=submit], input[type=submit]")
        if submit:
            submit.click()

        # Wait for the MFA screen to disappear
        try:
            page.wait_for_function(
                "() => !document.querySelector('input[autocomplete=\"one-time-code\"]')",
                timeout=15000
            )
        except PlaywrightTimeout:
            pass

        return self._is_post_login(page)

    def _is_post_login(self, page: Page) -> bool:
        """TSP-specific post-login detection."""
        url = page.url.lower()
        # TSP shows account overview after login
        if "acctoverview" in url or "accountoverview" in url:
            return True
        # Fall back to base detection
        return super()._is_post_login(page)

    def _trigger_export(self, page: Page, accounts: list[AccountConfig]) -> list[Path]:
        """Scrape TSP account overview for total balance and per-fund breakdown."""
        # Navigate to account overview if not already there
        if "acctoverview" not in page.url.lower():
            page.goto(self.export_url, wait_until="domcontentloaded", timeout=30000)

        total_balance = self._scrape_total_balance(page)
        fund_positions = self._scrape_fund_positions(page)

        if total_balance is None or total_balance <= 0:
            log.error("[tsp] Could not read total balance — aborting")
            return []

        self._persist_tsp_data(total_balance, fund_positions)
        return []   # No files downloaded; data written directly

    def _scrape_total_balance(self, page: Page) -> float | None:
        """Extract total account value from the overview page.

        TODO: verify selector against actual tsp.gov DOM.
        Common patterns:
          - A table cell labeled 'Total Account Balance' or 'Account Balance'
          - A heading or span with the dollar amount
        """
        # Try several selector strategies; return first match
        strategies = [
            # Strategy 1: explicit 'Total Account Balance' label
            lambda: page.inner_text(".accountBalance, #totalBalance, [data-account-balance]"),
            # Strategy 2: table row with 'Total' text
            lambda: page.eval_on_selector(
                "td:has-text('Total') + td, tr:has-text('Total Account Balance') td:last-child",
                "el => el.innerText"
            ),
        ]
        for strategy in strategies:
            try:
                raw = strategy()
                if raw:
                    return self._parse_dollar(raw)
            except Exception:
                continue
        log.warning("[tsp] Could not scrape total balance")
        return None

    def _scrape_fund_positions(self, page: Page) -> dict[str, dict]:
        """Extract per-fund units and values.

        Returns: {"L 2065": {"units": 1830.0, "balance": 36901.55}, ...}

        TODO: verify against actual tsp.gov DOM structure.
        The fund breakdown is typically in a table on the overview page.
        """
        positions = {}
        try:
            # Navigate to fund details if not on the right page
            # TSP often has 'Fund Balance Details' section or link
            rows = page.query_selector_all("table.fundBalance tr, table#fundDetails tr")
            for row in rows:
                cells = row.query_selector_all("td")
                if len(cells) >= 2:
                    fund_name = cells[0].inner_text().strip()
                    balance_text = cells[-1].inner_text().strip()
                    if fund_name and balance_text:
                        balance = self._parse_dollar(balance_text)
                        if balance and balance > 0:
                            positions[fund_name] = {"balance": balance, "units": 0.0}
        except Exception as e:
            log.warning("[tsp] Fund position scrape failed: %s", e)
        return positions

    def _persist_tsp_data(self, total_balance: float, fund_positions: dict) -> None:
        """Write balance and portfolio snapshots to the database."""
        now = datetime.utcnow().isoformat()
        with get_db() as conn:
            record_balance(conn, "tsp_7777", total_balance, now)
            conn.execute(
                """
                INSERT INTO portfolio_snapshots
                    (account_id, timestamp, total_account_value, cash_balance)
                VALUES (?, ?, ?, ?)
                """,
                ("tsp_7777", now, total_balance, 0.0),
            )
            conn.commit()
        log.info("[tsp] Persisted TSP balance: $%.2f", total_balance)
        for fund, data in fund_positions.items():
            log.info("[tsp]   %s: $%.2f", fund, data.get("balance", 0))

    @staticmethod
    def _parse_dollar(text: str) -> float:
        """Parse a dollar string like '$36,901.55' to float."""
        import re
        cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
```

### 5. Register TSP in `extractors/__init__.py`

Uncomment the TSP entry:
```python
"tsp":    lambda: _lazy("extractors.tsp_connector", "TSPConnector"),
```

Also add to `__all__`:
```python
from extractors.tsp_connector import TSPConnector  # noqa: E402, F401
```

### 6. Add TSP to `selector_registry.yaml`

Add a `tsp:` section with the selectors you observe during your manual
browse of my.tsp.gov. Use the same YAML structure as other institutions.

### 7. Add TSP to `accounts.yaml`

```yaml
tsp:
  - name: "TSP Uniformed Services"
    last4: "7777"
    type: retirement
    export:
      balance: true
      transactions: false
```

### 8. Add MFA overlay to frontend SSE handler

Find where the frontend handles SSE events (look for `EventSource` usage
or a custom SSE hook, likely in `frontend/src/lib/` or a component that
subscribes to `/api/refresh/events`).

When a `mfa_required` event arrives:
- Show a modal/overlay (not a toast — this needs user input, not just a notification)
- Display: "TSP is requesting your authenticator code"
- 6-digit numeric input field (maxLength=6, pattern="[0-9]*", autoFocus)
- Submit button: "Submit Code"
- On submit: `POST /api/mfa/submit` with `{institution: event.data.institution, code: enteredCode}`
- Dismiss modal on success response

If no existing modal component fits, create a simple one:
`frontend/src/components/MFAModal.tsx`

The modal must be rendered from a component that's always present
(e.g., the app root layout), so it's available regardless of which
page is active.

---

## Files to Create

1. `backend/mfa_bridge.py` — thread-safe MFA code exchange
2. `backend/routers/mfa.py` — API endpoints
3. `extractors/tsp_connector.py` — TSP connector
4. `frontend/src/components/MFAModal.tsx` — MFA input overlay

## Files to Modify

5. `backend/api_server.py` — register mfa router
6. `extractors/__init__.py` — uncomment TSP, add import
7. `selector_registry.yaml` — add `tsp:` section
8. `accounts.yaml` — add `tsp:` section
9. Frontend SSE handler — add `mfa_required` event listener and render `<MFAModal />`

## Files NOT to Modify

- `skills/institution_connector.py` — base class is correct as-is
- `backend/events.py` — no changes needed
- `scripts/ingest_tsp.py` — separate script, still useful for initial backfill
- Any existing connector files
- Database migrations — no schema changes needed for the connector itself

---

## Constraints

- The connector MUST follow the `InstitutionConnector` lifecycle contract:
  never close the browser, never spawn threads/subprocesses from `_trigger_export`
- MFA timeout is 300 seconds — if the user doesn't respond, the connector
  returns `ConnectorResult("tsp", "error", error="MFA timeout")`
- Session reuse is critical: once logged in successfully, the persistent
  profile should remain authenticated for days. Don't force re-login.
- If TSP doesn't show a MFA screen (session is still valid), the connector
  should complete without touching the MFA bridge at all
- Write data ONLY to `balance_snapshots` and `portfolio_snapshots` —
  do NOT write fake transactions; TSP has no spendable transactions
- The `_persist_tsp_data` method uses `with get_db()` directly because TSP
  data doesn't go through the standard file-based `result_writer.py` path
  (no CSV files to parse). The `result_writer` will be called separately
  by `automation_worker.py` with the `ConnectorResult` but since
  `result.files` is empty, it won't re-persist anything.
  Actually: store the total balance in `self._result_balances` so
  `result_writer.py` can handle it via the standard path. The direct
  `get_db()` call in `_persist_tsp_data` is a fallback only.

  Preferred approach: populate `self._result_balances` dict from
  `_trigger_export` so `automation_worker` / `result_writer` handles
  persistence via the standard path:
  ```python
  self._result_balances["7777"] = {
      "name": "TSP Uniformed Services",
      "balance": total_balance,
      "type": "retirement",
  }
  ```
  Then remove the direct DB write from the connector — let the pipeline handle it.

---

## Done Checklist

- [ ] `backend/mfa_bridge.py` created with `wait_for_code`, `submit_code`, `is_pending`
- [ ] `backend/routers/mfa.py` created with `POST /api/mfa/submit` and `GET /api/mfa/status`
- [ ] MFA router registered in `backend/api_server.py`
- [ ] `extractors/tsp_connector.py` created, extends `InstitutionConnector`
- [ ] TSP connector registered in `extractors/__init__.py` (uncommented, imported)
- [ ] TSP added to `selector_registry.yaml` and `accounts.yaml`
- [ ] Selectors verified against actual my.tsp.gov DOM (not guessed)
- [ ] `_wait_for_mfa` overridden to use `broadcast_event` + `wait_for_code`
- [ ] `_trigger_export` scrapes balance and populates `self._result_balances`
- [ ] `frontend/src/components/MFAModal.tsx` created
- [ ] MFAModal rendered in app root layout
- [ ] Frontend SSE handler listens for `mfa_required` and shows MFAModal
- [ ] Frontend submits code to `POST /api/mfa/submit`

## Verification

After completion, Claude will:
1. Read `backend/mfa_bridge.py` — verify thread safety (lock guards all shared state)
2. Read `backend/routers/mfa.py` — verify endpoints and error cases
3. Read `extractors/tsp_connector.py` — verify lifecycle contract adherence,
   MFA bridge integration, `self._result_balances` populated
4. Verify `extractors/__init__.py` TSP entry is uncommented and imported
5. Read `MFAModal.tsx` — verify it posts to correct endpoint and dismisses
6. Run import check: `python -c "from extractors.tsp_connector import TSPConnector; print('OK')"`
7. Run: `python -c "from backend.mfa_bridge import wait_for_code, submit_code; print('OK')"`
8. Run: `python -c "from backend.routers.mfa import router; print('OK')"`
